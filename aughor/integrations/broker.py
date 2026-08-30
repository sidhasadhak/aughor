"""VA-11 — the OAuth broker: a module, not a service.

The decision this implements (ROADMAP §6.1): **Aughor owns the vault.** The dance is
therefore small and ours — authorize redirect out, callback in, token exchange,
refresh-before-expiry, revoke — with the tokens landing in our own encrypted store
and every call that leaves the platform going through ``govern.outbound.external_call``,
so token traffic is capped, spanned and session-logged like any other outbound call.

Security posture, stated rather than implied:

* ``state`` is 32 random url-safe bytes, stored server-side, and **single-use** —
  ``take_pending`` pops. A state that can complete twice is a token mint.
* PKCE (S256) whenever the provider accepts it. The verifier never leaves the store
  until the exchange, and never appears in any URL.
* The callback trusts NOTHING it is handed: the state must match a pending flow we
  began, or the code is discarded unexchanged.
* Refresh happens BEFORE expiry (skew below), at the moment of use — not on a timer.
  A timer that has not fired is a token that has expired; a check at use cannot be.
* ``invalid_grant`` on refresh is a VERDICT, not an error to retry: the grant is dead
  upstream, the connection becomes ``needs_reconnect``, and only the user consenting
  again revives it.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from aughor.integrations.models import Connection
from aughor.integrations.providers import Provider, get_provider
from aughor.integrations.store import (
    get_app_decrypted,
    get_connection_decrypted,
    put_pending,
    save_connection,
    take_pending,
)

logger = logging.getLogger("aughor.integrations")

#: Refresh when the access token has less life left than this. Two minutes clears any
#: clock skew between us and the provider and the latency of the call being fronted.
REFRESH_SKEW_SECONDS = 120


class BrokerError(Exception):
    """A refusal with a sentence a person can act on. Routes render ``str(exc)``."""


def _post(url: str, data: dict, headers: Optional[dict] = None) -> dict:
    """One form-encoded POST, JSON back. A seam on purpose: tests replace THIS, so
    the state/PKCE/refresh logic above it is exercised for real while nothing leaves
    the machine."""
    import httpx
    resp = httpx.post(url, data=data, headers=headers or {}, timeout=20.0)
    try:
        body = resp.json()
    except Exception:
        body = {"error": f"non-JSON response (HTTP {resp.status_code})"}
    if not isinstance(body, dict):
        body = {"error": "non-object response"}
    body["_status"] = resp.status_code
    return body


def _expires_at(expires_in: object) -> Optional[str]:
    try:
        seconds = int(expires_in)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _expired_within(conn: Connection, skew: int) -> bool:
    if not conn.expires_at:
        return False  # a token with no stated expiry is refreshed only on a 401, not on a guess
    try:
        dies = datetime.fromisoformat(conn.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True   # an unparseable expiry is treated as expired — the safe misread
    return dies - datetime.now(timezone.utc) <= timedelta(seconds=skew)


# ── begin ────────────────────────────────────────────────────────────────────────

def begin(provider_id: str, *, user_id: str, redirect_uri: str,
          scopes: str = "") -> str:
    """Start one authorization: persist the flow, return the URL to send the user to.

    ``redirect_uri`` is passed by the ROUTE from the request it is serving, because
    only the route knows which origin the platform is reachable on — localhost:8000
    on a laptop, the stable production origin deployed. (Vercel preview URLs are
    per-commit and providers pin redirect URIs; the callback must live on the
    production origin — ROADMAP §3.4 risk (c).)
    """
    provider = get_provider(provider_id)
    if provider is None:
        raise BrokerError(f"unknown provider: {provider_id}")
    app = get_app_decrypted(provider_id)
    if app is None or not app.client_id:
        raise BrokerError(
            f"{provider.name} is not set up — register the org's OAuth client first")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48) if provider.pkce else ""
    put_pending(state, provider=provider_id, user_id=user_id, verifier=verifier,
                redirect_uri=redirect_uri)

    params = {
        "client_id": app.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes or provider.default_scopes,
        "state": state,
        **provider.authorize_extra,
    }
    if provider.pkce:
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return f"{provider.authorize_url}?{urlencode(params)}"


# ── complete ─────────────────────────────────────────────────────────────────────

def complete(state: str, code: str) -> Connection:
    """The callback's half: state → pending flow (single use) → code → tokens → store.

    The redirect URI for the exchange comes off the PENDING flow, not the callback
    request: providers compare it byte-for-byte with the authorize request's, and a
    second derivation from proxy headers is a second chance to disagree.
    """
    pending = take_pending(state)
    if pending is None:
        raise BrokerError(
            "this authorization is unknown, already used, or expired — start again "
            "from the catalog")
    provider = get_provider(str(pending.get("provider", "")))
    if provider is None:  # a provider removed mid-flight; refuse rather than guess
        raise BrokerError("the provider for this authorization no longer exists")
    app = get_app_decrypted(provider.id)
    if app is None:
        raise BrokerError(f"{provider.name} is no longer set up")

    data = {
        "client_id": app.client_id,
        "client_secret": app.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": str(pending.get("redirect_uri", "")),
    }
    if pending.get("verifier"):
        data["code_verifier"] = str(pending["verifier"])

    from aughor.govern.outbound import external_call
    with external_call(provider.id, "oauth.token") as extra:
        body = _post(provider.token_url, data)
        extra["ok"] = "access_token" in body

    if "access_token" not in body:
        raise BrokerError(
            f"{provider.name} refused the exchange: "
            f"{body.get('error_description') or body.get('error') or 'no token returned'}")

    conn = Connection(
        provider=provider.id,
        user_id=str(pending.get("user_id", "")),
        # What was GRANTED, read back from the response. Slack's v2 nests under
        # authed_user/bot; the top-level `scope` covers the common case and "" is the
        # honest value when a provider says nothing.
        scopes=str(body.get("scope", "") or ""),
        account=_account_label(provider, body),
        access_token=str(body.get("access_token", "")),
        refresh_token=str(body.get("refresh_token", "") or ""),
        token_type=str(body.get("token_type", "Bearer") or "Bearer"),
        expires_at=_expires_at(body.get("expires_in")),
        status="active",
    )
    saved = save_connection(conn)
    _audit("integration.connect", saved)
    return saved


def _account_label(provider: Provider, body: dict) -> str:
    """The provider's own name for the account, where the token response carries one."""
    team = body.get("team")
    if isinstance(team, dict) and team.get("name"):
        return str(team["name"])                    # Slack: workspace name
    for key in ("email", "user_id", "bot_user_id"):
        if body.get(key):
            return str(body[key])
    return ""


