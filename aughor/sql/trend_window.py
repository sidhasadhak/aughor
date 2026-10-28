"""
trend_window — anchor a KPI trend's ``chart_sql`` to the MOST RECENT N buckets.

A north-star metric's ``chart_sql`` is a small time series that EXPLAINS the metric
(margin per month, AOV per month, CAC per week). LLMs write these as
``... GROUP BY <bucket> ORDER BY <bucket> LIMIT N`` — but **ascending order + LIMIT
returns the OLDEST N buckets**. On a dataset that grows over years (missimi spans
2022–2025) the briefing then shows Jan–Dec 2022 forever, and the period-over-period
delta on the KPI card is computed on stale history instead of the latest period.

``recent_window`` rewrites such a trend so it returns the most-recent N buckets,
re-sorted ASCENDING for display — so sparklines read left→right = old→new and the
``series_move`` / ``deltaInfo`` consumers see ``first=oldest, last=newest``. It is:

  • deterministic + DB-free (pure sqlglot AST surgery),
  • idempotent (a query already wrapped this way has no top-level LIMIT, so it is
    left alone),
  • fail-open + HIGH-PRECISION: it ONLY rewrites a query it can prove is a time
    TREND — first projection is a date bucket, ordered ASCENDING by that first
    column, with a LIMIT. A top-N breakdown (``ORDER BY revenue DESC LIMIT 10``),
    an already-DESC trend, a trend with no LIMIT (already shows all history), or
    anything it cannot prove is a trend is returned UNCHANGED.
"""
from __future__ import annotations

import re

# A function call that buckets a timestamp into a period.
_BUCKET_FN = ("date_trunc", "datetrunc", "strftime", "time_bucket", "date_part", "extract")
# A projection alias/column that reads as a time bucket.
_BUCKET_ALIAS = re.compile(
    r"^(month|week|day|date|year|quarter|period|hour|dt|ds|mth|wk|yr|yyyymm|ym|bucket)$", re.I
)


def _first_is_date_bucket(first_expr, first_alias: str, dialect: str) -> bool:
    """True when a SELECT's first projection looks like a time bucket: a
    date_trunc/strftime/cast-to-date expression, or an alias/column that reads as
    a date bucket (``month`` / ``week`` / ``date`` …)."""
    if first_alias and _BUCKET_ALIAS.match(first_alias):
        return True
    try:
        s = first_expr.sql(dialect=dialect).lower()
    except Exception:
        return False
    if "::date" in s or "::timestamp" in s or " as date" in s or " as timestamp" in s:
        return True
    return any(fn + "(" in s for fn in _BUCKET_FN)


def _order_key_is_first(order_key, first_expr, first_alias: str, dialect: str) -> bool:
    """True when the (first) ORDER BY key sorts by the first projection — written as
    ``ORDER BY 1`` (ordinal), ``ORDER BY <alias>``, or the same expression."""
    from sqlglot import exp

    inner = order_key.this
    if isinstance(inner, exp.Literal) and inner.is_int and inner.name == "1":
        return True
    if isinstance(inner, exp.Column) and first_alias and inner.name.lower() == first_alias.lower():
        return True
    try:
        base = (first_expr.this if isinstance(first_expr, exp.Alias) else first_expr)
        return inner.sql(dialect=dialect).lower() == base.sql(dialect=dialect).lower()
    except Exception:
        return False


def recent_window(sql: str, dialect: str = "duckdb") -> str:
    """Return ``sql`` rewritten to fetch the most-recent N buckets of a time trend
    (ascending for display), or the original ``sql`` unchanged when it is not a
    provably-ascending, LIMITed time trend. Never raises."""
    if not sql or not sql.strip():
        return sql
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql

    if not isinstance(tree, exp.Select):
        return sql
    # No LIMIT → already returns the full history ascending; nothing to anchor.
    if tree.args.get("limit") is None:
        return sql
    order = tree.args.get("order")
    if order is None or not order.expressions:
        return sql
    sels = tree.expressions
    if not sels:
        return sql

    first = sels[0]
    first_alias = first.alias_or_name or ""
    if not _first_is_date_bucket(first, first_alias, dialect):
        return sql  # a top-N category breakdown, not a time trend

    key = order.expressions[0]
    if not _order_key_is_first(key, first, first_alias, dialect):
        return sql  # ordered by something other than the time bucket (e.g. a measure)

    # Rewrite: ensure the inner order is DESC (most-recent N via the existing LIMIT) —
    # whether the trend was written ascending (the OLDEST-window bug) or descending
    # (recent but newest-first) — then wrap and re-sort ASCENDING so the series reads
    # old→new left→right for display. Idempotent: the wrap drops the top-level LIMIT.
    try:
        inner = tree.copy()
        inner.args["order"].expressions[0].set("desc", True)
        order_target = exp.column(first_alias) if first_alias else exp.Literal.number(1)
        outer = exp.select("*").from_(inner.subquery(alias="_recent")).order_by(order_target)
        return outer.sql(dialect=dialect)
    except Exception:
        return sql
