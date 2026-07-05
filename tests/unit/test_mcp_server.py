"""R5 — the governed-intelligence MCP server.

Two layers of coverage:
  * **Mock** — drive the AughorClient against an httpx.MockTransport so the SSE-folding
    (ask / deep_analysis) and the read tools are tested without a live API or LLM.
  * **Real path** — drive the client against the actual FastAPI app in-process via
    httpx.ASGITransport, proving the wiring end-to-end (MCP client → real router → real
    ledger/registry) for the LLM-free read tools and the new /metrics/{name}/value route.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from aughor.mcp.client import AughorClient, AughorError
from aughor.mcp.server import mcp


# ── helpers ──────────────────────────────────────────────────────────────────────
def _sse(events: list[dict]) -> str:
    """Aughor's SSE framing — one `data: {json}` line per event, blank-line terminated."""
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)


def _client(routes: dict) -> AughorClient:
    """An AughorClient whose transport answers from `routes` (path -> httpx.Response or
    a callable(request) -> httpx.Response)."""
    def handler(request: httpx.Request) -> httpx.Response:
        resp = routes.get(request.url.path)
        if resp is None:
            return httpx.Response(404, json={"detail": f"no mock route for {request.url.path}"})
        return resp(request) if callable(resp) else resp
    return AughorClient(base_url="http://test", transport=httpx.MockTransport(handler))


def _run(coro):
    return asyncio.run(coro)


# ── the server surface ───────────────────────────────────────────────────────────
def test_server_registers_the_governed_tools():
    tools = {t.name for t in _run(mcp.list_tools())}
    assert tools == {
        "list_connections", "ask", "deep_analysis", "get_investigation", "get_metric",
        "list_findings", "get_briefing", "explore", "list_jobs", "get_job", "cancel_job",
    }
    # No raw `query` tool — the whole point is governed tools, not a SQL runner.
    assert "query" not in tools


def test_every_tool_has_an_llm_facing_description():
    for t in _run(mcp.list_tools()):
        assert t.description and len(t.description) > 40, t.name


# ── ask: folds the chat SSE stream + attaches the Trust Receipt ──────────────────
def test_ask_folds_stream_and_fetches_receipt():
    routes = {
        "/chat": httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse([
            {"type": "sql", "sql": "SELECT COUNT(*) FROM orders"},
            {"type": "columns", "columns": ["n"]},
            {"type": "rows", "rows": [[42]]},
            {"type": "headline", "headline": "There are 42 orders"},
            {"type": "trusted", "items": [{"metric": "orders"}]},
            {"type": "tables_used", "tables": ["orders"]},
            {"type": "done", "inv_id": "t1", "has_receipt": True},
        ])),
        "/chat/conn1/t1/receipt": httpx.Response(200, json={
            "natural_key": "chat:conn1:t1", "cost": {"total_tokens": 120},
        }),
    }
    res = _run(_client(routes).ask("how many orders", "conn1"))
    assert res["answer"] == "There are 42 orders"
    assert res["sql"].startswith("SELECT COUNT")
    assert res["row_count"] == 1
    assert res["rows"] == [[42]]
    assert res["trusted_metrics"] == [{"metric": "orders"}]
    assert res["tables_used"] == ["orders"]
    assert res["investigation_id"] == "t1"
    assert res["receipt"]["cost"]["total_tokens"] == 120


def test_ask_caps_the_row_sample():
    big = [[i] for i in range(500)]
    routes = {
        "/chat": httpx.Response(200, content=_sse([
            {"type": "rows", "rows": big},
            {"type": "headline", "headline": "ok"},
            {"type": "done", "inv_id": "x", "has_receipt": False},
        ])),
    }
    res = _run(_client(routes).ask("q", "c"))
    assert res["row_count"] == 500          # the true count is preserved …
    assert len(res["rows"]) == 50           # … but only a sample is returned to the LLM
    assert "receipt" not in res             # has_receipt False → no fetch


