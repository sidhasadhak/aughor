"""DS-11 — an integration as a step: the vault, consumed by a chain.

The receipt this wave is measured against is one sentence: *a chain reads Gmail under
the user's own grant and posts to Slack, every hop attributed, capped and audited.* What
is pinned here is that sentence and the four things a plausible implementation gets
wrong on the way to it:

* **The published keys are the OPERATION's, not the kind's.** Every effect kind before
  this one published the same keys on every instance, so a table keyed by kind WAS the
  answer. An integration step's keys are its operation's — which means B1's unknown-key
  refusal finally reaches a remote call, where the declared-action kind's open-set
  treatment has to accept anything.
* **A closed set may now contain a LIST.** W2's premise — measured, and true when it was
  measured — was that *nothing in this plane publishes a list*, so its rule could be
  written as "open set ⇒ fannable". A remote read is the first honest list, and fanning
  over `items` must work while fanning over `snippet` must still be refused at save.
* **A refusal is terminal, a cap is not.** An unknown operation, a dead grant and an
  un-allowlisted write all refuse identically on the next attempt, so they are
  ``dispatch_error``; a usage cap sent nothing, so its call is legitimate later and is
  ``failed``. Retrying a refusal is the #200 lesson repeated.
* **The step names both halves of what it spent.** ``<grant>:<operation>`` — two steps
  spending two different accounts must not read identically in a run history, which is
  the one question that history exists to answer.
"""
from __future__ import annotations

import pytest

from aughor.automations.dataflow import (
    list_published_keys, published_keys, validate_chain,
)
from aughor.automations.engine import _dispatch_integration, run_automation
from aughor.automations.models import Automation, Condition, Effect, EffectOutcome
from aughor.automations.store import upsert_automation
from aughor.integrations import call as callmod
from aughor.integrations import store as istore
from aughor.integrations.models import Connection


@pytest.fixture(autouse=True)
def _virgin_stores():
    """Cleaned both ways: the integration stores are session-scoped tmp files, so a grant
    left behind here turns up as an extra row in another file's registry assertions."""
    for s in (istore._APPS, istore._CONNS, istore._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])
    yield
    for s in (istore._APPS, istore._CONNS, istore._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])


@pytest.fixture
def grants():
    istore.save_connection(Connection(
        id="ic_g", provider="google", account="sales@example.com",
        scopes="https://www.googleapis.com/auth/gmail.readonly", status="active"))
    istore.save_connection(Connection(
        id="ic_s", provider="slack", account="Acme", scopes="chat:write",
        status="active"))


@pytest.fixture
def wire(monkeypatch):
    calls: list[dict] = []
    queue: list[tuple[int, object]] = []

    def _fake_request(method, url, *, headers, query, body):
        calls.append({"url": url, "query": dict(query or {}), "body": dict(body or {})})
        return queue.pop(0) if queue else (200, {})

    monkeypatch.setattr(callmod, "_request", _fake_request)
    monkeypatch.setattr(callmod, "_fresh_token", lambda cid: f"token-for-{cid}")
    return {"calls": calls, "queue": queue}


def _read(alias="inbox", conn="ic_g", **params) -> Effect:
    return Effect(kind="integration_call", alias=alias,
                  config={"connection_id": conn, "operation": "gmail.messages.list",
                          "params": params})


def _automation(*effects, **kw) -> Automation:
    return upsert_automation(Automation(
        name="chain", conn_id="conn-int",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=list(effects), max_retries=0, **kw))


class Dispatcher:
    """Stubs the leaves and delegates `integration_call` to the REAL dispatcher — the
    same split `test_automations_subchain.py` makes, and for its reason: an injected
    dispatcher replaces the whole table, so answering the kind under test here would
    exercise nothing this wave wrote."""

    def __init__(self):
        self.posted: list[dict] = []

    def __call__(self, effect, automation) -> EffectOutcome:
        if effect.kind == "integration_call":
            return _dispatch_integration(effect, automation)
        self.posted.append(dict(effect.config))
        return EffectOutcome(kind=effect.kind, target=effect.alias, status="executed",
                             data={"ts": "1.1", "channel": "C1"})


def _run(automation, dispatch):
    return run_automation(automation, dispatch=dispatch, persist=True,
                          probe=lambda *a, **k: True,
                          sleeper=lambda _s: None, rng=lambda: 0.0)


# ── the receipt ─────────────────────────────────────────────────────────────────

