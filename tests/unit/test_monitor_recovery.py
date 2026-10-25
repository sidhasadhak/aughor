"""Arc TC, TC-4 — alerts that close (`aughor/monitors/recovery.py`, flag `monitors.recovery`, off by default).

What these hold, with the flag on: the first check back within its limit after an alert writes ONE *recovered* alert
naming the alert it closes, when, and the value that came back; a second check within its limit writes nothing more;
the next alert after a recovery opens a new one, the grace period notwithstanding; a check says "within its limit"
apart from "suppressed by its grace period"; the alert lists say which recovery closed an alert; a recovery is recorded
and never sent; and every other reader of the alert store reads a recovery as no alert that fired. With the flag off,
the same ticks write the same rows and say the same words as before, and the routes return the rows as they were.

Driven through the monitor effect the heartbeat runs (`automations.engine._dispatch_monitor`) over a stand-in
warehouse whose value the test moves — the stores are the conftest's temp ones.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.connection import DatabaseConnection
from aughor.kernel.flags import EXPERIMENT, FLAG_DEFAULT, FLAG_ENV, FLAG_META, flag_enabled, flag_overrides
from aughor.monitors import recovery
from aughor.monitors.models import Monitor, MonitorAlert

ON = {"monitors.recovery": True}
OFF = {"monitors.recovery": False}


class _Warehouse:
    """A monitor's connection: the real adapters over an `execute` that answers whatever `rows` holds."""
    dialect = "duckdb"

    def __init__(self, value=None, rows=None):
        self.rows_ = rows if rows is not None else [[value]]

    def set(self, value):
        self.rows_ = [[value]]

    def execute(self, label, sql, internal=False):
        cols = [f"c{i}" for i in range(len(self.rows_[0]))] if self.rows_ else ["v"]
        return QueryResult(hypothesis_id=label, sql=sql, columns=cols, rows=self.rows_, row_count=len(self.rows_))

    def get_schema(self):
        return ""

    def close(self):
        pass

    rows = DatabaseConnection.rows
    scalar = DatabaseConnection.scalar


def _watch(**over) -> Monitor:
    base = dict(id="tc4-" + uuid.uuid4().hex[:8], conn_id="tc4-conn-" + uuid.uuid4().hex[:6], name="Units watch",
                alert_on="threshold_cross", custom_sql="SELECT COUNT(*) FROM orders", warning_threshold=10.0,
                threshold_direction="below", grace_period_hours=4.0)
    base.update(over)
    return Monitor(**base)


@pytest.fixture
def heartbeat(monkeypatch):
    """``tick(value)`` runs the monitor effect once over a warehouse reading ``value``; returns the run's message."""
    from aughor.automations.adopt import monitor_as_automation
    from aughor.automations.engine import _dispatch_monitor
    from aughor.automations.models import Effect
    from aughor.monitors.store import upsert_monitor

    watch = _watch()
    upsert_monitor(watch)
    wh = _Warehouse(0)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: wh)

    def tick(value):
        wh.set(value)
        out = _dispatch_monitor(Effect(kind="monitor", config={"monitor_id": watch.id}), monitor_as_automation(watch))
        assert out.status == "executed", out.message
        return out.message

    tick.watch = watch
    return tick


def _alerts(monitor_id: str) -> list[MonitorAlert]:
    from aughor.monitors.store import get_alerts
    return list(reversed(get_alerts(monitor_id=monitor_id, limit=100)))      # oldest first


# ── the flag ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_flag_is_registered_off_with_its_copy_and_its_question():
    assert FLAG_ENV["monitors.recovery"] == "AUGHOR_MONITORS_RECOVERY"
    assert "monitors.recovery" not in FLAG_DEFAULT and flag_enabled("monitors.recovery") is False
    meta = FLAG_META["monitors.recovery"]
    assert meta["label"] and meta["summary"] and meta["facts"] and "Off:" in meta["description"]
    assert "Falsifier" in EXPERIMENT["monitors.recovery"]


