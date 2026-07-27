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
from dataclasses import dataclass
from typing import Optional

# Wave V1: the vocabulary and the decision now live in the kernel so briefs, profiles and
# caches share one dialect (J5 — this module was written to be lifted). Re-exported here,
# so every existing importer of ChangeClass / StalenessState / FreshnessVerdict keeps
# working and gets the *same* types, not look-alikes.
from aughor.kernel.freshness import (  # noqa: F401  (re-export)
    ChangeClass,
    FreshnessVerdict,
    StalenessState,
    classify_fingerprints,
)


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


def _structural_and_per_table(ontology) -> tuple[str, dict[str, str]]:
    """Both structural fingerprints in ONE pass over the entities.

    ``classify`` needs the aggregate *and* the per-table map; computing them separately
    hashed every entity twice. Same bytes, one pass.
    """
    per = table_fingerprints(ontology)
    joined = "|".join(f"{k}={per[k]}" for k in sorted(per))
    return hashlib.md5(joined.encode()).hexdigest()[:16], per


def structural_fingerprint(ontology) -> str:
    """One aggregate structural hash over the whole ontology (tables + columns + types)."""
    return _structural_and_per_table(ontology)[0]


def classify(prev_graph, cur_ontology) -> FreshnessVerdict:
    """Compare a committed graph against the current ontology and decide the refresh
    class + staleness. Pure and deterministic.

    - no current ontology  → unknown (can't compare; don't touch the graph)
    - no committed graph    → full / stale (first build)
    - structure identical, data identical → skip / fresh
    - structure identical, data moved     → skip / DIRTY  (nightly reload: no rebuild)
    - structure moved, same table set     → partial / stale  (+ changed tables)
    - structure moved, table set changed  → full / stale

    Wave V1: the decision itself is :func:`aughor.kernel.freshness.classify_fingerprints`
    — this function is now the *extraction* half (pulling the two fingerprints and the
    per-table map out of a graph + ontology), which is the only ontology-specific part.
    The two domain-worded reasons are passed through so the verdicts are unchanged.
    """
    cur_struct, cur_units = (
        _structural_and_per_table(cur_ontology) if cur_ontology is not None else (None, None)
    )
    return classify_fingerprints(
        prev_structural=(prev_graph.structural_fingerprint or "") if prev_graph is not None else None,
        prev_data=(prev_graph.schema_fingerprint or "") if prev_graph is not None else None,
        cur_structural=cur_struct,
        cur_data=(getattr(cur_ontology, "schema_fingerprint", "") or "") if cur_ontology is not None else None,
        prev_units=dict(prev_graph.table_fingerprints or {}) if prev_graph is not None else None,
        cur_units=cur_units,
        absent_current_reason="no current ontology to compare",
        absent_prior_reason="no committed graph yet (first build)",
    )


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
    reindex: bool = True, force: bool = False,
) -> Optional[RefreshResult]:
    """Refresh a connection's graph at cost proportional to the change: SKIP does no
    work; PARTIAL/FULL rebuild the deterministic projection (and re-embed for search).
    Returns None only when ``graph.freshness`` is off and ``force`` was not asked for.
    Best-effort throughout — a refresh never raises into a live path.

    ``force`` exists because the classifier compares *schema* fingerprints, and the
    graph has narrative sources too: an exploration run can discover a dozen findings
    without touching a single column, and would classify SKIP. A caller that KNOWS its
    sources moved says so, and gets the rebuild plus the re-index. It bypasses the
    ``graph.freshness`` gate as well — that flag governs change *classification*, and a
    forced caller is not asking for a classification. The write itself stays gated by
    ``graph.build`` inside the builder, so flag-off is still byte-identical.
    """
    if not freshness_enabled() and not force:
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

        if not verdict.needs_rebuild and not force:
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
