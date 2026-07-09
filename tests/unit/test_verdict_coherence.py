"""Verdict↔recommendation self-coherence check (T4-4, 2026-07-09).

Deep-Analysis audit finding (inv1 original): the report shipped headline "the premise is inverted,
Fragrance is not the problem segment" WHILE every recommendation prescribed action on Fragrance, and
the contradiction_report reported severity "none" — because the cross-phase detector inspects only
phase summaries, never headline-vs-recommendations. `detect_verdict_recommendation_incoherence` is a
deterministic backstop. See aughor/agent/orchestrator.py.
"""
from aughor.agent.orchestrator import detect_verdict_recommendation_incoherence, ContradictionReport


def _rec(action):
    return {"action": action, "expected_impact": "", "owner": "", "timeline": ""}


def test_premise_inverted_with_actionable_recs_flags():
    c = detect_verdict_recommendation_incoherence(
        headline="Fragrance is not the problem — the premise is inverted",
        executive_summary="Fragrance actually shows the lower refund rate.",
        recommendations=[_rec("Reformulate Fragrance products to reduce scent intensity"),
                         _rec("Add allergy warnings to Fragrance PDPs")])
    assert c is not None
    assert c.kind == "verdict_recommendation_incoherence"
    assert c.severity == "high"


def test_abstention_with_actionable_recs_flags():
    c = detect_verdict_recommendation_incoherence(
        headline="2024 revenue decline is within normal variance, not a structural break",
        executive_summary="The decline is not statistically significant.",
        recommendations=[_rec("Launch a win-back campaign for lapsed Meta customers")])
    assert c is not None


def test_coherent_report_does_not_flag():
    """A normal report — verdict names a real driver, recs act on it — is coherent."""
    c = detect_verdict_recommendation_incoherence(
        headline="Revenue fell 6.6%, driven by Meta channel weakness",
        executive_summary="Meta collapsed -22%; volume-driven.",
        recommendations=[_rec("Reallocate spend away from Meta toward TikTok")])
    assert c is None


def test_rejection_with_only_advisory_recs_is_coherent():
    """A rejection verdict paired with passive/advisory recs agrees with itself — no flag."""
    c = detect_verdict_recommendation_incoherence(
        headline="Refunds did not spike — within normal variance",
        executive_summary="No anomaly was detected.",
        recommendations=[_rec("Continue to monitor refund volume over time"),
                         _rec("No action needed at this time")])
    assert c is None


def test_rejection_with_no_recs_is_coherent():
    c = detect_verdict_recommendation_incoherence(
        headline="The premise is inverted; X is not the problem", executive_summary="",
        recommendations=[])
    assert c is None


def test_accepts_object_recommendations():
    """Works on objects with an `.action` attr (the ADASynthesisModel shape), not just dicts."""
    class _R:
        def __init__(self, a): self.action = a
    c = detect_verdict_recommendation_incoherence(
        "X is not the problem", "premise inverted",
        [_R("Overhaul X's supply chain immediately")])
    assert c is not None


def test_folds_into_contradiction_report_severity():
    rep = ContradictionReport()
    assert rep.severity == "none"
    c = detect_verdict_recommendation_incoherence(
        "not the problem — premise inverted", "", [_rec("Fix the thing now")])
    rep.items.append(c)
    assert rep.severity == "high" and rep.to_dict()["count"] == 1
