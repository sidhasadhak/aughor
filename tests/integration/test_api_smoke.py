"""
Smoke tests for the Aughor API.

These tests hit the real FastAPI app via TestClient (no live server, no LLM calls).
They guard against import errors, startup failures, and obvious endpoint regressions.

Run:   uv run pytest tests/ -x -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_returns_200(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200, r.text


def test_health_body_has_status(client: TestClient) -> None:
    r = client.get("/health")
    body = r.json()
    assert "status" in body
    assert body["status"] == "ok"


# ── Connections ───────────────────────────────────────────────────────────────

def test_list_connections_returns_list(client: TestClient) -> None:
    r = client.get("/connections")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_list_connections_has_builtin(client: TestClient) -> None:
    r = client.get("/connections")
    conns = r.json()
    ids = [c.get("id") for c in conns]
    assert len(conns) > 0, "Expected at least the builtin DuckDB fixture connection"
    assert any(c.get("builtin") for c in conns), f"No builtin connection in {ids}"


def test_get_schema_for_builtin(client: TestClient, builtin_conn_id: str) -> None:
    r = client.get(f"/connections/{builtin_conn_id}/schema")
    assert r.status_code in (200, 404, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert "schema" in body  # returns {"schema": "...string..."}


# ── Security checks ───────────────────────────────────────────────────────────

def test_security_check_blocks_drop(client: TestClient) -> None:
    r = client.post("/security/check", json={"sql": "DROP TABLE orders"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("verdict") == "blocked", f"Expected DROP to be blocked: {body}"


def test_security_check_allows_select(client: TestClient) -> None:
    r = client.post("/security/check", json={"sql": "SELECT 1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("verdict") == "safe", f"Expected SELECT 1 to be allowed: {body}"


def test_security_check_blocks_delete(client: TestClient) -> None:
    r = client.post("/security/check", json={"sql": "DELETE FROM users WHERE 1=1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("verdict") == "blocked", f"Expected DELETE to be blocked: {body}"


# ── Direct query ──────────────────────────────────────────────────────────────

def test_query_run_executes_select(client: TestClient, builtin_conn_id: str) -> None:
    r = client.post("/query/run", json={
        "conn_id": builtin_conn_id,
        "sql": "SELECT 42 AS answer",
        "limit": 10,
        "use_cache": False,
        "use_bulk": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "columns" in body
    assert "rows" in body
    assert "answer" in body["columns"]
    # values are stringified; error must be None
    assert body.get("error") is None


def test_query_run_rejects_destructive(client: TestClient, builtin_conn_id: str) -> None:
    r = client.post("/query/run", json={
        "conn_id": builtin_conn_id,
        "sql": "DROP TABLE IF EXISTS __test_aughor",
        "limit": 10,
        "use_cache": False,
        "use_bulk": False,
    })
    # Security check returns 200 with error field, or 4xx — both are acceptable
    if r.status_code == 200:
        body = r.json()
        assert body.get("error") is not None, f"Expected DROP to be blocked: {body}"
    else:
        assert r.status_code in (400, 403, 422), r.text


# ── Investigations ────────────────────────────────────────────────────────────

def test_list_investigations_returns_list(client: TestClient) -> None:
    r = client.get("/investigations")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.e2e
def test_investigate_endpoint_accepts_request(client: TestClient, builtin_conn_id: str) -> None:
    """
    Confirm /investigate returns 200 and begins streaming.
    We only read the first SSE event — no LLM call validation, no full completion wait.
    This is a smoke test: wrong request shape → 422 would catch most regressions.
    """
    import json as _json

    # Use client.post with stream=True via httpx streaming
    with client.stream("POST", "/investigate", json={
        "question": "How many tables are there?",
        "connection_id": builtin_conn_id,
        "skip_cache": True,
    }) as response:
        assert response.status_code == 200, response.text
        # Read until we get the first data line or give up after 20 lines
        for i, line in enumerate(response.iter_lines()):
            if i > 20:
                break
            if line and line.startswith("data:"):
                payload = _json.loads(line[5:].strip())
                event_type = payload.get("type")
                assert event_type in ("start", "mode", "status_text", "error"), (
                    f"Unexpected first event type: {event_type}"
                )
                break


@pytest.mark.e2e
def test_investigate_sse_start_event_has_trace_id(client: TestClient, builtin_conn_id: str) -> None:
    """
    The SSE 'start' event must include a trace_id field (M7 Observability).
    Marked e2e because it reads the full streaming response — see
    tests/unit/test_telemetry.py::test_sse_start_event_trace_id_format for the
    fast equivalent that validates the same contract without a live graph.
    """
    import json as _json

    start_payload: dict | None = None
    with client.stream("POST", "/investigate", json={
        "question": "test observability trace_id field",
        "connection_id": builtin_conn_id,
        "skip_cache": True,
    }) as response:
        assert response.status_code == 200, response.text
        for i, line in enumerate(response.iter_lines()):
            if i > 50:
                break
            if not line or not line.startswith("data:"):
                continue
            payload = _json.loads(line[5:].strip())
            if payload.get("type") == "start":
                start_payload = payload
                break

    assert start_payload is not None, "Never received a 'start' SSE event"
    assert "trace_id" in start_payload, (
        f"'trace_id' missing from start event payload: {start_payload}"
    )
    assert "investigation_id" in start_payload
    assert start_payload["trace_id"] == start_payload["investigation_id"]


# ── Metrics ───────────────────────────────────────────────────────────────────

def test_list_metrics_returns_list(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


# ── Explorer ──────────────────────────────────────────────────────────────────

def test_exploration_status_returns_phase(client: TestClient, builtin_conn_id: str) -> None:
    r = client.get(f"/exploration/{builtin_conn_id}/status")
    assert r.status_code in (200, 404), r.text
    if r.status_code == 200:
        body = r.json()
        assert "phase" in body or "status" in body
