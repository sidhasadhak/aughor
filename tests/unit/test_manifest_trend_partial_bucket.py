"""The canvas trend chart stops ending on a cliff made by the clock.

The sibling of the investigate-path guard shipped 2026-09-02
(`investigate._clamp_intake_to_coverage`). That one trims an observation WINDOW; this one
trims the trailing bucket of a baseline TREND, which is the other place a partial period
reaches a reader — as the last point of a line chart on the canvas.

**The defect it descends from, seen live:** a briefing led with "orders fell 97.5%",
comparing nine hours of today (43 orders) against all of yesterday (1,733). A finding in
the same report said the number was artificially low, and the headline led with the
collapse anyway. Prose that knows is not a guard; the query layer is.

**The two conditions are inherited deliberately, not re-derived:**

1. Trim ONLY when the data reaches today. A closed dataset's final bucket is final, and
   trimming it would erase real data on every render forever — the demo and bakehouse sets
   must stay whole.
2. Trim ONLY when a complete bucket would remain. An empty trend chart is a worse answer
   than a partial one, because "no data" reads as a fact about the business rather than
   about the calendar.
"""
from __future__ import annotations

from aughor.explorer.coverage_manifest import ManifestCell
from aughor.explorer.manifest_query import cell_to_sql

TODAY = "2026-09-03"


class _Profile:
    """Only the attributes `cell_to_sql` reads — a stand-in for the profiler's object."""

    def __init__(self, *, date_range=None, n_periods=None, grain="day",
                 ts="created_at"):
        self.primary_timestamp = ts
        self.time_grain = grain
        self.date_range = date_range
        self.n_periods = n_periods


def _trend(profile, *, today=TODAY):
    cell = ManifestCell(metric="order_id", table="orders", axis="trend", cut=None,
                        source="profiled_measure")
    return cell_to_sql(cell, profile, None, today=today) or ""


# ── the trim fires ───────────────────────────────────────────────────────────────

def test_a_table_whose_data_reaches_TODAY_drops_the_unfinished_bucket():
    sql = _trend(_Profile(date_range=("2026-08-01", "2026-09-03"), n_periods=34))
    assert "date_trunc('day', CURRENT_DATE)" in sql
    assert "created_at <" in sql


def test_the_cutoff_is_the_WAREHOUSE_clock_not_this_process_clock():
    """A Python literal would be this process's idea of today; the warehouse's timezone
    disagrees with it for several hours a day, and the disagreement would show as a chart
    that trims a day early or a day late depending on where the server sits."""
    sql = _trend(_Profile(date_range=("2026-08-01", "2026-09-03"), n_periods=34))
    assert "CURRENT_DATE" in sql
    assert TODAY not in sql, "today was baked in as a literal instead of asked of the warehouse"


def test_the_cutoff_matches_the_BUCKET_grain_not_always_the_day():
    """A monthly trend's unfinished bucket is the whole current month. Trimming only today
    would leave the other 2 days of September plotted as a month."""
    sql = _trend(_Profile(date_range=("2025-01-01", "2026-09-03"), n_periods=21,
                          grain="month"))
    assert "date_trunc('month', CURRENT_DATE)" in sql


# ── the trim stays quiet, which is the harder half ───────────────────────────────

def test_a_CLOSED_dataset_is_left_WHOLE():
    """The condition that protects every demo and fixture set. Trimming a closed dataset's
    final bucket would erase real data on every render, forever."""
    sql = _trend(_Profile(date_range=("2023-01-01", "2023-12-31"), n_periods=12))
    assert "CURRENT_DATE" not in sql
    assert sql.endswith("GROUP BY 1 ORDER BY 1")


def test_a_dataset_with_ONE_bucket_is_left_whole_even_if_it_is_today():
    """An empty chart is a worse answer than a partial one: "no data" reads as a fact about
    the business rather than about the calendar."""
    sql = _trend(_Profile(date_range=(TODAY, TODAY), n_periods=1))
    assert "CURRENT_DATE" not in sql


def test_a_profile_with_NO_date_range_is_left_whole():
    """Unknown coverage is not an invitation to guess. The old behaviour is the safe one."""
    assert "CURRENT_DATE" not in _trend(_Profile(date_range=None, n_periods=12))


def test_a_profile_with_no_n_periods_is_left_whole():
    assert "CURRENT_DATE" not in _trend(
        _Profile(date_range=("2026-08-01", "2026-09-03"), n_periods=None))


# ── shape and blast radius ───────────────────────────────────────────────────────

def test_a_FUTURE_dated_row_still_trims_the_current_bucket():
    """`date_range` is the absolute max including outliers, so a stray future row trips the
    check. Trimming is still right: the current bucket is incomplete whatever that row
    claims, and the alternative is trusting bad data to decide a guard."""
    sql = _trend(_Profile(date_range=("2026-08-01", "2027-01-01"), n_periods=34))
    assert "CURRENT_DATE" in sql


def test_the_other_time_axes_are_UNTOUCHED():
    """`seasonality` buckets by month-of-year across all years and `yoy` by calendar year;
    neither ends on a trailing bucket a reader would read as a cliff, and adding a cutoff
    would silently drop the current year from a year-over-year chart."""
    profile = _Profile(date_range=("2026-08-01", "2026-09-03"), n_periods=34)
    for axis in ("seasonality", "yoy"):
        cell = ManifestCell(metric="order_id", table="orders", axis=axis, cut=None,
                            source="profiled_measure")
        assert "CURRENT_DATE" not in (cell_to_sql(cell, profile, None, today=TODAY) or "")


def test_the_headline_and_dimension_axes_are_untouched():
    """Neither has a time axis to end on, so a cutoff there would just discard today's rows
    from a total — a wrong number, quietly."""
    profile = _Profile(date_range=("2026-08-01", "2026-09-03"), n_periods=34)
    for axis, cut in (("headline", None), ("dimension", "traffic_source")):
        cell = ManifestCell(metric="order_id", table="orders", axis=axis, cut=cut,
                            source="profiled_measure")
        assert "CURRENT_DATE" not in (cell_to_sql(cell, profile, None, today=TODAY) or "")


def test_a_table_with_no_timestamp_still_yields_no_trend():
    """Unchanged: a time axis with no timestamp is None, not a query with a cutoff and
    nothing to cut."""
    assert _trend(_Profile(date_range=("2026-08-01", "2026-09-03"), n_periods=34,
                           ts=None)) == ""
