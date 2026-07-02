"""Characterization of the ambiguity-detection eval (evals/ambiguity_eval.py).

Locks the measure-before-trust finding for 3b: the deterministic two-source detector has 0% false
positives and full recall on under-specification + value-term ambiguity, but is BLIND to structural
ambiguity (the SOMA candidate-disagreement gap). When SOMA lands and starts catching structural
cases, the `structural` assertion here will fail — that's the signal to update this test deliberately.
"""
from __future__ import annotations

from evals.ambiguity_eval import run


def test_detector_has_no_false_positives_on_well_specified():
    assert run()["none"]["asked"] == 0


def test_detector_recalls_underspecified_and_value_term():
    r = run()
    assert r["underspecified"]["rate"] == 1.0
    assert r["value_term"]["rate"] == 1.0


def test_structural_ambiguity_is_the_uncovered_gap():
    # The deterministic detector cannot see structural ambiguity (no pronoun, no qualifier).
    # This 0.0 is the size of the gap that justifies the SOMA candidate-disagreement half of 3b.
    assert run()["structural"]["rate"] == 0.0
