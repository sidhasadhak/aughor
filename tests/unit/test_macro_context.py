"""Temporal Tier 2 — full-span macro context (long-arc rollup).

Builds the cheap coarse rollup the briefing juxtaposes against the recent regime.
See aughor/explorer/temporal.py + docs/ADAPTIVE_TEMPORAL_SCOPE.md §5.
"""
from aughor.explorer.temporal import build_macro_context, render_macro_context, _fmt, _growth


# ── helpers ───────────────────────────────────────────────────────────────────

def test_fmt_compact():
    assert _fmt(1234) == "1.2k"
    assert _fmt(3_900_000) == "3.9M"
    assert _fmt(2_100_000_000) == "2.1B"
    assert _fmt(42) == "42"


def test_growth_descriptors():
    assert "grew" in _growth(100, 410)
    assert "shrank" in _growth(100, 40)
    assert _growth(100, 105) == "held roughly flat"
    assert _growth(0, 100) is None       # undefined from zero base


# ── build_macro_context ───────────────────────────────────────────────────────

def test_build_basic_growth():
    periods = ["2018", "2019", "2020", "2021"]
    counts  = [1000, 2000, 3000, 4000]
    ctx = build_macro_context(periods, counts, micro_start="2021-01-01", anchor="orders")
    assert ctx is not None
    assert ctx["first_period"] == "2018" and ctx["last_period"] == "2021"
    assert ctx["n_periods"] == 4
    assert "grew 4.0×" in ctx["rows_growth"]
    assert ctx["micro_start"] == "2021-01-01"
    assert ctx["anchor"] == "orders"
    assert ctx["measure_name"] is None


def test_build_with_measure():
    periods = ["2019", "2020", "2021"]
    counts  = [500, 800, 1200]
    measures = [1_000_000, 2_000_000, 3_200_000]
    ctx = build_macro_context(periods, counts, measures=measures,
                              measure_name="revenue", anchor="orders")
    assert ctx["measure_name"] == "revenue"
    assert "grew 3.2×" in ctx["measure_growth"]
    assert ctx["measure_first"] == 1_000_000 and ctx["measure_last"] == 3_200_000


def test_build_filters_sentinel_years():
    # 9999 and 1900 placeholders must be dropped before computing the arc.
    periods = ["1900", "2020", "2021", "2022", "9999"]
    counts  = [9, 100, 200, 400, 7]
    ctx = build_macro_context(periods, counts)
    assert ctx["first_period"] == "2020" and ctx["last_period"] == "2022"
    assert ctx["n_periods"] == 3


def test_build_too_short_returns_none():
    assert build_macro_context(["2021"], [100]) is None
    assert build_macro_context(["9999", "2021"], [5, 100]) is None  # only 1 real period
    # Default gate is 3 periods: a 2-year span (with a likely-partial boundary year)
    # is suppressed rather than reported as misleading YoY growth.
    assert build_macro_context(["2024", "2025"], [100, 310]) is None


def test_build_min_periods_override():
    # Callers can lower the bar when they know the endpoints are complete years.
    ctx = build_macro_context(["2024", "2025"], [100, 310], min_periods=2)
    assert ctx is not None and ctx["n_periods"] == 2


def test_build_mismatched_lengths_returns_none():
    assert build_macro_context(["2020", "2021"], [100]) is None


def test_build_series_capped_to_12():
    periods = [str(2000 + i) for i in range(20)]
    counts  = [100 + i for i in range(20)]
    ctx = build_macro_context(periods, counts)
    assert len(ctx["series"]) == 12          # only the most recent 12 kept
    assert ctx["series"][-1]["period"] == "2019"
    assert ctx["n_periods"] == 20            # but the count reflects the full span


# ── render_macro_context ──────────────────────────────────────────────────────

def test_render_includes_arc_and_juxtaposition():
    ctx = build_macro_context(["2018", "2019", "2020", "2021"],
                              [1000, 2000, 3000, 4000],
                              measures=[1e6, 2e6, 3e6, 4e6], measure_name="revenue",
                              micro_start="2021-01-01", anchor="orders")
    block = render_macro_context(ctx)
    assert "LONG-ARC CONTEXT" in block
    assert "2018 → 2021" in block
    assert "orders" in block
    assert "revenue" in block
    assert "2021-01-01" in block          # juxtaposition line present


def test_render_empty_when_absent():
    assert render_macro_context(None) == ""
    assert render_macro_context({}) == ""
