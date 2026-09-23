"""Idea 6 · alerts that prove they work — one rule, a backtest before, a fire drill after.

The runner, the Watcher's replay and the backtest share `monitors/rules.py`; a backtest
replays a monitor's own series and names the days; a drill feeds the runner a synthetic
outlier through a stand-in connection, delivers the [DRILL] alert through the real
channel when asked, never files it, and is read back as "last proven working".
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from aughor.monitors import backtest as bt_mod, drill as drill_mod
from aughor.monitors.backtest import Backtest, backtest_monitor, series_sql_for
from aughor.monitors.drill import DRILL_PREFIX, DrillConnection, drill_monitor, proof
from aughor.monitors.models import Monitor
from aughor.monitors.rules import anomaly_verdict, threshold_verdict

D0 = date(2025, 9, 1)


def _monitor(**kw) -> Monitor:
    base = dict(id="m1", conn_id="c1", name="Orders anomaly", alert_on="anomaly",
                custom_sql="SELECT day, n FROM daily_orders", sigma_threshold=3.0,
                notification_channel="in_app")
    base.update(kw)
    return Monitor(**base)


def _series(n=420, base=100.0, spikes=None):
    pts = []
    for i in range(n):
        v = base + (i % 5) * 1.0
        if spikes and i in spikes:
            v = spikes[i]
        pts.append((D0 + timedelta(days=i), v))
    return pts


# ── one rule ─────────────────────────────────────────────────────────────────────

def test_the_anomaly_rule_is_the_runners_rule():
    hist = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
    quiet = anomaly_verdict(hist, 101.0, 3.0)
    assert not quiet.fired and quiet.z < 1.0
    loud = anomaly_verdict(hist, 140.0, 3.0)
    assert loud.fired and loud.direction == "above" and loud.severity == "critical"
    assert anomaly_verdict(hist[:4], 140.0, 3.0).fired is False        # fewer than 5: baseline building
    assert anomaly_verdict([5.0] * 10, 500.0, 3.0).fired is False       # no variance: nothing to detect
    warn = anomaly_verdict(hist, 100.0 + 3.2 * loud.std, 3.0)
    assert warn.fired and warn.severity == "warning"


def test_the_threshold_rule_is_critical_first():
    assert threshold_verdict(12.0, direction="above", warning=10.0, critical=11.0).severity == "critical"
    assert threshold_verdict(10.5, direction="above", warning=10.0, critical=11.0).severity == "warning"
    assert threshold_verdict(9.0, direction="above", warning=10.0, critical=11.0).fired is False
    assert threshold_verdict(9.0, direction="below", warning=10.0, critical=None).severity == "warning"


# ── the backtest ─────────────────────────────────────────────────────────────────

def test_the_backtest_names_how_often_and_on_which_days():
    today = D0 + timedelta(days=420)
    # Three spikes on Mondays, one on a Thursday, inside the last year.
    mondays = [i for i in range(60, 420) if (D0 + timedelta(days=i)).weekday() == 0][:3]
    thursday = next(i for i in range(200, 420) if (D0 + timedelta(days=i)).weekday() == 3)
    pts = _series(420, spikes={**{i: 400.0 for i in mondays}, thursday: 400.0})
    rows = [(d.isoformat(), v) for d, v in pts]
    bt = backtest_monitor(_monitor(), run_sql=lambda sql: (["day", "n"], rows, None), today=today)
    assert bt.ok and bt.rule == "anomaly" and bt.sigma == 3.0
    assert bt.count == 4 and bt.by_weekday == {"Monday": 3, "Thursday": 1}
    assert [f.severity for f in bt.firings] == ["critical"] * 4
    assert bt.sentence == "would have fired 4 times in the last 365 days, 3 of them Mondays."
    assert bt.days == 365 and bt.quieter_sigma is None


def test_a_noisy_backtest_offers_the_quieter_sigma(monkeypatch):
    today = D0 + timedelta(days=420)
    # Modest spikes every fortnight: the first ones fire at 2.5σ, and as they enter the
    # history σ grows until a higher rung on the ladder would have stayed quiet.
    spikes = {60 + 14 * k: 109.0 for k in range(25)}
    pts = _series(420, spikes=spikes)
    rows = [(d.isoformat(), v) for d, v in pts]
    monkeypatch.setattr(bt_mod, "MAX_FIRINGS_PER_YEAR", 3)
    bt = backtest_monitor(_monitor(sigma_threshold=2.5), run_sql=lambda sql: (["day", "n"], rows, None), today=today)
    assert bt.ok and bt.count > 3
    # The expectation is derived with the shared rule itself: the wiring is what is tested here.
    values = [v for _, v in pts][-(bt_mod.BACKTEST_DAYS + 30):]
    counts = {s: sum(1 for i in range(len(values)) if anomaly_verdict(values[:i], values[i], s).fired)
              for s in bt_mod.SIGMA_LADDER}
    expected = next((s for s in bt_mod.SIGMA_LADDER if s > 2.5 and counts[s] <= 3), None)
    assert bt.quieter_sigma == expected
    if expected is None:
        assert "would have fired at most" not in bt.sentence
    else:
        assert f"{expected}σ would have fired at most 3 times" in bt.sentence


def test_still_settling_days_are_not_replayed(monkeypatch):
    monkeypatch.setattr("aughor.settling.learned_lag_days", lambda cid: 8)
    today = D0 + timedelta(days=420)
    rows = [(d.isoformat(), v) for d, v in _series(420, spikes={417: 900.0})]   # 3 days old: still settling
    bt = backtest_monitor(_monitor(), run_sql=lambda sql: (["day", "n"], rows, None), today=today)
    assert bt.ok and bt.settle_days == 8 and bt.count == 0
    assert bt.series_to == (today - timedelta(days=8)).isoformat()
    assert bt.sentence.endswith("(the youngest 8 days are still settling and were not replayed).")


def test_a_threshold_monitor_replays_its_line():
    today = D0 + timedelta(days=420)
    rows = [(d.isoformat(), v) for d, v in _series(420, spikes={300: 150.0, 310: 121.0})]
    m = _monitor(alert_on="threshold_cross", threshold_direction="above", warning_threshold=120.0,
                 critical_threshold=140.0)
    bt = backtest_monitor(m, run_sql=lambda sql: (["day", "n"], rows, None), today=today)
    assert bt.ok and bt.rule == "threshold" and bt.sigma is None
    assert [(f.value, f.severity) for f in bt.firings] == [(150.0, "critical"), (121.0, "warning")]


def test_what_cannot_be_replayed_says_why():
    today = D0 + timedelta(days=420)
    scalar = backtest_monitor(_monitor(), run_sql=lambda sql: (["n"], [(42,)], None), today=today)
    assert not scalar.ok and "returned no (day, value) series" in scalar.reason
    stale = [(d.isoformat(), v) for d, v in _series(30)]
    old = backtest_monitor(_monitor(), run_sql=lambda sql: (["day", "n"], stale, None), today=today)
    assert not old.ok and old.reason.startswith("the series ends on 2025-09-30 — stale, or truncated")
    none = backtest_monitor(_monitor(custom_sql=None, metric_name=None),
                            run_sql=lambda sql: ([], [], None), today=today)
    assert not none.ok and none.reason == "nothing to replay: the monitor has neither SQL nor a metric"
    drift = backtest_monitor(_monitor(alert_on="segment_drift"),
                             run_sql=lambda sql: (["day", "n"], [(d.isoformat(), v) for d, v in _series(420)], None),
                             today=today)
    assert not drift.ok and "no day-by-day rule to replay" in drift.reason


def test_a_metric_monitor_is_replayed_as_its_definition_per_day(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("aughor.semantic.metrics.get_metric",
                        lambda name, connection_id=None: SimpleNamespace(
                            name=name, sql="COUNT(*)", tables=["orders"], filters=["status = 'Complete'"]))
    monkeypatch.setattr("aughor.settling.sampler.time_tables", lambda cid: [("thelook.orders", "created_at", 10)])
    sql, how = series_sql_for(_monitor(custom_sql=None, metric_name="orders"), since=date(2025, 8, 1))
    assert how == "metric 'orders' per day"
    assert sql.startswith('SELECT CAST("created_at" AS DATE) AS day, (COUNT(*)) AS value FROM orders WHERE')
    assert "DATE '2025-08-01'" in sql


# ── the drill ────────────────────────────────────────────────────────────────────

@pytest.fixture
def drills(tmp_path, monkeypatch):
    monkeypatch.setattr(drill_mod, "_path", lambda: tmp_path / "monitor_drills.json")
    return tmp_path


def test_the_stand_in_serves_a_quiet_series_and_an_outlier_on_the_newest_settled_day():
    db = DrillConnection(_monitor(), today=date(2026, 9, 23), settle_days=8)
    assert len(db.series) == 31 and db.series[-1][0] == "2026-09-15"
    assert db.series[-1][1] == db.outlier and db.outlier > 130.0
    assert db.scalar("SELECT 1") == db.outlier
    with pytest.raises(RuntimeError):
        db.execute("__monitor__", "DELETE FROM orders")


def test_a_drill_fires_the_rule_and_never_files_the_alert(drills, monkeypatch):
    filed: list = []
    monkeypatch.setattr("aughor.monitors.store.append_alert", lambda a: filed.append(a))
    d = drill_monitor(_monitor(), deliver=True, today=date(2026, 9, 23), settle_days=1)
    assert d.fired and d.severity == "critical" and d.delivered is None
    assert d.message.startswith(f"{DRILL_PREFIX} Orders anomaly: anomaly detected")
    assert "in-app only" in d.detail
    assert filed == []
    assert proof(_monitor())["sentence"].startswith("the rule fired in a drill on")


def test_a_drill_delivers_through_the_real_channel_marked_as_a_drill(drills, monkeypatch):
    from types import SimpleNamespace
    sent: list = []

    def fake_dispatch(alert, monitor=None):
        sent.append((alert, monitor))
        return SimpleNamespace(id="log-1", status="ok", error=None)

    monkeypatch.setattr("aughor.monitors.notify.dispatch_alert", fake_dispatch)
    m = _monitor(notification_channel="trig-slack")
    d = drill_monitor(m, deliver=True, today=date(2026, 9, 23), settle_days=1)
    assert d.proven and d.delivered is True and d.delivery_log_id == "log-1"
    assert d.detail == "delivered through trigger 'trig-slack'"
    alert, mon = sent[0]
    assert alert.id.startswith("drill-") and alert.message.startswith(DRILL_PREFIX) and mon is m
    assert proof(m)["sentence"].startswith("last proven working") and "trig-slack" in proof(m)["sentence"]

    monkeypatch.setattr("aughor.monitors.notify.dispatch_alert", lambda alert, monitor=None: None)
    gone = drill_monitor(m, deliver=True, today=date(2026, 9, 23), settle_days=1)
    assert gone.fired and gone.delivered is False and "nothing was sent" in gone.detail


def test_a_drill_that_stops_before_the_transport_says_so(drills):
    d = drill_monitor(_monitor(notification_channel="trig-slack"), deliver=False,
                      today=date(2026, 9, 23), settle_days=1)
    assert d.fired and d.delivered is None and d.detail == "the rule fired (critical); delivery not attempted"


def test_a_threshold_drill_crosses_the_line(drills):
    m = _monitor(alert_on="threshold_cross", custom_sql="SELECT n FROM x", threshold_direction="below",
                 warning_threshold=50.0, critical_threshold=None)
    d = drill_monitor(m, deliver=False, today=date(2026, 9, 23), settle_days=1)
    assert d.fired and d.severity == "warning"


def test_a_never_proven_monitor_says_so(drills, monkeypatch):
    monkeypatch.setattr("aughor.notifications.store.list_logs", lambda limit=100, trigger_id=None: [])
    assert proof(_monitor(id="m-new"))["sentence"] == "never proven — no drill, no delivered alert"


def test_the_doors(drills, monkeypatch):
    from fastapi.testclient import TestClient

    from aughor.api import app

    m = _monitor(id="m-door")
    monkeypatch.setattr("aughor.routers.monitors.get_monitor", lambda mid: m if mid == "m-door" else None)
    monkeypatch.setattr("aughor.monitors.backtest.backtest_monitor",
                        lambda monitor, run_sql=None, today=None: Backtest(monitor.id, "anomaly", True, sentence="never"))
    client = TestClient(app)
    assert client.post("/monitors/m-door/backtest").json()["sentence"] == "never"
    drilled = client.post("/monitors/m-door/drill", json={"deliver": False}).json()
    assert drilled["fired"] is True and drilled["delivered"] is None
    assert client.get("/monitors/m-door/proof").json()["sentence"].startswith("the rule fired in a drill")
    assert client.post("/monitors/nope/backtest").status_code == 404
