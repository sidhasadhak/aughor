"""The process designer's reading of the data (`ontology.process_design`, `POST /ontology/processes/preview`,
`GET /ontology/processes/candidates`).

The usability walk-through of 2026-10-09 typed a delivery process the obvious way and found it would publish ≈35,750
late deliveries that were records left behind — the form showed column names and could not count a draft. The samples
shop has the same shape at its own scale: 1,100 orders shipped and never delivered, the cancelled and refunded ones,
spread over two years. Every number the designer shows is held here to a query written by hand over the seeded
warehouse, and neither door writes anything.
"""
from __future__ import annotations

import json

import pytest

from aughor.db.connection import open_connection
from aughor.ontology import overrides as OV
from aughor.ontology.derived import cutoff_days
from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import find_override
from aughor.ontology.process_design import STALE_DAYS, candidates, creates, design_checks
from aughor.ontology.processes import (
    ObjectCounter,
    measure_process,
    process_fields,
    process_from_fields,
    resolve_process,
)
from tests.unit.test_object_bindings import GRAPH, rows, seed

DELIVERY = {
    "id": "order_delivery", "display_name": "Order delivery", "entity": "Order",
    "stages": [
        {"name": "placed", "display_name": "Placed", "timestamp": "order_date"},
        {"name": "shipped", "display_name": "Shipped", "timestamp": "shipped_at"},
        {"name": "delivered", "display_name": "Delivered", "timestamp": "delivered_at",
         "promise": {"name": "delivery", "within_days": 5}},
    ],
}
CONN, SCHEMA = "design-t", "ecommerce"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("design") / "samples.duckdb"
    seed(path)
    conn = open_connection("duckdb", str(path), schema_name=SCHEMA, connection_id=CONN)
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def one(db, sql: str):
    value = rows(db, sql)[0][0]
    return int(value) if isinstance(value, float) and value.is_integer() else value


def measured_draft(db, graph, spec):
    problem, fields = resolve_process(graph, spec["id"], process_fields(spec))
    assert problem == "", problem
    return process_from_fields(spec["id"], fields), measure_process(db, graph, spec["id"], fields)


# ── what a stage may be anchored to, read from the data ─────────────────────────────────────────────────────────────

def test_the_moments_and_states_a_type_carries_are_counted_as_the_data_holds_them(db, graph):
    read = candidates(db, graph, "Order")
    assert read["objects"] == one(db, "SELECT COUNT(*) FROM ecommerce.orders")
    own = {m["path"]: m for m in read["moments"] if not m["via"]}
    assert set(own) == {"order_date", "shipped_at", "delivered_at"}
    for col, m in own.items():
        assert m["set"] == one(db, f"SELECT COUNT({col}) FROM ecommerce.orders")
        assert m["earliest"][:10] == str(one(db, f"SELECT MIN({col}) FROM ecommerce.orders"))[:10]
        assert m["latest"][:10] == str(one(db, f"SELECT MAX({col}) FROM ecommerce.orders"))[:10]
    status = next(s for s in read["states"] if s["property"] == "status")
    want = {r[0]: r[1] for r in rows(db, "SELECT status, COUNT(*) FROM ecommerce.orders GROUP BY 1")}
    assert {v["value"]: v["objects"] for v in status["values"]} == want
    assert [v["objects"] for v in status["values"]] == sorted(want.values(), reverse=True)   # most held first
    assert read["states"][0]["property"] == "status"                                          # a status reads first


# ── the checks a draft is read against ──────────────────────────────────────────────────────────────────────────────

