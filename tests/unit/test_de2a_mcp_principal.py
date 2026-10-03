"""DE-2a — an outside agent is a principal, part a (ROADMAP §3.51; `docs/DBX_STUDY_2026-10-01.md` finding 3).

Measured on `f02c8f22`: the MCP client sent only `X-Api-Key`, so with `AUGHOR_REQUIRE_IDENTITY=1` every MCP call
was refused with a 401; the API compared the key with `!=`; FastMCP fixed a loopback-only host allowlist when the
server object was built at import, before `--host` was read. Run live on 2026-10-03 before the build, `--http
--host 0.0.0.0` answered a remote client `421 Invalid Host header` on every request and gave a loopback client with
no credential a full session.

What these pin: the client presents the principal it is given and nothing when given none; identity mode serves it
only with one; the key is compared in constant time; `--http` refuses to start without a token, refuses every
request without the bearer, and serves a remote client that presents it — the transport security built for the host
actually served.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from aughor.mcp.client import IDENTITY_ORG_HEADER, IDENTITY_USER_HEADER, AughorClient, AughorError

_PRINCIPAL_VARS = ("AUGHOR_MCP_ORG", "AUGHOR_MCP_USER", "AUGHOR_MCP_BEARER")


def _run(coro):
    return asyncio.run(coro)


# ── the client presents a principal ──────────────────────────────────────────────────────────────────────────────────

def test_the_client_presents_the_principal_it_is_given_and_nothing_otherwise(monkeypatch):
    for var in _PRINCIPAL_VARS:
        monkeypatch.delenv(var, raising=False)
    bare = AughorClient(base_url="http://t", api_key="")._headers()
    # Identity-off installs present no PRINCIPAL header; DE-2b added the agent mark, which is
    # what lets the API apply the organisation's agent policy to this client's calls.
    assert bare == {"accept": "application/json", "X-Aughor-Agent": "mcp"}, bare

    monkeypatch.setenv("AUGHOR_MCP_ORG", "acme")
    monkeypatch.setenv("AUGHOR_MCP_BEARER", "head.body.sig")
    h = AughorClient(base_url="http://t", api_key="k")._headers()
    assert h["X-Api-Key"] == "k"
    assert h["Authorization"] == "Bearer head.body.sig"
    assert h[IDENTITY_ORG_HEADER] == "acme" and h[IDENTITY_USER_HEADER] == "mcp", "an org names a user: `mcp`"
    assert AughorClient(base_url="http://t", org="acme", user="ana")._headers()[IDENTITY_USER_HEADER] == "ana"


def test_the_header_names_are_the_apis_own():
    """Spelled in the client so it stays httpx-only; held equal to the API's seam here."""
    from aughor.security import authz
    assert (IDENTITY_ORG_HEADER, IDENTITY_USER_HEADER) == (authz.IDENTITY_ORG_HEADER, authz.IDENTITY_USER_HEADER)


def test_identity_mode_serves_the_client_only_with_a_principal(monkeypatch):
    """Through the real app: the 401 the study measured, then the same call served once the client says who."""
    from aughor.api import app

    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    for var in _PRINCIPAL_VARS:
        monkeypatch.delenv(var, raising=False)

    anonymous = AughorClient(base_url="http://test", transport=httpx.ASGITransport(app=app))
    with pytest.raises(AughorError) as refused:
        _run(anonymous.list_connections())
    assert "401" in str(refused.value) and "identity required" in str(refused.value)

    named = AughorClient(base_url="http://test", transport=httpx.ASGITransport(app=app), org="acme", user="probe")
    assert isinstance(_run(named.list_connections()), list)


# ── the key is compared in constant time ─────────────────────────────────────────────────────────────────────────────

def _request(path: str = "/connections"):
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "scheme": "http", "server": ("test", 80), "path": path,
                    "query_string": b"", "headers": []})


