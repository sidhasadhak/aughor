"""`GET /auth/config` — the how-to-authenticate payload (VA-10).

The property that matters most is the paradoxical one: this route must answer
WITHOUT identity even when identity is required — a client with no token yet has to
be able to learn how to get one, or requiring identity bricks every UI. And it must
never serve more than what is public by nature (issuer + client id; no secret exists
on this path at all).
"""
from __future__ import annotations


def test_unconfigured_deployment_says_so(client, monkeypatch):
    monkeypatch.delenv("AUGHOR_OIDC_ISSUER", raising=False)
    body = client.get("/auth/config").json()
    assert body["oidc_configured"] is False


def test_configured_deployment_serves_issuer_audience_and_provider_hint(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", "https://accounts.google.com")
    monkeypatch.setenv("AUGHOR_OIDC_AUDIENCE", "abc123.apps.googleusercontent.com")
    body = client.get("/auth/config").json()
    assert body["oidc_configured"] is True
    assert body["issuer"] == "https://accounts.google.com"
    assert body["client_id"] == "abc123.apps.googleusercontent.com"
    assert body["provider"] == "google"


def test_a_non_google_issuer_is_generic(client, monkeypatch):
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", "https://login.example.test/realms/main")
    monkeypatch.setenv("AUGHOR_OIDC_AUDIENCE", "aughor")
    assert client.get("/auth/config").json()["provider"] == "generic"


def test_reachable_without_identity_even_when_identity_is_required(client, monkeypatch):
    """The whole point of the exemption: no token, no headers, identity required —
    and the route still answers, saying identity IS required."""
    monkeypatch.setenv("AUGHOR_REQUIRE_IDENTITY", "1")
    monkeypatch.setenv("AUGHOR_OIDC_ISSUER", "https://accounts.google.com")
    monkeypatch.setenv("AUGHOR_OIDC_AUDIENCE", "abc123.apps.googleusercontent.com")
    r = client.get("/auth/config")
    assert r.status_code == 200
    assert r.json()["identity_required"] is True
