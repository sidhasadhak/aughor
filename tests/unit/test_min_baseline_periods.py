"""A z over a two-month baseline is not a significance verdict — CA-2.

Receipt run b817b074 (2026-08-19): the baseline narrator wrote stat_note "z = 3.8 — significant"
from its own SQL's z-score over a baseline of two monthly points, and the phase summary called
the rise "statistically significant". stats.py's own test requires ≥10 points and had stayed
silent; `code_significant` then fell back to the model's flag.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.investigate import (
    _MIN_BASELINE_PERIODS,
    _longest_period_series,
    _neutralize_short_baseline_z,
)


def _res(columns, rows):
    return SimpleNamespace(columns=columns, rows=rows, error=None, row_count=len(rows), sql="SELECT 1")


def test_longest_period_series_counts_rows_of_the_longest_dated_result():
    results = [
        (None, _res(["period", "total_traffic"], [["2026-06-01", 1], ["2026-07-01", 2], ["2026-08-01", 3]])),
        (None, _res(["obs_traffic", "mean_traffic", "z_score"], [[50229, 25255.5, 3.8]])),   # no period column
    ]
    assert _longest_period_series(results) == 3
    assert _longest_period_series([(None, _res(["a", "b"], [[1, 2]]))]) is None


def test_short_baseline_z_is_rewritten_into_a_description():
    findings = [
        {"finding_id": "baseline_0", "stat_note": None, "is_significant": False},
        {"finding_id": "baseline_2", "stat_note": "z = 3.8 — significant", "is_significant": True},
        {"finding_id": "baseline_1", "stat_note": None, "is_significant": True},   # model flag, no z
    ]
    n = _neutralize_short_baseline_z(findings, n_periods=3)
    assert n == 2
    assert findings[1]["stat_note"].startswith("z = 3.8 was computed over a baseline of 2 period(s) — not a significance verdict")
    assert f"at least {_MIN_BASELINE_PERIODS}" in findings[1]["stat_note"]
    assert findings[1]["is_significant"] is False and findings[2]["is_significant"] is False
    assert findings[0]["stat_note"] is None


def test_the_threshold_is_six_periods():
    # the caller gates on _longest_period_series < _MIN_BASELINE_PERIODS; a z over a baseline
    # of five or more points is left to stand as the model wrote it
    assert _MIN_BASELINE_PERIODS == 6
    results = [(None, _res(["period", "v"], [[f"2026-0{m}-01", m] for m in range(1, 8)]))]
    assert _longest_period_series(results) == 7 >= _MIN_BASELINE_PERIODS
