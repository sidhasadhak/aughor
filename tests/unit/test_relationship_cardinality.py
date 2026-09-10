"""ON-0a, first commit: relationship cardinality is MEASURED against the data.

The served LuxExperience ontology (committed verbatim as the ON-0 ablation fixture) carries
verified joins labelled N:N that the data shows are N:1 or 1:1 — the validator had proved
the keys overlap and nothing had measured the cardinality. These tests pin the measurement
and ratchet the fixture: the wrong labels are named, and the measurement must fix exactly
them while leaving the genuine N:N edges alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology.cardinality import (
    apply_cardinality_measurements, label_for, measure_side,
)
from aughor.ontology.models import OntologyGraph, OntologyRelationship
from aughor.ontology.semantic_block import render_relationship_block

REPO = Path(__file__).resolve().parents[2]
LUX_FIXTURE = REPO / "evals" / "ablation_luxexperience_ontology.json"


def _db(tmp_path, ddl: str):
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute(ddl)
    con.close()
    return open_connection("duckdb", str(path), connection_id="t")


def _rel(rid, ft, fc, tt, tc, card="N:N", conf="verified"):
    return OntologyRelationship(
        id=rid, from_entity=ft.split(".")[-1], to_entity=tt.split(".")[-1], verb="RELATES_TO",
        cardinality=card, join_sql=f"{ft}.{fc} = {tt}.{tc}", from_table=ft, from_col=fc,
        to_table=tt, to_col=tc, join_confidence=conf, value_overlap=1.0)


_SHAPES = """
CREATE TABLE ones (k INT); INSERT INTO ones VALUES (1), (2), (3), (NULL);
CREATE TABLE manys (k INT); INSERT INTO manys VALUES (1), (1), (2), (3), (3), (NULL), (NULL);
CREATE TABLE empties (k INT);
CREATE TABLE "Odd Name" ("Product type" VARCHAR); INSERT INTO "Odd Name" VALUES ('a'), ('b'), ('a');
"""


def test_a_side_is_unique_over_its_non_null_rows(tmp_path):
    db = _db(tmp_path, _SHAPES)
    try:
        ones = measure_side(db, "ones", "k")
        assert (ones.rows, ones.non_null, ones.distinct, ones.unique, ones.side) == (4, 3, 3, True, "1")
        manys = measure_side(db, "manys", "k")
        assert (manys.non_null, manys.distinct, manys.side) == (5, 3, "N")
        assert measure_side(db, "empties", "k").non_null == 0          # counted, but nothing to say
        assert measure_side(db, "no_such_table", "k") is None           # a failed probe is None, never a guess
        odd = measure_side(db, "Odd Name", "Product type")               # identifiers that need quoting
        assert (odd.non_null, odd.distinct, odd.side) == (3, 2, "N")
    finally:
        db.close()


def test_labels_read_left_to_right_like_the_prompt(tmp_path):
    db = _db(tmp_path, _SHAPES)
    try:
        one, many = measure_side(db, "ones", "k"), measure_side(db, "manys", "k")
        assert label_for(many, one) == "N:1"      # many from-rows per to-row
        assert label_for(one, many) == "1:N"
        assert label_for(one, one) == "1:1"
        assert label_for(many, many) == "N:N"
    finally:
        db.close()


def test_a_contradicted_label_is_replaced_and_the_authored_one_survives_in_the_note(tmp_path):
    db = _db(tmp_path, _SHAPES)
    try:
        g = OntologyGraph(connection_id="c", schema_fingerprint="f",
                          relationships={"R": _rel("R", "manys", "k", "ones", "k", card="N:N")})
        report = apply_cardinality_measurements(g, db)
        rel = g.relationships["R"]
        assert rel.cardinality == "N:1" and rel.measured_cardinality == "N:1"
        assert rel.cardinality_note.startswith("authored N:N, measured N:1: ")
        assert [m.relationship_id for m in report.contradicted] == ["R"]
        assert rel.join_confidence == "verified"                          # the key overlap still stands
    finally:
        db.close()


def test_a_confirmed_label_is_stamped_and_an_unmeasurable_edge_is_left_untouched(tmp_path):
    db = _db(tmp_path, _SHAPES)
    try:
        g = OntologyGraph(connection_id="c", schema_fingerprint="f", relationships={
            "ok": _rel("ok", "manys", "k", "ones", "k", card="N:1"),
            "gone": _rel("gone", "manys", "k", "vanished", "k", card="N:N"),
            "empty": _rel("empty", "empties", "k", "ones", "k", card="N:1"),
        })
        report = apply_cardinality_measurements(g, db)
        assert g.relationships["ok"].measured_cardinality == "N:1"
        assert g.relationships["ok"].cardinality_note.startswith("measured N:1: ")
        for rid, authored in (("gone", "N:N"), ("empty", "N:1")):
            r = g.relationships[rid]
            assert r.cardinality == authored and r.measured_cardinality is None
            assert r.cardinality_note.startswith("not measurable: ")
        assert sorted(m.relationship_id for m in report.unmeasurable) == ["empty", "gone"]
        assert report.summary()["confirmed"] == 1
    finally:
        db.close()


# ── The ratchet on the served LuxExperience graph ─────────────────────────────────────────
# A hermetic warehouse that reproduces the KEY UNIQUENESS of the demo file for every table
# the served graph's verified joins touch (the 15 MB demo file is not in the repo):
#   orders / payments / shipments / customers / products / customer_service.order_id: unique
#   order_items.order_id, returns.order_id, return_logistics.order_id, price_history.product_id,
#   orders.customer_id, customer_service.customer_id: repeating
#   returns.return_id and return_logistics.return_id: unique (one logistics row per return)
_LUX_SHAPE = """
CREATE SCHEMA luxexperience;
CREATE TABLE luxexperience.customers (customer_id VARCHAR);
INSERT INTO luxexperience.customers VALUES ('c1'), ('c2'), ('c3');
CREATE TABLE luxexperience.orders (order_id VARCHAR, customer_id VARCHAR);
INSERT INTO luxexperience.orders VALUES ('o1','c1'), ('o2','c1'), ('o3','c2');
CREATE TABLE luxexperience.order_items (order_item_id VARCHAR, order_id VARCHAR, product_id VARCHAR);
INSERT INTO luxexperience.order_items VALUES ('i1','o1','p1'), ('i2','o1','p2'), ('i3','o2','p1'), ('i4','o3','p1');
CREATE TABLE luxexperience.payments (payment_id VARCHAR, order_id VARCHAR);
INSERT INTO luxexperience.payments VALUES ('pay1','o1'), ('pay2','o2'), ('pay3','o3');
CREATE TABLE luxexperience.shipments (shipment_id VARCHAR, order_id VARCHAR);
INSERT INTO luxexperience.shipments VALUES ('s1','o1'), ('s2','o2');
CREATE TABLE luxexperience.customer_service (ticket_id VARCHAR, customer_id VARCHAR, order_id VARCHAR);
INSERT INTO luxexperience.customer_service VALUES ('t1','c1','o1'), ('t2','c1','o2');
CREATE TABLE luxexperience.products (product_id VARCHAR);
INSERT INTO luxexperience.products VALUES ('p1'), ('p2');
CREATE TABLE luxexperience.price_history (price_id VARCHAR, product_id VARCHAR);
INSERT INTO luxexperience.price_history VALUES ('pr1','p1'), ('pr2','p1'), ('pr3','p2');
CREATE TABLE luxexperience.returns (return_id VARCHAR, order_item_id VARCHAR, order_id VARCHAR);
INSERT INTO luxexperience.returns VALUES ('r1','i1','o1'), ('r2','i2','o1');
CREATE TABLE luxexperience.return_logistics (return_logistics_id VARCHAR, return_id VARCHAR, order_id VARCHAR);
INSERT INTO luxexperience.return_logistics VALUES ('rl1','r1','o1'), ('rl2','r2','o1');
"""

#: The served graph's labels that the data contradicts (from_table, to_table) → measured.
#: `customer_service → orders` joins on customer_id and is genuinely N:N; it is NOT here.
_LUX_WRONG = {
    ("luxexperience.order_items", "luxexperience.orders"): "N:1",
    ("luxexperience.order_items", "luxexperience.payments"): "N:1",
    ("luxexperience.order_items", "luxexperience.shipments"): "N:1",
    ("luxexperience.return_logistics", "luxexperience.returns"): "1:1",
}
_LUX_GENUINE_NN = {
    ("luxexperience.customer_service", "luxexperience.orders"),
    ("luxexperience.order_items", "luxexperience.returns"),
    ("luxexperience.order_items", "luxexperience.return_logistics"),
}


@pytest.fixture(scope="module")
def lux_graph() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(LUX_FIXTURE.read_text()))


def _by_tables(graph):
    return {(r.from_table, r.to_table): r for r in graph.relationships.values()}


def test_the_served_luxexperience_graph_carries_the_four_wrong_labels(lux_graph):
    """Fails closed: if the committed fixture stops carrying them, this table is stale."""
    rels = _by_tables(lux_graph)
    for key in _LUX_WRONG:
        assert rels[key].cardinality == "N:N" and rels[key].join_confidence == "verified", key


def test_measurement_fixes_exactly_the_wrong_labels_on_the_served_graph(tmp_path, lux_graph):
    db = _db(tmp_path, _LUX_SHAPE)
    try:
        g = lux_graph.model_copy(deep=True)
        report = apply_cardinality_measurements(g, db)
        rels = _by_tables(g)
        for key, expected in _LUX_WRONG.items():
            assert rels[key].cardinality == expected == rels[key].measured_cardinality, key
            assert rels[key].cardinality_note.startswith("authored N:N, measured "), key
        for key in _LUX_GENUINE_NN:
            assert rels[key].cardinality == "N:N" == rels[key].measured_cardinality, key
        assert {(m.relationship_id) for m in report.contradicted} == {rels[k].id for k in _LUX_WRONG}
        assert not report.unmeasurable, [m.note for m in report.unmeasurable]
    finally:
        db.close()


def test_the_prompt_block_renders_the_measured_label(tmp_path, lux_graph):
    """The renderer reads `cardinality`, so a replaced label reaches the model with no new
    prose — the block's own CARDINALITY sentence finally applies to the join it was for."""
    db = _db(tmp_path, _LUX_SHAPE)
    try:
        g = lux_graph.model_copy(deep=True)
        cols = {"luxexperience.order_items": ["order_item_id", "order_id", "product_id"],
                "luxexperience.orders": ["order_id", "customer_id"]}
        before = render_relationship_block(g, cols)
        assert "luxexperience.order_items.order_id → luxexperience.orders.order_id [N:N, verified" in before
        apply_cardinality_measurements(g, db)
        after = render_relationship_block(g, cols)
        assert "luxexperience.order_items.order_id → luxexperience.orders.order_id [N:1, verified" in after
        assert "N:N" not in after
    finally:
        db.close()


