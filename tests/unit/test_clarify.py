"""Ask-vs-guess clarification detection (Phase 3 of the Insight+Deep merge).

Two-source, deterministic: under-specification (the complexity ambiguous flag) + value/term ambiguity
(a subjective qualifier not already grounded). The FP gate must keep well-specified questions quiet.
"""
from __future__ import annotations

from aughor.agent.clarify import assess_clarification


# ── Source A — under-specification ────────────────────────────────────────────

def test_underspecified_question_asks():
    d = assess_clarification("How is performance lately?")
    assert d.should_ask and d.source == "underspecified"
    assert "metric" in d.question.lower()


def test_vague_quality_question_asks():
    d = assess_clarification("show me the good ones")
    assert d.should_ask and d.source == "underspecified"


# ── Source B — value/term ambiguity (what the complexity flag misses) ──────────

def test_value_ambiguity_term_asks():
    # the canonical harness case: 'urgent' → which status? complexity flag does NOT fire here.
    d = assess_clarification("total amount of urgent orders")
    assert d.should_ask and d.source == "ambiguous_term"
    assert "urgent" in d.terms and "urgent" in d.question.lower()


def test_subjective_term_without_grounding_asks():
    d = assess_clarification("list active accounts")
    assert d.should_ask and d.source == "ambiguous_term" and "active" in d.terms


# ── The FP gate keeps well-specified questions quiet ──────────────────────────

def test_concrete_question_does_not_ask():
    assert assess_clarification("What is total revenue?").should_ask is False


def test_grounded_ranking_does_not_ask():
    # 'top N by metric' is specified — must not nag about it.
    assert assess_clarification("top 10 customers by revenue").should_ask is False


def test_qualifier_with_a_number_is_treated_as_grounded():
    # a nearby quantity suppresses the term ask (conservative FP avoidance).
    assert assess_clarification("active users in the last 30 days").should_ask is False


def test_qualifier_bound_by_a_threshold_does_not_ask():
    assert assess_clarification("accounts with revenue over 1000").should_ask is False


def test_empty_question_does_not_ask():
    assert assess_clarification("   ").should_ask is False


# ── Event payload ──────────────────────────────────────────────────────────────

def test_to_event_shape():
    ev = assess_clarification("total amount of urgent orders").to_event()
    assert set(ev) >= {"question", "options", "source", "terms", "reason"}
    assert ev["source"] == "ambiguous_term" and isinstance(ev["options"], list)
