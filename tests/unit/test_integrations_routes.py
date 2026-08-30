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
