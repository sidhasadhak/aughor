"""Wave A1 — the Automation model + store.

Locks the two properties the store exists for: an automation round-trips through SQLite with every
lifecycle field intact, and EVERY tick leaves a row — including the ticks that deliberately did
nothing, which is precisely what ``monitor_alerts`` cannot record (it stores only alerts that
fired, so "did it run at 03:00, and why did nothing happen?" is unanswerable there).

Hermetic: ``AUGHOR_AUTOMATIONS_DB`` is the conftest temp store.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from aughor.automations.models import Automation, AutomationRun, Condition, Effect, EffectOutcome
from aughor.automations.store import (
    append_run,
    delete_automation,
    get_automation,
    get_runs,
    last_run,
    list_automations,
    pause_automation,
    purge_connection,
    set_automation_enabled,
    upsert_automation,
)


def _automation(**kw) -> Automation:
    base = dict(
        conn_id="conn-a", name="Revenue watch",
        conditions=[Condition(kind="schedule", config={"cron": "0 8 * * 1"})],
        effects=[Effect(kind="notify", config={"trigger_id": "trig-1"})],
    )
    base.update(kw)
    return Automation(**base)


# ── model validation: malformed configs are rejected at construction ──────────────

@pytest.mark.parametrize("kind,config", [
    ("schedule", {}),                       # no cron
    ("metric", {"cron": "0 8 * * *"}),      # right shape, wrong key
    ("source_change", {}),                  # no table
    ("entity_appears", {"column": "id"}),   # no table
])
def test_condition_requires_its_config_keys(kind, config):
    """A condition that cannot be evaluated must never reach the store — reject at construction,
    not at execute, so a broken automation cannot sit in the DB looking schedulable."""
    with pytest.raises(ValidationError):
        Condition(kind=kind, config=config)


@pytest.mark.parametrize("kind,config", [
    ("investigate", {}),
    ("brief", {"trigger_id": "t"}),
    ("notify", {"subscription_id": "s"}),
    ("kinetic_action", {"params": {"amount": 1}}),
])
def test_effect_requires_its_config_keys(kind, config):
    with pytest.raises(ValidationError):
        Effect(kind=kind, config=config)


def test_automation_requires_at_least_one_condition_and_effect():
    with pytest.raises(ValidationError):
        Automation(conn_id="c", name="n", conditions=[], effects=[
            Effect(kind="notify", config={"trigger_id": "t"})])
    with pytest.raises(ValidationError):
        Automation(conn_id="c", name="n", effects=[], conditions=[
            Condition(kind="schedule", config={"cron": "* * * * *"})])


# ── round-trip ───────────────────────────────────────────────────────────────────

def test_round_trip_preserves_every_lifecycle_field():
    """The A1 decision gate: two conditions + two effects + a fallback survive
    model → SQLite → model unchanged, including muting, expiry and retry policy."""
    original = _automation(
        description="two of each",
        conditions=[
            Condition(kind="schedule", config={"cron": "0 8 * * 1"}),
            Condition(kind="metric", config={"monitor_id": "mon-7"}),
        ],
        condition_logic="any",
        effects=[
            Effect(kind="notify", config={"trigger_id": "trig-1"}),
            Effect(kind="kinetic_action", config={"action_id": "refund",
                                                  "params": {"amount": 500}}),
        ],
        fallback_effect=Effect(kind="notify", config={"trigger_id": "oncall"}),
        paused_until="2026-08-01T00:00:00Z",
        expires_at="2026-12-31T00:00:00Z",
        max_retries=3,
        retry_backoff_seconds=12.5,
    )
    upsert_automation(original)

    loaded = get_automation(original.id)
    assert loaded is not None
    # created_at/updated_at are stamped by the store; everything else must match exactly.
    assert loaded.model_dump(exclude={"created_at", "updated_at"}) == \
        original.model_dump(exclude={"created_at", "updated_at"})
    assert loaded.conditions[1].monitor_id == "mon-7"
    assert loaded.effects[1].params == {"amount": 500}
    assert loaded.fallback_effect is not None
    assert loaded.fallback_effect.config["trigger_id"] == "oncall"


def test_upsert_replaces_by_id():
    a = upsert_automation(_automation(name="before"))
    upsert_automation(a.model_copy(update={"name": "after"}))
    assert get_automation(a.id).name == "after"
    assert len([x for x in list_automations("conn-a") if x.id == a.id]) == 1


def test_enable_and_pause_toggles():
    a = upsert_automation(_automation(conn_id="conn-toggle"))
    assert set_automation_enabled(a.id, False).enabled is False
    assert set_automation_enabled(a.id, True).enabled is True
    assert pause_automation(a.id, "2027-01-01T00:00:00Z").paused_until == "2027-01-01T00:00:00Z"
    assert pause_automation(a.id, None).paused_until is None


def test_enabled_only_filter():
    upsert_automation(_automation(conn_id="conn-filter", name="on"))
    off = upsert_automation(_automation(conn_id="conn-filter", name="off", enabled=False))
    names = {x.name for x in list_automations("conn-filter", enabled_only=True)}
    assert names == {"on"}
    assert off.id not in {x.id for x in list_automations("conn-filter", enabled_only=True)}


# ── run history ──────────────────────────────────────────────────────────────────

def test_a_tick_that_fired_nothing_still_leaves_a_row():
    """The gate: this is the case the monitor store cannot represent at all."""
    a = upsert_automation(_automation(conn_id="conn-quiet"))
    append_run(AutomationRun(automation_id=a.id, automation_name=a.name, conn_id=a.conn_id,
                             outcome="not_fired",
                             reason="schedule(0 8 * * 1): next due 2026-07-27T08:00:00+00:00"))
    runs = get_runs(automation_id=a.id)
    assert len(runs) == 1
    assert runs[0].outcome == "not_fired"
    assert "next due" in runs[0].reason


def test_run_records_per_effect_outcomes_and_advances_the_summary():
    a = upsert_automation(_automation(conn_id="conn-hist"))
    append_run(AutomationRun(
        automation_id=a.id, automation_name=a.name, conn_id=a.conn_id,
        outcome="fired", reason="metric(mon-7): critical",
        conditions_fired=["metric(mon-7): critical"],
        effects=[
            EffectOutcome(kind="notify", target="trig-1", status="executed"),
            EffectOutcome(kind="kinetic_action", target="refund", status="criterion_failed",
                          message="Refunds over €10,000 need finance sign-off.", attempts=1),
        ],
        finished_at="2026-07-23T09:00:00Z",
    ))
    run = last_run(a.id)
    assert run is not None and run.outcome == "fired"
    assert [e.status for e in run.effects] == ["executed", "criterion_failed"]
    # The authored criterion message survives persistence verbatim — never paraphrased.
    assert run.effects[1].message == "Refunds over €10,000 need finance sign-off."
    # The config row's summary can never disagree with its history.
    reloaded = get_automation(a.id)
    assert reloaded.last_status == "fired"
    assert reloaded.last_run_at == "2026-07-23T09:00:00Z"


def test_append_run_is_idempotent_on_duplicate_id():
    a = upsert_automation(_automation(conn_id="conn-idem"))
    run = AutomationRun(automation_id=a.id, conn_id=a.conn_id, outcome="gated", reason="disabled")
    append_run(run)
    append_run(run)
    assert len(get_runs(automation_id=a.id)) == 1


# ── cascade ──────────────────────────────────────────────────────────────────────

def test_delete_automation_removes_its_runs():
    a = upsert_automation(_automation(conn_id="conn-del"))
    append_run(AutomationRun(automation_id=a.id, conn_id=a.conn_id, outcome="gated", reason="x"))
    assert delete_automation(a.id) is True
    assert get_automation(a.id) is None
    assert get_runs(automation_id=a.id) == []


def test_purge_connection_clears_both_tables():
    a = upsert_automation(_automation(conn_id="conn-purge"))
    append_run(AutomationRun(automation_id=a.id, conn_id="conn-purge",
                             outcome="fired", reason="x"))
    removed = purge_connection("conn-purge")
    assert removed >= 2
    assert list_automations("conn-purge") == []
    assert get_runs(conn_id="conn-purge") == []
