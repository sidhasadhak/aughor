"""Build orchestration for the connection knowledge graph — Wave C1.

Gathers the deterministic sources (the built ontology, the merged glossary, the
crystallized ambiguity resolutions, the discovered findings) and hands them to the
pure projection in :mod:`aughor.ontology.context_graph`, then persists the committed
artifact. Every source read is best-effort: one empty or unavailable store degrades
that slice of the graph, never the whole build.

Gated behind ``graph.build`` (default off) so ``main`` is byte-identical until the
flag flips — C1 writes the artifact but nothing reads it back until C2.
"""
from __future__ import annotations

from typing import Callable, Optional

from aughor.kernel.errors import tolerate
from aughor.kernel.flags import flag_enabled
from aughor.org.context import current_org_id
from aughor.ontology.context_graph import ContextGraph, project_graph


def _safe(fn: Callable, what: str, default):
    """Run a source read, returning ``default`` (never raising) on failure so a
    single unavailable store can't sink the build."""
    try:
        return fn()
    except Exception as exc:
        tolerate(exc, f"context-graph source '{what}' is best-effort",
                 counter="context_graph.source_read")
        return default


def load_findings(connection_id: str) -> list[dict]:
    """Normalize the connection's discovered findings into the projection's finding
    shape ``{id, text, sql, tables, source, generated_at}``. Enumerated from the
    exploration store (conn-scoped, the enumerable source) and marked ``source=
    "dossier"`` when the finding carries a captured dossier in the Ledger — the
    write-only half of the open loop, finally a graph node."""
    from aughor.explorer.store import get_insights
    from aughor.explorer.scope import tables_in_sql

    out: list[dict] = []
    for ins in get_insights(connection_id):
        fid = str(ins.get("id") or "")
        text = str(ins.get("finding") or "")
        if not fid or not text:
            continue
        sql = str(ins.get("sql") or "")
        tables = sorted(tables_in_sql(sql)) if sql else []
        source = "dossier" if _has_dossier(connection_id, fid) else "exploration"
        out.append({
            "id": fid,
            "text": text,
            "sql": sql,
            "tables": tables,
            "source": source,
            "generated_at": ins.get("generated_at", ""),
        })
    return out


def _has_dossier(connection_id: str, insight_id: str) -> bool:
    """True iff a captured dossier artifact exists for this finding (the derivation
    the CEO-'how was this derived?' path renders). Best-effort — a Ledger miss just
    means the finding is sourced as a plain exploration insight."""
    try:
        from aughor.kernel.ledger import Ledger
        art = Ledger.default().artifact_latest(f"insight:{connection_id}:{insight_id}")
        return bool(art and (art.get("payload") or {}).get("dossier"))
    except Exception:
        return False


def build_context_graph(
    connection_id: str,
    schema_name: Optional[str] = None,
    *,
    org_id: Optional[str] = None,
    persist: bool = True,
) -> Optional[ContextGraph]:
    """Build (and, by default, persist) the connection knowledge graph.

    Returns ``None`` when the flag is off (byte-identical: nothing read, nothing
    written) or when the connection has no built ontology yet — the graph is a
    projection *of* the ontology, so it cannot precede it.
    """
    if not flag_enabled("graph.build"):
        return None

    from aughor.ontology.store import load_latest_ontology

    resolved_org = org_id or current_org_id()
    ontology = _safe(lambda: load_latest_ontology(connection_id, schema_name),
                     "ontology", None)
    if ontology is None:
        return None

    merged_glossary = _safe(_load_glossary, "glossary", {})
    resolutions = _safe(
        lambda: _list_resolutions(connection_id, resolved_org), "ambiguity_ledger", [])
    findings = _safe(lambda: load_findings(connection_id), "findings", [])

    cg = project_graph(
        ontology,
        org_id=resolved_org,
        connection_id=connection_id,
        schema_name=schema_name or getattr(ontology, "schema_name", "") or "",
        merged_glossary=merged_glossary,
        resolutions=resolutions,
        findings=findings,
    )

    if persist:
        try:
            from aughor.ontology.context_graph_store import save_graph
            save_graph(cg)
        except Exception as exc:
            tolerate(exc, "context-graph persistence is best-effort; the built graph "
                          "is still returned to the caller",
                     counter="context_graph.persist")
    return cg


def _load_glossary() -> dict:
    """The merged glossary as the projection wants it: a ``{table: meta}`` mapping.

    ``load_merged_glossary`` returns the *envelope* ``{"tables": {table: meta}}``, and
    the projection iterates its argument as table→meta. Handing over the envelope made
    the loop run exactly once, on the literal key ``"tables"``, which then failed the
    connection-scope check — so every glossary term on every connection was silently
    dropped and the ``defines`` edge kind was unreachable. Unwrap here, at the boundary
    that knows the store's shape.
    """
    from aughor.semantic.glossary import load_merged_glossary
    merged = load_merged_glossary() or {}
    return merged.get("tables", merged)


def _list_resolutions(connection_id: str, org_id: str) -> list:
    from aughor.semantic.ambiguity_ledger import list_resolutions
    return list_resolutions(connection_id, org_id)