def test_objects_waiting_at_a_stage_for_over_a_year_are_asked_about_with_the_states_that_explain_them(db, graph):
    process, measured = measured_draft(db, graph, DELIVERY)
    promise = measured.stages[2].promise
    (stuck,) = [c for c in design_checks(db, graph, process, measured) if c["id"] == "stuck:delivered"]
    as_of = promise.as_of[:10]
    cutoff = cutoff_days(promise.as_of, STALE_DAYS)
    open_ = one(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE shipped_at IS NOT NULL AND delivered_at IS NULL")
    stale = one(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE shipped_at IS NOT NULL AND delivered_at IS NULL "
                    f"AND shipped_at < DATE '{cutoff[:10]}'")
    assert as_of == str(one(db, "SELECT MAX(delivered_at) FROM ecommerce.orders"))[:10]
    assert stuck["level"] == "ask" and stuck["numbers"]["open"] == open_ == 1100
    assert stuck["numbers"]["stale"] == stale > 0 and stuck["numbers"]["overdue"] == promise.open_overdue
    assert f"{open_:,} orders reached Shipped and never Delivered, {stale:,} of them more than a year ago" in stuck["says"]
    by = {r[0]: r[1] for r in rows(db, "SELECT status, COUNT(*) FROM ecommerce.orders WHERE shipped_at IS NOT NULL "
                                       f"AND delivered_at IS NULL AND shipped_at < DATE '{cutoff[:10]}' GROUP BY 1")}
    exit_ = stuck["exit"]
    assert sorted(exit_["values"]) == ["cancelled", "refunded"] == sorted(by)                 # neither alone explains it
    assert exit_["explains"] == stale and exit_["of"] == stale
    assert exit_["holding"] == one(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE status IN ('cancelled', 'refunded')")
    assert exit_["recent"] == open_ - stale                                                    # what the exit also takes
    # the objects the check is about are listed through the object door, by its own filters
    counter = ObjectCounter(db, graph)
    listed = counter.one(stuck["show"]["entity"], [{"name": "n", "agg": "count"}], stuck["show"]["filters"])
    assert int(listed["n"]) == stale


def test_once_the_way_they_left_is_declared_nothing_is_asked_and_who_left_is_said(db, graph):
    spec = {**DELIVERY, "leaves": {"property": "status", "values": ["cancelled", "refunded"]}}
    process, measured = measured_draft(db, graph, spec)
    checks = design_checks(db, graph, process, measured)
    assert not [c for c in checks if c["level"] == "ask"]
    (left,) = [c for c in checks if c["id"] == "leaves"]
    gone = one(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE status IN ('cancelled', 'refunded')")
    assert left["level"] == "ok" and left["says"].startswith(f"{gone:,} orders whose status is cancelled or refunded")


def test_moments_dated_after_today_are_said_and_listed(db, graph):
    process, measured = measured_draft(db, graph, DELIVERY)
    checks = {c["id"]: c for c in design_checks(db, graph, process, measured, now="2024-06-01T00:00:00+00:00")}
    for col, stage in (("order_date", "placed"), ("shipped_at", "shipped"), ("delivered_at", "delivered")):
        future = one(db, f"SELECT COUNT(*) FROM ecommerce.orders WHERE {col} > DATE '2024-06-01'")
        assert future > 0 and checks[f"future:{stage}"]["says"].startswith(f"{future:,} ")
        listed = ObjectCounter(db, graph).one("order", [{"name": "n", "agg": "count"}], checks[f"future:{stage}"]["show"]["filters"])
        assert int(listed["n"]) == future
    assert not [c for c in design_checks(db, graph, process, measured) if c["id"].startswith("future:")]


def test_stages_in_order_are_said_ok_and_one_out_of_order_is_said_and_listed(db, graph):
    process, measured = measured_draft(db, graph, DELIVERY)
    skipped = one(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE delivered_at IS NOT NULL AND shipped_at IS NULL")
    early = one(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE delivered_at < shipped_at")
    ids = {c["id"] for c in design_checks(db, graph, process, measured)}
    assert (skipped, early) == (0, 0) and "order" in ids and not ids & {"skipped:delivered", "early:delivered"}
    backwards = {**DELIVERY, "id": "backwards", "stages": [
        {"name": "shipped", "timestamp": "shipped_at"}, {"name": "placed", "timestamp": "order_date"}]}
    process, measured = measured_draft(db, graph, backwards)
    checks = design_checks(db, graph, process, measured)
    assert "order" not in {c["id"] for c in checks}                                            # no all-clear beside it
    (early_check,) = [c for c in checks if c["id"] == "early:placed"]
    assert early_check["says"].startswith(
        f"{one(db, 'SELECT COUNT(*) FROM ecommerce.orders WHERE order_date < shipped_at'):,} reach placed before")


def test_what_a_process_creates_is_said_with_its_number_now(db, graph):
    _, measured = measured_draft(db, graph, DELIVERY)
    made = {c["name"]: c for c in creates(measured)}
    promise = measured.stages[2].promise
    assert made["overdue_delivery"]["value"] == promise.open_overdue
    assert made["delivery_breach_rate"]["value"] == promise.breach_rate
    assert made["delivery_lag_days"]["value"] == measured.stages[2].p50_days


# ── the doors: counted, never written ───────────────────────────────────────────────────────────────────────────────

class _Kept:
    """The fixture's connection, handed to a door that closes what it opens."""
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


@pytest.fixture
def served(db, graph, monkeypatch):
    from aughor.routers import ontology as ONT
    monkeypatch.setattr(ONT, "_get_ontology_graph", lambda conn, schema=None: graph)
    monkeypatch.setattr(ONT, "_resolve_schema", lambda conn, schema=None: SCHEMA)
    monkeypatch.setattr("aughor.db.connection.open_connection_for_with_schema", lambda conn, schema=None: _Kept(db))
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_the_preview_door_counts_a_draft_as_declaring_it_would_and_writes_nothing(served, db, graph):
    r = served.post("/ontology/processes/preview", params={"connection_id": CONN}, json=DELIVERY)
    assert r.status_code == 200, r.text
    body = r.json()
    _, measured = measured_draft(db, graph, DELIVERY)
    assert [s["reached"] for s in body["process"]["stages"]] == [s.reached for s in measured.stages]
    assert "stuck:delivered" in {c["id"] for c in body["checks"]}
    assert {c["name"] for c in body["creates"]} >= {"overdue_delivery", "delivery_breach_rate"}
    assert find_override(CONN, SCHEMA, "process", "order_delivery") is None                    # nothing written
    assert "order_delivery" not in graph.processes


def test_the_preview_door_refuses_what_declaring_would_refuse(served, graph):
    bad = served.post("/ontology/processes/preview", params={"connection_id": CONN}, json={**DELIVERY, "id": "Order delivery"})
    assert bad.status_code == 400 and "snake_case" in bad.json()["detail"]
    graph.processes["order_delivery"] = process_from_fields("order_delivery", process_fields(DELIVERY))
    taken = served.post("/ontology/processes/preview", params={"connection_id": CONN}, json=DELIVERY)
    assert taken.status_code == 409


def test_the_candidates_door_reads_a_type_and_refuses_one_it_does_not_have(served, db):
    r = served.get("/ontology/processes/candidates", params={"connection_id": CONN, "entity": "Order"})
    assert r.status_code == 200 and r.json()["objects"] == one(db, "SELECT COUNT(*) FROM ecommerce.orders")
    by_api = served.get("/ontology/processes/candidates", params={"connection_id": CONN, "entity": "order"})
    assert by_api.status_code == 200 and by_api.json()["entity"] == "Order"
    assert served.get("/ontology/processes/candidates", params={"connection_id": CONN, "entity": "Nope"}).status_code == 404
