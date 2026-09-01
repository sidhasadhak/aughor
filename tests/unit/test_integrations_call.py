"""DS-11 — the consumer: what happens when a grant is actually spent.

``call.py`` is the only door to a user's token, so what is locked here is the ORDER of
its gates and the fact that each one refuses BEFORE the thing it guards:

* a revoked or un-refreshable grant never reaches the network;
* a scope the user did not consent to is refused HERE, with the scope named, rather
  than sent and returned as the provider's own opaque 403;
* a param the roster does not declare is refused rather than forwarded — an undeclared
  ``cc`` silently dropped is a message the author believes was copied to someone;
* a path value cannot leave its path segment (``../..`` addresses a message called
  that, and nothing else);
* the approval gate stops an un-allowlisted WRITE and does not touch a read;
* the call rides ``govern.outbound``, so it is capped before the work and countable
  after it;
* Slack's ``200 {"ok": false}`` is a failure, because a body-level refusal read as
  success is how an integration reports a message it never sent.

``call._request`` is the seam (one HTTP call): tests replace THAT, so every gate above
it runs its real code while nothing leaves the machine — the same choice
``broker._post`` made, and the reason both are trustworthy under test.
"""
from __future__ import annotations

import pytest

from aughor.integrations import call as callmod
from aughor.integrations import store
from aughor.integrations.models import Connection


@pytest.fixture(autouse=True)
def _virgin_stores():
    """The integration stores are SESSION-scoped tmp files — the ordering-dependent
    failure `test_integrations_broker.py` documents. Cleaned on the way OUT as well:
    a grant left behind here is an extra row in another file's component-registry
    search, which is how that half of the rule was bought."""
    for s in (store._APPS, store._CONNS, store._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])
    yield
    for s in (store._APPS, store._CONNS, store._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])


@pytest.fixture
def grant():
    """One live Google grant carrying exactly the scope its read operations need."""
    return store.save_connection(Connection(
        id="ic_google", provider="google", account="sales@example.com",
        scopes="openid email https://www.googleapis.com/auth/gmail.readonly",
        access_token="at-live", refresh_token="rt-live", status="active"))


@pytest.fixture
def slack_grant():
    return store.save_connection(Connection(
        id="ic_slack", provider="slack", account="Acme",
        scopes="chat:write channels:read",
        access_token="at-slack", status="active"))


@pytest.fixture
def wire(monkeypatch):
    """A faux provider: records every request, answers from a queue."""
    calls: list[dict] = []
    queue: list[tuple[int, object]] = []

    def _fake_request(method, url, *, headers, query, body):
        calls.append({"method": method, "url": url, "headers": dict(headers),
                      "query": dict(query or {}), "body": dict(body or {})})
        return queue.pop(0) if queue else (200, {})

    monkeypatch.setattr(callmod, "_request", _fake_request)
    # The token is fetched through the broker; refresh policy is that module's contract
    # and is proven in its own file. Here it is a fixed string, so what is asserted is
    # what THIS module does with it.
    monkeypatch.setattr(callmod, "_fresh_token", lambda cid: "at-live")
    return {"calls": calls, "queue": queue}


# ── the grant's own verdicts, before anything leaves ─────────────────────────────

def test_a_revoked_grant_never_reaches_the_network(wire):
    store.save_connection(Connection(id="ic_dead", provider="google", status="revoked"))
    res = callmod.call_operation("ic_dead", "gmail.messages.list")
    assert res.status == "refused" and "revoked" in res.message
    assert wire["calls"] == [], "a revoked grant must not produce a request"


def test_a_grant_awaiting_reconnection_names_the_door(wire):
    store.save_connection(Connection(id="ic_stale", provider="google",
                                     status="needs_reconnect"))
    res = callmod.call_operation("ic_stale", "gmail.messages.list")
    assert res.status == "refused"
    assert "reconnect" in res.message.lower() and "Integrations" in res.message
    assert wire["calls"] == []


def test_an_operation_from_another_provider_is_refused(wire, grant):
    """A Slack operation on a Google grant. Caught here rather than by Google answering
    404 to a slack.com path — which could not happen, because the URL is the roster's,
    but the pairing still has to be checked or the request would go out with the wrong
    account's token in the header."""
    res = callmod.call_operation(grant.id, "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi"})
    assert res.status == "refused" and "google" in res.message
    assert wire["calls"] == []


def test_a_scope_the_user_declined_is_refused_with_the_scope_named(wire):
    store.save_connection(Connection(id="ic_thin", provider="google",
                                     scopes="openid email", status="active"))
    res = callmod.call_operation("ic_thin", "gmail.messages.list")
    assert res.status == "refused"
    assert "gmail.readonly" in res.message and "reconnect" in res.message
    assert wire["calls"] == []


