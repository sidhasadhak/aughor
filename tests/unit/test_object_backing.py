"""ON-1: the noun decouples from the table.

An object type has a stable `api_name`, a `backing` (its table by default; a keyed SELECT
when a human sets one), links have a name on each side, and the backing's key is MEASURED
unique — the way every claim is measured since ON-0a. Every existing consumer of the table
reads it byte-identically; the validator probes a query-backed object through its SELECT.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology import models as M
from aughor.ontology import overrides as OV
from aughor.ontology.backing import apply_backing_measurements, entity_from_clause, measure_override_backings
from aughor.ontology.models import Backing, OntologyEntity, OntologyGraph, OntologyRelationship, snake_name
from aughor.ontology.validator import _entity_table, validate_semantics

REPO = Path(__file__).resolve().parents[2]
LUX = REPO / "evals" / "ablation_luxexperience_ontology.json"

_WH = """
CREATE SCHEMA crm;
CREATE TABLE crm.customers (customer_id INT, name VARCHAR);
INSERT INTO crm.customers VALUES (1,'a'), (2,'b'), (3,'c');
CREATE TABLE crm.customer_profiles (customer_id INT, lifetime_spend DOUBLE, lifetime_orders INT);
INSERT INTO crm.customer_profiles VALUES (1, 100.0, 2), (2, 50.0, 1), (3, 0.0, 0);
CREATE TABLE crm.reviews (product_id VARCHAR, rating INT);
INSERT INTO crm.reviews VALUES ('p1', 5), ('p1', 4), ('p2', 3);
"""

_CUSTOMER_SQL = ("SELECT c.customer_id, c.name, p.lifetime_spend, p.lifetime_orders "
                 "FROM crm.customers c JOIN crm.customer_profiles p ON p.customer_id = c.customer_id")


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def _db(tmp_path):
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path)); con.execute(_WH); con.close()
    return open_connection("duckdb", str(path), connection_id="t")


def _entity(eid="Customer", table="crm.customers", pk="customer_id", grain=True, **kw) -> OntologyEntity:
    return OntologyEntity(id=eid, display_name=eid, source_tables=[table], identity_key=pk, grain_verified=grain, **kw)


def test_names_and_backings_fill_from_the_id_and_the_first_table():
    assert snake_name("OrderItem") == "order_item" and snake_name("ReturnLogistic") == "return_logistic"
    e = _entity("OrderItem", "shop.order_items", "order_item_id")
    assert e.api_name == "order_item"
    assert e.backing == Backing(kind="table", table="shop.order_items", primary_key="order_item_id")
    r = OntologyRelationship(id="R", from_entity="OrderItem", to_entity="Order", cardinality="N:1",
                             join_sql="", from_table="shop.order_items", from_col="order_id", to_table="shop.orders", to_col="order_id")
    assert (r.api_name, r.reverse_api_name) == ("order_item_to_order", "order_to_order_item")
    explicit = _entity("Order", "shop.orders", "order_id", api_name="sales_order")
    assert explicit.api_name == "sales_order"                      # a set name is never overwritten


def test_a_graph_built_before_on1_loads_with_every_single_table_type_unchanged():
    g = OntologyGraph.model_validate(json.loads(LUX.read_text()))
    for e in g.entities.values():
        assert e.backing.kind == "table" and e.backing.table == e.source_tables[0]
        assert e.backing.primary_key == e.identity_key and e.api_name == snake_name(e.id)
    raw = json.loads(LUX.read_text())["entities"]["Order"]
    dumped = g.entities["Order"].model_dump()
    assert all(dumped[k] == raw[k] for k in raw)                    # every pre-existing field byte-identical
    assert g.table_to_entity == json.loads(LUX.read_text())["table_to_entity"]   # the ERD underneath is untouched


def test_a_query_backing_reads_through_its_select_and_the_table_backing_reads_the_table():
    e = _entity()
    assert _entity_table(OntologyGraph(connection_id="c", schema_fingerprint="f", entities={e.id: e}), "Customer") == "crm.customers"
    q = _entity(backing=Backing(kind="query", sql=_CUSTOMER_SQL + ";", primary_key="customer_id"))
    assert entity_from_clause(q) == f"({_CUSTOMER_SQL}) AS b"
    assert _entity_table(OntologyGraph(connection_id="c", schema_fingerprint="f", entities={q.id: q}), "Customer") == f"({_CUSTOMER_SQL}) AS b"


def test_backing_keys_are_measured_and_a_false_grain_claim_is_corrected(tmp_path):
    db = _db(tmp_path)
    try:
        good = _entity("Customer", "crm.customers", "customer_id", grain=True)
        liar = _entity("Review", "crm.reviews", "product_id", grain=True)        # 114-duplicates shape
        q = _entity("Customer360", "crm.customers", "customer_id", grain=True,
                    backing=Backing(kind="query", sql=_CUSTOMER_SQL, primary_key="customer_id"))
        bad_q = _entity("CustomerX", "crm.customers", "customer_id", grain=True,
                        backing=Backing(kind="query", sql="SELECT * FROM crm.reviews", primary_key="product_id"))
        g = OntologyGraph(connection_id="c", schema_fingerprint="f", entities={e.id: e for e in (good, liar, q, bad_q)})
        report = apply_backing_measurements(g, db)
        assert good.backing.verified is True and good.grain_verified is True
        assert liar.backing.verified is False and liar.grain_verified is False
        assert "grain_verified was True; measured False" in liar.backing.verification_note
        assert q.backing.verified is True and q.grain_verified is True
        assert bad_q.backing.verified is False and "NOT unique" in bad_q.backing.verification_note
        assert report.grain_refuted == ["Review"] and report.grain_confirmed == []
        assert report.summary()["not_unique"][0]["entity"] == "Review"
    finally:
        db.close()


def test_a_derived_property_is_verified_against_the_two_table_backing(tmp_path):
    """The ON-1 receipt: a Customer backed by two tables with lifetime_value derived."""
    db = _db(tmp_path)
    try:
        cust = _entity("Customer", "crm.customers", "customer_id",
                       backing=Backing(kind="query", sql=_CUSTOMER_SQL, primary_key="customer_id"))
        cust.computed_properties.append(M.ComputedProperty(id="lifetime_value", label="Lifetime value",
                                                           formula_sql="SUM(lifetime_spend) / NULLIF(SUM(lifetime_orders), 0)", unit="$"))
        cust.computed_properties.append(M.ComputedProperty(id="broken", label="Broken", formula_sql="SUM(no_such_col)"))
        g = OntologyGraph(connection_id="c", schema_fingerprint="f", entities={"Customer": cust})
        validate_semantics(g, db)
        by = {cp.id: cp for cp in g.entities["Customer"].computed_properties}
        assert by["lifetime_value"].verified is True
        assert by["broken"].verified is False and by["broken"].verification_note
    finally:
        db.close()


def test_a_human_backing_binds_by_dry_run_and_earns_verified_only_when_measured(tmp_path):
    conn, schema = "c", "crm"
    ov = OV.OntologyOverride(target_kind="entity", target_id="Customer",
                             fields={"backing": {"kind": "query", "sql": _CUSTOMER_SQL, "primary_key": "customer_id"}})
    OV.bind_overrides(ov, None, lambda sql: None)
    assert ov.binding["backing"]["bound"] is True and "unique" not in ov.binding["backing"]
    OV.save_override(conn, schema, ov)
    e = _entity()
    g = OntologyGraph(connection_id=conn, schema_name=schema, schema_fingerprint="f", entities={"Customer": e})
    OV.apply_overrides(g, conn, schema)
    assert e.backing.kind == "query" and e.backing.sql == _CUSTOMER_SQL
    assert e.backing.verified is None and "not yet measured" in e.backing.verification_note
    db = _db(tmp_path)
    try:
        report = measure_override_backings(conn, schema, db)
    finally:
        db.close()
    assert report.overrides_measured == ["Customer"]
    saved = OV.find_override(conn, schema, "entity", "Customer")
    assert saved.binding["backing"]["unique"] is True
    e2 = _entity()
    g2 = OntologyGraph(connection_id=conn, schema_name=schema, schema_fingerprint="f", entities={"Customer": e2})
    OV.apply_overrides(g2, conn, schema)
    assert e2.backing.verified is True                                   # the measurement rides the overlay
    assert e2.source_tables == ["crm.customers"]                          # the ERD underneath is untouched
    # an unbound backing never earns verified
    bad = OV.OntologyOverride(target_kind="entity", target_id="Customer",
                              fields={"backing": {"kind": "query", "sql": "SELECT nope FROM nowhere", "primary_key": "x"}})
    OV.bind_overrides(bad, None, lambda sql: "no such table")
    assert bad.binding["backing"]["bound"] is False
    e3 = _entity(); OV._apply_entity(e3, bad)
    assert e3.backing.verified is False


def test_the_entity_route_accepts_a_backing_and_the_read_path_shows_it(tmp_path, monkeypatch, client):
    from aughor.ontology import store as ST
    from aughor.routers import ontology as R
    from aughor.util.json_store import KeyedJsonStore
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    e = _entity()
    ST.save_ontology("cid", "crm", "fp", OntologyGraph(connection_id="cid", schema_name="crm", schema_fingerprint="fp", entities={"Customer": e}))
    monkeypatch.setattr(R, "_explain_for", lambda _cid: ((lambda sql: None), (lambda: None)))
    r = client.put("/ontology/entities/Customer", params={"connection_id": "cid", "schema_name": "crm"},
                   json={"backing": {"kind": "query", "sql": _CUSTOMER_SQL, "primary_key": "customer_id"}})
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True and r.json()["override"]["binding"]["backing"]["bound"] is True
    got = client.get("/ontology/entities", params={"connection_id": "cid", "schema_name": "crm"})
    assert got.status_code == 200, got.text
    cust = got.json()["Customer"]                                   # the route returns {id: entity}
    assert cust["backing"]["kind"] == "query" and cust["api_name"] == "customer"
    assert cust["source_tables"] == ["crm.customers"]
