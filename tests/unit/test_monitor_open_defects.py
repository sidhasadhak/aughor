"""The monitor defects ROADMAP §3.26 left open, fixed under ED-0 (§3.58).

Each test is the defect's own failure, driven through the code that had it:

1. an anomaly check over a category breakdown z-scored the categories as days;
2. ``grace_period_hours`` was never saved, so every monitor read back the 4-hour default;
3. the form offered "slack" and "email", which are no trigger's id, so such a monitor sent nothing;
4. a monitor over a metric with no dates ran the bare expression ("SUM(x)") as a statement;
5. "Run now" filed a real alert past the debounce and sent it;
6. an automation naming a monitor checked it on every 60-second tick, not on the monitor's cron;
8. the Hub map listed automations and no monitors.

(7, the ``monitors.guarded`` flag, was stale words only: the guard is unconditional since 2026-08-06.)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import duckdb
import pytest
from fastapi import HTTPException

import aughor.monitors.store as store
from aughor.monitors import runner
from aughor.monitors.models import Monitor


@pytest.fixture()
def monitors(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "monitors.db")
    store._init_schema()
    return store


class _Rows:
    """A connection whose `rows` returns what it was given, and records what it was asked."""

    def __init__(self, rows):
        self._rows, self.asked = rows, []

    def rows(self, sql, *, label, sql_dialect, strict, internal=False):
        self.asked.append(sql)
        return list(self._rows)


# ── 1 · an anomaly check reads days, or says it cannot ──────────────────────────

def test_an_anomaly_check_over_a_category_breakdown_is_a_failed_run():
    """theLook's one anomaly monitor watches revenue BY CATEGORY. Its rows were scored as days."""
    m = Monitor(conn_id="c1", name="Outerwear watch", alert_on="anomaly",
                custom_sql="SELECT category, SUM(sale_price) FROM t GROUP BY 1")
    db = _Rows([("Outerwear & Coats", 120.0), ("Jeans", 80.0), ("Tops", 60.0), ("Socks", 9.0),
                ("Suits", 300.0), ("Swim", 40.0)])
    run = runner.check_monitor(m, db, suppress=False)
    assert run.alert is None
    assert "not a date" in run.failed and "Outerwear & Coats" in run.failed


def test_an_anomaly_series_is_scored_on_its_newest_day_whatever_the_row_order():
    m = Monitor(conn_id="c1", name="Orders watch", alert_on="anomaly", sigma_threshold=2.0,
                custom_sql="SELECT day, n FROM t")
    days = [(f"2026-09-{d:02d}", 100.0 + (d % 3)) for d in range(1, 11)]
    spike = ("2026-09-11", 500.0)
    db = _Rows([spike, *days[::-1], (None, 1.0)])          # newest first, and one row with no date
    run = runner.check_monitor(m, db, suppress=False)
    assert run.failed == ""
    assert run.alert is not None and run.alert.current_value == 500.0


# ── 2 · the grace period is saved ───────────────────────────────────────────────

def test_a_grace_period_reads_back_as_it_was_set(monitors):
    m = Monitor(conn_id="c1", name="m", custom_sql="SELECT 1", grace_period_hours=0.0)
    monitors.upsert_monitor(m)
    assert monitors.get_monitor(m.id).grace_period_hours == 0.0
    monitors.upsert_monitor(monitors.get_monitor(m.id).model_copy(update={"grace_period_hours": 12.5}))
    assert monitors.get_monitor(m.id).grace_period_hours == 12.5


def test_the_routes_carry_the_grace_period(monitors, monkeypatch):
    from aughor.routers import monitors as routes

    monkeypatch.setattr("aughor.security.authz.check_owner", lambda *a, **k: None)
    monkeypatch.setattr("aughor.security.authz.get_principal", lambda _r: None)
    monkeypatch.setattr(routes, "_validate_custom_sql", lambda *a: None)
    made = routes.create_monitor(routes.CreateMonitorRequest(
        conn_id="c1", name="m", custom_sql="SELECT 1", grace_period_hours=1.5), request=None)
    assert monitors.get_monitor(made["id"]).grace_period_hours == 1.5
    routes.update_monitor(made["id"], routes.UpdateMonitorRequest(grace_period_hours=0.0))
    assert monitors.get_monitor(made["id"]).grace_period_hours == 0.0


# ── 3 · a channel names a destination ───────────────────────────────────────────

def test_a_channel_that_names_no_trigger_is_refused(monitors, monkeypatch):
    from aughor.routers import monitors as routes

    monkeypatch.setattr("aughor.security.authz.check_owner", lambda *a, **k: None)
    monkeypatch.setattr("aughor.security.authz.get_principal", lambda _r: None)
    monkeypatch.setattr(routes, "_validate_custom_sql", lambda *a: None)
    monkeypatch.setattr("aughor.notifications.store.get_trigger",
                        lambda tid: SimpleNamespace(id=tid) if tid == "trg-1" else None)
    for word in ("slack", "email"):
        with pytest.raises(HTTPException) as exc:
            routes.create_monitor(routes.CreateMonitorRequest(
                conn_id="c1", name="m", custom_sql="SELECT 1", notification_channel=word), request=None)
        assert exc.value.status_code == 422 and repr(word) in exc.value.detail
    made = routes.create_monitor(routes.CreateMonitorRequest(
        conn_id="c1", name="m", custom_sql="SELECT 1", notification_channel="trg-1"), request=None)
    assert made["notification_channel"] == "trg-1"


