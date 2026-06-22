"""Tier-0 role-aware temporal scope — regression tests for the calendar-table pitfall.

A date-dimension / calendar table holds one row per day far into the future and is
uniformly dense, so anchoring the analytical window on MAX(any date column) drags it
past the last real fact and every fact filter returns zero rows ("no data" briefings).
The window must anchor on the trailing edge of *activity* (measure-bearing tables).

See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3.
"""
from aughor.explorer.windowing import role_aware_time_window as _role_aware_time_window


def _tp(**ranges):
    """ranges: table=(start, end) → table profiles with effective+absolute date range."""
    return {t: {"effective_date_range": (s, e), "date_range": (s, e)} for t, (s, e) in ranges.items()}


def _cp(**has_measure):
    """has_measure: table=bool → column profiles with/without a measure column."""
    out = {}
    for t, has in has_measure.items():
        out[t] = (
            {"amount": {"semantic_type": "measure"}}
            if has else
            {"label": {"semantic_type": "dimension"}}
        )
    return out


def test_calendar_spine_does_not_drag_window_into_the_future():
    # Calendar runs to 2025; the actual facts stop mid-2023.
    tp = _tp(
        date_dim=("2015-01-01", "2025-12-31"),
        sales=("2019-01-01", "2023-06-30"),
        orders=("2019-01-01", "2023-06-15"),
    )
    cp = _cp(date_dim=False, sales=True, orders=True)
    start, end, discrepancy = _role_aware_time_window(tp, cp)

    # Anchored on the activity edge (2023-06/07), NOT the calendar (2025).
    assert end is not None and end.startswith("2023-0"), f"anchored at {end}, expected ~2023-06"
    assert start.startswith("2022-"), start
    # The calendar↔fact discrepancy is surfaced as a data-quality signal.
    assert any(t == "date_dim" for t, _ in discrepancy), discrepancy


def test_sentinel_far_future_dates_are_ignored():
    # An SCD valid_to sentinel (9999-12-31) must not anchor the window.
    tp = _tp(
        sales=("2019-01-01", "2023-06-30"),
        scd=("9999-01-01", "9999-12-31"),
    )
    cp = _cp(sales=True, scd=True)
    _start, end, _disc = _role_aware_time_window(tp, cp)
    assert end.startswith("2023-0"), f"anchored at {end}, expected ~2023-06"


def test_fallback_when_no_measures_detected_does_not_regress():
    # Profiler produced no measure semantics → anchor on every dated table (old behaviour),
    # still sentinel-filtered. No silent empty window.
    tp = _tp(a=("2019-01-01", "2022-03-31"), b=("2019-01-01", "2021-09-30"))
    cp = _cp(a=False, b=False)
    _start, end, _disc = _role_aware_time_window(tp, cp)
    assert end.startswith("2022-"), end


def test_single_fact_normal_window_has_no_discrepancy():
    tp = _tp(orders=("2018-01-01", "2023-05-31"))
    cp = _cp(orders=True)
    start, end, discrepancy = _role_aware_time_window(tp, cp)
    assert end.startswith("2023-0")
    assert start.startswith("2022-")
    assert discrepancy == []


def test_no_dated_tables_returns_none():
    tp = {"lookup": {"effective_date_range": None, "date_range": None}}
    cp = _cp(lookup=False)
    start, end, discrepancy = _role_aware_time_window(tp, cp)
    assert (start, end, discrepancy) == (None, None, [])


def test_anchor_activity_picks_latest_measure_bearing_table():
    from aughor.explorer.windowing import anchor_activity as _anchor_activity
    tp = _tp(sales=("2019-01-01", "2023-06-30"), orders=("2019-01-01", "2023-09-30"),
             date_dim=("2015-01-01", "2025-12-31"))
    cp = _cp(sales=True, orders=True, date_dim=False)
    table, rec, _eff = _anchor_activity(tp, cp)
    assert table == "orders" and rec.startswith("2023-09")   # latest activity, not the calendar


def test_days_between_helper():
    from aughor.explorer.windowing import days_between as _days_between
    assert _days_between("2025-11-17", "2026-05-17") == 181
    assert _days_between("2026-05-17", "2025-11-17") == 181   # absolute
    assert _days_between("bad", "2026-01-01") == 0            # parse-safe


