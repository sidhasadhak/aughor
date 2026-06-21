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
