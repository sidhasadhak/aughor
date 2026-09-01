"""VA-11 consumer — the one path that spends a grant, exercised against a faux provider.

`call._get` is the seam (one authorized GET): tests replace THAT, so resolution, the
scope check, URL construction, the outbound cap and the response mapping all run their
real code while nothing leaves the machine — the same arrangement `broker._post` has,
for the same reason.

What is asserted is the property each guard exists for. The wave's whole premise was
that this plane was INERT — `fresh_access_token` had no callers — so the tests that
matter are the ones proving the refusals happen BEFORE a token is spent, and that a call
which does go out is countable afterwards.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from aughor.integrations import call as callmod
from aughor.integrations import store
from aughor.integrations.models import Connection, ProviderApp
from aughor.integrations.operations import get_operation, scope_granted

GMAIL_LIST = "google.gmail.messages.list"
GMAIL_GET = "google.gmail.messages.get"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@pytest.fixture(autouse=True)
def _virgin_stores():
    for s in (store._APPS, store._CONNS, store._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])
    yield


@pytest.fixture
def google(monkeypatch):
    """An org app, a live grant, and a faux Gmail. Returns the recorder."""
    store.save_app(ProviderApp(id="google", client_id="cid", client_secret="cs"))
    conn = store.save_connection(Connection(
        provider="google", user_id="u1", scopes=f"openid email {GMAIL_SCOPE}",
        account="sales@example.com", access_token="at-1", refresh_token="rt-1",
        # Far enough out that the broker does not try to refresh; refresh policy is the
        # broker's own suite, and a test that accidentally exercises it is testing two
        # things and will fail for the wrong reason.
        expires_at="2099-01-01T00:00:00+00:00", status="active"))
    seen: list[dict] = []
    queued: list[tuple[int, dict]] = []

    def _fake_get(url, token):
        seen.append({"url": url, "token": token})
        return queued.pop(0) if queued else (200, {})

    monkeypatch.setattr(callmod, "_get", _fake_get)
    return {"conn": conn, "seen": seen, "queued": queued}


# ── refusals that spend nothing ──────────────────────────────────────────────────

def test_an_unknown_operation_is_refused_before_any_token_is_fetched(google):
    with pytest.raises(callmod.CallRefused, match="unknown operation"):
        callmod.call("google.gmail.messages.burn", google["conn"].id)
    assert google["seen"] == [], "a refused call must not reach the provider"


def test_a_grant_for_another_provider_is_refused_naming_both(google):
    other = store.save_connection(Connection(provider="microsoft", user_id="u1",
                                             access_token="at-x", status="active"))
    with pytest.raises(callmod.CallRefused) as exc:
        callmod.call(GMAIL_LIST, other.id)
    # Both names, because a 401 from the wrong host names neither.
    assert "google" in str(exc.value) and "microsoft" in str(exc.value)
    assert google["seen"] == []


@pytest.mark.parametrize("status,fragment", [
    ("revoked", "revoked"),
    ("needs_reconnect", "reconnect"),
])
def test_a_dead_grant_is_refused_with_the_sentence_that_fixes_it(google, status, fragment):
    dead = store.save_connection(google["conn"].model_copy(update={"status": status}))
    with pytest.raises(callmod.CallRefused, match=fragment):
        callmod.call(GMAIL_LIST, dead.id)
    assert google["seen"] == []


def test_a_scope_the_user_never_consented_to_is_refused_naming_the_scope(google):
    """The receipt §3.4 asks for: a downgraded consent reads as a sentence, not a 403."""
    narrowed = store.save_connection(
        google["conn"].model_copy(update={"scopes": "openid email"}))
    with pytest.raises(callmod.CallRefused) as exc:
        callmod.call(GMAIL_LIST, narrowed.id)
    assert GMAIL_SCOPE in str(exc.value)
    assert google["seen"] == [], "the token must not be spent to be told this"


def test_a_narrower_scope_that_merely_CONTAINS_the_required_one_is_not_enough():
    """Graph's `Mail.ReadBasic` contains `Mail.Read` and grants strictly less.

    A substring check would read a metadata-only grant as full mail access. This is the
    reason `scope_granted` splits on the provider's own delimiter, and the assertion is
    on the narrower-grant direction because that is the one that would leak.
    """
    outlook = get_operation("microsoft.outlook.messages.list")
    assert outlook.scope == "Mail.Read"
    assert not scope_granted(outlook, "Mail.ReadBasic offline_access")
    assert scope_granted(outlook, "Mail.Read offline_access")


def test_a_provider_that_reports_no_scopes_is_believed_rather_than_refused():
    """`Connection.scopes` is read back from the token response and "" is its honest
    value. Unknown is not the same as missing: refusing on it would make every provider
    that omits `scope` unusable, and the provider is the authority on its own grant."""
    assert scope_granted(get_operation(GMAIL_LIST), "")


def test_a_required_param_missing_at_call_time_is_its_own_refusal(google):
    """Reported as `invalid_params` by the step, not as a dead connection — a BOUND
    param that resolved to nothing is the author's problem, not the grant's."""
    with pytest.raises(callmod.CallParamsMissing, match="Message id"):
        callmod.call(GMAIL_GET, google["conn"].id, {"message_id": "  "})
    assert google["seen"] == []


# ── the call that does go out ────────────────────────────────────────────────────

def test_params_are_encoded_into_the_declared_shape_and_cannot_escape_it(google):
    google["queued"].append((200, {"messages": [{"id": "m1", "threadId": "t1"}]}))
    callmod.call(GMAIL_LIST, google["conn"].id,
                 {"q": "is:unread from:a&b", "max_results": "5"})
    url = google["seen"][0]["url"]
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "gmail.googleapis.com"
    # The ampersand rode inside the value rather than becoming a second parameter.
    assert q["q"] == ["is:unread from:a&b"]
    assert q["maxResults"] == ["5"]


def test_a_path_param_cannot_climb_out_of_its_segment(google):
    google["queued"].append((200, {"id": "m1"}))
    callmod.call(GMAIL_GET, google["conn"].id, {"message_id": "../../tokens"})
    path = urlparse(google["seen"][0]["url"]).path
    assert path.endswith("/messages/..%2F..%2Ftokens"), path


def test_the_step_publishes_declared_keys_and_never_the_provider_body(google):
    google["queued"].append((200, {
        "messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}],
        "resultSizeEstimate": 47,
        # A field nothing declared. It must not reach chain context, where a later step
        # could bind it into a channel.
        "internalAuthToken": "SHOULD-NOT-TRAVEL",
    }))
    data = callmod.call(GMAIL_LIST, google["conn"].id)
    assert data["count"] == 2 and data["estimate"] == 47
    assert [i["id"] for i in data["items"]] == ["m1", "m2"]
    assert "SHOULD-NOT-TRAVEL" not in str(data)


def test_gmail_headers_become_named_fields(google):
    """Gmail returns headers as a LIST of {name, value} — the shape a dotted-path
    mini-language could not have reached, which is why the mapper is a function."""
    google["queued"].append((200, {
        "id": "m1", "snippet": "quarterly numbers",
        "payload": {"headers": [{"name": "Subject", "value": "Q3 review"},
                                {"name": "From", "value": "cfo@example.com"}]},
    }))
    data = callmod.call(GMAIL_GET, google["conn"].id, {"message_id": "m1"})
    assert data["subject"] == "Q3 review"
    assert data["sender"] == "cfo@example.com"
    assert data["snippet"] == "quarterly numbers"


def test_the_bearer_token_comes_from_the_broker_not_off_the_record(google, monkeypatch):
    """The one path that hands out a token is `fresh_access_token`, so refresh policy
    cannot be remembered by one caller and forgotten by another."""
    from aughor.integrations import broker
    monkeypatch.setattr(broker, "fresh_access_token", lambda cid: f"fresh-for-{cid}")
    google["queued"].append((200, {}))
    callmod.call(GMAIL_LIST, google["conn"].id)
    assert google["seen"][0]["token"] == f"fresh-for-{google['conn'].id}"


def test_a_provider_refusal_is_a_failure_carrying_the_providers_own_words(google):
    google["queued"].append((403, {"error": {"message": "Insufficient Permission"}}))
    with pytest.raises(callmod.CallFailed) as exc:
        callmod.call(GMAIL_LIST, google["conn"].id)
    assert "Insufficient Permission" in str(exc.value)
    assert exc.value.status == 403


def test_a_failed_call_is_still_recorded_as_an_external_call(google, monkeypatch):
    """A provider error recorded only on the success path is how a failing counterparty
    stays invisible in exactly the week it matters. The raise happens INSIDE the span."""
    events: list[dict] = []
    from aughor.obs import session_log as slog
    monkeypatch.setattr(slog, "emit",
                        lambda kind, **kw: events.append({"kind": kind, **kw}))
    google["queued"].append((500, {"error": "backend error"}))
    with pytest.raises(callmod.CallFailed):
        callmod.call(GMAIL_LIST, google["conn"].id)
    external = [e for e in events if e["kind"] == slog.EXTERNAL_CALL]
    assert external, "the failed call left no countable trace"
    assert external[0]["ok"] is False
    assert external[0]["name"] == f"google.{GMAIL_LIST}"


def test_the_call_is_attributed_to_the_grants_owner(google, monkeypatch):
    audited: list[dict] = []
    from aughor.govern import actions as govern_actions
    monkeypatch.setattr(govern_actions, "audit",
                        lambda action, **kw: audited.append({"action": action, **kw}))
    google["queued"].append((200, {}))
    callmod.call(GMAIL_LIST, google["conn"].id)
    assert audited and audited[0]["action"] == "integration.call"
    assert audited[0]["actor"] == "u1"
    assert GMAIL_LIST in audited[0]["detail"]
