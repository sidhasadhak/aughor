"""Metrics per DATASET, a proposal a person removes, and who did it — the overhaul of 2026-10-07.

The user, that day:
  * *"when there are multiple schemas belonging to the same industry … the proposed metric could be
    duplicate by name but those should be distinctly defined for each of the schema with a
    possibility of promoting it to the connection level"*;
  * *"when I select … all schemas in the semantic layer … all the metrics across all the schemas of
    the selected connection should be displayed"*;
  * *"user needs the right to remove the proposed Metric and edit anything"*;
  * *"user did not enter the name again because the user is already logged in"*.

Read through the real metric store (an instance file of the test's own) and the real catalogue;
only the explorer's profiles and the packages are doubles.
"""
from __future__ import annotations

import pytest

from aughor.semantic import metric_catalogue as MC
from aughor.semantic import metrics as M


class _NSM:
    def __init__(self, name, maps_to="", value_sql=""):
        self.name, self.maps_to, self.value_sql = name, maps_to, value_sql
        self.definition, self.unit_or_range, self.why_it_matters = "", "USD", ""


class _Profile:
    def __init__(self, metrics):
        self.north_star_metrics = list(metrics)


@pytest.fixture
def warehouse(monkeypatch, tmp_path):
    """One connection, `wh`, with two datasets — staging and marts — each profiled by the explorer
    and each proposing its own Revenue."""
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    profiles = {
        "staging": _Profile([_NSM("Revenue", "staging.orders.amount", "SELECT SUM(amount) FROM staging.orders")]),
        "marts": _Profile([_NSM("Revenue", "marts.fct_orders.net", "SELECT SUM(net) FROM marts.fct_orders"),
                           _NSM("Orders", "marts.fct_orders.id", "SELECT COUNT(id) FROM marts.fct_orders")]),
    }
    monkeypatch.setattr("aughor.business_profile.store.load", lambda c, s=None: profiles.get(s))
    monkeypatch.setattr("aughor.business_profile.store.load_raw", lambda c, s=None: {})
    monkeypatch.setattr("aughor.business_profile.store.profiled_schemas", lambda c: ["staging", "marts"])
    monkeypatch.setattr("aughor.packs.knowledge.packages", lambda: ())
    monkeypatch.setattr("aughor.semantic.metric_time.with_dates", lambda c, m: m)
    return "wh"


def _rows(conn, schema):
    return [(r.source, r.schema, r.name) for r in MC.catalogue_for(conn, schema)]


# ── every dataset, together ────────────────────────────────────────────────────────────────

def test_all_schemas_lists_every_datasets_proposals_each_saying_which(warehouse):
    assert _rows(warehouse, "*") == [("explorer", "staging", "revenue"),
                                     ("explorer", "marts", "revenue"),
                                     ("explorer", "marts", "orders")]
    # One dataset in view lists its own only.
    assert _rows(warehouse, "staging") == [("explorer", "staging", "revenue")]


# ── one name, two datasets, then the connection ────────────────────────────────────────────

def test_two_datasets_each_keep_their_own_revenue_and_one_can_be_promoted(warehouse):
    staging = MC.materialise(warehouse, "revenue", "staging")
    marts = MC.materialise(warehouse, "revenue", "marts")
    assert (staging.schema_name, marts.schema_name) == ("staging", "marts")
    # Two definitions — the second did not overwrite the first, as `materialise` did by name alone.
    assert "staging.orders" in M.definition_at("revenue", warehouse, "staging").sql
    assert "marts.fct_orders" in M.definition_at("revenue", warehouse, "marts").sql
    assert [m.sql for m in M.list_metrics(connection_id=warehouse, schema_name="marts")] == [marts.sql]
    # Every dataset in view: both, each where it lives.
    assert _rows(warehouse, "*")[:2] == [("defined", "staging", "revenue"), ("defined", "marts", "revenue")]

    # Promote marts' to the connection: staging keeps its own; a third dataset reads marts'.
    M.move_metric("revenue", warehouse, "marts", marts.model_copy(update={"schema_name": "*"}))
    assert M.get_metric("revenue", connection_id=warehouse, schema_name="staging").sql == staging.sql
    assert M.get_metric("revenue", connection_id=warehouse, schema_name="finance").sql == marts.sql
    assert M.definition_at("revenue", warehouse, "marts") is None
    assert M.definition_at("revenue", warehouse, "*").sql == marts.sql


def test_a_definition_written_before_datasets_belongs_to_the_one_its_sql_reads(warehouse):
    """Every definition on a live install predates the field. Daily Gross Revenue reads
    `main.sales_transactions`: it is `main`'s, and is not listed under any other dataset."""
    M.save_metric(M.MetricDefinition(name="daily_sales", connection=warehouse, label="Daily Sales",
                                     sql="SELECT SUM(totalPrice) FROM main.sales_transactions"))
    assert M.home_schema(M.definition_at("daily_sales", warehouse)) == "main"
    assert [m.name for m in M.list_metrics(connection_id=warehouse, schema_name="marts")] == []
    assert [m.name for m in M.list_metrics(connection_id=warehouse, schema_name="main")] == ["daily_sales"]
    assert [m.name for m in M.list_metrics(connection_id=warehouse)] == ["daily_sales"]


