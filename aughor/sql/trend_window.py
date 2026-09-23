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


# ── period_split — the same trend, cut to one period and its comparison ─────────────────

#: A projection that is a function of time but not a bucket of it would split on a
#: meaningless boundary; a window function would compute across the removed rows.
_SPLIT_LABEL = "period"
#: The two coverage columns `period_split` appends after the metric's own.
COVERAGE_FIRST, COVERAGE_LAST = "_period_first_day", "_period_last_day"


def _unwrapped(tree):
    """The trend inside `recent_window`'s wrapper (``SELECT * FROM (<trend>) AS _recent ORDER
    BY …``) — the shape the profile store gives every LIMITed chart. Cutting the wrapper
    instead found no GROUP BY and refused GMV on the first real run (2026-09-23). Anything
    else is returned as it is."""
    from sqlglot import exp
    source = tree.args.get("from_") or tree.args.get("from")
    inner = source.this if source is not None else None
    if (isinstance(inner, exp.Subquery) and isinstance(inner.this, exp.Select)
            and len(tree.expressions) == 1 and isinstance(tree.expressions[0], exp.Star)
            and not any(tree.args.get(k) for k in ("where", "group", "having", "joins"))):
        return inner.this
    return tree
#: A bare first column read as a date by its name (`created_at`, `order_date`, `ts`).
_DATE_NAME = re.compile(r"date|time|(?:^|_)(?:at|on|ts|day|dt|ds)$", re.I)


def period_split(sql: str, *, start, end, previous_start, previous_end,
                 dialect: str = "duckdb") -> tuple:
    """Rewrite a KPI's TIME-TREND ``chart_sql`` so it computes the SAME metric once for a
    period and once for its comparison period: two rows, ``('current', v)`` and
    ``('previous', v)``. Returns ``(sql, "")``, or ``(None, reason)`` when the query cannot
    be proved to be a single-series trend over a raw date column.

    The trend's own bucket (day, week or month) is REPLACED, not filtered: the bucket
    function's raw date column is read out of it, cast to a date, and the rows are labelled
    by which window they fall in, then grouped by that label. So a monthly revenue chart
    yields a correct WEEK of revenue, and a rate (``SUM(a)/SUM(b)``) is recomputed over the
    whole window at its own grain — never averaged across the chart's buckets, which for a
    ratio is a different number. Windows are half-open (``start <= d < end``), dates in UTC
    as the source stores them. Deterministic, DB-free; never raises."""
    if not sql or not sql.strip():
        return None, "the metric has no trend query"
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None, "its trend query does not parse"
    if not isinstance(tree, exp.Select) or not tree.expressions:
        return None, "its trend query is not a single SELECT"
    tree = _unwrapped(tree)
    first = tree.expressions[0]
    first_alias = first.alias_or_name or ""
    bucket = first.unalias()
    if any(isinstance(e, exp.Window) for sel in tree.expressions for e in sel.find_all(exp.Window)):
        return None, "its trend query uses a window function, which a period cut would change"
    group = tree.args.get("group")
    keys = list(group.expressions) if group is not None else []
    if len(keys) != 1:
        return None, ("its query is not grouped by time alone" if keys
                      else "its query is not grouped by a time bucket")
    key = keys[0]
    refers_to_bucket = (
        (isinstance(key, exp.Literal) and key.is_int and key.name == "1")
        or (isinstance(key, exp.Column) and first_alias and key.name.lower() == first_alias.lower()
            and not key.table)
        or key == bucket)
    if not refers_to_bucket:
        return None, "its query is grouped by something other than its first column"
    columns = {c.sql(dialect=dialect): c for c in bucket.find_all(exp.Column)}
    if len(columns) != 1:
        return None, "its time bucket does not read exactly one date column"
    column = next(iter(columns.values()))
    # sqlglot 30 spells these `with_` / `from_`; older releases `with` / `from`
    source = tree.args.get("from_") or tree.args.get("from")
    derived = bool(tree.args.get("with_") or tree.args.get("with")) or any(
        isinstance(src, exp.Subquery)
        for src in [source.this if source is not None else None]
        + [j.this for j in tree.args.get("joins") or []])
    if isinstance(bucket, exp.Column):
        # a bare column is a date only by its name: `status` in "top statuses by revenue"
        # is the first column of a breakdown, and casting it to a date fails at run time
        if not (_first_is_date_bucket(first, first_alias, dialect) or _DATE_NAME.search(column.name)):
            return None, "its first column is not a date"
        if derived:
            return None, ("its date column comes from a sub-query, where it may already be a "
                          "bucket rather than a date")
    elif not _first_is_date_bucket(first, first_alias, dialect):
        return None, "its first column is not a date bucket"
    try:
        day = exp.DataType.build("date")

        def on(d):
            return exp.Cast(this=exp.Literal.string(d.isoformat()), to=day.copy())

        def within(lo, hi):
            d = exp.Cast(this=column.copy(), to=day.copy())
            return exp.and_(exp.GTE(this=d, expression=on(lo)),
                            exp.LT(this=d.copy(), expression=on(hi)))

        label = (exp.Case().when(within(start, end), exp.Literal.string("current"))
                 .else_(exp.Literal.string("previous")))
        out = tree.copy()
        out.expressions[0] = exp.alias_(label, _SPLIT_LABEL)
        # the first and last day each window's rows actually cover: a comparison year the data
        # only reaches in September is not a year, and "+200%" against it is not a move
        as_day = exp.Cast(this=column.copy(), to=day.copy())
        out.append("expressions", exp.alias_(exp.Min(this=as_day.copy()), COVERAGE_FIRST))
        out.append("expressions", exp.alias_(exp.Max(this=as_day), COVERAGE_LAST))
        out.set("group", exp.Group(expressions=[label.copy()]))
        for arg in ("order", "limit", "offset"):
            out.set(arg, None)
        out = out.where(exp.or_(exp.paren(within(previous_start, previous_end)),
                                exp.paren(within(start, end))), append=True, copy=False)
        return out.sql(dialect=dialect), ""
    except Exception as exc:  # noqa: BLE001 — a rewrite that fails is reported, never raised
        return None, f"its trend query could not be cut to a period ({type(exc).__name__})"
