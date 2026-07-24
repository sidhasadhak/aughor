"""J3 — the fidelity harness (`aughor/evals/fidelity.py`).

Pure arithmetic over `RunSummary` objects, so these are the cheapest tests in the wave and
cover the claim the whole of E4 rests on: that a delta is only reported when the baseline
does not differ from *itself* by more.

The cases below are chosen around the ways a summary lies rather than around the API:
a delta inside the noise, a floor that was never established, an axis nothing measured, and
a composite that averages a broken dimension into respectability.
"""
from __future__ import annotations

import pytest

from aughor.evals.fidelity import (
    DEFAULT_FLOOR_THRESHOLD,
    assess,
    axis_of,
    compare,
    harmonic_composite,
    noise_floor,
)
from aughor.evals.runner import RunSummary


def _summary(pass_rate: float, accuracy: float | None = None, total: int = 100) -> RunSummary:
    """A RunSummary with the given axes — built from the real class, so these tests break if
    `pass_rate` / `accuracy` ever stop meaning what the harness assumes."""
    s = RunSummary(run_id="r", suite_id="s", iterations=1, total=total)
    s.stable_pass = round(pass_rate * total)
    if accuracy is not None:
        s.correctness_known = total
        s.correct = round(accuracy * total)
    return s


# ── the axis ──────────────────────────────────────────────────────────────────

def test_axis_reports_band_and_stdev_together():
    a = axis_of([_summary(0.60), _summary(0.66), _summary(0.63)], "pass_rate")
    assert a.n == 3
    assert a.mean == pytest.approx(0.63)
    assert a.band == pytest.approx(0.06)
    assert a.stdev > 0


def test_an_unmeasured_axis_is_absent_not_zero():
    """`accuracy` is None when no case declared an expectation. Folding that to 0.0 would
    report a suite that measured nothing as a suite that got everything wrong."""
    a = axis_of([_summary(0.6), _summary(0.6)], "accuracy")
    assert a.n == 0
    assert a.mean == 0.0


def test_axis_skips_only_the_replicates_that_lacked_it():
    a = axis_of([_summary(0.6, accuracy=0.5), _summary(0.6)], "accuracy")
    assert a.values == (0.5,)


# ── the floor ─────────────────────────────────────────────────────────────────

def test_a_single_replicate_is_no_floor_rather_than_a_floor_of_zero():
    """A floor of zero would make every delta attributable — the exact opposite of the
    conservative reading a single run deserves."""
    floor = noise_floor([_summary(0.64)])
    assert floor.verified is False
    assert floor.band == 0.0
    assert "never run against itself" in floor.reason


def test_a_configuration_that_disagrees_with_itself_fails_verification():
    floor = noise_floor([_summary(0.55), _summary(0.70)])
    assert floor.verified is False
    assert floor.band == pytest.approx(0.15)
    assert "disagrees with itself" in floor.reason


def test_a_stable_configuration_verifies_and_says_what_it_permits():
    floor = noise_floor([_summary(0.64), _summary(0.65), _summary(0.63)])
    assert floor.verified is True
    assert floor.band == pytest.approx(0.02)
    assert "attributable" in floor.reason


def test_the_threshold_is_the_one_the_golden_runner_already_used():
    assert DEFAULT_FLOOR_THRESHOLD == 0.05


# ── the comparison ────────────────────────────────────────────────────────────

def test_a_delta_inside_the_noise_is_refused_not_hedged():
    baseline = [_summary(0.60), _summary(0.64)]        # band 0.04, verified
    variant = [_summary(0.63), _summary(0.65)]         # +0.02 — inside the band
    d = compare(baseline, variant)
    assert d.attributable is False
    assert "inside the noise" in d.verdict
    assert "not an observation" in d.verdict


