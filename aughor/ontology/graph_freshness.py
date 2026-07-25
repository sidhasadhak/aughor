"""Freshness for the connection knowledge graph — Wave C3.

Two fingerprints, deliberately split:

  * **structural** — tables + columns + types, and NOTHING data-dependent. A comment
    change or a nightly reload leaves it identical.
  * **data** — the ontology's own ``schema_fingerprint``, which folds in ``row_count``,
    so it moves on every reload.

The split is what lets the change-classifier be honest: a nightly data load is NOT a
schema change and must not trigger a rebuild (it marks the graph *dirty*, not *stale*);
a column add re-profiles only its table (PARTIAL); a new/dropped table re-clusters (FULL).
This vocabulary — ``fresh | dirty | stale | unknown`` and the SKIP/PARTIAL/FULL classes —
is written to be **lifted by Wave V** (J5): one staleness dialect for graph, briefs,
profiles, and caches, not four.

Nothing here calls the LLM. Refresh cost is proportional to the change: SKIP touches
nothing (no rebuild, no re-embed); PARTIAL/FULL rebuild the deterministic projection.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal, Optional

# Refresh action a change implies.
ChangeClass = Literal["skip", "partial", "full", "unknown"]
# How trustworthy the committed graph is against the live schema+data right now.
StalenessState = Literal["fresh", "dirty", "stale", "unknown"]


def _bare(t: str) -> str:
    return str(t).rsplit(".", 1)[-1].strip().strip('"').lower()


def _entity_struct(ent) -> str:
    """The structural signature of one entity: its tables and its (column, type) set,
    sorted so it is order-independent. Row counts and sample values are deliberately
    excluded — they are DATA, not structure."""
    tables = sorted(_bare(t) for t in (getattr(ent, "source_tables", []) or []))
    cols = sorted(
        f"{p.name.lower()}:{(getattr(p, 'data_type', '') or '').lower()}"
        for p in (getattr(ent, "properties", {}) or {}).values()
    )
    return "|".join(tables) + "#" + ",".join(cols)


def table_fingerprints(ontology) -> dict[str, str]:
    """Per-entity structural fingerprint → {entity_id: hash}. Keyed by entity id (the
    graph's table unit) so PARTIAL can name exactly which tables' structure moved."""
    out: dict[str, str] = {}
    for eid, ent in (getattr(ontology, "entities", {}) or {}).items():
        out[eid] = hashlib.md5(_entity_struct(ent).encode()).hexdigest()[:16]
    return out


def structural_fingerprint(ontology) -> str:
    """One aggregate structural hash over the whole ontology (tables + columns + types)."""
    per = table_fingerprints(ontology)
    joined = "|".join(f"{k}={per[k]}" for k in sorted(per))
    return hashlib.md5(joined.encode()).hexdigest()[:16]


@dataclass
class FreshnessVerdict:
    change: ChangeClass          # what refresh should DO
    staleness: StalenessState    # how the committed graph reads RIGHT NOW
    changed_tables: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def needs_rebuild(self) -> bool:
        return self.change in ("partial", "full")


def classify(prev_graph, cur_ontology) -> FreshnessVerdict:
    """Compare a committed graph against the current ontology and decide the refresh
    class + staleness. Pure and deterministic.

    - no current ontology  → unknown (can't compare; don't touch the graph)
    - no committed graph    → full / stale (first build)
    - structure identical, data identical → skip / fresh
    - structure identical, data moved     → skip / DIRTY  (nightly reload: no rebuild)
    - structure moved, same table set     → partial / stale  (+ changed tables)
    - structure moved, table set changed  → full / stale
    """
    if cur_ontology is None:
        return FreshnessVerdict("unknown", "unknown", reason="no current ontology to compare")
    if prev_graph is None:
        return FreshnessVerdict("full", "stale", reason="no committed graph yet (first build)")

    cur_struct = structural_fingerprint(cur_ontology)
    cur_data = getattr(cur_ontology, "schema_fingerprint", "") or ""
    prev_struct = prev_graph.structural_fingerprint or ""
    prev_data = prev_graph.schema_fingerprint or ""

    if cur_struct == prev_struct:
        if cur_data == prev_data:
            return FreshnessVerdict("skip", "fresh", reason="structure and data unchanged")
        # A reload / backfill: the structure the graph encodes is still correct, but the
        # findings and profiles rest on data that moved. Surface it; do NOT rebuild.
        return FreshnessVerdict("skip", "dirty",
                                reason="data moved (row counts changed); structure unchanged")

    # Structure changed — is it a column-level change to known tables (partial) or a
    # table set change (full)?
    cur_tables = table_fingerprints(cur_ontology)
    prev_tables = dict(prev_graph.table_fingerprints or {})
    added = set(cur_tables) - set(prev_tables)
    removed = set(prev_tables) - set(cur_tables)
    changed = [t for t in cur_tables if t in prev_tables and cur_tables[t] != prev_tables[t]]

    if added or removed:
        return FreshnessVerdict("full", "stale", changed_tables=sorted(changed),
                                reason=f"tables added={sorted(added)} removed={sorted(removed)}")
    return FreshnessVerdict("partial", "stale", changed_tables=sorted(changed),
                            reason=f"columns changed on {sorted(changed)}")


@dataclass
class RefreshResult:
    verdict: FreshnessVerdict
    rebuilt: bool
    indexed: int = 0


def freshness_enabled() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled("graph.freshness")


def refresh_context_graph(
    connection_id: str, schema_name: Optional[str] = None, *, org_id: str = "",
    reindex: bool = True,
) -> Optional[RefreshResult]:
    """Refresh a connection's graph at cost proportional to the change: SKIP does no
    work; PARTIAL/FULL rebuild the deterministic projection (and re-embed for search).
    Returns None only when ``graph.freshness`` is off. Best-effort throughout — a
    refresh never raises into a live path."""
    if not freshness_enabled():
        return None
    from aughor.kernel.errors import tolerate
    from aughor.org.context import current_org_id
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    from aughor.ontology.context_graph_search import merge_graphs

    org = org_id or current_org_id()
    try:
        from aughor.ontology.store import load_latest_ontology
        cur_ontology = load_latest_ontology(connection_id, schema_name)
        prev = merge_graphs(load_graphs_for_connection(org, connection_id))
        verdict = classify(prev, cur_ontology)

        if not verdict.needs_rebuild:
            return RefreshResult(verdict=verdict, rebuilt=False)

        from aughor.ontology.context_graph_build import build_context_graph
        cg = build_context_graph(connection_id, schema_name, org_id=org, persist=True)
        if cg is None:
            # graph.build is off — record the verdict but nothing was built.
            return RefreshResult(verdict=verdict, rebuilt=False)
        indexed = 0
        if reindex:
            try:
                from aughor.ontology.context_graph_search import index_graph
                indexed = index_graph(cg)
            except Exception as exc:
                tolerate(exc, "graph re-index after refresh is best-effort; the committed "
                              "artifact is still fresh and the lexical floor still searches",
                         counter="context_graph.refresh_reindex")
        return RefreshResult(verdict=verdict, rebuilt=True, indexed=indexed)
    except Exception as exc:
        tolerate(exc, "context-graph refresh is best-effort", counter="context_graph.refresh")
        return RefreshResult(verdict=FreshnessVerdict("unknown", "unknown", reason=str(exc)),
                             rebuilt=False)


def staleness_of(connection_id: str, schema_name: Optional[str] = None, *, org_id: str = "") -> StalenessState:
    """The current staleness state of a connection's committed graph (for a UI banner /
    briefing gate). ``unknown`` when nothing is built or the ontology can't be read."""
    from aughor.org.context import current_org_id
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    from aughor.ontology.context_graph_search import merge_graphs
    try:
        from aughor.ontology.store import load_latest_ontology
        org = org_id or current_org_id()
        prev = merge_graphs(load_graphs_for_connection(org, connection_id))
        if prev is None:
            return "unknown"
        return classify(prev, load_latest_ontology(connection_id, schema_name)).staleness
    except Exception:
        return "unknown"
