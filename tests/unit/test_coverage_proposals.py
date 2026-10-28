"""Arc MC, MC-3 / MC-5 / MC-6 — proposals for the areas the data covers, every one through the gates.

A DuckDB shop with sold lines, a returns table whose every row has a return date, and web sessions. With retail's
`order_item` role bound as LuxExperience had it (to `returns`), the return-rate recipe is proposed with its gates read —
it never moves, and its return date is never empty — and the catalogue's row says so and cannot be adopted (MC-3's
falsifier). Bound to the sold lines, it is adoptable. The writer (MC-5) is handed one area's patterns and tables per
call, and a proposal reading a table its area was not given, or citing a pattern it does not compute, is refused
(MC-5's falsifier). A measure three findings compute with no metric reading it is proposed (MC-6).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import duckdb
import pytest

from aughor.semantic import coverage_proposals as CP

TODAY = date.today()


@pytest.fixture
def shop(tmp_path, monkeypatch):
    path = tmp_path / "shop.duckdb"
    c = duckdb.connect(str(path))
    start = TODAY - timedelta(days=200)
    c.execute(f"""CREATE TABLE order_items AS
        SELECT row_number() OVER () AS order_item_id, row_number() OVER () AS order_id,
               d::TIMESTAMP + INTERVAL 9 HOUR AS created_at, CAST(10 + day(d) AS DOUBLE) AS sale_price,
               CASE WHEN (row_number() OVER ()) % 4 = 0 THEN d::TIMESTAMP + INTERVAL 2 DAY END AS returned_at
        FROM range(DATE '{start}', DATE '{TODAY}', INTERVAL 1 DAY) t(d)""")
    c.execute("""CREATE TABLE returns AS SELECT order_item_id AS return_id, order_item_id,
                 CAST(returned_at AS DATE) AS return_date, sale_price AS refund FROM order_items
                 WHERE returned_at IS NOT NULL""")
    c.execute(f"""CREATE TABLE web_sessions AS SELECT row_number() OVER () AS session_id,
                  d::TIMESTAMP AS session_start, (row_number() OVER ()) % 3 = 0 AS converted
                  FROM range(DATE '{start}', DATE '{TODAY}', INTERVAL 1 DAY) t(d)""")
    c.close()
    conn = f"shop{uuid.uuid4().hex[:6]}"

    def col(t, n, dtype, nulls=0.0, sem=""):
        return {f"{t}.{n}": {"table": t, "column": n, "dtype": dtype, "null_rate": nulls, "semantic_type": sem}}

    entry = {"tables": {"order_items": {"table": "order_items", "row_count": 200, "primary_timestamp": "created_at",
                                        "grain_column": "order_item_id"},
                        "returns": {"table": "returns", "row_count": 50, "primary_timestamp": "return_date",
                                    "grain_column": "return_id"},
                        "web_sessions": {"table": "web_sessions", "row_count": 200, "primary_timestamp": "session_start",
                                         "grain_column": "session_id"}},
             "columns": {**col("order_items", "order_item_id", "bigint"), **col("order_items", "order_id", "bigint"),
                         **col("order_items", "created_at", "timestamp"),
                         **col("order_items", "sale_price", "double", sem="measure"),
                         **col("order_items", "returned_at", "timestamp", 0.75),
                         **col("returns", "return_id", "bigint"), **col("returns", "order_item_id", "bigint"),
                         **col("returns", "return_date", "date"), **col("returns", "refund", "double", sem="measure"),
                         **col("web_sessions", "session_id", "bigint"),
                         **col("web_sessions", "session_start", "timestamp"),
                         **col("web_sessions", "converted", "boolean")}}
    from aughor.business_profile import metric_kb
    from aughor.business_profile import store as profile_store
    from aughor.db import connection as dbconn
    from aughor.semantic import metrics as metric_store
    from aughor.tools import profile_cache
    # a metrics file of the test's own: a definition saved here never reaches another test's raw read
    monkeypatch.setattr(metric_store, "_DEFAULT_PATH", tmp_path / "metrics.json", raising=False)
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setattr(metric_kb, "industry_scope", lambda *a, **k: "retail")
    monkeypatch.setattr(profile_cache, "merged_profile_entry", lambda *a, **k: entry)
    monkeypatch.setattr(profile_cache, "profile_entry_for", lambda *a, **k: entry)
    monkeypatch.setattr(dbconn, "open_connection_for",
                        lambda cid, *a, **k: dbconn.open_connection("duckdb", str(path), connection_id=cid))
    profile_store._family().put(profile_store._key(conn), {"connection_id": conn, "schema_name": None,
                                                           "profile": {"industry": "Retail"}})
    return conn, path


def _bind(conn: str, order_item: dict) -> None:
    from aughor.packs.bindings import save_binding
    save_binding("retail", conn, {"order_item": order_item}, schema="")


def test_a_recipe_bound_to_a_table_whose_every_row_is_a_return_is_proposed_refused_and_not_adoptable(shop, monkeypatch):
    conn, _ = shop
    _bind(conn, {"table": "returns", "columns": {"returned_at": "return_date"}})
    out = CP.run(conn, None)
    rate = next(p for p in out["proposals"] if p["name"] == "return_rate")
    assert rate["state"] == CP.STATE_GATE_FAILED and rate["area"] == "returns"
    assert rate["gates"]["binding"]["ok"] is False
    assert "returns.return_date is never empty" in rate["gates"]["binding"]["why"]
    assert rate["gates"]["moves"]["ok"] is False and "it reads 1 in every one" in rate["gates"]["moves"]["why"]
    assert rate["reason"].startswith("its roles are bound to the right columns — no: the formula counts a row")

    from aughor.semantic.metric_catalogue import catalogue_for
    row = next(r for r in catalogue_for(conn) if r.name == "return_rate")
    assert (row.source, row.state, row.area) == ("industry", "gate_failed", "returns")
    assert row.reason == rate["reason"]

    from aughor import govern
    monkeypatch.setattr(govern, "guard", lambda *a, **k: None)
    from fastapi.testclient import TestClient

    from aughor.api import app
    with TestClient(app) as client:
        got = client.post(f"/metrics/catalogue/{conn}/adopt", json={"items": [{"name": "return_rate"}]}).json()
    assert got["adopted"] == []
    assert got["skipped"][0]["reason"].startswith("it failed a check when it was proposed: its roles are bound")


def test_bound_to_the_sold_lines_the_same_recipe_passes_every_gate(shop):
    conn, _ = shop
    _bind(conn, {"table": "order_items", "columns": {"returned_at": "returned_at"}})
    out = CP.run(conn, None)
    rate = next(p for p in out["proposals"] if p["name"] == "return_rate")
    assert rate["state"] == CP.STATE_PROPOSED, rate["reason"]
    assert set(rate["gates"]) >= {"runs", "dated", "window", "binding", "moves", "sane_range"}
    assert rate["time_column"] == "order_items.created_at"
    from aughor.semantic.metric_catalogue import catalogue_for
    row = next(r for r in catalogue_for(conn) if r.name == "return_rate")
    assert row.state == "proposed" and row.gates["sane_range"]["ok"] is True


def test_a_verdict_read_under_a_binding_that_changed_is_not_applied(shop):
    conn, _ = shop
    _bind(conn, {"table": "returns", "columns": {"returned_at": "return_date"}})
    CP.run(conn, None)
    _bind(conn, {"table": "order_items", "columns": {"returned_at": "returned_at"}})
    from aughor.semantic.metric_catalogue import catalogue_for
    row = next(r for r in catalogue_for(conn) if r.name == "return_rate")
    assert row.state == "proposed" and row.gates is None


# ── MC-6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_measure_three_findings_keep_computing_is_proposed_in_its_area(shop, monkeypatch):
    conn, _ = shop
    from aughor.explorer import store as explorer_store
    findings = [{"id": f"f{i}", "sql": f"SELECT SUM(refund) FROM returns WHERE return_id > {i}"} for i in range(3)]
    monkeypatch.setattr(explorer_store, "get_findings", lambda *a, **k: findings)
    out = CP.run(conn, None)
    spot = next(p for p in out["proposals"] if p["source"] == CP.SOURCE_BLIND_SPOT)
    assert (spot["name"], spot["area"], spot["findings"]) == ("total_refund", "returns", 3)
    assert spot["sql"] == "SELECT SUM(refund) AS total_refund FROM returns"
    assert spot["state"] == CP.STATE_PROPOSED, spot["reason"]
    # two findings are not enough, and a measure a metric reads is not a blind spot
    monkeypatch.setattr(explorer_store, "get_findings", lambda *a, **k: findings[:2])
    assert not [p for p in CP.run(conn, None)["proposals"] if p["source"] == CP.SOURCE_BLIND_SPOT]


# ── MC-5 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Provider:
    """Answers each area's call with what is written for it; records every prompt."""
    _model = "test-model"

    def __init__(self, answers: dict):
        self.answers, self.prompts = answers, []

    def complete(self, *, system, user, response_model, temperature=0.0):
        self.prompts.append(user)
        area = user.split("AREA: ", 1)[1].split(" — ", 1)[0]
        return response_model.model_validate(self.answers.get(area, {"proposals": [], "skipped": []}))


