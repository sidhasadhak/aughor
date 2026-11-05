"""Track A9 (docs/TENX_PROGRAM_2026-11-05.md): the browser's credential is an HttpOnly cookie.

Before: Google's ID token sat in ``localStorage`` and rode every call as a bearer — readable by any
script on the page. Now the token is presented once to ``POST /auth/session``, verified as every
bearer is, and exchanged for a cookie a script cannot read; the ledger keeps the cookie's hash,
never the cookie; sign-out and expiry are a row's absence, seen by the next request.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from aughor.security import oidc, sessions
from aughor.security.authz import Principal

ISSUER, AUDIENCE = "https://idp.a9.test", "aughor-a9"
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC = _PRIVATE.public_key()


def _token(email="ada@a9.test", exp_delta=600) -> str:
    return pyjwt.encode({"sub": "u-ada", "email": email, "iss": ISSUER, "aud": AUDIENCE,
                         "exp": int(time.time()) + exp_delta}, _PRIVATE, algorithm="RS256")


@pytest.fixture
def idp(monkeypatch):
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AUGHOR_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("AUGHOR_OIDC_DEFAULT_ORG", "a9-org")
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setattr(oidc, "_signing_key", lambda token: _PUBLIC)


def test_a_verified_token_becomes_an_httponly_cookie_that_signs_every_later_call(client, idp):
    client.cookies.clear()
    r = client.post("/auth/session", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == "ada@a9.test" and r.json()["org_id"] == "a9-org"
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "path=/" in set_cookie
    assert "secure" not in set_cookie                  # plain HTTP here; Secure rides TLS or X-Forwarded-Proto
    # The cookie alone — no bearer, no headers — is the identity now.
    me = client.get("/rbac/me")
    assert me.status_code == 200 and me.json()["user_id"] == "ada@a9.test" and me.json()["org_id"] == "a9-org"


def test_the_ledger_holds_the_hash_never_the_cookie(client, idp):
    client.cookies.clear()
    client.post("/auth/session", headers={"Authorization": f"Bearer {_token()}"})
    secret = client.cookies.get(sessions.COOKIE)
    assert secret
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().kv_load_all(sessions.STORE)
    assert secret not in rows and sessions._key(secret) in rows
    assert rows[sessions._key(secret)]["user_id"] == "ada@a9.test"


def test_sign_out_ends_the_session_and_the_old_cookie_resolves_nobody(client, idp):
    client.cookies.clear()
    client.post("/auth/session", headers={"Authorization": f"Bearer {_token()}"})
    secret = client.cookies.get(sessions.COOKIE)
    out = client.delete("/auth/session")
    assert out.status_code == 200 and out.json() == {"signed_out": True, "ended": True}
    # A stale tab still presenting the old cookie is nobody — and never the header seam.
    client.cookies.set(sessions.COOKIE, secret)
    r = client.get("/rbac/me", headers={"X-Aughor-Org": "a9-org", "X-Aughor-User": "mallory"})
    assert r.status_code == 401, r.text
    # Signing out again with the stale cookie: identity is required and the cookie is nobody, so the front
    # door answers first — a 401, never a second session ended.
    assert client.delete("/auth/session").status_code == 401


def test_expired_forged_and_absent_cookies_resolve_nobody(client, idp, monkeypatch):
    assert sessions.resolve(None) is None and sessions.resolve("not-a-session") is None
    secret, exp = sessions.mint(Principal(user_id="ada@a9.test", org_id="a9-org"))
    assert sessions.resolve(secret) == Principal(user_id="ada@a9.test", org_id="a9-org")
    monkeypatch.setattr(sessions.time, "time", lambda: exp + 1)
    assert sessions.resolve(secret) is None                            # expired, and removed on sight
    monkeypatch.setattr(sessions.time, "time", lambda: exp - 100)
    assert sessions.resolve(secret) is None


def test_nothing_weaker_than_a_verified_token_mints_a_session(client, idp):
    client.cookies.clear()
    no_bearer = client.post("/auth/session", headers={"X-Aughor-Org": "a9-org", "X-Aughor-User": "mallory"})
    assert no_bearer.status_code == 401
    bad = client.post("/auth/session", headers={"Authorization": f"Bearer {_token(exp_delta=-5)}"})
    assert bad.status_code == 401                                        # refused at the front door
    assert sessions.COOKIE not in client.cookies


def test_without_an_issuer_there_is_nothing_to_sign_in_to(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    assert client.post("/auth/session").status_code == 404


def test_credentials_ride_only_when_every_origin_is_named():
    """Starlette with `*` + credentials echoes ANY origin beside allow-credentials: true — the combination the
    browser is told to refuse, and the one that would hand a signed-in person's cookie to any site. The suite
    runs with `*` (conftest), so that is the case the live app shows here; the named case is the pure decision."""
    from aughor.api import cors_policy
    assert cors_policy("http://localhost:3000, https://app.example") == (["http://localhost:3000", "https://app.example"], True)
    assert cors_policy("*") == (["*"], False)
    assert cors_policy("http://localhost:3000,*") == (["http://localhost:3000", "*"], False)


def test_the_wildcard_suite_app_sends_no_credentials_header(client):
    pre = client.options("/rbac/me", headers={"Origin": "https://evil.example",
                                             "Access-Control-Request-Method": "GET"})
    assert pre.headers.get("access-control-allow-credentials") != "true"
