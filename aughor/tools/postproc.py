"""Post-processing operators — composable transforms over a SQL-shaped
``(columns, rows)`` result, in Aughor's native data shape (no pandas).

Inspired by Apache Superset's pandas_postprocessing (compare / contribution /
rolling / cum), but rewritten for Aughor's `list[str], list[list]` results so the
deep-analysis, briefing, and stats surfaces can derive period-over-period deltas,
share-of-total, moving averages, and running totals WITHOUT a second SQL query.

Two layers:
  * series math (pure list[float] → list) — pct_changes / shares / rolling / cumulative,
  * table transforms ((columns, rows) → (columns, rows)) that append a derived column.

The series helpers are also used by tools/stats.py to surface period-over-period
and concentration signals to the LLM.
"""
from __future__ import annotations

import re
from typing import Optional

Row = list
Table = tuple[list[str], list[Row]]


# ── additivity ──────────────────────────────────────────────────────────────────
# Share-of-total / concentration / Pareto language is ONLY valid for an ADDITIVE measure
# (revenue, counts). Summing a NON-ADDITIVE one (an average/rate/ratio) yields a meaningless
# "total" and each group's "share" of it is noise — the AOV-by-payment-type bug ("credit_card
# accounts for 20% of 346.89" = five ~€69 averages summed). Mirrors web/lib/measureKind.ts.
# Matched against a name normalised so snake_case/camel separators become spaces (so a
# word boundary \b works on "total_spend" → "total spend"). Non-additive wins over additive.
_NON_ADDITIVE_NAME = re.compile(
    r"\b(avg|average|mean|median|rate|ratio|pct|percent|proportion|margin|share|per|"
    r"aov|arpu|arppu|asp|roas|cac|cpa|cpc|cpm|ltv|index|score)\b", re.I)
_ADDITIVE_NAME = re.compile(
    r"\b(revenue|sales|amount|spend|cost|total|sum|gmv|qty|quantity|orders?|units?|"
    r"profit|volume|count|customers|users|sessions|clicks|impressions|visits|transactions)\b", re.I)
_NON_ADDITIVE_SQL = re.compile(
    r"\b(avg|mean|median|stddev|std_dev|variance|var_samp|var_pop|corr|"
    r"percentile_cont|percentile_disc)\s*\(", re.I)


def is_additive_measure(col_name: str, sql: Optional[str] = None) -> bool:
    """True when a measure can be summed across groups into a meaningful total (so a
    share-of-total / concentration claim is valid). The SQL (when given) is authoritative
    for the non-additive case — ``aov`` from ``ROUND(AVG(order_value),2)`` is non-additive
    even though the alias hides it; else the column name decides, defaulting to non-additive
    for unknown names (never claim a share-of-total we cannot justify)."""
    if sql and _NON_ADDITIVE_SQL.search(sql):
        return False
    name = re.sub(r"[^a-z0-9]+", " ", (col_name or "").lower())
    if _NON_ADDITIVE_NAME.search(name):
        return False
    if _ADDITIVE_NAME.search(name):
        return True
    return False


# ── coercion ──────────────────────────────────────────────────────────────────

def _to_float(v: object) -> Optional[float]:
    if v is None or v == "" or v == "NULL":
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _col_idx(columns: list[str], col: str | int) -> int:
    if isinstance(col, int):
        return col
    return columns.index(col)


def column_floats(columns: list[str], rows: list[Row], col: str | int) -> list[Optional[float]]:
    """Per-row float values for a column (None where non-numeric/null), aligned to rows."""
    idx = _col_idx(columns, col)
    return [_to_float(r[idx]) if idx < len(r) else None for r in rows]


# ── column totals ────────────────────────────────────────────────────────────────

def _parsed_as(sql: str, dialect: str):
    """The statement as sqlglot reads it in ``dialect``; None when it is not that dialect's
    spelling. Only sqlglot's own parse errors mean that — anything else propagates."""
    import sqlglot
    from sqlglot.errors import ParseError, TokenError
    try:
        return sqlglot.parse_one(sql, read=dialect)
    except (ParseError, TokenError):
        return None


def _parsed(sql: str):
    """The statement in the first dialect that parses it, or None. The finding's SQL is in
    its engine's own spelling and the finding does not say which."""
    for dialect in ("bigquery", "duckdb", "snowflake", "mysql", "postgres"):
        tree = _parsed_as(sql, dialect)
        if tree is not None:
            return tree
    return None


def _adds_across_rows(e) -> bool:
    """A projection whose value adds across the groups it is computed for: a SUM, a COUNT of
    rows, or a sum or difference of those, under a ROUND / CAST / COALESCE. COUNT(DISTINCT …)
    does not — a customer who bought in two categories is counted in both — and a ratio, an
    average or a window value never does."""
    from sqlglot import exp
    if e.find(exp.Distinct, exp.Window) is not None:
        return False
    while isinstance(e, (exp.Paren, exp.Round, exp.Cast, exp.TryCast, exp.Coalesce, exp.Neg)):
        e = e.this
    if isinstance(e, (exp.Add, exp.Sub)):
        return _adds_across_rows(e.left) and _adds_across_rows(e.right)
    return isinstance(e, (exp.Sum, exp.Count))


