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


def test_the_gate_checks_whatever_the_label():
    """A dunder label used to bypass the check silently (the original bug). GM-5: no label exempts a person's SQL —
    the gate runs outside any door, where no statement is declared internal."""
    for label in ("query_builder", "__catalog__", "__bulk__"):
        blocked = gate_user_sql("any-conn", label, "DELETE FROM t")
        assert blocked is not None and "[BLOCKED]" in (blocked.error or ""), label


def test_read_only_sql_passes_the_gate():
    """A plain SELECT is allowed through (returns None → falls to dispatch)."""
    assert gate_user_sql("any-conn", "query_builder", "SELECT 1") is None


@pytest.mark.parametrize("sql", ["DELETE FROM orders", "DROP TABLE customers"])
def test_query_semantic_blocks_mutating_sql(sql):
    """/query/semantic re-runs user SQL server-side. It previously dispatched it
    under the ``__semantic__`` dunder id — ungated AND unaudited (the same class
    of bug as the original Query Builder bypass). The raw SQL must be gated at
    the endpoint, before the LIMIT wrapper demotes the first token."""
    r = client.post(
        "/query/semantic",
        json={
            "conn_id": "any-conn",
            "sql": sql,
            "column": "notes",
            "operator": "filter",
            "predicate": "mentions a refund",
        },
    )
    assert r.status_code == 403
    assert "[BLOCKED]" in r.json()["detail"]
