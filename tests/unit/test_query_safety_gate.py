"""Regression: the Query Builder / bulk-read surface (/query/run) must enforce
the SAME SafetyChecker gate as the chat path. Previously it dispatched user SQL
under the ``__querybuilder__`` / ``__bulk__`` dunder ids, which match the
internal-query bypass in connection._is_internal_query — so DELETE/DROP/COPY ran
ungated and unaudited against the warehouse. Hermetic (gate runs before the
connection is resolved, so no live DB is needed)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db.connection import gate_user_sql

client = TestClient(app)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "DROP TABLE customers",
        "TRUNCATE TABLE events",
        "UPDATE orders SET total = 0",
        "INSERT INTO audit VALUES (1)",
    ],
)
def test_query_run_blocks_mutating_sql(sql):
    """A mutating statement is blocked at the endpoint, before dispatch."""
    r = client.post("/query/run", json={"conn_id": "any-conn", "sql": sql})
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None and "[BLOCKED]" in body["error"]
    assert body["rows"] == [] and body["row_count"] == 0


def test_query_run_blocks_mutating_sql_on_bulk_path():
    """use_bulk routes to bulk_read() (ConnectorX, never execute()) — the gate
    must still fire because it lives at the endpoint, not in execute()."""
    r = client.post(
        "/query/run",
        json={"conn_id": "any-conn", "sql": "DROP TABLE customers", "use_bulk": True},
    )
    assert r.status_code == 200
    assert "[BLOCKED]" in (r.json()["error"] or "")


def test_gate_uses_non_internal_label():
    """The user-facing label must NOT be a dunder id, or _is_internal_query
    silently bypasses the check (the original bug)."""
    from aughor.db.connection import _is_internal_query

    assert _is_internal_query("query_builder") is False
    # The gate actually blocks a mutating statement under this label.
    blocked = gate_user_sql("any-conn", "query_builder", "DELETE FROM t")
    assert blocked is not None and "[BLOCKED]" in (blocked.error or "")


def test_read_only_sql_passes_the_gate():
    """A plain SELECT is allowed through (returns None → falls to dispatch)."""
    assert gate_user_sql("any-conn", "query_builder", "SELECT 1") is None
