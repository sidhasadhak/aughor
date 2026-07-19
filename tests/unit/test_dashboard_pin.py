"""Pin-from-insight endpoint (Briefing cockpit, Slice 0 — Door 1).

Verifies the ENDPOINT's contract, not the guard battery (which is tested in aughor/sql):
the finding is resolved from the brief's domain insights, its SQL is re-run through
execute_guarded, a query that errors is REFUSED (422, nothing stored), and a clean pin is
stored linked back to the source finding. The resolver / connection / guard are stubbed so
the test stays hermetic and deterministic.
"""
from __future__ import annotations

import types

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.dashboard.store import get_card, list_cards
from aughor.platform.contracts.execution import QueryResult

client = TestClient(app)

FAKE_INSIGHTS = {
    "customer": [{"id": "ins_pin", "finding": "Womenswear return rate is 32%", "sql": "SELECT 0.32 AS rate"}]
}


def _patch(monkeypatch, *, insights=FAKE_INSIGHTS, result=None):
    monkeypatch.setattr(
        "aughor.routers.exploration._domain_insights_for", lambda conn, schema: insights
    )
    monkeypatch.setattr(
        "aughor.db.connection.open_connection_for",
        lambda conn: types.SimpleNamespace(close=lambda: None),
    )
    if result is None:
        result = QueryResult(
            hypothesis_id="pin", sql="SELECT 0.32 AS rate",
            columns=["rate"], rows=[[0.32]], row_count=1,
        )
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda db, sql, **kw: result)


def test_pin_creates_guarded_card_linked_to_finding(monkeypatch):
    _patch(monkeypatch)
    r = client.post("/cards/pin-insight", json={
        "connection_id": "workspace", "insight_id": "ins_pin", "scope_ref": "cv_pin",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    card = body["card"]
    assert card["source"] == "insight"
    assert card["kind"] == "kpi"
    assert card["provenance"]["insight_id"] == "ins_pin"
    assert card["provenance"]["receipt_ref"] == "insight:workspace:ins_pin"
    assert card["links"] == ["ins_pin"]                       # graph edge to the source finding
    assert card["sql"] == "SELECT 0.32 AS rate"
    assert card["title"] == "Womenswear return rate is 32%"
    assert body["preview"]["row_count"] == 1
    assert get_card(card["id"]) is not None                   # persisted


def test_pin_refuses_when_guard_errors(monkeypatch):
    blocked = QueryResult(
        hypothesis_id="pin", sql="x", columns=[], rows=[], row_count=0, error="[BLOCKED] mutation",
    )
    _patch(monkeypatch, result=blocked)
    r = client.post("/cards/pin-insight", json={
        "connection_id": "workspace", "insight_id": "ins_pin", "scope_ref": "cv_blk",
    })
    assert r.status_code == 422
    assert "not pinned" in r.json()["detail"].lower()
    assert list_cards(scope="canvas", scope_ref="cv_blk") == []   # nothing stored


def test_pin_missing_insight_is_404(monkeypatch):
    _patch(monkeypatch, insights={"d": []})
    r = client.post("/cards/pin-insight", json={
        "connection_id": "workspace", "insight_id": "nope", "scope_ref": "cv_x",
    })
    assert r.status_code == 404


def test_pin_profile_only_finding_is_422(monkeypatch):
    _patch(monkeypatch, insights={"d": [{"id": "ins_nosql", "finding": "profile fact", "sql": ""}]})
    r = client.post("/cards/pin-insight", json={
        "connection_id": "workspace", "insight_id": "ins_nosql", "scope_ref": "cv_y",
    })
    assert r.status_code == 422


def test_pin_passes_through_caveats(monkeypatch):
    caveated = QueryResult(
        hypothesis_id="pin", sql="SELECT 1", columns=["n"], rows=[[1]], row_count=1,
        caveats=["value-disjoint join"],
    )
    _patch(monkeypatch, result=caveated)
    r = client.post("/cards/pin-insight", json={
        "connection_id": "workspace", "insight_id": "ins_pin", "scope_ref": "cv_cav",
    })
    assert r.status_code == 201
    assert r.json()["caveats"] == ["value-disjoint join"]
