"""
Unit tests for database connection layer and SQL safety checker.

Tests DuckDB execute(), bulk_read() fallback, and safety classification.
No external databases required — all tests use in-memory DuckDB.
"""
from __future__ import annotations



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

def test_a_label_exempts_nothing() -> None:
    """GM-5 — the label's spelling used to exempt a statement from the safety check and the audit: any dunder, and a
    hand-listed set of bare names (`__bulk__` among them, a person's own SQL). Now every label is checked."""
    from aughor.db.connection import security_pre
    for h in ("__catalog__", "__schema_filter__", "__profiler__", "__bulk__",
              "scan", "columns", "freshness", "list_schemas", "sample", "chat", "h1", ""):
        blocked = security_pre("c1", h, "DROP TABLE x")
        assert blocked is not None and "[BLOCKED]" in (blocked.error or ""), repr(h)


def test_security_pre_skips_a_statement_declared_internal() -> None:
    """The exemption is the caller's declaration, in force for its one statement: a DROP under it is not even
    scored (the census holds who may declare it — the platform's own statements)."""
    from aughor.db.connection import security_pre
    from aughor.db.doors import through_door
    out = through_door(object(), "DROP TABLE x", None, lambda s: security_pre("c1", "any label", s), internal=True)
    assert out is None
    assert security_pre("c1", "any label", "DROP TABLE x") is not None, "the declaration outlived its statement"


def test_fleet_agent_data_queries_are_audited() -> None:
    """Every agent that reads USER data appears in the audit trail — the
    'any dunder is internal' rule silently exempted Scout/Watcher (and the
    revalidate paths) from Security & Audit. The federation paths' reads are
    plumbing since 2026-09-14; their ANSWERS are audited on every connection
    they read (tests/unit/test_security_post_across_connections.py)."""
    from aughor.db.connection import security_pre

    for h in ("__explorer__", "__monitor__", "__monitor_window__", "__revalidate__", "__fix_save__"):
        blocked = security_pre("c1", h, "DROP TABLE x")
        assert blocked is not None, f"{h} must be checked and audited"
    # The explorer's information_schema catalog probe stays plumbing by DECLARING it
    # (`internal=True`); the census ratchet holds every platform statement to that.


def test_explorer_query_lands_in_audit_log(tmp_path) -> None:
    """Live path: a Scout-labelled query through DuckDBConnection.execute is
    recorded in the audit store (AUGHOR_AUDIT_DB is a temp dir via conftest)."""
    import duckdb

    from aughor.db.connection import DuckDBConnection
    from aughor.security.audit import AuditLogger

    db_file = tmp_path / "t.duckdb"
    seed = duckdb.connect(str(db_file))
    seed.execute("CREATE TABLE t AS SELECT 1 AS a")
    seed.close()

    conn = DuckDBConnection(db_file, connection_id="audit-live-test")
    try:
        res = conn.execute("__explorer__", "SELECT a FROM t")
        assert not res.error and res.row_count == 1
    finally:
        conn.close()

    records = [r for r in AuditLogger.recent(200) if r["connection_id"] == "audit-live-test"]
    assert records, "explorer query did not reach the audit log"
    assert records[0]["hypothesis_id"] == "__explorer__"
    assert records[0]["verdict"] == "safe"
