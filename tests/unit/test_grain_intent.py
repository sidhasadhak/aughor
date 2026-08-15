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


# ── COUNT(*) over a finer grain than the entity the question counts ──────────
# The Superstore miss (2026-08-14): "how many orders in Q4 2016?" → 806 line items,
# not 406 orders. The schema declared the grain and carried order_id; nothing on the
# live path read either. Precision is the contract: every legitimate COUNT(*) below
# must stay silent.

from aughor.sql.grain_intent import count_star_over_finer_grain  # noqa: E402

_LINE_ITEM_COLS = ["row_id", "order_id", "order_date", "customer_id", "product_id", "sales"]


def test_how_many_orders_with_count_star_on_line_items_fires():
    d = count_star_over_finer_grain(
        "How many orders were placed in Q4 2016?",
        "SELECT COUNT(*) AS count FROM orders WHERE order_date >= '2016-10-01' AND order_date <= '2016-12-31'",
        _LINE_ITEM_COLS)
    assert d and "COUNT(DISTINCT order_id)" in d


def test_number_of_customers_fires_too():
    d = count_star_over_finer_grain(
        "What is the number of customers in the West region?",
        "SELECT COUNT(*) FROM orders WHERE region = 'West'", _LINE_ITEM_COLS)
    assert d and "COUNT(DISTINCT customer_id)" in d


def test_count_distinct_already_is_silent():
    assert count_star_over_finer_grain(
        "How many orders were placed in Q4 2016?",
        "SELECT COUNT(DISTINCT order_id) FROM orders WHERE order_date >= '2016-10-01'",
        _LINE_ITEM_COLS) is None


def test_row_words_are_silent():
    # "how many rows / records / line items" — COUNT(*) is exactly right.
    for q in ("How many rows are in orders?", "How many records were loaded?",
              "How many line items were sold?", "How many transactions happened in May?"):
        assert count_star_over_finer_grain(q, "SELECT COUNT(*) FROM orders", _LINE_ITEM_COLS) is None, q


def test_no_entity_key_in_scope_is_silent():
    # A table with no <entity>_id column gives no evidence of a finer grain.
    assert count_star_over_finer_grain(
        "How many orders were placed?", "SELECT COUNT(*) FROM orders",
        ["id", "placed_at", "total"]) is None


def test_joins_and_group_by_belong_to_fanout_detectors():
    assert count_star_over_finer_grain(
        "How many orders per region?",
        "SELECT region, COUNT(*) FROM orders GROUP BY region", _LINE_ITEM_COLS) is None
    assert count_star_over_finer_grain(
        "How many orders were returned?",
        "SELECT COUNT(*) FROM orders o JOIN returns r ON o.order_id = r.order_id",
        _LINE_ITEM_COLS) is None


def test_questions_that_do_not_count_are_silent():
    for q in ("What were total sales per year?", "Which region generates the most sales?",
              "Show sales by customer segment."):
        assert count_star_over_finer_grain(q, "SELECT COUNT(*) FROM orders", _LINE_ITEM_COLS) is None, q
