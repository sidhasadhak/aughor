"""VA-11 — the routes, through the real app: wiring, the two-button catalog, and the
ownership boundary. The broker's own guards live in ``test_integrations_broker``;
what these prove is that the API layer neither leaks nor invents."""
from __future__ import annotations

import pytest

from aughor.integrations import broker, store
from aughor.integrations.models import Connection


@pytest.fixture(autouse=True)
def _virgin_stores():
    """The integration stores are SESSION-scoped tmp files, so a `google_app` saved by
    one test file is still there when the next file's catalog asserts `configured is
    False`. Found as an ordering-dependent failure: broker tests before route tests
    turned Set up into Connect. Every test here starts from an empty store."""
    for s in (store._APPS, store._CONNS, store._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])
    yield


@pytest.fixture
def no_provider_calls(monkeypatch):
    monkeypatch.setattr(broker, "_post",
                        lambda *a, **k: {"error": "network reached", "_status": 599})


def test_the_catalog_flips_set_up_into_connect(client, no_provider_calls):
    before = client.get("/integrations/catalog").json()
    google = next(p for p in before["providers"] if p["id"] == "google")
    assert google["configured"] is False
    assert before["redirect_uri"].endswith("/oauth/callback")

    r = client.put("/integrations/google/app",
                   json={"client_id": "cid-1", "client_secret": "cs-1"})
    assert r.status_code == 200
    assert r.json()["app"]["client_secret"] != "cs-1", "the secret must come back masked"

    after = client.get("/integrations/catalog").json()
    assert next(p for p in after["providers"] if p["id"] == "google")["configured"] is True


