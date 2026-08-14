"""OA·N8-0 — a fired alert reaches its configured channel.

`Monitor.notification_channel` shipped with monitors and was read by nothing; its own
field description said so ("only in_app wired currently"). A user could configure a
monitor to notify Slack and get silence, with no error anywhere.

The claims, each with the failure it guards:

  1. `in_app` (the default) still sends NOTHING outward. This wave must not turn every
     existing monitor into a webhook.
  2. A channel naming an Action Hub trigger delivers through it, carrying the facts a
     receiver needs to ROUTE — severity, value vs threshold, connection, deep link —
     not just prose.
  3. Delivery is idempotent at the ALERT, not just at the row: `INSERT OR IGNORE` made
     a duplicate a row-level no-op while the fan-out still ran, so a re-submitted alert
     would have re-sent the webhook.
  4. A broken or missing destination never costs the alert. The row is the source of
     truth and is committed before anything is sent.
"""
from __future__ import annotations

import pytest

import aughor.monitors.notify as notify
import aughor.monitors.store as store
from aughor.monitors.models import Monitor, MonitorAlert
from aughor.notifications.models import ActionLog, ActionPayload, ActionTrigger


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "monitors.db")
    store._init_schema()
    monkeypatch.delenv("AUGHOR_WEB_URL", raising=False)


@pytest.fixture()
def sent(monkeypatch):
    """Capture what would have gone over the wire, without going over it."""
    calls: list[tuple[ActionTrigger, ActionPayload]] = []

    def _fake_fire(trigger, payload):
        calls.append((trigger, payload))
        return ActionLog(
            id="log1", trigger_id=trigger.id, trigger_name=trigger.name,
            investigation_id=payload.investigation_id, rec_index=0,
            recommendation=payload.recommendation, status="ok",
            http_status=200, error=None, fired_at="2026-08-14T00:00:00Z",
        )

    import aughor.notifications.executor as executor
    monkeypatch.setattr(executor, "fire_action", _fake_fire)
    return calls


def _monitor(channel: str) -> Monitor:
    m = Monitor(conn_id="conn-demo", name="EMEA margin", custom_sql="SELECT 1",
                metric_name="margin_pct", notification_channel=channel)
    store.upsert_monitor(m)
    return m


def _alert(monitor: Monitor, **kw) -> MonitorAlert:
    return MonitorAlert(
        monitor_id=monitor.id, monitor_name=monitor.name, conn_id=monitor.conn_id,
        metric_name=monitor.metric_name, triggered_at="2026-08-14T09:00:00Z",
        alert_on="below", severity=kw.pop("severity", "critical"),
        current_value=kw.pop("current_value", 8.5), threshold=kw.pop("threshold", 10.0),
        previous_value=kw.pop("previous_value", 11.2),
        message=kw.pop("message", "margin_pct fell below 10.0"), **kw)


# ── 1. the default stays silent ───────────────────────────────────────────────

def test_in_app_monitor_sends_nothing(isolated, sent):
    """The historical behaviour, pinned. Every monitor that exists today defaults
    here — this wave must be invisible to all of them."""
    store.append_alert(_alert(_monitor("in_app")))
    assert sent == []


def test_empty_channel_is_treated_as_in_app(isolated, sent):
    """A blank channel is not a trigger id. Falling through to a lookup would log a
    spurious 'trigger does not exist' warning on every fire."""
    store.append_alert(_alert(_monitor("")))
    assert sent == []


# ── 2. a configured channel actually delivers ─────────────────────────────────

def test_trigger_channel_delivers_with_routable_facts(isolated, sent, monkeypatch):
    monkeypatch.setenv("AUGHOR_WEB_URL", "https://aughor.example.com")
    trigger = ActionTrigger(id="trg-n8n", name="n8n", type="webhook",
                            url="https://n8n.example.com/webhook/abc")
    monkeypatch.setattr("aughor.notifications.store.get_trigger",
                        lambda tid: trigger if tid == "trg-n8n" else None)

    alert = _alert(_monitor("trg-n8n"))
    store.append_alert(alert)

    assert len(sent) == 1, "a monitor naming a trigger did not deliver"
    fired_trigger, payload = sent[0]
    assert fired_trigger.id == "trg-n8n"

    ctx = payload.context
    assert ctx["kind"] == "monitor_alert"
    assert ctx["severity"] == "critical"
    assert ctx["current_value"] == 8.5 and ctx["threshold"] == 10.0
    assert ctx["conn_id"] == "conn-demo"
    assert ctx["monitor_name"] == "EMEA margin"
    assert ctx["deep_link"] == "https://aughor.example.com/?tab=monitors&conn=conn-demo"
    # The prose carries the comparison, not just the bare number — a reader cannot
    # tell whether 8.5 is bad without the threshold beside it.
    assert "8.5" in payload.recommendation and "10" in payload.recommendation


def test_deep_link_omitted_rather_than_guessed(isolated, sent, monkeypatch):
    """Without AUGHOR_WEB_URL the API cannot know its own public origin. A Slack
    message linking to localhost is worse than one with no link."""
    trigger = ActionTrigger(id="t1", name="hook", type="webhook", url="https://x.example.com/h")
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: trigger)
    store.append_alert(_alert(_monitor("t1")))
    assert sent[0][1].context["deep_link"] == ""


