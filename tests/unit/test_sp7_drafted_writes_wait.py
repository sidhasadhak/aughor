"""SP-7 (§3.11, the second movement) — a write drafted from a sentence waits for a person.

The approval switch (`AUGHOR_ACTION_APPROVAL`) is off by default, and with it off a declared
write inside an armed chain runs unattended: the one kind of step a model could draft that
changes the world with nobody looking. A chain a person builds by hand stays that person's
decision; a chain a model drafts marks each declared write, and the executor asks a person on
every run whatever the switch says. A human accept, or a standing grant — a person's prior
approval of that exact target — still satisfies it.

Every hit of the retired word in this file is a frozen identifier: the declared-action kind
literal, the executor's function and its model class. That is why the vocabulary ratchet
exempts this path rather than counting it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.actions.executor import execute_kinetic_action
from aughor.automations.models import Automation, Condition, Effect
from aughor.automations.propose import ProposedChain, propose_chain
from aughor.ontology.models import ActionParameter, KineticAction, SideEffect

CONN = "sp7-writes"


def _action() -> KineticAction:
    return KineticAction(
        id="flag_order", kind="side_effect",
        params=[ActionParameter(name="amount", data_type="NUMERIC", required=True)],
        side_effects=[SideEffect(kind="webhook", config={"url": "https://hooks.example.com/x"})],
        risk="high")


def _recorder():
    calls: list = []

    def dispatch(action, params, scope=""):
        calls.append((action.id, dict(params)))
        return {"dispatched": True}

    dispatch.calls = calls
    return dispatch


@pytest.fixture(autouse=True)
def _switch_off(monkeypatch):
    """The deployment default — exactly when a drafted write used to run unattended."""
    monkeypatch.delenv("AUGHOR_ACTION_APPROVAL", raising=False)


# ── the executor ──────────────────────────────────────────────────────────────────────

def test_with_the_switch_off_an_unmarked_write_still_runs():
    """The control: a chain a person built by hand behaves exactly as before."""
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 5}, scope=CONN, dispatch=d)
    assert r.status == "executed" and len(d.calls) == 1


def test_a_drafted_write_asks_a_person_whatever_the_switch_says():
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 5}, scope=CONN, dispatch=d,
                               require_approval=True)
    assert r.status == "approval_required" and r.ok is False
    assert "waits for a person on every run" in r.message
    assert d.calls == []                                   # nothing was dispatched


def test_a_person_accepting_it_runs_it():
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 5}, scope=CONN, dispatch=d,
                               require_approval=True, approved=True)
    assert r.status == "executed" and len(d.calls) == 1


def test_a_standing_grant_still_satisfies_it(monkeypatch):
    monkeypatch.setattr("aughor.actions.grants.standing_grant_id",
                        lambda action, params, scope: "grant-1")
    d = _recorder()
    r = execute_kinetic_action(_action(), {"amount": 5}, scope=CONN, dispatch=d,
                               require_approval=True)
    assert r.status == "executed" and len(d.calls) == 1


# ── the engine passes a step's mark ───────────────────────────────────────────────────

@pytest.mark.parametrize("marked", [True, False])
def test_the_engine_passes_a_steps_mark_to_the_executor(monkeypatch, marked):
    import aughor.automations.engine as engine

    seen: dict = {}

    def spy(action, params, **kwargs):
        seen.update(kwargs)
        held = bool(kwargs.get("require_approval"))
        return SimpleNamespace(status="approval_required" if held else "executed",
                               message="", outcome={})

    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda conn_id, schema_name=None: SimpleNamespace(
                            kinetic_actions={"flag_order": _action()}, schema_name="s"))
    monkeypatch.setattr("aughor.actions.executor.execute_kinetic_action", spy)
    config = {"action_id": "flag_order", "params": {"amount": 5}}
    if marked:
        config["require_approval"] = True
    effect = Effect(kind="kinetic_action", config=config)
    automation = Automation(conn_id=CONN, name="held",
                            conditions=[Condition(kind="schedule", config={"cron": "0 9 * * *"})],
                            effects=[effect])

    outcome = engine._dispatch_kinetic(effect, automation)
    assert seen["require_approval"] is marked
    assert outcome.status == ("approval_required" if marked else "executed")


# ── the drafter marks what it drafts ──────────────────────────────────────────────────

class _Provider:
    """The model, scripted — nothing here spends a token."""

    def __init__(self, draft):
        self.draft = draft

    def complete(self, *, system, user, response_model, temperature=0.0):
        return self.draft


def test_a_drafted_declared_write_is_marked_and_the_person_is_told():
    chain = ProposedChain(
        name="Flag late orders",
        conditions=[{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
        effects=[{"kind": "kinetic_action", "alias": "flag",
                  "config": {"action_id": "flag_order", "params": {"amount": 5}}}])
    out = propose_chain("flag late orders every morning", conn_id=CONN, provider=_Provider(chain))
    assert out.verdict == "proposed", out.reason
    assert out.draft["effects"][0]["config"]["require_approval"] is True
    assert out.notes.startswith("Action 1 waits for a person on every run")