# ── an alert that closes ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_first_check_back_within_its_limit_closes_the_alert_once_and_a_new_alert_opens_after(heartbeat):
    mid = heartbeat.watch.id
    with flag_overrides(ON):
        fired = heartbeat(5)
        held = heartbeat(5)
        back = heartbeat(15)
        again = heartbeat(15)
        refired = heartbeat(5)
        back2 = heartbeat(15)

    rows = _alerts(mid)
    assert [(a.alert_on, a.severity) for a in rows] == [
        ("threshold_cross", "warning"), ("recovered", "info"), ("threshold_cross", "warning"), ("recovered", "info")]
    first, rec, second, rec2 = rows

    # the check that fired, the one the grace period held, said apart — never "no alert" for both
    assert fired.startswith("warning: Units watch: 5 below warning threshold 10")
    assert held == ("suppressed by its grace period: a warning alert inside 4h of the last one, not filed"
                    " · read 5 (warning below 10)")
    # one recovery, naming the alert it closes, when, and the value that came back
    when = first.triggered_at[:16].replace("T", " ")
    assert rec.message == (f"Units watch: back within its limit — read 15 (warning below 10). "
                           f"Closes the warning alert of {when} UTC, which read 5.")
    assert (rec.current_value, rec.previous_value, rec.threshold) == (15.0, 5.0, 10.0)
    assert rec.id == recovery.recovery_id(first)
    assert back == (f"within its limit · recovered: closes the warning alert of {when} UTC, which read 5 "
                    f"(recorded here; a recovery is not sent) · read 15 (warning below 10)")
    # a second check within its limit writes nothing more, and says so plainly
    assert again == "within its limit · read 15 (warning below 10)"
    # a new alert after the recovery opens a new one, inside the grace period of the first
    assert refired.startswith("warning: Units watch: 5 below warning threshold 10")
    assert rec2.id == recovery.recovery_id(second) != rec.id and "recovered: closes the warning alert" in back2


def test_off_the_same_ticks_write_the_same_rows_and_say_the_same_words_as_before(heartbeat):
    mid = heartbeat.watch.id
    with flag_overrides(OFF):
        said = [heartbeat(v) for v in (5, 5, 15, 15, 5, 15)]
    assert said[0].startswith("warning: Units watch: 5 below warning threshold 10")
    assert said[1:] == ["no alert · read 5 (warning below 10)", "no alert · read 15 (warning below 10)",
                        "no alert · read 15 (warning below 10)", "no alert · read 5 (warning below 10)",
                        "no alert · read 15 (warning below 10)"]
    assert [(a.alert_on, a.severity) for a in _alerts(mid)] == [("threshold_cross", "warning")]


def test_two_checks_racing_to_close_one_alert_write_one_recovery(heartbeat):
    from aughor.monitors.runner import check_monitor
    from aughor.monitors.store import append_alert

    watch = heartbeat.watch
    with flag_overrides(ON):
        heartbeat(5)
        run = check_monitor(watch, _Warehouse(15), suppress=True)
    with flag_overrides(OFF):           # asked while the alert is open, so only the flag can say no
        assert recovery.recovery_alert(watch, run) is None, "off, no caller can write a recovery"
    with flag_overrides(ON):
        one, two = recovery.recovery_alert(watch, run), recovery.recovery_alert(watch, run)
        append_alert(one[0])
        append_alert(two[0])
    assert [a.alert_on for a in _alerts(watch.id)] == ["threshold_cross", "recovered"]


def test_only_an_alert_from_a_rule_with_a_limit_is_closed():
    from aughor.monitors.store import append_alert

    with flag_overrides(ON):
        m = _watch()
        append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(3), alert_on="threshold_cross", severity="warning"))
        append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(2), alert_on="anomaly", severity="info",
                                  message="baseline building"))
        append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(1), alert_on="query_failing", severity="warning"))
        # an information alert and an alert about running sit above it, and it is still the open one
        assert recovery.open_alert(m.id).alert_on == "threshold_cross"
        n = _watch()
        append_alert(MonitorAlert(monitor_id=n.id, triggered_at=_ago(1), alert_on="trend_reversal", severity="warning"))
        assert recovery.open_alert(n.id) is None, "a trend reversal is an event, not a state that comes back"