def test_the_measure_door_relabels_the_cached_graph_without_a_rebuild(tmp_path, monkeypatch, lux_graph, client):
    """`POST /ontology/relationships/measure` measures the graph that is already cached and
    saves it back — the UI shows the corrected labels with no model call spent."""
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore
    import aughor.db.connection as C
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology("914df862", "luxexperience", "fp", lux_graph.model_copy(deep=True))
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path)); con.execute(_LUX_SHAPE); con.close()
    monkeypatch.setattr(C, "open_connection_for_with_schema",
                        lambda *_a, **_k: open_connection("duckdb", str(path), connection_id="t"))
    r = client.post("/ontology/relationships/measure",
                    params={"connection_id": "914df862", "schema_name": "luxexperience"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_name"] == "luxexperience" and body["relationships"] == 11
    assert body["confirmed"] == 7 and body["unmeasurable"] == []
    assert sorted((c["authored"], c["measured"]) for c in body["contradicted"]) == [
        ("N:N", "1:1"), ("N:N", "N:1"), ("N:N", "N:1"), ("N:N", "N:1")]
    saved = ST.load_ontology("914df862", "luxexperience", "fp")
    assert _by_tables(saved)[("luxexperience.order_items", "luxexperience.orders")].cardinality == "N:1"
    assert _by_tables(saved)[("luxexperience.order_items", "luxexperience.orders")].cardinality_note.startswith("authored N:N")
    # nothing cached for the scope → nothing is measured, and no neighbour is
    r2 = client.post("/ontology/relationships/measure", params={"connection_id": "914df862", "schema_name": "other"})
    assert r2.status_code == 404
