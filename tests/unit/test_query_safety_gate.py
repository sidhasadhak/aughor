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


def test_a_blocked_statement_is_audited_in_the_suites_own_store_never_the_live_one():
    """The statements this file sends are audited where the suite keeps its stores.

    Found 2026-10-12 on the live install: 595 audit rows under the connection id ``any-conn``, every one a
    DELETE/DROP/INSERT/UPDATE/TRUNCATE from ``query_builder`` this file sends to prove the gate blocks it, written to
    the LIVE audit trail between 2026-06-28 and 2026-07-02 — the five days between this file landing (55f06606) and
    conftest pointing ``AUGHOR_AUDIT_DB`` at a temp dir (d4a6359f, 2026-07-03). Nothing has leaked since; this pins
    it at the writer, beside the generic guard in test_store_hermeticity.py."""
    from pathlib import Path

    from aughor.db.home import default_home
    from aughor.security import audit

    store = Path(audit._DB_PATH).resolve()
    assert "aughor-test-stores" in str(store), store
    assert default_home().resolve() not in store.parents, store          # never the live ~/.aughor
    before = audit.AuditLogger.stats(connection_id="any-conn")["total"]
    assert gate_user_sql("any-conn", "query_builder", "DELETE FROM t") is not None
    assert audit.AuditLogger.stats(connection_id="any-conn")["total"] == before + 1   # audited — here
