"""Progressive escalation detection (Phase 5) — offer depth when a quick answer is thin.

Deterministic, low false-positive: fires on an errored query, an empty analytical result, or a
causal question answered by a single figure — and stays quiet on a healthy direct lookup.
"""
from __future__ import annotations

from aughor.agent.escalate import assess_escalation


def test_errored_quick_answer_offers_escalation():
    v = assess_escalation("revenue by region", columns=[], rows=[], error="Binder Error: ...")
    assert v.should_offer and v.signal == "error"


def test_empty_result_on_analytical_question_offers_escalation():
    # the 'Womenswear' shape: a wrong filter → zero rows on an analytical ask
    v = assess_escalation("gross margin by platform and season", columns=["p", "m"], rows=[])
    assert v.should_offer and v.signal == "no_rows"


def test_causal_question_with_a_single_figure_offers_escalation():
    v = assess_escalation("why did revenue drop last week?", columns=["d"], rows=[[-0.08]])
    assert v.should_offer and v.signal == "causal_thin"


def test_healthy_direct_lookup_does_not_escalate():
    v = assess_escalation("what is total revenue?", columns=["total"], rows=[[8416308.73]])
    assert v.should_offer is False


def test_empty_result_on_a_trivial_count_does_not_escalate():
    # zero rows can be a legitimate answer to a simple lookup — don't nag
    v = assess_escalation("orders today", columns=["n"], rows=[])
    assert v.should_offer is False


def test_a_healthy_ranking_does_not_escalate():
    v = assess_escalation("top regions by revenue", columns=["region", "rev"],
                          rows=[["EMEA", 100], ["US", 90], ["APAC", 70]])
    assert v.should_offer is False


def test_deep_route_never_escalates():
    # escalation is a quick-path affordance; a deep answer is already the deep path
    v = assess_escalation("why did revenue drop?", columns=["d"], rows=[[-0.08]], route_depth="deep")
    assert v.should_offer is False


def test_to_event_shape():
    ev = assess_escalation("revenue by region", rows=[], error="boom").to_event()
    assert set(ev) >= {"signal", "reason"} and ev["signal"] == "error"
