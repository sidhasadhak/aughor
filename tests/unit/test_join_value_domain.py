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
    # At most 4 join CONDITIONS probed (_MAX_PROBES = 4), each in 2 directions → ≤8 calls
    assert conn.execute.call_count <= 8


# ── Real-connection regression (the mock can't catch value stringification) ──
# DuckDBConnection.execute() stringifies every result value for JSON
# serialisation, so the probe's COUNT(*) comes back as '93' not 93. A mock
# returning ints hid this; only a real connection exercises the int() coercion.

def _real_conn():
    import duckdb
    from pathlib import Path
    from aughor.db.connection import DuckDBConnection

    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    # Two tables: a real FK pair (orders.cust ⊆ customers.id) and a disjoint pair.
    conn._conn.execute("CREATE TABLE customers (id VARCHAR)")
    conn._conn.execute("INSERT INTO customers VALUES ('C001'),('C002'),('C003'),('C004'),('C005')")
    conn._conn.execute("CREATE TABLE orders (cust VARCHAR, camp VARCHAR)")
    conn._conn.execute("INSERT INTO orders VALUES ('C001','CMP1'),('C002','CMP2'),('C003','CMP1')")
    conn._conn.execute("CREATE TABLE campaigns (id VARCHAR)")
    conn._conn.execute("INSERT INTO campaigns VALUES ('CMP1'),('CMP2'),('CMP3')")
    return conn


def test_real_connection_good_fk_no_warning():
    conn = _real_conn()
    sql = "SELECT * FROM orders o JOIN customers c ON o.cust = c.id"
    assert check_join_value_domains(conn, sql) == []


def test_real_connection_disjoint_join_warns():
    conn = _real_conn()
    # orders.cust (C00x) vs campaigns.id (CMPx) — same VARCHAR type, disjoint values
    sql = "SELECT * FROM orders o JOIN campaigns c ON o.cust = c.id"
    warnings = check_join_value_domains(conn, sql)
    assert len(warnings) == 1
    assert warnings[0].overlap == 0.0
    assert "MISMATCH" in warnings[0].to_prompt_text()


def test_real_connection_correct_camp_join_no_warning():
    conn = _real_conn()
    # The CORRECT campaign join (orders.camp ⊆ campaigns.id) must not warn
    sql = "SELECT * FROM orders o JOIN campaigns c ON o.camp = c.id"
    assert check_join_value_domains(conn, sql) == []


import pytest


# ── direction-aware containment (F8) ─────────────────────────────────────────

def test_subset_join_not_flagged_direction_aware():
    # child ⊆ parent (orders ⋈ refunds): parent→child low (6%), child→parent high
    # (100%) → MAX passes. The single-direction check used to false-flag this.
    conn = MagicMock()
    conn.execute.side_effect = [_qr(6, 100), _qr(100, 100)]
    sql = "SELECT * FROM orders o JOIN refunds r ON o.order_id = r.order_id"
    assert check_join_value_domains(conn, sql) == []


def test_fabricated_join_flagged_both_directions_low():
    # genuinely different vocabularies (refund_reason ↔ warehouse) → low BOTH ways → flag
    conn = MagicMock()
    conn.execute.side_effect = [_qr(0, 100), _qr(0, 100)]
    sql = "SELECT * FROM refunds r JOIN orders o ON r.refund_reason = o.warehouse"
    assert len(check_join_value_domains(conn, sql)) == 1


# ── Ill-formatted join-key reconciliation (Rec 3 / DAB GAP-3) ─────────────────

from aughor.sql.join_guard import reconcile_join_keys  # noqa: E402


def _real_conn_skew():
    """Two tables whose keys refer to the SAME entities but with different key FORMATS:
    books.bid = 'bid_1' vs reviews.book_ref = 'bref_1' — 0% raw overlap, 100% on digits."""
    import duckdb
    from pathlib import Path
    from aughor.db.connection import DuckDBConnection

    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE books (bid VARCHAR)")
    conn._conn.execute("INSERT INTO books VALUES ('bid_1'),('bid_2'),('bid_3'),('bid_4')")
    conn._conn.execute("CREATE TABLE reviews (book_ref VARCHAR)")
    conn._conn.execute("INSERT INTO reviews VALUES ('bref_1'),('bref_2'),('bref_3'),('bref_4')")
    return conn


def test_reconciliation_finds_prefix_skew(monkeypatch):
    monkeypatch.setenv("AUGHOR_JOIN_KEY_RECONCILIATION", "1")
    conn = _real_conn_skew()
    sql = "SELECT * FROM books b JOIN reviews r ON b.bid = r.book_ref"
    warnings = check_join_value_domains(conn, sql)
    assert len(warnings) == 1
    r = warnings[0].reconciliation
    assert r is not None
    assert r.overlap >= 0.9
    assert r.transform in ("digits", "strip_prefix")
    txt = warnings[0].to_prompt_text()
    assert "reconcile" in txt.lower()
    assert "regexp_replace" in txt      # the actionable normalized-join expression


def test_reconciliation_off_by_default_is_byte_identical(monkeypatch):
    monkeypatch.delenv("AUGHOR_JOIN_KEY_RECONCILIATION", raising=False)
    conn = _real_conn_skew()
    sql = "SELECT * FROM books b JOIN reviews r ON b.bid = r.book_ref"
    warnings = check_join_value_domains(conn, sql)
    assert len(warnings) == 1
    assert warnings[0].reconciliation is None                      # flag off → no attempt
    assert "different entities" in warnings[0].to_prompt_text()    # original message unchanged


def test_reconciliation_absent_for_genuinely_disjoint_keys(monkeypatch):
    monkeypatch.setenv("AUGHOR_JOIN_KEY_RECONCILIATION", "1")
    conn = _real_conn()   # orders.cust ('C00x') vs campaigns.id ('CMPx') — truly different entities
    sql = "SELECT * FROM orders o JOIN campaigns c ON o.cust = c.id"
    warnings = check_join_value_domains(conn, sql)
    assert len(warnings) == 1
    assert warnings[0].reconciliation is None    # no normalization reconciles disjoint entities


def test_reconcile_join_keys_direct_on_skew():
    conn = _real_conn_skew()
    recon = reconcile_join_keys(conn, "books", "bid", "reviews", "book_ref", raw_overlap=0.0)
    assert recon is not None and recon.overlap >= 0.9


def test_reconcile_fail_open_on_error():
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("boom")
    assert reconcile_join_keys(conn, "a", "x", "b", "y", 0.0) is None