def test_a_grant_that_states_no_scopes_is_not_refused(wire, monkeypatch):
    """Silence is not a measured absence. Several providers return no scope list at all,
    and refusing on silence would dim every row on one that simply does not say — the
    palette's own rule (only a measured zero dims), one plane over."""
    store.save_connection(Connection(id="ic_quiet", provider="google", scopes="",
                                     status="active"))
    wire["queue"].append((200, {"messages": []}))
    res = callmod.call_operation("ic_quiet", "gmail.messages.list")
    assert res.status == "executed"


# ── the params: only what the roster declares, and nothing that moves the path ───

def test_an_undeclared_param_is_refused_not_dropped(wire, slack_grant):
    res = callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi", "cc": "boss@x.com"})
    assert res.status == "refused" and "'cc'" in res.message
    assert wire["calls"] == [], "an undeclared param must not be forwarded"


def test_a_missing_required_param_is_refused(wire, slack_grant):
    res = callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                 {"channel": "#x"})
    assert res.status == "refused" and "text" in res.message
    assert wire["calls"] == []


def test_a_path_value_cannot_escape_its_segment(wire, grant):
    """The whole guarantee of the closed URL set. A path param that could carry a `/`
    would let a declared operation address an undeclared endpoint."""
    wire["queue"].append((200, {"id": "x", "threadId": "t", "snippet": "s"}))
    callmod.call_operation(grant.id, "gmail.messages.get", {"id": "../../admin"})
    url = wire["calls"][0]["url"]
    assert url == ("https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                   "..%2F..%2Fadmin")
    # 8 — the two in `https://` and the six of the declared path. The value contributed
    # none of its own, which is the entire guarantee.
    assert url.count("/") == 8


def test_declared_defaults_are_sent_and_the_token_rides_the_header(wire, grant):
    wire["queue"].append((200, {"messages": []}))
    callmod.call_operation(grant.id, "gmail.messages.list", {"q": "is:unread"})
    sent = wire["calls"][0]
    assert sent["query"] == {"q": "is:unread", "maxResults": 10}
    assert sent["headers"]["Authorization"] == "Bearer at-live"


# ── what comes back: declared keys only, bounded ────────────────────────────────

def test_only_declared_keys_are_published(wire, grant):
    wire["queue"].append((200, {
        "messages": [{"id": "m1", "threadId": "t1", "internalDate": "170"}],
        "nextPageToken": "np", "resultSizeEstimate": 41,
    }))
    res = callmod.call_operation(grant.id, "gmail.messages.list")
    assert res.status == "executed"
    assert res.data == {"items": [{"id": "m1", "threadId": "t1"}], "count": 1,
                        "next_page_token": "np"}, \
        "a provider adding a field must not silently widen what a chain carries"


def test_a_provider_that_ignores_our_limit_is_refused_not_truncated(wire, grant):
    """W2's law: a silently shortened list is a chain acting on part of the world while
    its `count` describes all of it."""
    wire["queue"].append((200, {"messages": [{"id": str(n)} for n in range(callmod.MAX_ITEMS + 1)]}))
    res = callmod.call_operation(grant.id, "gmail.messages.list")
    assert res.status == "refused" and "Lower this step's limit" in res.message


def test_slacks_two_hundred_with_ok_false_is_a_failure(wire, slack_grant):
    wire["queue"].append((200, {"ok": False, "error": "channel_not_found"}))
    res = callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                 {"channel": "#nope", "text": "hi"})
    assert res.status == "failed" and "channel_not_found" in res.message


def test_a_failed_call_publishes_nothing(wire, grant):
    wire["queue"].append((403, {"error": {"message": "Insufficient Permission"}}))
    res = callmod.call_operation(grant.id, "gmail.messages.list")
    assert res.status == "failed" and "Insufficient Permission" in res.message
    assert res.data == {}, "an error body is not this operation's declared keys"


def test_an_unreadable_write_is_uncertain_and_an_unreadable_read_is_not(
        wire, grant, slack_grant, monkeypatch):
    """A transport failure MAY have delivered. For a write that is the difference
    between a retry and a duplicate; for a read it is only a retry."""
    def _boom(*a, **k):
        raise ConnectionError("connection reset")
    monkeypatch.setattr(callmod, "_request", _boom)
    assert callmod.call_operation(grant.id, "gmail.messages.list").status == "failed"
    assert callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                  {"channel": "#x", "text": "hi"}).status == "uncertain"


# ── the two governance planes ───────────────────────────────────────────────────

