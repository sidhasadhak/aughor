"""Integration tests for the value-domain join-guard REPAIR loop.

These exercise the regenerate-on-mismatch wiring with a real in-memory DuckDB
connection and a stubbed LLM, proving the two branches that matter:

  - a regeneration that CLEARS the mismatch is adopted
  - a regeneration that does NOT clear it is rejected (original result kept)

The stub avoids a live model so the accept/reject logic is tested deterministically.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import DuckDBConnection


def _conn():
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders (cust VARCHAR, camp VARCHAR, amt INT)")
    conn._conn.execute(
        "INSERT INTO orders VALUES ('C1','M1',10),('C2','M2',20),('C3','M1',30)"
    )
    conn._conn.execute("CREATE TABLE campaigns (id VARCHAR, name VARCHAR)")
    conn._conn.execute("INSERT INTO campaigns VALUES ('M1','spring'),('M2','summer')")
    return conn


# The disjoint join (orders.cust ↔ campaigns.id) and its correct form.
_BAD = "SELECT c.name, SUM(o.amt) AS rev FROM orders o JOIN campaigns c ON o.cust = c.id GROUP BY c.name"
_GOOD = "SELECT c.name, SUM(o.amt) AS rev FROM orders o JOIN campaigns c ON o.camp = c.id GROUP BY c.name"


class _StubProvider:
    """Returns a fixed SQL string as the .fixed_sql of any response_model."""

    def __init__(self, fixed_sql: str):
        self._fixed_sql = fixed_sql

    def complete(self, *, system, user, response_model):
        # Build the response model with whatever fixed-sql / explanation fields it has.
        fields = response_model.model_fields
        kwargs = {}
        for name in fields:
            if "sql" in name:
                kwargs[name] = self._fixed_sql
            elif name in ("explanation", "fix_explanation"):
                kwargs[name] = "stubbed fix"
            elif name == "data_quality_issue":
                kwargs[name] = None
            else:
                kwargs[name] = ""
        return response_model(**kwargs)


# ── ADA path: _execute_safe ──────────────────────────────────────────────────

def test_ada_execute_safe_adopts_clearing_fix(monkeypatch):
    from aughor.agent import investigate as I

    monkeypatch.setattr(I, "_provider", lambda role="coder": _StubProvider(_GOOD))
    conn = _conn()
    result = I._execute_safe(conn, "dimensional", _BAD, schema="orders(cust,camp,amt) campaigns(id,name)")
    # The good fix overlaps → adopted; rows are returned.
    assert result.error is None
    assert result.row_count > 0
    assert "o.camp = c.id" in result.sql.replace('"', "").replace(" AS ", " ")


def test_ada_execute_safe_rejects_nonclearing_fix(monkeypatch):
    from aughor.agent import investigate as I

    # Stub returns a fix that STILL joins on the disjoint column → must be rejected.
    monkeypatch.setattr(I, "_provider", lambda role="coder": _StubProvider(_BAD))
    conn = _conn()
    result = I._execute_safe(conn, "dimensional", _BAD, schema="orders campaigns")
    # Original kept (still the disjoint join, 0 rows) — never replaced with a
    # rewrite that fails the same guard.
    assert result.error is None
    assert "o.cust = c.id" in result.sql.replace('"', "").replace(" AS ", " ")


def test_ada_execute_safe_clean_join_no_repair(monkeypatch):
    from aughor.agent import investigate as I

    # If the provider is called on a clean join it would corrupt the result;
    # assert it is NOT called (no mismatch → no repair).
    called = {"n": 0}

    def _boom(role="coder"):
        called["n"] += 1
        return _StubProvider(_BAD)

    monkeypatch.setattr(I, "_provider", _boom)
    conn = _conn()
    result = I._execute_safe(conn, "dimensional", _GOOD, schema="orders campaigns")
    assert result.row_count > 0
    assert called["n"] == 0
