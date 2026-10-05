"""OAuth-authenticated MCP servers — the code half (the 2027 study §Q "the ecosystem"; the close-out, C9).

The consumer could reach a foreign server with one opaque `Authorization` value an operator pasted in. A server
that authenticates by OAuth — the shape the MCP specification standardises — needs a client that discovers the
authorization server, registers or presents a client, runs PKCE, sends a person to sign in and comes back with a
token set it refreshes. The MCP SDK ships exactly that client as an `httpx.Auth` (`mcp.client.auth`), and
`streamablehttp_client` takes it as `auth=`; this module supplies the two things the SDK leaves to the host:

- **where the tokens live** — `ServerTokenStorage`, the SDK's `TokenStorage` protocol over the server row: the token
  set and the client registration are written on the row and encrypted at rest by the store like every other secret
  field; a read says only whether a person has signed in (`McpServer.to_safe_dict`).
- **how a person signs in** — the SDK's authorization-code flow calls a `redirect_handler` with the URL to open and
  then awaits a `callback_handler` for the code the browser brings back. `begin` runs one connection attempt on a
  thread whose handlers park on that exchange: the redirect handler records the URL and returns it to the person,
  the callback handler waits (bounded) for `complete`, which the callback door calls when the browser lands on
  `/mcp-servers/oauth/callback?code&state`. Then the SDK exchanges the code, stores the tokens, and the session
  initialises; later calls through `session.open_session` carry the Bearer and refresh it silently.

What is deliberately said rather than hidden: a server in an OAuth mode with no token set does not hang or guess —
every ordinary open raises `McpSignInRequired`, naming the door; a sign-in waiter lives in THIS process and expires
(`SIGNIN_TIMEOUT_S`), so a deployment with several API workers routes the callback to the worker that began the
sign-in or the callback finds no waiter and says so (the integrations broker's SQLite pending store is the shape for
that, left for a deployment that needs it); and the live sign-in against a real authorization server is the
install's to run — nothing here is tested against one.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qs, urlparse

from aughor.mcpservers import store
from aughor.mcpservers.models import McpServer
from aughor.mcpservers.session import McpUnreachable
from aughor.util.time import now_iso_z

logger = logging.getLogger(__name__)

#: How long a person has to finish signing in once the URL is handed to them.
SIGNIN_TIMEOUT_S = 600.0
#: How long `begin` waits for the server to produce the sign-in URL (discovery and registration happen first).
URL_TIMEOUT_S = 30.0
#: The browser's way back. Exempt from the API key in `api._AUTH_EXEMPT`: the redirect carries no key, and the
#: route verifies the unguessable `state` the SDK minted instead.
CALLBACK_PATH = "/mcp-servers/oauth/callback"
#: The ledger kind a sign-in and a sign-out are journaled as (`kernel/events.CATALOGUE`).
EVENT_KIND = "mcp.oauth"


class McpSignInRequired(McpUnreachable):
    """The server authenticates by OAuth and no person has signed in yet — a verdict with a door in it."""


# ── where the tokens live ─────────────────────────────────────────────────────────────────────

class ServerTokenStorage:
    """The SDK's `TokenStorage` protocol over the server row. Every read is fresh from the store — the SDK
    refreshes tokens inside a call and writes them back here, and a stale in-memory copy would hand the next
    call the token the refresh just retired."""

    def __init__(self, server_id: str):
        self.server_id = str(server_id)

    def _server(self) -> Optional[McpServer]:
        return store.get_server(self.server_id)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        s = self._server()
        if s is None or not s.oauth_tokens:
            return None
        try:
            return OAuthToken.model_validate_json(s.oauth_tokens)
        except Exception as exc:  # noqa: BLE001 — an unreadable token set is "not signed in", said in the log
            logger.warning("mcp server %s: stored token set unreadable (%s); treating as signed out", self.server_id, exc)
            return None

    async def set_tokens(self, tokens) -> None:
        s = self._server()
        if s is None:
            return
        s.oauth_tokens = tokens.model_dump_json(exclude_none=True)
        s.oauth_token_obtained_at = now_iso_z()
        store.save_server(s)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        s = self._server()
        if s is None:
            return None
        if s.oauth_client_info:
            try:
                return OAuthClientInformationFull.model_validate_json(s.oauth_client_info)
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp server %s: stored client registration unreadable (%s)", self.server_id, exc)
        if s.oauth_client_id:
            # A client the operator registered by hand: presented as the registration, so the SDK skips
            # dynamic registration and never asks the server for a client it already has.
            return OAuthClientInformationFull(client_id=s.oauth_client_id, client_secret=s.oauth_client_secret or None,
                                              redirect_uris=None, grant_types=["authorization_code", "refresh_token"],
                                              response_types=["code"], scope=s.oauth_scopes or None,
                                              token_endpoint_auth_method=(s.oauth_token_endpoint_auth if s.oauth_client_secret else "none"))
        return None

    async def set_client_info(self, info) -> None:
        s = self._server()
        if s is None:
            return
        s.oauth_client_info = info.model_dump_json(exclude_none=True)
        store.save_server(s)


# ── the provider the transport is handed ─────────────────────────────────────────────────────

Handlers = tuple[Callable[[str], Awaitable[None]], Callable[[], Awaitable[tuple[str, Optional[str]]]]]


def _refusing_handlers(server: McpServer) -> Handlers:
    """The handlers an ORDINARY open carries: a server that needs a person to sign in says so and names the
    door, rather than hanging a worker on a browser nobody opened."""
    why = (f"'{server.name or server.id}' authenticates by OAuth and no person has signed in yet — "
           f"POST /mcp-servers/{server.id}/oauth/begin and open the URL it returns")

    async def redirect(_url: str) -> None:
        raise McpSignInRequired(why)

    async def callback() -> tuple[str, Optional[str]]:
        raise McpSignInRequired(why)

    return redirect, callback


def auth_for(server: McpServer, *, redirect_uri: str = "", handlers: Optional[Handlers] = None):
    """The `httpx.Auth` the transport is handed for this server, or None for the header posture."""
    if server.transport != "http" or server.auth_mode == "header":
        return None
    storage = ServerTokenStorage(server.id)
    if server.auth_mode == "oauth_client_credentials":
        from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
        return ClientCredentialsOAuthProvider(server_url=server.url, storage=storage, client_id=server.oauth_client_id,
                                              client_secret=server.oauth_client_secret,
                                              token_endpoint_auth_method=server.oauth_token_endpoint_auth,
                                              scopes=server.oauth_scopes or None)
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata
    redirect_handler, callback_handler = handlers or _refusing_handlers(server)
    metadata = OAuthClientMetadata(
        redirect_uris=[redirect_uri or "http://localhost:8000" + CALLBACK_PATH],
        grant_types=["authorization_code", "refresh_token"], response_types=["code"],
        scope=server.oauth_scopes or None, client_name="Aughor",
        token_endpoint_auth_method=server.oauth_token_endpoint_auth if server.oauth_client_secret else "none")
    return OAuthClientProvider(server_url=server.url, client_metadata=metadata, storage=storage,
                               redirect_handler=redirect_handler, callback_handler=callback_handler,
                               timeout=SIGNIN_TIMEOUT_S)


# ── the sign-in: begin on a thread, complete from the callback ───────────────────────────────

@dataclass
class _Waiter:
    server_id: str
    started_at: float = field(default_factory=time.time)
    authorization_url: str = ""
    state: str = ""
    code: str = ""
    error: str = ""
    url_ready: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    ended: threading.Event = field(default_factory=threading.Event)


_WAITERS: dict[str, _Waiter] = {}
_LOCK = threading.Lock()


def _signin_flow(server: McpServer, provider, timeout_s: float) -> None:
    """One connection attempt with the interactive provider: the first request's 401 starts the SDK's flow —
    discovery, registration, PKCE, the browser through the handlers, the token exchange — and an initialised
    session means the token set is stored. Factored out so the suite can stand a flow in for a live server."""
    from aughor.mcpservers.session import open_session, run_blocking

    async def _go():
        async with open_session(server, timeout_s, auth=provider):
            return True

    run_blocking(_go, timeout_s)


def begin(server: McpServer, *, redirect_uri: str, timeout_s: float = SIGNIN_TIMEOUT_S) -> dict[str, Any]:
    """Start a person's sign-in to this server: returns the URL to open and the `state` the callback will carry."""
    if server.auth_mode != "oauth_authorization_code":
        raise ValueError(f"'{server.name or server.id}' does not sign in by authorization code (auth_mode={server.auth_mode!r})")
    w = _Waiter(server_id=server.id)

    async def redirect_handler(url: str) -> None:
        w.authorization_url = url
        w.state = (parse_qs(urlparse(url).query).get("state") or [""])[0]
        with _LOCK:
            _sweep()
            if w.state:
                _WAITERS[w.state] = w
        w.url_ready.set()

    async def callback_handler() -> tuple[str, Optional[str]]:
        # Polled, not parked on an executor thread: a blocking wait handed to the default executor
        # would hold the interpreter's exit for the whole sign-in window (its workers are joined at
        # exit), and a sleep loop is cancellable by the transport's own timeout.
        deadline = time.time() + timeout_s
        while not w.done.is_set():
            if time.time() > deadline:
                raise McpUnreachable(f"the sign-in was not completed within {timeout_s:.0f}s")
            await asyncio.sleep(0.25)
        if w.error:
            raise McpUnreachable(f"the authorization server refused: {w.error}")
        return w.code, w.state

    provider = auth_for(server, redirect_uri=redirect_uri, handlers=(redirect_handler, callback_handler))

    def _target() -> None:
        try:
            _signin_flow(server, provider, timeout_s)
        except Exception as exc:  # noqa: BLE001 — the person reads the reason from `complete` or `begin`
            w.error = w.error or f"{type(exc).__name__}: {exc}"
        finally:
            with _LOCK:
                if w.state and _WAITERS.get(w.state) is w:
                    _WAITERS.pop(w.state, None)
            w.url_ready.set()
            w.ended.set()

    threading.Thread(target=_target, name=f"mcp-oauth-{server.id}", daemon=True).start()
    w.url_ready.wait(timeout=URL_TIMEOUT_S)
    if not w.authorization_url:
        raise McpUnreachable(w.error or f"the server offered no sign-in within {URL_TIMEOUT_S:.0f}s")
    return {"server_id": server.id, "authorization_url": w.authorization_url, "state": w.state,
            "expires_in": int(timeout_s), "callback": redirect_uri,
            "note": "open the URL and sign in; the browser's return to the callback completes it"}


