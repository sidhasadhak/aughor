"""VA-11 — the OAuth broker's guards, exercised for real against a faux provider.

``broker._post`` is the seam (one form-encoded POST): tests replace THAT, so state
handling, PKCE, refresh policy and revocation all run their real code while nothing
leaves the machine. What is asserted is the property each guard exists for, not the
happy path around it — a state that completes twice is a token mint, a token in
plaintext at rest is a breach with extra steps, and an ``invalid_grant`` retried
forever is a schedule of failures.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from aughor.integrations import broker, store
from aughor.integrations.models import ProviderApp


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
def google_app():
    store.save_app(ProviderApp(id="google", client_id="cid-123",
                               client_secret="cs-verysecret"))
    yield


@pytest.fixture
def exchange(monkeypatch):
    """A faux token endpoint: records every POST, answers from a queue."""
    calls: list[dict] = []
    responses: list[dict] = [{
        "access_token": "at-live-token-1", "refresh_token": "rt-live-token-1",
        "expires_in": 3600, "scope": "openid email", "token_type": "Bearer",
        "_status": 200,
    }]

    def _fake_post(url, data, headers=None):
        calls.append({"url": url, "data": dict(data)})
        return dict(responses.pop(0)) if responses else {"error": "queue empty", "_status": 500}

    monkeypatch.setattr(broker, "_post", _fake_post)
    return {"calls": calls, "responses": responses}


def _begin(user="u1"):
    return broker.begin("google", user_id=user,
                        redirect_uri="http://localhost:8000/oauth/callback")


def _state_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


# ── begin ────────────────────────────────────────────────────────────────────────

def test_the_authorize_url_carries_state_pkce_and_the_offline_quirks(google_app):
    url = _begin()
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == ["cid-123"]
    assert q["response_type"] == ["code"]
    assert len(q["state"][0]) >= 32
    assert q["code_challenge_method"] == ["S256"]
    # Google's two offline quirks — without them every consent after the first omits
    # the refresh token, and the grant silently cannot outlive its first hour.
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    # The verifier must NOT be in the URL — only its S256 challenge.
    assert "code_verifier" not in q


def test_begin_refuses_when_the_org_app_is_not_registered():
    with pytest.raises(broker.BrokerError, match="not set up"):
        broker.begin("microsoft", user_id="u1",
                     redirect_uri="http://localhost:8000/oauth/callback")


def test_slack_gets_no_pkce_params(google_app):
    # Slack's v2 flow errors on unknown params; sending PKCE "to be safe" breaks
    # exactly one provider in a way no generic test sees. Per-provider, from data.
    store.save_app(ProviderApp(id="slack", client_id="c", client_secret="s"))
    url = broker.begin("slack", user_id="u1",
                       redirect_uri="http://localhost:8000/oauth/callback")
    q = parse_qs(urlparse(url).query)
    assert "code_challenge" not in q and "code_challenge_method" not in q


# ── complete ─────────────────────────────────────────────────────────────────────

def test_the_exchange_presents_the_verifier_behind_the_challenge(google_app, exchange):
    url = _begin()
    q = parse_qs(urlparse(url).query)
    conn = broker.complete(_state_of(url), "auth-code-1")

    sent = exchange["calls"][0]["data"]
    assert sent["code"] == "auth-code-1"
    assert sent["grant_type"] == "authorization_code"
    # The verifier the exchange presents must hash to the challenge the authorize URL
    # carried — the pair IS PKCE; asserting each half separately proves neither.
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"][0]
    # The redirect_uri must be byte-identical to the authorize request's.
    assert sent["redirect_uri"] == "http://localhost:8000/oauth/callback"
    assert conn.status == "active"
    assert conn.scopes == "openid email", "scopes are what the PROVIDER said was granted"


def test_a_state_is_single_use(google_app, exchange):
    """The guard the whole dance hangs on: a state that completes twice is a token mint."""
    url = _begin()
    state = _state_of(url)
    broker.complete(state, "auth-code-1")
    with pytest.raises(broker.BrokerError, match="unknown, already used, or expired"):
        broker.complete(state, "auth-code-1")


def test_an_unknown_state_never_reaches_the_provider(google_app, exchange):
    with pytest.raises(broker.BrokerError):
        broker.complete("forged-state", "stolen-code")
    assert exchange["calls"] == [], "the code must be discarded UNEXCHANGED"


def test_an_expired_pending_flow_is_refused(google_app, exchange, monkeypatch):
    import time as _real_time
    import types
    url = _begin()
    # Patch the MODULE REFERENCE inside `store`, with the real clock captured first —
    # patching the global `time.time` makes the fake call itself and recurse.
    later = _real_time.time() + store.PENDING_TTL_SECONDS + 1
    monkeypatch.setattr(store, "time", types.SimpleNamespace(time=lambda: later))
    with pytest.raises(broker.BrokerError):
        broker.complete(_state_of(url), "auth-code-1")
    assert exchange["calls"] == [], "an expired flow's code must be discarded unexchanged"


def test_tokens_are_encrypted_at_rest_and_absent_from_the_safe_dict(google_app, exchange):
    """Read the RAW store file. The property is at rest, and only the file can prove it."""
    url = _begin()
    conn = broker.complete(_state_of(url), "auth-code-1")

    raw = json.dumps(store._CONNS.all())
    assert "at-live-token-1" not in raw and "rt-live-token-1" not in raw, \
        "a plaintext token at rest is a breach with extra steps"

    safe = store.get_connection(conn.id).to_safe_dict()
    assert "access_token" not in safe and "refresh_token" not in safe, \
        "dropped, not masked — a mask still confirms the token's length-class"


# ── refresh ──────────────────────────────────────────────────────────────────────

def _dying(google_app_conn_id: str):
    conn = store.get_connection(google_app_conn_id)
    return store.save_connection(conn.model_copy(update={
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}))


def test_a_dying_token_is_refreshed_before_it_is_handed_out(google_app, exchange):
    url = _begin()
    conn = broker.complete(_state_of(url), "auth-code-1")
    _dying(conn.id)
    exchange["responses"].append({"access_token": "at-refreshed-2",
                                  "expires_in": 3600, "_status": 200})

    token = broker.fresh_access_token(conn.id)

    assert token == "at-refreshed-2"
    refresh = exchange["calls"][-1]["data"]
    assert refresh["grant_type"] == "refresh_token"
    assert refresh["refresh_token"] == "rt-live-token-1"
    # The provider did not rotate the refresh token, so ours must survive the update.
    again = store.get_connection_decrypted(conn.id)
    assert again.refresh_token == "rt-live-token-1"


def test_invalid_grant_is_a_verdict_not_a_retry(google_app, exchange):
    url = _begin()
    conn = broker.complete(_state_of(url), "auth-code-1")
    _dying(conn.id)
    exchange["responses"].append({"error": "invalid_grant", "_status": 400})

    with pytest.raises(broker.BrokerError, match="reconnect"):
        broker.fresh_access_token(conn.id)
    assert store.get_connection(conn.id).status == "needs_reconnect"
    # And the verdict STICKS: the next call must refuse without touching the provider.
    before = len(exchange["calls"])
    with pytest.raises(broker.BrokerError, match="reconnect"):
        broker.fresh_access_token(conn.id)
    assert len(exchange["calls"]) == before


def test_a_healthy_token_is_handed_out_without_a_refresh(google_app, exchange):
    url = _begin()
    conn = broker.complete(_state_of(url), "auth-code-1")
    calls_before = len(exchange["calls"])
    assert broker.fresh_access_token(conn.id) == "at-live-token-1"
    assert len(exchange["calls"]) == calls_before, "an hour of life left is not 'dying'"


# ── revoke ───────────────────────────────────────────────────────────────────────

def test_revoke_tells_the_provider_then_clears_our_copy(google_app, exchange):
    url = _begin()
    conn = broker.complete(_state_of(url), "auth-code-1")
    exchange["responses"].append({"_status": 200})

    cleared = broker.revoke(conn.id)

    assert exchange["calls"][-1]["url"] == "https://oauth2.googleapis.com/revoke"
    assert exchange["calls"][-1]["data"]["token"] == "at-live-token-1"
    assert cleared.status == "revoked"
    stored = store.get_connection_decrypted(conn.id)
    assert stored.access_token == "" and stored.refresh_token == "", \
        "the row stays for audit; the tokens must not"
    with pytest.raises(broker.BrokerError, match="revoked"):
        broker.fresh_access_token(conn.id)
