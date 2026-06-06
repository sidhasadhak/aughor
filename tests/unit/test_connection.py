"""
Unit tests for database connection layer and SQL safety checker.

Tests DuckDB execute(), bulk_read() fallback, and safety classification.
No external databases required — all tests use in-memory DuckDB.
"""
from __future__ import annotations

import pytest


# ── DuckDB execute ────────────────────────────────────────────────────────────

def _make_duckdb_conn():
    """Create a DuckDBConnection wired to an in-memory database for testing.

    DuckDB refuses read_only=True on :memory: databases, so we bypass __init__
    and set the internal attributes directly with a writable connection.
    """
    import duckdb
    from aughor.db.connection import DuckDBConnection
    from pathlib import Path

    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")  # writable, in-process
    conn._connection_id = "test"
    conn._schema_name = None
    return conn


def test_duckdb_execute_select_literal() -> None:
    conn = _make_duckdb_conn()
    result = conn.execute("test", "SELECT 1 AS n")
    assert result.columns == ["n"]
    # execute() stringifies all values for JSON serialisation
    assert result.rows == [["1"]]
    assert result.error is None


def test_duckdb_execute_returns_correct_types() -> None:
    conn = _make_duckdb_conn()
    result = conn.execute("test", "SELECT 42 AS answer, 'hello' AS msg")
    assert "answer" in result.columns
    assert "msg" in result.columns
    # Values are stringified
    assert result.rows[0][result.columns.index("answer")] == "42"
    assert result.rows[0][result.columns.index("msg")] == "hello"


def test_duckdb_execute_multi_row() -> None:
    conn = _make_duckdb_conn()
    result = conn.execute("test", "SELECT unnest([1, 2, 3]) AS n")
    assert result.columns == ["n"]
    assert len(result.rows) == 3


def test_duckdb_bulk_read_fallback() -> None:
    """bulk_read() on DuckDB falls back to execute() — result must be valid."""
    conn = _make_duckdb_conn()
    result = conn.bulk_read("SELECT 1 AS x", limit=100)
    assert result.columns == ["x"]
    assert len(result.rows) == 1
    assert result.rows[0][0] == "1"  # stringified


def test_duckdb_execute_blocked_query_returns_error() -> None:
    """Security pre-check must block DROP and return a QueryResult with error."""
    conn = _make_duckdb_conn()
    result = conn.execute("test", "DROP TABLE IF EXISTS __nonexistent")
    # The safety checker should block this and return error in QueryResult
    assert result.error is not None
    assert len(result.rows) == 0


# ── SQL Safety checker ────────────────────────────────────────────────────────

def test_safety_blocks_drop_table() -> None:
    from aughor.security.safety import SafetyChecker, SafetyVerdict
    result = SafetyChecker.check("DROP TABLE users")
    assert result.verdict == SafetyVerdict.BLOCKED


def test_safety_blocks_delete() -> None:
    from aughor.security.safety import SafetyChecker, SafetyVerdict
    result = SafetyChecker.check("DELETE FROM orders WHERE 1=1")
    assert result.verdict == SafetyVerdict.BLOCKED


def test_safety_blocks_truncate() -> None:
    from aughor.security.safety import SafetyChecker, SafetyVerdict
    result = SafetyChecker.check("TRUNCATE TABLE events")
    assert result.verdict == SafetyVerdict.BLOCKED


def test_safety_allows_select() -> None:
    from aughor.security.safety import SafetyChecker, SafetyVerdict
    result = SafetyChecker.check("SELECT * FROM orders LIMIT 100")
    assert result.verdict == SafetyVerdict.SAFE


def test_safety_allows_select_literal() -> None:
    from aughor.security.safety import SafetyChecker, SafetyVerdict
    result = SafetyChecker.check("SELECT 1")
    assert result.verdict == SafetyVerdict.SAFE


def test_safety_is_allowed_interface() -> None:
    """is_allowed() returns (bool, reason_str) tuple."""
    from aughor.security.safety import SafetyChecker
    ok, reason = SafetyChecker.is_allowed("SELECT 1")
    assert ok is True
    assert isinstance(reason, str)

    ok2, reason2 = SafetyChecker.is_allowed("DROP TABLE users")
    assert ok2 is False
    assert reason2  # non-empty reason


# ── Internal-query audit bypass ───────────────────────────────────────────────

def test_internal_query_bypasses_audit() -> None:
    """Platform plumbing (dunder labels + metadata allowlist) is not audited;
    real user labels are. Keeps the audit trail to genuine user activity."""
    from aughor.db.connection import _is_internal_query

    # dunder plumbing labels
    for h in ("__catalog__", "__schema_filter__", "__profiler__", "__bulk__"):
        assert _is_internal_query(h) is True, h
    # bare metadata allowlist
    for h in ("scan", "columns", "freshness", "list_schemas", "sample"):
        assert _is_internal_query(h) is True, h
    # genuine user activity must still be audited
    for h in ("chat", "h1", "inv1", "hypothesis_3"):
        assert _is_internal_query(h) is False, h
    # edge cases that must NOT match the dunder shape
    for h in ("", "__", "_x", None):
        assert _is_internal_query(h) is False, repr(h)


def test_security_pre_skips_internal_query() -> None:
    """_security_pre never blocks an internal query, even a dangerous-looking one."""
    from aughor.db.connection import _security_pre
    # A DROP would normally be BLOCKED; under an internal label it's not even scored.
    assert _security_pre("c1", "__catalog__", "DROP TABLE x") is None