def complete(state: str, code: str, *, error: str = "") -> dict[str, Any]:
    """The callback door's half: hand the code to the waiting sign-in and report whether a token set was stored."""
    with _LOCK:
        w = _WAITERS.pop(str(state or ""), None)
    if w is None:
        raise LookupError("no sign-in is waiting for this state — it expired, was already used, or began in another process")
    w.code = str(code or "")
    w.error = str(error or "")
    w.done.set()
    w.ended.wait(timeout=URL_TIMEOUT_S + 30)
    server = store.get_server(w.server_id)
    signed_in = bool(server and server.signed_in)
    _journal(w.server_id, "signed_in" if signed_in else "sign_in_failed", by="", detail=w.error)
    return {"server_id": w.server_id, "signed_in": signed_in, "error": w.error}


def sign_out(server: McpServer, *, by: str = "") -> McpServer:
    """Forget the token set (the registration stays — it is the client, not the person)."""
    server.oauth_tokens = ""
    server.oauth_token_obtained_at = ""
    saved = store.save_server(server)
    _journal(server.id, "signed_out", by=by)
    return saved


def status(server: McpServer) -> dict[str, Any]:
    """What a read may say of a server's OAuth state: the mode, whether a person signed in and when, and when
    the access token lapses — never the token."""
    out: dict[str, Any] = {**server.to_safe_dict()["oauth"], "expires_at": ""}
    if server.signed_in:
        try:
            from mcp.shared.auth import OAuthToken
            tok = OAuthToken.model_validate_json(server.oauth_tokens)
            out["refreshable"] = bool(tok.refresh_token)
            if tok.expires_in and server.oauth_token_obtained_at:
                from datetime import datetime, timedelta
                got = datetime.fromisoformat(server.oauth_token_obtained_at.replace("Z", "+00:00"))
                out["expires_at"] = (got + timedelta(seconds=int(tok.expires_in))).isoformat(timespec="seconds")
        except Exception:  # noqa: BLE001 — a token set that cannot be read is said as signed in and nothing more
            out["note"] = "the stored token set could not be read"
    with _LOCK:
        out["sign_in_pending"] = any(w.server_id == server.id for w in _WAITERS.values())
    return out


def _sweep() -> None:
    """Drop waiters past their time — under `_LOCK`."""
    now = time.time()
    for state in [s for s, w in _WAITERS.items() if now - w.started_at > SIGNIN_TIMEOUT_S + URL_TIMEOUT_S]:
        _WAITERS.pop(state, None)


def _journal(server_id: str, action: str, *, by: str, detail: str = "") -> None:
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(EVENT_KIND, {"server_id": server_id, "action": action, "by": by, "detail": detail[:200]})
    except Exception:  # noqa: BLE001 — the row is the authority; the event is the trail
        logger.debug("mcp oauth journal emit failed", exc_info=True)
