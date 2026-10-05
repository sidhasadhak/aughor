"""Phase 2 of the 2027 study, P2-2 — triage under an attention budget (`govern/attention.py`),
charged at the departure gate.

What these hold: an addressee has a fixed number of unattended interruptions a week, the default
or the number a person set; once spent, the next clean unattended departure is HELD under its own
state with its score and reason, recorded in the departures ledger and listed by the door — never
silenced; a person's own send is exempt; a hold by any accuracy law outranks the budget and is
not charged against it; the four ranking terms are published with their weights and how each is
read today, and the score rides every judged row; a monitor alert brings its size term; the slots
reset on Monday.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aughor.govern import attention as A
from aughor.govern import departure_store as ds
from aughor.govern.departure import HELD_BUDGET, PERSON, Measurement, gate_departure
from aughor.routers import attention as R


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))


def _gate(text, **kw):
    base = dict(kind="slack_post", org_id="default", conn_id="", text=text, automation_id="auto1",
                automation_name="Test chain", target="#ops")
    base.update(kw)
    return gate_departure(**base)


def _measured(*values):
    from aughor.util.time import now_iso_z
    return Measurement(source="stub analysis", values=[float(v) for v in values], measured_at=now_iso_z())


def test_the_terms_are_published_with_their_weights_and_how_each_is_read():
    terms = R.get_terms()
    assert [t["term"] for t in terms["terms"]] == ["mission", "size", "waiting", "novelty"]
    assert round(sum(t["weight"] for t in terms["terms"]), 6) == 1.0
    assert all(t["read_today"] for t in terms["terms"]) and terms["held_state"] == HELD_BUDGET
    s = A.score(kind="monitor_alert", size=0.5, novelty=1.0)
    assert s["terms"] == {"mission": 0.0, "size": 0.5, "waiting": 1.0, "novelty": 1.0}
    assert s["score"] == round(0.25 * 0.5 + 0.2 * 1.0 + 0.2 * 1.0, 3)


def test_once_the_weeks_slots_are_spent_the_next_clean_departure_is_held_and_listed():
    A.set_slots("#ops", 2)
    assert A.slots_for("#ops") == 2 and A.slots_for("#elsewhere") == A.DEFAULT_SLOTS_PER_WEEK
    first = _gate("Orders held steady at the usual level this morning.")
    second = _gate("Returns were ordinary today; nothing to flag.")
    assert first.state == "departed" and second.state == "departed"
    assert first.guards["attention"] == "passed" and "0 of 2 slots" in first.checks["attention"]
    assert "score" in first.checks["triage"] and "novelty 1.00" in first.checks["triage"]
    third = _gate("Refund volume stayed inside its band all day.")
    assert third.state == HELD_BUDGET and third.held
    assert third.guards["attention"] == "held" and third.reasons == [third.checks["attention"]]
    assert "all 2 slots to #ops are used this week" in third.reason_sentence()
    assert "listed on the departures screen" in third.reason_sentence()
    # the hold is a row under its own state, with its score, and the door lists it
    held = A.held_this_week("#ops")
    assert [h["departure_id"] for h in held] == [third.record_id] and "score" in held[0]["triage"]
    assert ds.summary_counts()["by_state"] == {"departed": 2, HELD_BUDGET: 1}
    view = R.get_budget(addressee="#ops")
    assert (view["slots"], view["used"], view["left"], view["held_count"]) == (2, 2, 0, 1)
    assert R.get_held()["held"][0]["target"] == "#ops"
    # a different place has its own slots
    assert _gate("Nothing unusual for finance this week.", target="#finance").state == "departed"


def test_a_persons_own_send_is_exempt_and_an_accuracy_hold_is_not_charged():
    A.set_slots("#ops", 0)
    person = _gate("Here is the number I promised.", origin=PERSON)
    assert person.state == "departed" and person.guards["attention"] == "exempt"
    # a message the trust law holds is held by the trust law, not the budget, and spends no slot
    from aughor.govern.departure import TRUST_BANNER
    held = _gate(f"{TRUST_BANNER} on this figure. Revenue rose 9.1%.", measurement=_measured(9.1))
    assert held.state == "held" and held.guards["attention"] == "not_applicable"
    assert A.used_this_week("#ops") == 0
    # and with no slots at all, the first clean unattended send is held
    assert _gate("Quiet day; every metric inside its band.").state == HELD_BUDGET


def test_a_monitor_alert_brings_its_size_term_and_the_repeat_guard_feeds_novelty():
    assert A.size_for_alert(12.4, 10.0) == pytest.approx(0.24)
    assert A.size_for_alert(30.0, 10.0) == 1.0 and A.size_for_alert(None, 10.0) == 0.0 and A.size_for_alert(5.0, 0) == 0.0
    import uuid
    place = "#alerts-" + uuid.uuid4().hex[:6]        # its own slots: the kernel kv keeps overrides across tests
    v = _gate("Refund rate is above its band.", kind="monitor_alert", triage={"size": 0.24}, target=place)
    assert "size 0.24" in v.checks["triage"] and "waiting 1.00" in v.checks["triage"]
    # the repeat guard's own words feed novelty: the same shape with moved numbers is half as novel
    from aughor.govern import departure as gate
    moved = gate._Check(gate.PASSED, "the same message moved 9% since 2026-10-01 10:00")
    judged = gate._attention(gate.DEPARTED, gate.UNATTENDED, "analysis", place, "", moved, None)
    assert judged.outcome == gate.PASSED and "novelty 0.50" in judged.detail["triage"]
    fresh = gate._Check(gate.PASSED, "not sent to this place in the last 7 days")
    assert "novelty 1.00" in gate._attention(gate.DEPARTED, gate.UNATTENDED, "analysis", place, "", fresh, None).detail["triage"]


def test_slots_are_set_through_the_door_and_the_week_starts_on_monday():
    out = R.post_slots(R.SlotsBody(addressee="#ops", slots=3), principal=None)
    assert out["set_to"] == 3 and out["slots"] == 3
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        R.post_slots(R.SlotsBody(addressee="#ops", slots=-1), principal=None)
    assert A.week_start(datetime(2026, 10, 7, 15, 30, tzinfo=timezone.utc)) == "2026-10-05T00:00:00Z"
    charge = A.charge(addressee="#ops", kind="briefing", now=datetime(2026, 10, 7, 15, 30, tzinfo=timezone.utc))
    assert charge["allowed"] and charge["resets"] == "2026-10-12" and charge["terms"]["waiting"] == 0.4


def test_the_remedy_and_the_law_exist_for_the_new_guard():
    from aughor.govern import departure_remedies as dr
    told = dr.explain_guard("attention")
    assert told is not None and told["label"] == "attention budget" and "slots" in told["meaning"]
    assert "attention" in dr.laws() and "unattended interruptions" in dr.laws()["attention"]["sentence"]
