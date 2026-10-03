"""Aughor talks to Slack's app-management API itself (Arc AO-2d).

Measured 2026-10-03 (docs/AGENT_OPS_STUDY_2026-10-03.md §8): giving an agent a Slack door
took twenty manual steps across four surfaces and five hand-copied secrets — the manifest
pasted at api.slack.com, the app installed by hand, three tokens copied back. Slack's
``apps.manifest.create`` lets a CONFIGURATION TOKEN (one paste, from
api.slack.com/apps → "Your App Configuration Tokens") create the app from the manifest
Aughor already renders, and hands back the signing secret and an OAuth client — so the
install can be a button on an HTTPS deployment (``oauth.v2.access`` returns the bot
token). What Slack offers no API for is the app-level token (``xapp-``, Socket Mode), so
that one paste remains, and this module's callers say so instead of pretending.

Like ``verify.py``: urllib, one job per function, never raises — a network failure is a
failure to REACH Slack, reported as such, not dressed as Slack's answer.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_API = "https://slack.com/api"
_TIMEOUT_S = 20


def _post(method: str, *, bearer: str = "", form: dict | None = None,
          body: dict | None = None) -> tuple[bool, dict]:
    """One Slack Web API call. ``(ok, payload)``; a transport failure is
    ``(False, {"error": "unreachable: …"})``."""
    url = f"{_API}/{method}"
    headers = {"accept": "application/json"}
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json; charset=utf-8"
    else:
        data = urllib.parse.urlencode(form or {}).encode("utf-8")
        headers["content-type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("slack %s unreachable: %s", method, exc)
        return False, {"error": f"unreachable: {exc}"}
    if not isinstance(payload, dict):
        return False, {"error": "malformed response"}
    return bool(payload.get("ok")), payload


def create_app(config_token: str, manifest: dict) -> tuple[bool, dict]:
    """``apps.manifest.create``. On success the payload carries ``app_id``,
    ``credentials`` (client_id, client_secret, verification_token, signing_secret) and
    ``oauth_authorize_url``. The configuration token is used once and never stored."""
    if not (config_token or "").strip():
        return False, {"error": "no configuration token"}
    ok, payload = _post("apps.manifest.create", bearer=config_token.strip(),
                        body={"manifest": manifest})
    if not ok:
        # Slack's own words, plus the manifest validator's detail when it gave one — the
        # one thing a person can act on when a manifest is refused.
        errs = payload.get("errors") or []
        if errs:
            payload["error"] = f"{payload.get('error', 'invalid_manifest')}: " + "; ".join(
                str(e.get("message") or e) for e in errs[:5])
    return ok, payload


def update_app(config_token: str, app_id: str, manifest: dict) -> tuple[bool, dict]:
    """``apps.manifest.update`` — the manifest re-rendered after a change (a rename, agent
    mode turned on). Scope changes still need a reinstall, which Slack reports as
    ``permissions_updated``."""
    if not (config_token or "").strip() or not app_id:
        return False, {"error": "no configuration token or app id"}
    return _post("apps.manifest.update", bearer=config_token.strip(),
                 body={"app_id": app_id, "manifest": manifest})


def install_url(client_id: str, scopes: list[str], redirect_uri: str, state: str) -> str:
    """Slack's OAuth v2 authorize URL for installing the app to a workspace."""
    q = urllib.parse.urlencode({
        "client_id": client_id, "scope": ",".join(scopes),
        "redirect_uri": redirect_uri, "state": state,
    })
    return f"https://slack.com/oauth/v2/authorize?{q}"


def exchange_code(client_id: str, client_secret: str, code: str,
                  redirect_uri: str) -> tuple[bool, dict]:
    """``oauth.v2.access`` — the install's code for the bot token. The payload carries
    ``access_token`` (xoxb-), ``team`` and ``bot_user_id``."""
    return _post("oauth.v2.access", form={
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "redirect_uri": redirect_uri,
    })
