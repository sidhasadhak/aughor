"""R1 — a duplicate-entity merge is "two tables, one binding" (ROADMAP §3.15; the ON-7 leftovers).

The merge used to rewrite the cached graph. It walked the survivor's properties and segments as lists — they are
mappings, so a type with any property raised and the door answered 500 — unioned `source_tables` (a property of the
other table then compiled against the survivor's own), deleted the other types and repointed their links and
metrics, and wrote the raw cache a rebuild replaces. Now the survivor binds each other type's table on its key,
counted one row per object, and the other type becomes its PART: nothing is deleted, the edit lives in the overrides
tree, and a cluster the data does not hold is refused whole before anything is written.

Every count is held to a hand-written query over the seeded samples warehouse, plus three tables that hold the same
customers: `clients` (one column Customer lacks), `contacts` (none) and `profiles`.
"""
from __future__ import annotations

import json

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology import overrides as OV
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
from tests.unit.test_object_bindings import GRAPH, ints, payment_type, seed

CONN = "entity-merge-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}
MERGE = "/ontology/entities/merge"

SAME_CUSTOMERS = """
CREATE TABLE ecommerce.clients AS
SELECT customer_id AS client_id, full_name, email, city, country,
       CASE WHEN lifetime_spend >= 5000 THEN 'gold' WHEN lifetime_spend >= 1000 THEN 'silver' ELSE 'bronze' END AS tier
FROM ecommerce.customers;
CREATE TABLE ecommerce.contacts AS SELECT customer_id AS contact_id, full_name, email FROM ecommerce.customers;
CREATE TABLE ecommerce.profiles AS
SELECT customer_id AS profile_id, full_name, lifetime_orders * 10 AS loyalty_points FROM ecommerce.customers;
"""


def table_type(entity_id: str, table: str, columns: list[tuple[str, str, str]]) -> OntologyEntity:
    """The type the builder makes of ``table``: its first column is its key, and its profile is what a binding
    over the table borrows."""
    key = columns[0][0]
    return OntologyEntity(id=entity_id, display_name=entity_id, source_tables=[table], identity_key=key,
                          grain_verified=True,
                          properties={c: EntityProperty(name=c, data_type=t, semantic_type=r, is_primary_key=c == key)
                                      for c, t, r in columns})


def built_graph() -> OntologyGraph:
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    text = "VARCHAR"
    g.entities["Client"] = table_type("Client", "clients", [
        ("client_id", text, "key"), ("full_name", text, "dimension"), ("email", text, "dimension"),
        ("city", text, "dimension"), ("country", text, "dimension"), ("tier", text, "dimension")])
    g.entities["Contact"] = table_type("Contact", "contacts", [
        ("contact_id", text, "key"), ("full_name", text, "dimension"), ("email", text, "dimension")])
    g.entities["Profile"] = table_type("Profile", "profiles", [
        ("profile_id", text, "key"), ("full_name", text, "dimension"), ("loyalty_points", "INTEGER", "measure")])
    g.entities["Payment"] = payment_type()
    return g


@pytest.fixture
def door(tmp_path, monkeypatch):
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", built_graph())
    path = tmp_path / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute(SAME_CUSTOMERS)
    con.close()

    def _open(*_a, **_k):
        return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)

    monkeypatch.setattr(C, "open_connection_for_with_schema", _open)
    return _open


def count(door, sql: str) -> int:
    conn = door()
    try:
        return ints(conn, sql)[0]
    finally:
        conn.close()


def overrides() -> dict:
    return {(ov.target_kind, ov.target_id): ov for ov in OV.load_overrides(CONN, "ecommerce")}


def merge(client, merge_ids: list[str], canonical_id: str, **extra):
    return client.post(MERGE, params=PARAMS, json={"merge_ids": merge_ids, "canonical_id": canonical_id, **extra})


def test_a_duplicate_type_is_bound_onto_the_survivor_and_becomes_its_part_with_nothing_deleted(door, client):
    merged = merge(client, ["Customer", "Client"], "Customer")
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert (body["merged_into"], body["absorbed"], body["warnings"]) == ("Customer", ["Client"], [])
    [binding] = body["bindings"]
    assert (binding["name"], binding["kind"], binding["key"], binding["verified"]) == ("clients", "static", "client_id",
                                                                                     True)
    # One row per customer, every one reached; it adds the one column Customer lacks and skips the rest by name.
    assert (binding["covered"], binding["orphans"], binding["supplies"]) == (
        count(door, "SELECT COUNT(*) FROM customers"), 0, 1)
    assert sorted(binding["skipped"]) == ["city", "country", "email", "full_name"]
    assert [(p["id"], p["binding"]) for p in body["parts"]] == [("Client", "clients")]

    shown = client.get("/object-types", params=PARAMS).json()
    by_type = {t["object_type"]: t for t in shown["object_types"]}
    assert by_type["client"]["absorbed_into"] == "customer" and by_type["customer"]["parts"][0]["binding"] == "clients"
    page = client.get("/object-types/client", params=PARAMS).json()
    assert (page["part_of"]["id"], page["part_of"]["holds"]) == ("Customer", True)
    assert {"Customer_RELATES_TO_Order", "Customer_RELATES_TO_Review"} <= {e["relationship"] for e in shown["links"]}

    # The other table's column is read through the binding, on the survivor's key.
    query = {"object_type": "customer", "filters": [{"path": "tier", "value": "gold"}], "measures": [{"agg": "count"}]}
    compiled = client.post("/objects/query", params=PARAMS, json=query).json()
    assert compiled["path"] == "compiled", compiled
    gold = count(door, "SELECT COUNT(*) FROM customers c JOIN clients k ON k.client_id = c.customer_id "
                       "WHERE k.tier = 'gold'")
    assert int(compiled["rows"][0][0]) == gold > 0

    # Written to the overrides tree, so a rebuild — the cache written afresh — keeps it.
    saved = overrides()
    assert saved[("entity", "Client")].fields["absorbed_into"] == "Customer"
    assert (saved[("entity", "Customer")].fields["bindings"]["clients"]["table"],
            saved[("entity", "Customer")].fields["bindings"]["clients"]["key"]) == ("clients", "client_id")
    from aughor.ontology import store as ST
    ST.save_ontology(CONN, "ecommerce", "fp-rebuilt", built_graph())
    rebuilt = {t["object_type"]: t for t in client.get("/object-types", params=PARAMS).json()["object_types"]}
    assert rebuilt["client"]["absorbed_into"] == "customer"