# ── Tier-1 tuning: core-fact anchor tie-break + calendar-spine hardening ──────
# (cross-connection validation surfaced these: a tiny `campaigns` table beating the
#  6.4M-row `order_items` on a recency tie; TPC-DS `date_dim` → 2100 anchoring the
#  window past all real facts because its date-part columns were mis-tagged as measures.)

def _tpr(**spec):
    """spec: table=(start, end, row_count) → profiles carrying a row_count."""
    return {t: {"effective_date_range": (s, e), "date_range": (s, e), "row_count": r}
            for t, (s, e, r) in spec.items()}


def test_core_fact_wins_recency_tie():
    from aughor.explorer.windowing import anchor_activity as _anchor_activity
    tp = _tpr(campaigns=("2025-11-01", "2026-05-17", 5_000),
              order_items=("2025-05-17", "2026-05-17", 6_437_071))
    cp = _cp(campaigns=True, order_items=True)
    table, _rec, _eff = _anchor_activity(tp, cp)
    assert table == "order_items"   # the core fact, not the tiny peripheral table


def test_slightly_fresher_peripheral_within_tolerance_loses_to_core_fact():
    from aughor.explorer.windowing import anchor_activity as _anchor_activity
    # peripheral table 10 days fresher (within the 45-day tolerance) but tiny
    tp = _tpr(campaigns=("2025-11-01", "2026-05-27", 5_000),
              order_items=("2025-05-17", "2026-05-17", 6_000_000))
    cp = _cp(campaigns=True, order_items=True)
    table, _rec, _eff = _anchor_activity(tp, cp)
    assert table == "order_items"


def test_clearly_fresher_table_outside_tolerance_sets_the_edge():
    from aughor.explorer.windowing import anchor_activity as _anchor_activity
    # a table 6 months fresher legitimately defines the trailing edge, tiny or not
    tp = _tpr(old_fact=("2019-01-01", "2023-06-30", 9_000_000),
              new_fact=("2024-01-01", "2024-06-30", 1_000))
    cp = _cp(old_fact=True, new_fact=True)
    table, rec, _eff = _anchor_activity(tp, cp)
    assert table == "new_fact" and rec.startswith("2024-06")


def test_calendar_spine_detected_by_name():
    from aughor.explorer.windowing import _is_calendar_spine
    assert _is_calendar_spine("main.date_dim", {"amount": {"semantic_type": "measure"}}) is True
    assert _is_calendar_spine("dim_date", None) is True
    assert _is_calendar_spine("calendar", None) is True
    assert _is_calendar_spine("orders", {"amount": {"semantic_type": "measure"}}) is False


def test_calendar_spine_detected_by_datepart_shape():
    from aughor.explorer.windowing import _is_calendar_spine
    # a non-obviously-named table whose "measures" are all date-parts (mis-tagged)
    cols = {f"d_{p}": {"semantic_type": "measure"}
            for p in ("year", "moy", "dom", "qoy", "week_seq")}
    assert _is_calendar_spine("weird_spine", cols) is True
    # a real fact with genuine measures is not a calendar
    real = {"revenue": {"semantic_type": "measure"}, "quantity": {"semantic_type": "measure"}}
    assert _is_calendar_spine("store_sales", real) is False


def test_mistagged_calendar_excluded_from_anchor():
    from aughor.explorer.windowing import anchor_activity as _anchor_activity
    # date_dim runs to 2100 with date-part columns mis-tagged as measures — must NOT anchor.
    tp = _tpr(**{"main.date_dim": ("2015-01-01", "2100-01-01", 73_049),
                 "main.item":     ("2000-01-01", "2001-10-27", 18_000)})
    cp = {
        "main.date_dim": {f"d_{p}": {"semantic_type": "measure"}
                          for p in ("year", "moy", "dom", "qoy")},
        "main.item":     {"price": {"semantic_type": "measure"}},
    }
    table, rec, _eff = _anchor_activity(tp, cp)
    assert table == "main.item" and rec.startswith("2001")   # window lands in the real era
