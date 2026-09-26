"""BR-9 (2026-09-26): a cockpit card run for a range.

Pinned: with a range the card's SQL is cut to it on the main date of the first table it reads
and `scoped` says what the number covers; a card whose tables have no date runs standing and
`scoped` says why; a range's figure never rolls into the standing value history; a range is
refused with the flag off.
"""
from __future__ import annotations

import types
from datetime import date

from fastapi.testclient import TestClient

from aughor.api import app
from aughor.briefing.ranges import RangeSpec
from aughor.control_plane.contracts.execution import QueryResult
from aughor.dashboard.models import DashboardCard
from aughor.dashboard.store import get_card, upsert_card

client = TestClient(app)
SPEC = RangeSpec(preset="last_week", start=date(2026, 8, 17), end=date(2026, 8, 24),
                 previous_start=date(2026, 8, 10), previous_end=date(2026, 8, 17),
                 last_year_start=None, last_year_end=None, as_of=date(2026, 9, 26), lag_days=8, lag_source="test")
PROFILE = {"tables": {"orders": {"primary_timestamp": "created_at"}, "products": {}}, "columns": {}}


def _stub(monkeypatch, seen: dict):
    monkeypatch.setattr("aughor.db.connection.open_connection_for",
                        lambda conn: types.SimpleNamespace(close=lambda: None, dialect="duckdb"))

    def run(db, sql, **kw):
        seen["sql"] = sql
        return QueryResult(hypothesis_id="c", sql=sql, columns=["n"], rows=[[7]], row_count=1)
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", run)
    monkeypatch.setattr("aughor.briefing.ranges.resolve_for", lambda cid, preset=None, **kw: (SPEC, ""))
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: PROFILE)


def test_a_range_cuts_the_card_on_its_tables_date_and_never_rolls_into_the_history(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    seen: dict = {}
    _stub(monkeypatch, seen)
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    r = client.post(f"/cards/{card.id}/run", params={"preset": "last_week"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scoped"]["standing"] is False and body["scoped"]["grain"] == "orders.created_at"
    assert body["scoped"]["covers"] and "2026-08-17" in seen["sql"] and "2026-08-24" in seen["sql"]
    assert body["rows"] == [[7]] and body["refresh"]["last_value"] is None and body["refresh"]["history"] == []
    assert get_card(card.id).refresh.last_value is None
    # Standing run: the same card records its value.
    r = client.post(f"/cards/{card.id}/run")
    assert r.json()["scoped"] is None and r.json()["refresh"]["last_value"] == 7 and seen["sql"] == card.sql


def test_a_card_without_a_date_runs_standing_and_says_why(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    seen: dict = {}
    _stub(monkeypatch, seen)
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM products", title="products"))
    body = client.post(f"/cards/{card.id}/run", params={"preset": "last_week"}).json()
    assert body["scoped"] == {"covers": body["scoped"]["covers"], "standing": True, "why": "no date on products", "grain": None}
    assert seen["sql"] == card.sql and body["refresh"]["last_value"] == 7


def test_a_range_is_refused_with_the_flag_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "0")
    seen: dict = {}
    _stub(monkeypatch, seen)
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    r = client.post(f"/cards/{card.id}/run", params={"preset": "last_week"})
    assert r.status_code == 404 and "briefing.ranges" in r.json()["detail"]
