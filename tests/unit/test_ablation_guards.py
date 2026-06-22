"""R4 — the ablation harness's safety classification + that the canonical trap shapes
trip the deterministic guards it composes. Hermetic (no live connection, no LLM)."""
from __future__ import annotations

from aughor.sql.fanout import detect_fanout, measure_times_key_arithmetic
from evals.ablation_eval import _classify_plain, _classify_guarded


_OK = {"execution_success": 1.0, "result_set_match": 1.0, "row_count_match": 1.0}
_WRONG = {"execution_success": 1.0, "result_set_match": 0.0, "row_count_match": 0.0}
_EXEC_FAIL = {"execution_success": 0.0, "error": "Generated failed: boom"}


def test_classify_plain_trichotomy():
    assert _classify_plain(_OK, "SELECT 1") == "correct"
    assert _classify_plain(_WRONG, "SELECT 1") == "silent-wrong"   # executed but wrong = dangerous
    assert _classify_plain(_EXEC_FAIL, "SELECT 1") == "error"
    assert _classify_plain({}, None) == "error"                    # generation produced nothing


def test_classify_guarded_caught_beats_silent():
    # A wrong result that a guard FLAGGED is 'caught' (safe), not 'silent-wrong' (dangerous).
    assert _classify_guarded(_WRONG, "SELECT 1", ["fanout"]) == "caught"
    assert _classify_guarded(_WRONG, "SELECT 1", []) == "silent-wrong"
    # Correct wins regardless of whether a guard fired.
    assert _classify_guarded(_OK, "SELECT 1", ["fanout"]) == "correct"
    # A guard fired but the rewrite didn't bind → still flagged (caught), never silently shipped.
    assert _classify_guarded(_EXEC_FAIL, "SELECT 1", ["value_domain"]) == "caught"
    assert _classify_guarded(_EXEC_FAIL, "SELECT 1", []) == "error"
    assert _classify_guarded({}, None, []) == "error"


def test_canonical_traps_trip_the_guards():
    """The deterministic guards `apply_guards` composes fire on the exact plausible-wrong
    shapes a naive agent writes — the headline of the ablation."""
    tcols = {
        "orders": ["order_id", "customer_id", "order_value", "order_status"],
        "order_items": ["order_id", "order_item_id", "unit_price", "unit_cost"],
    }
    # Fan-out: an order-grain measure summed across a join to a line-grain child.
    ff = detect_fanout(
        "SELECT SUM(o.order_value) AS rev FROM orders o "
        "JOIN order_items oi ON o.order_id = oi.order_id",
        tcols, "duckdb")
    assert ff is not None, "fan-out across the orders→order_items chasm must be detected"

    # id-arithmetic: a measure multiplied by a key/id column fabricates a magnitude.
    hint = measure_times_key_arithmetic(
        "SELECT SUM(unit_price * order_item_id) AS rev FROM order_items", tcols, "duckdb")
    assert hint and "id" in hint.lower(), "SUM(measure × id) must be flagged"

    # A clean, additive aggregate trips neither.
    assert detect_fanout("SELECT SUM(unit_price) FROM order_items", tcols, "duckdb") is None
    assert not measure_times_key_arithmetic("SELECT SUM(unit_price) FROM order_items", tcols, "duckdb")
