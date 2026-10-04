"""Our MCP server, as a client meets it (PENDING: Spotlight — "tools exposed over MCP do not
describe their arguments properly, and clients must reconnect to see new ones"; Automations —
"an automation newly exposed as an MCP tool only appears after the client reconnects").

Driven through a REAL client session (the SDK's in-memory transport), not by inspecting the
server's dicts: the client sees each Spotlight tool's declared JSON Schema and sends native
arguments; the server declares `tools.listChanged`; and when an agent appears and another is
disabled, the client is TOLD on its next call and re-lists them — without reconnecting.
"""
from __future__ import annotations

import asyncio

from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from aughor.mcp import server as srv

PREFERENCE = {"name": "set_preference", "description": "Set one appearance preference.",
              "parameters": {"type": "object", "properties": {
                  "key": {"type": "string", "description": "theme or density"},
                  "value": {"type": "string", "enum": ["dark", "light", "system"]}},
                  "required": ["key", "value"]}}


class _Api:
    def __init__(self):
        self.agents = [{"id": "ag1", "name": "Ops", "enabled": True, "purpose": "ops"}]
        self.spotlight_calls: list[tuple[str, str, dict]] = []

    async def list_spotlight_tools(self):
        return [PREFERENCE]

    async def list_user_agents(self):
        return list(self.agents)

    async def list_automation_tools(self):
        return []

    async def call_spotlight_tool(self, name, *, connection="", args=None):
        self.spotlight_calls.append((name, connection, dict(args or {})))
        return {"ok": True}

    async def agent_policy(self):
        return {"effective": {"level": "act"}}


def test_a_client_sees_declared_arguments_and_a_list_that_changes_without_reconnecting(monkeypatch):
    api = _Api()
    monkeypatch.setattr(srv, "mcp", srv.PolicedFastMCP("t"))
    monkeypatch.setattr(srv, "_client", api)
    monkeypatch.setattr(srv, "_DYNAMIC", {})
    monkeypatch.setattr(srv, "_LIVE_SOURCES", set())
    monkeypatch.setattr(srv, "_live_checked", [])
    srv.forget_policy()

    async def run():
        assert await srv.register_spotlight_tools(api) == ["set_preference"]
        assert await srv.register_agent_tools(api) == ["ask_ops"]
        assert srv._LIVE_SOURCES == set()             # registering never turns the refresh on
        srv.enable_live_tools("spotlight", "agents")  # the entry point does
        told: list = []

        async def on_message(message):
            if isinstance(message, types.ServerNotification):
                told.append(type(message.root).__name__)

        async with create_connected_server_and_client_session(srv.mcp, message_handler=on_message) as client:
            assert client.get_server_capabilities().tools.listChanged is True
            listed = {t.name: t for t in (await client.list_tools()).tools}
            schema = listed["set_preference"].inputSchema
            assert schema["required"] == ["key", "value"]
            assert schema["properties"]["value"]["enum"] == ["dark", "light", "system"]
            assert "args" not in schema["properties"] and "connection" in schema["properties"]

            await client.call_tool("set_preference", {"key": "theme", "value": "dark"})
            assert api.spotlight_calls == [("set_preference", "", {"key": "theme", "value": "dark"})]

            api.agents = [{"id": "ag1", "name": "Ops", "enabled": False},
                          {"id": "ag2", "name": "Finance", "enabled": True, "purpose": "money"}]
            srv._live_checked.clear()                  # the TTL has passed
            await client.call_tool("set_preference", {"key": "theme", "value": "light"})
            for _ in range(50):                        # the notice arrives on the stream
                if "ToolListChangedNotification" in told:
                    break
                await asyncio.sleep(0.01)
            assert "ToolListChangedNotification" in told
            names = {t.name for t in (await client.list_tools()).tools}
            assert "ask_finance" in names and "ask_ops" not in names

    asyncio.run(run())