def test_the_writer_gets_one_call_per_uncovered_area_and_its_mistakes_are_refused(shop, monkeypatch):
    conn, _ = shop
    provider = _Provider({
        "Orders & sales": {"proposals": [
            {"pattern_id": "ec_gmv", "name": "gmv", "label": "GMV", "definition": "sold value",
             "sql": "SELECT SUM(sale_price) AS gmv FROM order_items", "time_column": "order_items.created_at"},
            {"pattern_id": "ec_cancellation_rate", "name": "cancellations", "label": "Cancellations", "definition": "?",
             "sql": "SELECT COUNT(*) AS cancellations FROM order_items", "time_column": "order_items.created_at"},
            {"pattern_id": "ec_made_up", "name": "made_up", "label": "Made up", "definition": "?",
             "sql": "SELECT COUNT(*) FROM order_items", "time_column": "order_items.created_at"},
            {"pattern_id": "", "name": "sessions_seen", "label": "Sessions seen", "definition": "?",
             "sql": "SELECT COUNT(*) FROM web_sessions", "time_column": "web_sessions.session_start"}],
            "skipped": [{"pattern_id": "ec_net_revenue", "why": "no discount column"}]},
    })
    from aughor.llm import provider as llm_provider
    monkeypatch.setattr(llm_provider, "get_provider", lambda *a, **k: provider)
    out = CP.run(conn, None, write=True, why="the connection was profiled")
    spend = out["spend"]
    assert spend["calls"] == len(provider.prompts) == len(spend["areas"]) >= 3
    assert spend["model"] == "test-model"
    orders_prompt = next(u for u in provider.prompts if "AREA: Orders & sales" in u)
    assert "TABLE order_items" in orders_prompt and "TABLE web_sessions" not in orders_prompt
    assert "PATTERN ec_gmv" in orders_prompt and "PATTERN ec_conversion_rate" not in orders_prompt
    by = {p["name"]: p for p in out["proposals"]}
    assert by["gmv"]["state"] == CP.STATE_PROPOSED, by["gmv"]["reason"]
    assert (by["gmv"]["source"], by["gmv"]["pattern"]) == (CP.SOURCE_PATTERN, "ec_gmv")
    assert by["cancellations"]["state"] == CP.STATE_GATE_FAILED
    assert by["cancellations"]["reason"] == "it computes its pattern — no: it cites a rate, and its statement divides nothing"
    assert by["made_up"]["gates"]["pattern"] == {"ok": False, "why": "it cites ec_made_up, which is not one of its "
                                                                     "area's patterns"}
    assert by["sessions_seen"]["gates"]["area"] == {"ok": False, "why": "it reads web_sessions, which its area was "
                                                                        "not given"}
    orders = next(a for a in spend["areas"] if a["area"] == "orders_sales")
    assert orders["skipped"] == [{"pattern": "ec_net_revenue", "why": "no discount column"}]
    # the catalogue lists the writer's proposals as their own source, a refused one not adoptable
    from aughor.semantic.metric_catalogue import catalogue_for
    rows = {r.name: r for r in catalogue_for(conn) if r.source == "coverage"}
    assert rows["gmv"].state == "proposed" and rows["gmv"].why_it_matters == ("the knowledge base's Gross Merchandise "
                                                                             "Value (GMV)")
    assert rows["sessions_seen"].state == "gate_failed"


