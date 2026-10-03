"""Arc AO-5 — doors ×10: MCP, HTTP (+ embed), Teams, an inbound webhook, A2A.

Measured 2026-10-03 (docs/AGENT_OPS_STUDY_2026-10-03.md §2 finding 5): no external-agent
identity, no MCP door to a NAMED agent, no Teams, no embed, no A2A. Every door here hands
the question to the ask door AS the agent and names its caller as a principal; every
headless door carries its own credential and never opens the rest of the API. The ask
door itself is stubbed (`fold_ask`) — no model runs in these tests.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from aughor.custom_agents import create_agent, delete_agent, list_agents, update_agent
from aughor.custom_agents.keys import (agent_key_issued_at, agent_key_matches, issue_agent_key,
                                       revoke_agent_key)


@pytest.fixture(autouse=True)
def _clean():
    yield
    for a in list_agents():
        revoke_agent_key(a.id)
        delete_agent(a.id)
    from aughor.teamsbots import store
    for b in store.list_bots():
        store.delete_bot(b.id)


@pytest.fixture()
def client(monkeypatch):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(flags, "flag_enabled", lambda name: name == "agents.user_defined")
    from aughor.api import app
    return TestClient(app)


def _stub_fold(monkeypatch, seen: list):
    async def _fold(**kw):
        seen.append(kw)
        return {"agent_id": kw["agent_id"], "question": kw["question"],
                "headline": "There were 49 orders.", "sql": "SELECT COUNT(DISTINCT order_id) FROM orders",
                "columns": ["order_count"], "rows": [[49]], "row_count": 1, "receipt_id": "rc-1",
                "investigation_id": "inv-1", "error": "", "truncated": False, "frames": 7}
    monkeypatch.setattr("aughor.custom_agents.reach.fold_ask", _fold)
    return _fold


# ── the key ─────────────────────────────────────────────────────────────────────────

def test_the_agents_key_is_issued_once_compared_in_constant_time_and_revoked_by_deletion():
    a = create_agent("Keyed", instructions="x")
    assert agent_key_issued_at(a.id) == "" and not agent_key_matches(a.id, "anything")
    raw = issue_agent_key(a.id)
    assert agent_key_matches(a.id, raw) and not agent_key_matches(a.id, raw + "x")
    assert agent_key_issued_at(a.id)
    again = issue_agent_key(a.id)
    assert again != raw and not agent_key_matches(a.id, raw), "issuing replaces"
    assert revoke_agent_key(a.id) and not agent_key_matches(a.id, again)
    assert not revoke_agent_key(a.id)


def test_the_key_routes_mint_once_and_the_doors_route_says_the_state(client):
    a = create_agent("Doors", instructions="x", purpose="Orders questions")
    before = client.get(f"/agents/custom/{a.id}/doors").json()
    assert before["http"]["state"] == "no key" and before["mcp"]["tool"] == "ask_doors"
    assert before["embed"]["state"] == "needs the HTTP key" and before["a2a"]["card"].endswith("/.well-known/agent.json")
    r = client.post(f"/agents/custom/{a.id}/key")
    assert r.status_code == 200, r.text
    assert r.json()["key"] and "Authorization: Bearer" in r.json()["header"] and "curl" in r.json()
    after = client.get(f"/agents/custom/{a.id}/doors").json()
    assert after["http"]["state"] == "open" and after["http"]["key_issued_at"]
    assert r.json()["key"] not in json.dumps(after), "the status never discloses the key"
    assert client.delete(f"/agents/custom/{a.id}/key").status_code == 200
    assert client.get(f"/agents/custom/{a.id}/doors").json()["http"]["state"] == "no key"


# ── AO-5b · the HTTP door ───────────────────────────────────────────────────────────

def test_the_http_door_needs_the_agents_key_and_answers_as_the_agent(client, monkeypatch):
    seen: list = []
    _stub_fold(monkeypatch, seen)
    a = create_agent("Http", instructions="x", connection_id="conn-h")
    key = client.post(f"/agents/custom/{a.id}/key").json()["key"]
    body = {"question": "How many orders yesterday?", "asker": "me@example.com"}
    assert client.post(f"/doors/agents/{a.id}/ask", json=body).status_code == 401
    assert client.post(f"/doors/agents/{a.id}/ask", json=body,
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/doors/agents/ua_nobody/ask", json=body,
                       headers={"Authorization": f"Bearer {key}"}).status_code == 401, \
        "an unknown agent and a wrong key must look the same to a caller probing for agents"
    r = client.post(f"/doors/agents/{a.id}/ask", json=body, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    assert r.json()["headline"] == "There were 49 orders." and r.json()["rows"] == [[49]]
    assert seen[0]["agent_id"] == a.id and seen[0]["connection_id"] == "conn-h"
    assert seen[0]["principal_ref"] == "api:http:me@example.com"
    # The key opens the door, not the API.
    assert client.get("/doors/agents/x/nothing", headers={"Authorization": f"Bearer {key}"}).status_code in (404, 405)


def test_a_paused_agent_answers_nothing_and_says_so(client, monkeypatch):
    _stub_fold(monkeypatch, [])
    a = create_agent("Paused", instructions="x")
    key = client.post(f"/agents/custom/{a.id}/key").json()["key"]
    update_agent(a.id, enabled=False)
    r = client.post(f"/doors/agents/{a.id}/ask", json={"question": "q"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 409 and "paused" in r.json()["detail"]


# ── AO-5d · the webhook as a conversation ───────────────────────────────────────────

def test_the_webhook_answers_in_the_response_and_delivers_to_the_callback(client, monkeypatch):
    _stub_fold(monkeypatch, [])
    delivered: list = []
    monkeypatch.setattr("aughor.routers.doors._deliver", lambda url, ans: delivered.append((url, ans["headline"])) or {"ok": True, "status": 200})
    a = create_agent("Hook", instructions="x")
    key = client.post(f"/agents/custom/{a.id}/key").json()["key"]
    r = client.post(f"/doors/agents/{a.id}/webhook",
                    json={"question": "q", "callback_url": "https://example.com/in", "asker": "svc"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    assert r.json()["headline"] == "There were 49 orders." and r.json()["callback"] == {"ok": True, "status": 200}
    assert delivered == [("https://example.com/in", "There were 49 orders.")]
    r = client.post(f"/doors/agents/{a.id}/webhook", json={"question": "q"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.json()["callback"] is None


def test_a_callback_that_is_not_http_is_refused_not_tried(monkeypatch):
    from aughor.routers.doors import _deliver
    assert _deliver("file:///etc/passwd", {})["ok"] is False


# ── AO-5e · A2A ─────────────────────────────────────────────────────────────────────

def test_the_agent_card_lists_enabled_agents_as_skills_and_is_public(client):
    a = create_agent("Card", instructions="x", purpose="Churn questions", connection_id="c1")
    b = create_agent("Hidden", instructions="x")
    update_agent(b.id, enabled=False)
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["name"] == "Aughor" and card["authentication"]["schemes"] == ["bearer"]
    skills = {s["id"]: s for s in card["skills"]}
    assert a.id in skills and b.id not in skills
    assert skills[a.id]["description"] == "Churn questions" and skills[a.id]["url"].endswith(f"/doors/a2a/{a.id}")


def test_message_send_returns_a_completed_task_with_the_answer(client, monkeypatch):
    seen: list = []
    _stub_fold(monkeypatch, seen)
    a = create_agent("A2A", instructions="x")
    key = client.post(f"/agents/custom/{a.id}/key").json()["key"]
    rpc = {"jsonrpc": "2.0", "id": "7", "method": "message/send", "params": {"message": {
        "role": "user", "parts": [{"kind": "text", "text": "How many orders yesterday?"}],
        "metadata": {"asker": "other-agent"}}}}
    r = client.post(f"/doors/a2a/{a.id}", json=rpc, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    task = r.json()["result"]
    assert task["status"]["state"] == "completed"
    parts = task["artifacts"][0]["parts"]
    assert parts[0] == {"kind": "text", "text": "There were 49 orders."}
    assert parts[1]["data"]["sql"].startswith("SELECT") and parts[1]["data"]["rows"] == [[49]]
    assert seen[0]["principal_ref"] == "api:a2a:other-agent"
    bad = client.post(f"/doors/a2a/{a.id}", json={"jsonrpc": "2.0", "id": 1, "method": "tasks/cancel"},
                      headers={"Authorization": f"Bearer {key}"})
    assert bad.json()["error"]["code"] == -32601
    assert client.post(f"/doors/a2a/{a.id}", json=rpc).status_code == 401


# ── AO-5c · Teams ───────────────────────────────────────────────────────────────────

def _activity(**over):
    base = {"type": "message", "id": "act-1", "text": "How many orders yesterday?",
            "serviceUrl": "https://smba.trafficmanager.net/emea/",
            "conversation": {"id": "19:abc@thread.v2"},
            "from": {"id": "29:user-1", "name": "Amit"}, "recipient": {"id": "28:bot", "name": "Aughor"}}
    base.update(over)
    return base


def test_a_teams_bot_binds_an_app_to_an_agent_and_names_its_endpoint(client, monkeypatch):
    a = create_agent("Teams", instructions="x")
    r = client.post("/teams-bots", json={"name": "Aughor in Teams", "agent_id": a.id, "app_id": "app-1",
                                         "app_password": "pw-secret"})
    assert r.status_code == 200, r.text
    bot = r.json()["bot"]
    assert bot["app_password"] != "pw-secret" and "secret" not in bot["app_password"], "masked"
    assert r.json()["messaging_endpoint"] == "" and "HTTPS" in r.json()["needs"][0]
    monkeypatch.setenv("AUGHOR_PUBLIC_API_URL", "https://aughor.example.com")
    r2 = client.post("/teams-bots", json={"name": "b2", "agent_id": a.id, "app_id": "app-2", "app_password": "pw"})
    assert r2.json()["messaging_endpoint"] == f"https://aughor.example.com/doors/teams/{r2.json()['bot']['id']}/messages"
    assert client.post("/teams-bots", json={"name": "x", "app_id": "a", "app_password": ""}).status_code == 422
    assert client.get("/teams-bots").json()["bots"][0]["agent_id"] == a.id
    doors = client.get(f"/agents/custom/{a.id}/doors").json()
    assert doors["teams"]["state"] == "open" and len(doors["teams"]["bots"]) == 2
    assert client.delete(f"/teams-bots/{bot['id']}").status_code == 200


def test_an_inbound_activity_is_verified_answered_as_the_agent_and_replied(client, monkeypatch):
    seen: list = []
    _stub_fold(monkeypatch, seen)
    from aughor.teamsbots import reply, verify
    monkeypatch.setattr(verify, "verify_activity_token",
                        lambda auth, app_id: (auth == "Bearer good" and app_id == "app-1", "verified" if auth == "Bearer good" else "token refused"))
    monkeypatch.setattr(reply, "connector_token", lambda app_id, pw: (True, "tok") if pw == "pw-secret" else (False, "no"))
    sent: list = []
    monkeypatch.setattr(reply, "send_reply", lambda **kw: sent.append(kw) or (True, {"id": "reply-1"}))
    a = create_agent("Teams2", instructions="x", connection_id="c-t")
    bot_id = client.post("/teams-bots", json={"name": "b", "agent_id": a.id, "app_id": "app-1",
                                              "app_password": "pw-secret"}).json()["bot"]["id"]
    assert client.post(f"/doors/teams/{bot_id}/messages", json=_activity(),
                       headers={"Authorization": "Bearer forged"}).status_code == 401
    r = client.post(f"/doors/teams/{bot_id}/messages", json=_activity(), headers={"Authorization": "Bearer good"})
    assert r.status_code == 200, r.text
    assert r.json()["answered"] is True and r.json()["headline"] == "There were 49 orders."
    assert seen[0]["principal_ref"] == "teams:29:user-1" and seen[0]["session_id"] == "teams:19:abc@thread.v2"
    assert sent[0]["service_url"] == "https://smba.trafficmanager.net/emea/"
    assert sent[0]["conversation_id"] == "19:abc@thread.v2" and sent[0]["reply_to_id"] == "act-1"
    assert "There were 49 orders." in sent[0]["text"] and "```sql" in sent[0]["text"]
    typing = client.post(f"/doors/teams/{bot_id}/messages", json=_activity(type="typing"),
                         headers={"Authorization": "Bearer good"})
    assert typing.json() == {"ignored": "typing"}
    assert client.post("/doors/teams/tb_nobody/messages", json=_activity(),
                       headers={"Authorization": "Bearer good"}).status_code == 404


def test_the_rendered_teams_answer_carries_rows_and_sql():
    from aughor.teamsbots.reply import render_answer
    text = render_answer({"headline": "Two.", "columns": ["n"], "rows": [[1], [2]], "sql": "SELECT 1",
                          "receipt_id": "rc"})
    assert text.startswith("Two.") and "| n |" in text and "```sql" in text and "receipt rc" in text


# ── AO-5a · MCP: each custom agent a tool, its caller a principal ───────────────────

def _sse(events: list[dict]) -> str:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)


def _mcp_client(routes: dict):
    from aughor.mcp.client import AughorClient

    def handler(request: httpx.Request) -> httpx.Response:
        resp = routes.get(request.url.path)
        if resp is None:
            return httpx.Response(404, json={"detail": f"no mock route for {request.url.path}"})
        return resp(request) if callable(resp) else resp

    return AughorClient(base_url="http://test", transport=httpx.MockTransport(handler))


def test_each_enabled_custom_agent_becomes_a_tool_that_asks_as_it(monkeypatch):
    from aughor.mcp import server as S
    asks: list = []

    def _ask(request: httpx.Request) -> httpx.Response:
        asks.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=_sse([
            {"type": "agent", "agent_id": "ua_1"},
            {"type": "headline_delta", "headline": "There were"},
            {"type": "sql", "sql": "SELECT COUNT(*) FROM orders"},
            {"type": "columns", "columns": ["n"]},
            {"type": "rows", "rows": [[49]], "row_count": 1},
            {"type": "receipt_id", "receipt_id": "rc-9"},
            {"type": "headline", "headline": "There were 49 orders."},
            # The quick path's spelling of the turn id — the one the live door met (2026-10-03).
            {"type": "done", "inv_id": "inv-9"},
        ]))

    client = _mcp_client({
        "/agents/custom": httpx.Response(200, json=[
            {"id": "ua_1", "name": "The Look Analyst", "purpose": "Orders questions", "enabled": True,
             "connection_id": "c1", "schema_scope": "thelook"},
            {"id": "ua_2", "name": "Paused One", "enabled": False},
            # The same slug twice: the second must not shadow the first (nor can any agent
            # reach the governed `ask` — every agent tool is prefixed).
            {"id": "ua_3", "name": "The Look Analyst", "enabled": True},
        ]),
        "/ask": _ask,
    })
    added = asyncio.run(S.register_agent_tools(client))
    try:
        assert added == ["ask_the_look_analyst"], added
        tools = getattr(S.mcp._tool_manager, "_tools", {})
        desc = tools["ask_the_look_analyst"].description
        assert "Orders questions" in desc and "c1" in desc and "PROPOSE" in desc
        out = asyncio.run(tools["ask_the_look_analyst"].fn(question="How many orders yesterday?", asker="claude"))
        assert out["headline"] == "There were 49 orders." and out["sql"].startswith("SELECT")
        assert out["rows"] == [[49]] and out["receipt_id"] == "rc-9" and out["investigation_id"] == "inv-9"
        assert asks[0]["agent_id"] == "ua_1" and asks[0]["connection_id"] == "c1"
        assert asks[0]["principal_ref"] == "api:mcp:claude"
    finally:
        from aughor.mcp.policy import DYNAMIC_LEVELS
        for name in added:
            S.mcp._tool_manager.remove_tool(name)
            DYNAMIC_LEVELS.pop(name, None)


def test_an_unreachable_api_registers_nothing_and_raises_nothing():
    from aughor.mcp import server as S
    client = _mcp_client({})
    assert asyncio.run(S.register_agent_tools(client)) == []


def test_an_agents_tool_is_a_run_under_the_organisations_agent_policy(client, monkeypatch):
    """AO-5a held to DE-2b. An agent's tool is an ask AS that agent, so it needs what `ask`
    needs: the install's default policy (`run`) lists it with a run's hints, a `read` policy
    hides it, and the door it calls is a run at the API too. Measured 2026-10-03 with the
    two arcs combined: the tool was registered, then hidden and refused as an unmapped act."""
    from aughor.mcp import policy as P
    from aughor.mcp import server as S
    from aughor.mcp.client import AGENT_HEADER, AGENT_MARK, TOOL_HEADER
    from aughor.orgsettings import agent_policy as AP

    def _policy(level: str):
        async def agent_policy():
            return {"effective": {"level": level, "connections": None, "tools": None,
                                  "set_by": "ana", "source": "saved"}}
        return agent_policy

    added = asyncio.run(S.register_agent_tools(_mcp_client({"/agents/custom": httpx.Response(200, json=[
        {"id": "ua_1", "name": "The Look Analyst", "enabled": True, "connection_id": "c1"}])})))
    try:
        assert added == ["ask_the_look_analyst"] and P.tool_level(added[0]) == "run"
        monkeypatch.setattr(S._client, "agent_policy", _policy("run"))
        S.forget_policy()
        listed = {t.name: t for t in asyncio.run(S.mcp.list_tools())}
        hints = listed[added[0]].annotations
        assert hints.readOnlyHint is False and hints.destructiveHint is False
        monkeypatch.setattr(S._client, "agent_policy", _policy("read"))
        S.forget_policy()
        assert added[0] not in {t.name for t in asyncio.run(S.mcp.list_tools())}
    finally:
        for name in added:
            S.mcp._tool_manager.remove_tool(name)
            P.DYNAMIC_LEVELS.pop(name, None)
        S.forget_policy()
    assert P.tool_level("ask_the_look_analyst") == "act", "a level is the registrar's to declare, not the name's"

    # The door the tool calls. Under a `read` policy the API refuses it as the run it is —
    # before the fix it was refused as an act, and so refused under the default policy too.
    AP.save_agent_policy("default", level="read", set_by="ana")
    try:
        refused = client.post("/ask", json={"question": "How many orders?", "connection_id": "c1"},
                              headers={AGENT_HEADER: AGENT_MARK, TOOL_HEADER: "ask_the_look_analyst"})
    finally:
        AP.clear_agent_policy("default")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == P.CODE_LEVEL and refused.json()["detail"]["required_level"] == "run"


# ── the fold reads the quick path's own spelling of the turn ─────────────────────────

def test_the_fold_takes_the_turn_id_from_the_quick_paths_done_frame(monkeypatch):
    """Receipt 2026-10-03: a live door answer carried a receipt and NO investigation id — the
    quick path names its turn `inv_id` on `done`, the deep path `investigation_id` on
    `start`, and the fold read one spelling. A verdict needs the turn, so both are read."""
    import asyncio
    from aughor.custom_agents import reach

    async def _stream(_req, _user):
        for e in [{"type": "headline", "headline": "October."},
                  {"type": "columns", "columns": ["probe"]},
                  {"type": "rows", "rows": [[1]], "row_count": 1},
                  {"type": "sql", "sql": "SELECT 1"},
                  # The grid the closing prose is about — emitted again, last wins (the live
                  # door handed one row back twice before this).
                  {"type": "columns", "columns": ["month", "revenue"]},
                  {"type": "rows", "rows": [["2023-10", 49602.4]], "row_count": 1},
                  {"type": "receipt_id", "receipt_id": "rc-7"},
                  {"type": "done", "inv_id": "quick-7", "has_receipt": True}]:
            yield f"data: {json.dumps(e)}\n\n"

    monkeypatch.setattr("aughor.routers.investigations.build_ask_stream", _stream)
    out = asyncio.run(reach.fold_ask(agent_id="ua_x", question="q", connection_id="workspace",
                                     principal_ref="api:http:t", session_id="", depth="quick", max_rows=50))
    assert out["investigation_id"] == "quick-7" and out["receipt_id"] == "rc-7"
    assert out["headline"] == "October." and out["frames"] == 8
    assert out["columns"] == ["month", "revenue"] and out["rows"] == [["2023-10", 49602.4]]
    assert out["row_count"] == 1 and out["truncated"] is False
