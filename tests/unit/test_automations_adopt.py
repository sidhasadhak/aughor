"""Wave A5 — adopt monitors + briefs onto the one engine.

The decision gate is EQUIVALENCE + REVERSIBILITY: the engine path produces the same alert/delivery
as the legacy path (same severity, message, and anti-flap debounce), and flipping the flag off
restores the legacy path with no data migration. The strongest evidence is that the translation is
literally the same two functions (`run_monitor`, `deliver_subscription`) called from a different
loop — so these tests lock the WIRING that makes "different loop, same behaviour" true, and the one
place a bug could hide: double-firing across a runtime flip.

Hermetic: the monitor/brief stores are the conftest temp DBs; `run_monitor` / `deliver_subscription`
are patched to spy on the calls the engine makes.
"""
from __future__ import annotations

from aughor.automations.adopt import (
    adoption_active,
    list_adopted_automations,
    monitor_as_automation,
    subscription_as_automation,
)
from aughor.automations.engine import run_automation
from aughor.automations.models import Effect
from aughor.briefs.models import BriefSubscription
from aughor.briefs.store import save_subscription
from aughor.monitors.models import Monitor, MonitorAlert
from aughor.monitors.store import upsert_monitor


def _monitor(**kw) -> Monitor:
    base = dict(id="m1", conn_id="c1", name="Revenue drop",
                check_cron="0 * * * *", alert_on="threshold_cross")
    base.update(kw)
    return Monitor(**base)


def _sub(**kw) -> BriefSubscription:
    base = dict(id="s1", conn_id="c1", name="Weekly brief", period="week", trigger_id="t1")
    base.update(kw)
    return BriefSubscription(**base)


# ── translation shape ────────────────────────────────────────────────────────────

def test_monitor_translates_to_schedule_plus_monitor_effect():
    a = monitor_as_automation(_monitor(check_cron="*/5 * * * *"))
    assert a.id == "monitor:m1"
    assert a.conditions[0].kind == "schedule" and a.conditions[0].cron == "*/5 * * * *"
    assert a.effects[0].kind == "monitor" and a.effects[0].config == {"monitor_id": "m1"}
    assert a.max_retries == 0, "the legacy monitor job never retried; a faithful replay must not add one"


def test_subscription_translates_to_schedule_plus_brief_effect():
    a = subscription_as_automation(_sub(period="day"))
    assert a.id == "brief:s1"
    assert a.conditions[0].kind == "schedule" and a.conditions[0].cron == "0 8 * * *"
    assert a.effects[0].kind == "brief" and a.effects[0].config == {"subscription_id": "s1"}
    assert a.max_retries == 0, "a brief is an outward send — a retry would risk a duplicate"


def test_disabled_objects_are_not_adopted():
    upsert_monitor(_monitor(id="m-on", conn_id="c-adopt"))
    upsert_monitor(_monitor(id="m-off", conn_id="c-adopt", enabled=False))
    save_subscription(_sub(id="s-on", conn_id="c-adopt"))
    save_subscription(_sub(id="s-off", conn_id="c-adopt", enabled=False))
    ids = {a.id for a in list_adopted_automations()}
    assert "monitor:m-on" in ids and "brief:s-on" in ids
    assert "monitor:m-off" not in ids and "brief:s-off" not in ids


# ── the monitor effect: faithful replay of the legacy job ─────────────────────────

def test_monitor_effect_appends_the_same_alert_the_monitor_produces(monkeypatch):
    """Equivalence: the `monitor` effect appends exactly the alert `run_monitor` returns — the
    engine path yields the same alert the legacy scheduler would have."""
    upsert_monitor(_monitor(id="m-eq", conn_id="c-eq"))
    alert = MonitorAlert(monitor_id="m-eq", triggered_at="2026-07-24T10:00:00Z",
                         severity="critical", message="Revenue down 40%")
    seen_suppress = {}

    def fake_run_monitor(m, db, suppress=True):
        seen_suppress["value"] = suppress
        return alert

    appended: list = []
    monkeypatch.setattr("aughor.monitors.runner.run_monitor", fake_run_monitor)
    monkeypatch.setattr("aughor.monitors.store.append_alert", lambda a: appended.append(a))
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: type("D", (), {"close": lambda self: None})())

    from aughor.automations.engine import _dispatch_monitor
    out = _dispatch_monitor(Effect(kind="monitor", config={"monitor_id": "m-eq"}),
                            monitor_as_automation(_monitor(id="m-eq", conn_id="c-eq")))
    assert out.status == "executed"
    assert appended == [alert], "the effect did not append the monitor's own alert"
    assert seen_suppress["value"] is True, "the anti-flap debounce (suppress=True) was not preserved"


def test_monitor_effect_appends_nothing_when_the_check_is_quiet(monkeypatch):
    upsert_monitor(_monitor(id="m-quiet", conn_id="c-q"))
    appended: list = []
    monkeypatch.setattr("aughor.monitors.runner.run_monitor", lambda m, db, suppress=True: None)
    monkeypatch.setattr("aughor.monitors.store.append_alert", lambda a: appended.append(a))
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: type("D", (), {"close": lambda self: None})())
    from aughor.automations.engine import _dispatch_monitor
    out = _dispatch_monitor(Effect(kind="monitor", config={"monitor_id": "m-quiet"}),
                            monitor_as_automation(_monitor(id="m-quiet", conn_id="c-q")))
    assert out.status == "executed" and out.message == "no alert"
    assert appended == []


