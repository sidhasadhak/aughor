"""Temporal Tier 1 — current-regime detection. See aughor/explorer/regime.py."""
from aughor.explorer.regime import detect_current_regime, adaptive_window


def test_flat_series_has_no_regime_shift():
    r = detect_current_regime([100] * 30)
    assert r.changepoint is None and r.start == 0


def test_recent_level_jump_starts_a_new_regime():
    # 18 low periods then 12 high periods (a 3x volume jump).
    counts = [100] * 18 + [320] * 12
    r = detect_current_regime(counts)
    assert r.changepoint == 18, r
    assert r.start == 18
    assert r.before_level < r.after_level


def test_short_series_falls_back_to_full_span():
    r = detect_current_regime([10, 50, 10, 60])  # < 2*min_periods
    assert r.start == 0 and r.changepoint is None


def test_small_wobble_is_not_a_regime():
    # ±10% noise around a stable level must NOT trip a regime.
    counts = [100, 110, 95, 105, 100, 98, 102, 97, 103, 101, 99, 100, 104, 96, 100, 100]
    r = detect_current_regime(counts)
    assert r.changepoint is None, r


def test_drop_to_a_lower_regime_is_detected():
    counts = [500] * 14 + [120] * 10   # demand collapses
    r = detect_current_regime(counts)
    assert r.changepoint == 14
    assert r.before_level > r.after_level


def test_adaptive_window_maps_regime_to_dates():
    periods = [f"2021-{m:02d}-01" for m in range(1, 13)] + [f"2022-{m:02d}-01" for m in range(1, 13)]
    counts = [100] * 12 + [400] * 12   # regime shift at the 2022 boundary (index 12)
    start, end, reason = adaptive_window(periods, counts)
    assert start == "2022-01-01", start
    assert end == "2022-12-01"
    assert "regime shift" in reason


def test_adaptive_window_full_span_when_stable():
    periods = [f"2022-{m:02d}-01" for m in range(1, 13)]
    counts = [100] * 12
    start, end, reason = adaptive_window(periods, counts)
    assert start == "2022-01-01" and end == "2022-12-01"
    assert "full span" in reason


def test_adaptive_window_rejects_mismatched_inputs():
    assert adaptive_window(["2022-01-01"], [1, 2, 3]) == (None, None, "no usable activity series")
