"""Rate confidence intervals + segment-uniformity assessment (2026-06-26).

The Swiss-Air deep analysis reported a ~2.5% refund rate that was flat across every
dimension, then dismissed elevated small-sample segments (5.88% on 85 tickets) by
eyeballing. These primitives make that rigorous: Wilson CIs per segment + a two-
proportion test vs the pooled rest, Bonferroni-corrected, yielding an explicit
"uniform / no signal" verdict instead of a hunch. See aughor/tools/stats.py.
"""
from aughor.tools.stats import (
    proportion_ci,
    two_proportion_pvalue,
    assess_rate_uniformity,
    _analyze_rate_segments,
)


def test_proportion_ci_brackets_the_rate():
    lo, hi = proportion_ci(25, 1000)  # 2.5%
    assert lo < 0.025 < hi
    assert 0.015 < lo and hi < 0.04   # tight-ish for n=1000


def test_proportion_ci_is_wide_for_small_n():
    # 5/85 ≈ 5.88% but with a huge interval reaching well past a 2.5% baseline — the
    # apparent "spike" is not distinguishable from baseline. (Wilson's lower edge sits
    # right around 2.5%; the segment-vs-rest test is what decides significance.)
    lo, hi = proportion_ci(5, 85)
    assert hi - lo > 0.08            # very wide
    assert hi > 0.12                 # upper bound far above the 2.5% baseline
    assert lo < 0.04                 # lower bound near the baseline


def test_two_proportion_pvalue_identical_rates_not_significant():
    assert two_proportion_pvalue(25, 1000, 25, 1000) > 0.9


def test_two_proportion_pvalue_clear_difference_is_significant():
    assert two_proportion_pvalue(250, 1000, 25, 1000) < 0.001


def test_swiss_air_uniform_rates_flagged_no_signal():
    # Six segments hovering at ~2.5% with a couple of noisy small-sample "spikes".
    segments = [
        ("on_time", 6800, 270000),       # 2.52%
        ("delay_60+", 24, 870),          # 2.76%
        ("ZRH-EZE prem_econ", 5, 85),    # 5.88% — small sample
        ("GVA-TLV business", 14, 302),   # 4.64% — small sample
        ("longhaul_business", 170, 6726),# 2.53%
        ("lead_8_30d", 2880, 114000),    # 2.53%
    ]
    res = assess_rate_uniformity(segments)
    assert res is not None
    assert res.all_uniform is True
    assert res.n_significant == 0
    assert "NO SIGNAL" in res.interpretation
    assert 0.024 < res.baseline_rate < 0.027


def test_genuine_outlier_segment_is_detected():
    # One segment is massively different on a large sample → real signal.
    segments = [
        ("a", 250, 10000),   # 2.5%
        ("b", 255, 10000),   # 2.55%
        ("c", 248, 10000),   # 2.48%
        ("d", 1200, 10000),  # 12% — clearly different, big sample
    ]
    res = assess_rate_uniformity(segments)
    assert res is not None
    assert res.all_uniform is False
    assert res.n_significant >= 1
    assert any(sr.label == "d" and sr.significant for sr in res.segments)


def test_too_few_segments_returns_none():
    assert assess_rate_uniformity([("only", 5, 100)]) is None


def test_detector_reconstructs_from_rate_and_denominator_columns():
    # Mirrors the Swiss-Air SQL output shape: label, total_tickets, refund_rate.
    columns = ["segment", "total_tickets", "refund_rate"]
    rows = [
        ["on_time", 270000, 0.0252],
        ["delay_30", 5000, 0.0260],
        ["delay_60", 870, 0.0276],
        ["longhaul_biz", 6726, 0.0253],
    ]
    stat = _analyze_rate_segments(columns, rows)
    assert stat is not None
    assert stat.type == "uniformity"
    assert stat.is_significant is False
    assert "NO SIGNAL" in stat.interpretation


def test_detector_handles_percent_scale():
    columns = ["segment", "n_orders", "conversion_pct"]
    rows = [
        ["a", 5000, 2.5],
        ["b", 4800, 2.6],
        ["c", 5200, 2.4],
    ]
    stat = _analyze_rate_segments(columns, rows)
    assert stat is not None
    assert stat.type == "uniformity"


def test_detector_stays_silent_without_a_denominator():
    # No count column to anchor n → no confident reconstruction → silence.
    columns = ["segment", "refund_rate"]
    rows = [["a", 0.025], ["b", 0.026], ["c", 0.024]]
    assert _analyze_rate_segments(columns, rows) is None
