"""Track A2 (docs/TENX_PROGRAM_2026-11-05.md §1.3): identity required with nothing to verify it.

Measured before this: with ``AUGHOR_REQUIRE_IDENTITY=1`` and no OIDC issuer, the transitional
``X-Aughor-Org`` / ``X-Aughor-User`` headers were the identity. Anyone on the port named an
organisation, was its first caller, and was made its owner — and nothing said so anywhere. The
one deployment where trusting those headers is right is a proxy that authenticates and strips
them, and the app cannot tell that apart from an open port; so the operator declares it
(``AUGHOR_IDENTITY_FROM_PROXY=1``) or the API refuses every request with the reason.

The suite itself signs requests with those headers, so ``tests/conftest.py`` declares the proxy
for every other test; these delete the declaration to see the refusal.
"""
from __future__ import annotations

from aughor.security.authz import identity_unverifiable


def _undeclared(monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("AUGHOR_IDENTITY_FROM_PROXY", raising=False)


def test_required_and_undeclared_refuses_every_request_with_the_reason(client, monkeypatch):
    _undeclared(monkeypatch)
    r = client.get("/connections", headers={"X-Aughor-Org": "acme", "X-Aughor-User": "mallory"})
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert "AUGHOR_OIDC_ISSUER" in detail and "AUGHOR_IDENTITY_FROM_PROXY" in detail
    assert "strips them from clients" in detail       # the one condition under which the seam is safe
    # And the headers resolve NOTHING — a dead seam, not a refused-but-trusted one.
    from aughor.security.authz import resolve_principal
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": "/connections", "query_string": b"",
             "headers": [(b"x-aughor-org", b"acme"), (b"x-aughor-user", b"mallory")]}
    assert resolve_principal(Request(scope)) is None


def test_health_and_auth_config_still_answer_and_say_why(client, monkeypatch):
    _undeclared(monkeypatch)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "degraded"
    assert body["identity"] == {"required": True, "verified_by": "nothing", "ok": False,
                                "refusal": identity_unverifiable()}
    cfg = client.get("/auth/config").json()
    assert cfg["identity_required"] is True and cfg["oidc_configured"] is False
    assert cfg["refusal"] == identity_unverifiable()


def test_a_declared_proxy_opens_the_seam_and_health_says_which(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    monkeypatch.setenv("AUGHOR_IDENTITY_FROM_PROXY", "1")
    assert identity_unverifiable() == ""
    r = client.get("/connections", headers={"X-Aughor-Org": "a2-proxy-org", "X-Aughor-User": "amit"})
    assert r.status_code == 200, r.text
    assert client.get("/health").json()["identity"]["verified_by"] == "proxy"


def test_identity_off_is_byte_identical(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_REQUIRE_IDENTITY", raising=False)
    monkeypatch.delenv("AUGHOR_IDENTITY_FROM_PROXY", raising=False)
    assert identity_unverifiable() == ""
    assert client.get("/connections").status_code == 200
    assert client.get("/health").json()["identity"]["verified_by"] == "off"


def test_the_doctor_reads_the_same_predicate(monkeypatch):
    from aughor import doctor
    _undeclared(monkeypatch)
    c = doctor._identity()
    assert c.status == doctor.FAIL and "AUGHOR_IDENTITY_FROM_PROXY" in c.fix
    monkeypatch.setenv("AUGHOR_IDENTITY_FROM_PROXY", "1")
    c = doctor._identity()
    assert c.status == doctor.WARN and "declared proxy" in c.found
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", "https://accounts.google.com")
    assert doctor._identity().status == doctor.OK