def test_a_cluster_the_data_does_not_hold_is_refused_whole_before_anything_is_written(door, client):
    # Client alone would merge; Contact has no column Customer lacks, so the cluster merges nothing at all.
    whole = merge(client, ["Customer", "Client", "Contact"], "Customer")
    assert whole.status_code == 400
    assert "Contact: it would supply no property" in whole.json()["detail"]
    assert "Client:" not in whole.json()["detail"] and overrides() == {}

    # A payment's own key never meets an order's, however well its rows count.
    by_own_key = merge(client, ["Order", "Payment"], "Order")
    assert by_own_key.status_code == 400 and "its key reaches no Order" in by_own_key.json()["detail"]
    assert overrides() == {}

    # Named by the column that holds an order's key, the same table is one row per order and merges.
    by_order = merge(client, ["Order", "Payment"], "Order", keys={"Payment": "order_id"})
    assert by_order.status_code == 200, by_order.text
    [binding] = by_order.json()["bindings"]
    assert by_order.json()["absorbed"] == ["Payment"]
    assert (binding["key"], binding["covered"], binding["orphans"]) == (
        "order_id", count(door, "SELECT COUNT(*) FROM orders WHERE order_id IN (SELECT order_id FROM payments)"),
        count(door, "SELECT COUNT(DISTINCT order_id) FROM payments WHERE order_id NOT IN (SELECT order_id FROM orders)"))


def test_a_merge_that_would_make_a_part_of_a_part_is_refused(door, client):
    assert merge(client, ["Customer", "Client"], "Customer").status_code == 200
    before = {k: ov.model_dump() for k, ov in overrides().items()}

    into_part = merge(client, ["Client", "Profile"], "Client")
    assert into_part.status_code == 400 and "Client is itself a part of Customer" in into_part.json()["detail"]
    with_parts = merge(client, ["Profile", "Customer"], "Profile")
    assert with_parts.status_code == 400 and "Customer has parts of its own (Client)" in with_parts.json()["detail"]
    assert {k: ov.model_dump() for k, ov in overrides().items()} == before


def test_a_binding_the_survivor_holds_is_never_overwritten_and_a_table_it_binds_is_not_bound_twice(door, client):
    held = client.put("/ontology/entities/Customer/bindings/profiles", params=PARAMS,
                      json={"table": "clients", "key": "client_id"})
    assert held.status_code == 200, held.text

    clash = merge(client, ["Customer", "Profile"], "Customer")
    assert clash.status_code == 400 and "already has a binding named profiles" in clash.json()["detail"]
    assert overrides()[("entity", "Customer")].fields["bindings"]["profiles"]["table"] == "clients"

    again = merge(client, ["Customer", "Client"], "Customer")
    assert again.status_code == 200, again.text
    assert (again.json()["absorbed"], again.json()["bindings"]) == (["Client"], [])
    assert sorted(overrides()[("entity", "Customer")].fields["bindings"]) == ["profiles"]

    # A binding the survivor holds over the table, but that the data refutes, is no ground for a part.
    refuted = client.put("/ontology/entities/Customer/bindings/by_name", params=PARAMS,
                         json={"table": "contacts", "key": "full_name"})
    assert refuted.status_code == 200 and refuted.json()["binding"]["verified"] is False, refuted.text
    trusted = merge(client, ["Customer", "Contact"], "Customer")
    assert trusted.status_code == 400
    assert "binding by_name over contacts is not counted one row per Customer" in trusted.json()["detail"]
    assert "absorbed_into" not in (overrides().get(("entity", "Contact")).fields if ("entity", "Contact") in overrides()
                                   else {})


def test_a_type_merged_into_another_is_no_longer_offered_as_its_duplicate(door, client, monkeypatch):
    import aughor.semantic.embedder as embedder

    types = sorted(built_graph().entities.values(), key=lambda e: e.id)
    slot = {e.id: n for n, e in enumerate(types)}
    slot["Client"] = slot["Customer"]                                   # the two read as one thing
    named = {(e.display_name or e.id): slot[e.id] for e in types}
    monkeypatch.setattr(embedder, "embed", lambda texts: [
        [1.0 if n == named[t.split(" — ")[0]] else 0.0 for n in range(len(types))] for t in texts])

    def suggested() -> list[set[str]]:
        r = client.get("/ontology/duplicate-entities", params=PARAMS)
        assert r.status_code == 200, r.text
        return [{e["id"] for e in c["entities"]} for c in r.json()["clusters"]]

    assert suggested() == [{"Customer", "Client"}]
    assert merge(client, ["Customer", "Client"], "Customer").status_code == 200
    assert suggested() == []
