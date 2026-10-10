"""Arc OC-6 — authority consulted where an action runs (D4), and its changes pushed to subscribers (D6).

The study found the L0–L5 ladder read only when widening and by autonomy: a person who capped an action at L2
("prepare") left it exactly as runnable as before, and a standing grant ran one unattended at any level. And the
graduations and demotions that change who may run what were listed as subscribable and only ever journaled.
"""
from __future__ import annotations

from aughor.actions import authority as A
from aughor.actions.executor import execute_kinetic_action
from tests.unit.test_action_authority import _action, _conn, _recorder


def test_a_cap_below_execute_refuses_the_run_approved_or_not_and_lifting_it_runs_it(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    conn, rec = _conn(), _recorder()
    A.set_ceiling("refund", conn, level=2, by="ana", why="prepare only, until finance signs off")
    capped = execute_kinetic_action(_action(), {"order_id": "1"}, actor="user:ana", scope=conn, dispatch=rec, approved=True)
    assert (capped.status, capped.http_status(), rec.calls) == ("authority_capped", 403, [])
    assert "L2 (prepare)" in capped.message and "prepare only, until finance signs off" in capped.message
    A.set_ceiling("refund", conn, level=None, by="ana")
    ran = execute_kinetic_action(_action(), {"order_id": "1"}, actor="user:ana", scope=conn, dispatch=rec, approved=True)
    assert ran.status == "executed" and rec.calls == [("refund", {"order_id": "1"})]


def test_a_cap_at_approval_runs_nothing_unattended_on_a_standing_grant(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")
    monkeypatch.setattr("aughor.actions.grants.standing_grant_id", lambda action, params, scope: "grant-1")
    conn, rec = _conn(), _recorder()
    ran = execute_kinetic_action(_action(), {"order_id": "2"}, actor="agent", scope=conn, dispatch=rec)
    assert (ran.status, ran.granted_by) == ("executed", "grant-1")           # a person's grant on this very target
    A.set_ceiling("refund", conn, level=3, by="ana", why="every refund waits for a person this quarter")
    held = execute_kinetic_action(_action(), {"order_id": "2"}, actor="agent", scope=conn, dispatch=rec)
    assert held.status == "approval_required" and len(rec.calls) == 1        # the grant is not honoured under the cap
    irreversible = execute_kinetic_action(_action(reversibility="irreversible", undo=None), {"order_id": "2"},
                                          actor="agent", scope=_conn(), dispatch=rec)
    assert irreversible.status == "approval_required" and len(rec.calls) == 1   # never passes L3, so never unattended


def test_an_unreadable_record_leaves_the_approval_gate_to_decide_alone(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    def broken(action, scope, **k):
        raise RuntimeError("ledger locked")
    monkeypatch.setattr(A, "level_for", broken)
    rec = _recorder()
    assert execute_kinetic_action(_action(), {"order_id": "3"}, actor="u", scope=_conn(), dispatch=rec,
                                  approved=True).status == "executed"


def test_a_demotion_reaches_the_people_subscribed_to_it(monkeypatch):
    pushed: list = []
    monkeypatch.setattr("aughor.record.subscriptions.notify",
                        lambda kind, payload, conn_id="": pushed.append((kind, payload["text"], conn_id)))
    conn = _conn()
    A.demote("refund", conn, why="verification failed after execution")
    assert pushed == [("authority.demoted", f"The action refund was demoted to L3 on {conn}: "
                                            "verification failed after execution", conn)]
