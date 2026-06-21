"""Filter value-domain guard — extended to `!=` / `NOT IN` (eval 2026-06-21, Q29).

The guard already caught `status = 'cancelled'` when the data holds 'canceled' (matches
NO rows). The eval surfaced the NEGATED mirror: `status != 'cancelled'` EXCLUDES no rows
(every row is kept), so a deep analysis concluded "cancellation rate is zero across all
dimensions" despite 15,737 canceled orders. This locks extraction + the operator-aware
message + the real-DB probe for both polarities. See aughor/sql/join_guard.py.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.db.connection import DuckDBConnection
from aughor.sql.join_guard import (
    _extract_filter_literals,
    check_filter_value_domains,
    FilterDomainWarning,
)


# ── AST extraction: all four operators, JOIN-ON skipped ──────────────────────
def test_extract_eq_and_neq_and_notin():
    base = "SELECT * FROM missimi.orders WHERE order_status {op}"
    assert _extract_filter_literals(base.format(op="= 'cancelled'")) == [
        ("missimi.orders", "order_status", "cancelled", "=")]
    assert _extract_filter_literals(base.format(op="!= 'cancelled'")) == [
        ("missimi.orders", "order_status", "cancelled", "!=")]
    assert _extract_filter_literals(base.format(op="<> 'cancelled'")) == [
        ("missimi.orders", "order_status", "cancelled", "!=")]
    rows = _extract_filter_literals(base.format(op="NOT IN ('cancelled','x')"))
    assert ("missimi.orders", "order_status", "cancelled", "NOT IN") in rows


def test_join_on_literal_is_not_a_filter():
    assert _extract_filter_literals("SELECT * FROM a JOIN b ON a.k = 'x'") == []


# ── Operator-aware message ───────────────────────────────────────────────────
def test_message_distinguishes_match_vs_exclude():
    pos = FilterDomainWarning("orders", "order_status", "cancelled", ["canceled"], "canceled", "=")
    neg = FilterDomainWarning("orders", "order_status", "cancelled", ["canceled"], "canceled", "!=")
    assert "matches NO rows" in pos.to_prompt_text()
    assert "excludes NO rows" in neg.to_prompt_text() and "no-op" in neg.to_prompt_text()
    assert "canceled" in pos.to_prompt_text()  # suggestion surfaced


# ── Real-DuckDB probe: both polarities flagged, correct value left alone ──────
def _conn():
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders (order_id INT, order_status VARCHAR)")
    conn._conn.execute(
        "INSERT INTO orders VALUES "
        "(1,'canceled'),(2,'delivered'),(3,'shipped'),(4,'canceled'),(5,'delivered')"
    )
    return conn


def test_eq_typo_flagged_with_suggestion():
    w = check_filter_value_domains(_conn(), "SELECT COUNT(*) FROM orders WHERE order_status = 'cancelled'")
    assert len(w) == 1 and w[0].bad_value == "cancelled" and w[0].suggestion == "canceled"
    assert w[0].op == "="


def test_neq_typo_flagged_the_q29_scar():
    # `!= 'cancelled'` excludes nothing — the false "zero cancellations" path.
    w = check_filter_value_domains(_conn(), "SELECT COUNT(*) FROM orders WHERE order_status != 'cancelled'")
    assert len(w) == 1 and w[0].op == "!=" and w[0].suggestion == "canceled"
    assert "excludes NO rows" in w[0].to_prompt_text()


def test_not_in_typo_flagged():
    w = check_filter_value_domains(_conn(), "SELECT COUNT(*) FROM orders WHERE order_status NOT IN ('cancelled')")
    assert len(w) == 1 and w[0].op == "NOT IN"


def test_correct_value_not_flagged_either_polarity():
    assert check_filter_value_domains(_conn(), "SELECT COUNT(*) FROM orders WHERE order_status = 'canceled'") == []
    assert check_filter_value_domains(_conn(), "SELECT COUNT(*) FROM orders WHERE order_status != 'delivered'") == []


def test_novel_value_with_no_near_match_left_alone():
    # 'refunded' isn't a typo of any present value → high-precision: no warning.
    assert check_filter_value_domains(_conn(), "SELECT COUNT(*) FROM orders WHERE order_status != 'refunded'") == []
