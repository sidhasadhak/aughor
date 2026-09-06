"""VA-10 — OIDC bearer verification at the identity seam (§6 item 11).

The properties that matter, each the closure of a measured hole:

  * a VERIFIED token resolves the principal — and tenant isolation now rides a
    signature, not a header;
  * an INVALID token resolves nothing and is never downgraded to the header seam;
  * while an issuer is configured and identity is required, ``X-Aughor-User: mallory``
    is DEAD — the exact spoof demonstrated live on 2026-09-04 (§3.5);
  * half-configuration (issuer without audience) fails closed;
  * localhost mode and the no-OIDC deployment are byte-identical to before.

The one seam the tests replace is ``oidc._signing_key`` — everything below it
(signature, exp, aud, iss, claim mapping) runs for real against keys minted here.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from aughor.security import oidc

ISSUER = "https://idp.example.test"
AUDIENCE = "aughor-client-id"

_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC = _PRIVATE.public_key()


def _token(*, sub="user-1", email="ada@example.test", iss=ISSUER, aud=AUDIENCE,
           exp_delta=600, extra=None) -> str:
    claims = {"sub": sub, "iss": iss, "aud": aud,
              "exp": int(time.time()) + exp_delta, **({"email": email} if email else {}),
              **(extra or {})}
    return pyjwt.encode(claims, _PRIVATE, algorithm="RS256")


@pytest.fixture
def oidc_env(monkeypatch):
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AUGHOR_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setattr(oidc, "_signing_key", lambda token: _PUBLIC)


@pytest.fixture
def acme_canvas(monkeypatch):
    """A canvas owned by org 'acme' — the tenant-isolation probe object."""
    from aughor.canvas.models import CanvasScope
    from aughor.canvas.store import create_canvas
    from aughor.db.registry import add_connection
    from aughor.org.context import using_org

    with using_org("acme"):
        conn_id = add_connection(name="acme-conn", conn_type="duckdb",
                                 dsn="/tmp/acme-oidc.duckdb", meta={})
    canvas = create_canvas(
        name="acme-oidc-canvas",
        scopes=[CanvasScope(connection_id=conn_id, schema_name=None, tables=[])])
    return canvas.id


# ── the module's own contracts (no HTTP) ─────────────────────────────────────────

def test_only_jwt_shaped_bearers_are_claimed():
    # /cron/tick's `Bearer $CRON_SECRET` and the webhook token must pass through.
    assert oidc.bearer_token("Bearer some-cron-secret") is None
    assert oidc.bearer_token("Bearer a.b") is None
    assert oidc.bearer_token(None) is None
    assert oidc.bearer_token("Basic dXNlcjpwYXNz") is None
    assert oidc.bearer_token("Bearer h.p.s") == "h.p.s"


def test_issuer_without_audience_fails_closed(monkeypatch):
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", ISSUER)
    monkeypatch.delenv("AUGHOR_OIDC_AUDIENCE", raising=False)
    with pytest.raises(oidc.OidcError, match="AUGHOR_OIDC_AUDIENCE"):
        oidc.verify(_token())


def test_verify_enforces_signature_expiry_audience_issuer(oidc_env):
    assert oidc.verify(_token())["sub"] == "user-1"
    with pytest.raises(oidc.OidcError):
        oidc.verify(_token(exp_delta=-600))
    with pytest.raises(oidc.OidcError):
        oidc.verify(_token(aud="someone-elses-app"))
    with pytest.raises(oidc.OidcError):
        oidc.verify(_token(iss="https://evil.example.test"))
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = pyjwt.encode({"sub": "x", "iss": ISSUER, "aud": AUDIENCE,
                           "exp": int(time.time()) + 600}, other_key, algorithm="RS256")
    with pytest.raises(oidc.OidcError):
        oidc.verify(forged)


def test_principal_prefers_email_and_org_claim_is_strict(monkeypatch):
    assert oidc.principal_of({"sub": "s1", "email": "ada@example.test"}).user_id == "ada@example.test"
    assert oidc.principal_of({"sub": "s1"}).user_id == "s1"
    assert oidc.principal_of({"sub": "s1"}).org_id == "default"
    monkeypatch.setenv("AUGHOR_OIDC_ORG_CLAIM", "org")
    assert oidc.principal_of({"sub": "s1", "org": "acme"}).org_id == "acme"
    # A configured org claim that the token lacks REFUSES — silently landing in the
    # default org would be a tenant-boundary bug wearing a convenience.
    with pytest.raises(oidc.OidcError, match="org"):
        oidc.principal_of({"sub": "s1"})


# ── the seam under HTTP ──────────────────────────────────────────────────────────

def test_verified_token_resolves_and_tenant_isolation_rides_the_signature(
        client, acme_canvas, oidc_env, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("AUGHOR_OIDC_DEFAULT_ORG", "acme")
    ok = client.get(f"/canvases/{acme_canvas}",
                    headers={"Authorization": f"Bearer {_token()}"})
    assert ok.status_code == 200

    # Same valid token, different org → 403: the boundary is now signed.
    monkeypatch.setenv("AUGHOR_OIDC_DEFAULT_ORG", "globex")
    other = client.get(f"/canvases/{acme_canvas}",
                       headers={"Authorization": f"Bearer {_token()}"})
    assert other.status_code == 403


def test_invalid_token_is_401_never_a_header_downgrade(client, acme_canvas, oidc_env, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get(f"/canvases/{acme_canvas}", headers={
        "Authorization": f"Bearer {_token(exp_delta=-600)}",
        # The spoof ride-along: these headers must NOT rescue a bad token.
        "X-Aughor-Org": "acme", "X-Aughor-User": "mallory"})
    assert r.status_code == 401


def test_the_mallory_headers_are_dead_while_oidc_is_configured(
        client, acme_canvas, oidc_env, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get(f"/canvases/{acme_canvas}",
                   headers={"X-Aughor-Org": "acme", "X-Aughor-User": "mallory"})
    assert r.status_code == 401
    assert "OIDC" in r.json()["detail"]


def test_without_oidc_the_transitional_header_seam_is_unchanged(client, acme_canvas, monkeypatch):
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    r = client.get(f"/canvases/{acme_canvas}", headers={"X-Aughor-Org": "acme"})
    assert r.status_code == 200


def test_localhost_mode_is_byte_identical(client, acme_canvas, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    assert client.get(f"/canvases/{acme_canvas}").status_code == 200


# ── the admin view (VA-10's second half) ─────────────────────────────────────────

def test_admin_users_unions_ledger_and_roles_and_states_coverage(client):
    from aughor.org.context import current_org_id
    from aughor.rbac.store import assign_role

    assign_role(current_org_id() or "default", "ada@example.test", "analyst")
    r = client.get("/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert {"users", "total_calls", "unattributed_calls", "coverage",
            "identity_required", "oidc_configured"} <= set(body)
    ada = next(u for u in body["users"] if u["user_id"] == "ada@example.test")
    assert ada["roles"] == ["analyst"]
    assert ada["calls"] == 0  # granted a role, no calls yet — still real


def test_admin_users_never_shows_the_unattributed_cohort_as_a_user(client, monkeypatch):
    """Found by driving the live route after #459: the rollup keys a missing user as
    the "(unattributed)" placeholder, not "" — and the roster showed it as a user with
    3,167 calls. The placeholder belongs in `unattributed_calls`, never in `users`."""
    import aughor.obs.usage as usage_mod
    from aughor.obs.usage import UNATTRIBUTED, UsageReport, UsageRow

    fake = UsageReport(axes=("user_id",), total_calls=5,
                       unattributed={"user_id": 4},
                       rows=[UsageRow(key={"user_id": UNATTRIBUTED}, calls=4),
                             UsageRow(key={"user_id": "ada@example.test"}, calls=1)])
    monkeypatch.setattr(usage_mod, "usage_report", lambda **kw: fake)

    body = client.get("/admin/users").json()
    names = [u["user_id"] for u in body["users"]]
    assert UNATTRIBUTED not in names
    assert "ada@example.test" in names
    assert body["unattributed_calls"] == 4
    assert body["coverage"] == 0.2
