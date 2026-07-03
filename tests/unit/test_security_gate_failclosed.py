"""REC-01 / SEC-02 — the SQL safety gate must fail CLOSED.

A safety control that ERRORS must DENY the query, not silently allow it. The
historical `except Exception: pass` in `_security_pre` failed OPEN — any bug in
the SafetyChecker turned the one write-protection layer into a no-op. These
tests pin fail-closed behaviour both at the gate function and end-to-end through
`DuckDBConnection.execute`.
"""
from __future__ import annotations

import duckdb
import pytest


def _boom(sql):  # matches SafetyChecker.check(sql) call shape
    raise RuntimeError("safety checker exploded")


def test_security_pre_returns_blocked_when_checker_errors(monkeypatch):
    from aughor.security import safety
    monkeypatch.setattr(safety.SafetyChecker, "check", staticmethod(_boom))

    from aughor.db.connection import security_pre
    result = security_pre("conn1", "h1", "SELECT 1")

    assert result is not None, "gate must fail closed (return a BLOCKED result), not None"
    assert result.error and result.error.startswith("[BLOCKED]")
    assert result.row_count == 0 and result.rows == []


def test_execute_fails_closed_end_to_end(tmp_path, monkeypatch):
    from aughor.security import safety
    monkeypatch.setattr(safety.SafetyChecker, "check", staticmethod(_boom))

    # A real (writable) DuckDB file, then reopened read-only by DuckDBConnection.
    p = str(tmp_path / "w.duckdb")
    w = duckdb.connect(p)
    w.execute("CREATE TABLE t(x INTEGER)")
    w.execute("INSERT INTO t VALUES (1)")
    w.close()

    from aughor.db.connection import DuckDBConnection
    conn = DuckDBConnection(p)
    r = conn.execute("h1", "SELECT * FROM t")

    assert r.error and r.error.startswith("[BLOCKED]"), (
        "a broken safety gate must block the query, never run it"
    )
    assert r.row_count == 0 and r.rows == []


def test_internal_queries_still_bypass_the_gate(monkeypatch):
    """Dunder-labelled platform plumbing must NOT be affected by fail-closed —
    it never reaches the checker in the first place."""
    from aughor.security import safety
    monkeypatch.setattr(safety.SafetyChecker, "check", staticmethod(_boom))

    from aughor.db.connection import security_pre
    # A dunder internal label bypasses the gate entirely → None (proceed).
    assert security_pre("conn1", "__catalog__", "SELECT 1") is None