def test_connect_returns_the_authorize_url(client, no_provider_calls):
    client.put("/integrations/google/app",
               json={"client_id": "cid-1", "client_secret": "cs-1"})
    r = client.post("/integrations/google/connect")
    assert r.status_code == 200
    assert r.json()["authorize_url"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?")


def test_a_forged_callback_renders_not_connected_and_exchanges_nothing(
        client, no_provider_calls):
    r = client.get("/oauth/callback", params={"state": "forged", "code": "stolen"})
    assert r.status_code == 200
    assert "Not connected" in r.text


def test_declined_consent_is_reported_as_a_choice(client):
    r = client.get("/oauth/callback", params={"error": "access_denied"})
    assert "Consent was declined" in r.text


def test_someone_elses_connection_is_a_404_not_a_403(client, no_provider_calls):
    """A 403 confirms the id exists; for another user's grant, existence itself is
    the leak. Filed under RC-4's identity rules: the route filters on the CURRENT
    user, and a foreign id must be indistinguishable from a nonexistent one."""
    foreign = store.save_connection(Connection(
        provider="google", user_id="somebody-else", access_token="at-x"))
    r = client.post(f"/integrations/connections/{foreign.id}/revoke")
    assert r.status_code == 404

    mine = client.get("/integrations/connections").json()["connections"]
    assert all(c["id"] != foreign.id for c in mine)


# ── the Set-up form is an EDITOR, not a one-shot ──────────────────────────────────

def test_the_catalog_shows_back_what_was_stored(client):
    """An Edit form opening on two empty boxes reads as "nothing was ever saved" — the
    user's own words when they hit it. The client id comes back whole (it travels in the
    browser's address bar during the dance; it is not a secret), the secret only as a
    masked preview: enough to say one EXISTS, never enough to read it."""
    client.put("/integrations/google/app",
               json={"client_id": "cid-123", "client_secret": "shh-super-secret"})

    google = next(p for p in client.get("/integrations/catalog").json()["providers"]
                  if p["id"] == "google")
    assert google["client_id"] == "cid-123"
    assert google["secret_preview"] and "shh-super-secret" not in google["secret_preview"]
    assert "•" in google["secret_preview"]


def test_a_blank_secret_keeps_the_stored_one(client):
    """The secret is never readable, so requiring it back on every edit would force a
    rotation to fix a typo in the client id."""
    client.put("/integrations/google/app",
               json={"client_id": "cid-1", "client_secret": "secret-1"})
    fixed = client.put("/integrations/google/app", json={"client_id": "cid-2"})
    assert fixed.status_code == 200, fixed.text

    from aughor.integrations.store import get_app_decrypted
    app = get_app_decrypted("google")
    assert app.client_id == "cid-2"
    assert app.client_secret == "secret-1"      # unchanged, not blanked


def test_an_authored_callback_is_stored_and_used(client):
    client.put("/integrations/google/app", json={
        "client_id": "cid", "client_secret": "sec",
        "redirect_uri": "https://tunnel.example.com/oauth/callback"})

    google = next(p for p in client.get("/integrations/catalog").json()["providers"]
                  if p["id"] == "google")
    assert google["redirect_uri"] == "https://tunnel.example.com/oauth/callback"

    url = client.post("/integrations/google/connect").json()["authorize_url"]
    assert "tunnel.example.com%2Foauth%2Fcallback" in url or \
           "tunnel.example.com/oauth/callback" in url


def test_a_callback_that_cannot_complete_is_refused_at_save(client):
    """Only one route can finish the exchange; a URI that does not end there is a flow
    that breaks after the person has already consented."""
    bad = client.put("/integrations/google/app", json={
        "client_id": "c", "client_secret": "s", "redirect_uri": "https://example.com/hello"})
    assert bad.status_code == 422
    assert "/oauth/callback" in bad.json()["detail"]


def test_slack_refuses_an_http_callback_at_save(client):
    """Slack's own documented rule, enforced before the person walks into its error
    page — which is how this was found."""
    refused = client.put("/integrations/slack/app", json={
        "client_id": "c", "client_secret": "s",
        "redirect_uri": "http://localhost:8000/oauth/callback"})
    assert refused.status_code == 422
    assert "http://" in refused.json()["detail"]


def test_the_providers_own_address_is_refused_as_a_callback(client):
    """The mistake this field invites, found live: a person asked for "the Slack URL"
    has their WORKSPACE url in hand, and it passes every other rule — https, ends in
    /oauth/callback, not http. It then fails silently: consent succeeds, Slack redirects
    to itself, and nothing reaches the exchange."""
    refused = client.put("/integrations/slack/app", json={
        "client_id": "c", "client_secret": "s",
        "redirect_uri": "https://luxexperience-crew.slack.com/oauth/callback"})
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert "own address" in detail
    assert "BACK to Aughor" in detail        # it says WHOSE address it should be


def test_a_tunnel_to_this_api_is_accepted(client):
    ok = client.put("/integrations/slack/app", json={
        "client_id": "c", "client_secret": "s",
        "redirect_uri": "https://calm-otter-1234.trycloudflare.com/oauth/callback"})
    assert ok.status_code == 200, ok.text


# ── the door a laptop can actually open ───────────────────────────────────────────

def _slack(client):
    return next(p for p in client.get("/integrations/catalog").json()["providers"]
                if p["id"] == "slack")


def test_slack_oauth_is_not_offered_when_the_callback_cannot_be_https(client):
    """The whole point: a fresh install is reached over http://, Slack refuses http://,
    so its OAuth button cannot work — and pointing a new user at it costs them an evening
    on a tunnel to reach a token nothing consumes yet."""
    assert _slack(client)["oauth_ready"] is False
    assert _slack(client)["alt_door"] == "slack_app"


def test_a_provider_that_takes_the_loopback_address_is_ready(client):
    """Google and Microsoft accept `http://localhost`, so nothing changes for them."""
    google = next(p for p in client.get("/integrations/catalog").json()["providers"]
                  if p["id"] == "google")
    assert google["oauth_ready"] is True
    assert google["alt_door"] == ""


def test_an_https_override_makes_slack_oauth_available_again(client):
    """A tunnel (or a real deployment) is the case OAuth was written for — the readiness
    reads the SAME callback `connect` will send, so the button and the dance agree."""
    client.put("/integrations/slack/app", json={
        "client_id": "c", "client_secret": "s",
        "redirect_uri": "https://calm-otter-1234.trycloudflare.com/oauth/callback"})
    assert _slack(client)["oauth_ready"] is True