def test_a_monitor_saved_before_the_check_can_still_be_edited(monitors, monkeypatch):
    """Refused where it is chosen, not wherever it is carried: an edit that leaves a stored "slack" alone goes through,
    and the form shows the person that it names no destination."""
    from aughor.routers import monitors as routes

    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: None)
    m = Monitor(conn_id="c1", name="old", custom_sql="SELECT 1", notification_channel="slack")
    monitors.upsert_monitor(m)
    out = routes.update_monitor(m.id, routes.UpdateMonitorRequest(name="renamed", notification_channel="slack"))
    assert out["name"] == "renamed"


# ── 4 · a metric's value is read through its statement ──────────────────────────

def test_an_undated_metric_monitor_reads_a_value(monkeypatch):
    from aughor.semantic.metrics import MetricDefinition

    metric = MetricDefinition(name="units", label="Units", sql="SUM(qty)", tables=["sales"],
                              filters=["status <> 'void'"], connection="c1")
    monkeypatch.setattr(runner, "_metric_of", lambda _m: metric)
    con = duckdb.connect()
    con.execute("CREATE TABLE sales (qty INT, status VARCHAR)")
    con.execute("INSERT INTO sales VALUES (5, 'ok'), (7, 'ok'), (100, 'void')")

    def scalar(sql, *, label, cast, sql_dialect, strict):
        row = con.execute(sql).fetchone()
        return cast(row[0]) if row and row[0] is not None else None

    m = Monitor(conn_id="c1", name="Units floor", metric_name="units", alert_on="threshold_cross",
                threshold_direction="below", warning_threshold=20.0)
    run = runner.check_monitor(m, SimpleNamespace(scalar=scalar, dialect="duckdb"), suppress=False)
    assert run.failed == "" and run.reading == 12.0            # the filter is the definition: 100 void units out
    assert run.alert is not None and run.alert.severity == "warning"
    con.close()


# ── 5 · Run now shows its verdict and files nothing ─────────────────────────────

def test_run_now_files_and_sends_nothing(monitors, monkeypatch):
    from aughor.monitors import scheduler

    m = Monitor(conn_id="c1", name="Always", custom_sql="SELECT 1", alert_on="threshold_cross",
                threshold_direction="above", warning_threshold=0.0)
    monitors.upsert_monitor(m)
    sent: list = []
    monkeypatch.setattr("aughor.monitors.notify.dispatch_alert", lambda *a, **k: sent.append(a))
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda _c: SimpleNamespace(scalar=lambda *a, **k: 5.0, close=lambda: None))
    alert, said = scheduler.trigger_now_read(m.id)
    assert alert is not None and alert.severity == "warning" and "read 5" in said
    assert monitors.get_alerts(m.id) == [] and sent == []


# ── 6 · a chain checks a monitor on the monitor's own cadence ───────────────────

def test_a_metric_condition_is_checked_on_its_monitors_cron(monitors, monkeypatch):
    from aughor.automations import engine
    from aughor.automations.models import Automation, Condition, Effect

    m = Monitor(conn_id="c1", name="Hourly", custom_sql="SELECT 1", check_cron="0 * * * *")
    monitors.upsert_monitor(m)
    auto = Automation(id="ed0-chain", conn_id="c1", name="chain",
                      conditions=[Condition(kind="metric", config={"monitor_id": m.id})],
                      effects=[Effect(kind="notify", config={"trigger_id": "t", "message": "x"})])
    probed: list = []

    def probe(cond, a):
        probed.append(cond.monitor_id)
        return False, "no alert"

    last = SimpleNamespace(started_at="2026-10-24T10:00:30Z")
    monkeypatch.setattr(engine, "last_run", lambda _id: last)
    monkeypatch.setattr(engine, "last_delivery_claim", lambda _id: None)
    quiet = datetime(2026, 10, 24, 10, 31, tzinfo=timezone.utc)
    fired, _details, reason = engine.evaluate_conditions(auto, now=quiet, probe=probe)
    assert not fired and probed == [] and "not checked on this tick" in reason

    engine.evaluate_conditions(auto, now=quiet + timedelta(minutes=30), probe=probe)     # 11:01, past the hour
    assert probed == [m.id]

    engine.evaluate_conditions(auto, now=quiet, probe=probe, manual=True)                # a person asked
    assert probed == [m.id, m.id]


# ── 8 · the Hub map lists monitors ──────────────────────────────────────────────

def test_the_hub_map_lists_monitors(monitors, monkeypatch):
    from aughor.hub.map import hub_map

    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: None)
    on = Monitor(conn_id="ed0-hub", name="GMV floor", custom_sql="SELECT 1")
    off = Monitor(conn_id="ed0-hub", name="Old watch", custom_sql="SELECT 1", enabled=False,
                  notification_channel="slack")
    monitors.upsert_monitor(on)
    monitors.upsert_monitor(off)
    body = hub_map("ed0-hub")
    rows = {r["name"]: r for r in body["rows"]}
    assert rows["GMV floor"]["kind"] == "monitor" and rows["GMV floor"]["state"] == "live"
    assert rows["GMV floor"]["destinations"] == [{"kind": "in_app", "target": ""}]
    assert rows["Old watch"]["state"] == "disabled" and rows["Old watch"]["destinations"][0]["missing"] is True
    assert body["totals"]["monitors"] == 2