def test_context_is_absent_from_the_body_for_pre_existing_callers():
    """`context` is additive: an investigation-recommendation payload must serialise
    byte-identically to before, or every existing webhook receiver sees a changed body."""
    p = ActionPayload(investigation_id="inv1", rec_index=0, recommendation="do the thing",
                      metric_name="revenue", headline="Revenue fell", trigger_id="t1",
                      triggered_at="2026-08-14T00:00:00Z")
    assert "context" not in p.to_dict()


# ── 3. idempotency covers the SEND, not just the row ──────────────────────────

def test_duplicate_alert_does_not_resend(isolated, sent, monkeypatch):
    """`INSERT OR IGNORE` made a duplicate a no-op row-wise while the fan-out below it
    still ran. Harmless for an event emit; a re-sent webhook is not."""
    trigger = ActionTrigger(id="t1", name="hook", type="webhook", url="https://x.example.com/h")
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: trigger)
    alert = _alert(_monitor("t1"))
    store.append_alert(alert)
    store.append_alert(alert)          # same id — a retry, not a new alert
    assert len(sent) == 1, "a duplicate alert id fired the webhook twice"


def test_delivery_key_is_stable_for_one_alert(isolated, sent, monkeypatch):
    """The inner HTTP retry (twice, on a 15s timeout) must be distinguishable from a
    new alert by the receiver. A fresh timestamp cannot do that; the alert id can."""
    trigger = ActionTrigger(id="t1", name="hook", type="webhook", url="https://x.example.com/h")
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: trigger)
    alert = _alert(_monitor("t1"))
    store.append_alert(alert)
    assert sent[0][1].delivery_key == f"monitor-alert:{alert.id}"


# ── 4. delivery never costs the alert ─────────────────────────────────────────

def test_unknown_trigger_still_persists_the_alert(isolated, sent, monkeypatch, caplog):
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: None)
    alert = _alert(_monitor("deleted-trigger"))
    store.append_alert(alert)
    assert [a.id for a in store.get_alerts()] == [alert.id]
    assert sent == []
    assert "does not exist" in caplog.text, "a misconfigured channel failed silently"


def test_dispatch_failure_never_raises(isolated, monkeypatch):
    """Fail-open in one direction only: a delivery problem must not look like a
    monitor that failed to fire."""
    def _boom(_tid):
        raise RuntimeError("action store unreachable")
    monkeypatch.setattr("aughor.notifications.store.get_trigger", _boom)
    alert = _alert(_monitor("t1"))
    store.append_alert(alert)          # must not raise
    assert [a.id for a in store.get_alerts()] == [alert.id]


def test_dispatch_alert_is_a_noop_for_an_unresolvable_monitor(isolated, sent):
    """An alert whose monitor was deleted between fire and delivery."""
    ghost = MonitorAlert(monitor_id="gone", monitor_name="?", conn_id="c1",
                         triggered_at="2026-08-14T09:00:00Z", alert_on="below",
                         severity="info", message="x")
    assert notify.dispatch_alert(ghost) is None
    assert sent == []


# ── the Slack rendering ───────────────────────────────────────────────────────

def test_slack_renders_an_alert_as_an_alert(isolated):
    """Reusing the recommendation template would headline a critical alert with
    'Aughor recommendation:' and bury the severity."""
    from aughor.notifications.executor import _build_slack_payload
    trigger = ActionTrigger(id="t1", name="slack", type="slack",
                            url="https://hooks.slack.com/x", channel="#ops")
    alert = MonitorAlert(monitor_id="m1", monitor_name="EMEA margin", conn_id="conn-demo",
                         metric_name="margin_pct", triggered_at="2026-08-14T09:00:00Z",
                         alert_on="below", severity="critical", current_value=8.5,
                         threshold=10.0, message="margin_pct fell below 10.0")
    payload = ActionPayload(investigation_id="monitor:m1", rec_index=0,
                            recommendation="…", metric_name="margin_pct",
                            headline="…", trigger_id="t1", triggered_at="…",
                            context=notify.alert_context(alert))
    body = _build_slack_payload(trigger, payload)
    assert body["text"] == "*Monitor alert*: EMEA margin"
    assert body["attachments"][0]["color"] == "#CD4246"      # critical ≠ house blue
    titles = {f["title"] for f in body["attachments"][0]["fields"]}
    assert {"Severity", "Metric", "Observed", "Connection"} <= titles


def test_slack_recommendation_rendering_is_unchanged():
    """The pre-existing path must not shift — the same trigger serves both."""
    from aughor.notifications.executor import _build_slack_payload
    trigger = ActionTrigger(id="t1", name="slack", type="slack",
                            url="https://hooks.slack.com/x", channel="#ops")
    payload = ActionPayload(investigation_id="inv-12345678", rec_index=0,
                            recommendation="Raise the floor price",
                            metric_name="revenue", headline="Revenue fell",
                            trigger_id="t1", triggered_at="2026-08-14T00:00:00Z")
    body = _build_slack_payload(trigger, payload)
    assert body["text"] == "*Aughor recommendation*: Raise the floor price"
    assert body["attachments"][0]["color"] == "#2D72D2"