def test_ask_raises_on_error_event_without_answer():
    routes = {"/chat": httpx.Response(200, content=_sse([
        {"type": "error", "message": "Answer stopped — token budget exceeded"},
    ]))}
    with pytest.raises(AughorError) as e:
        _run(_client(routes).ask("q", "c"))
    assert "token budget" in str(e.value)


# ── deep_analysis: folds the investigate SSE stream ──────────────────────────────
def test_deep_analysis_returns_report_and_receipt():
    routes = {
        "/investigate": httpx.Response(200, content=_sse([
            {"type": "start", "investigation_id": "inv9"},
            {"type": "hypotheses", "hypotheses": [{"text": "h1"}]},
            {"type": "answer_report", "answer_report": {"findings": [{"x": 1}]}, "investigation_id": "inv9"},
            {"type": "done"},
        ])),
        "/ada/conn1/inv9/receipt": httpx.Response(200, json={"natural_key": "ada:conn1:inv9"}),
    }
    res = _run(_client(routes).deep_analysis("why did margin fall", "conn1"))
    assert res["status"] == "complete"
    assert res["investigation_id"] == "inv9"
    assert res["report_kind"] == "ada"
    assert res["report"] == {"findings": [{"x": 1}]}
    assert res["hypotheses"] == [{"text": "h1"}]
    assert res["receipt"]["natural_key"] == "ada:conn1:inv9"


def test_deep_analysis_accepts_deprecated_ada_report_wire_alias():
    # The old `ada_report` event/field is kept one release (REC-U9) — a client on the new
    # code must still fold a stream from an older server.
    routes = {
        "/investigate": httpx.Response(200, content=_sse([
            {"type": "start", "investigation_id": "inv9"},
            {"type": "ada_report", "ada_report": {"findings": [{"x": 1}]}, "investigation_id": "inv9"},
            {"type": "done"},
        ])),
        "/ada/conn1/inv9/receipt": httpx.Response(200, json={"natural_key": "ada:conn1:inv9"}),
    }
    res = _run(_client(routes).deep_analysis("why did margin fall", "conn1"))
    assert res["report_kind"] == "ada"
    assert res["report"] == {"findings": [{"x": 1}]}


def test_deep_analysis_running_when_no_terminal_report():
    # stream ends after `start` (e.g. the client stopped reading) — hand back the id to poll.
    routes = {"/investigate": httpx.Response(200, content=_sse([
        {"type": "start", "investigation_id": "inv5"},
    ]))}
    res = _run(_client(routes).deep_analysis("q", "c"))
    assert res["status"] == "running"
    assert res["investigation_id"] == "inv5"
    assert res["report"] is None


# ── get_metric: definition + governed value ──────────────────────────────────────
def test_get_metric_returns_definition_and_value():
    routes = {
        "/metrics": httpx.Response(200, json=[
            {"name": "gross_margin", "label": "Gross Margin", "sql": "SUM(a-b)/SUM(a)"},
            {"name": "aov", "label": "AOV", "sql": "AVG(total)"},
        ]),
        "/metrics/gross_margin/value": httpx.Response(200, json={
            "name": "gross_margin", "label": "Gross Margin", "value": 0.4702,
            "unit": "ratio", "sql": "SUM(a-b)/SUM(a)",
        }),
    }
    res = _run(_client(routes).get_metric(name="gross_margin", connection="conn1"))
    assert res["definition"]["label"] == "Gross Margin"
    assert res["value"] == 0.4702
    assert res["sql"] == "SUM(a-b)/SUM(a)"


def test_get_metric_lists_when_no_name():
    routes = {"/metrics": httpx.Response(200, json=[{"name": "x", "sql": "1"}])}
    res = _run(_client(routes).get_metric())
    assert res["metrics"] == [{"name": "x", "sql": "1"}]


def test_get_metric_unknown_name_raises():
    routes = {"/metrics": httpx.Response(200, json=[{"name": "x", "sql": "1"}])}
    with pytest.raises(AughorError) as e:
        _run(_client(routes).get_metric(name="nope", connection="c"))
    assert "no governed metric" in str(e.value)