def test_a_run_that_is_not_asked_to_write_makes_no_model_call(shop, monkeypatch):
    """The run door proposes by code only; the writer writes when the connection is profiled, or on its own door."""
    conn, _ = shop
    from aughor.llm import provider as llm_provider
    monkeypatch.setattr(llm_provider, "get_provider", lambda *a, **k: pytest.fail("a model was called"))
    out = CP.run(conn, None)
    assert out["spend"] is None and "flags" not in out
    assert not [p for p in out["proposals"] if p["source"] in (CP.SOURCE_PATTERN, CP.SOURCE_AREA)]


def test_an_area_a_metric_already_covers_is_still_written_for_its_open_patterns_and_told_what_is_measured(shop, monkeypatch):
    """LuxExperience's Traffic & conversion had one working metric beside 22 patterns: covered, and thin. The writer is
    handed the patterns no metric there computes, never the one already measured."""
    conn, _ = shop
    from aughor.semantic.metrics import MetricDefinition, save_metric
    save_metric(MetricDefinition(name="gmv", label="GMV", sql="SELECT SUM(sale_price) AS gmv FROM order_items",
                                 connection=conn, status="approved", time_kind="flow",
                                 time_column="order_items.created_at"))
    provider = _Provider({})
    from aughor.llm import provider as llm_provider
    monkeypatch.setattr(llm_provider, "get_provider", lambda *a, **k: provider)
    CP.run(conn, None, write=True)
    orders = next(u for u in provider.prompts if "AREA: Orders & sales" in u)
    assert "ALREADY MEASURED here (do not write these again): GMV" in orders
    assert "PATTERN ec_gmv " not in orders and "PATTERN ec_aov " in orders


