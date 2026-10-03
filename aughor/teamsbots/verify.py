"""Is this Activity really from the Bot Framework? (AO-5c)

The Bot Connector signs every inbound activity with a JWT whose audience is the bot's
Microsoft App ID and whose keys are published at the Bot Framework's OpenID configuration.
`verify_activity_token` checks exactly that — signature against the published key set,
audience, issuer, expiry — and answers ``(ok, why)``. Never raises: an unreachable key
server is a failure to VERIFY, said as such, not a forged request and not a 500.

One function, so a test substitutes it; the real one is used nowhere else.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

OPENID_CONFIG = "https://login.botframework.com/v1/.well-known/openidconfiguration"
#: The issuers the Bot Framework uses for a multi-tenant bot's inbound activities.
ISSUERS = ("https://api.botframework.com",)
_TIMEOUT_S = 10
_jwks_cache: dict = {}


def _jwks_uri() -> str:
    if _jwks_cache.get("uri"):
        return _jwks_cache["uri"]
    req = urllib.request.Request(OPENID_CONFIG, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        cfg = json.loads(resp.read().decode("utf-8") or "{}")
    _jwks_cache["uri"] = str(cfg.get("jwks_uri") or "")
    return _jwks_cache["uri"]


def verify_activity_token(authorization: str, app_id: str) -> tuple[bool, str]:
    """``(ok, why)`` for the `Authorization: Bearer …` header of an inbound activity."""
    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return False, "no bearer token"
    if not app_id:
        return False, "this bot has no app id"
    try:
        import jwt
        uri = _jwks_uri()
        if not uri:
            return False, "the Bot Framework's key set could not be located"
        key = jwt.PyJWKClient(uri).get_signing_key_from_jwt(token)
        jwt.decode(token, key.key, algorithms=["RS256"], audience=app_id,
                   issuer=list(ISSUERS), options={"require": ["exp", "aud", "iss"]})
        return True, "verified"
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, f"could not reach the Bot Framework's key set: {exc}"
    except Exception as exc:                            # noqa: BLE001 — jwt's own error classes
        return False, f"token refused: {type(exc).__name__}: {exc}"
