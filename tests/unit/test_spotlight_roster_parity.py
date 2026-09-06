"""SP-5 (§3.11) — one roster, every door: the parity ratchet.

The receipt the wave names: "a diff of the two rosters returns empty and is ratcheted
so it stays empty." Both sides here are LIVE constructions, never greps — the converse
roster is built, the HTTP listing is served, the MCP registration is driven — so a
tool added to one transport without the others is a failing test, not a drift
([[grep-and-count-false-negatives]]'s lesson, applied to the arc's first law).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.agent.spotlight_roster import spotlight_roster
from aughor.api import app

client = TestClient(app)


def _declared() -> dict[str, str]:
    return {t.name: t.description for t in spotlight_roster("parity-conn")}


# ── the declaration reaches every transport ────────────────────────────────────────

def test_conversation_carries_exactly_the_declared_roster():
    from aughor.agent.converse_tools import converse_tools
    declared = _declared()
    conversational = {t.name: t.description for t in converse_tools("parity-conn")}
    missing = set(declared) - set(conversational)
    assert not missing, f"declared tools absent from conversation: {sorted(missing)}"
    drifted = [n for n in declared if conversational[n] != declared[n]]
    assert not drifted, f"descriptions drifted between declaration and conversation: {drifted}"


def test_http_listing_diffs_empty_against_the_declaration():
    declared = _declared()
    listed = {t["name"]: t["description"]
              for t in client.get("/spotlight/tools").json()["tools"]}
    assert listed == declared            # names AND descriptions — the routing policy


def test_mcp_registration_diffs_empty_against_the_declaration():
    """Drive the real registration function against the real listing payload — the
    transport registers FROM the declaration, and the diff is empty."""
    import asyncio

    from aughor.mcp import server as mcp_server

    payload = client.get("/spotlight/tools").json()["tools"]

    class _StubApi:
        async def list_spotlight_tools(self):
            return payload

    registered: dict[str, str] = {}

    class _StubMcp:
        _tool_manager = type("TM", (), {"_tools": {}})()

        @staticmethod
        def add_tool(fn, name="", description=""):
            registered[name] = description

    real_mcp = mcp_server.mcp
    mcp_server.mcp = _StubMcp()
    try:
        added = asyncio.run(mcp_server.register_spotlight_tools(_StubApi()))
    finally:
        mcp_server.mcp = real_mcp

    declared = _declared()
    assert set(added) == set(declared)
    # The declared description leads on the MCP side too (an argument rendering may
    # follow it, because that transport passes arguments as one object).
    for name, desc in declared.items():
        assert registered[name].startswith(desc), f"{name}: declared description not led with"


def test_mcp_registration_skips_a_collision_rather_than_shadowing():
    import asyncio

    from aughor.mcp import server as mcp_server

    class _StubApi:
        async def list_spotlight_tools(self):
            return [{"name": "ask", "description": "collides", "parameters": {}},
                    {"name": "platform_usage", "description": "fine", "parameters": {}}]

    class _StubMcp:
        _tool_manager = type("TM", (), {"_tools": {"ask": object()}})()

        @staticmethod
        def add_tool(fn, name="", description=""):
            pass

    real_mcp = mcp_server.mcp
    mcp_server.mcp = _StubMcp()
    try:
        added = asyncio.run(mcp_server.register_spotlight_tools(_StubApi()))
    finally:
        mcp_server.mcp = real_mcp
    assert added == ["platform_usage"]   # 'ask' skipped, never shadowed


# ── the dispatch door ──────────────────────────────────────────────────────────────

def test_dispatch_runs_the_same_body_conversation_runs():
    r = client.post("/spotlight/tools/platform_guide",
                    json={"connection_id": "parity-conn", "args": {"topic": "nope"}})
    assert r.status_code == 200
    out = r.json()["result"]
    assert set(out["topics"]) == {"create_agent", "create_automation",
                                  "connect_data", "appearance"}


def test_dispatch_refuses_an_unknown_tool_naming_the_roster():
    r = client.post("/spotlight/tools/imaginary_tool", json={"args": {}})
    assert r.status_code == 404
    assert "platform_usage" in r.json()["detail"]


def test_dispatch_relays_a_raising_tool_as_a_refusal(monkeypatch):
    monkeypatch.setattr("aughor.obs.session_log.recent_sessions",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("ledger gone")))
    r = client.post("/spotlight/tools/platform_traces", json={"args": {}})
    assert r.status_code == 200
    assert "RuntimeError" in r.json()["result"]["error"]
