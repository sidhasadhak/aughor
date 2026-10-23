"""Arc AP-7 — your own query on the dashboard (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9).

A card that reads a person's own SQL says how it is shown, and is drawn so: the platform sums the statement's rows by
what runs along the bottom — a date put in buckets — and by what splits it, the top few values and the rest as Other,
folded exactly (an average from its sums and counts, never an average of averages), with what cannot be folded said.
The person's statement is embedded word for word. Every number here is checked against the rows themselves, summed in
Python — never against the statement that summed them.
"""
from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections import defaultdict

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.cockpit import queries as Q
from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.kernel.flags import flag_overrides

CONN = "queries-t"
SALES = ("SELECT o.order_date, c.country, o.total_amount, o.customer_id, o.status FROM ecommerce.orders o "
         "JOIN ecommerce.customers c ON c.customer_id = o.customer_id")


class _Borrowed:
    """The module's database, lent to a door that closes what it opens."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("queries") / "sales.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def rows(db):
    """Every row the statement returns, as Python reads them: the oracle every figure here is checked against."""
    out = Q.execute(db, SALES, max_rows=10_000, seconds=60)
    assert out["error"] is None and len(out["rows"]) == 5000
    names = [c["name"] for c in out["columns"]]
    return [dict(zip(names, r)) for r in out["rows"]]


def _columns(db, sql=SALES):
    return Q.probe(db, sql, seconds=60)["columns"]


def _monday(day: str) -> str:
    d = dt.date.fromisoformat(str(day)[:10])
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def _by(points, key="s"):
    out = defaultdict(dict)
    for p in points:
        out[str(p["x"])[:10]][p[key]] = p["v"]
    return out


# ── summed by the platform, folded exactly ────────────────────────────────────────────────────────────────────────────

def test_a_chart_sums_the_query_s_rows_by_week_and_folds_the_rest_into_other(db, rows):
    shown = Q.Shown.model_validate({"as": "bar", "x": "order_date", "bucket": "week", "split": "country", "top": 3,
                                    "series": [{"column": "total_amount", "agg": "sum"}]})
    ran = Q.run(db, SALES, shown, _columns(db), seconds=60)
    assert ran["error"] is None
    out = ran["shown"]
    totals = defaultdict(float)
    for r in rows:
        totals[r["country"]] += float(r["total_amount"])
    top = sorted(totals, key=lambda k: (-totals[k], k))[:3]
    assert out["series"] == [*top, "Other"] and out["other"] is True
    expected = defaultdict(lambda: defaultdict(float))
    for r in rows:
        expected[_monday(r["order_date"])][r["country"] if r["country"] in top else "Other"] += float(r["total_amount"])
    got = _by(out["points"])
    assert set(got) == set(expected)
    for week, by in expected.items():
        for s, v in by.items():
            assert got[week][s] == pytest.approx(v), (week, s)
    assert out["x"] == {"name": "order_date", "kind": "date", "bucket": "week"}


def test_an_average_folds_from_its_sums_and_counts_never_an_average_of_averages(db, rows):
    shown = Q.Shown.model_validate({"as": "bar", "x": "order_date", "bucket": "year", "split": "country", "top": 2,
                                    "series": [{"column": "total_amount", "agg": "avg"}]})
    out = Q.run(db, SALES, shown, _columns(db), seconds=60)["shown"]
    top = out["series"][:2]
    for year in ("2023", "2024"):
        rest = [float(r["total_amount"]) for r in rows if str(r["order_date"]).startswith(year) and r["country"] not in top]
        assert _by(out["points"])[f"{year}-01-01"]["Other"] == pytest.approx(sum(rest) / len(rest))


def test_a_count_of_different_values_draws_its_top_values_and_says_the_rest_cannot_be_added_up(db):
    shown = Q.Shown.model_validate({"as": "bar", "x": "order_date", "bucket": "year", "split": "country", "top": 3,
                                    "series": [{"column": "customer_id", "agg": "count_distinct"}]})
    out = Q.run(db, SALES, shown, _columns(db), seconds=60)["shown"]
    assert out["other"] is False and "Other" not in {p["s"] for p in out["points"]}
    assert out["said"] == ["The 7 other values of country are not drawn: a count of different values cannot be added up "
                           "into Other."]


def test_a_running_total_ends_on_the_whole(db):
    shown = Q.Shown.model_validate({"as": "line", "x": "order_date", "bucket": "month", "running": True,
                                    "series": [{"agg": "count"}]})
    out = Q.run(db, SALES, shown, _columns(db), seconds=60)["shown"]
    assert out["points"][-1]["v"] == 5000 and len(out["points"]) == 24
    assert [p["v"] for p in out["points"]] == sorted(p["v"] for p in out["points"])


def test_two_series_are_their_own_split_named_by_what_each_sums(db, rows):
    shown = Q.Shown.model_validate({"as": "bar", "x": "status", "series": [{"agg": "count"},
                                                                         {"column": "total_amount", "agg": "max"}]})
    out = Q.run(db, SALES, shown, _columns(db), seconds=60)["shown"]
    assert out["series"] == ["Count", "Most of total_amount"]
    delivered = [float(r["total_amount"]) for r in rows if r["status"] == "delivered"]
    got = {(p["x"], p["s"]): p["v"] for p in out["points"]}
    assert got[("delivered", "Count")] == len(delivered) and got[("delivered", "Most of total_amount")] == max(delivered)


def test_numbers_along_the_bottom_run_in_their_own_order(db):
    sql = "SELECT CAST(EXTRACT(month FROM order_date) AS INTEGER) AS month, total_amount FROM ecommerce.orders"
    shown = Q.Shown.model_validate({"as": "bar", "x": "month", "series": [{"agg": "count"}]})
    out = Q.run(db, sql, shown, _columns(db, sql), seconds=60)["shown"]
    assert [p["x"] for p in out["points"]] == list(range(1, 13))              # 2 before 10, never "1, 10, 11, 12, 2"


def test_a_figure_sums_the_rows_and_a_table_shows_its_columns_sorted_and_says_there_is_more(db, rows):
    fig = Q.run(db, SALES, Q.Shown.model_validate({"as": "figure", "series": [{"column": "total_amount", "agg": "sum"}]}),
                _columns(db), seconds=60)["shown"]
    assert fig["value"] == pytest.approx(sum(float(r["total_amount"]) for r in rows))
    assert fig["label"] == "Sum of total_amount"
    table = Q.run(db, SALES, Q.Shown.model_validate({"as": "table", "columns": ["country", "total_amount"],
                                                     "sort": "total_amount"}), _columns(db), seconds=60)["shown"]
    assert [c["name"] for c in table["columns"]] == ["country", "total_amount"]
    assert len(table["rows"]) == Q.TABLE_ROWS and table["more"] is True
    assert table["rows"][0][1] == max(float(r["total_amount"]) for r in rows)
    assert table["said"] == [f"The first {Q.TABLE_ROWS} rows; the query returns more."]


def test_a_chart_drawn_as_the_query_returns_it_never_adds_up_the_query_s_own_numbers(db):
    sql = ("SELECT c.country, o.status, AVG(o.total_amount) AS avg_amount FROM ecommerce.orders o "
           "JOIN ecommerce.customers c ON c.customer_id = o.customer_id GROUP BY 1, 2")
    shown = Q.Shown.model_validate({"as": "bar", "summed": False, "x": "country", "split": "status", "top": 2,
                                    "series": [{"column": "avg_amount"}]})
    out = Q.run(db, sql, shown, _columns(db, sql), seconds=60)["shown"]
    assert out["other"] is False and len(out["series"]) == 2
    assert out["said"][0].endswith("the query's own numbers are not added up into Other.")


# ── the statement around a person's own ───────────────────────────────────────────────────────────────────────────────

def test_the_person_s_statement_is_embedded_word_for_word():
    inner = "SELECT DATE(created_at) AS day, country, sale_price FROM thelook.orders -- theirs"
    cols = [{"name": "day", "type": "DATE"}, {"name": "country", "type": "VARCHAR"}, {"name": "sale_price", "type": "DOUBLE"}]
    shown = Q.Shown.model_validate({"as": "bar", "x": "day", "bucket": "week", "split": "country",
                                    "series": [{"column": "sale_price", "agg": "sum"}]})
    sql, cap = Q.statement(inner + " ;\n", shown, cols, "bigquery")
    assert sql.count(inner) == 1 and cap == Q.MAX_GROUPS + 1
    assert "DATE_TRUNC(`q`.`day`, WEEK(MONDAY)) AS x" in sql and sql.endswith(f"GROUP BY 1, 2 ORDER BY 1 LIMIT {Q.MAX_GROUPS + 1}")
    timed = [{"name": "at", "type": "TIMESTAMP"}, {"name": "n", "type": "BIGINT"}]
    month = Q.Shown.model_validate({"as": "line", "x": "at", "bucket": "month", "series": [{"column": "n", "agg": "sum"}]})
    assert "TIMESTAMP_TRUNC(CAST(`q`.`at` AS TIMESTAMP), MONTH) AS x" in Q.statement("SELECT at, n FROM t", month, timed, "bigquery")[0]
    assert "DATE_TRUNC('MONTH', \"q\".\"at\") AS x" in Q.statement("SELECT at, n FROM t", month, timed, "postgres")[0]
    plain = Q.Shown.model_validate({"as": "table"})
    assert Q.statement(inner, plain, cols, "bigquery") == (inner, Q.TABLE_ROWS + 1)


# ── what a setup asks that a query cannot give ────────────────────────────────────────────────────────────────────────

def test_each_thing_a_setup_asks_that_the_query_cannot_give_is_said():
    cols = [{"name": "day", "type": "DATE"}, {"name": "country", "type": "VARCHAR"}, {"name": "amount", "type": "DECIMAL(18,2)"}]

    def said(**setup):
        return Q.check(Q.normalized(Q.Shown.model_validate(setup), cols), cols)
    assert said(**{"as": "bar", "x": "day", "series": [{"column": "amount", "agg": "sum"}]}) == []
    assert said(**{"as": "bar", "x": "when", "series": [{"column": "amount"}]}) == [
        "Along the bottom names “when”, which this query does not return (it returns day, country, amount)."]
    assert said(**{"as": "bar", "x": "day", "series": [{"column": "country", "agg": "sum"}]}) == [
        "Sum reads a number, and “country” is text."]
    assert said(**{"as": "bar", "x": "country", "bucket": "week", "series": [{"agg": "count"}]}) == [
        "Only a date or a time is put in buckets, and “country” is text."]
    assert said(**{"as": "bar", "x": "day", "split": "day", "series": [{"agg": "count"}]}) == [
        "A chart is not split by what runs along the bottom."]
    assert said(**{"as": "bar", "x": "day", "split": "country", "series": [{"agg": "count"}, {"column": "amount"}]}) == [
        "A chart of more than one series is split by its series: take off the split or a series."]
    assert said(**{"as": "line", "x": "day", "segments": "shares", "series": [{"agg": "count"}]}) == [
        "Shares are drawn as bars or an area."]
    assert said(**{"as": "figure", "series": []}) == ["A figure shows one value and a scatter one height."]
    assert said(**{"as": "pie"}) == ["A card is shown as a table, a figure, a bar, a line, an area or a scatter — not “pie”."]
    assert Q.normalized(Q.Shown.model_validate({"as": "bar", "x": "day", "series": [{"agg": "count"}]}), cols).bucket == "day"
    assert Q.normalized(Q.Shown.model_validate({"as": "scatter", "x": "day", "series": [{"column": "amount"}]}), cols).summed is False


# ── the tables a query reads, and a row policy on them ────────────────────────────────────────────────────────────────

def test_the_tables_a_query_reads_are_its_own_names_its_ctes_left_out():
    sql = ("WITH recent AS (SELECT * FROM `bigquery-public-data.thelook_ecommerce.orders`) "
           "SELECT * FROM recent JOIN thelook.users u ON u.id = recent.user_id")
    assert Q.tables_of(sql, "bigquery") == ["orders", "users"]


def test_a_query_over_a_table_a_row_policy_narrows_is_refused_while_policies_hold():
    from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph, RowPolicy
    order = OntologyEntity(id="Order", display_name="Order", source_tables=["ecommerce.orders"], identity_key="id",
                           grain_verified=True,
                           row_policies=[RowPolicy(group="support", conditions=[{"path": "status", "op": "=", "value": "x"}])])
    user = OntologyEntity(id="User", display_name="User", source_tables=[], identity_key="id", grain_verified=True,
                          backing=Backing(table="users", primary_key="id"))
    graph = OntologyGraph(connection_id=CONN, schema_name="ecommerce", schema_fingerprint="fp")
    graph.entities = {"Order": order, "User": user}
    with flag_overrides({"ontology.security": True}):
        assert Q.policy_refusal(graph, ["users", "orders"]) == (
            "This query reads orders straight from its table, and Order has a row policy: a query cannot be narrowed to "
            "each reader. Read Order through a set instead.")
        assert Q.policy_refusal(graph, ["users"]) is None
    with flag_overrides({"ontology.security": False}):
        assert Q.policy_refusal(graph, ["orders"]) is None
    # an entity read through a keyed query still names the tables it is made of
    keyed = OntologyEntity(id="Line", display_name="Line", source_tables=["order_items"], identity_key="id", grain_verified=True,
                           backing=Backing(kind="query", sql="SELECT * FROM order_items", primary_key="id"),
                           row_policies=[RowPolicy(group="support", conditions=[])])
    graph.entities = {"Line": keyed}
    with flag_overrides({"ontology.security": True}):
        assert "Line has a row policy" in (Q.policy_refusal(graph, ["order_items"]) or "")


# ── stopped after the time limit ──────────────────────────────────────────────────────────────────────────────────────

def test_a_query_that_runs_past_its_time_is_stopped_and_says_so():
    class Slow:
        """An engine that runs until it is asked to stop, and then returns its interrupt as an error."""
        dialect = "duckdb"

        def __init__(self):
            self.asked = threading.Event()

        def interrupt(self):
            self.asked.set()
            return True

        def execute_typed(self, *_a, **_k):
            assert self.asked.wait(5), "the engine was never asked to stop"
            return type("R", (), {"error": "INTERRUPT Error: Interrupted!", "caveats": []})(), None
    slow = Slow()
    out = Q.execute(slow, "SELECT 1", max_rows=2, seconds=0.2)
    assert slow.asked.is_set() and out["error"] == "The query was stopped after 0.2 s."
    quick = Slow()
    quick.execute_typed = lambda *_a, **_k: (type("R", (), {"error": "boom", "caveats": []})(), None)
    assert Q.execute(quick, "SELECT 1", max_rows=2, seconds=5)["error"] == "boom" and not quick.asked.is_set()


# ── over HTTP: preview, keep, run ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db, monkeypatch):
    from aughor.api import app
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda conn, *a, **k: _Borrowed(db))
    monkeypatch.setattr("aughor.cockpit.pieces.served_graph", lambda conn: None)
    return TestClient(app)


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True, "cockpit.queries": True}):
        yield


def test_off_the_doors_answer_404_and_a_card_runs_as_it_always_did(client):
    conn = f"q{uuid.uuid4().hex[:6]}"
    with flag_overrides({"cockpit.composed": True, "cockpit.queries": False}):
        r = client.post("/cockpits/queries/preview", params={"connection_id": conn}, json={"sql": "SELECT 1"})
        assert r.status_code == 404 and "off on this install" in r.text
        r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": "SELECT 1"})
        assert r.status_code == 404


def test_a_preview_says_the_columns_the_first_rows_and_the_card_as_shown(client, on):
    conn = f"q{uuid.uuid4().hex[:6]}"
    r = client.post("/cockpits/queries/preview", params={"connection_id": conn}, json={
        "sql": SALES, "shown": {"as": "bar", "x": "order_date", "split": "country", "series": [{"column": "total_amount"}]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] == [] and [c["name"] for c in body["columns"]][:3] == ["order_date", "country", "total_amount"]
    assert {c["name"]: c["type"] for c in body["columns"]}["order_date"] == "DATE"
    assert len(body["rows"]) == Q.PREVIEW_ROWS and body["more"] is True
    assert body["setup"]["bucket"] == "day" and body["shown"]["as"] == "bar" and body["shown"]["other"] is True
    assert body["tables"] == ["orders", "customers"]


def test_what_cannot_run_or_be_shown_is_refused_in_words_and_nothing_is_kept(client, on):
    from aughor.dashboard.store import list_cards
    conn = f"q{uuid.uuid4().hex[:6]}"
    r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": "DELETE FROM ecommerce.orders"})
    assert r.status_code == 422 and r.json()["detail"]["refused"]
    r = client.post("/cockpits/queries", params={"connection_id": conn}, json={
        "sql": SALES, "shown": {"as": "bar", "x": "nowhere", "series": [{"agg": "count"}]}})
    assert r.status_code == 422
    assert r.json()["detail"]["refused"][0].startswith("Along the bottom names “nowhere”")
    assert list_cards(connection_id=conn) == []


def test_a_kept_query_is_a_card_of_the_person_s_own_and_a_change_supersedes_it(client, on):
    from aughor.dashboard.store import get_card
    conn = f"q{uuid.uuid4().hex[:6]}"
    shown = {"as": "bar", "x": "order_date", "bucket": "month", "series": [{"column": "total_amount", "agg": "sum"}]}
    r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": SALES, "shown": shown,
                                                                               "title": "Sales by month"})
    assert r.status_code == 201, r.text
    first = r.json()["card"]
    assert (first["scope"], first["own"], first["source"], first["kind"]) == ("user", True, "authored", "chart")
    assert first["render"]["shown"]["bucket"] == "month" and first["render"]["columns"][0]["name"] == "order_date"
    r = client.post("/cockpits/queries", params={"connection_id": conn}, json={
        "sql": SALES, "shown": {**shown, "segments": "side_by_side"}, "replaces": first["id"]})
    assert r.status_code == 201, r.text
    second = r.json()["card"]
    assert second["id"] != first["id"] and second["title"] == "Sales by month"
    assert get_card(first["id"]).provenance.superseded_by == second["id"]
    # the run draws it as it is shown; with queries off the same card runs as every card always did
    run = client.post(f"/cards/{second['id']}/run").json()
    assert run["error"] is None and run["shown"]["as"] == "bar" and len(run["shown"]["points"]) == 24
    with flag_overrides({"cockpit.queries": False}):
        assert "shown" not in client.post(f"/cards/{second['id']}/run").json()


def test_a_change_to_a_card_that_is_not_the_person_s_own_is_refused(client, on):
    from aughor.dashboard.models import DashboardCard
    from aughor.dashboard.store import upsert_card
    conn = f"q{uuid.uuid4().hex[:6]}"
    theirs = upsert_card(DashboardCard(connection_id=conn, scope="connection", scope_ref=conn, title="Pinned", sql="SELECT 1"))
    r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": SALES, "replaces": theirs.id})
    assert r.status_code == 422 and "Only a card of your own" in r.text


def test_writing_sql_on_a_cockpit_follows_the_sql_editor_s_rule():
    from aughor.rbac.permissions import Permission as P
    from aughor.rbac.policy import required_permission
    assert required_permission("POST", "/query/run") == P.ANALYSIS_RUN
    for path in ("/cockpits/queries", "/cockpits/queries/preview"):
        assert required_permission("POST", path) == P.ANALYSIS_RUN


def _policed():
    from aughor.ontology.models import OntologyEntity, OntologyGraph, RowPolicy
    graph = OntologyGraph(connection_id=CONN, schema_name="ecommerce", schema_fingerprint="fp")
    graph.entities = {"Order": OntologyEntity(id="Order", display_name="Order", source_tables=["orders"], identity_key="order_id",
                                              grain_verified=True, row_policies=[RowPolicy(group="support", conditions=[])])}
    return graph


def test_the_door_keeps_no_query_over_a_table_a_row_policy_narrows_and_a_kept_one_stops_running_once_one_does(client, on, monkeypatch):
    conn = f"q{uuid.uuid4().hex[:6]}"
    shown = {"as": "figure", "series": [{"column": "total_amount", "agg": "sum"}]}
    kept = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": SALES, "shown": shown}).json()["card"]
    monkeypatch.setattr("aughor.cockpit.pieces.served_graph", lambda c: _policed())
    with flag_overrides({"ontology.security": True}):
        r = client.post("/cockpits/queries", params={"connection_id": conn}, json={"sql": SALES, "shown": shown})
        assert r.status_code == 422 and "Order has a row policy" in r.json()["detail"]["refused"][0]
        run = client.post(f"/cards/{kept['id']}/run").json()
        assert run["shown"] is None and "Order has a row policy" in run["error"]
