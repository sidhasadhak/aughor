"""Sustained level-shift significance — the point-anomaly blind spot (2026-07-09).

Deep-Analysis audit finding (inv3): a "why did revenue decline in 2024 vs 2023?" investigation
divided the two-year mean gap by a single-MONTH sigma (z=-0.86) — wrong by √n — and dismissed a
real, statistically-significant −6.4% decline as "within normal variance", then aborted the entire
dimensional decomposition at Tier 0. Single-point anomaly detection is structurally blind to a
sustained shift where no individual month is an outlier. `mean_shift_significance` is the correct
two-sample (Welch) test; `_analyze_time_series` now reports the STRONGER of point-anomaly and
level-shift so the Tier-0 gate proceeds on a real decline. See aughor/tools/stats.py.
"""
from aughor.tools.stats import mean_shift_significance, _analyze_time_series


# Real inv3 monthly net revenue: 2023 (higher) then 2024 (lower) — a sustained −6.4% decline.
INV3_REVENUE = [
    115137, 96201, 116683, 106558, 111371, 106232, 118369, 106129, 94952, 110281, 97351, 101978,
    100859, 95898, 99424, 97421, 104377, 98980, 98016, 102663, 101786, 100895, 96658, 101990,
]
# Real inv4 monthly refund amounts — genuinely flat, ±noise, no sustained shift.
INV4_REFUNDS = [
    5725, 15394, 13554, 7162, 15553, 10471, 7402, 14008, 9389, 9873, 11084, 7615,
    14427, 9552, 10212, 13841, 6941, 11629, 10075, 6405, 12494, 10311, 8603, 11902,
]


def test_sustained_decline_is_significant():
    """inv3's −6.4% two-year decline: no single month is an outlier, but the two halves' means
    differ significantly — the case single-point anomaly detection missed."""
    r = mean_shift_significance(INV3_REVENUE)
    assert r is not None
    assert r.is_significant is True
    assert r.rel_change < 0                    # a decline
    assert abs(r.t_stat) > 2.0                 # ≈ -2.83, well past the gate's 1.5/2.0
    assert r.p_value < 0.05


def test_flat_series_is_not_significant():
    """inv4's flat refund series must NOT trip the shift test — the clean Tier-0 rejection
    (premise 'refunds spiked' is false) must be preserved."""
    r = mean_shift_significance(INV4_REFUNDS)
    assert r is not None
    assert r.is_significant is False
    assert abs(r.rel_change) < 0.03            # immaterial


def test_trivial_significant_shift_gated_by_effect_size():
    """A tiny but statistically-'significant' wobble on a tight series must be gated out by the
    material-effect floor so it doesn't force expensive downstream phases."""
    # Two tight clusters 1% apart — p may be small but the effect is immaterial.
    tight = [1000, 1001, 999, 1000, 1002, 998, 1010, 1011, 1009, 1010, 1012, 1008]
    r = mean_shift_significance(tight)
    assert r is not None
    # 1% shift is below the 3% material-effect floor → not flagged regardless of p.
    assert r.is_significant is False


def test_clear_ramp_is_significant():
    ramp = [100, 105, 110, 108, 115, 120, 125, 130, 128, 135, 140, 145]
    r = mean_shift_significance(ramp)
    assert r is not None and r.is_significant is True and r.rel_change > 0


def test_too_short_returns_none():
    assert mean_shift_significance([100, 110, 120]) is None       # < 2*min_per_group
    assert mean_shift_significance([]) is None


def test_analyze_time_series_reports_level_shift_sigma():
    """The gate reads `sigma`/`is_significant` off _analyze_time_series; a sustained decline must
    surface a sigma ≥ ~2 so route_after_baseline proceeds instead of dismissing it as noise."""
    sr = _analyze_time_series("net_revenue", INV3_REVENUE)
    assert sr.is_significant is True
    assert sr.sigma is not None and sr.sigma > 2.0


def test_analyze_time_series_flat_stays_insignificant():
    sr = _analyze_time_series("refund_amt", INV4_REFUNDS)
    assert sr.is_significant is False
    assert sr.sigma is not None and sr.sigma < 1.5
