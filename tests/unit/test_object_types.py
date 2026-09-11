"""ON-3b / ON-3c — an object type as one connected slice, and how one type reaches another.

Every fact the slice states is held to its authority: the key's uniqueness and rows to a count over the
seeded samples warehouse; a link's traversability to ON-2's own compiler — a link or path the slice calls
followed must compile, and a refused one must be refused with the very sentence the slice shows; and a
business-verb name to the compiler and the instance reader resolving it exactly as the mechanical name.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.backing import apply_backing_measurements
from aughor.ontology.models import OntologyGraph
from aughor.semantic.object_instances import list_linked
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
from aughor.semantic.object_types import describe_object_type, find_paths, link_name_problem, object_type_map

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="object-types-t")
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _one(db, sql):
    """A row of counts — the connection hands cells back as text."""
    return [int(v) for v in db.execute("reference", sql).rows[0]]


# ── the slice ─────────────────────────────────────────────────────────────────────────────

def test_a_type_states_its_key_its_rows_and_every_property_with_its_source(db, graph):
    apply_backing_measurements(graph, db)
    customer = describe_object_type(graph, "customer")
    (rows,) = _one(db, "SELECT COUNT(*) FROM customers")
    assert (customer["key"]["property"], customer["key"]["verified"], customer["key"]["rows"]) == ("customer_id", True, rows)
    table = graph.entities["Customer"].backing.table
    [binding] = customer["bindings"]                                # no further binding: the backing is the one
    assert (binding["primary"], binding["kind"], binding["reads"], binding["table"], binding["key"], binding["rows"],
            binding["supplies"]) == (True, "static", "table", table, "customer_id", rows,
                                     len(graph.entities["Customer"].properties))
    props = {p["name"]: p for p in customer["properties"]}
    assert set(props) == set(graph.entities["Customer"].properties)
    assert all(p["source"] == {"binding": binding["name"], "table": table, "column": name} for name, p in props.items())
    columns = {str(r[0]) for r in db.execute(
        "reference", "SELECT column_name FROM information_schema.columns WHERE table_name = 'customers'").rows}
    assert set(props) <= columns                                    # every source names a column the binding has
    assert props["customer_id"]["is_key"] and not props["full_name"]["is_key"]
    assert (customer["display_property"]["property"], customer["display_property"]["source"]) == ("full_name", "proposed")
    name = graph.entities["Customer"].display_name
    assert customer["summary"].startswith(
        f"{name} (customer): key customer_id — unique per object, measured over {rows:,} rows; named by full_name; "
        f"{len(props)} properties read from {table}; 2 links, 2 followed by the compiler")


def test_each_link_is_marked_the_way_the_compiler_treats_it(graph):
    item = describe_object_type(graph, "order_item")
    links = {link["name"]: link for link in item["links"]}
    assert links["order_item_to_review"]["traversable"] is False and "N:N" in links["order_item_to_review"]["why_not"]
    assert (links["order_item_to_order"]["kind"], links["order_item_to_order"]["cardinality"]) == ("to-one", "N:1")
    assert item["counts"]["traversable_links"] == sum(1 for link in links.values() if link["traversable"])
    for name, link in links.items():
        query = {"object_type": "order_item", "filters": [{"path": name, "op": "exists"}], "measures": [{"agg": "count"}]}
        if link["traversable"]:
            compile_object_query(query, graph)
        else:
            with pytest.raises(ObjectQueryRefused) as refused:
                compile_object_query(query, graph)
            assert refused.value.reason == link["why_not"]


def test_a_link_answers_to_its_business_verb_name_beside_its_mechanical_one(db, graph):
    customer = describe_object_type(graph, "customer")
    assert {link["name"]: (link["business_name"], link["business_name_source"]) for link in customer["links"]} == {
        "customer_to_order": ("customer_places_order", "proposed"),
        "customer_to_review": ("customer_writes_review", "proposed")}
    by_verb = compile_object_query({"object_type": "customer", "by": ["country"],
                                    "measures": [{"name": "orders", "agg": "count", "path": "customer_places_order"}]},
                                   graph)
    by_name = compile_object_query({"object_type": "customer", "by": ["country"],
                                    "measures": [{"name": "orders", "agg": "count", "path": "customer_to_order"}]}, graph)
    assert by_verb.sql == by_name.sql
    assert list_linked(graph, db, "customer", "C00042", "customer_places_order", limit=5)["link"] == "customer_to_order"

    graph.relationships["Customer_RELATES_TO_Order"].name = "customer_buys"      # a person names it
    order_link = next(link for link in describe_object_type(graph, "order")["links"] if link["to"] == "customer")
    assert (order_link["name"], order_link["business_name"], order_link["business_name_source"]) == (
        "order_to_customer", "customer_buys", "human")
    compile_object_query({"object_type": "order", "by": ["customer_buys.country"], "measures": [{"agg": "count"}]}, graph)
    with pytest.raises(ObjectQueryRefused):                                      # the proposal it replaced is gone
        compile_object_query({"object_type": "order", "by": ["customer_places_order.country"],
                              "measures": [{"agg": "count"}]}, graph)


def test_the_declared_actions_that_take_a_type_are_listed_with_their_object_parameters(graph, tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    OV.save_override("samples", "ecommerce", OV.OntologyOverride(target_kind="action", target_id="flag_order", fields={
        "kind": "annotate", "risk": "low", "object_type": "Order",
        "params": [{"name": "order", "kind": "object", "object_type": "Order"}, {"name": "reason"}],
        "edits": [{"object": "order", "property": "review_flag", "value": "true", "note": "{reason}"}]}))
    OV.apply_overrides(graph, "samples", "ecommerce")
    [action] = describe_object_type(graph, "order")["actions"]
    assert (action["id"], action["why"], action["kind"], action["risk"]) == ("flag_order", "takes order (Order)", "annotate", "low")
    assert action["params"][0] == {"name": "order", "kind": "object", "object_type": "Order",
                                   "data_type": "VARCHAR", "required": True}
    assert action["edits"] == [{"object": "order", "property": "review_flag"}]
    assert describe_object_type(graph, "customer")["actions"] == []


def test_verified_metrics_are_listed_and_unverified_ones_named_not_dropped(graph):
    order = describe_object_type(graph, "order")
    assert [m["id"] for m in order["metrics"]] == ["aov", "revenue"] and order["unverified_metrics"] == []
    graph.metrics["aov"].verified = False
    order = describe_object_type(graph, "order")
    assert [m["id"] for m in order["metrics"]] == ["revenue"] and order["unverified_metrics"] == ["aov"]


# ── the map ───────────────────────────────────────────────────────────────────────────────

def test_the_map_lists_every_type_with_its_facts_and_every_link_once(graph):
    m = object_type_map(graph)
    assert {t["object_type"] for t in m["object_types"]} == {"customer", "order", "order_item", "product", "review"}
    assert sorted(link["relationship"] for link in m["links"]) == sorted(graph.relationships)
    review = next(link for link in m["links"] if link["relationship"] == "OrderItem_RELATES_TO_Review")
    assert (review["traversable"], review["verb"], review["from"], review["to"]) == (
        False, "associated with", "order_item", "review")
    assert "N:N" in review["why_not"]
    order = next(t for t in m["object_types"] if t["object_type"] == "order")
    assert (order["metrics"], order["links"], order["display_property"], order["display_is_key"]) == (2, 2, "order_id", True)


# ── paths ─────────────────────────────────────────────────────────────────────────────────

def test_paths_from_customer_to_product_mark_every_hop_and_agree_with_the_compiler(graph):
    found = find_paths(graph, "customer", "product")
    assert found["found"] == 2 and [p["length"] for p in found["paths"]] == [3, 3]
    followed, refused = found["paths"]
    assert [(h["link"], h["cardinality"], h["traversable"]) for h in followed["hops"]] == [
        ("customer_to_order", "1:N", True), ("order_to_order_item", "1:N", True), ("order_item_to_product", "N:1", True)]
    assert (followed["traversable"], followed["reach"], followed["compiles_as"]) == (True, "to-many", ["filter"])
    assert refused["traversable"] is False and refused["hops"][1]["traversable"] is False
    assert refused["why_not"].startswith("hop 2 (review_to_order_item) is refused") and "N:N" in refused["why_not"]
    for path in found["paths"]:
        query = {"object_type": "customer", "filters": [{"path": f"{path['path']}.category", "value": "shoes"}],
                 "measures": [{"agg": "count"}]}
        if path["compiles_as"]:
            compile_object_query(query, graph)
        else:
            with pytest.raises(ObjectQueryRefused):
                compile_object_query(query, graph)


def test_a_to_one_path_compiles_as_a_dimension_and_a_path_past_the_hop_limit_says_so(graph):
    first = find_paths(graph, "order", "customer")["paths"][0]
    assert (first["length"], first["reach"], first["compiles_as"]) == (1, "to-one", ["filter", "dimension"])
    compile_object_query({"object_type": "order", "by": [f"{first['path']}.country"], "measures": [{"agg": "count"}]},
                         graph)
    long_way = find_paths(graph, "product", "review", max_hops=4)["paths"][0]
    assert (long_way["length"], long_way["traversable"], long_way["compiles_as"]) == (4, True, [])
    assert "at most 3 links" in long_way["why_not"]
    with pytest.raises(ObjectQueryRefused):
        compile_object_query({"object_type": "product", "filters": [{"path": f"{long_way['path']}.rating", "value": 5}],
                              "measures": [{"agg": "count"}]}, graph)


def test_a_path_needs_two_known_types(graph):
    with pytest.raises(ObjectQueryRefused):
        find_paths(graph, "order", "order")
    with pytest.raises(ObjectQueryRefused) as refused:
        find_paths(graph, "order", "invoice")
    assert "customer" in refused.value.available


def test_a_link_name_must_be_snake_case_and_name_nothing_else_on_either_type(graph):
    rel = "Customer_RELATES_TO_Order"
    assert link_name_problem(graph, rel, "customer_buys") == ""
    assert "snake_case" in link_name_problem(graph, rel, "Customer Buys")
    assert "already has a link named 'customer_writes_review'" in link_name_problem(graph, rel, "customer_writes_review")
    assert "has a property named 'country'" in link_name_problem(graph, rel, "country")
    assert "no link" in link_name_problem(graph, "Nope", "customer_buys")
