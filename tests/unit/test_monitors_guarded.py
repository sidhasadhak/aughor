"""WP-1b (platform review 2026-07-12) — guarded monitor evaluations.

Monitors run user `custom_sql` on a schedule with no correctness battery: a
wrong-grain SUM / id-arithmetic product silently mis-values the metric and then
ALERTS on it. Under `monitors.guarded` (default off) the runner attaches a
deterministic caveat to the fired alert; create/update reject mutating or
non-binding custom SQL with an explicit 422 instead of a silent never-fires.
"""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from aughor.monitors.models import Monitor, MonitorAlert
from aughor.monitors.runner import run_monitor
from aughor.util.time import now_iso


def _monitor(**over) -> Monitor:
    base = dict(
        conn_id="wp1b-conn",
        name="revenue watch",
        alert_on="threshold_cross",
        custom_sql="SELECT SUM(amt * order_id) AS x FROM sales",
        warning_threshold=10.0,
        threshold_direction="above",
    )
    base.update(over)
    return Monitor(**base)


class _StubDB:
    dialect = "duckdb"

    def rows(self, sql, label=None):
        return [[999.0]]

    def scalar(self, sql, label=None, cast=float):
        return 999.0

    def get_schema(self):
        return "TABLE: sales\n  order_id  INTEGER\n  amt  DOUBLE\n"


# ── Runner: flag-gated caveat ─────────────────────────────────────────────────

def test_guarded_off_is_byte_identical(monkeypatch):
    monkeypatch.delenv("AUGHOR_MONITORS_GUARDED", raising=False)
    alert = run_monitor(_monitor(), _StubDB(), suppress=False)
    assert alert is not None and alert.severity == "warning"
    assert alert.caveat is None  # default off — no probe, no field


def test_guarded_attaches_id_arithmetic_caveat(monkeypatch):
    monkeypatch.setenv("AUGHOR_MONITORS_GUARDED", "1")
    alert = run_monitor(_monitor(), _StubDB(), suppress=False)
    assert alert is not None
    assert alert.caveat and "id-arithmetic" in alert.caveat, alert.caveat
    # Caveat-and-deliver: the alert itself still fired, unchanged.
    assert alert.severity == "warning" and alert.current_value == 999.0


def test_guarded_quiet_on_clean_sql(monkeypatch):
    monkeypatch.setenv("AUGHOR_MONITORS_GUARDED", "1")
    m = _monitor(custom_sql="SELECT SUM(amt) AS x FROM sales")
    alert = run_monitor(m, _StubDB(), suppress=False)
    assert alert is not None
    assert alert.caveat is None  # no finding → no caveat


def test_guarded_skips_bare_scalar_expression(monkeypatch):
    monkeypatch.setenv("AUGHOR_MONITORS_GUARDED", "1")
    m = _monitor(custom_sql="1 + 1")  # no FROM — nothing the AST probes can see
    alert = run_monitor(m, _StubDB(), suppress=False)
    assert alert is not None and alert.caveat is None


# ── Store: caveat round-trips (exercises the v2 migration) ────────────────────

def test_alert_caveat_roundtrips_through_store():
    from aughor.monitors.store import append_alert, get_alerts

    a = MonitorAlert(monitor_id="wp1b-m1", monitor_name="w", conn_id="c",
                     triggered_at=now_iso(), severity="warning",
                     message="crossed", caveat="id-arithmetic guard: SUM(amt * order_id)")
    append_alert(a)
    got = [x for x in get_alerts(monitor_id="wp1b-m1") if x.id == a.id]
    assert got and got[0].caveat == a.caveat


def test_alert_without_caveat_roundtrips_none():
    from aughor.monitors.store import append_alert, get_alerts

    a = MonitorAlert(monitor_id="wp1b-m2", monitor_name="w", conn_id="c",
                     triggered_at=now_iso(), severity="info", message="ok")
    append_alert(a)
    got = [x for x in get_alerts(monitor_id="wp1b-m2") if x.id == a.id]
    assert got and got[0].caveat is None


# ── Router: create/update validation ─────────────────────────────────────────

@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


def _register_conn(tmp_path):
    import duckdb
    from aughor.db import registry
    p = tmp_path / "mon.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE sales (order_id INT, amt DOUBLE)")
    con.execute("INSERT INTO sales VALUES (1, 10.0)")
    con.close()
    return registry.add_connection("wp1b-mon", "duckdb", str(p))


def test_create_rejects_mutating_custom_sql(client, tmp_path):
    cid = _register_conn(tmp_path)
    r = client.post("/monitors", json={
        "conn_id": cid, "name": "bad", "custom_sql": "DELETE FROM sales",
        "alert_on": "threshold_cross", "warning_threshold": 1.0,
    })
    assert r.status_code == 422
    assert "custom_sql rejected" in r.json()["detail"]


def test_create_rejects_nonbinding_custom_sql(client, tmp_path):
    cid = _register_conn(tmp_path)
    r = client.post("/monitors", json={
        "conn_id": cid, "name": "bad-bind",
        "custom_sql": "SELECT no_such_col FROM sales",
        "alert_on": "threshold_cross", "warning_threshold": 1.0,
    })
    assert r.status_code == 422
    assert "does not bind" in r.json()["detail"]


def test_create_accepts_clean_custom_sql(client, tmp_path):
    cid = _register_conn(tmp_path)
    r = client.post("/monitors", json={
        "conn_id": cid, "name": "ok", "custom_sql": "SELECT SUM(amt) FROM sales",
        "alert_on": "threshold_cross", "warning_threshold": 1.0,
    })
    assert r.status_code == 201, r.text


def test_update_validates_new_custom_sql(client, tmp_path):
    cid = _register_conn(tmp_path)
    created = client.post("/monitors", json={
        "conn_id": cid, "name": "ok2", "custom_sql": "SELECT SUM(amt) FROM sales",
        "alert_on": "threshold_cross", "warning_threshold": 1.0,
    }).json()
    r = client.put(f"/monitors/{created['id']}",
                   json={"custom_sql": "DROP TABLE sales"})
    assert r.status_code == 422
