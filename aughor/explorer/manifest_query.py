"""Deterministic baseline SQL for an L2 manifest cell — the Tier-1 #4 keystone.

The cold-run experiment proved Phase 8 spends ~14 LLM calls per finding because it generates
questions by LLM trial-and-error (most produce failing or redundant SQL). A manifest cell
(`metric × dimension × time-axis`) is already a precise query spec — so we synthesize its
baseline SQL **mechanically, with zero LLM calls**, and let the existing Phase-8 pipeline
(deterministic identifier/semantic repair → `dry_run` bind-check + skip → join value-domain
guard → fan-out/grain/ratio guards → execute → interpret) enforce correctness.

That division is what keeps accuracy at the current bar while removing the generation cost:
**this module only PROPOSES; the pipeline DISPOSES.** A naive proposal can never become a wrong
finding — an unbindable or fan-out-prone proposal is skipped by the guards, exactly as an
LLM-proposed one would be. The only LLM call left per cell is the interpretation of real rows.

Pure (profiles + cell in, SQL string out) — no I/O, no LLM — so it is fully unit-testable.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.explorer.coverage_manifest import ManifestCell

# A measure is a RATE (averaged, not summed) when its unit/interpretation says so or its
# values sit in [0,1.x]. Summing a rate is meaningless; the ratio guard backstops the rest.
_RATE_HINTS = ("fraction", "percent", "ratio", "rate", "pct")
_TOP_N = 20            # dimension breakdowns: top-N by value (the guard drops fan-out)


def _is_rate(metric_profile: Any) -> bool:
    if metric_profile is None:
        return False
    blob = " ".join(str(getattr(metric_profile, a, "") or "")
                    for a in ("unit", "value_interpretation")).lower()
    if any(h in blob for h in _RATE_HINTS):
        return True
    vr = getattr(metric_profile, "value_range", None)
    if isinstance(vr, (tuple, list)) and len(vr) >= 2:
        lo, hi = vr[0], vr[1]
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and -1.0 <= lo and hi <= 1.5:
            return True   # values within [0,1.x] → a rate, not an additive measure
    return False


def _agg(metric: str, metric_profile: Any) -> str:
    """The grain-safe aggregate for a measure: AVG for a rate, SUM for an additive measure."""
    return f"AVG({metric})" if _is_rate(metric_profile) else f"SUM({metric})"


def _trunc(ts: str, grain: str, dialect: str) -> str:
    g = (grain or "month").lower()
    if g not in ("day", "week", "month", "quarter", "year"):
        g = "month"
    return f"date_trunc('{g}', {ts})"      # DuckDB / Postgres-compatible


def _reaches_current_bucket(table_profile: Any, *, today: str = "") -> bool:
    """Does this table's data run into the bucket that has not finished yet?

    The canvas sibling of `investigate._clamp_intake_to_coverage`, and it carries that
    guard's two conditions rather than inventing new ones:

    **1. Only when the data reaches TODAY.** A closed dataset's final bucket is final —
    trimming it would erase real data on every render, forever, which is why the demo and
    bakehouse sets must stay whole. `date_range` is the absolute (min, max), so a row dated
    in the future also trips this, and trimming is still right there: the current bucket is
    incomplete whatever a stray row claims.

    **2. Only when a complete bucket would remain.** A table whose whole life is today has
    one bucket, and an empty trend chart is a worse answer than a partial one — "no data"
    reads as a fact about the business rather than about the calendar.

    `today` is injectable for the same reason it is on the investigate guard: a test that
    had to wait for midnight is a test nobody runs.
    """
    from datetime import date, datetime, timezone

    rng = getattr(table_profile, "date_range", None)
    if not rng or len(rng) < 2 or rng[1] is None:
        return False
    if (getattr(table_profile, "n_periods", None) or 0) <= 1:
        return False

    ref = today or datetime.now(timezone.utc).date().isoformat()
    dmax = rng[1]
    # The profiler hands back whatever the driver gave it — a date, a datetime, or a
    # string. Comparing the first ten characters is the one reading that works for all
    # three without a parse that can raise on a dialect nobody tested.
    if isinstance(dmax, (date, datetime)):
        dmax_s = dmax.isoformat()[:10]
    else:
        dmax_s = str(dmax).strip()[:10]
    return bool(dmax_s) and dmax_s >= ref[:10]


def cell_to_sql(cell: ManifestCell, table_profile: Any, metric_profile: Any,
                *, dialect: str = "duckdb", today: str = "") -> Optional[str]:
    """Runnable baseline SQL for ``cell``, or None when the data can't support it
    (e.g. a time axis with no timestamp). ``metric`` is a column on ``cell.table``; a named
    KPI cell (table ``"(business)"`` / unmapped) returns None — those reuse the metric's
    own ``value_sql``/``chart_sql`` instead, which is already validated."""
    # A cell carrying pre-validated SQL (a KPI's value_sql) is used verbatim — already correct.
    if getattr(cell, "sql", None):
        return cell.sql
    # Profile-led KPI cells carry a KPI *name* (e.g. "Gross Merchandise Value (GMV)"), not a
    # column — they reuse the metric's own validated value_sql/chart_sql, not a synthesised
    # aggregate. Only profiled-measure cells (metric == a real column) are synthesised here.
    if cell.source != "profiled_measure" or cell.table == "(business)" or not cell.table:
        return None
    metric, table = cell.metric, cell.table
    agg = _agg(metric, metric_profile)
    ts = getattr(table_profile, "primary_timestamp", None)
    grain = getattr(table_profile, "time_grain", None) or "month"

    if cell.axis == "headline":
        return f"SELECT {agg} AS value FROM {table}"

    if cell.axis == "dimension" and cell.cut:
        return (f"SELECT {cell.cut}, {agg} AS value FROM {table} "
                f"GROUP BY {cell.cut} ORDER BY value DESC LIMIT {_TOP_N}")

    if cell.axis in ("trend", "seasonality", "yoy"):
        if not ts:
            return None
        if cell.axis == "trend":
            period = _trunc(ts, grain, dialect)
            where = f"{ts} IS NOT NULL"
            if _reaches_current_bucket(table_profile, today=today):
                # The trailing bucket has not finished, so plotting it draws a cliff that
                # is a property of the clock, not of the business. The investigate path
                # learned this live: a briefing led with "orders fell 97.5%" comparing nine
                # hours of today against all of yesterday, while a finding in the same
                # report said the number was partial. Prose that knows is not a guard.
                #
                # Expressed in SQL rather than as a computed literal so the cutoff is the
                # WAREHOUSE's idea of now, in the warehouse's own timezone — a Python
                # literal would be this process's idea of today, and the two disagree for
                # several hours a day.
                where += f" AND {ts} < {_trunc('CURRENT_DATE', grain, dialect)}"
            return (f"SELECT {period} AS period, {agg} AS value FROM {table} "
                    f"WHERE {where} GROUP BY 1 ORDER BY 1")
        if cell.axis == "seasonality":
            return (f"SELECT EXTRACT(month FROM {ts}) AS month, {agg} AS value FROM {table} "
                    f"WHERE {ts} IS NOT NULL GROUP BY 1 ORDER BY 1")
        # yoy — value per calendar year (the pipeline computes the deltas downstream)
        return (f"SELECT EXTRACT(year FROM {ts}) AS year, {agg} AS value FROM {table} "
                f"WHERE {ts} IS NOT NULL GROUP BY 1 ORDER BY 1")

    return None


def cell_question(cell: ManifestCell) -> str:
    """A short natural-language label for a cell — the 'question' the baseline answers,
    used for journaling, the angle tag, and dedup signatures."""
    m = cell.metric
    if cell.axis == "headline":
        return f"What is total {m}?"
    if cell.axis == "dimension":
        return f"How does {m} break down by {cell.cut}?"
    if cell.axis == "trend":
        return f"How has {m} trended over time?"
    if cell.axis == "seasonality":
        return f"Does {m} show seasonality across the year?"
    if cell.axis == "yoy":
        return f"How does {m} compare year over year?"
    return f"{m} ({cell.axis})"
