"""Conversational follow-up detection + the chat history-context builder (Phase 4).

is_followup must catch continuations ("now break that down", "filter that to Q4") and
stay quiet on self-contained fresh questions. build_history_section must carry the prior
SQL + a result digest, and switch to a "compose on the base query" header for follow-ups.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.followup import is_followup
from aughor.routers.investigations import build_history_section


# ── is_followup ───────────────────────────────────────────────────────────────

def test_continuation_leads_are_followups():
    for q in ["now break that down by region", "and by channel?", "what about Europe?",
              "then show profit instead", "also split by month"]:
        assert is_followup(q) is True, q


def test_refine_verbs_are_followups():
    for q in ["filter that to last quarter", "drill into APAC", "exclude returns",
              "narrow it down to enterprise", "just the top accounts"]:
        assert is_followup(q) is True, q


def test_reference_to_a_prior_item_is_a_followup():
    assert is_followup("show me the top one") is True
    assert is_followup("why is that one different?") is True
    assert is_followup("compare those regions") is True


def test_fresh_questions_are_not_followups():
    for q in ["revenue by region last month", "What is total revenue?",
              "Show top 10 customers by revenue", "products that sold well",
              "the highest revenue product", "Why did revenue drop 8% last week?"]:
        assert is_followup(q) is False, q


def test_empty_is_not_a_followup():
    assert is_followup("") is False and is_followup("   ") is False


# ── build_history_section ─────────────────────────────────────────────────────

def _turn(**kw):
    base = {"question": "q", "sql": "SELECT 1", "columns": ["a"], "headline": "", "key_rows": []}
    base.update(kw)
    return SimpleNamespace(**base)


def test_empty_history_is_blank():
    assert build_history_section([]) == ""


def test_history_carries_sql_columns_and_result_digest():
    t = _turn(question="orders by platform", sql="SELECT platform, COUNT(*) ...",
              columns=["platform", "n"], headline="YOOX leads",
              key_rows=[["YOOX", 165], ["OUTNET", 112]])
    out = build_history_section([t])
    assert "orders by platform" in out
    assert "SELECT platform, COUNT(*)" in out
    assert "platform, n" in out
    assert "YOOX leads" in out
    # the result digest resolves "that"/"the top one" against real values
    assert "Result (sample):" in out and "YOOX | 165" in out


def test_followup_header_instructs_composition_on_the_base():
    out = build_history_section([_turn()], followup=True)
    assert "FOLLOW-UP" in out and "base" in out.lower()


def test_non_followup_header_is_the_plain_reference_hint():
    out = build_history_section([_turn()], followup=False)
    assert "CONVERSATION HISTORY" in out and "FOLLOW-UP" not in out


def test_only_the_last_three_turns_are_kept():
    turns = [_turn(question=f"q{i}") for i in range(5)]
    out = build_history_section(turns)
    assert "q4" in out and "q1" not in out


def test_deep_turn_carries_headline_even_without_sql():
    # a deep/investigate turn may have no single representative SQL — its headline is the
    # continuity (Phase 4b). The SQL line is skipped, the headline is kept.
    t = _turn(question="why did revenue fall?", sql="", columns=[],
              headline="Revenue fell 8% on enterprise churn", key_rows=[])
    out = build_history_section([t])
    assert "why did revenue fall?" in out
    assert "Revenue fell 8% on enterprise churn" in out
    assert "SQL:" not in out
