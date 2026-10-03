"""DE-2b and DE-2c (ROADMAP §3.51; §6 item 37(c)) — an outside agent is a principal with a policy.

DE-2b: one policy per organisation — `read`, `run`, `act` — with connection and tool
allowlists, kept with the organisation's per-org settings, `run` by default and `act` only by a
person, narrowed (never widened) by the environment, enforced in the API on every request the
MCP client marks as its own, refused with stable codes, audited with its principal; the MCP
server hides a disallowed tool from `tools/list` and refuses it by name; every tool carries
`readOnlyHint` / `destructiveHint`. DE-2c: the four knowledge tools reach their bodies through
the API, under the request's organisation, user and RBAC.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from aughor.mcp import policy as P
from aughor.mcp import server as S
from aughor.mcp.client import AGENT_HEADER, AGENT_MARK, TOOL_HEADER, AughorClient
from aughor.orgsettings import agent_policy as AP

ORG = "default"      # identity is off in the suite, so every request is the default organisation's
AGENT = {AGENT_HEADER: AGENT_MARK}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_policy(monkeypatch):
    for var in ("AUGHOR_AGENT_POLICY_LEVEL", "AUGHOR_AGENT_POLICY_CONNECTIONS", "AUGHOR_AGENT_POLICY_TOOLS"):
        monkeypatch.delenv(var, raising=False)
    AP.clear_agent_policy(ORG)
    S.forget_policy()
    yield
    AP.clear_agent_policy(ORG)
    S.forget_policy()


# ── the store ────────────────────────────────────────────────────────────────────────

def test_an_install_with_no_saved_policy_runs_at_run_and_says_it_is_the_default():
    p = AP.effective_agent_policy(ORG)
    assert p.level == "run" and p.source == "default" and p.set_by == ""
    assert p.allows_level("read") and p.allows_level("run") and not p.allows_level("act")
    assert p.allows_tool("anything") and p.allows_connection("c1")


def test_a_person_saves_a_policy_and_it_is_read_on_the_next_call():
    saved = AP.save_agent_policy(ORG, level="read", connections=["c1", "c1", " c2 "], tools=["ask", "list_connections"],
                                 set_by="ana")
    assert saved.level == "read" and saved.connections == ("c1", "c2") and saved.tools == ("ask", "list_connections")
    assert saved.set_by == "ana" and saved.source == "saved" and saved.updated_at
    assert AP.effective_agent_policy(ORG).level == "read"
    assert not AP.effective_agent_policy(ORG).allows_connection("c3")
    with pytest.raises(ValueError):
        AP.save_agent_policy(ORG, level="act", set_by="")        # nobody grants act
    with pytest.raises(ValueError):
        AP.save_agent_policy(ORG, level="root", set_by="ana")
    AP.clear_agent_policy(ORG)
    assert AP.effective_agent_policy(ORG).source == "default"


def test_the_environment_narrows_and_never_widens(monkeypatch):
    AP.save_agent_policy(ORG, level="act", connections=["c1", "c2"], set_by="ana")
    monkeypatch.setenv("AUGHOR_AGENT_POLICY_LEVEL", "read")
    monkeypatch.setenv("AUGHOR_AGENT_POLICY_CONNECTIONS", "c2,c3")
    monkeypatch.setenv("AUGHOR_AGENT_POLICY_TOOLS", "list_connections,ask")
    p = AP.effective_agent_policy(ORG)
    assert p.level == "read" and p.connections == ("c2",) and p.tools == ("ask", "list_connections")
    assert p.source == "narrowed" and set(p.narrowed_by) == {"level", "connections", "tools"}
    # The other way round: a saved `read` and an environment `act` stay `read`.
    AP.save_agent_policy(ORG, level="read", set_by="ana")
    monkeypatch.setenv("AUGHOR_AGENT_POLICY_LEVEL", "act")
    monkeypatch.delenv("AUGHOR_AGENT_POLICY_CONNECTIONS")
    monkeypatch.delenv("AUGHOR_AGENT_POLICY_TOOLS")
    p = AP.effective_agent_policy(ORG)
    assert p.level == "read" and p.source == "saved"
    # An unreadable cap is the tightest cap, not no cap.
    monkeypatch.setenv("AUGHOR_AGENT_POLICY_LEVEL", "everything")
    assert AP.effective_agent_policy(ORG).level == "read"


# ── the levels ───────────────────────────────────────────────────────────────────────

def test_every_registered_tool_has_a_level_and_the_routes_classify():
    registered = set(S.mcp._tool_manager._tools)
    assert set(P.TOOL_LEVELS) == registered, "a tool with no level is a registration mistake"
    assert P.tool_level("cancel_job") == "act" and P.tool_level("ask") == "run" and P.tool_level("list_connections") == "read"
    assert P.tool_level("some_automation") == "act", "an unknown dynamic tool is an act, conservatively"
    assert P.route_level("POST", "/chat") == "run" and P.route_level("POST", "/jobs/{job_id}/cancel") == "act"
    assert P.route_level("GET", "/connections") == "read" and P.route_level("DELETE", "/things/{id}") == "act"
    assert P.route_level("POST", "/spotlight/tools/{tool_name}", "platform_usage") == "read"
    assert P.route_level("POST", "/spotlight/tools/{tool_name}", "draft_automation") == "act"
    assert P.tool_annotations("read").readOnlyHint is True and P.tool_annotations("act").destructiveHint is True
    assert P.tool_annotations("run").readOnlyHint is False and P.tool_annotations("run").destructiveHint is False


def test_the_spotlight_act_names_are_the_rosters_own():
    """The level map's copy of Spotlight's act limb is held to the roster, so a new act tool
    cannot arrive classified as a read."""
    from aughor.agent.spotlight_act import spotlight_act_tools
    assert P.SPOTLIGHT_ACT_TOOLS == {t.name for t in spotlight_act_tools("c1")}


# ── the API enforces it, and audits it ───────────────────────────────────────────────

def _api():
    from aughor.api import app
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_an_unmarked_request_is_untouched_even_under_a_read_policy():
    AP.save_agent_policy(ORG, level="read", set_by="ana")

    async def go():
        async with _api() as c:
            r = await c.post("/jobs/not-a-job/cancel")
            return r.status_code
    assert _run(go()) != 403, "the web app and every other caller are not agents"


def test_the_default_policy_refuses_an_act_by_name_and_serves_a_read():
    async def go():
        async with _api() as c:
            refused = await c.post("/jobs/not-a-job/cancel", headers={**AGENT, TOOL_HEADER: "cancel_job"})
            served = await c.get("/connections", headers={**AGENT, TOOL_HEADER: "list_connections"})
            return refused, served
    refused, served = _run(go())
    assert refused.status_code == 403
    body = refused.json()["detail"]
    assert body["error"] == "agent_policy_denied" and body["code"] == P.CODE_LEVEL
    assert body["tool"] == "cancel_job" and body["policy_level"] == "run" and body["required_level"] == "act"
    assert served.status_code == 200


def test_a_read_policy_hides_run_and_a_grant_of_act_opens_the_cancel():
    AP.save_agent_policy(ORG, level="read", set_by="ana")

    async def go():
        async with _api() as c:
            chat = await c.post("/chat", json={"question": "how many orders?", "connection_id": "c1"},
                                headers={**AGENT, TOOL_HEADER: "ask"})
            AP.save_agent_policy(ORG, level="act", set_by="ana")
            cancel = await c.post("/jobs/not-a-job/cancel", headers={**AGENT, TOOL_HEADER: "cancel_job"})
            return chat, cancel
    chat, cancel = _run(go())
    assert chat.status_code == 403 and chat.json()["detail"]["code"] == P.CODE_LEVEL
    assert chat.json()["detail"]["required_level"] == "run"
    assert cancel.status_code != 403, "a person granted act; the route itself answers now"


def test_tool_and_connection_allowlists_refuse_by_name_including_a_connection_in_the_body():
    AP.save_agent_policy(ORG, level="run", connections=["c1"], tools=["list_connections", "ask", "list_findings"], set_by="ana")

    async def go():
        async with _api() as c:
            tool = await c.get("/metrics", headers={**AGENT, TOOL_HEADER: "get_metric"})
            path = await c.get("/exploration/c2/findings", headers={**AGENT, TOOL_HEADER: "list_findings"})
            body = await c.post("/chat", json={"question": "q", "connection_id": "c2"}, headers={**AGENT, TOOL_HEADER: "ask"})
            ok = await c.get("/exploration/c1/findings", headers={**AGENT, TOOL_HEADER: "list_findings"})
            return tool, path, body, ok
    tool, path, body, ok = _run(go())
    assert tool.status_code == 403 and tool.json()["detail"]["code"] == P.CODE_TOOL
    assert path.status_code == 403 and path.json()["detail"]["code"] == P.CODE_CONNECTION
    assert path.json()["detail"]["connection"] == "c2"
    assert body.status_code == 403 and body.json()["detail"]["code"] == P.CODE_CONNECTION
    assert ok.status_code != 403


def test_every_agent_call_is_audited_with_its_principal_and_shows_on_the_governance_feed():
    from aughor.govern.audit_categories import KIND_CATEGORY, feed

    assert KIND_CATEGORY["mcp.tool_call"] == "data_access"

    import uuid
    robot = f"robot-{uuid.uuid4().hex[:8]}"

    async def go():
        async with _api() as c:
            await c.post("/jobs/not-a-job/cancel", headers={**AGENT, TOOL_HEADER: "cancel_job", "X-Aughor-User": robot})
            await c.get("/connections", headers={**AGENT, TOOL_HEADER: "list_connections", "X-Aughor-User": robot})
    _run(go())
    events = [e for e in feed(category="data_access", limit=500)
              if e.kind == "mcp.tool_call" and e.detail.get("actor") == robot]
    assert len(events) == 2, "one audit row per agent call, allowed or refused"
    by_tool = {e.detail.get("tool"): e for e in events}
    refused, served = by_tool["cancel_job"], by_tool["list_connections"]
    assert refused.detail["allowed"] is False and refused.detail["code"] == P.CODE_LEVEL
    assert refused.detail["required_level"] == "act" and refused.detail["policy_level"] == "run"
    assert refused.actor == robot and "refused (AGENT_LEVEL_DENIED)" in refused.summary
    assert served.detail["allowed"] is True and served.detail["code"] is None and "allowed" in served.summary


def test_the_policy_route_is_set_by_a_person_and_refuses_the_agent():
    async def go():
        async with _api() as c:
            before = await c.get("/org-settings/agent-policy")
            by_agent = await c.put("/org-settings/agent-policy", json={"level": "act"}, headers=AGENT)
            by_person = await c.put("/org-settings/agent-policy", json={"level": "act", "connections": ["c1"]})
            after = await c.get("/org-settings/agent-policy")
            cleared = await c.delete("/org-settings/agent-policy")
            return before, by_agent, by_person, after, cleared
    before, by_agent, by_person, after, cleared = _run(go())
    assert before.status_code == 200 and before.json()["effective"]["level"] == "run" and before.json()["saved"] is None
    assert by_agent.status_code == 403 and by_agent.json()["detail"]["code"] == P.CODE_SELF_SET
    assert by_person.status_code == 200
    eff = after.json()["effective"]
    assert eff["level"] == "act" and eff["connections"] == ["c1"] and eff["set_by"] == "api-key"
    assert cleared.json()["effective"]["source"] == "default"


# ── the MCP server hides, refuses by name, and carries the hints ─────────────────────

def _policy_answer(level: str, tools=None):
    async def agent_policy():
        return {"effective": {"level": level, "connections": None, "tools": tools, "set_by": "ana", "source": "saved"}}
    return agent_policy


def test_a_read_policy_hides_explore_and_refuses_it_by_name(monkeypatch):
    monkeypatch.setattr(S._client, "agent_policy", _policy_answer("read"))
    S.forget_policy()
    listed = {t.name: t for t in _run(S.mcp.list_tools())}
    assert "explore" not in listed and "ask" not in listed and "cancel_job" not in listed
    assert {"list_connections", "search_graph", "get_table_health", "list_runs"} <= set(listed)
    assert listed["list_connections"].annotations.readOnlyHint is True
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError) as e:
        _run(S.mcp.call_tool("explore", {"connection": "c1"}))
    body = json.loads(str(e.value))
    assert body["code"] == P.CODE_LEVEL and body["tool"] == "explore" and body["required_level"] == "run"


def test_an_act_policy_lists_the_act_tool_with_its_destructive_hint(monkeypatch):
    monkeypatch.setattr(S._client, "agent_policy", _policy_answer("act"))
    S.forget_policy()
    listed = {t.name: t for t in _run(S.mcp.list_tools())}
    assert listed["cancel_job"].annotations.destructiveHint is True
    assert listed["ask"].annotations.readOnlyHint is False and listed["ask"].annotations.destructiveHint is False


def test_a_tool_allowlist_hides_the_rest_and_refuses_them_by_name(monkeypatch):
    monkeypatch.setattr(S._client, "agent_policy", _policy_answer("run", tools=["list_connections"]))
    S.forget_policy()
    assert {t.name for t in _run(S.mcp.list_tools())} == {"list_connections"}
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError) as e:
        _run(S.mcp.call_tool("list_findings", {"connection": "c1"}))
    assert json.loads(str(e.value))["code"] == P.CODE_TOOL


def test_when_the_api_cannot_be_asked_the_default_run_applies(monkeypatch):
    async def down():
        raise RuntimeError("connection refused")
    monkeypatch.setattr(S._client, "agent_policy", down)
    S.forget_policy()
    names = {t.name for t in _run(S.mcp.list_tools())}
    assert "cancel_job" not in names and {"ask", "explore", "list_connections"} <= names


# ── DE-2c: the knowledge tools go through the API ────────────────────────────────────

def test_the_knowledge_tools_call_the_api_with_the_agent_mark_and_the_tool_name(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/org-settings/agent-policy":
            return httpx.Response(200, json={"effective": {"level": "run", "connections": None, "tools": None}})
        if request.url.path == "/knowledge/c1/graph/search":
            return httpx.Response(200, json={"available": True, "nodes": [{"id": "table:orders"}], "q": request.url.params["q"]})
        if request.url.path == "/knowledge/c1/table-health":
            return httpx.Response(200, json={"checked": False, "table": request.url.params["table"]})
        return httpx.Response(404, json={"detail": "no such route in this fake"})

    fake = AughorClient(base_url="http://t", api_key="", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(S, "_client", fake)
    S.forget_policy()
    out = _run(S.mcp.call_tool("search_graph", {"connection": "c1", "query": "orders"}))
    health = _run(S.mcp.call_tool("get_table_health", {"connection": "c1", "table": "orders"}))
    assert any(r.url.path == "/knowledge/c1/graph/search" for r in seen)
    search_req = next(r for r in seen if r.url.path == "/knowledge/c1/graph/search")
    assert search_req.headers[AGENT_HEADER] == AGENT_MARK and search_req.headers[TOOL_HEADER] == "search_graph"
    assert "table:orders" in json.dumps(out if isinstance(out, dict) else [b.model_dump() for b in out])
    assert "orders" in json.dumps(health if isinstance(health, dict) else [b.model_dump() for b in health])


def test_the_knowledge_routes_run_the_same_bodies_in_the_api_process():
    async def go():
        async with _api() as c:
            health = await c.get("/knowledge/c-none/table-health", params={"table": "orders"}, headers=AGENT)
            trusted = await c.get("/knowledge/c-none/trusted-queries", headers=AGENT)
            search = await c.get("/knowledge/c-none/graph/search", params={"q": "orders"}, headers=AGENT)
            return health, trusted, search
    health, trusted, search = _run(go())
    assert health.status_code == 200 and health.json().get("checked") is False, health.text
    assert trusted.status_code == 200 and search.status_code == 200
    assert search.json().get("available") is False, "no graph is built for this connection, and it says so"


def test_the_knowledge_tools_are_still_readable_under_a_read_policy_through_the_api():
    AP.save_agent_policy(ORG, level="read", set_by="ana")

    async def go():
        async with _api() as c:
            return await c.get("/knowledge/c-none/table-health", params={"table": "orders"},
                               headers={**AGENT, TOOL_HEADER: "get_table_health"})
    assert _run(go()).status_code == 200
