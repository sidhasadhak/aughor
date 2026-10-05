"""The 2027 study's close-out, C9 — OAuth-authenticated MCP servers, the code half (`aughor/mcpservers/oauth.py`).

What these hold: the two OAuth modes are rows a person writes down with the model's own rules (http only; client
credentials need a client); the token set lives on the row, encrypted at rest and never returned; the transport is
handed the SDK's provider for an OAuth server and nothing for the header posture; an ordinary open of a server
nobody signed in to says so and names the door rather than hanging; a sign-in begins on a thread that parks on the
browser's return, the callback completes it, the token set is stored and journaled, and a state nobody is waiting
for is refused; a sign-out forgets the token set; the API exempts the callback from the key. The live sign-in against
a real authorization server is the install's — nothing here talks to one.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.mcpservers import oauth as O
from aughor.mcpservers import store
from aughor.mcpservers.models import SERVER_SECRET_FIELDS, McpServer


def _release_waiters():
    """End every sign-in a test left waiting, so its thread returns instead of outliving the test."""
    for w in list(O._WAITERS.values()):
        w.error = w.error or "test teardown"
        w.done.set()
    O._WAITERS.clear()


@pytest.fixture(autouse=True)
def _clean_allowlist():
    for s in store.list_servers():
        store.delete_server(s.id)
    _release_waiters()
    yield
    for s in store.list_servers():
        store.delete_server(s.id)
    _release_waiters()


def _server(**over) -> McpServer:
    fields = {"name": "Ledger", "transport": "http", "url": "https://mcp.example.com/mcp", "auth_mode": "oauth_authorization_code"}
    fields.update(over)
    return store.save_server(McpServer(**fields))


# ── the row ────────────────────────────────────────────────────────────────────────────────

def test_the_modes_follow_the_models_rules_and_a_read_never_carries_a_secret():
    with pytest.raises(ValueError, match="http server"):
        McpServer(name="x", transport="stdio", command="npx", auth_mode="oauth_authorization_code")
    with pytest.raises(ValueError, match="client credentials need"):
        McpServer(name="x", transport="http", url="https://a/mcp", auth_mode="oauth_client_credentials")
    s = _server(auth_mode="oauth_client_credentials", oauth_client_id="cid", oauth_client_secret="shh", oauth_scopes="read")
    safe = s.to_safe_dict()
    assert not (set(safe) & set(SERVER_SECRET_FIELDS))
    assert safe["oauth"] == {"mode": "oauth_client_credentials", "signed_in": False, "client_id": "cid", "scopes": "read",
                             "obtained_at": "", "has_client_secret": True}
    assert "shh" not in json.dumps(store._SERVERS.all())          # encrypted at rest (the rows as persisted)
    assert store.get_server(s.id).oauth_client_secret == "shh"   # and readable through the store


def test_the_token_set_lives_on_the_row_encrypted_and_a_read_says_only_that_a_person_signed_in():
    from mcp.shared.auth import OAuthToken
    s = _server()
    storage = O.ServerTokenStorage(s.id)
    assert asyncio.run(storage.get_tokens()) is None and not O.status(s)["signed_in"]
    asyncio.run(storage.set_tokens(OAuthToken(access_token="tok-secret", token_type="Bearer", expires_in=3600, refresh_token="r1")))
    raw = json.dumps(store._SERVERS.all())
    assert "tok-secret" not in raw and "r1" not in raw
    again = store.get_server(s.id)
    assert again.signed_in and json.loads(again.oauth_tokens)["access_token"] == "tok-secret"
    got = asyncio.run(storage.get_tokens())
    assert got.access_token == "tok-secret" and got.refresh_token == "r1"
    st = O.status(again)
    assert st["signed_in"] and st["refreshable"] and st["expires_at"] and st["obtained_at"]
    assert "tok-secret" not in json.dumps(again.to_safe_dict()) and "tok-secret" not in json.dumps(st)
    # a hand-registered client is presented as the registration, so the SDK never re-registers
    s2 = _server(oauth_client_id="cid-2", oauth_client_secret="s2")
    info = asyncio.run(O.ServerTokenStorage(s2.id).get_client_info())
    assert info.client_id == "cid-2" and info.client_secret == "s2" and info.token_endpoint_auth_method == "client_secret_basic"
    # a sign-out forgets the token set and keeps the row
    out = O.sign_out(store.get_server(s.id), by="user:ana")
    assert not out.signed_in and store.get_server(s.id) is not None and not O.status(out)["signed_in"]


# ── what the transport is handed ───────────────────────────────────────────────────────────

def test_the_transport_is_handed_the_sdks_provider_for_an_oauth_server_and_nothing_for_a_header():
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
    header = _server(auth_mode="header", auth_header="Bearer pasted")
    assert O.auth_for(header) is None
    cc = _server(auth_mode="oauth_client_credentials", oauth_client_id="cid", oauth_client_secret="shh")
    assert isinstance(O.auth_for(cc), ClientCredentialsOAuthProvider)
    code = _server()
    provider = O.auth_for(code, redirect_uri="https://aughor.example/mcp-servers/oauth/callback")
    assert isinstance(provider, OAuthClientProvider)
    assert str(provider.context.client_metadata.redirect_uris[0]) == "https://aughor.example/mcp-servers/oauth/callback"
    # an ordinary open of a server nobody signed in to says so and names the door — it never hangs on a browser
    with pytest.raises(O.McpSignInRequired, match=f"POST /mcp-servers/{code.id}/oauth/begin"):
        asyncio.run(provider.context.redirect_handler("https://as.example/authorize?state=x"))


# ── the sign-in: begin, the browser's return, complete ────────────────────────────────────

def _fake_flow(code_to_token=lambda code: f"tok-{code}"):
    """Stands in for the SDK's flow on a live server: hands the handlers a URL, waits for the browser's return,
    then stores the token set the way the SDK would."""
    def flow(server, provider, timeout_s):
        from mcp.shared.auth import OAuthToken

        async def go():
            await provider.context.redirect_handler("https://as.example/authorize?client_id=c&state=S1&code_challenge=x")
            code, state = await provider.context.callback_handler()
            assert state == "S1"
            await provider.context.storage.set_tokens(OAuthToken(access_token=code_to_token(code), token_type="Bearer", expires_in=600))
        asyncio.run(go())
    return flow


def test_a_sign_in_begins_on_a_thread_and_the_callback_completes_it(monkeypatch):
    monkeypatch.setattr(O, "_signin_flow", _fake_flow())
    from aughor.kernel.ledger import Ledger
    s = _server()
    begun = O.begin(s, redirect_uri="https://aughor.example/mcp-servers/oauth/callback", timeout_s=20)
    assert begun["authorization_url"].startswith("https://as.example/authorize") and begun["state"] == "S1"
    assert O.status(store.get_server(s.id))["sign_in_pending"]
    with pytest.raises(LookupError, match="no sign-in is waiting"):
        O.complete("not-a-state", "abc")
    done = O.complete("S1", "abc")
    assert done == {"server_id": s.id, "signed_in": True, "error": ""}
    after = store.get_server(s.id)
    assert after.signed_in and json.loads(after.oauth_tokens)["access_token"] == "tok-abc"
    assert "tok-abc" not in json.dumps(store._SERVERS.all())
    assert not O.status(after)["sign_in_pending"]
    with pytest.raises(LookupError):
        O.complete("S1", "abc")                               # single use

    def _payload(e):
        p = e.get("payload")
        return json.loads(p) if isinstance(p, str) else (p or {})
    mine = [_payload(e) for e in Ledger.default().events(kind=O.EVENT_KIND) if _payload(e).get("server_id") == s.id]
    assert mine and mine[0]["action"] == "signed_in"            # newest first
    # a server that does not sign in by authorization code is refused with why
    cc = _server(auth_mode="oauth_client_credentials", oauth_client_id="cid", oauth_client_secret="shh")
    with pytest.raises(ValueError, match="does not sign in by authorization code"):
        O.begin(cc, redirect_uri="https://aughor.example/mcp-servers/oauth/callback")


def test_the_authorization_servers_refusal_reaches_the_person(monkeypatch):
    monkeypatch.setattr(O, "_signin_flow", _fake_flow())
    s = _server()
    O.begin(s, redirect_uri="https://aughor.example/mcp-servers/oauth/callback", timeout_s=20)
    done = O.complete("S1", "", error="access_denied")
    assert done["signed_in"] is False and "access_denied" in done["error"]
    assert not store.get_server(s.id).signed_in


# ── the doors ──────────────────────────────────────────────────────────────────────────────

def test_the_doors_begin_complete_and_sign_out_and_the_callback_needs_no_key(monkeypatch):
    monkeypatch.setattr(O, "_signin_flow", _fake_flow())
    from aughor.api import _AUTH_EXEMPT
    from aughor.routers.mcpservers import router
    assert any(O.CALLBACK_PATH.startswith(p) for p in _AUTH_EXEMPT)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    created = client.post("/mcp-servers", json={"name": "Ledger", "transport": "http", "url": "https://mcp.example.com/mcp",
                                                "auth_mode": "oauth_authorization_code", "oauth_scopes": "read"}).json()
    assert created["oauth"] == {"mode": "oauth_authorization_code", "signed_in": False, "client_id": "", "scopes": "read",
                                "obtained_at": "", "has_client_secret": False, "expires_at": "", "sign_in_pending": False}
    sid = created["id"]
    begun = client.post(f"/mcp-servers/{sid}/oauth/begin", headers={"x-forwarded-proto": "https", "x-forwarded-host": "aughor.example"})
    assert begun.status_code == 200, begun.text
    assert begun.json()["callback"] == "https://aughor.example/mcp-servers/oauth/callback"
    assert client.get("/mcp-servers/oauth/callback?state=nope&code=x").status_code == 404
    landed = client.get("/mcp-servers/oauth/callback?state=S1&code=zzz")
    assert landed.status_code == 200 and "Signed in" in landed.text
    view = client.get("/mcp-servers").json()["servers"][0]
    assert view["oauth"]["signed_in"] and "oauth_tokens" not in view and "tok-zzz" not in json.dumps(view)
    # an update that keeps the client keeps the sign-in; one that changes the mode drops it
    kept = client.put(f"/mcp-servers/{sid}", json={"name": "Ledger renamed", "transport": "http", "url": "https://mcp.example.com/mcp",
                                                   "auth_mode": "oauth_authorization_code", "oauth_scopes": "read"}).json()
    assert kept["oauth"]["signed_in"] and kept["name"] == "Ledger renamed"
    out = client.post(f"/mcp-servers/{sid}/oauth/sign-out").json()
    assert out["oauth"]["signed_in"] is False
    assert client.post(f"/mcp-servers/{sid}/oauth/begin").status_code == 200   # signs in again
    assert client.get("/mcp-servers/oauth/callback?state=S1&code=again").status_code == 200
    assert client.get("/mcp-servers").json()["servers"][0]["oauth"]["signed_in"]
    moved = client.put(f"/mcp-servers/{sid}", json={"name": "Ledger", "transport": "http", "url": "https://mcp.example.com/mcp",
                                                    "auth_mode": "header", "auth_header": "Bearer pasted"}).json()
    assert moved["oauth"]["mode"] == "header" and moved["oauth"]["signed_in"] is False and moved["has_auth"] is True
