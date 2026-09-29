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


def test_a_run_says_its_own_figure_and_the_standing_one_stays_the_cards(monkeypatch):
    """Arc CT-4. A card that already HAS a standing value, then read for a range: the run's
    figure is the range's, and `refresh` goes on carrying the standing one. The card drew
    `refresh`, so it showed the all-time figure under the range's label — which the test above
    could not see, because it cuts the card before it has ever run standing."""
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    seen: dict = {}
    _stub(monkeypatch, seen)
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))

    def answering(figure):
        def run(db, sql, **kw):
            seen["sql"] = sql
            return QueryResult(hypothesis_id="c", sql=sql, columns=["n"], rows=[[figure]], row_count=1)
        monkeypatch.setattr("aughor.sql.executor.execute_guarded", run)

    answering("8416308.73")                      # as the warehouse answers: text
    standing = client.post(f"/cards/{card.id}/run").json()
    assert standing["value"] == 8416308.73 and standing["refresh"]["last_value"] == 8416308.73

    answering("2778117.83")
    ranged = client.post(f"/cards/{card.id}/run", params={"preset": "last_week"}).json()
    assert ranged["scoped"]["standing"] is False
    assert ranged["value"] == 2778117.83                       # the range's own
    assert ranged["refresh"]["last_value"] == 8416308.73       # the card's standing one, untouched
    assert get_card(card.id).refresh.history == [8416308.73]


def test_a_table_has_no_figure(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    _stub(monkeypatch, {})
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda db, sql, **kw: QueryResult(
        hypothesis_id="c", sql=sql, columns=["region", "n"], rows=[["NA", 3], ["EU", 2]], row_count=2))
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT region, COUNT(*) AS n FROM orders GROUP BY 1", title="by region"))
    assert client.post(f"/cards/{card.id}/run").json()["value"] is None
    assert client.post(f"/cards/{card.id}/run", params={"preset": "last_week"}).json()["value"] is None


def test_a_card_without_a_date_runs_standing_and_says_why(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    seen: dict = {}
    _stub(monkeypatch, seen)
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM products", title="products"))
    body = client.post(f"/cards/{card.id}/run", params={"preset": "last_week"}).json()
    assert body["scoped"] == {"covers": body["scoped"]["covers"], "standing": True, "why": "no date on products", "grain": None}
    assert seen["sql"] == card.sql and body["refresh"]["last_value"] == 7


def _answers(monkeypatch, seen: list, by_window: dict):
    """The warehouse, answering each window's cut with its own figure."""
    def run(db, sql, **kw):
        seen.append(sql)
        figure = next((v for day, v in by_window.items() if day in sql), None)
        return QueryResult(hypothesis_id="c", sql=sql, columns=["n"], rows=[[figure]], row_count=1)
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", run)


def test_asked_to_compare_a_cut_figure_is_read_for_its_comparison_the_same_way(monkeypatch):
    """A cockpit's card says how its figure moved against the window its range is compared
    with — the card's own SQL, cut on the same date, so the two differ only by their dates."""
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    _stub(monkeypatch, {})
    seen: list = []
    _answers(monkeypatch, seen, {"2026-08-24": 7, "2026-08-10": 5})
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    body = client.post(f"/cards/{card.id}/run", params={"preset": "last_week", "compare": True}).json()
    assert body["value"] == 7
    from aughor.briefing.ranges import phrases
    assert body["previous"] == {"covers": phrases(SPEC)["compared_with"], "word": "the week before",
                                "equal_age": True, "value": 5, "why": ""}
    assert len(seen) == 2 and "2026-08-10" in seen[1] and "2026-08-17" in seen[1]
    assert get_card(card.id).refresh.history == []          # neither figure is the standing one


def test_a_comparison_before_the_range_settles_says_it_is_not_at_equal_age(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    _stub(monkeypatch, {})
    young = RangeSpec(**{**SPEC.__dict__, "as_of": date(2026, 8, 26)})
    monkeypatch.setattr("aughor.briefing.ranges.resolve_for", lambda cid, preset=None, **kw: (young, ""))
    _answers(monkeypatch, [], {"2026-08-24": 7, "2026-08-10": 5})
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    body = client.post(f"/cards/{card.id}/run", params={"preset": "last_week", "compare": True}).json()
    assert body["previous"]["value"] == 5 and body["previous"]["equal_age"] is False


def test_a_comparison_with_no_figure_says_so_and_is_never_zero(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    _stub(monkeypatch, {})
    _answers(monkeypatch, [], {"2026-08-24": 7})
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    prev = client.post(f"/cards/{card.id}/run", params={"preset": "last_week", "compare": True}).json()["previous"]
    assert prev["value"] is None and prev["why"] == "it has no figure there"


def test_nothing_is_compared_unasked_or_where_nothing_was_cut(monkeypatch):
    """The Briefing's own cards never ask, so they pay for no second query; a card that ran
    standing has no window of its own to compare."""
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "1")
    _stub(monkeypatch, {})
    seen: list = []
    _answers(monkeypatch, seen, {"2026-08-24": 7, "2026-08-10": 5})
    orders = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                       sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    assert "previous" not in client.post(f"/cards/{orders.id}/run", params={"preset": "last_week"}).json()
    assert len(seen) == 1
    products = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                         sql="SELECT COUNT(*) AS n FROM products", title="products"))
    body = client.post(f"/cards/{products.id}/run", params={"preset": "last_week", "compare": True}).json()
    assert body["scoped"]["standing"] is True and body["previous"] is None and len(seen) == 2


def test_a_range_is_refused_with_the_flag_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_BRIEFING_RANGES", "0")
    seen: dict = {}
    _stub(monkeypatch, seen)
    card = upsert_card(DashboardCard(connection_id="c-range", scope="connection", scope_ref="c-range",
                                     sql="SELECT COUNT(*) AS n FROM orders", title="orders"))
    r = client.post(f"/cards/{card.id}/run", params={"preset": "last_week"})
    assert r.status_code == 404 and "briefing.ranges" in r.json()["detail"]
