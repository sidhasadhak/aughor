"""Hermetic unit tests for the overview mode's pure notability math.

Pure, fast, no DB, no LLM — every assertion runs against ``aughor.overview.metrics``
directly. Covers the share/concentration/spread/deviation helpers, the ``notability_*``
normalizers (bounds + monotonicity), and TOTALITY: none of the sequence-taking helpers
may raise on ``[]`` / ``[None]`` / ``[0]`` / mixed signs / non-numeric strings.
"""
from __future__ import annotations

import math

import pytest

from aughor.overview import metrics as M


# ── shares() ──────────────────────────────────────────────────────────────────

def test_shares_normalizes_to_sum_one():
    s = M.shares([80, 10, 10])
    assert s == pytest.approx([0.8, 0.1, 0.1])
    assert sum(s) == pytest.approx(1.0)


def test_shares_arbitrary_vector_sums_to_one():
    assert sum(M.shares([3, 1, 1])) == pytest.approx(1.0)


def test_shares_empty_and_zero_total():
    assert M.shares([]) == []
    assert M.shares([0, 0]) == []
    assert M.shares([0]) == []


def test_shares_uses_abs_for_negatives():
    # magnitude, not sign — a −80 group is 80% of the absolute total
    assert M.shares([-80, 10, 10]) == pytest.approx([0.8, 0.1, 0.1])
    assert M.shares([-5, -5]) == pytest.approx([0.5, 0.5])


def test_shares_drops_none_and_nan():
    assert M.shares([1, None, 2]) == pytest.approx([1 / 3, 2 / 3])
    assert M.shares([float("nan"), 1.0]) == pytest.approx([1.0])


def test_shares_drops_non_numeric_strings():
    assert M.shares(["x", 2, 3]) == pytest.approx([0.4, 0.6])


# ── hhi() ─────────────────────────────────────────────────────────────────────

def test_hhi_single_group_is_one():
    assert M.hhi([5]) == pytest.approx(1.0)
    assert M.hhi([12345]) == pytest.approx(1.0)


def test_hhi_n_equal_groups_is_one_over_n():
    assert M.hhi([1, 1, 1, 1]) == pytest.approx(0.25)      # 4 equal → 1/4
    assert M.hhi([1, 1, 1, 1, 1]) == pytest.approx(0.2)    # 5 equal → 1/5


def test_hhi_higher_for_skewed():
    assert M.hhi([98, 1, 1]) > M.hhi([34, 33, 33])


def test_hhi_monotonic_concentrated_beats_even():
    assert M.hhi([90, 5, 5]) > M.hhi([34, 33, 33])


def test_hhi_degenerate_is_zero():
    assert M.hhi([]) == 0.0
    assert M.hhi([0]) == 0.0


# ── top_share() ───────────────────────────────────────────────────────────────

def test_top_share_top1():
    assert M.top_share([80, 10, 10]) == pytest.approx(0.8)
    assert M.top_share([80, 10, 10], 1) == pytest.approx(0.8)


def test_top_share_top2_sums_two():
    assert M.top_share([80, 10, 10], 2) == pytest.approx(0.9)


def test_top_share_is_by_magnitude_not_position():
    # the largest slice wins regardless of input order
    assert M.top_share([10, 80, 10], 1) == pytest.approx(0.8)


def test_top_share_empty():
    assert M.top_share([], 1) == 0.0
    assert M.top_share([0, 0], 2) == 0.0


# ── gini() ────────────────────────────────────────────────────────────────────

def test_gini_all_equal_is_zero():
    assert M.gini([5, 5, 5]) == pytest.approx(0.0)
    assert M.gini([1, 1, 1, 1]) == pytest.approx(0.0)


def test_gini_one_takes_all_is_high():
    # n=3, one group holds everything → (n-1)/n = 0.6667
    assert M.gini([0, 0, 100]) == pytest.approx(2 / 3, abs=1e-9)
    assert M.gini([0, 0, 100]) > 0.6


def test_gini_fewer_than_two_values_is_zero():
    assert M.gini([5]) == 0.0
    assert M.gini([]) == 0.0


def test_gini_monotonic_unequal_beats_equal():
    assert M.gini([0, 0, 100]) > M.gini([10, 10, 10])


# ── skew_ratio() ──────────────────────────────────────────────────────────────

def test_skew_ratio_mean_over_median():
    assert M.skew_ratio(20, 10) == pytest.approx(2.0)
    assert M.skew_ratio(313, 97) == pytest.approx(313 / 97)


def test_skew_ratio_symmetric_is_one():
    assert M.skew_ratio(5, 5) == pytest.approx(1.0)


def test_skew_ratio_zero_or_none_median():
    assert M.skew_ratio(10, 0) == 0.0
    assert M.skew_ratio(10, None) == 0.0
    assert M.skew_ratio(None, 10) == 0.0


# ── spread_ratio() ────────────────────────────────────────────────────────────

def test_spread_ratio_hi_over_lo():
    assert M.spread_ratio(6, 19719) == pytest.approx(3286.5)  # the fare-span example (~3286×)


def test_spread_ratio_uses_magnitude():
    assert M.spread_ratio(-5, 10) == pytest.approx(2.0)
    assert M.spread_ratio(10, 5) == pytest.approx(0.5)


def test_spread_ratio_zero_or_none_lo():
    assert M.spread_ratio(0, 10) == 0.0
    assert M.spread_ratio(None, 10) == 0.0


# ── deviation() ───────────────────────────────────────────────────────────────