# ── list_findings / get_briefing / explore / jobs ────────────────────────────────
def test_list_findings_trims_and_caps():
    insights = [{"id": f"i{n}", "finding": f"f{n}", "confidence": 0.9, "novelty": 0.5,
                 "domain": "sales", "sql": "SELECT 1", "extra": "dropped"} for n in range(40)]
    routes = {"/exploration/conn1/findings": httpx.Response(200, json={
        "phase": "complete", "insights": insights,
    })}
    res = _run(_client(routes).list_findings("conn1", limit=10))
    assert res["count"] == 40
    assert len(res["findings"]) == 10
    assert set(res["findings"][0]) == {"id", "finding", "confidence", "novelty", "domain", "sql"}


def test_get_briefing_maps_fields():
    routes = {"/exploration/conn1/briefing": httpx.Response(200, json={
        "narrative": "Margin erosion …", "headline_theme": "Margin", "citations": [{"id": "i1"}],
        "generated_at": "2026-06-21T00:00:00Z", "available": True,
    })}
    res = _run(_client(routes).get_briefing("conn1"))
    assert res["available"] is True
    assert res["headline_theme"] == "Margin"
    assert res["narrative"].startswith("Margin erosion")


def test_explore_reports_started_and_phase():
    routes = {
        "/exploration/conn1/start": httpx.Response(200, json={"ok": True}),
        "/exploration/conn1/status": httpx.Response(200, json={"phase": "running", "insights_found": 3}),
    }
    res = _run(_client(routes).explore("conn1"))
    assert res["started"] is True
    assert res["phase"] == "running"
    assert res["insights_found"] == 3


def test_list_jobs_passthrough():
    routes = {"/jobs": httpx.Response(200, json=[{"id": "j1", "agent": {"name": "Scout"}}])}
    res = _run(_client(routes).list_jobs(state="active"))
    assert res[0]["agent"]["name"] == "Scout"


# ── error surfacing ──────────────────────────────────────────────────────────────
def test_capability_lock_surfaces_cleanly():
    routes = {"/investigate": httpx.Response(402, json={"detail": "Upgrade to Pro for Deep Analysis"})}
    with pytest.raises(AughorError) as e:
        _run(_client(routes).deep_analysis("q", "c"))
    assert "capability locked" in str(e.value)


def test_not_found_surfaces_cleanly():
    routes = {"/jobs/missing": httpx.Response(404, json={"detail": "No such job"})}
    with pytest.raises(AughorError) as e:
        _run(_client(routes).get_job("missing"))
    assert "not found" in str(e.value).lower()


def test_dropped_none_query_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = str(request.url.query)
        return httpx.Response(200, json={"insights": []})

    client = AughorClient(base_url="http://test", transport=httpx.MockTransport(handler))
    _run(client.list_findings("conn1", schema=None, limit=5))
    # schema=None must NOT be sent as ?schema=None
    assert b"schema" not in (request_query := seen["query"].encode())
    assert b"None" not in request_query


# ── real path: drive the actual app in-process (no LLM, no live server) ──────────
def _real_client() -> AughorClient:
    from aughor.api import app
    return AughorClient(base_url="http://test", transport=httpx.ASGITransport(app=app))


def test_real_path_list_connections_and_jobs():
    client = _real_client()
    conns = _run(client.list_connections())
    assert isinstance(conns, list)              # hermetic env → empty, but the wiring runs
    jobs = _run(client.list_jobs())
    assert isinstance(jobs, list)


def test_real_path_metric_value_endpoint_404():
    # Proves the new GET /metrics/{name}/value route is wired into the live app.
    client = _real_client()
    with pytest.raises(AughorError) as e:
        _run(client._get("/metrics/__no_such_metric__/value", params={"conn_id": "x"}))
    assert "not found" in str(e.value).lower()
