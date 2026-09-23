"""CP-2 — the calibration fold, and the trap it refuses to fall into.

CP-2 was drafted as "publish an ECE for the treatment Choice". Building it showed that
clause to be wrong: expected calibration error needs to know which predictions were RIGHT,
and "how much work this ask deserved" is a judgement no run records.

The obvious substitute is the dangerous one. `ran` sits in every row, and scoring the judged
treatment against it would produce a confident-looking number measuring fidelity to a
baseline the census proved broken — the path that picks `deep_analysis` 0 times in 60 tool
uses. These tests pin that `ran` is used ONLY as the arc's falsifier and never as accuracy.

Two levers the run labels itself do get a real ECE, from a real outcome, with no model call.
"""
from __future__ import annotations

import pytest

from aughor.judgment.calibration import NO_LABEL, calibrate


def _row(**kw):
    base = {"treatment": "multi_query", "treatment_p": 0.9, "ran": "quick", "agreed": False}
    base.update(kw)
    return base


# ── what the run can label ───────────────────────────────────────────────────────────────

def test_steps_implied_is_scored_against_the_queries_that_actually_ran():
    """A real label from a real outcome: the turn ran two grids, and a prediction of "two or
    three" was right."""
    rows = [_row(steps_implied_score=2.0, steps_implied_p=0.8, observed_grids=2),
            _row(steps_implied_score=2.0, steps_implied_p=0.8, observed_grids=3)]
    got = calibrate(rows)["levers"]["steps_implied"]
    assert got["available"] and got["n"] == 2
    assert got["ece"] == pytest.approx(0.2, abs=1e-6), "confident 0.8, right 2 of 2"


def test_a_prediction_is_scored_against_its_BAND_not_an_exact_count():
    """The levels are ranges, so predicting 2.6 for a turn that ran three queries is a GOOD
    prediction. Scoring it wrong would make the number measure the scale's granularity
    rather than the judge."""
    inside = calibrate([_row(steps_implied_score=2.4, steps_implied_p=0.9, observed_grids=3)])
    outside = calibrate([_row(steps_implied_score=2.4, steps_implied_p=0.9, observed_grids=9)])
    assert inside["levers"]["steps_implied"]["bins"][0]["accuracy"] == 1.0
    assert outside["levers"]["steps_implied"]["bins"][0]["accuracy"] == 0.0


def test_from_last_result_is_right_exactly_when_no_query_ran():
    rows = [_row(from_last_result=True, from_last_result_p=0.7, observed_grids=0),
            _row(from_last_result=True, from_last_result_p=0.7, observed_grids=2)]
    got = calibrate(rows)["levers"]["from_last_result"]
    assert got["available"] and got["n"] == 2
    assert got["bins"][0]["accuracy"] == 0.5


def test_an_empty_corpus_is_unavailable_not_a_perfect_score():
    """The most misleading number this module could produce is a perfect ECE over no
    predictions."""
    got = calibrate([])
    assert got["rows"] == 0
    assert got["levers"]["steps_implied"]["available"] is False
    assert "empty" in got["levers"]["steps_implied"]["reason"]


def test_a_row_with_no_observed_outcome_cannot_be_scored():
    """A shadow written before CP-2's outcome capture carries a prediction and no label. It
    must not be counted as either right or wrong."""
    got = calibrate([_row(steps_implied_score=2.0, steps_implied_p=0.8)])
    assert got["levers"]["steps_implied"]["available"] is False


# ── what it refuses to label ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lever", sorted(NO_LABEL))
def test_every_unlabellable_lever_says_WHY_rather_than_going_missing(lever):
    """A report that silently omitted them would read as "these were fine". Each reason is
    its own, because two of these are one labelling session away and two are not."""
    got = calibrate([_row()])["levers"][lever]
    assert got["available"] is False and len(got["reason"]) > 40


def test_the_treatment_is_NEVER_given_an_ECE_from_what_ran():
    """The trap, asserted directly. Every row here agrees with `ran` and states 0.9
    confidence — a scorer that used `ran` as truth would report a beautiful ECE. There must
    be no ECE at all.
    """
    rows = [_row(ran="multi_query", agreed=True) for _ in range(20)]
    got = calibrate(rows)
    t = got["levers"]["treatment"]
    assert t["available"] is False
    assert "ece" not in t
    assert "broken baseline" in t["reason"]


def test_agreement_is_reported_as_the_FALSIFIER_and_labelled_as_such():
    """It is a real and useful number — "is there any decision here to take" — so it is
    reported, with the reading attached so nobody quotes it as accuracy."""
    rows = [_row(agreed=True)] * 9 + [_row(agreed=False)]
    f = calibrate(rows)["falsifier"]
    assert f["rows_with_a_treatment"] == 10 and f["agreed_with_what_ran"] == 9
    assert f["agreement"] == pytest.approx(0.9)
    assert "NOT an accuracy score" in f["reading"]
