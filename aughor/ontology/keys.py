"""Arc OC-3 — one contract: the stores that carry meaning, keyed to the ontology's ids (ROADMAP §3.56).

The study that opened Arc OC found meaning kept in about nine stores keyed to tables and columns — the metric registry,
the glossary, the vocabulary, trusted queries, column config, monitors, cards, automation triggers and the Record. The
ontology names the business; those stores did not point at it, so a release could only guess what a change touched,
and nothing could read an approved metric as *the* measure of an entity's objects.

This module starts with the store that already half-carries the key: a metric's grain names its table. For each metric
it proposes the entity it measures — from the grain's table, else the one entity its tables (or its statement's FROM)
are backed by — and says why, or why none could be chosen. A proposal is never stored and nothing reads it as the
metric's meaning: a person confirms the entity through `PUT /metrics/{name}/entity`, and only then is the metric keyed
(`MetricDefinition.entity`). `keyed_counts` is the census's reading of how far every store is keyed — the arc's OC-3
receipt is that share moving from its baseline of zero.
"""
from __future__ import annotations

from typing import Any


def _bare(table: str) -> str:
    return str(table or "").strip().strip("`\"").lower().rsplit(".", 1)[-1]


def _grain_table(m: Any) -> str:
    """The table a metric's grain names — `order_items.created_at` and `thelook.order_items.created_at` both name
    `order_items`; a bare column names none."""
    parts = [p for p in str(getattr(m, "time_column", "") or "").strip().split(".") if p]
    return _bare(parts[-2]) if len(parts) >= 2 else ""


def _grain_column(m: Any) -> str:
    parts = [p for p in str(getattr(m, "time_column", "") or "").strip().split(".") if p]
    return parts[-1] if parts else ""


def _parsed(sql: str, dialect: Any):
    import sqlglot
    try:
        return sqlglot.parse_one(sql or "", read=dialect)
    except Exception:  # noqa: BLE001 — an expression-only metric (`COUNT(id)`) is not a statement
        return None


def statement_tables(sql: str) -> set[str]:
    """The tables a metric's statement reads, by parsing it — CTE names are not tables. Empty when it does not parse.
    Backticked names parse as BigQuery; anything else as the default dialect."""
    from sqlglot import exp
    tree = _parsed(sql, "bigquery") or _parsed(sql, None)
    if tree is None:
        return set()
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {_bare(t.name) for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in ctes}


def _entity_of(graph: Any, table: str) -> str:
    if not table:
        return ""
    for t, eid in (graph.table_to_entity or {}).items():
        if _bare(t) == table:
            return eid
    for eid, e in graph.entities.items():
        if any(_bare(s) == table for s in e.source_tables):
            return eid
    return ""


def propose_metric_entity(m: Any, graph: Any) -> dict:
    """``{entity, property, why, candidates}`` — the entity a metric measures, as its own declaration says it: the
    grain's table first (the table a range filters, so the objects that are counted), else the one entity every table
    it names — or its statement reads — is backed by. ``entity`` is "" when none can be chosen, with why."""
    if graph is None:
        return {"entity": "", "property": "", "why": "no ontology is built for this scope", "candidates": []}
    grain = _grain_table(m)
    entity = _entity_of(graph, grain)
    if entity:
        column = _grain_column(m)
        prop = column if column in (graph.entities[entity].properties or {}) else ""
        return {"entity": entity, "property": prop, "candidates": [entity],
                "why": f"its grain, {m.time_column}, is a date of {entity}'s table {grain}"}
    tables = {_bare(t) for t in (getattr(m, "tables", None) or []) if t} or statement_tables(getattr(m, "sql", ""))
    backed = sorted({e for e in (_entity_of(graph, t) for t in tables) if e})
    if len(backed) == 1:
        source = "the table it names" if getattr(m, "tables", None) else "the table its statement reads"
        column = _grain_column(m)
        prop = column if column in (graph.entities[backed[0]].properties or {}) else ""
        return {"entity": backed[0], "property": prop, "candidates": backed,
                "why": f"{source} ({', '.join(sorted(tables))}) backs {backed[0]}"
                       + (f", and its grain {column} is one of its dates" if prop else "; it names no dated grain")}
    if backed:
        return {"entity": "", "property": "", "candidates": backed,
                "why": f"its tables back {len(backed)} entities ({', '.join(backed)}) and its grain names none of "
                       "them — a person says which one it measures"}
    return {"entity": "", "property": "", "candidates": [],
            "why": "none of its tables backs an entity on this scope" if tables else "it names no table"}


def metric_keys(connection_id: str, schema_name: str, graph: Any) -> list[dict]:
    """Every metric that applies to the scope, with its confirmed entity, the proposal and why."""
    from aughor.semantic.metrics import list_metrics
    out = []
    for m in list_metrics(connection_id=connection_id, schema_name=schema_name):
        proposal = propose_metric_entity(m, graph)
        out.append({"name": m.name, "label": m.label, "status": m.status, "entity": m.entity or "",
                    "confirmed_by": m.entity_confirmed_by or "", "proposal": proposal,
                    "agrees": bool(m.entity) and m.entity == proposal["entity"]})
    return out


def keyed_counts() -> dict:
    """How far each store that carries meaning is keyed to the ontology — the census's `keyed` section. A store that
    cannot be read is said, never counted as zero."""
    out: dict[str, Any] = {}
    try:
        from aughor.semantic.metrics import list_metrics
        metrics = [m for m in list_metrics() if m.status != "deprecated"]
        out["metrics"] = {"of": len(metrics), "n": sum(1 for m in metrics if m.entity)}
    except Exception as exc:  # noqa: BLE001
        out["metrics"] = None
        out.setdefault("unread", {})["metrics"] = str(exc)[:200]
    return out
