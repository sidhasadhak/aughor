"""Premise validation for cross-sectional investigations (questioning the question).

A "why is X so high/low" question ASSERTS the metric is at an extreme; the scan should
validate that premise before explaining it. Behind AUGHOR_PREMISE_CHECK.
"""
from __future__ import annotations

from aughor.agent.investigate import _premise_direction, _premise_enabled


def test_detects_high_assertion():
    assert _premise_direction("Why are womenswear returns so high?") == "high"
    assert _premise_direction("Why is churn so elevated?") == "high"
    assert _premise_direction("Why are there so many returns?") == "high"


def test_detects_low_assertion():
    assert _premise_direction("Why is conversion so low?") == "low"
    assert _premise_direction("Why is repeat purchase so weak?") == "low"
    assert _premise_direction("Why are margins declining?") == "low"


def test_neutral_questions_have_no_premise():
    assert _premise_direction("What is total revenue by month?") is None
    assert _premise_direction("Show orders by region") is None
    assert _premise_direction("Which platform has the most orders?") is None


def test_flag_gating(monkeypatch):
    # ada.premise_check is auto-elevated by default (2026-07-13 graduation):
    # unset ⇒ enabled (its deterministic trigger gates per run); explicit "0" kills.
    monkeypatch.delenv("AUGHOR_PREMISE_CHECK", raising=False)
    assert _premise_enabled() is True
    monkeypatch.setenv("AUGHOR_PREMISE_CHECK", "0")
    assert _premise_enabled() is False
    monkeypatch.setenv("AUGHOR_PREMISE_CHECK", "1")
    assert _premise_enabled() is True