def column_totals(sql: str, columns: list[str], rows: list[Row],
                  row_count: Optional[int] = None) -> list[tuple[str, str]]:
    """Each additive column's total over EVERY row of a result, as ``(column, total)``.

    Computed here so that no model adds rows: an Agent-mode answer stated the "combined
    revenue" of ten categories as 1,299,882.88 when its own ten rows sum to 1,299,928.70,
    and the one repair call kept the wrong figure.

    A column is totalled only when both the name rule above (`is_additive_measure`) and its
    own projection in the SQL say it adds across rows. Nothing is totalled when the rows in
    hand are not the whole result (a total of the first page would read as the total), when
    there are fewer than two, or when the statement has a ROLLUP / CUBE / GROUPING SETS row
    that already holds a subtotal."""
    from sqlglot import exp
    n = len(rows or [])
    if n < 2 or (row_count or n) > n or not sql:
        return []
    tree = _parsed(sql)
    if tree is None or tree.find(exp.Rollup, exp.Cube, exp.GroupingSets) is not None:
        return []
    out: list[tuple[str, str]] = []
    for i, col in enumerate(columns or []):
        if not is_additive_measure(str(col), sql):
            continue
        defs = [a.this for a in tree.find_all(exp.Alias) if a.alias.lower() == str(col).lower()]
        if not defs or not all(_adds_across_rows(d) for d in defs):
            continue
        cells = [r[i] if i < len(r) else None for r in rows]
        nums = [_to_float(c) for c in cells]
        if any(v is None and c not in (None, "", "NULL") for c, v in zip(cells, nums)):
            continue                        # a non-numeric cell: not a measure column
        vals = [v for v in nums if v is not None]
        if len(vals) < 2:
            continue
        total = sum(vals)
        if all(float(v).is_integer() for v in vals):
            out.append((str(col), str(int(round(total)))))
        else:
            out.append((str(col), f"{total:.2f}" if abs(total) >= 1 else f"{total:.6g}"))
    return out


# ── series math (pure) ─────────────────────────────────────────────────────────

def pct_changes(values: list[Optional[float]]) -> list[Optional[float]]:
    """Period-over-period fractional change vs the previous value (0.12 = +12%).

    None where either side is missing or the prior value is 0 (undefined)."""
    out: list[Optional[float]] = [None]
    for prev, cur in zip(values, values[1:]):
        if prev is None or cur is None or prev == 0:
            out.append(None)
        else:
            out.append((cur - prev) / prev)
    return out


def shares(values: list[Optional[float]]) -> list[Optional[float]]:
    """Each value's fraction of the (non-null) total. None where the value is null
    or the total is 0."""
    total = sum(v for v in values if v is not None)
    if total == 0:
        return [None for _ in values]
    return [None if v is None else v / total for v in values]


def rolling(values: list[Optional[float]], window: int, op: str = "mean") -> list[Optional[float]]:
    """Trailing rolling aggregate over `window` points. None until the window fills
    or when any point in the window is missing. op ∈ {mean, sum, min, max}."""
    if window < 1:
        raise ValueError("window must be >= 1")
    out: list[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
            continue
        win = values[i + 1 - window : i + 1]
        if any(v is None for v in win):
            out.append(None)
            continue
        w = [v for v in win if v is not None]
        out.append({
            "mean": sum(w) / len(w), "sum": sum(w), "min": min(w), "max": max(w),
        }[op])
    return out


def cumulative(values: list[Optional[float]]) -> list[Optional[float]]:
    """Running total. Nulls contribute 0 but keep the running value going."""
    out: list[Optional[float]] = []
    running = 0.0
    for v in values:
        running += v or 0.0
        out.append(running)
    return out


# ── table transforms ((columns, rows) → (columns, rows)) ───────────────────────

def _append_column(columns: list[str], rows: list[Row], name: str, vals: list[Optional[float]]) -> Table:
    new_cols = [*columns, name]
    new_rows = [[*r, vals[i]] for i, r in enumerate(rows)]
    return new_cols, new_rows


def with_period_over_period(columns: list[str], rows: list[Row], value_col: str | int) -> Table:
    """Append `<col>_pct_change` — fractional change vs the previous row. Assumes
    rows are already ordered by period (as DATE_TRUNC'd SQL returns them)."""
    name = f"{columns[_col_idx(columns, value_col)]}_pct_change"
    return _append_column(columns, rows, name, pct_changes(column_floats(columns, rows, value_col)))


def with_contribution(columns: list[str], rows: list[Row], value_col: str | int) -> Table:
    """Append `<col>_pct_of_total` — each row's share of the column total."""
    name = f"{columns[_col_idx(columns, value_col)]}_pct_of_total"
    return _append_column(columns, rows, name, shares(column_floats(columns, rows, value_col)))


def with_rolling(columns: list[str], rows: list[Row], value_col: str | int, window: int, op: str = "mean") -> Table:
    name = f"{columns[_col_idx(columns, value_col)]}_rolling_{op}{window}"
    return _append_column(columns, rows, name, rolling(column_floats(columns, rows, value_col), window, op))


def with_cumulative(columns: list[str], rows: list[Row], value_col: str | int) -> Table:
    name = f"{columns[_col_idx(columns, value_col)]}_cumulative"
    return _append_column(columns, rows, name, cumulative(column_floats(columns, rows, value_col)))
