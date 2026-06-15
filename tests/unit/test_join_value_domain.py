"""Unit tests for the value-domain join guard.

Tests cover:
- JOIN condition extraction (including alias resolution)
- check_join_value_domains integration with a mock connection
- Fail-open behaviour on bad SQL / connection errors
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aughor.sql.join_guard import (
    JoinDomainWarning,
    _extract_join_conditions,
    check_join_value_domains,
)
from aughor.agent.state import QueryResult


def _qr(matched: int, total: int) -> QueryResult:
    """Build a fake QueryResult as returned by the overlap probe."""
    return QueryResult(
        hypothesis_id="__domain_probe__",
        sql="SELECT ...",
        columns=["total", "matched"],
        rows=[[total, matched]],
        row_count=1,
    )


# ── _extract_join_conditions ─────────────────────────────────────────────────

def test_extract_simple_join():
    sql = "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
    conds = _extract_join_conditions(sql)
    assert len(conds) == 1
    t_a, c_a, t_b, c_b = conds[0]
    assert t_a == "orders" and c_a == "customer_id"
    assert t_b == "customers" and c_b == "id"


def test_extract_aliased_join():
    sql = "SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id"
    conds = _extract_join_conditions(sql)
    assert len(conds) == 1
    t_a, c_a, t_b, c_b = conds[0]
    assert t_a == "orders" and c_a == "customer_id"
    assert t_b == "customers" and c_b == "id"


def test_extract_schema_qualified():
    sql = "SELECT * FROM beauty.orders o JOIN beauty.customers c ON o.customer_id = c.id"
    conds = _extract_join_conditions(sql)
    assert len(conds) == 1
    t_a, c_a, t_b, c_b = conds[0]
    assert "orders" in t_a and c_a == "customer_id"
    assert "customers" in t_b and c_b == "id"


def test_extract_no_join_returns_empty():
    sql = "SELECT * FROM orders WHERE status = 'active'"
    assert _extract_join_conditions(sql) == []


def test_extract_unparseable_returns_empty():
    assert _extract_join_conditions("NOT VALID SQL $$$$") == []


def test_extract_multiple_joins():
    sql = """
    SELECT * FROM a
    JOIN b ON a.bid = b.id
    JOIN c ON b.cid = c.id
    """
    conds = _extract_join_conditions(sql)
    assert len(conds) == 2


# ── check_join_value_domains ─────────────────────────────────────────────────

def _mock_conn(matched: int, total: int) -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value = _qr(matched, total)
    return conn


def test_high_overlap_no_warning():
    conn = _mock_conn(matched=95, total=100)
    sql = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
    warnings = check_join_value_domains(conn, sql)
    assert warnings == []


def test_low_overlap_emits_warning():
    conn = _mock_conn(matched=3, total=100)
    sql = "SELECT * FROM orders o JOIN forms f ON o.customer_id = f.c_id"
    warnings = check_join_value_domains(conn, sql)
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, JoinDomainWarning)
    assert w.overlap == pytest.approx(0.03)
    assert "customer_id" in w.to_prompt_text()
    assert "c_id" in w.to_prompt_text()
    assert "MISMATCH" in w.to_prompt_text()


def test_zero_overlap_emits_warning():
    conn = _mock_conn(matched=0, total=100)
    sql = "SELECT * FROM a JOIN b ON a.x_id = b.y_id"
    warnings = check_join_value_domains(conn, sql)
    assert len(warnings) == 1
    assert warnings[0].overlap == 0.0


def test_empty_table_no_warning():
    # total=0 means the sample returned nothing — no false positive
    conn = _mock_conn(matched=0, total=0)
    sql = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
    warnings = check_join_value_domains(conn, sql)
    assert warnings == []


def test_no_join_no_probe():
    conn = MagicMock()
    sql = "SELECT * FROM orders WHERE status = 'active'"
    warnings = check_join_value_domains(conn, sql)
    assert warnings == []
    conn.execute.assert_not_called()


def test_connection_error_is_fail_open():
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("connection lost")
    sql = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
    # Must not raise
    warnings = check_join_value_domains(conn, sql)
    assert warnings == []


def test_bad_sql_is_fail_open():
    conn = MagicMock()
    warnings = check_join_value_domains(conn, "THIS IS NOT SQL ###")
    assert warnings == []
    conn.execute.assert_not_called()


def test_caps_at_max_probes():
    """Guard probes at most 4 join conditions, not unbounded."""
    conn = _mock_conn(matched=0, total=100)  # all mismatches to maximise probe count
    sql = """
    SELECT * FROM a
    JOIN b ON a.b_id = b.id
    JOIN c ON b.c_id = c.id
    JOIN d ON c.d_id = d.id
    JOIN e ON d.e_id = e.id
    JOIN f ON e.f_id = f.id
    """
    check_join_value_domains(conn, sql)
    # At most 4 probes fired (_MAX_PROBES = 4)
    assert conn.execute.call_count <= 4


import pytest
