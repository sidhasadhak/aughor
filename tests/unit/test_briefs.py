"""Scheduled brief subscriptions — store CRUD, cron resolution, delivery wiring.

Backend for backlog #4 (#20c): push the Intelligence Digest on a schedule via an
Action Hub trigger. See aughor/briefs/.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import aughor.briefs.store as bstore
from aughor.briefs.models import BriefSubscription, DEFAULT_CRON
from aughor.briefs import delivery as bdelivery


# ── model: cron resolution ───────────────────────────────────────────────────

def test_resolved_cron_defaults_by_period():
    assert BriefSubscription(conn_id="c", name="n", trigger_id="t",
                             period="week").resolved_cron() == DEFAULT_CRON["week"]
    assert BriefSubscription(conn_id="c", name="n", trigger_id="t",
                             period="day").resolved_cron() == DEFAULT_CRON["day"]


def test_resolved_cron_explicit_wins():
    sub = BriefSubscription(conn_id="c", name="n", trigger_id="t",
                            period="week", send_cron="30 6 * * 5")
    assert sub.resolved_cron() == "30 6 * * 5"


# ── store: CRUD round-trip ───────────────────────────────────────────────────

def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bstore, "_PATH", tmp_path / "subs.json")


def test_store_create_assigns_id_and_persists(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    sub = BriefSubscription(conn_id="c1", name="Weekly", trigger_id="t1")
    saved = bstore.save_subscription(sub)
    assert saved.id  # assigned
    got = bstore.get_subscription(saved.id)
    assert got is not None and got.name == "Weekly"


def test_store_update_by_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    saved = bstore.save_subscription(BriefSubscription(conn_id="c1", name="A", trigger_id="t1"))
    saved.name = "B"
    bstore.save_subscription(saved)
    rows = bstore.list_subscriptions()
    assert len(rows) == 1 and rows[0].name == "B"


def test_store_list_filters_by_conn(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    bstore.save_subscription(BriefSubscription(conn_id="c1", name="A", trigger_id="t1"))
    bstore.save_subscription(BriefSubscription(conn_id="c2", name="B", trigger_id="t1"))
    assert len(bstore.list_subscriptions("c1")) == 1
    assert len(bstore.list_subscriptions()) == 2


def test_store_delete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    saved = bstore.save_subscription(BriefSubscription(conn_id="c1", name="A", trigger_id="t1"))
    assert bstore.delete_subscription(saved.id) is True
    assert bstore.delete_subscription(saved.id) is False
    assert bstore.get_subscription(saved.id) is None


# ── delivery: payload + firing ───────────────────────────────────────────────

def _fake_digest(alerts=2, critical=1, sections=1):
    secs = [SimpleNamespace(title="Alerts", items=["a", "b"]) for _ in range(sections)]
    return SimpleNamespace(alert_count=alerts, critical_count=critical,
                           sections=secs, to_markdown=lambda: "# Digest\n- a\n- b")


def test_build_brief_payload_summary(monkeypatch):
    monkeypatch.setattr("aughor.monitors.digest.build_digest",
                        lambda conn_id, period: _fake_digest())
    sub = BriefSubscription(conn_id="c1", name="W", trigger_id="t1", period="week")
    summary, md, digest = bdelivery.build_brief_payload(sub)
    assert summary.startswith("Weekly Intelligence Brief")
    assert "2 alert(s)" in summary and "1 critical" in summary
    assert md.startswith("# Digest")


def test_build_brief_payload_quiet_period(monkeypatch):
    monkeypatch.setattr("aughor.monitors.digest.build_digest",
                        lambda conn_id, period: _fake_digest(alerts=0, critical=0, sections=0))
    sub = BriefSubscription(conn_id="c1", name="W", trigger_id="t1", period="day")
    summary, _md, _d = bdelivery.build_brief_payload(sub)
    assert "no significant activity" in summary


def test_deliver_subscription_no_trigger(monkeypatch, tmp_path):
    _isolate(tmp_path, monkeypatch)
    import aughor.actions.store as astore
    monkeypatch.setattr(astore, "get_trigger", lambda tid: None)
    sub = bstore.save_subscription(BriefSubscription(conn_id="c1", name="W", trigger_id="missing"))
    result = bdelivery.deliver_subscription(sub)
    assert result["status"] == "failed"
    assert "trigger not found" in (result["error"] or "").lower()
    # outcome recorded on the subscription
    assert bstore.get_subscription(sub.id).last_status == "failed"


def test_deliver_subscription_fires_and_records(monkeypatch, tmp_path):
    _isolate(tmp_path, monkeypatch)
    import aughor.actions.store as astore
    import aughor.actions.executor as execu
    monkeypatch.setattr(astore, "get_trigger",
                        lambda tid: SimpleNamespace(id=tid, enabled=True))
    monkeypatch.setattr("aughor.monitors.digest.build_digest",
                        lambda conn_id, period: _fake_digest())
    captured = {}

    def _fire(trigger, payload):
        captured["payload"] = payload
        return SimpleNamespace(status="ok", http_status=200, error=None)

    monkeypatch.setattr(execu, "fire_action", _fire)
    sub = bstore.save_subscription(BriefSubscription(conn_id="c1", name="W", trigger_id="t1"))
    result = bdelivery.deliver_subscription(sub)

    assert result["status"] == "ok"
    p = captured["payload"]
    assert p.recommendation.startswith("Weekly Intelligence Brief")
    assert p.investigation_id == f"brief:{sub.id}"
    assert bstore.get_subscription(sub.id).last_status == "ok"


# ── router: validation ───────────────────────────────────────────────────────

def test_router_create_rejects_missing_trigger(monkeypatch):
    from aughor.routers.briefs import create_brief_subscription, _SubscriptionBody
    import aughor.actions.store as astore
    monkeypatch.setattr(astore, "get_trigger", lambda tid: None)
    with pytest.raises(HTTPException) as ei:
        create_brief_subscription(_SubscriptionBody(conn_id="c1", name="W", trigger_id="nope"))
    assert ei.value.status_code == 400


def test_router_create_rejects_bad_period(monkeypatch):
    from aughor.routers.briefs import create_brief_subscription, _SubscriptionBody
    with pytest.raises(HTTPException) as ei:
        create_brief_subscription(_SubscriptionBody(conn_id="c1", name="W", trigger_id="t1", period="month"))
    assert ei.value.status_code == 422
