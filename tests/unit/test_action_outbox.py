"""Arc OC-6 — the outbox: a declared action's calls kept as rows, delivered under a lease, retried by cause, and an
unknown one checked by the action's own verification read before anything is sent again.

The executor runs for real (approval off); the far end is a stand-in `dispatch_effect` that answers what each test
needs, and the action's check is a stand-in `verify` — so each property is held without a network: a call that did
not go out goes again later; one that got no answer is never sent blind; one the far end refused is never sent again
by itself; two workers never hold one row; and with the flag off nothing changes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aughor.actions import outbox
from aughor.actions.authority import executions
from aughor.actions.executor import KineticDispatchError, execute_kinetic_action
from aughor.ontology.models import ActionParameter, KineticAction, Verification

LATER = datetime.now(timezone.utc) + timedelta(hours=2)


def _carrier(**change) -> KineticAction:
    base = dict(id="open_claim", kind="side_effect", risk="low", reversibility="irreversible",
                params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
                side_effects=[{"kind": "http", "config": {"url": "https://carrier.example/claims"}}],
                verification=Verification(sql="SELECT 1 FROM claims WHERE order_id = '{order_id}'", expects="rows"))
    base.update(change)
    return KineticAction(**base)


@pytest.fixture(autouse=True)
def _empty_outbox():
    """The worker reads every connection's due calls, so each test starts from an empty outbox."""
    c = outbox._conn()
    try:
        c.execute("DELETE FROM action_outbox")
        c.commit()
    finally:
        c.close()


@pytest.fixture
def far_end(monkeypatch):
    """The carrier, stood in: each call answers the next item of ``answers`` — a dict, or an exception to raise."""
    state = {"answers": [], "calls": 0, "check": "passed"}

    def dispatch(se, action, params, scope=""):
        state["calls"] += 1
        answer = state["answers"].pop(0) if state["answers"] else {"kind": se.kind, "http_status": 200, "ok": True}
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("aughor.actions.executor.dispatch_effect", dispatch)
    monkeypatch.setattr("aughor.actions.authority.verify",
                        lambda action, params, scope, **k: {"status": state["check"], "why": f"check {state['check']}"})
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    return state


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "actions.outbox")


def _press(conn: str, action: KineticAction | None = None):
    return execute_kinetic_action(action or _carrier(), {"order_id": "O-7"}, actor="ana", scope=conn, approved=True)


