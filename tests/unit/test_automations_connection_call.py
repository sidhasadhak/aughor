"""VA-11 consumer — the step that spends a user's grant, and the four ways it reports.

The wave's premise, measured on 2026-09-01 before a line was written: the vault was
BUILT and INERT — `broker.fresh_access_token()` had zero callers outside its own tests
and nothing but `routers/integrations.py` imported the package at all. §7's recurring
failure, verbatim: a plane complete, tested, and reaching nothing.

What is pinned here is the join between the two planes, because that is where a
plausible implementation goes quietly wrong:

* **Four refusals, four statuses.** A dead grant, a missing scope, an empty required
  param, a provider error and a usage cap are not one failure mode. A run canvas that
  spelled them all `failed` would send someone to check a provider that is fine.
* **The published set is OPEN, and that is what makes the chain possible.** One kind,
  many operation shapes — so `list the messages → for each → read it → post` is a chain
  this plane can express, and a closed set would have refused the fan-out at save.
* **The grant and the operation are NOT bindable.** Which credential a step spends is an
  authored decision; an upstream value choosing it would be a chain picking its own
  counterparty.
* **A step is refused at SAVE for naming an operation that does not exist**, like every
  other reference in this plane. K1: reject at parse, never surface.
"""
from __future__ import annotations

import pytest

from aughor.automations.dataflow import BINDABLE_FIELDS, PUBLISHED_KEYS, validate_chain
from aughor.automations.engine import _dispatch_connection_call
from aughor.automations.models import Automation, Condition, Effect
from aughor.integrations import call as callmod
from aughor.integrations import store as istore
from aughor.integrations.models import Connection

GMAIL_LIST = "google.gmail.messages.list"
GMAIL_GET = "google.gmail.messages.get"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@pytest.fixture(autouse=True)
def _virgin_stores():
    for s in (istore._APPS, istore._CONNS, istore._PENDING):
        for d in list(s.all()):
            s.delete(d["id"])
    yield


@pytest.fixture
def grant():
    return istore.save_connection(Connection(
        provider="google", user_id="u1", scopes=GMAIL_SCOPE,
        account="sales@example.com", access_token="at-1",
        expires_at="2099-01-01T00:00:00+00:00", status="active"))


def _step(grant_id, operation=GMAIL_LIST, alias="mail", **params) -> Effect:
    return Effect(kind="connection_call", alias=alias,
                  config={"grant_id": grant_id, "operation": operation,
                          "params": params or {}})


def _automation(*effects) -> Automation:
    return Automation(name="chain", conn_id="conn-1",
                      conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                      effects=list(effects))


#: The dispatcher reads only the automation's name and id, so any valid chain will do —
#: an automation with no effects is refused by the model, which is its own good law.
AUTO = _automation(Effect(kind="investigate", config={"question": "anything"}))


# ── the four statuses ─────────────────────────────────────────────────────────

def test_a_result_publishes_the_operations_keys_and_counts_what_came_back(grant, monkeypatch):
    monkeypatch.setattr(callmod, "_get", lambda url, token: (200, {
        "messages": [{"id": "m1", "threadId": "t1"}], "resultSizeEstimate": 1}))
    out = _dispatch_connection_call(_step(grant.id), AUTO)
    assert out.status == "executed"
    assert out.data["count"] == 1 and out.data["items"][0]["id"] == "m1"
    # The run row says what came back, not merely that something did.
    assert "1 result" in out.message


def test_a_dead_grant_is_a_dispatch_error_not_a_failure(grant):
    """`failed` licenses the retries this plane performs. Retrying a revoked grant is a
    schedule of identical refusals, which is the shape `dispatch_error` exists to stop."""
    dead = istore.save_connection(grant.model_copy(update={"status": "revoked"}))
    out = _dispatch_connection_call(_step(dead.id), AUTO)
    assert out.status == "dispatch_error"
    assert "revoked" in out.message


def test_a_missing_scope_names_the_scope_on_the_run_row(grant):
    narrowed = istore.save_connection(grant.model_copy(update={"scopes": "openid email"}))
    out = _dispatch_connection_call(_step(narrowed.id), AUTO)
    assert out.status == "dispatch_error"
    assert GMAIL_SCOPE in out.message


def test_a_bound_param_that_resolved_to_nothing_is_invalid_params(grant):
    """The distinction that matters on a canvas: this is the author's problem, and
    `invalid_params` is the status this plane already uses to say so.

    Constructed the way the ENGINE constructs it — a step authored with a binding, then
    `model_copy`d with the resolved config — because an empty literal cannot be authored
    at all (the save-time refusal below sees to that), and a test that could not happen
    in production proves the shape of nothing.
    """
    authored = Effect(kind="connection_call", alias="read",
                      config={"grant_id": grant.id, "operation": GMAIL_GET,
                              "params": {"message_id": {"$from": "inbox.id"}}})
    bound = authored.model_copy(update={"config": {
        **authored.config, "params": {"message_id": ""}}})
    out = _dispatch_connection_call(bound, AUTO)
    assert out.status == "invalid_params"
    assert "Message id" in out.message


def test_a_provider_error_is_a_failure_carrying_the_providers_words(grant, monkeypatch):
    monkeypatch.setattr(callmod, "_get",
                        lambda url, token: (503, {"error": {"message": "backendError"}}))
    out = _dispatch_connection_call(_step(grant.id), AUTO)
    assert out.status == "failed"
    assert "backendError" in out.message