def test_a_usage_cap_blocks_before_the_work_and_says_nothing_was_sent(
        wire, grant, monkeypatch):
    from aughor.govern import outbound

    class _Decision:
        allowed = False
        reason = "monthly call budget reached"

    monkeypatch.setattr(outbound, "_cap_decision", lambda org, user: _Decision())
    res = callmod.call_operation(grant.id, "gmail.messages.list")
    assert res.status == "blocked" and "budget" in res.message
    assert wire["calls"] == [], "the cap is consulted BEFORE the work, not after it"


def test_the_call_is_countable_as_an_external_call(wire, grant, monkeypatch):
    """A span alone leaves the cap plane blind — it reads session events, not spans.
    That gap is exactly what made VA-9's deliverable 5 read as instrumented while
    nothing could be metered."""
    import aughor.obs.session_log as slog
    seen: list[dict] = []
    real_emit = slog.emit

    def _capture(kind, **kw):
        if kind == slog.EXTERNAL_CALL:
            seen.append(kw)
        return real_emit(kind, **kw)

    monkeypatch.setattr(slog, "emit", _capture)
    wire["queue"].append((200, {"messages": []}))
    callmod.call_operation(grant.id, "gmail.messages.list")
    assert [e["name"] for e in seen] == ["google.gmail.messages.list"]
    assert seen[0]["ok"] is True
    assert seen[0]["payload"]["http_status"] == 200


def test_an_un_allowlisted_write_stops_and_a_read_does_not(wire, grant, slack_grant,
                                                           monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    wire["queue"].append((200, {"messages": []}))
    assert callmod.call_operation(grant.id, "gmail.messages.list").status == "executed", \
        "a read is audited and proceeds — the gate is for what CHANGES something"
    res = callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi"})
    # `needs_approval`, not `refused` — alone among the verdicts here it is a QUESTION a
    # person can answer, and the automation plane turns exactly this one into a durable
    # proposal and parks the run on them.
    assert res.status == "needs_approval" and "approval" in res.message.lower()
    assert len(wire["calls"]) == 1, "the refused write must never have been sent"


def test_allowlisting_the_write_for_this_grant_lets_it_through(wire, slack_grant,
                                                              monkeypatch):
    """Scoped to the GRANT, which is the grain a person reasons about: approving
    'this account may post to Slack' must not approve a second account's."""
    from aughor.govern import actions as govern

    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    govern.allow("integration.slack.slack.chat.postMessage", slack_grant.id,
                 actor="tester")
    wire["queue"].append((200, {"ok": True, "ts": "1.2", "channel": "C1"}))
    res = callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi"})
    assert res.status == "executed" and res.data == {"ts": "1.2", "channel": "C1"}

    other = store.save_connection(Connection(id="ic_slack2", provider="slack",
                                             scopes="chat:write", status="active"))
    assert callmod.call_operation(other.id, "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi"}).status == "needs_approval"


def test_every_call_lands_in_the_audit_ledger_naming_the_grants_owner(wire, monkeypatch):
    from aughor.govern import actions as govern

    store.save_connection(Connection(
        id="ic_owned", provider="google", user_id="u_amit",
        scopes="https://www.googleapis.com/auth/gmail.readonly", status="active"))
    wire["queue"].append((200, {"messages": []}))
    callmod.call_operation("ic_owned", "gmail.messages.list", actor="agent:a1")
    row = next(r for r in govern.recent_audit(50)
               if r.get("action") == "integration.google.gmail.messages.list")
    assert row["decision"] == "executed"
    assert "u_amit" in row["detail"], "whose consent was spent is what this row is for"
    assert row["scope"] == "ic_owned"


def test_a_human_accept_is_not_asked_to_pass_the_gate_again(wire, slack_grant,
                                                            monkeypatch):
    """The accept IS the approval. Asking again would refuse it forever — the proposal is
    not allowlisted, and nothing about a person saying yes makes it so."""
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    wire["queue"].append((200, {"ok": True, "ts": "1.2", "channel": "C1"}))
    res = callmod.call_operation(slack_grant.id, "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi"},
                                 actor="amit", approved=True)
    assert res.status == "executed"


def test_approving_bypasses_the_gate_and_nothing_else(wire, monkeypatch):
    """An approval is permission, not a promise that the world stood still: a proposal can
    sit for days and the account behind it can be revoked in the meantime."""
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    store.save_connection(Connection(id="ic_dead2", provider="slack", scopes="chat:write",
                                     status="revoked"))
    res = callmod.call_operation("ic_dead2", "slack.chat.postMessage",
                                 {"channel": "#x", "text": "hi"}, approved=True)
    assert res.status == "refused" and "revoked" in res.message
    assert wire["calls"] == []


def test_an_unknown_operation_is_a_refusal_not_a_crash(wire, grant):
    assert callmod.call_operation(grant.id, "gmail.messages.delete").status == "refused"
    assert callmod.call_operation("nope", "gmail.messages.list").status == "refused"