def test_monitor_effect_skips_a_missing_or_disabled_monitor(monkeypatch):
    from aughor.automations.engine import _dispatch_monitor
    out = _dispatch_monitor(Effect(kind="monitor", config={"monitor_id": "ghost"}),
                            monitor_as_automation(_monitor(id="ghost", conn_id="c")))
    assert out.status == "skipped"


# ── the brief effect delivers via the same path ───────────────────────────────────

def test_brief_effect_delivers_the_subscription(monkeypatch):
    save_subscription(_sub(id="s-eq", conn_id="c-eq"))
    delivered: list = []

    def fake_deliver(sub, persist=True):
        delivered.append(sub.id)
        return {"status": "ok"}

    monkeypatch.setattr("aughor.briefs.delivery.deliver_subscription", fake_deliver)
    from aughor.automations.engine import _dispatch_brief
    out = _dispatch_brief(Effect(kind="brief", config={"subscription_id": "s-eq"}),
                          subscription_as_automation(_sub(id="s-eq", conn_id="c-eq")))
    assert out.status == "executed"
    assert delivered == ["s-eq"]


# ── end to end through the engine (schedule fires once per due window) ─────────────

def test_adopted_monitor_fires_its_effect_through_run_automation(monkeypatch):
    upsert_monitor(_monitor(id="m-e2e", conn_id="c-e2e"))
    alert = MonitorAlert(monitor_id="m-e2e", triggered_at="2026-07-24T10:00:00Z",
                         severity="warning", message="edge")
    appended: list = []
    monkeypatch.setattr("aughor.monitors.runner.run_monitor", lambda m, db, suppress=True: alert)
    monkeypatch.setattr("aughor.monitors.store.append_alert", lambda a: appended.append(a))
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: type("D", (), {"close": lambda self: None})())

    a = monitor_as_automation(_monitor(id="m-e2e", conn_id="c-e2e"))
    run = run_automation(a, persist=False)
    assert run.outcome == "fired"
    assert [o.status for o in run.effects] == ["executed"]
    assert appended == [alert]


# ── reversibility + no double-fire ────────────────────────────────────────────────

def test_adoption_requires_both_flags(monkeypatch):
    """adopt_legacy alone must do NOTHING — it needs the engine on too, or it would stand the
    legacy schedulers down with nothing running to replace them."""
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.adopt_legacy")
    assert adoption_active() is False
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n in ("automations.adopt_legacy", "automations.engine"))
    assert adoption_active() is True


def test_the_legacy_monitor_job_stands_down_when_adoption_is_active(monkeypatch):
    """The no-double-fire net: with adoption active the legacy monitor job returns at FIRE time
    without running the check — so only the heartbeat fires it."""
    upsert_monitor(_monitor(id="m-sd", conn_id="c-sd"))
    ran = {"value": False}
    monkeypatch.setattr("aughor.monitors.runner.run_monitor",
                        lambda m, db, suppress=True: ran.__setitem__("value", True))
    monkeypatch.setattr("aughor.automations.adopt.adoption_active", lambda: True)

    from aughor.monitors.scheduler import _make_job_fn
    _make_job_fn("m-sd")()          # invoke the legacy job body directly
    assert ran["value"] is False, "the legacy monitor job ran while adopted — double-fire risk"


def test_the_legacy_brief_job_stands_down_when_adoption_is_active(monkeypatch):
    """Same net for briefs — and it matters more, because a brief is an OUTWARD send."""
    save_subscription(_sub(id="s-sd", conn_id="c-sd"))
    delivered = {"value": False}
    monkeypatch.setattr("aughor.briefs.delivery.deliver_subscription",
                        lambda sub, persist=True: delivered.__setitem__("value", True))
    monkeypatch.setattr("aughor.automations.adopt.adoption_active", lambda: True)

    from aughor.briefs.scheduler import _make_job_fn
    _make_job_fn("s-sd")()
    assert delivered["value"] is False, "the legacy brief job delivered while adopted — double-send risk"


def test_the_legacy_monitor_job_runs_normally_when_adoption_is_off(monkeypatch):
    """Reversibility: flag off ⇒ the legacy job runs exactly as before (byte-identical path)."""
    upsert_monitor(_monitor(id="m-legacy", conn_id="c-legacy"))
    ran = {"value": False}
    monkeypatch.setattr("aughor.monitors.runner.run_monitor",
                        lambda m, db, suppress=True: ran.__setitem__("value", True) or None)
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda cid: type("D", (), {"close": lambda self: None})())
    monkeypatch.setattr("aughor.db.registry.get_connection_org", lambda cid: "")
    monkeypatch.setattr("aughor.automations.adopt.adoption_active", lambda: False)

    from aughor.monitors.scheduler import _make_job_fn
    _make_job_fn("m-legacy")()
    assert ran["value"] is True, "the legacy job did not run with adoption off"
