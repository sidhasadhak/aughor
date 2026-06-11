"""Failure-path contract — the platform must fail GRACEFULLY, never crash or
silently mislead.

Happy-path smoke tests (test_api_smoke.py) prove the endpoints work when inputs
are valid. These lock the harder, fool-proofing half: bad inputs, malicious SQL,
and unknown resources must produce a clean 4xx or a populated `error` — never a
500, never a silent-empty success. Behavior here was PROBED against the real app
first (no assumptions): every case below reflects observed current behavior, so a
regression that turns a graceful failure into a crash (or weakens the security
boundary) becomes a CI failure.

All in-process via TestClient — no live LLM, no live server.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _run(client, conn_id, sql):
    return client.post("/query/run", json={
        "conn_id": conn_id, "sql": sql, "limit": 50,
        "use_cache": False, "use_bulk": False,
    })


# ── Unknown resources → clean 4xx, never 500 ──────────────────────────────────

def test_bad_connection_schema_is_404(client: TestClient) -> None:
    r = client.get("/connections/__nope__/schema")
    assert r.status_code == 404, r.text


def test_query_on_bad_connection_is_404(client: TestClient) -> None:
    r = _run(client, "__nope__", "SELECT 1")
    assert r.status_code == 404, r.text


def test_unknown_investigation_is_404(client: TestClient) -> None:
    r = client.get("/investigations/__nope__")
    assert r.status_code == 404, r.text


# ── Malformed requests → 4xx validation, never 500 ────────────────────────────

def test_query_missing_fields_is_422(client: TestClient) -> None:
    r = client.post("/query/run", json={})
    assert r.status_code == 422, r.text


def test_query_empty_sql_is_4xx(client: TestClient, builtin_conn_id: str) -> None:
    r = _run(client, builtin_conn_id, "")
    assert 400 <= r.status_code < 500, r.text


def test_security_check_missing_sql_is_4xx(client: TestClient) -> None:
    r = client.post("/security/check", json={})
    assert 400 <= r.status_code < 500, r.text


# ── Invalid SQL → 200 with a SURFACED error, not a crash and not silent-empty ──

def test_garbage_sql_surfaces_error_not_crash(client: TestClient, builtin_conn_id: str) -> None:
    r = _run(client, builtin_conn_id, "this is not sql at all")
    assert r.status_code == 200, r.text
    body = r.json()
    # The user must learn their SQL was invalid — a populated error, not a silent empty.
    assert body.get("error"), f"invalid SQL must surface an error, got: {body}"
    assert body.get("row_count") == 0


def test_missing_table_surfaces_error(client: TestClient, builtin_conn_id: str) -> None:
    r = _run(client, builtin_conn_id, "SELECT * FROM __no_such_table__")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error"), f"missing table must surface an error, got: {body}"


def test_huge_limit_does_not_crash(client: TestClient, builtin_conn_id: str) -> None:
    r = _run(client, builtin_conn_id, "SELECT 1")
    assert r.status_code == 200, r.text  # limit 50 in helper; sanity that the path is alive
    r2 = client.post("/query/run", json={
        "conn_id": builtin_conn_id, "sql": "SELECT 1", "limit": 10**9,
        "use_cache": False, "use_bulk": False,
    })
    assert r2.status_code == 200, r2.text


# ── Security boundary — sneaky destructive SQL must stay BLOCKED ───────────────

import pytest


@pytest.mark.parametrize("sql,why", [
    ("SELECT 1; DROP TABLE orders",        "stacked / multi-statement"),
    ("SELECT 1 -- \n; DROP TABLE orders",  "comment-hidden stacked"),
    ("DrOp TaBlE orders",                  "case-mixed DROP"),
    ("TRUNCATE orders",                    "TRUNCATE"),
    ("UPDATE users SET admin=1",           "UPDATE (write)"),
    ("DELETE FROM users WHERE 1=1",        "DELETE (write)"),
])
def test_destructive_sql_is_blocked(client: TestClient, sql: str, why: str) -> None:
    r = client.post("/security/check", json={"sql": sql})
    assert r.status_code == 200, r.text
    assert r.json().get("verdict") == "blocked", f"{why!r} must be blocked: {r.json()}"


def test_plain_select_is_allowed(client: TestClient) -> None:
    r = client.post("/security/check", json={"sql": "SELECT 1"})
    assert r.status_code == 200 and r.json().get("verdict") == "safe", r.text


# ── Defense-in-depth: even if a destructive statement reaches /query/run, the
#    executor wrapping (SELECT * FROM (<sql>)) must prevent DDL from executing. ──

def test_drop_via_query_run_cannot_execute_ddl(client: TestClient, builtin_conn_id: str) -> None:
    r = _run(client, builtin_conn_id, "DROP TABLE IF EXISTS __probe_ddl__")
    assert r.status_code == 200, r.text
    body = r.json()
    # Wrapped as a subquery → DDL is a syntax error there → surfaced, never executed.
    assert body.get("error"), f"DDL must not execute silently: {body}"
    assert body.get("row_count") == 0
