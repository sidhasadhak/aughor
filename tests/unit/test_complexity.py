"""Deterministic complexity assessment + cost-tiered routing (Part 2 winning formula)."""
from __future__ import annotations

from aughor.agent.complexity import assess_complexity, model_role_for


def test_trivial_single_metric_is_simple():
    v = assess_complexity("What is total revenue?")
    assert v.tier == "simple"
    assert model_role_for(v) == "fast"          # cheap path for easy questions


def test_basic_aggregation_is_cheap_path_eligible():
    # A single basic GROUP BY is exactly what the cheap "fast" model should handle.
    v = assess_complexity("Show revenue by region for last month")
    assert v.tier == "simple" and model_role_for(v) == "fast"
    assert v.signals["aggregate"] >= 1 and v.signals["temporal"] >= 1


def test_comparison_is_moderate_or_complex():
    # Comparison / cross-section needs the frontier "coder" role.
    v = assess_complexity("Compare revenue by region this month versus last month")
    assert v.tier in ("moderate", "complex")
    assert model_role_for(v) == "coder"
    assert v.signals["compare"] >= 1


def test_causal_question_is_complex():
    v = assess_complexity("Why did revenue drop 8% last week compared to the prior week?")
    assert v.tier == "complex"
    assert v.score >= 0.65
    assert model_role_for(v) == "coder"          # never downgrade a hard question
    assert any("causal" in r for r in v.reasons)


def test_deterministic_same_question_same_verdict():
    q = "Which segment drove the increase in failure rate, and why?"
    a, b = assess_complexity(q), assess_complexity(q)
    assert a == b                                 # frozen dataclass equality


def test_vague_underspecified_question_flagged_ambiguous():
    v = assess_complexity("how is it doing lately?")
    assert v.ambiguous is True


def test_concrete_question_not_flagged_ambiguous():
    v = assess_complexity("What is the average order value by channel this quarter?")
    assert v.ambiguous is False


def test_schema_breadth_raises_score():
    schema = "TABLE: orders  (10 rows)\n  id  INT\n\nTABLE: customers  (5 rows)\n  id  INT\n\nTABLE: payments  (3 rows)\n  id  INT\n"
    narrow = assess_complexity("list orders")
    wide = assess_complexity("join orders, customers and payments for each customer", schema)
    assert wide.score > narrow.score


def test_empty_question_is_simple():
    v = assess_complexity("")
    assert v.tier == "simple" and v.score == 0.0