def test_a_delta_larger_than_the_floor_is_attributed_with_its_denominator():
    baseline = [_summary(0.60), _summary(0.61)]        # band 0.01
    variant = [_summary(0.75), _summary(0.76)]         # +0.15
    d = compare(baseline, variant)
    assert d.attributable is True
    assert d.delta == pytest.approx(0.15)
    assert "better" in d.verdict and "floor of 0.010" in d.verdict


def test_a_regression_is_attributed_too():
    d = compare([_summary(0.80), _summary(0.81)], [_summary(0.60), _summary(0.61)])
    assert d.attributable is True
    assert d.delta < 0
    assert "worse" in d.verdict


def test_no_delta_survives_an_unverified_floor_however_large_it_looks():
    """The headline case: a huge apparent win, on a baseline that cannot hold still."""
    baseline = [_summary(0.30), _summary(0.90)]        # band 0.60 — unverified
    variant = [_summary(0.95), _summary(0.96)]
    d = compare(baseline, variant)
    assert d.attributable is False
    assert "refusing to attribute" in d.verdict


def test_comparing_against_an_axis_nobody_measured_says_so():
    d = compare([_summary(0.6), _summary(0.61)], [_summary(0.7), _summary(0.71)],
                axis="accuracy")
    assert d.attributable is False
    assert "no measurement" in d.verdict


# ── the composite ─────────────────────────────────────────────────────────────

def test_one_broken_axis_zeroes_the_composite_where_a_mean_would_hide_it():
    axes = {"pass_rate": 1.0, "accuracy": 0.0}
    assert sum(axes.values()) / len(axes) == 0.5      # what an arithmetic mean would report
    assert harmonic_composite(axes) == 0.0


def test_the_composite_is_dominated_by_the_weakest_axis():
    assert harmonic_composite({"a": 0.9, "b": 0.1}) < 0.5


def test_equal_axes_give_back_that_value():
    assert harmonic_composite({"a": 0.6, "b": 0.6}) == pytest.approx(0.6)


def test_nothing_measured_is_not_a_pass():
    assert harmonic_composite({}) == 0.0
    assert harmonic_composite({"a": None}) == 0.0


# ── the whole report ──────────────────────────────────────────────────────────

def test_assess_floors_the_baseline_and_compares_every_other_cell():
    cells = {
        "baseline": [_summary(0.60, 0.60), _summary(0.61, 0.61)],
        "variant-a": [_summary(0.75, 0.75), _summary(0.76, 0.76)],
        "variant-b": [_summary(0.61, 0.61), _summary(0.62, 0.62)],
    }
    r = assess(cells, baseline="baseline")

    assert set(r.floors) == {"pass_rate", "accuracy"}
    assert all(f.verified for f in r.floors.values())
    by = {(d.variant, d.axis): d for d in r.deltas}
    assert by[("variant-a", "pass_rate")].attributable is True
    assert by[("variant-b", "pass_rate")].attributable is False   # +0.01, inside the band
    assert r.attributable is True


def test_assess_without_its_baseline_refuses_rather_than_picking_one():
    r = assess({"a": [_summary(0.6)]}, baseline="baseline")
    assert r.deltas == []
    assert r.attributable is False
    assert "not in the grid" in r.warnings[0]


def test_report_carries_the_fixture_stamp_into_its_summary():
    r = assess({"baseline": [_summary(0.6), _summary(0.61)]}, baseline="baseline",
               fixture={"data_version": "fp:abc123"})
    assert r.fixture == {"data_version": "fp:abc123"}
    assert "fp:abc123" in r.summary_lines()[0]


def test_report_round_trips_to_dict():
    r = assess({"baseline": [_summary(0.6, 0.6), _summary(0.61, 0.61)],
                "v": [_summary(0.8, 0.8), _summary(0.81, 0.81)]}, baseline="baseline")
    d = r.to_dict()
    assert d["attributable"] is True
    assert set(d["axes"]) == {"baseline", "v"}
    assert d["composite"]["v"] > d["composite"]["baseline"]
