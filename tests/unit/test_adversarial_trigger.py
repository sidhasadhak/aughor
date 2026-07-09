"""Confidence-tiered adversarial-verification trigger (T4-3, 2026-07-09).

ReFoRCE-style tiering: an expensive skeptic pass should fire ONLY on decision-changing verdicts
(a premise rejection — "X is not the problem" — or an abstention — "within normal variance"), not
on every finding. `is_decision_changing_verdict` is the deterministic gate; the refuter itself
(`run_refutation`) is flag-gated (`ada.adversarial_verify`, default off) so the default path stays
deterministic. See aughor/agent/orchestrator.py + investigate.py.
"""
from aughor.agent.orchestrator import is_decision_changing_verdict
from aughor.kernel.flags import flag_enabled


def test_premise_rejection_is_decision_changing():
    assert is_decision_changing_verdict("Fragrance is not the problem — the premise is inverted", "") is True
    assert is_decision_changing_verdict("The data shows X is actually lower than peers", "") is True


def test_abstention_is_decision_changing():
    assert is_decision_changing_verdict("2024 revenue decline is within normal variance", "") is True
    assert is_decision_changing_verdict("No anomaly was detected in the series", "") is True
    assert is_decision_changing_verdict("This is not a structural break", "") is True


def test_ordinary_driver_verdict_is_not_decision_changing():
    """A normal 'X fell, driven by Y' conclusion is NOT high-stakes — don't spend a refuter on it."""
    assert is_decision_changing_verdict("Revenue fell 6.6%, driven by Meta channel weakness",
                                        "Meta collapsed -22%; volume-driven.") is False
    assert is_decision_changing_verdict("Fragrance refunds are driven by scent intensity (66%)", "") is False


def test_flag_is_off_by_default():
    """The adversarial pass must not change the default deterministic path."""
    assert flag_enabled("ada.adversarial_verify") is False


def test_refuter_alias_is_public_and_callable():
    from aughor.agent.explore import run_refutation
    assert callable(run_refutation)
