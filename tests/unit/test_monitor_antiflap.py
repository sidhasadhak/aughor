"""Monitor anti-flap (debounce) — a sustained breach must alert once, then at most
once per grace window, not every cron tick; escalations fire immediately; the
manual "test now" path bypasses suppression. See aughor/monitors/runner.py.
"""
from datetime import datetime, timedelta, timezone

import aughor.monitors.runner as runner
from aughor.monitors.models import Monitor, MonitorAlert


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _alert(sev: str, hours_ago: float = 0.0) -> MonitorAlert:
    return MonitorAlert(monitor_id="m", triggered_at=_iso(hours_ago), severity=sev, message="x")


def _mon(grace: float = 4.0) -> Monitor:
    return Monitor(conn_id="c", name="n", grace_period_hours=grace)


# ── _suppressed_by_grace core logic ───────────────────────────────────────────

def test_first_alert_never_suppressed(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert", lambda mid: None)
    assert runner._suppressed_by_grace(_mon(), _alert("warning")) is False


def test_same_severity_within_grace_is_suppressed(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert", lambda mid: _alert("warning", hours_ago=1))
    assert runner._suppressed_by_grace(_mon(grace=4), _alert("warning")) is True


def test_same_severity_after_grace_fires_again(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert", lambda mid: _alert("warning", hours_ago=5))
    assert runner._suppressed_by_grace(_mon(grace=4), _alert("warning")) is False


def test_escalation_fires_immediately(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert", lambda mid: _alert("warning", hours_ago=1))
    assert runner._suppressed_by_grace(_mon(grace=4), _alert("critical")) is False


def test_deescalation_suppressed_within_grace(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert", lambda mid: _alert("critical", hours_ago=1))
    assert runner._suppressed_by_grace(_mon(grace=4), _alert("warning")) is True


def test_grace_zero_disables_suppression(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert", lambda mid: _alert("warning", hours_ago=0.1))
    assert runner._suppressed_by_grace(_mon(grace=0), _alert("warning")) is False


# ── run_monitor wiring (suppress flag) ────────────────────────────────────────

def test_run_monitor_applies_debounce_by_default(monkeypatch):
    m = Monitor(conn_id="c", name="n", alert_on="threshold_cross")
    monkeypatch.setattr(runner, "run_threshold_monitor", lambda mon, db: _alert("warning"))
    monkeypatch.setattr(runner, "_suppressed_by_grace", lambda mon, a: True)
    assert runner.run_monitor(m, db=None) is None                    # debounced
    assert runner.run_monitor(m, db=None, suppress=False) is not None  # manual test bypasses


def test_run_monitor_fires_when_not_suppressed(monkeypatch):
    m = Monitor(conn_id="c", name="n", alert_on="threshold_cross")
    monkeypatch.setattr(runner, "run_threshold_monitor", lambda mon, db: _alert("critical"))
    monkeypatch.setattr(runner, "_suppressed_by_grace", lambda mon, a: False)
    out = runner.run_monitor(m, db=None)
    assert out is not None and out.severity == "critical"
