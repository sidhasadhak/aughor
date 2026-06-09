"""Semantic Compiler — typed Intent IR + deterministic SQL synthesis.

The thesis: for the *safe, common* analytical shapes, the LLM should fill a small typed
intent — not hand-write SQL. The SQL is then ASSEMBLED deterministically from the verified
ontology (entities, measure/dimension columns, object-set filters) + the canonical metric
resolver, and dialect-transpiled with sqlglot. "The LLM augments a declarative layer rather
than regenerating SQL." (Backlog #11; depends on the #2 metric resolver.)

Four intents are covered — the ones that map 1:1 to a grounded, single-table template:
  • scalar     — one aggregate                      → SELECT SUM(x) FROM t [WHERE …]
  • timeseries — an aggregate over a time grain      → … GROUP BY date_trunc(grain, ts)
  • breakdown  — an aggregate by a dimension         → … GROUP BY dim ORDER BY metric DESC
  • ranking    — breakdown + ORDER + LIMIT (top-N)   → … ORDER BY metric DESC LIMIT n

synthesize_sql is **coverage-gated**: every reference (entity/table, measure or named
metric, dimension, time column, object set) must resolve against the ontology, and the
metric must be single-table — otherwise it returns None and the caller falls back to the
LLM SQL path. It never guesses. Single-table only in v1: cross-table joins are exactly
where free-form generation goes wrong (fan-out), so they stay on the fallback path.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_INTENT_TYPES = ("scalar", "timeseries", "breakdown", "ranking")
_AGGS = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX",
         "count": "COUNT", "count_distinct": "COUNT_DISTINCT"}
_GRAINS = {"hour", "day", "week", "month", "quarter", "year"}


class QueryIntent(BaseModel):
    """A typed, symbolic description of a single analytical query — no SQL.

    The measure is given EITHER as a named canonical ``metric`` OR as an ``agg`` over a
    ``measure`` column (count needs no column). All names are symbolic references resolved
    against the ontology by synthesize_sql.
    """
    intent_type: str = Field(description="scalar | timeseries | breakdown | ranking")
    entity:      str = Field(default="", description="Ontology entity id (resolves the table)")
    table:       str = Field(default="", description="Explicit table; else from entity/metric")

    metric:      str = Field(default="", description="Canonical metric name (preferred)")
    measure:     str = Field(default="", description="Measure column, used with agg when no metric")
    agg:         str = Field(default="sum", description="sum|avg|min|max|count|count_distinct")

    dimension:   str = Field(default="", description="Column for breakdown/ranking")
    time_col:    str = Field(default="", description="Timestamp column for timeseries (else resolved)")
    time_grain:  str = Field(default="month", description="hour|day|week|month|quarter|year")

    object_set:  str = Field(default="", description="Named verified object set to filter by")
    window:      Optional[tuple] = Field(default=None, description="(start_iso, end_iso) on time_col")
    order_desc:  bool = Field(default=True)
    limit:       Optional[int] = Field(default=None)


# ── resolution helpers ──────────────────────────────────────────────────────────

def _entity_for(ontology, *, entity: str = "", table: str = ""):
    if entity and entity in ontology.entities:
        return ontology.entities[entity]
    if table:
        e = ontology.entity_for_table(table) if hasattr(ontology, "entity_for_table") else None
        if e:
            return e
        for ent in ontology.entities.values():
            if table in (ent.source_tables or []):
                return ent
    return None


def _props(entity) -> dict:
    return dict(getattr(entity, "properties", {}) or {})


def _alias(name: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in (name or "value").lower()).strip("_")
    return out or "value"


def _resolve_measure(intent: QueryIntent, table: str, props: dict,
                     metrics: list) -> Optional[tuple]:
    """Return (expr, alias) for the measure, or None if it can't be grounded."""
    # 1) named canonical metric (verified, single-table)
    if intent.metric:
        norm = intent.metric.strip().lower()
        for m in metrics or []:
            if m.name.strip().lower() == norm and getattr(m, "verified", True):
                tbls = {t for t in (m.tables or []) if t}
                if tbls and not tbls <= {table, table.split(".")[-1]}:
                    return None  # multi-table metric → fall back
                return m.sql, _alias(m.name)
        return None  # named but unknown/unverified → fall back

    # 2) aggregate over a measure column (or COUNT)
    agg = (intent.agg or "sum").lower()
    if agg not in _AGGS:
        return None
    if agg == "count" and not intent.measure:
        return "COUNT(*)", "count"
    if not intent.measure or intent.measure not in props:
        return None
    p = props[intent.measure]
    if agg in ("sum", "avg", "min", "max") and getattr(p, "semantic_type", "") != "measure":
        return None  # only aggregate real measure columns (avoids SUM(id)-style nonsense)
    if agg == "count_distinct":
        return f"COUNT(DISTINCT {intent.measure})", f"distinct_{_alias(intent.measure)}"
    return f"{_AGGS[agg]}({intent.measure})", f"{agg}_{_alias(intent.measure)}"


