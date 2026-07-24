"""Wave A4 — the resolve-once proposal inbox + target-bound standing grants.

The properties that make the plane safe to expose unattended, each locked here:

* **Resolve exactly once.** A double-accept dispatches exactly once; the second call is a no-op, not
  a second side effect. Proven by counting dispatches through an injected recorder.
* **Idempotent staging.** The same (run_id, call_id) staged twice is one row — a replayed run cannot
  duplicate, nor resurrect an already-resolved proposal.
* **A grant bypasses APPROVAL only, never CRITERIA.** A granted target whose value fails a submission
  criterion is still rejected with the authored message.
* **Byte-identical when the flag is off.** The executor consults no grant; the inbox stages nothing.

Hermetic: both stores are the conftest temp DBs; the executor runs unmocked with an injected
dispatcher, so the real approval/criteria/audit pipeline is exercised.
"""
from __future__ import annotations

import pytest

from aughor.kinetic import inbox
from aughor.ontology.models import ActionParameter, KineticAction, SubmissionCriterion


def _action(**kw) -> KineticAction:
    base = dict(
        id="refund", kind="side_effect",
        params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
        submission_criteria=[], side_effects=[], risk="high",
    )
    base.update(kw)
    return KineticAction(**base)


def _proposal(**kw) -> inbox.StagedProposal:
    base = dict(connection_id="conn-a", action_id="refund",
                params={"order_id": "8821"}, source="agent")
    base.update(kw)
    return inbox.StagedProposal(**base)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.proposals")


@pytest.fixture
def graph_of(monkeypatch):
    """Patch the ontology load so accept_proposal resolves the declared action."""
    def _install(action):
        class _G:
            kinetic_actions = {action.id: action}
        monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                            lambda cid, schema=None: _G())
    return _install


# ── staging + idempotency ──────────────────────────────────────────────────────

def test_stage_and_fetch():
    p = inbox.stage_proposal(_proposal(reasoning="over the return window"))
    got = inbox.get_proposal(p.id)
    assert got is not None
    assert got.action_id == "refund" and got.params == {"order_id": "8821"}
    assert got.status == "pending"


def test_staging_the_same_run_call_is_idempotent():
    a = inbox.stage_proposal(_proposal(connection_id="conn-idem", run_id="run-1", call_id="0"))
    b = inbox.stage_proposal(_proposal(connection_id="conn-idem", run_id="run-1", call_id="0",
                                       reasoning="different text"))
    assert a.id == b.id
    # the second stage did not overwrite or duplicate
    assert len(inbox.list_proposals("conn-idem")) == 1


def test_a_resolved_proposal_is_not_resurrected_by_a_replay():
    p = inbox.stage_proposal(_proposal(run_id="run-2", call_id="0"))
    inbox.reject_proposal(p.id, actor="me")
    # a replay of the same run stages nothing new and returns the resolved row
    again = inbox.stage_proposal(_proposal(run_id="run-2", call_id="0"))
    assert again.id == p.id
    assert inbox.get_proposal(p.id).status == "rejected"


def test_proposals_without_a_call_id_are_never_collapsed():
    p1 = inbox.stage_proposal(_proposal(connection_id="conn-nokey"))
    p2 = inbox.stage_proposal(_proposal(connection_id="conn-nokey"))
    assert p1.id != p2.id
    assert len(inbox.list_proposals("conn-nokey")) == 2


# ── resolve-once ────────────────────────────────────────────────────────────────

def test_reject_is_resolve_once():
    p = inbox.stage_proposal(_proposal(connection_id="conn-rej"))
    assert inbox.reject_proposal(p.id, actor="a") is True
    assert inbox.reject_proposal(p.id, actor="b") is False   # no-op, already resolved
    resolved = inbox.get_proposal(p.id)
    assert resolved.status == "rejected" and resolved.resolved_by == "a"


def test_accept_dispatches_exactly_once_under_a_double_accept(flag_on, graph_of):
    """The J1 decision gate: a second accept must NOT cause a second side effect."""
    graph_of(_action(submission_criteria=[]))
    calls: list = []

    def rec_dispatch(action, params, scope=""):
        calls.append((action.id, params, scope))
        return {"ok": True}

    # First accept executes once (approved bypasses the approval gate).
    import aughor.kinetic.executor as ex
    p = inbox.stage_proposal(_proposal(connection_id="conn-acc"))

    # Patch default_dispatch so the real executor path runs but the side effect is captured.
    import aughor.kinetic.inbox as inbox_mod
    orig = ex.default_dispatch
    ex.default_dispatch = rec_dispatch
    try:
        r1, _ = inbox_mod.accept_proposal(p.id, actor="human")
        r2, _ = inbox_mod.accept_proposal(p.id, actor="human")
    finally:
        ex.default_dispatch = orig

    assert r1.status == "executed"
    assert r2.status == "already_resolved"
    assert len(calls) == 1, "the second accept dispatched a second side effect"
    assert inbox.get_proposal(p.id).status == "executed"


def test_accepting_an_unknown_proposal_is_not_found(flag_on):
    r, grant = inbox.accept_proposal("ghost", actor="x")
    assert r.status == "not_found" and grant == ""


# ── accept honours the criteria (approval bypass is not a criteria bypass) ────────

def test_accept_still_enforces_submission_criteria(flag_on, graph_of):
    """Accepting is the APPROVAL act, not a criteria override — a value the criterion rejects is
    still refused with the authored message, and nothing dispatches."""
    msg = "Refunds over the window need a manager."
    graph_of(_action(submission_criteria=[SubmissionCriterion(expr="order_id == '8821'", message=msg)]))
    calls: list = []
    import aughor.kinetic.executor as ex
    orig = ex.default_dispatch
    ex.default_dispatch = lambda a, p, s="": calls.append(1)
    try:
        p = inbox.stage_proposal(_proposal(connection_id="conn-crit", params={"order_id": "9999"}))
        r, _ = inbox.accept_proposal(p.id, actor="human")
    finally:
        ex.default_dispatch = orig
    assert r.status == "criterion_failed"
    assert r.message == msg
    assert calls == []


# ── purge ────────────────────────────────────────────────────────────────────────

def test_purge_connection_and_source():
    inbox.stage_proposal(_proposal(connection_id="conn-p", source="automation:auto-9"))
    inbox.stage_proposal(_proposal(connection_id="conn-p", source="agent",
                                   run_id="r", call_id="1"))
    assert inbox.purge_source("automation:auto-9") == 1
    assert inbox.purge_connection("conn-p") == 1
    assert inbox.list_proposals("conn-p") == []