# ── what a check found ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_check_says_within_its_limit_only_where_its_rule_judged_a_value_against_a_line():
    from aughor.monitors.runner import WITHIN, check_monitor

    assert check_monitor(_watch(), _Warehouse(15)).outcome == WITHIN
    assert check_monitor(_watch(warning_threshold=None), _Warehouse(15)).outcome == "", "no line, nothing to be within"
    assert check_monitor(_watch(), _Warehouse(None)).outcome == "", "a check that read no value judged nothing"
    assert check_monitor(_watch(alert_on="any_change"), _Warehouse(15)).outcome != WITHIN


def test_freshness_anomaly_and_drift_say_within_their_limit_with_what_they_judged():
    from aughor.monitors.runner import WITHIN, check_monitor

    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    run = check_monitor(_watch(alert_on="data_freshness", freshness_table="orders"), _Warehouse(fresh))
    assert run.outcome == WITHIN and "orders last updated 1.0h ago, inside its 24h" == run.judged_words

    days = [((datetime.now(timezone.utc) - timedelta(days=40 - i)).date().isoformat(), 100.0 + (i % 5)) for i in range(30)]
    run = check_monitor(_watch(alert_on="anomaly", custom_sql="SELECT day, v FROM s"), _Warehouse(rows=[list(d) for d in days]))
    assert run.outcome == WITHIN and "from its rolling mean" in run.judged_words and run.judged == days[-1][1]

    pytest.importorskip("scipy")
    from aughor.monitors.store import append_alert
    drift = _watch(alert_on="segment_drift", dimension_column="region", custom_sql="SELECT r, v FROM s")
    append_alert(MonitorAlert(monitor_id=drift.id, triggered_at=_ago(1), alert_on="segment_drift", severity="info",
                              message="segment baseline recorded"))     # its first run records a baseline instead
    even = [["north", 100.0], ["south", 101.0], ["east", 99.0], ["west", 100.0]]
    run = check_monitor(drift, _Warehouse(rows=even))
    assert run.outcome == WITHIN and run.judged_words.startswith("p=")


# ── the grace period and the baselines ──────────────────────────────────────────────────────────────────────────────

def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def test_a_recovery_ends_the_grace_period_only_with_the_flag_on():
    from aughor.monitors.runner import _suppressed_by_grace
    from aughor.monitors.store import append_alert

    m = _watch()
    append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(1.0), alert_on="threshold_cross", severity="warning"))
    append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(0.5), alert_on="recovered", severity="info"))
    now = MonitorAlert(monitor_id=m.id, triggered_at=_ago(0), alert_on="threshold_cross", severity="warning")
    with flag_overrides(ON):
        assert _suppressed_by_grace(m, now) is False
    with flag_overrides(OFF):
        assert _suppressed_by_grace(m, now) is True


def test_a_recovery_is_never_a_baseline_a_trend_point_or_the_last_alert():
    from aughor.monitors.runner import _last_alert, _last_alert_value
    from aughor.monitors.store import append_alert

    m = _watch()
    append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(1.0), alert_on="threshold_cross", severity="warning",
                              current_value=5.0))
    append_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(0.5), alert_on="recovered", severity="info",
                              current_value=15.0))
    assert _last_alert(m.id).alert_on == "threshold_cross" and _last_alert_value(m.id) == 5.0


# ── not sent ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_recovery_is_recorded_and_never_sent_nor_asked_about(monkeypatch):
    from aughor.monitors import notify

    touched: list[str] = []
    monkeypatch.setattr(notify, "_open_inquiry_for_alert", lambda a, m: touched.append("inquiry"))
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: touched.append("send") or None)
    m = _watch(notification_channel="trg-ops")
    notify.dispatch_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(0), alert_on="recovered", severity="info"), m)
    assert touched == []
    notify.dispatch_alert(MonitorAlert(monitor_id=m.id, triggered_at=_ago(0), alert_on="threshold_cross"), m)
    assert touched == ["inquiry", "send"], "the stand-ins never saw an alert, so the first assertion proved nothing"


# ── the readers ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _closed_pair(heartbeat) -> tuple[MonitorAlert, MonitorAlert]:
    with flag_overrides(ON):
        heartbeat(5)
        heartbeat(15)
    first, rec = _alerts(heartbeat.watch.id)[-2:]
    return first, rec


