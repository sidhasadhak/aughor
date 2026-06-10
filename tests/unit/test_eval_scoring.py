"""Regression tests for the metric-aware (multi-reference) eval scorer (#13b).

The golden set defines "revenue" inconsistently (orders.total_amount on some
questions, order_items.line_total on others). `score_single` accepts a record's
`accept_sql` alternatives and scores the generated query against the BEST of
{reference_sql} ∪ accept_sql, so a correct answer that picked the *other*
canonical revenue definition is no longer scored wrong — WITHOUT becoming
permissive to genuinely wrong answers.
"""
from __future__ import annotations

from types import SimpleNamespace

import duckdb
import pytest

from evals.sql_accuracy import score_single


@pytest.fixture()
def db():
    """In-memory DuckDB where the two revenue definitions deliberately DISAGREE:
    SUM(orders.total_amount) = 100 but SUM(order_items.line_total) = 430."""
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE orders (order_id INT, total_amount DOUBLE)")
    conn.execute("INSERT INTO orders VALUES (1, 40), (2, 60)")  # total_amount sum = 100
    conn.execute("CREATE TABLE order_items (order_id INT, line_total DOUBLE)")
    conn.execute(
        "INSERT INTO order_items VALUES (1, 200), (1, 30), (2, 150), (2, 50)"
    )  # line_total sum = 430
    return SimpleNamespace(_conn=conn)


REVENUE_RECORD = {
    "id": "t1",
    "question": "total revenue",
    "reference_sql": "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM orders",
    "accept_sql": [
        "SELECT ROUND(SUM(line_total), 2) AS total_revenue FROM order_items"
    ],
}


def test_primary_definition_scores_perfect(db):
    gen = "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM orders"
    s = score_single(db, REVENUE_RECORD, gen)
    assert s["overall"] == 1.0
    assert s["matched_reference"] == 0
    assert s["num_references"] == 2


def test_alternative_definition_also_scores_perfect(db):
    # The metric confound: model picks the OTHER valid revenue definition.
    gen = "SELECT ROUND(SUM(line_total), 2) AS total_revenue FROM order_items"
    s = score_single(db, REVENUE_RECORD, gen)
    assert s["overall"] == 1.0
    assert s["matched_reference"] == 1  # matched the accept_sql alternative


def test_wrong_answer_still_fails(db):
    # A same-shape but semantically wrong answer (count, not revenue) must stay
    # below the 0.80 pass bar — metric-awareness must not become permissiveness.
    gen = "SELECT COUNT(*) AS total_revenue FROM orders"
    s = score_single(db, REVENUE_RECORD, gen)
    assert s["overall"] < 0.80
    assert s["matched_reference"] == 0


def test_no_accept_sql_is_backward_compatible(db):
    # Records without accept_sql behave exactly as before (single reference).
    rec = {k: v for k, v in REVENUE_RECORD.items() if k != "accept_sql"}
    gen = "SELECT ROUND(SUM(line_total), 2) AS total_revenue FROM order_items"
    s = score_single(db, rec, gen)
    assert s["num_references"] == 1
    assert s["overall"] < 0.80  # line_total (430) != total_amount (100), correctly penalised


def test_broken_alternative_is_skipped_not_penalised(db):
    # A non-executing accept_sql is a dataset-authoring issue; it must be skipped
    # rather than drag the score down or crash.
    rec = dict(REVENUE_RECORD)
    rec["accept_sql"] = ["SELECT this_column_does_not_exist FROM orders"]
    gen = "SELECT ROUND(SUM(total_amount), 2) AS total_revenue FROM orders"
    s = score_single(db, rec, gen)
    assert s["overall"] == 1.0  # primary still matches
    assert s["num_references"] == 1  # broken alt not counted