def test_a_chain_reads_gmail_under_the_grant_and_posts_what_it_found(grants, wire):
    """The wave's own sentence, end to end: the read runs under the user's token, its
    output is what the post says, and both hops are on one run."""
    wire["queue"].append((200, {"messages": [{"id": "m1", "threadId": "t1"},
                                             {"id": "m2", "threadId": "t2"}]}))
    chain = _automation(
        _read(q="is:unread newer_than:1d"),
        Effect(kind="slack_post", alias="tell",
               config={"bot_id": "sb_1", "channel": "C1",
                       "message": {"$from": "inbox.count"}}))
    d = Dispatcher()

    run = _run(chain, d)

    assert run.outcome == "fired"
    assert [o.status for o in run.effects] == ["executed", "executed"]
    assert run.effects[0].target == "ic_g:gmail.messages.list"
    assert run.effects[0].data == {"items": [{"id": "m1", "threadId": "t1"},
                                             {"id": "m2", "threadId": "t2"}],
                                   "count": 2, "next_page_token": ""}
    assert d.posted[0]["message"] == 2, "the post said what the read found"
    assert wire["calls"][0]["query"] == {"q": "is:unread newer_than:1d", "maxResults": 10}


def test_the_step_names_the_grant_it_spent_not_only_the_operation(grants, wire):
    """DS-8's live run found the general shape of this: a dispatcher that names its
    target after what it dispatched publishes the step's context where no binding can
    reach it. Two grants, one operation, two distinguishable rows."""
    istore.save_connection(Connection(id="ic_g2", provider="google",
                                      account="ops@example.com",
                                      scopes="https://www.googleapis.com/auth/gmail.readonly",
                                      status="active"))
    wire["queue"] += [(200, {"messages": []}), (200, {"messages": []})]
    run = _run(_automation(_read(alias="a"), _read(alias="b", conn="ic_g2")), Dispatcher())
    assert [o.target for o in run.effects] == ["ic_g:gmail.messages.list",
                                              "ic_g2:gmail.messages.list"]
    assert [c["url"] for c in wire["calls"]].count(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages") == 2


# ── per-operation ports: B1 reaches a remote call ───────────────────────────────

def test_what_a_step_publishes_is_its_operations_not_its_kinds():
    listing = _read()
    reading = Effect(kind="integration_call", alias="one",
                     config={"connection_id": "ic_g", "operation": "gmail.messages.get",
                             "params": {"id": "m1"}})
    assert published_keys(listing) == ("items", "count", "next_page_token")
    assert published_keys(reading) == ("id", "thread_id", "snippet")
    assert list_published_keys(listing) == ("items",)
    assert list_published_keys(reading) == ()


def test_an_unknown_key_on_an_integration_step_is_refused_at_save():
    problem = validate_chain([
        _read(),
        Effect(kind="slack_post", alias="tell",
               config={"bot_id": "b", "channel": "C1",
                       "message": {"$from": "inbox.snippet"}}),
    ])
    assert problem and "has no 'snippet'" in problem


def test_an_unknown_operation_is_refused_at_save_naming_what_exists():
    problem = validate_chain([Effect(kind="integration_call", alias="x",
                                     config={"connection_id": "ic_g",
                                             "operation": "gmail.messages.delete"})])
    assert problem and "gmail.messages.delete" in problem
    assert "gmail.messages.list" in problem, "the refusal names the closed set"


def test_an_undeclared_input_is_refused_at_save_not_at_nine_am():
    problem = validate_chain([Effect(kind="integration_call", alias="x",
                                     config={"connection_id": "ic_s",
                                             "operation": "slack.chat.postMessage",
                                             "params": {"channel": "#x", "text": "hi",
                                                        "cc": "boss"}})])
    assert problem and "'cc'" in problem


def test_both_config_keys_are_required_at_construction():
    with pytest.raises(ValueError):
        Effect(kind="integration_call", config={"connection_id": "ic_g"})
    with pytest.raises(ValueError):
        Effect(kind="integration_call", config={"operation": "gmail.messages.list"})


# ── the first list this plane ever published ────────────────────────────────────

def test_a_chain_fans_out_over_what_a_remote_read_returned(grants, wire):
    """W2 said it plainly: *nothing in this plane publishes a list*, so a fan source
    could only be a literal list or a binding onto the one open-set kind. This is the
    first closed set with a list in it, and the fan must work over that key."""
    wire["queue"].append((200, {"messages": [{"id": "m1", "threadId": "t1"},
                                             {"id": "m2", "threadId": "t2"}]}))
    chain = _automation(
        _read(),
        Effect(kind="slack_post", alias="tell",
               config={"bot_id": "sb_1", "channel": "C1",
                       "message": {"$from": "item.id"}},
               for_each={"source": {"$from": "inbox.items"}}))
    d = Dispatcher()

    run = _run(chain, d)

    assert [c["message"] for c in d.posted] == ["m1", "m2"], "one dispatch per item"
    assert [o.fan_index for o in run.effects[1:]] == [1, 2]


def test_fanning_over_a_scalar_key_is_still_refused_at_save():
    """The other half of the same rule. `count` is in the closed set and is not a list;
    an open set would have let this through."""
    problem = validate_chain([
        _read(),
        Effect(kind="slack_post", alias="tell",
               config={"bot_id": "b", "channel": "C1", "message": "x"},
               for_each={"source": {"$from": "inbox.count"}}),
    ])
    assert problem and "only items is a list" in problem


# ── refusals: terminal, and told apart from a budget ────────────────────────────

def test_a_dead_grant_makes_the_step_terminal_not_retriable(wire):
    istore.save_connection(Connection(id="ic_dead", provider="google", status="revoked"))
    run = _run(_automation(_read(conn="ic_dead")), Dispatcher())
    outcome = run.effects[0]
    assert outcome.status == "dispatch_error", "a verdict is not retried"
    assert outcome.attempts == 1
    assert "revoked" in outcome.message


def test_a_usage_cap_leaves_the_step_retriable(grants, wire, monkeypatch):
    from aughor.govern import outbound

    class _Decision:
        allowed = False
        reason = "monthly call budget reached"

    monkeypatch.setattr(outbound, "_cap_decision", lambda org, user: _Decision())
    run = _run(_automation(_read()), Dispatcher())
    assert run.effects[0].status == "failed", "nothing was sent — later is legitimate"
    assert wire["calls"] == []


def test_a_step_that_failed_publishes_nothing(grants, wire):
    wire["queue"].append((403, {"error": {"message": "Insufficient Permission"}}))
    run = _run(_automation(_read()), Dispatcher())
    assert run.effects[0].status == "failed"
    assert run.effects[0].data == {}


def test_a_dependent_step_skips_when_the_read_never_published(grants, wire):
    """The path that already existed: an unresolved binding skips the dependent rather
    than running it with a hole in its params."""
    wire["queue"].append((500, {"error": "backend error"}))
    chain = _automation(
        _read(),
        Effect(kind="slack_post", alias="tell",
               config={"bot_id": "sb_1", "channel": "C1",
                       "message": {"$from": "inbox.count"}}))
    d = Dispatcher()

    run = _run(chain, d)

    assert [o.status for o in run.effects] == ["failed", "skipped"]
    assert d.posted == [], "nothing was posted about a read that did not happen"


# ── the preview ─────────────────────────────────────────────────────────────────

def test_a_dry_run_previews_the_operations_own_keys(grants, wire):
    """B2's own pre-check found this exact failure once: a preview whose upstream
    published nothing reported a working chain as broken."""
    chain = _automation(
        _read(),
        Effect(kind="slack_post", alias="tell",
               config={"bot_id": "sb_1", "channel": "C1",
                       "message": {"$from": "inbox.count"}}))
    run = run_automation(chain, dry_run=True, persist=False,
                         probe=lambda *a, **k: True,
                         sleeper=lambda _s: None, rng=lambda: 0.0)
    assert run.effects[0].data["count"] == "«inbox.count»"
    assert wire["calls"] == [], "a preview dispatches nothing"


# ── the canvas ──────────────────────────────────────────────────────────────────

def test_two_integration_steps_do_not_draw_as_the_same_node():
    """Found by drawing it: a chain that read Gmail and posted to Slack rendered as two
    nodes both labelled "Use an integration", with nothing on either to say which. The
    operation is what tells them apart — and it is safe to put on a picture BY
    CONSTRUCTION, because it is an id from the closed roster rather than authored text."""
    from aughor.automations.graph import build_graph

    chain = _automation(
        _read(alias="inbox"),
        Effect(kind="integration_call", alias="tell",
               config={"connection_id": "ic_s", "operation": "slack.chat.postMessage",
                       "params": {"channel": "#revenue", "text": {"$from": "inbox.count"}}}))
    nodes = {n["id"]: n for n in build_graph(chain)["nodes"]}
    assert nodes["inbox"]["detail"] == "gmail.messages.list"
    assert nodes["tell"]["detail"] == "slack.chat.postMessage"


def test_the_node_face_never_carries_the_account_or_the_message():
    """The allowlist's own rule. An account's email address on a picture that is read on
    screen and exported is the spill this labeller exists to prevent, and a message body
    is the other half of it."""
    from aughor.automations.graph import build_graph

    chain = _automation(Effect(
        kind="integration_call", alias="tell",
        config={"connection_id": "ic_s", "operation": "slack.chat.postMessage",
                "params": {"channel": "#revenue", "text": "quarterly numbers, internal"}}))
    blob = str(build_graph(chain))
    assert "quarterly numbers, internal" not in blob
    assert "ic_s" not in blob


def test_a_binding_into_params_still_draws_as_a_data_edge():
    """`BINDABLE_FIELDS` names `params`, so the reference lives one level down. An edge
    the engine follows and the canvas does not draw is a picture that under-claims — the
    mirror of the failure this module exists to prevent."""
    from aughor.automations.graph import build_graph, data_edges_only

    chain = _automation(
        _read(alias="inbox"),
        Effect(kind="integration_call", alias="tell",
               config={"connection_id": "ic_s", "operation": "slack.chat.postMessage",
                       "params": {"channel": "#revenue", "text": {"$from": "inbox.count"}}}))
    edges = data_edges_only(build_graph(chain))
    assert [(e["from"], e["to"], e["label"]) for e in edges] == [("inbox", "tell", "count")]


# ── DS-11's completion · the write parks on a human ─────────────────────────────
#
# The gap the first half left, stated as its own section. A write the graduated gate
# refuses is the ONE verdict here a person can answer, and before this it was reported as
# a terminal error on a run that walked on — the exact shape DS-8 was built to end, one
# effect kind over.

def _post(alias="tell", **params) -> Effect:
    return Effect(kind="integration_call", alias=alias,
                  config={"connection_id": "ic_s", "operation": "slack.chat.postMessage",
                          "params": {"channel": "#revenue", "text": "hi", **params}})


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")


def _proposals(run_id):
    from aughor.actions.inbox import proposals_for_run
    return proposals_for_run(run_id)


def test_a_gated_write_parks_the_run_instead_of_failing_it(grants, wire, gate_on):
    from aughor.automations.store import get_run

    run = _run(_automation(_read(alias="inbox"), _post()), Dispatcher())

    assert run.outcome == "paused", "a question a person can answer is not a failure"
    assert run.finished_at is None, "a parked run has not finished"
    assert [o.status for o in run.effects] == ["executed", "approval_required"]
    staged = _proposals(run.id)
    assert len(staged) == 1
    assert staged[0].kind == "integration"
    assert staged[0].grant_id == "ic_s", "the proposal names WHOSE consent it would spend"
    assert staged[0].action_id == "slack.chat.postMessage"
    assert staged[0].connection_id == "conn-int", \
        "the WAREHOUSE connection — what the inbox filters and purges by"
    assert staged[0].params == {"channel": "#revenue", "text": "hi"}
    assert get_run(run.id).outcome == "paused"


def test_the_params_frozen_on_the_proposal_are_the_RESOLVED_ones(grants, wire, gate_on):
    """RC-3's rule: freezing `{"$from": …}` would freeze a reference whose meaning moves,
    not a value a human can weigh."""
    wire["queue"].append((200, {"messages": [{"id": "m1"}, {"id": "m2"}]}))
    run = _run(_automation(_read(alias="inbox"),
                           _post(text={"$from": "inbox.count"})), Dispatcher())
    assert _proposals(run.id)[0].params["text"] == 2


def test_accepting_it_performs_the_write_and_resumes_the_same_run(grants, wire, gate_on):
    from aughor.actions.inbox import accept_proposal
    from aughor.automations.engine import resume_run

    wire["queue"].append((200, {"messages": [{"id": "m1"}]}))
    parked = _run(_automation(_read(alias="inbox"), _post()), Dispatcher())
    assert parked.outcome == "paused"
    sent_before = len(wire["calls"])

    wire["queue"].append((200, {"ok": True, "ts": "17.1", "channel": "C9"}))
    result, _grant = accept_proposal(_proposals(parked.id)[0].id, actor="amit")
    assert result.ok, result.message
    assert len(wire["calls"]) == sent_before + 1, "the accept IS what sent it"

    resumed = resume_run(parked.id, dispatch=Dispatcher())
    assert resumed is not None
    assert resumed.id == parked.id, "one run, one trace — a human in its middle"
    assert resumed.outcome == "fired"
    assert [o.status for o in resumed.effects] == ["executed", "executed"]
    assert resumed.effects[1].data == {"ts": "17.1", "channel": "C9"}, \
        "the resumed step publishes what the approved write actually returned"


def test_the_accept_does_not_ask_the_gate_a_second_time(grants, wire, gate_on):
    """The human's accept IS the approval. Asking again would refuse it forever — the
    proposal is not allowlisted, and nothing about accepting it makes it so."""
    from aughor.actions.inbox import accept_proposal

    parked = _run(_automation(_post()), Dispatcher())
    wire["queue"].append((200, {"ok": True, "ts": "1.1", "channel": "C1"}))
    result, _ = accept_proposal(_proposals(parked.id)[0].id, actor="amit")
    assert result.status == "executed"


def test_the_accept_still_re_asks_everything_that_is_not_the_gate(grants, wire, gate_on):
    """An approval is permission, not a promise that the world stood still: a proposal can
    sit for days and the account behind it can be revoked in the meantime."""
    from aughor.actions.inbox import accept_proposal
    from aughor.integrations.models import Connection

    parked = _run(_automation(_post()), Dispatcher())
    istore.save_connection(Connection(id="ic_s", provider="slack", scopes="chat:write",
                                      status="revoked"))
    result, _ = accept_proposal(_proposals(parked.id)[0].id, actor="amit")
    assert not result.ok and "revoked" in result.message
    assert wire["calls"] == [], "a revoked grant is not spent because a human said yes"


def test_rejecting_it_skips_the_step_and_the_chain_finishes(grants, wire, gate_on):
    from aughor.actions.inbox import reject_proposal
    from aughor.automations.engine import resume_run

    wire["queue"].append((200, {"messages": []}))
    parked = _run(_automation(_read(alias="inbox"), _post()), Dispatcher())
    reject_proposal(_proposals(parked.id)[0].id, actor="amit")

    resumed = resume_run(parked.id, dispatch=Dispatcher())
    assert resumed.outcome == "fired"
    assert [o.status for o in resumed.effects] == ["executed", "skipped"]
    assert wire["calls"] == [c for c in wire["calls"] if "slack" not in c["url"]]


def test_a_read_never_parks(grants, wire, gate_on):
    """The gate is for what CHANGES something. A read that stopped for a human would make
    every scheduled chain a queue of approvals nobody asked for."""
    wire["queue"].append((200, {"messages": []}))
    run = _run(_automation(_read()), Dispatcher())
    assert run.outcome == "fired" and _proposals(run.id) == []


def test_an_allowlisted_write_does_not_park_at_all(grants, wire, gate_on):
    from aughor.govern import actions as govern

    action = "integration.slack.slack.chat.postMessage"
    govern.allow(action, "ic_s", actor="amit")
    try:
        wire["queue"].append((200, {"ok": True, "ts": "1.1", "channel": "C1"}))
        run = _run(_automation(_post()), Dispatcher())
        assert run.outcome == "fired"
        assert _proposals(run.id) == [], "a standing approval is not a question"
    finally:
        # The allowlist is org-scoped LEDGER state, not a fixture: left behind, it makes
        # every later test in this file describe a deployment where this write is already
        # approved — which is how a test that proves the pause silently stops proving it.
        govern.revoke(action, "ic_s")


def test_an_accepted_write_whose_transport_broke_is_uncertain_not_executed(
        grants, wire, gate_on, monkeypatch):
    """One approved post becoming two is what this status exists to prevent, and the
    resumed run has to carry the word rather than flatten it to `failed`."""
    from aughor.actions.inbox import accept_proposal, get_proposal
    from aughor.automations.engine import resume_run

    parked = _run(_automation(_post()), Dispatcher())
    pid = _proposals(parked.id)[0].id

    def _boom(*a, **k):
        raise ConnectionError("connection reset")
    monkeypatch.setattr(callmod, "_request", _boom)
    accept_proposal(pid, actor="amit")
    assert get_proposal(pid).status == "uncertain"

    resumed = resume_run(parked.id, dispatch=Dispatcher())
    assert resumed.effects[0].status == "uncertain"
