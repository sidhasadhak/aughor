"""Graduate-card-to-Monitor endpoint (Briefing cockpit, Slice 4 — watch → alert).

The card's guarded SQL becomes a scheduled threshold Monitor, and the thresholds + monitor id
are recorded back on the card. The monitor store + scheduler are stubbed so the test stays
hermetic (no real monitor persisted / scheduled); the dashboard store is isolated by conftest.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.dashboard.models import DashboardCard
from aughor.dashboard.store import get_card, upsert_card

client = TestClient(app)


def _stub_monitor(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("aughor.monitors.store.upsert_monitor",
                        lambda m: captured.setdefault("monitor", m) or m)
    monkeypatch.setattr("aughor.monitors.scheduler.reload_monitor", lambda m: None)
    return captured


def _card(sql: str = "SELECT SUM(gmv) FROM orders") -> DashboardCard:
    return upsert_card(DashboardCard(
        connection_id="workspace", scope="connection", scope_ref="workspace",
        kind="kpi", title="GMV total", sql=sql,
    ))


def test_graduate_creates_monitor_and_marks_card(monkeypatch):
    cap = _stub_monitor(monkeypatch)
    card = _card()
    r = client.post(f"/cards/{card.id}/graduate",
                    json={"warning_threshold": 100, "critical_threshold": 50, "threshold_direction": "below"})
    assert r.status_code == 201, r.text

    m = cap["monitor"]
    assert m.custom_sql == "SELECT SUM(gmv) FROM orders"    # the card's guarded SQL
    assert m.reanchor_window is True                        # frozen window can't go stale
    assert m.alert_on == "threshold_cross"
    assert m.warning_threshold == 100 and m.critical_threshold == 50

    stored = get_card(card.id)                              # thresholds recorded back on the card
    assert stored.thresholds["warning"] == 100
    assert stored.thresholds["direction"] == "below"
    assert stored.thresholds["monitor_id"] == m.id
    assert r.json()["monitor"]["custom_sql"] == "SELECT SUM(gmv) FROM orders"


def test_graduate_requires_a_threshold(monkeypatch):
    _stub_monitor(monkeypatch)
    card = _card()
    r = client.post(f"/cards/{card.id}/graduate", json={})
    assert r.status_code == 422                             # no warning/critical → refused


def test_graduate_missing_card_is_404(monkeypatch):
    _stub_monitor(monkeypatch)
    r = client.post("/cards/nope/graduate", json={"warning_threshold": 1})
    assert r.status_code == 404


def test_graduate_card_without_sql_is_422(monkeypatch):
    _stub_monitor(monkeypatch)
    card = _card(sql="")
    r = client.post(f"/cards/{card.id}/graduate", json={"warning_threshold": 1})
    assert r.status_code == 422
