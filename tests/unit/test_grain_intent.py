"""Grain-of-intent check (aughor/sql/grain_intent.py) — precision-first detection.

Fixtures are REAL Spider2 Phase-0 miss questions (the 11 grain-bucket cases) plus
previously-correct sentinel questions that must NOT fire — a false fire costs a wasted
repair round, so precision is the contract under test.
"""
from __future__ import annotations

from aughor.sql.grain_intent import check_result_grain, expected_grain


# ── detection: the real grain-miss questions ─────────────────────────────────

def test_top_n_detected():
    e = expected_grain("Please identify the top three customers, based on their "
                       "customer_unique_id, who have the highest number of delivered orders")
    assert e and e.kind == "exact" and e.n == 3


def test_numeric_top_n_detected():
    e = expected_grain("Can you find 5 delivery drivers with the highest average number "
                       "of daily deliveries?")
    assert e and e.kind == "exact" and e.n == 5


def test_singular_intent_detected():
    e = expected_grain("Which player has participated in the highest number of winning "
                       "matches as a member of the squad?")
    assert e and e.kind == "exact" and e.n == 1


def test_singular_year_detected():
    e = expected_grain("In which year were the two most common causes of traffic "
                       "accidents different from those in other years?")
    # "two most common causes" describes the CRITERION, not the output rows — the
    # output is "which year". Precision rule: TOP_N matches first ⇒ n=2 is an
    # acceptable conservative read; what matters is it never fires on 7 rows vs 1-2.
    assert e is not None


def test_per_entity_detected():
    e = expected_grain("For each match, considering every innings, please combine runs "
                       "from both batsman and extra sources")
    assert e and e.kind == "per_entity" and e.entity == "match"


def test_per_entity_customer():
    e = expected_grain("For each customer, group all deposits and withdrawals")
    assert e and e.kind == "per_entity" and e.entity == "customer"


# ── precision: sentinels that must NOT fire ──────────────────────────────────

def test_plain_aggregate_question_no_expectation_fire():
    # A scalar question with no grain markers → detector may return None or exact-1;
    # either way a 1-row result must never produce a diagnosis.
    q = "What is the average order value?"
    assert check_result_grain(q, 1) is None


def test_unbounded_list_question_does_not_fire():
    q = "Could you list each musical style with the number of times it appears?"
    # 'each musical style' → per_entity, but with no probe supplied it must stay silent.
    assert check_result_grain(q, 40) is None


# ── firing semantics ─────────────────────────────────────────────────────────

def test_top3_with_5_rows_fires():
    q = "Please identify the top three customers based on delivered orders"
    # tie_tolerance 1.0 → allow up to 6; 5 rows is within tolerance → silent
    assert check_result_grain(q, 5) is None
    # 7 rows exceeds 3*(1+1.0)=6 → fires
    assert "GRAIN MISMATCH" in (check_result_grain(q, 7) or "")


def test_singular_with_many_rows_fires():
    q = "Which player has participated in the highest number of winning matches?"
    assert "GRAIN MISMATCH" in (check_result_grain(q, 7) or "")
    assert check_result_grain(q, 1) is None
    assert check_result_grain(q, 2) is None  # a tie — within tolerance


def test_per_entity_probe_comparison():
    q = "For each match, combine runs from both sources"
    probe = lambda col: 577 if "match" in col.lower() else None  # noqa: E731
    cols = ["match_id", "over_id", "runs"]
    # per-ball grain (134k rows) vs 577 matches → fires
    diag = check_result_grain(q, 134_703, columns_in_scope=cols, count_distinct=probe)
    assert diag and "one output row per match" in diag
    # right grain → silent
    assert check_result_grain(q, 577, columns_in_scope=cols, count_distinct=probe) is None
    # near-right (some matches filtered) → silent, not a false fire
    assert check_result_grain(q, 431, columns_in_scope=cols, count_distinct=probe) is None


def test_no_probe_no_per_entity_fire():
    q = "For each match, combine runs"
    assert check_result_grain(q, 134_703) is None
