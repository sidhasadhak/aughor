"""An action whose every effect the platform performs is proved by the platform's own record (2026-10-09).

The declare door required a SQL read proving every side effect took effect, and the action designer could therefore
offer neither *Tell someone* nor *Start an investigation*: a message and an investigation land in no table a read can
see. The user's call: the platform's own record counts — a message's delivery log, an investigation's accepted job.
``notify`` now reaches a destination a person saved in Notifications, through the send every other door uses; the
`SideEffect` docstring had said so for a year while it went to a bare URL.
"""
from __future__ import annotations

import pytest

from aughor.actions import authority
from aughor.actions.executor import KineticDispatchError, default_dispatch
from aughor.notifications.models import ActionLog, ActionTrigger
from aughor.ontology.models import KineticAction

DESK = ActionTrigger(id="t-desk", name="Carrier desk", type="slack", url="https://hooks.slack.example/x")


def tell(**change) -> KineticAction:
    return KineticAction.model_validate({
        "id": "tell_carrier", "display_name": "Tell the carrier desk", "kind": "side_effect", "risk": "low",
        "params": [{"name": "order", "kind": "object", "object_type": "Order"}, {"name": "reason", "kind": "value"}],
        "side_effects": [{"kind": "notify", "config": {"destination": "t-desk", "message": "Order {order}: {reason}"}}],
        "reversibility": "irreversible", **change})


def ask(**change) -> KineticAction:
    return KineticAction.model_validate({
        "id": "why_late", "kind": "side_effect", "risk": "high", "reversibility": "irreversible",
        "params": [{"name": "order", "kind": "value"}],
        "side_effects": [{"kind": "trigger_investigation", "config": {"question": "Why is order {order} late?"}}], **change})


@pytest.fixture
def sent(monkeypatch):
    """Notifications, stood in for: one saved destination, and every send recorded with the status set here."""
    record = {"status": "ok", "calls": []}

    def fire(trigger, payload):
        record["calls"].append((trigger.id, payload.recommendation, payload.headline))
        return ActionLog(id="log-1", trigger_id=trigger.id, trigger_name=trigger.name, investigation_id="",
                         rec_index=0, recommendation=payload.recommendation, status=record["status"],
                         http_status=200 if record["status"] == "ok" else 500, error=None, fired_at="now")
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: DESK if tid == "t-desk" else None)
    monkeypatch.setattr("aughor.notifications.executor.fire_action", fire)
    return record


# ── the declaration ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_message_or_an_investigation_is_declared_without_a_statement_and_still_says_how_it_is_taken_back():
    assert authority.platform_performed(tell()) and authority.platform_performed(ask())
    assert authority.declaration_problem(tell()) == "" and authority.declaration_problem(ask()) == ""
    assert "undo" in authority.declaration_problem(tell(reversibility=""))
    # A bare URL is not the platform's to record: it still needs the read that proves it.
    raw = tell(side_effects=[{"kind": "notify", "config": {"url": "https://example.com/hook"}}])
    assert not authority.platform_performed(raw) and "verification statement" in authority.declaration_problem(raw)
    mixed = tell(side_effects=[*tell().side_effects, {"kind": "http", "config": {"url": "https://x.example"}}])
    assert not authority.platform_performed(mixed)


# ── the send and its record ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_message_goes_to_the_saved_destination_and_its_delivery_log_is_the_proof(sent):
    outcome = default_dispatch(tell(), {"order": "Order:6", "reason": "Missed pickup"})
    assert sent["calls"] == [("t-desk", "Order 6: Missed pickup", "Tell the carrier desk")]
    assert outcome["side_effects"][0] == {"kind": "notify", "destination": "t-desk", "destination_name": "Carrier desk",
                                          "message": "Order 6: Missed pickup", "log_id": "log-1", "status": "ok"}
    verified = authority.verify(tell(), {}, "c1", outcome=outcome)
    assert verified == {"status": "passed", "basis": "platform_record",
                        "why": "the platform's own record: delivered to Carrier desk (delivery log-1)"}


@pytest.mark.parametrize("status, says", [
    ("skipped", "is turned off in Notifications — nothing was sent"),
    ("timeout", "may have been delivered — no answer came back"),
    ("failed", "was not delivered"),
])
def test_a_message_that_did_not_land_is_a_dispatch_error_in_words(sent, status, says):
    sent["status"] = status
    with pytest.raises(KineticDispatchError, match=says):
        default_dispatch(tell(), {"order": "6", "reason": "x"})


def test_a_destination_removed_since_or_a_message_naming_an_unasked_answer_is_said(sent):
    with pytest.raises(KineticDispatchError, match="no destination 'gone' is saved"):
        default_dispatch(tell(side_effects=[{"kind": "notify", "config": {"destination": "gone"}}]), {})
    with pytest.raises(KineticDispatchError, match="does not declare"):
        default_dispatch(tell(side_effects=[{"kind": "notify", "config": {"destination": "t-desk", "message": "{who}"}}]), {})


def test_an_investigation_is_proved_by_its_accepted_job_and_a_missing_record_is_never_called_failed():
    assert authority.verify(ask(), {}, "c1", outcome={"side_effects": [{"kind": "trigger_investigation", "job_id": "j9"}]}) == {
        "status": "passed", "basis": "platform_record", "why": "the platform's own record: the investigation was accepted (job j9)"}
    assert authority.verify(ask(), {}, "c1", outcome={"side_effects": [{"kind": "trigger_investigation"}]})["status"] == "unavailable"
    assert authority.verify(ask(), {}, "c1", outcome=None)["status"] == "unavailable"
    plain = tell(side_effects=[{"kind": "notify", "config": {"url": "https://example.com/hook"}}])
    assert authority.verify(plain, {}, "c1", outcome={"side_effects": []})["status"] == "not_declared"
