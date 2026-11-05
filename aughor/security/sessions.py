"""Browser sessions — an HttpOnly cookie in place of a token the page can read (Track A9).

VA-10 put Google's ID token in ``localStorage`` and attached it as a bearer on every call.
That works, and it hands the credential to any script that runs on the page: an XSS bug
anywhere in the frontend reads the token and is the person for an hour. The 10× program's
Track A9 (`docs/TENX_PROGRAM_2026-11-05.md` §3) moves the credential where a script cannot
reach it:

1. the browser signs in as before and gets the ID token from the identity provider;
2. it presents that token ONCE, to ``POST /auth/session``, which verifies it exactly as
   every bearer is verified (``security/oidc.py``) and answers with a session cookie —
   ``HttpOnly``, ``SameSite=Lax``, ``Secure`` behind TLS;
3. every later call carries the cookie (``credentials: "include"``) and nothing else; the
   page keeps only the signed-in EMAIL, for the chip, which is not a credential.

The cookie's value is a random secret; the ledger holds its SHA-256, so a read of the
ledger does not yield a usable session. A session is bounded by :data:`TTL_S` and ends on
``DELETE /auth/session`` (sign out) — revocation is a row's absence, which the next request
sees. Resolution is fail-closed like a bad token: an unknown, expired or revoked cookie
resolves NO principal and never falls through to a weaker seam (``authz.resolve_principal``).

``SameSite=Lax`` is what keeps a cross-site page from riding the cookie: a form or a fetch
from another site does not carry it. The API's CORS allows credentials only for the exact
origins it serves (``api.py``), never ``*``.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from typing import Optional

from aughor.security.authz import Principal

COOKIE = "aughor_session"
STORE = "auth_sessions"

#: How long a browser session lives, from sign-in: twelve hours by default — a working day
#: with room, shorter than the IdP's own session, longer than the ID token it replaced.
TTL_S = int(os.environ.get("AUGHOR_SESSION_TTL_S", str(12 * 3600)))


def _key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _ledger():
    from aughor.kernel.ledger import Ledger
    return Ledger.default()


def mint(principal: Principal) -> tuple[str, int]:
    """A new session for a VERIFIED principal: the cookie value (returned once, never stored)
    and the epoch second it expires."""
    secret = secrets.token_urlsafe(32)
    exp = int(time.time()) + TTL_S
    _ledger().kv_put(STORE, _key(secret),
                     {"user_id": principal.user_id, "org_id": principal.org_id, "exp": exp,
                      "issued_at": int(time.time())})
    return secret, exp


def resolve(secret: Optional[str]) -> Optional[Principal]:
    """The principal a cookie names, or ``None`` — unknown, expired (and then removed) or revoked."""
    if not secret:
        return None
    led = _ledger()
    row = led.kv_get(STORE, _key(secret))
    if not row:
        return None
    if int(row.get("exp") or 0) <= int(time.time()):
        led.kv_delete(STORE, _key(secret))
        return None
    user, org = str(row.get("user_id") or ""), str(row.get("org_id") or "")
    if not user or not org:
        return None
    return Principal(user_id=user, org_id=org)


def revoke(secret: Optional[str]) -> bool:
    """End a session. True when there was one to end."""
    if not secret:
        return False
    return _ledger().kv_delete(STORE, _key(secret))