def test_off_a_call_goes_out_once_inline_as_before_and_nothing_is_kept(far_end, monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    r = _press("ob-off")
    assert r.status == "executed" and far_end["calls"] == 1 and "outbox" not in r.outcome
    assert outbox.list_sends("ob-off") == []


def test_a_call_delivered_in_the_press_is_checked_at_once(far_end, on):
    r = _press("ob-1")
    assert r.status == "executed" and r.verification["status"] == "passed"
    [send] = outbox.list_sends("ob-1")
    assert (send.status, send.attempts, send.entry) == ("delivered", 1, "")


def test_a_call_that_did_not_go_out_goes_again_later_and_its_check_is_booked_when_it_lands(far_end, on):
    far_end["answers"] = [KineticDispatchError("refused connection", cause="not_delivered")]
    r = _press("ob-2")
    assert r.status == "executed" and r.verification["status"] == "pending"
    [send] = outbox.list_sends("ob-2")
    assert (send.status, send.cause, send.attempts, send.entry) == ("queued", "not_delivered", 1, r.action_entry)
    assert outbox.work_once("w1") == []                                   # not due yet: a pause before the next attempt
    [done] = outbox.work_once("w1", now=LATER)
    assert (done.status, done.attempts, far_end["calls"]) == ("delivered", 2, 2)
    assert executions("open_claim", "ob-2")[0]["verification"]["status"] == "passed"   # booked on the entry


def test_a_call_with_no_answer_is_checked_before_anything_is_sent_again(far_end, on):
    far_end["answers"] = [KineticDispatchError("read timeout", cause="unknown")]
    _press("ob-3")
    [send] = outbox.list_sends("ob-3")
    assert send.status == "unknown"
    [done] = outbox.work_once("w1", now=LATER)
    assert done.status == "delivered" and "nothing was sent again" in done.reconciled
    assert far_end["calls"] == 1                                          # the check found it: never sent twice


def test_an_unknown_call_its_check_does_not_find_is_sent_again_and_one_it_cannot_say_waits_for_a_person(far_end, on):
    far_end["answers"] = [KineticDispatchError("read timeout", cause="unknown")]
    _press("ob-4")
    far_end["check"] = "failed"
    [again] = outbox.work_once("w1", now=LATER)
    assert again.status == "delivered" and far_end["calls"] == 2 and again.attempts == 2
    far_end.update(answers=[KineticDispatchError("read timeout", cause="unknown")], check="unavailable")
    _press("ob-5")
    [held] = outbox.work_once("w1", now=LATER)
    assert held.status == "dead" and "a person decides" in held.last_error and far_end["calls"] == 3


@pytest.mark.parametrize("answer, status, cause", [
    ({"kind": "http", "http_status": 422, "ok": False}, "dead", "refused"),
    ({"kind": "http", "http_status": 503, "ok": False}, "queued", "server_error"),
    ({"kind": "http", "http_status": 429, "ok": False}, "queued", "rate_limited"),
    (KineticDispatchError("SSRF guard", cause="refused"), "dead", "refused"),
])
def test_what_happens_next_follows_why_the_call_failed(far_end, on, answer, status, cause):
    far_end["answers"] = [answer]
    _press("ob-6")
    [send] = outbox.list_sends("ob-6")
    assert (send.status, send.cause) == (status, cause)
    if cause == "rate_limited":
        wait = datetime.fromisoformat(send.next_at) - datetime.fromisoformat(send.updated_at)
        assert wait >= timedelta(seconds=60)


def test_a_call_out_of_attempts_waits_for_a_person_who_may_send_it_again_or_leave_it(far_end, on):
    far_end["answers"] = [KineticDispatchError("refused", cause="not_delivered")] * outbox.MAX_ATTEMPTS
    _press("ob-7")
    for _ in range(outbox.MAX_ATTEMPTS):
        outbox.work_once("w1", now=datetime.now(timezone.utc) + timedelta(days=1))
    [dead] = outbox.list_sends("ob-7")
    assert dead.status == "dead" and f"after {outbox.MAX_ATTEMPTS} attempts" in dead.last_error
    sent = outbox.retry(dead.id, by="ana")
    assert sent.status == "delivered" and sent.resolved_by == "ana"
    far_end["answers"] = [{"kind": "http", "http_status": 400, "ok": False}]
    _press("ob-8")
    [refused] = outbox.list_sends("ob-8")
    left = outbox.dismiss(refused.id, by="ben", note="the carrier closed that account")
    assert (left.status, left.note) == ("dismissed", "the carrier closed that account")


def test_two_workers_never_hold_one_call_and_one_that_stopped_mid_send_is_unknown(far_end, on):
    send = outbox.enqueue(_carrier(), 0, {"order_id": "O-9"}, "ob-9")
    first, second = outbox._claim(send.id, "w1"), outbox._claim(send.id, "w2")
    assert first is not None and second is None
    assert outbox._sweep_stopped(datetime.now(timezone.utc) + timedelta(seconds=outbox.LEASE_S + 1)) == 1
    assert outbox.get(send.id).status == "unknown"


def test_a_writeback_that_fails_leaves_the_edits_and_every_other_call_undone(far_end, on):
    action = _carrier(side_effects=[{"kind": "http", "config": {"url": "https://erp.example/hold"}, "lane": "writeback"},
                                    {"kind": "http", "config": {"url": "https://carrier.example/claims"}}])
    far_end["answers"] = [{"kind": "http", "http_status": 409, "ok": False}]
    r = _press("ob-10", action)
    assert r.status == "dispatch_error" and "the writeback was refused (HTTP 409)" in r.message
    assert far_end["calls"] == 1 and outbox.list_sends("ob-10") == []
    with pytest.raises(ValueError, match="at most one writeback"):
        _carrier(side_effects=[{"kind": "http", "config": {}, "lane": "writeback"}] * 2)
