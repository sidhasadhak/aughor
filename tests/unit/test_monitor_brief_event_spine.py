"""T3 kernel-leverage — monitors and briefs land on the event spine.

A fired monitor alert and a delivered brief now emit `monitor.alert` /
`brief.delivered` events so these scheduled subsystems are observable on the
same journal the explorer uses, instead of living only in their own stores.
"""
import pytest


class _StubLedger:
    def __init__(self):
        self.events = []

    def emit(self, kind, payload=None, *, conn_id=None, canvas_id=None, job_id=None):
        self.events.append({"kind": kind, "payload": payload or {}, "conn_id": conn_id})
        return len(self.events)


@pytest.fixture
def stub_ledger(monkeypatch):
    import aughor.kernel.ledger as ledger_mod
    stub = _StubLedger()
    monkeypatch.setattr(ledger_mod.Ledger, "default", classmethod(lambda cls: stub))
    return stub


def test_append_alert_emits_monitor_alert(monkeypatch, tmp_path, stub_ledger):
    import aughor.monitors.store as store
    from aughor.monitors.models import MonitorAlert
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "monitors.db")
    store._init_schema()

    alert = MonitorAlert(
        monitor_id="m1", monitor_name="Revenue drop", conn_id="connX",
        metric_name="revenue", triggered_at="2026-06-12T10:00:00+00:00",
        severity="critical", current_value=123.0, message="Revenue below threshold",
    )
    store.append_alert(alert)

    ev = [e for e in stub_ledger.events if e["kind"] == "monitor.alert"]
    assert len(ev) == 1
    assert ev[0]["conn_id"] == "connX"
    assert ev[0]["payload"]["severity"] == "critical"
    assert ev[0]["payload"]["metric"] == "revenue"
    assert ev[0]["payload"]["monitor_name"] == "Revenue drop"


def test_deliver_subscription_emits_brief_delivered(monkeypatch, stub_ledger):
    import aughor.briefs.delivery as delivery
    from aughor.briefs.models import BriefSubscription

    sub = BriefSubscription(id="s1", name="Weekly digest", conn_id="connY",
                            period="week", trigger_id="t1")

    # trigger_id "t1" doesn't resolve → the real graceful "trigger not found"
    # path runs (status='failed'); the emit must still fire. persist=False keeps
    # it off the briefs store.
    result = delivery.deliver_subscription(sub, persist=False)
    assert result["status"] == "failed"

    ev = [e for e in stub_ledger.events if e["kind"] == "brief.delivered"]
    assert len(ev) == 1
    assert ev[0]["conn_id"] == "connY"
    assert ev[0]["payload"]["name"] == "Weekly digest"
    assert ev[0]["payload"]["status"] == result["status"]
