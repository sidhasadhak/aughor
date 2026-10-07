"""The header an http MCP server's credential travels in (2026-10-07).

The consumer forwarded `auth_header` only as `Authorization`. Composio takes its key only as
`x-api-key` (required on every MCP request since April 2026), so a real Composio run could not
authenticate at all. A server now names its header; the default is the one it always was.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.mcpservers import session as S
from aughor.mcpservers import store
from aughor.mcpservers.models import McpServer

_URL = "https://backend.composio.dev/v3/mcp/srv_test?user_id=u1"


@pytest.fixture(autouse=True)
def _clean_allowlist():
    for s in store.list_servers():
        store.delete_server(s.id)
    yield
    for s in store.list_servers():
        store.delete_server(s.id)


def _http(**over) -> McpServer:
    return McpServer(**{"name": "Composio", "transport": "http", "url": _URL, **over})


def test_the_default_header_is_authorization_exactly_as_before():
    assert _http(auth_header="Bearer k").auth_header_name == "Authorization"
    assert _http(auth_header="Bearer k", auth_header_name="  ").auth_header_name == "Authorization"


def test_a_server_may_name_its_own_header():
    assert _http(auth_header="ak_test", auth_header_name=" x-api-key ").auth_header_name == "x-api-key"


@pytest.mark.parametrize("bad", ["x api key", "x-api-key:", "Content-Type", "host", "Mcp-Session-Id"])
def test_a_name_that_is_not_a_header_or_is_the_connections_own_is_refused(bad):
    with pytest.raises(ValueError):
        _http(auth_header="k", auth_header_name=bad)


def test_the_connection_sends_the_credential_in_the_named_header(monkeypatch):
    import mcp.client.streamable_http as transport

    seen: dict = {}

    @asynccontextmanager
    async def capture(url, headers=None, timeout=None, auth=None):
        seen["headers"] = headers
        raise RuntimeError("stopped before connecting")
        yield  # pragma: no cover

    monkeypatch.setattr(transport, "streamablehttp_client", capture)

    async def open_(server):
        async with S.open_session(server, 1.0):
            pass

    with pytest.raises(RuntimeError, match="stopped before connecting"):
        asyncio.run(open_(_http(auth_header="ak_test", auth_header_name="x-api-key")))
    assert seen["headers"] == {"x-api-key": "ak_test"}
    with pytest.raises(RuntimeError, match="stopped before connecting"):
        asyncio.run(open_(_http(auth_header="Bearer k")))
    assert seen["headers"] == {"Authorization": "Bearer k"}


def test_a_read_names_the_header_and_an_update_that_omits_it_keeps_it():
    from aughor.routers.mcpservers import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    created = client.post("/mcp-servers", json={"name": "Composio", "transport": "http", "url": _URL,
                                                "auth_header": "ak_test", "auth_header_name": "x-api-key"})
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["auth_header_name"] == "x-api-key" and row["has_auth"] is True
    assert "ak_test" not in created.text, "the key itself is never read back"

    # A client written before the field existed renames the server and sends no header name.
    renamed = client.put(f"/mcp-servers/{row['id']}", json={"name": "Composio (prod)", "transport": "http", "url": _URL})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["auth_header_name"] == "x-api-key"
    assert store.get_server(row["id"]).auth_header == "ak_test", "an omitted value keeps the stored key"

    moved = client.put(f"/mcp-servers/{row['id']}", json={"name": "Composio (prod)", "transport": "http", "url": _URL,
                                                          "auth_header_name": "Authorization"})
    assert moved.json()["auth_header_name"] == "Authorization"

    refused = client.post("/mcp-servers", json={"name": "Bad", "transport": "http", "url": _URL,
                                                "auth_header": "k", "auth_header_name": "Content-Type"})
    assert refused.status_code == 400 and "Content-Type" in refused.json()["detail"]


def test_a_refusal_says_the_status_the_servers_reason_and_the_header_the_key_went_in():
    """Composio refused a key sent in a misnamed header (2026-10-07), and the reader was shown
    only "ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)" — the SDK runs its
    transport in a task group. A local server refuses the way Composio did, through the real SDK."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Refuse(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer error="unauthorized", '
                                                 'error_description="No Authorization: Bearer header on request"')
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"Authorization required"}')

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/mcp"
        with pytest.raises(S.McpUnreachable) as refused:
            S.list_tools(McpServer(name="Composio", transport="http", url=url, auth_header="ck_test",
                                   auth_header_name="thelook-composio"), timeout_s=10)
    finally:
        httpd.shutdown()
    assert str(refused.value) == ('the server answered 401 Unauthorized, saying "No Authorization: Bearer header '
                                  'on request" — the credential went in the thelook-composio header')