def test_the_api_key_is_compared_in_constant_time(monkeypatch):
    import aughor.api as api

    seen: list[tuple] = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)
    monkeypatch.setattr(api.hmac, "compare_digest", spy)
    monkeypatch.setattr(api, "_API_KEY", "s3cret")

    with pytest.raises(HTTPException) as e:
        api._require_auth(_request(), key="wrong")
    assert e.value.status_code == 401 and seen == [("wrong", "s3cret")]
    api._require_auth(_request(), key="s3cret")                     # the right key passes
    api._require_auth(_request("/health"), key=None)                # an exempt path asks for none
    with pytest.raises(HTTPException):
        api._require_auth(_request(), key=None)                     # a missing key is a mismatch, not a crash


# ── --http has a door, and its transport security follows the host ───────────────────────────────────────────────────

def test_transport_security_follows_the_host():
    from aughor.mcp.server import transport_security_for

    loopback = transport_security_for("127.0.0.1")
    assert loopback.enable_dns_rebinding_protection and "127.0.0.1:*" in loopback.allowed_hosts
    assert transport_security_for("0.0.0.0").enable_dns_rebinding_protection is False


def test_the_bearer_gate_refuses_every_request_without_the_token():
    from aughor.mcp.server import BearerGate

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"served"})

    gate = BearerGate(inner, "t0k")

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gate), base_url="http://127.0.0.1:8765") as c:
            return (await c.post("/mcp"),
                    await c.post("/mcp", headers={"Authorization": "Bearer nope"}),
                    await c.post("/mcp", headers={"Authorization": "Basic dDBr"}),
                    await c.post("/mcp", headers={"Authorization": "Bearer t0k"}))

    none, wrong, basic, right = _run(go())
    assert none.status_code == wrong.status_code == basic.status_code == 401
    assert none.headers["www-authenticate"].startswith("Bearer") and "AUGHOR_MCP_TOKEN" in none.text
    assert right.status_code == 200 and right.text == "served"
    with pytest.raises(ValueError):
        BearerGate(inner, "")


def test_http_refuses_to_start_without_a_token(monkeypatch):
    import aughor.mcp.__main__ as entry

    monkeypatch.delenv("AUGHOR_MCP_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["aughor.mcp", "--http", "--no-automations", "--no-spotlight"])
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert "AUGHOR_MCP_TOKEN" in str(e.value.code)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _initialize(port: int, headers: dict) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "probe", "version": "0"}}}
    return httpx.post(f"http://127.0.0.1:{port}/mcp", json=body, timeout=10,
                      headers={"Accept": "application/json, text/event-stream", **headers})


def test_a_remote_client_is_served_with_the_token_and_refused_without(tmp_path: Path):
    """The pre-check, after. Before: a remote client got 421 on everything and a loopback client got a session for
    nothing. Now the host's `Host` header is accepted, and the token decides."""
    port = _free_port()
    env = {**os.environ, "AUGHOR_MCP_TOKEN": "t0k-live", "AUGHOR_API_URL": "http://127.0.0.1:1",
           "AUGHOR_SKIP_DOTENV": "1"}
    log = (tmp_path / "mcp.log").open("w")
    proc = subprocess.Popen([sys.executable, "-m", "aughor.mcp", "--http", "--host", "0.0.0.0", "--port", str(port),
                             "--no-automations", "--no-spotlight"], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 40
        while True:
            try:
                httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=1)
                break
            except httpx.HTTPError:
                if proc.poll() is not None:
                    pytest.fail("the server exited: " + (tmp_path / "mcp.log").read_text())
                if time.time() > deadline:
                    pytest.fail("the server did not come up: " + (tmp_path / "mcp.log").read_text())
                time.sleep(0.3)
        remote = {"Host": f"203.0.113.5:{port}"}
        assert _initialize(port, remote).status_code == 401, "a remote client without the token: refused, not 421"
        assert _initialize(port, {}).status_code == 401, "a loopback client without the token: refused too"
        served = _initialize(port, {**remote, "Authorization": "Bearer t0k-live"})
        assert served.status_code == 200 and '"serverInfo"' in served.text, served.text[:300]
    finally:
        proc.kill()
        proc.wait(timeout=10)
        log.close()
