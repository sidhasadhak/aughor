"""Pin-from-Query-Builder endpoint (Briefing cockpit, Slice 2 — Door 2).

Verifies the ENDPOINT's contract, not the guard battery (tested in aughor/sql): the
user-authored SQL is re-run through execute_guarded, a query that errors is REFUSED (422,
nothing stored), a clean pin is stored with source=query_builder and its opaque render spec,
and `kind` is derived from the result shape (scalar → kpi, otherwise chart). The connection
and guard are stubbed so the test stays hermetic and deterministic.
"""
from __future__ import annotations

import types

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.dashboard.store import get_card, list_cards
from aughor.platform.contracts.execution import QueryResult

client = TestClient(app)


def _patch(monkeypatch, *, result=None):
    monkeypatch.setattr(
        "aughor.db.connection.open_connection_for",
        lambda conn: types.SimpleNamespace(close=lambda: None),
    )
    if result is None:
        result = QueryResult(
            hypothesis_id="pinq", sql="SELECT 0.32 AS rate",
            columns=["rate"], rows=[[0.32]], row_count=1,
        )
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda db, sql, **kw: result)


def test_pin_query_creates_guarded_kpi_card(monkeypatch):
    _patch(monkeypatch)
    r = client.post("/cards/pin-query", json={
        "connection_id": "workspace", "sql": "SELECT 0.32 AS rate",
        "title": "Return rate", "scope_ref": "workspace",
        "render": {"chartType": "auto", "custom": {"format": ",.0%"}},
    })
    assert r.status_code == 201, r.text
    card = r.json()["card"]
    assert card["source"] == "query_builder"
    assert card["kind"] == "kpi"                              # 1×1 numeric → kpi
    assert card["title"] == "Return rate"
    assert card["sql"] == "SELECT 0.32 AS rate"
    assert card["scope"] == "connection" and card["scope_ref"] == "workspace"
    assert card["render"]["custom"]["format"] == ",.0%"      # opaque render round-tripped
    assert card["provenance"]["insight_id"] == ""            # no origin finding (ad-hoc query)
    assert get_card(card["id"]) is not None                  # persisted


def test_pin_query_grouped_result_is_chart_kind(monkeypatch):
    grouped = QueryResult(
        hypothesis_id="pinq", sql="x", columns=["month", "gmv"],
        rows=[["2024-01", 100], ["2024-02", 120], ["2024-03", 90]], row_count=3,
    )
    _patch(monkeypatch, result=grouped)
    r = client.post("/cards/pin-query", json={
        "connection_id": "workspace", "sql": "SELECT month, gmv FROM t", "title": "GMV by month",
    })
    assert r.status_code == 201, r.text
    assert r.json()["card"]["kind"] == "chart"               # not a scalar → chart


def test_pin_query_refuses_when_guard_errors(monkeypatch):
    blocked = QueryResult(
        hypothesis_id="pinq", sql="x", columns=[], rows=[], row_count=0, error="[BLOCKED] mutation",
    )
    _patch(monkeypatch, result=blocked)
    r = client.post("/cards/pin-query", json={
        "connection_id": "workspace", "sql": "DELETE FROM t", "title": "bad", "scope_ref": "cvq_blk",
    })
    assert r.status_code == 422
    assert "not pinned" in r.json()["detail"].lower()
    assert list_cards(scope="connection", scope_ref="cvq_blk") == []   # nothing stored


def test_pin_query_empty_sql_is_422(monkeypatch):
    _patch(monkeypatch)
    r = client.post("/cards/pin-query", json={
        "connection_id": "workspace", "sql": "   ", "title": "empty",
    })
    assert r.status_code == 422


def test_pin_query_defaults_scope_ref_to_connection(monkeypatch):
    _patch(monkeypatch)
    r = client.post("/cards/pin-query", json={
        "connection_id": "conn_default", "sql": "SELECT 1", "title": "t",
    })
    assert r.status_code == 201, r.text
    card = r.json()["card"]
    assert card["scope"] == "connection" and card["scope_ref"] == "conn_default"


def test_pin_query_untitled_falls_back(monkeypatch):
    _patch(monkeypatch)
    r = client.post("/cards/pin-query", json={"connection_id": "workspace", "sql": "SELECT 1"})
    assert r.status_code == 201, r.text
    assert r.json()["card"]["title"] == "Pinned query"


def test_pin_query_passes_through_caveats(monkeypatch):
    caveated = QueryResult(
        hypothesis_id="pinq", sql="SELECT 1", columns=["n"], rows=[[1]], row_count=1,
        caveats=["value-disjoint join"],
    )
    _patch(monkeypatch, result=caveated)
    r = client.post("/cards/pin-query", json={
        "connection_id": "workspace", "sql": "SELECT 1", "title": "cav",
    })
    assert r.status_code == 201
    assert r.json()["caveats"] == ["value-disjoint join"]