def test_a_usage_cap_refuses_the_step_and_says_it_was_a_budget(grant, monkeypatch):
    """`govern.outbound` fails OPEN when it cannot read a cap and closed when one says
    block — so arriving here means a cap deliberately refused this call, and the run row
    must not read as a provider outage."""
    from aughor.govern import outbound

    def _blocked(org_id, user_id):
        class _D:
            allowed = False
            reason = "monthly external-call budget reached"
        return _D()

    monkeypatch.setattr(outbound, "_cap_decision", _blocked)
    monkeypatch.setattr(callmod, "_get", lambda url, token: (200, {}))
    out = _dispatch_connection_call(_step(grant.id), AUTO)
    assert out.status == "dispatch_error"
    assert "usage cap" in out.message and "budget reached" in out.message


# ── the plane's shape ─────────────────────────────────────────────────────────

def test_the_published_set_is_open_because_one_kind_carries_many_shapes():
    """A Gmail list publishes count/estimate/items; a single message publishes
    subject/sender/snippet. Those keys belong to the OPERATION, and this table is keyed
    by kind — so a closed set here could only be wrong for one of them."""
    assert PUBLISHED_KEYS["connection_call"] is None


def test_a_chain_may_fan_out_over_what_a_call_returned(grant):
    """The wave's own shape: list the messages, read each one. A CLOSED published set is
    refused as a `for_each` source (correctly — every closed one in this plane is
    strings), so the open set is what makes this expressible at all."""
    chain = [
        _step(grant.id, GMAIL_LIST, alias="inbox"),
        Effect(kind="connection_call", alias="each",
               for_each={"source": {"$from": "inbox.items"}},
               config={"grant_id": grant.id, "operation": GMAIL_GET,
                       "params": {"message_id": {"$from": "item.id"}}}),
    ]
    # Models, not dumps: `alias_for` reads the attribute, so a dumped chain would collapse
    # every alias to its position and refuse a sound design for the wrong reason.
    assert validate_chain(chain) is None


@pytest.mark.parametrize("field", ["grant_id", "operation"])
def test_the_credential_selector_may_not_be_bound(grant, field):
    """An upstream value choosing which credential a step spends would be a chain picking
    its own counterparty — and `BINDABLE_FIELDS` alone would not have stopped it.

    That table DECLARES the input ports; `resolve()` walks the whole config regardless, so
    every other kind in this plane substitutes bindings into fields its tuple omits. The
    gap is harmless on an org-scoped `bot_id` and has teeth on a credential, so this kind
    refuses it where a save actually fails.
    """
    assert BINDABLE_FIELDS["connection_call"] == ("params",)
    config = {"grant_id": grant.id, "operation": GMAIL_LIST,
              field: {"$from": "one.items"}}
    with pytest.raises(ValueError, match="must be written, not bound"):
        Effect(kind="connection_call", config=config)


def test_an_operation_this_build_does_not_declare_is_refused_at_save(grant):
    """A typo in an operation id is not a value that might work tomorrow — it is a step
    that can never run, and discovering that at 07:00 costs a morning."""
    with pytest.raises(ValueError, match="unknown operation"):
        Effect(kind="connection_call",
               config={"grant_id": grant.id, "operation": "google.gmail.messages.burn"})


def test_a_required_param_may_be_BOUND_at_save_but_not_absent(grant):
    """`{"$from": "inbox.id"}` is not a value yet and will not be one until the chain
    runs; demanding a literal would refuse exactly the chains this wave enables."""
    Effect(kind="connection_call",
           config={"grant_id": grant.id, "operation": GMAIL_GET,
                   "params": {"message_id": {"$from": "inbox.id"}}})
    with pytest.raises(ValueError, match="Message id"):
        Effect(kind="connection_call",
               config={"grant_id": grant.id, "operation": GMAIL_GET})


# ── the palette tells the truth about this deployment ─────────────────────────

@pytest.fixture
def as_u1(monkeypatch):
    """The palette answers "can *I* place this step", so it counts the BROWSING user's
    grants — `current_user_id()`, the same source `govern.outbound` attributes against."""
    from aughor.org import context
    monkeypatch.setattr(context, "current_user_id", lambda: "u1")
    yield


def _row():
    from aughor.automations.palette import entries
    return next(r for r in entries("conn-1") if r["kind"] == "connection_call")


def test_the_palette_dims_the_row_when_nobody_has_connected_an_account():
    row = _row()
    assert row["availability"] == "needs_setup"
    assert "connect one" in row["reason"].lower()


def test_a_revoked_grant_does_not_light_the_row(grant, as_u1):
    """A revoked row is still a row. Counting rows would light this entry on a
    deployment where every grant is dead — the palette's own law, broken quietly."""
    istore.save_connection(grant.model_copy(update={"status": "revoked"}))
    assert _row()["availability"] == "needs_setup"


def test_one_live_grant_lights_it(grant, as_u1):
    assert _row()["availability"] == "ready"


def test_another_users_grant_does_not_light_my_palette(grant):
    """`grant` belongs to u1 and the browsing user here is nobody. A palette that counted
    the whole org's grants would offer a step whose account the reader cannot reach."""
    assert _row()["availability"] == "needs_setup"
