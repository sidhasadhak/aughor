"""Confidence-tiered adversarial-verification trigger (T4-3, 2026-07-09).

ReFoRCE-style tiering: an expensive skeptic pass should fire ONLY on decision-changing verdicts
(a premise rejection — "X is not the problem" — or an abstention — "within normal variance"), not
on every finding. `is_decision_changing_verdict` is the deterministic gate; the refuter itself
(`run_refutation`) is gated by the materiality tier (`ada.adversarial_high_stakes`, auto-eligible)
so the default path stays deterministic. See aughor/agent/orchestrator.py + investigate.py.
"""
from aughor.agent.orchestrator import is_decision_changing_verdict


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


def test_the_full_tier_stays_deleted_and_the_auto_tier_remains():
    """`ada.adversarial_verify` (challenge EVERY decision-changing verdict) was deleted
    2026-07-31 (flag strategy §4G) — superseded by the materiality-gated auto tier. A
    re-registration would silently resurrect an LLM call per decision-changing verdict."""
    from aughor.kernel.flags import AUTO_ELIGIBLE, FLAG_ENV

    assert "ada.adversarial_verify" not in FLAG_ENV
    assert "ada.adversarial_high_stakes" in FLAG_ENV
    assert "ada.adversarial_high_stakes" in AUTO_ELIGIBLE


def test_refuter_alias_is_public_and_callable():
    from aughor.agent.explore import run_refutation
    assert callable(run_refutation)
