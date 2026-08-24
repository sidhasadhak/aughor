"""An automation that cannot dispatch at all belonged in Attention and was nowhere.

Measured on the live install 2026-08-24: ONE automation existed, enabled, and its only
effect named `cr-proof-trigger` — an Action Hub trigger created during Wave CR5's live
proof and never replaced. It had been failing on every hourly tick since, producing
`dispatch_error: unknown Action Hub trigger: cr-proof-trigger` into a log line nobody
reads. The outcome was PRODUCED and nothing CONSUMED it, which is the shape this repo
keeps rediscovering.

An unknown trigger is not a transient failure that clears on retry. It fails identically
on the next tick, and every tick after that, until a person changes the configuration —
which is the definition of something waiting on a human.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def _run(automation_id: str, *, status: str, message: str = "unknown Action Hub trigger: x",
         name: str = "Hourly jobs pulse", started_at: str | None = None):
    from aughor.automations.models import AutomationRun, EffectOutcome
    from aughor.automations.store import append_run
    run = AutomationRun(
        automation_id=automation_id, automation_name=name, conn_id="c1",
        outcome="fired", reason="schedule due",
        effects=[EffectOutcome(kind="notify", target="cr-proof-trigger",
                               status=status, message=message)],
        **({"started_at": started_at} if started_at else {}),
    )
    return append_run(run)


def _tick(automation_id: str, *, name: str = "Hourly jobs pulse",
          started_at: str | None = None):
    """A tick that evaluated its conditions and did NOT fire — no effects at all.

    This is what the engine records most of the time: measured live, it ticks every
    minute and fires once an hour.
    """
    from aughor.automations.models import AutomationRun
    from aughor.automations.store import append_run
    return append_run(AutomationRun(
        automation_id=automation_id, automation_name=name, conn_id="c1",
        outcome="not_fired", reason="schedule not due", effects=[],
        **({"started_at": started_at} if started_at else {}),
    ))


def _attention(client) -> dict:
    return client.get("/control-room/needs-human").json()


def test_an_automation_that_cannot_dispatch_needs_a_human(client):
    _run("auto-broken-1", status="dispatch_error")

    body = _attention(client)

    mine = [r for r in body["rows"] if r["source"] == "automation_broken"]
    assert len(mine) == 1, "a permanently failing automation appeared nowhere"
    assert "cannot dispatch" in mine[0]["title"]
    assert "unknown Action Hub trigger" in mine[0]["title"], (
        "the message must be carried verbatim — paraphrasing it loses the only clue")
    assert mine[0]["resolve"]["automation_id"] == "auto-broken-1"


def test_the_count_still_equals_the_sum_of_its_sources(client):
    """The CR4 gate. Attention is a VIEW: a source that adds rows without adding to the
    count turns the badge into a number that means nothing."""
    _run("auto-broken-2", status="dispatch_error")

    body = _attention(client)

    assert body["sources"]["broken_automations"] >= 1
    assert body["count"] == sum(body["sources"].values())


def test_an_automation_that_dispatched_is_not_waiting_on_anybody(client):
    _run("auto-fine", status="executed", message="delivered")

    rows = [r for r in _attention(client)["rows"]
            if r["resolve"].get("automation_id") == "auto-fine"]
    assert rows == []


def test_a_failure_that_has_since_recovered_is_gone(client):
    """Only the NEWEST run decides. An automation somebody has already fixed must not keep
    a row alive out of the archive."""
    _run("auto-recovered", status="dispatch_error", started_at="2026-08-01T00:00:00Z")
    _run("auto-recovered", status="executed", message="delivered")

    rows = [r for r in _attention(client)["rows"]
            if r["resolve"].get("automation_id") == "auto-recovered"]
    assert rows == [], "a recovered automation is still being reported as broken"


def test_one_row_per_automation_however_many_times_it_has_failed(client):
    """Failing hourly for a week is ONE problem. 168 rows of it would bury the other four
    sources rather than surface this one."""
    for i in range(6):
        _run("auto-noisy", status="dispatch_error",
             started_at=f"2026-08-2{i}T00:00:00Z")

    rows = [r for r in _attention(client)["rows"]
            if r["resolve"].get("automation_id") == "auto-noisy"]
    assert len(rows) == 1


def test_a_tick_that_did_not_fire_does_not_read_as_health(client):
    """The defect that only driving the live system could find.

    The engine ticks EVERY MINUTE and records `not_fired` when the schedule is not due,
    firing once an hour. Deciding on the most recent run of ANY kind therefore read a
    `not_fired` tick as "it dispatched fine" and hid the broken automation for 59 minutes
    out of every 60. Every earlier test in this file used `fired` runs, so none of them
    could catch it — the shape below is the live one, verbatim.
    """
    _run("auto-hourly", status="dispatch_error", started_at="2026-08-24T07:00:10Z")
    for minute in (2, 3, 4):
        _tick("auto-hourly", started_at=f"2026-08-24T07:0{minute}:11Z")

    rows = [r for r in _attention(client)["rows"]
            if r["resolve"].get("automation_id") == "auto-hourly"]
    assert len(rows) == 1, (
        "a tick that never reached its effects carries no verdict on whether they can "
        "dispatch — only a run that fired does")


def test_a_fire_that_recovered_still_clears_it(client):
    """The other direction, with non-firing ticks in between: the newest run that ACTUALLY
    FIRED decides, so a fixed automation drops out even though ticks follow it."""
    _run("auto-fixed", status="dispatch_error", started_at="2026-08-24T05:00:00Z")
    _tick("auto-fixed", started_at="2026-08-24T05:30:00Z")
    _run("auto-fixed", status="executed", message="delivered",
         started_at="2026-08-24T06:00:00Z")
    _tick("auto-fixed", started_at="2026-08-24T06:30:00Z")

    rows = [r for r in _attention(client)["rows"]
            if r["resolve"].get("automation_id") == "auto-fixed"]
    assert rows == []