def test_deviation_signed_relative_to_median():
    assert M.deviation(15, [10, 10, 10]) == pytest.approx(0.5)   # +50% above typical
    assert M.deviation(5, [10, 10, 10]) == pytest.approx(-0.5)   # −50% below


def test_deviation_needs_two_peers():
    assert M.deviation(10, [5]) == pytest.approx(0.0)
    assert M.deviation(10, []) == pytest.approx(0.0)


def test_deviation_zero_median():
    assert M.deviation(10, [0, 0]) == 0.0


def test_deviation_robust_to_outlier_uses_median_not_mean():
    # median of [10,10,20,20,100] is 20 → (100−20)/20 = 4.0; the MEAN (32) would give 2.125
    assert M.deviation(100, [10, 20, 10, 20, 100]) == pytest.approx(4.0)


# ── notability normalizers: bounds ────────────────────────────────────────────

_UNIT = [0.0, 0.1, 0.25, 0.33, 0.5, 0.75, 0.9, 1.0]


def test_notability_concentration_bounds():
    for h in _UNIT:
        for t in _UNIT:
            v = M.notability_concentration(h, t)
            assert 0.0 <= v <= 1.0


def test_notability_deviation_bounds():
    for r in (-10, -2, -1, -0.45, 0, 0.45, 1, 2, 10):
        v = M.notability_deviation(r)
        assert 0.0 <= v <= 1.0


def test_notability_skew_bounds():
    for r in (0, 0.5, 1, 1.5, 2, 3, 10, 100):
        v = M.notability_skew(r)
        assert 0.0 <= v <= 1.0


def test_notability_spread_bounds():
    for r in (0.1, 0.5, 1, 2, 10, 100, 1000, 1e6):
        v = M.notability_spread(r)
        assert 0.0 <= v <= 1.0


def test_notability_coverage_bounds():
    for nr in (0.0, 0.1, 0.35, 0.5, 0.9, 1.0):
        assert 0.0 <= M.notability_coverage(null_rate=nr) <= 1.0
    for rows in (0, 1, 100, 5000, 261610, 10_000_000):
        assert 0.0 <= M.notability_coverage(untouched_rows=rows) <= 1.0
    assert 0.0 <= M.notability_coverage(single_value=True) <= 1.0


# ── notability normalizers: monotonicity + shape ──────────────────────────────

def test_notability_concentration_rises_with_hhi_and_top1():
    assert M.notability_concentration(0.6, 0.0) > M.notability_concentration(0.2, 0.0)
    assert M.notability_concentration(0.0, 0.9) > M.notability_concentration(0.0, 0.5)
    assert M.notability_concentration(0.6, 0.9) > M.notability_concentration(0.1, 0.4)


def test_notability_deviation_rises_with_abs_and_is_symmetric():
    assert M.notability_deviation(1.0) > M.notability_deviation(0.2)
    assert M.notability_deviation(-1.0) == pytest.approx(M.notability_deviation(1.0))
    assert M.notability_deviation(0.0) == pytest.approx(0.0)


def test_notability_skew_zero_at_symmetric_and_rises():
    assert M.notability_skew(1.0) == pytest.approx(0.0)
    assert M.notability_skew(1.6) == pytest.approx(0.5)     # mean/median 1.5 half-saturation
    assert M.notability_skew(3) > M.notability_skew(1.5)


def test_notability_spread_zero_below_one_and_rises():
    assert M.notability_spread(1.0) == 0.0
    assert M.notability_spread(0.5) == 0.0
    assert M.notability_spread(1000) > M.notability_spread(10)


def test_notability_coverage_single_value_and_untouched_positive():
    assert M.notability_coverage(single_value=True) > 0.0
    assert M.notability_coverage(untouched_rows=100000) > M.notability_coverage(untouched_rows=0)
    assert M.notability_coverage(null_rate=0.5) > M.notability_coverage(null_rate=0.1)


# ── TOTALITY — no helper may raise on degenerate input ────────────────────────

_DEGENERATE_SEQS = [
    [],
    [None],
    [0],
    [0, 0],
    [-1, 2, -3],
    ["a", "b"],
    [None, "x", 3],
    [float("nan")],
    [float("nan"), None],
    "not-a-list-but-iterable",   # each char is a non-numeric str → all dropped
]


@pytest.mark.parametrize("seq", _DEGENERATE_SEQS)
def test_vector_helpers_are_total(seq):
    # never raises; returns the documented type on any degenerate sequence
    assert isinstance(M.shares(seq), list)
    assert isinstance(M.hhi(seq), float)
    assert isinstance(M.top_share(seq, 1), float)
    assert isinstance(M.top_share(seq, 2), float)
    assert isinstance(M.gini(seq), float)
    # deviation's `value` is a documented float; its `peers` sequence is the total surface
    assert isinstance(M.deviation(1.0, seq), float)


@pytest.mark.parametrize("bad", [None, "a", "", [], {}])
def test_ratio_helpers_are_total_on_non_numeric_scalars(bad):
    # skew_ratio / spread_ratio guard their float() coercion → 0.0, never raise
    assert isinstance(M.skew_ratio(bad, bad), float)
    assert isinstance(M.spread_ratio(bad, bad), float)
    assert M.skew_ratio(bad, 5) == 0.0     # a non-coercible numerator → 0.0
    assert M.spread_ratio(bad, 5) == 0.0   # a non-coercible lo → 0.0


def test_no_helper_leaves_a_nan_share_or_inf():
    # a real degenerate mix still produces finite, bounded outputs
    for out in (M.shares([1, float("nan"), 2]),):
        assert all(math.isfinite(x) for x in out)
