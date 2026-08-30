"""VA-11 — the integrations API: catalog, app set-up, connect, callback, revoke.

The shape the user's reference screenshots describe: a catalog where a provider with
no org app registered shows **Set up**, and a registered one shows **Connect**. Both
verbs are here; the tokens never are — list responses DROP token fields rather than
mask them (``Connection.to_safe_dict``), and the app secret comes back masked.

The callback returns a small self-contained HTML page rather than redirecting into
the web app: the API's origin is the one the provider was told about, the web app's
origin differs per install, and a redirect guessed wrong turns a finished consent
into a 404 — the page says what happened and hands the person back.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from aughor.integrations import broker, store
from aughor.integrations.models import ProviderApp
from aughor.integrations.providers import PROVIDERS, get_provider

logger = logging.getLogger("aughor.integrations")

router = APIRouter(tags=["integrations"])


def _user() -> str:
    from aughor.org.context import current_user_id
    return current_user_id() or ""


def _callback_uri(request: Request) -> str:
    """The redirect URI as THIS deployment is reachable — honouring the proxy headers
    a fronted deployment arrives behind, because the provider will compare it
    byte-for-byte with what the org registered."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{proto}://{host}/oauth/callback"


# ── catalog ──────────────────────────────────────────────────────────────────────

@router.get("/integrations/catalog")
def catalog(request: Request):
    """Every provider, with the two flags the two buttons need."""
    mine = {c.provider: c for c in store.list_connections(_user())}
    out = []
    for p in PROVIDERS.values():
        app = store.get_app(p.id)
        conn = mine.get(p.id)
        out.append({
            "id": p.id, "name": p.name, "category": p.category, "blurb": p.blurb,
            "configured": bool(app and app.client_id),
            "console_url": p.console_url,
            # So the Set-up form can say that THIS redirect URI will not be accepted,
            # rather than showing a string the provider rejects on the next click.
            "https_only": p.https_only,
            "connection": conn.to_safe_dict() if conn else None,
        })
    return {"providers": out, "redirect_uri": _callback_uri(request)}


# ── org app registration (Set up) ────────────────────────────────────────────────

class AppBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""


@router.put("/integrations/{provider_id}/app")
def put_app(provider_id: str, body: AppBody, request: Request):
    provider = get_provider(provider_id)
    if provider is None:
        raise HTTPException(404, f"unknown provider: {provider_id}")
    if not body.client_id.strip() or not body.client_secret.strip():
        raise HTTPException(422, "client_id and client_secret are both required")
    app = store.save_app(ProviderApp(
        id=provider_id, client_id=body.client_id.strip(),
        client_secret=body.client_secret.strip()))
    # The redirect URI rides back with the save because it is the NEXT thing the person
    # needs — it must be pasted into the provider console they just came from.
    return {"app": app.to_safe_dict(), "redirect_uri": _callback_uri(request)}


# ── connect / callback ───────────────────────────────────────────────────────────

@router.post("/integrations/{provider_id}/connect")
def connect(provider_id: str, request: Request):
    """Begin the dance; the client sends the browser to `authorize_url`."""
    try:
        url = broker.begin(provider_id, user_id=_user(),
                           redirect_uri=_callback_uri(request))
    except broker.BrokerError as exc:
        raise HTTPException(422, str(exc))
    return {"authorize_url": url}


def _page(title: str, detail: str) -> HTMLResponse:
    # Deliberately dependency-free: this renders on the API origin with no app shell.
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>{title}</title>"
        f"<body style='font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0'>"
        f"<div style='max-width:28rem;text-align:center'><h1 style='font-size:1.2rem'>{title}</h1>"
        f"<p style='color:#555'>{detail}</p></div></body>")


@router.get("/oauth/callback")
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    """Where the provider sends the person back. HTML on purpose — see module doc."""
    if error:
        # `access_denied` is the person declining. Their choice is reported as a
        # choice, and the pending flow dies with its TTL — nothing to clean here.
        return _page("Not connected",
                     "Consent was declined — nothing was stored. You can close this "
                     "tab and return to Aughor.")
    if not state or not code:
        return _page("Not connected", "The provider returned no authorization.")
    try:
        conn = broker.complete(state, code)
    except broker.BrokerError as exc:
        return _page("Not connected", str(exc))
    return _page("Connected",
                 f"{conn.provider} is connected{f' as {conn.account}' if conn.account else ''}. "
                 "You can close this tab and return to Aughor.")


# ── my connections ───────────────────────────────────────────────────────────────

@router.get("/integrations/connections")
def my_connections():
    return {"connections": [c.to_safe_dict() for c in store.list_connections(_user())]}


@router.post("/integrations/connections/{conn_id}/revoke")
def revoke(conn_id: str):
    conn = store.get_connection(conn_id)
    if conn is None or conn.user_id != _user():
        # 404 for someone else's connection, not 403 — a 403 confirms it exists.
        raise HTTPException(404, "unknown connection")
    try:
        cleared = broker.revoke(conn_id)
    except broker.BrokerError as exc:
        raise HTTPException(422, str(exc))
    provider = get_provider(cleared.provider)
    return {
        "connection": cleared.to_safe_dict(),
        # Microsoft has no revocation endpoint: the person must also remove the grant on
        # the account's own security page, and hiding that would be a revoke only we
        # believe. Named per provider, from the registry, never hardcoded.
        "provider_side": bool(provider and provider.revoke_url),
    }