def test_a_number_is_not_a_date_and_two_proposals_of_one_figure_are_one_measure():
    """Live 2026-10-26 on LuxExperience: cost per click dated by `fiscal_year`, and three consent proposals reading
    0.6196 alike."""
    from aughor.semantic.metric_gates import column_kind
    assert CP._date_type("marketing_campaigns.fiscal_year", {"marketing_campaigns.fiscal_year": {
        "table": "marketing_campaigns", "column": "fiscal_year", "dtype": "integer"}}) == "integer"
    assert column_kind("integer") == "integer" and column_kind("text") == "text" and column_kind("date") == "time"
    same = [0.57, 0.61, 0.65, 0.61]
    rows = [{"label": "Marketing consent rate", "state": CP.STATE_PROPOSED, "figures": same, "gates": {}},
            {"label": "Email subscribed rate", "state": CP.STATE_PROPOSED, "figures": list(same), "gates": {}},
            {"label": "Open rate", "state": CP.STATE_PROPOSED, "figures": [0.2, 0.3, 0.25, 0.28], "gates": {}}]
    CP.one_measure_once(rows)
    assert [r["state"] for r in rows] == [CP.STATE_PROPOSED, CP.STATE_GATE_FAILED, CP.STATE_PROPOSED]
    assert rows[1]["reason"] == ("no approved metric measures the same — no: it reads exactly what Marketing consent "
                                 "rate, proposed here too, reads in each of the last 4 months — one measure, proposed twice")


def test_a_proposal_dated_by_a_year_number_is_refused_before_its_figures_are_read(shop, monkeypatch):
    conn, path = shop
    import duckdb
    c = duckdb.connect(str(path))
    c.execute("CREATE TABLE campaigns AS SELECT 2025 AS fiscal_year, 10.0 AS spend, 100 AS clicks")
    c.close()
    from aughor.tools import profile_cache
    entry = profile_cache.merged_profile_entry(conn)
    entry["columns"]["campaigns.fiscal_year"] = {"table": "campaigns", "column": "fiscal_year", "dtype": "integer"}
    p = {"name": "cpc", "label": "Cost per click", "sql": "SELECT SUM(spend) / SUM(clicks) FROM campaigns",
         "time_column": "campaigns.fiscal_year", "gates": {}}
    from aughor.db.connection import open_connection
    db = open_connection("duckdb", str(path))

    def run_sql(sql):
        r = db.execute("t", sql, internal=True)
        return list(r.columns or []), list(r.rows or []), r.error
    CP.gate(p, connection_id=conn, schema_name=None, run_sql=run_sql, dialect="duckdb", approved=[],
            columns=entry["columns"])
    db.close()
    assert p["state"] == CP.STATE_GATE_FAILED
    assert p["gates"]["dated"]["why"].startswith("its date, campaigns.fiscal_year, is integer — a number, not a day")