# ── use ──────────────────────────────────────────────────────────────────────────

def fresh_access_token(conn_id: str) -> str:
    """The token a caller may present RIGHT NOW — refreshed first if it is dying.

    The only path that hands out a plaintext access token, so refresh policy cannot
    be forgotten by one caller and remembered by another.
    """
    conn = get_connection_decrypted(conn_id)
    if conn is None:
        raise BrokerError("unknown connection")
    if conn.status == "revoked":
        raise BrokerError("this connection was revoked")
    if conn.status == "needs_reconnect":
        raise BrokerError(
            "this connection needs the user to reconnect — the provider refused its refresh")
    if _expired_within(conn, REFRESH_SKEW_SECONDS):
        conn = _refresh(conn)
    return conn.access_token


def _refresh(conn: Connection) -> Connection:
    provider = get_provider(conn.provider)
    app = get_app_decrypted(conn.provider)
    if provider is None or app is None:
        raise BrokerError(f"{conn.provider} is no longer set up")
    if not conn.refresh_token:
        # No refresh token was ever granted (Google without `access_type=offline`, or a
        # provider that does not issue them). Dead on expiry, and said so.
        save_connection(conn.model_copy(update={"status": "needs_reconnect"}))
        raise BrokerError(
            f"the {provider.name} grant carries no refresh token — reconnect to renew it")

    from aughor.govern.outbound import external_call
    with external_call(provider.id, "oauth.refresh") as extra:
        body = _post(provider.token_url, {
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": conn.refresh_token,
        })
        extra["ok"] = "access_token" in body

    if "access_token" not in body:
        if body.get("error") == "invalid_grant":
            save_connection(conn.model_copy(update={"status": "needs_reconnect"}))
            raise BrokerError(
                f"{provider.name} revoked this grant upstream — the user must reconnect")
        raise BrokerError(
            f"{provider.name} refresh failed: "
            f"{body.get('error_description') or body.get('error') or 'no token returned'}")

    return save_connection(conn.model_copy(update={
        "access_token": str(body["access_token"]),
        # A provider MAY rotate the refresh token; keep the old one when it does not.
        "refresh_token": str(body.get("refresh_token") or conn.refresh_token),
        "expires_at": _expires_at(body.get("expires_in")) or conn.expires_at,
        "status": "active",
    }))


# ── revoke ───────────────────────────────────────────────────────────────────────

def revoke(conn_id: str) -> Connection:
    """Revoke at the provider where an endpoint exists, then clear our copy.

    Returns the connection with ``status="revoked"`` and tokens CLEARED — the row
    itself stays, because "who held access, until when" is the audit answer this
    record exists to give. When the provider has no revocation endpoint (Microsoft),
    the route discloses that the grant must also be removed on the account's own
    security page; pretending otherwise would be a revoke that only we believe.
    """
    conn = get_connection_decrypted(conn_id)
    if conn is None:
        raise BrokerError("unknown connection")
    provider = get_provider(conn.provider)

    if provider and provider.revoke_url and conn.access_token:
        from aughor.govern.outbound import external_call
        try:
            with external_call(provider.id, "oauth.revoke") as extra:
                body = _post(provider.revoke_url, {"token": conn.access_token})
                extra["ok"] = body.get("_status", 500) < 400
        except Exception as exc:  # the provider being down must not block OUR revoke
            logger.warning("provider-side revoke failed for %s: %s", conn_id, exc)

    cleared = save_connection(conn.model_copy(update={
        "access_token": "", "refresh_token": "", "status": "revoked"}))
    _audit("integration.revoke", cleared)
    return cleared


def _audit(action: str, conn: Connection) -> None:
    """A governed decision, attributed — best-effort, never the reason a flow fails."""
    try:
        from aughor.govern.actions import audit
        audit(action, scope=conn.provider, decision="executed",
              actor=conn.user_id, detail=f"connection {conn.id}")
    except Exception:  # pragma: no cover - telemetry must not break the dance
        logger.debug("integration audit skipped", exc_info=True)