# ── removing a proposal ─────────────────────────────────────────────────────────────────────

def test_a_removed_proposal_stays_removed_in_its_dataset_and_can_be_restored(warehouse):
    M.dismiss_proposal(warehouse, "marts", "Revenue", by="ana@example.com", source="explorer")
    assert ("explorer", "marts", "revenue") not in _rows(warehouse, "*")
    assert ("explorer", "staging", "revenue") in _rows(warehouse, "*"), "removed in marts only"
    removed = MC.removed_for(warehouse, "marts")
    assert [(d["name"], d["by"]) for d in removed] == [("revenue", "ana@example.com")]

    assert M.restore_proposal(warehouse, "marts", "revenue")
    assert ("explorer", "marts", "revenue") in _rows(warehouse, "*")


def test_a_removal_holds_at_the_profile_read_every_reader_uses(monkeypatch, tmp_path):
    """The explorer re-proposes by name on every rebuild, and the Briefing, the KPI strip and the
    agent read the profile — the removal is applied where they all read it."""
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    from aughor.business_profile import store
    from aughor.business_profile.models import BusinessProfile

    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    ns = {"definition": "", "why_it_matters": "", "unit_or_range": ""}
    profile = BusinessProfile.model_validate({
        "industry": "retail", "business_model": "", "summary": "", "key_questions": [],
        "confidence": 0.9, "evidence": "",
        "north_star_metrics": [{"name": "Revenue", "maps_to": "orders.amount", **ns},
                               {"name": "Orders", "maps_to": "orders.id", **ns}]})
    store.save("conn-r", profile, schema_name="shop")
    M.dismiss_proposal("conn-r", "shop", "Revenue", by="ana")
    assert [m.name for m in store.load("conn-r", "shop").north_star_metrics] == ["Orders"]
    # A rebuild writes the metric again; it is still not served.
    store.save("conn-r", profile, schema_name="shop")
    assert [m.name for m in store.load("conn-r", "shop").north_star_metrics] == ["Orders"]


