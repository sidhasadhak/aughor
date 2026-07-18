"""Run/refresh endpoint (Briefing cockpit, Slice 0 → sets up Slice 1's trend).

Verifies: a single numeric cell becomes the card's tracked value and rolls the previous one
into prev_value (delta); multi-row/error results don't set a scalar; a note card is a no-op;
missing card 404s. Connection + guard are stubbed to stay hermetic.
"""
from __future__ import annotations

import types

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.dashboard.models import DashboardCard
from aughor.dashboard.store import get_card, upsert_card
from aughor.platform.contracts.execution import QueryResult

client = TestClient(app)


def _stub(monkeypatch, result):
    monkeypatch.setattr(
        "aughor.db.connection.open_connection_for",
        lambda conn: types.SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda db, sql, **kw: result)


def _card(**kw) -> DashboardCard:
    return upsert_card(DashboardCard(
        connection_id="workspace", scope="connection", scope_ref="workspace",
        sql="SELECT 0.32 AS rate", title="rate", **kw,
    ))


def _qr(**kw) -> QueryResult:
    base = dict(hypothesis_id="c", sql="s", columns=["rate"], rows=[[0.32]], row_count=1)
    base.update(kw)
    return QueryResult(**base)


def test_run_scalar_tracks_value_delta_and_history(monkeypatch):
    card = _card()
    _stub(monkeypatch, _qr(rows=[[0.32]], row_count=1))
    r1 = client.post(f"/cards/{card.id}/run")
    assert r1.status_code == 200
    assert r1.json()["refresh"]["last_value"] == 0.32
    assert r1.json()["refresh"]["prev_value"] is None
    assert r1.json()["refresh"]["history"] == [0.32]        # trend series seeded

    _stub(monkeypatch, _qr(rows=[[0.40]], row_count=1))
    r2 = client.post(f"/cards/{card.id}/run")
    assert r2.json()["refresh"]["last_value"] == 0.40
    assert r2.json()["refresh"]["prev_value"] == 0.32       # previous rolled in → delta
    assert r2.json()["refresh"]["history"] == [0.32, 0.40]  # appended → sparkline
    assert get_card(card.id).refresh.last_value == 0.40      # persisted


def test_run_history_dedupes_consecutive_equal_values(monkeypatch):
    card = _card()
    _stub(monkeypatch, _qr(rows=[[5.0]], row_count=1))
    client.post(f"/cards/{card.id}/run")
    r = client.post(f"/cards/{card.id}/run")                 # same value again
    assert r.json()["refresh"]["history"] == [5.0]           # not [5.0, 5.0] — meaningful steps only


def test_run_multi_row_has_no_scalar(monkeypatch):
    card = _card()
    _stub(monkeypatch, _qr(columns=["m", "v"], rows=[["a", 1], ["b", 2]], row_count=2))
    r = client.post(f"/cards/{card.id}/run")
    assert r.status_code == 200
    assert r.json()["row_count"] == 2
    assert r.json()["refresh"]["last_value"] is None


def test_run_surfaces_error_without_scalar(monkeypatch):
    card = _card()
    _stub(monkeypatch, _qr(columns=[], rows=[], row_count=0, error="boom"))
    r = client.post(f"/cards/{card.id}/run")
    assert r.status_code == 200
    assert r.json()["error"] == "boom"
    assert r.json()["refresh"]["last_value"] is None


def test_run_missing_card_404():
    assert client.post("/cards/nope/run").status_code == 404


def test_run_note_card_is_noop(monkeypatch):
    card = upsert_card(DashboardCard(connection_id="workspace", kind="note", sql="", body="n", title="n"))
    r = client.post(f"/cards/{card.id}/run")
    assert r.status_code == 200
    assert r.json()["row_count"] == 0
