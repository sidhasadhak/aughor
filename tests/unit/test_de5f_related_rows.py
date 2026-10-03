"""DE-5f (ROADMAP §3.51) — the rows related to a value, through the joins the data bears out.

Measured first: the ontology's relationships carry the measured value overlap and cardinality, but only
between tables that resolve to object types; the join map carries declared keys and name matches with no
overlap until the join guard probes them; and the one door that opened "linked rows" needed object types
and a measured cardinality. These pin the new door: every join touching a column is listed with its
evidence in the catalog's own words, the rows are opened only through a verified or declared join — never on
a name alone, never through a pair the values disprove — and the statement runs through the run's door with
the value BOUND, so a quote in a key is a quote in a key.

Hermetic: a DuckDB file with a declared key (orders.buyer → customers.id), a name match the values bear out
(events.customer_id ↔ customers.id) and one they disprove (customers.region_id ↔ regions.id).
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)

QUOTED = "c'1"


@pytest.fixture()
def shop(tmp_path):
    db = tmp_path / "de5f.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE customers(id VARCHAR PRIMARY KEY, name VARCHAR, region_id INTEGER)")
    c.execute("INSERT INTO customers VALUES ('c''1', 'Ada', 1), ('c2', 'Bo', 2), ('c3', 'Cy', 3)")
    c.execute("CREATE TABLE orders(order_id INTEGER, buyer VARCHAR REFERENCES customers(id), total DOUBLE)")
    c.execute("INSERT INTO orders VALUES (1, 'c''1', 10), (2, 'c''1', 20), (3, 'c2', 5)")
    c.execute("CREATE TABLE events(event_id INTEGER, customer_id VARCHAR)")
    c.execute("INSERT INTO events VALUES (1, 'c''1'), (2, 'c3'), (3, 'c3')")
    c.execute("CREATE TABLE regions(id INTEGER, name VARCHAR)")
    c.execute("INSERT INTO regions VALUES (900, 'north'), (901, 'south')")
    c.close()
    cid = registry.add_connection("de5f", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _joins(cid: str, table: str, column: str) -> dict:
    r = client.get(f"/connections/{cid}/related-joins", params={"table": table, "column": column})
    assert r.status_code == 200, r.text
    return r.json()


def _by_other(body: dict) -> dict:
    return {(j["other_table"].split(".")[-1], j["other_column"]): j for j in body["joins"]}


def _open(cid: str, **body) -> dict:
    r = client.post("/query/related", json={"conn_id": cid, **body})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1 · the joins touching a column, with their evidence ──────────────────────────────────────────

def test_a_declared_key_is_listed_with_its_measured_overlap(shop):
    body = _joins(shop, "orders", "buyer")
    assert body["ontology"] == "not built" and "join_map" not in body
    joins = _by_other(body)
    edge = joins[("customers", "id")]
    assert edge["match"] == "declared" and edge["verdict"] == "verified" and edge["openable"] is True
    assert edge["overlap"] == 1.0 and edge["source"] == "join_map"
    assert edge["sentence"] == "100% value overlap; declared foreign key"


def test_a_key_column_lists_both_sides_declared_and_name_matched(shop):
    joins = _by_other(_joins(shop, "customers", "id"))
    assert joins[("orders", "buyer")]["match"] == "declared" and joins[("orders", "buyer")]["openable"] is True
    inferred = joins[("events", "customer_id")]
    assert inferred["match"] in ("exact", "inferred") and inferred["verdict"] == "verified"
    assert inferred["openable"] is True and inferred["overlap"] is not None and inferred["overlap"] >= 0.5
    assert "value overlap" in inferred["sentence"] and "declared" not in inferred["sentence"]


def test_a_name_match_the_values_disprove_is_listed_and_not_openable(shop):
    joins = _by_other(_joins(shop, "customers", "region_id"))
    rejected = joins[("regions", "id")]
    assert rejected["verdict"] == "rejected" and rejected["openable"] is False
    assert rejected["overlap"] == 0.0
    assert rejected["sentence"] == "0% value overlap — the columns share a name and not their values"


def test_a_column_with_no_join_answers_an_empty_list_not_a_guess(shop):
    body = _joins(shop, "orders", "total")
    assert body["joins"] == [] and body["ontology"] == "not built"


# ── 2 · the rows, through the door, with the value bound ──────────────────────────────────────────

def test_related_rows_open_through_a_declared_key_with_the_value_bound(shop):
    from aughor.security.audit import AuditLogger
    before = len(AuditLogger.recent(limit=500, connection_id=shop, label="query_workbench"))
    body = _open(shop, table="orders", column="buyer", value=QUOTED, other_table="customers", other_column="id")
    assert body["error"] is None and body["code"] is None and body["format"] == "typed"
    assert body["columns"] == ["id", "name", "region_id"]
    assert body["rows"] == [[QUOTED, "Ada", 1]], "the one customer the quoted key names"
    assert body["sql"] == 'SELECT * FROM "customers" WHERE "id" = :v', "identifiers quoted, the value never in the text"
    assert body["params"] == {"v": QUOTED}
    assert body["label"] == "customers rows related to orders.buyer = c'1"
    assert body["caveats"][0] == ("Related through orders.buyer = customers.id — 100% value overlap; declared "
                                  "foreign key.")
    assert body["join"]["verdict"] == "verified" and body["truncated"] is False
    after = AuditLogger.recent(limit=500, connection_id=shop, label="query_workbench")
    assert len(after) == before + 1, "one audit row under the run's label"


def test_related_rows_open_the_other_way_and_through_a_verified_name_match(shop):
    orders = _open(shop, table="customers", column="id", value=QUOTED, other_table="orders", other_column="buyer")
    assert orders["error"] is None and sorted(r[0] for r in orders["rows"]) == [1, 2]
    events = _open(shop, table="customers", column="id", value="c3", other_table="events", other_column="customer_id")
    assert events["error"] is None and sorted(r[0] for r in events["rows"]) == [2, 3]
    assert "value overlap" in events["caveats"][0] and "declared" not in events["caveats"][0]


def test_rows_are_never_opened_on_a_guess(shop):
    # A pair the values disprove: refused with the join's own evidence.
    body = _open(shop, table="customers", column="region_id", value=1, other_table="regions", other_column="id")
    assert body["code"] == "JOIN_NOT_VERIFIED" and body["rows"] == []
    assert "0% value overlap" in body["error"] and body["join"]["verdict"] == "rejected"
    # A pair no join connects at all.
    body = _open(shop, table="orders", column="buyer", value=QUOTED, other_table="events", other_column="customer_id")
    assert body["code"] == "JOIN_NOT_VERIFIED" and "not opened on a guess" in body["error"] and body["join"] is None
    # A NULL has nothing to match; an unknown connection is a 404.
    r = client.post("/query/related", json={"conn_id": shop, "table": "orders", "column": "buyer", "value": None,
                                            "other_table": "customers", "other_column": "id"})
    assert r.status_code == 400
    r = client.post("/query/related", json={"conn_id": "nope", "table": "orders", "column": "buyer", "value": 1,
                                            "other_table": "customers", "other_column": "id"})
    assert r.status_code == 404


# ── 3 · the ontology's edge leads, with its overlap and cardinality ────────────────────────────────

def test_the_ontology_edge_leads_with_overlap_and_cardinality_both_ways(shop, tmp_path, monkeypatch):
    from aughor.ontology import store as ST
    from aughor.ontology.models import OntologyGraph, OntologyRelationship
    from aughor.util.json_store import KeyedJsonStore
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    rel = OntologyRelationship(
        id="Order_RELATES_TO_Customer", from_entity="Order", to_entity="Customer", cardinality="N:1",
        join_sql="orders.buyer = customers.id", from_table="orders", from_col="buyer",
        to_table="customers", to_col="id", join_confidence="verified", value_overlap=0.97,
        measured_cardinality="N:1")
    graph = OntologyGraph(connection_id=shop, schema_fingerprint="fp", relationships={rel.id: rel})
    ST.save_ontology(shop, "main", "fp", graph)

    forward = _by_other(_joins(shop, "orders", "buyer"))
    edge = forward[("customers", "id")]
    assert edge["source"] == "ontology" and edge["overlap"] == 0.97 and edge["cardinality"] == "N:1"
    assert edge["sentence"] == "97% value overlap; N:1" and edge["openable"] is True
    assert len(forward) == 1, "the join map's copy of the same pair is not listed twice"

    back = _by_other(_joins(shop, "customers", "id"))
    assert back[("orders", "buyer")]["cardinality"] == "1:N", "the cardinality reads from this column's side"
    assert back[("events", "customer_id")]["source"] == "join_map", "a pair the ontology does not hold still comes from the map"

    opened = _open(shop, table="orders", column="buyer", value="c2", other_table="customers", other_column="id")
    assert opened["caveats"][0] == "Related through orders.buyer = customers.id — 97% value overlap; N:1."


# ── 4 · the words and the statement ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("match, overlap, rejected, verdict, sentence", [
    ("declared", 1.0, False, "verified", "100% value overlap; declared foreign key"),
    ("exact", 0.8, False, "verified", "80% value overlap"),
    ("declared", None, False, "declared", "declared foreign key — not probed"),
    ("inferred", None, False, "unprobed", "name match — not probed, so not opened on the name alone"),
    ("declared", 0.12, True, "disputed", "DECLARED foreign key, but only 12% value overlap — the declaration and the data disagree"),
    ("inferred", 0.0, True, "rejected", "0% value overlap — the columns share a name and not their values"),
])
def test_each_verdict_has_its_sentence_and_only_two_open_rows(match, overlap, rejected, verdict, sentence):
    from aughor.sql.related import OPENABLE, sentence_for, verdict_for
    v = verdict_for(match, overlap, rejected=rejected)
    assert v == verdict
    assert sentence_for(match, overlap, v, None) == sentence
    assert sentence_for(match, overlap, v, "N:1") == sentence + "; N:1"
    assert (v in OPENABLE) is (v in ("verified", "declared"))


def test_the_statement_quotes_for_the_engine_and_binds_the_value():
    from aughor.sql.related import related_label, related_sql

    class _Duck:
        dialect = "duckdb"

    class _My:
        dialect = "mysql"

    assert related_sql(_Duck(), "customers", "id") == 'SELECT * FROM "customers" WHERE "id" = :v'
    assert related_sql(_Duck(), "customers", "id", "shop") == 'SELECT * FROM "shop"."customers" WHERE "id" = :v'
    assert related_sql(_Duck(), "shop.customers", "id", "other") == 'SELECT * FROM "shop"."customers" WHERE "id" = :v'
    assert related_sql(_Duck(), "customers", "id", "main") == 'SELECT * FROM "customers" WHERE "id" = :v'
    assert related_sql(_My(), "customers", "id") == "SELECT * FROM `customers` WHERE `id` = :v"
    assert related_label("shop.customers", "orders", "buyer", "x" * 40) == "customers rows related to orders.buyer = " + "x" * 23 + "…"


def test_the_rbac_table_knows_the_route():
    from aughor.rbac.policy import POLICY
    assert POLICY[("POST", "/query/related")] == POLICY[("POST", "/query/run")]