# ── who did it ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers.metrics import router

    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    monkeypatch.setenv("AUGHOR_LOCAL_USER", "ana@example.com")
    monkeypatch.setattr("aughor.routers.metrics._require_binds", lambda *a, **k: None)
    monkeypatch.setattr("aughor.semantic.metric_time.with_dates", lambda c, m: m)
    monkeypatch.setattr("aughor.govern.guard", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_an_approval_and_a_date_confirmation_record_who_is_signed_in_never_a_typed_name(client):
    sql = "SELECT SUM(amount) AS revenue FROM shop.orders"
    r = client.post("/metrics", json={"name": "revenue", "connection": "c9", "label": "Revenue", "sql": sql,
                                      "approved_by": "Finance"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft", "a create that carried approved_by landed approved"
    assert r.json()["approved_by"] is None

    r = client.put("/metrics/revenue?schema=shop", json={
        "name": "revenue", "connection": "c9", "label": "Revenue", "sql": sql,
        "time_column": "shop.orders.created_at", "time_kind": "flow", "time_grain": "day",
        "time_confirmed_by": "someone else"})
    assert r.status_code == 200, r.text
    assert r.json()["time_confirmed_by"] == "ana@example.com"
    assert r.json()["time_grain"] == "day"

    for action in ("propose", "approve"):
        r = client.post("/metrics/revenue/transition", json={"action": action, "actor": "the CEO",
                                                             "connection": "c9", "schema_name": "shop"})
        assert r.status_code == 200, r.text
    assert r.json()["metric"]["approved_by"] == "ana@example.com"
    assert r.json()["audit"]["actor"] == "ana@example.com"


def test_a_definition_can_be_renamed_moved_and_promoted_and_a_draft_removed(client):
    sql = "SELECT SUM(amount) AS revenue FROM shop.orders"
    assert client.post("/metrics", json={"name": "revenue", "connection": "c9", "label": "Revenue",
                                         "sql": sql}).status_code == 201
    r = client.put("/metrics/revenue?schema=shop", json={"name": "gross_revenue", "connection": "c9",
                                                          "label": "Gross revenue", "sql": sql,
                                                          "additivity": "additive"})
    assert r.status_code == 200, r.text
    assert M.definition_at("revenue", "c9") is None
    assert M.definition_at("gross_revenue", "c9", "shop").additivity == "additive"

    r = client.post("/metrics/gross_revenue/promote?connection_id=c9&schema=shop")
    assert r.status_code == 200, r.text
    assert M.definition_at("gross_revenue", "c9", "*") is not None

    r = client.delete("/metrics/gross_revenue?connection=c9&schema=*")
    assert r.status_code == 200, r.text
    assert M.definition_at("gross_revenue", "c9") is None
    assert [d["name"] for d in M.dismissed_proposals("c9")] == ["gross_revenue"], \
        "a removed definition the explorer proposed would come back on the next rebuild"


# ── no static or stale figures ──────────────────────────────────────────────────────────────

def test_a_dataset_that_ended_reads_its_last_month_and_an_empty_count_is_no_figure(monkeypatch):
    """Uber's rides end 2024-12-30. Every recent range read nothing for them — and a COUNT read 0,
    which was shown as a measured figure. Now: the last month the data covers, saying so."""
    from datetime import date

    from aughor.briefing import ranges
    from aughor.semantic import metric_time as mt

    class _Rides:
        name, label, status, connection, unit = "rides", "Completed rides", "approved", "c", "count"
        time_kind, time_column, time_source, time_confirmed_by = "flow", "uber.rides.day", "set by a person", "t"
        sql, tables, filters = "SELECT COUNT(*) AS rides FROM uber.rides", [], []
        version, owner, approved_by = 1, "", "t"

    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: [_Rides()])
    monkeypatch.setattr(mt, "ensure_dates", lambda *a, **k: {})
    monkeypatch.setattr(mt, "measure_sql", lambda m, windows, **k: ("Q " + " ".join(f"{w.label}={w.start}" for w in windows), ""))

    def run_sql(sql):
        if "MAX(" in sql.upper():
            return ["last_day"], [("2024-12-30",)], ""
        if "current=2024-12-01" in sql:
            return [], [("current", 4100, date(2024, 12, 1), date(2024, 12, 30), 4100),
                        ("previous", 3900, date(2024, 11, 1), date(2024, 11, 30), 3900)], ""
        return [], [("current", 0, None, None, 0), ("previous", 0, None, None, 0)], ""   # a COUNT of nothing

    spec, _ = ranges.resolve_range("last_month", today=date(2026, 10, 7), lag_days=1)
    out = ranges.measure_range("c", spec, run_sql=run_sql, dialect="duckdb")
    [got] = out["measured"]
    assert got["current"] == 4100 and got["previous"] == 3900
    assert got["anchored"]["data_ends"] == "2024-12-30"
    assert "December 2024" in got["anchored"]["covers"], got["anchored"]

    # The same metric where its data does not end before the range: an empty month is not 0.
    def empty(sql):
        if "MAX(" in sql.upper():
            return ["last_day"], [("2026-10-06",)], ""
        return [], [("current", 0, None, None, 0), ("previous", 0, None, None, 0)], ""
    out = ranges.measure_range("c", spec, run_sql=empty, dialect="duckdb")
    assert out["measured"] == []
    assert out["unmeasured"] == [{"name": "Completed rides", "reason": "its data has no rows in this range"}]


def test_a_sum_that_leaves_cancelled_rows_out_is_a_flow_and_a_count_of_open_rows_a_level():
    """`WHERE cancelled_at IS NULL` made revenue a LEVEL — everything up to each window's end, a
    figure that barely moved and stood still once the data ended."""
    from aughor.semantic.metric_time import infer
    profile = {"tables": {"orders": {"primary_timestamp": "created_at"}},
               "columns": {"orders.created_at": {"table": "orders", "column": "created_at", "dtype": "timestamp"},
                           "orders.cancelled_at": {"table": "orders", "column": "cancelled_at", "dtype": "timestamp"}}}
    revenue = infer({"sql": "SELECT SUM(amount) FROM orders WHERE cancelled_at IS NULL"}, profile)
    assert revenue.fields["time_kind"] == "flow", revenue.fields
    open_orders = infer({"sql": "SELECT COUNT(*) FROM orders WHERE cancelled_at IS NULL"}, profile)
    assert open_orders.fields["time_kind"] == "stock", open_orders.fields


def test_a_statements_dates_are_set_the_moment_it_is_saved(monkeypatch):
    """A statement's `tables` field is empty, so the date rule read no profile and set nothing; and
    it ran only for approved metrics — a new metric could not follow the period picker until then."""
    from aughor.semantic.metric_time import with_dates
    profile = {"tables": {"uber_ncr.rides": {"primary_timestamp": "day"}},
               "columns": {"uber_ncr.rides.day": {"table": "uber_ncr.rides", "column": "day", "dtype": "date"}}}
    seen = {}
    monkeypatch.setattr("aughor.tools.profile_cache.profile_entry_for",
                        lambda c, tables: seen.setdefault("tables", tables) and profile)
    m = with_dates("ws", M.MetricDefinition(name="rides", connection="ws", label="Rides",
                                            sql="SELECT COUNT(*) AS rides FROM uber_ncr.rides"))
    assert seen["tables"] == ["uber_ncr.rides"]
    assert (m.time_kind, m.time_column) == ("flow", "uber_ncr.rides.day")
