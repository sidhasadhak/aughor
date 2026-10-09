"""Arc OC-3, first slice — a metric keyed to the entity it measures (ROADMAP §3.56).

Before: every approved metric named tables and a grain column, never the entity whose objects it counts, so a release
could only guess what a change to the ontology touched and nothing read an approved metric as an entity's measure.
Now the grain's table — else the one entity its tables or its statement are backed by — proposes the entity, with why;
a person confirms it through `PUT /metrics/{name}/entity`, which leaves the statement, status and version untouched; an
edit keeps it; the census counts how many metrics are keyed; and the dependents index and a release's diff read it.

Live: on theLook every one of the 15 metrics drew a proposal — fourteen from their grain, one from its table.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from aughor.ontology import keys as K
from aughor.ontology.models import Backing, EntityProperty, OntologyEntity, OntologyGraph

CONN = "keys-t"


def _entity(eid: str, table: str, *props: str) -> OntologyEntity:
    return OntologyEntity(id=eid, display_name=eid, source_tables=[table], identity_key="id", grain_verified=True,
                          backing=Backing(kind="table", table=table, verified=True),
                          properties={p: EntityProperty(name=p, data_type="TIMESTAMP") for p in props})


def _graph() -> OntologyGraph:
    return OntologyGraph(connection_id=CONN, schema_name="shop", schema_fingerprint="x",
                         entities={"OrderItem": _entity("OrderItem", "order_items", "created_at", "shipped_at"),
                                   "InventoryItem": _entity("InventoryItem", "inventory_items", "sold_at"),
                                   "Order": _entity("Order", "orders", "created_at")},
                         table_to_entity={"order_items": "OrderItem", "inventory_items": "InventoryItem",
                                          "orders": "Order"})


# ── the proposal, from the metric's own declaration ───────────────────────────────────────────

@pytest.mark.parametrize("metric, entity, prop, says", [
    (NS(time_column="order_items.created_at", tables=["order_items"], sql=""), "OrderItem", "created_at", "its grain"),
    (NS(time_column="shop.order_items.shipped_at", tables=[], sql=""), "OrderItem", "shipped_at", "its grain"),
    (NS(time_column="sold_at", tables=["inventory_items"], sql="COUNT(id)"), "InventoryItem", "sold_at",
     "the table it names"),
    # a CTE named like a table is not that table: only `order_items` is read
    (NS(time_column="", tables=[], sql="WITH orders AS (SELECT order_id FROM order_items) SELECT COUNT(*) FROM orders"),
     "OrderItem", "", "the table its statement reads"),
])
def test_a_metric_proposes_the_entity_its_own_declaration_names(metric, entity, prop, says):
    p = K.propose_metric_entity(metric, _graph())
    assert (p["entity"], p["property"]) == (entity, prop) and says in p["why"]


def test_a_metric_over_two_entities_with_no_grain_proposes_none_and_says_why():
    p = K.propose_metric_entity(NS(time_column="", tables=["order_items", "inventory_items"], sql=""), _graph())
    assert p["entity"] == "" and p["candidates"] == ["InventoryItem", "OrderItem"] and "a person says" in p["why"]
    none = K.propose_metric_entity(NS(time_column="", tables=["refunds"], sql=""), _graph())
    assert none["entity"] == "" and "backs an entity" in none["why"]


# ── confirmed by a person, kept through an edit, counted ──────────────────────────────────────

@pytest.fixture
def store(monkeypatch, tmp_path):
    from aughor.semantic import metrics as M
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    monkeypatch.setattr("aughor.semantic.metric_time.with_dates", lambda c, m: m)
    graph = _graph()
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema=None: graph)
    monkeypatch.setattr("aughor.routers.ontology._get_ontology_graph", lambda conn, schema=None: graph)
    M.save_metric(M.MetricDefinition(name="revenue", connection=CONN, schema_name="shop", label="Revenue",
                                     sql="SELECT SUM(sale_price) AS revenue FROM order_items",
                                     tables=["order_items"], time_column="order_items.created_at",
                                     status="approved", version=3, approved_by="finance"))
    from fastapi.testclient import TestClient

    from aughor.api import app
    return TestClient(app)


def test_a_person_confirms_the_entity_and_nothing_it_computes_changes(store):
    from aughor.semantic import metrics as M
    r = store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"}, json={"entity": "OrderItem"})
    assert r.status_code == 200, r.text
    m = M.definition_at("revenue", CONN, "shop")
    assert (m.entity, m.status, m.version, m.sql) == ("OrderItem", "approved", 3,
                                                      "SELECT SUM(sale_price) AS revenue FROM order_items")
    assert m.entity_confirmed_by                              # the person signed in, never a name a form sent
    keys = store.get("/ontology/keys", params={"connection_id": CONN, "schema_name": "shop"}).json()["metrics"]
    (row,) = keys
    assert (row["entity"], row["proposal"]["entity"], row["agrees"]) == ("OrderItem", "OrderItem", True)


def test_an_entity_the_scope_does_not_serve_is_refused_and_an_empty_one_clears(store):
    from aughor.semantic import metrics as M
    r = store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"}, json={"entity": "Refund"})
    assert r.status_code == 400 and "no entity 'Refund'" in r.json()["detail"] and "OrderItem" in r.json()["detail"]
    store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"}, json={"entity": "OrderItem"})
    assert store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"},
                     json={"entity": ""}).status_code == 200
    m = M.definition_at("revenue", CONN, "shop")
    assert m.entity is None and m.entity_confirmed_by is None


def test_an_edit_keeps_the_confirmed_entity(store):
    from aughor.semantic import metrics as M
    store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"}, json={"entity": "OrderItem"})
    m = M.definition_at("revenue", CONN, "shop")
    body = {**m.model_dump(), "label": "Gross revenue"}
    r = store.put("/metrics/revenue", params={"schema": "shop"}, json=body)
    assert r.status_code == 200, r.text
    edited = M.definition_at("revenue", CONN, "shop")
    assert (edited.label, edited.entity) == ("Gross revenue", "OrderItem")


def test_the_census_counts_keyed_metrics(store):
    store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"}, json={"entity": "OrderItem"})
    from aughor.semantic import metrics as M
    M.save_metric(M.MetricDefinition(name="orders", connection=CONN, schema_name="shop", label="Orders",
                                     sql="SELECT COUNT(*) FROM orders", status="approved"))
    assert K.keyed_counts()["metrics"] == {"of": 2, "n": 1}


# ── what relies on an entity now includes the metrics keyed to it ─────────────────────────────

def test_a_keyed_metric_relies_on_its_entity(store, monkeypatch):
    from aughor.ontology.dependents import dependents_of
    store.put("/metrics/revenue/entity", params={"connection_id": CONN, "schema": "shop"}, json={"entity": "OrderItem"})
    rows = dependents_of(_graph(), CONN, "entity", "OrderItem", automations=[])
    assert ("metric", "revenue", "the approved metric measures its objects") in {
        (r["consumer"], r["id"], r["how"]) for r in rows}
    assert dependents_of(_graph(), CONN, "entity", "Order", automations=[]) == []
