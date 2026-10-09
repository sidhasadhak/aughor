"""Arc OC-6 — a proposal carries the version of the action it proposes, and an execution books the one it ran under.

A proposal staged on Monday was accepted on Thursday against whatever the action declared on Thursday: a person
approved one thing, and another could run. Now an accept compares the pin with the action as it stands, refuses a
changed one with what changed, and runs nothing.
"""
from __future__ import annotations

from aughor.actions import inbox
from aughor.actions.pins import action_pin, changed_since
from aughor.ontology.models import SubmissionCriterion
from tests.unit.test_kinetic_inbox import _action, _proposal, flag_on, graph_of  # noqa: F401 — fixtures by name


def _dispatching(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr("aughor.actions.executor.default_dispatch",
                        lambda action, params, scope="": calls.append((action.id, dict(params))) or {"ok": True})
    return calls


def test_an_accept_runs_what_was_proposed_and_the_ledger_names_the_declaration_that_ran(flag_on, graph_of, monkeypatch):  # noqa: F811
    from aughor.actions.authority import executions
    action = _action()
    graph_of(action)
    calls = _dispatching(monkeypatch)
    staged = inbox.stage_proposal(_proposal(connection_id="pins-a"))
    pinned = staged.detail["action_pin"]
    assert pinned["hash"] == action_pin(action, "pins-a")["hash"]
    result, _ = inbox.accept_proposal(staged.id, actor="human")
    assert result.status == "executed" and calls == [("refund", {"order_id": "8821"})]
    assert executions("refund", "pins-a")[0]["action_pin"]["hash"] == pinned["hash"]


def test_an_action_changed_since_it_was_proposed_is_refused_on_accept_and_nothing_runs(flag_on, graph_of, monkeypatch):  # noqa: F811
    graph_of(_action())
    calls = _dispatching(monkeypatch)
    staged = inbox.stage_proposal(_proposal(connection_id="pins-b"))
    graph_of(_action(submission_criteria=[SubmissionCriterion(expr="order_id != '0'", message="no zero")]))
    result, _ = inbox.accept_proposal(staged.id, actor="human")
    assert (result.status, result.http_status(), calls) == ("action_changed", 409, [])
    assert "changed since it was proposed" in result.message and "propose it again" in result.message
    assert inbox.get_proposal(staged.id).status == "failed"


def test_a_proposal_older_than_pins_is_accepted_as_before():
    assert changed_since(None, {"hash": "x"}) == "" and changed_since({}, {"hash": "x"}) == ""
    assert changed_since({"hash": "a", "version": 3}, {"hash": "b", "version": 4}).startswith(
        "the action changed since it was proposed — proposed under version 3, it now reads version 4")