def test_the_alert_lists_say_which_recovery_closed_an_alert_and_off_return_the_rows_as_they_were(heartbeat):
    from aughor.monitors.store import get_alerts
    from aughor.routers.monitors import get_all_alerts, get_monitor_alerts

    from aughor.monitors.store import append_alert

    # an information alert sits before the recovery, and no recovery closes it
    failing = MonitorAlert(monitor_id=heartbeat.watch.id, conn_id=heartbeat.watch.conn_id, triggered_at=_ago(2),
                           alert_on="threshold_cross", severity="info", message="Units watch: runner error — boom")
    append_alert(failing)
    first, rec = _closed_pair(heartbeat)
    conn = heartbeat.watch.conn_id
    with flag_overrides(ON):
        listed = {a["id"]: a for a in get_all_alerts(conn_id=conn, limit=100, unacknowledged_only=False,
                                                     workspace_id=None)}
        one = {a["id"]: a for a in get_monitor_alerts(heartbeat.watch.id, limit=50, unacknowledged_only=False)}
    for rows in (listed, one):
        assert "closed_by" not in rows[failing.id]
        assert rows[first.id]["closed_by"] == rec.id and rows[first.id]["closed_at"] == rec.triggered_at
        assert rows[rec.id]["closes"] == first.id and "closed_by" not in rows[rec.id]
    with flag_overrides(OFF):
        raw = [a.model_dump() for a in get_alerts(conn_id=conn, limit=100)]
        assert get_all_alerts(conn_id=conn, limit=100, unacknowledged_only=False, workspace_id=None) == raw
        assert get_monitor_alerts(heartbeat.watch.id, limit=50, unacknowledged_only=False) == \
            [a.model_dump() for a in get_alerts(monitor_id=heartbeat.watch.id, limit=50)]


def test_what_waits_on_a_person_is_neither_a_recovery_nor_an_alert_one_closed(heartbeat):
    from aughor.agent.platform_tools import list_monitors

    _closed_pair(heartbeat)
    conn = heartbeat.watch.conn_id
    with flag_overrides(ON):
        assert list_monitors(conn, {})["unacknowledged_alerts"] == 0
    with flag_overrides(OFF):
        assert list_monitors(conn, {})["unacknowledged_alerts"] == 1, "off, the alert waits as before"


def test_a_recovery_is_no_alert_that_fired_to_the_other_readers(heartbeat):
    from types import SimpleNamespace

    from aughor.knowledge.period_brief import alert_findings
    from aughor.monitors.alert_summary import build_alert_summary
    from aughor.monitors.missed import _fired_around

    first, rec = _closed_pair(heartbeat)
    conn, mid = heartbeat.watch.conn_id, heartbeat.watch.id
    summary = build_alert_summary(conn, period="day")
    assert summary.alert_count == 1
    lines = next(s for s in summary.sections if s.kind == "monitor_alerts").items
    assert any(line.startswith("🟢") and "back within its limit" in line for line in lines)
    today = datetime.now(timezone.utc).date()
    window = SimpleNamespace(start=today, end=today + timedelta(days=1))
    assert [f["id"] for f in alert_findings(conn, window)] == [f"alert::{first.id}"]
    assert _fired_around(mid, today) == [first.triggered_at]


def test_a_missions_watch_counts_the_alerts_that_fired_not_their_recovery(heartbeat):
    from aughor.record import mission as M

    _closed_pair(heartbeat)
    conn = heartbeat.watch.conn_id
    m = M.write_mission(M.Mission(
        name="Keep units up " + uuid.uuid4().hex[:4], objective=M.Objective(metric="units", direction="up", spec=None),
        scope=M.Scope(connections=[conn]), owner="user:ana", review=M.Review(cadence="weekly"), state="active",
        watches=[M.Watch(kind="monitor", ref=heartbeat.watch.id, label="units")]), by="user:ana")
    report = M.compose_report(m, run_sql_for=lambda c: (lambda sql: []), now=datetime.now(timezone.utc) + timedelta(hours=1))
    assert report["watches"][0]["state"] == "fired 1 time this period"