def _resolve_time_col(intent: QueryIntent, entity, props: dict) -> Optional[str]:
    if intent.time_col:
        return intent.time_col if intent.time_col in props else None
    if getattr(entity, "created_at_col", None) and entity.created_at_col in props:
        return entity.created_at_col
    for name, p in props.items():
        if getattr(p, "semantic_type", "") == "timestamp":
            return name
    return None


def _filters(intent: QueryIntent, entity, props: dict, time_col: Optional[str]) -> list:
    out: list = []
    af = getattr(entity, "active_filter", None)
    if af:
        out.append(af)
    if intent.object_set:
        os_ = (getattr(entity, "object_sets", {}) or {}).get(intent.object_set)
        if os_ is None or not getattr(os_, "verified", False):
            return None  # asked for an object set we can't verify → fall back
        if getattr(os_, "filter_sql", ""):
            out.append(os_.filter_sql)
    if intent.window and time_col:
        s, e = intent.window
        if s:
            out.append(f"{time_col} >= '{s}'")
        if e:
            out.append(f"{time_col} <= '{e}'")
    return out


def _transpile(sql: str, dialect: str) -> Optional[str]:
    try:
        import sqlglot
        return sqlglot.parse_one(sql, read=dialect).sql(dialect=dialect)
    except Exception as exc:
        logger.debug("compiler: transpile failed (%s) for: %s", exc, sql)
        return None


# ── the compiler ─────────────────────────────────────────────────────────────────

def synthesize_sql(intent: QueryIntent, ontology, *, metrics: Optional[list] = None,
                   dialect: str = "duckdb") -> Optional[str]:
    """Assemble grounded SQL for *intent*, or None when it can't be fully resolved.

    Coverage-gated and single-table: any unresolved reference, a multi-table metric, or an
    unsupported intent type → None (the caller then uses the LLM SQL path)."""
    if intent.intent_type not in _INTENT_TYPES:
        return None

    entity = _entity_for(ontology, entity=intent.entity, table=intent.table)
    if entity is None or not getattr(entity, "source_tables", None):
        return None
    table = intent.table or entity.source_tables[0]
    props = _props(entity)
    if not props:
        return None

    if metrics is None:
        try:
            from aughor.semantic.canonical import resolve_canonical_metrics
            metrics = resolve_canonical_metrics(
                getattr(ontology, "connection_id", "") or "",
                getattr(ontology, "schema_name", "") or None,
                ontology=ontology,
            )
        except Exception:
            metrics = []

    measure = _resolve_measure(intent, table, props, metrics)
    if measure is None:
        return None
    expr, alias = measure

    # dimension / time grounding by intent type
    dim = None
    if intent.intent_type in ("breakdown", "ranking"):
        if not intent.dimension or intent.dimension not in props:
            return None
        dim = intent.dimension
    time_col = None
    if intent.intent_type == "timeseries":
        if intent.time_grain not in _GRAINS:
            return None
        time_col = _resolve_time_col(intent, entity, props)
        if not time_col:
            return None
    elif intent.window:
        # a window was requested on a non-timeseries intent — it needs a time column too
        time_col = _resolve_time_col(intent, entity, props)
        if not time_col:
            return None  # can't honour the window → fall back rather than drop it

    where = _filters(intent, entity, props, time_col)
    if where is None:
        return None
    # timeseries excludes NULL timestamps so the grain bucket is meaningful
    if intent.intent_type == "timeseries":
        where = where + [f"{time_col} IS NOT NULL"]
    where_sql = (" WHERE " + " AND ".join(f"({c})" for c in where)) if where else ""

    if intent.intent_type == "scalar":
        sql = f"SELECT {expr} AS {alias} FROM {table}{where_sql}"
    elif intent.intent_type == "timeseries":
        period = f"date_trunc('{intent.time_grain}', {time_col})"
        sql = (f"SELECT {period} AS period, {expr} AS {alias} "
               f"FROM {table}{where_sql} GROUP BY 1 ORDER BY 1")
    else:  # breakdown / ranking
        order = "DESC" if intent.order_desc else "ASC"
        sql = (f"SELECT {dim}, {expr} AS {alias} "
               f"FROM {table}{where_sql} GROUP BY 1 ORDER BY 2 {order}")
        if intent.intent_type == "ranking":
            sql += f" LIMIT {int(intent.limit) if intent.limit else 10}"

    return _transpile(sql, dialect)
