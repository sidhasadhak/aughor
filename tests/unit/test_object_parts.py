"""ON-7 — the declared entity, its parts and its links (ROADMAP §3.15, the second movement).

Three things the graph could not hold before: a DETAIL binding (many rows per object, no clock — an order's
lines) read at the object's grain only through its declared rollups, each computed inside the object's own
partition before the join; a type marked a PART of another (`absorbed_into`), which holds only while the parent
binds its table; and a type or a link that a person DECLARED rather than the builder found — rebuilt at read
time from what the door recorded, measured like everything else. Every claim is held to a hand-written count or
query over the seeded samples warehouse (plus the three tables `test_object_bindings` adds), and a graph built
before this wave loads with every new field at its default.
"""
from __future__ import annotations

import json

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.bindings import binding_problem, binding_spec, spec_problem
from aughor.ontology.declared import (
    backs_existing_type,
    declared_entity,
    entity_fields,
    entity_spec_problem,
    link_fields,
    link_id,
    link_problem_on_graph,
    link_spec_problem,
    measure_declared_backing,
    measure_declared_link,
)
from aughor.ontology.bindings import describe_with
from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import OntologyOverride, apply_overrides, save_override
from aughor.ontology.parts import absorb_problem, detail_from, lapsed_parts, part_of, parts_of
from aughor.semantic.object_instances import get_object
from aughor.semantic.object_query import link_problem, object_links
from aughor.semantic.object_types import describe_object_type, object_type_map
from aughor.db.connection import open_connection
from tests.unit.test_object_bindings import GRAPH, LUX, bind, compile_, ints, payment_type, refusal, rows, seed

LINES = {"kind": "detail", "table": "order_items", "key": "order_id",
         "rollups": {"units": {"column": "quantity", "agg": "sum"}, "line_count": {"column": "item_id", "agg": "count"},
                     "top_unit_price": {"column": "unit_price", "agg": "max"}}}
PAYMENT = {"id": "Payment", "display_name": "Payment", "description": "one captured or settled payment per order",
           "domain": "Finance", "entity_type": "event", "backing": {"table": "payments", "primary_key": "payment_id"}}
PAYS_FOR = {"from_entity": "Payment", "to_entity": "Order", "name": "pays_for", "from_column": "order_id",
            "to_column": "order_id"}
SCOPE = ("object-parts-t", "ecommerce")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("parts") / "samples.duckdb"
    seed(path)
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="parts-t")
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


# ── nothing built before changes ────────────────────────────────────────────────────────────

def test_a_graph_built_before_the_second_movement_loads_with_every_new_field_at_its_default():
    g = OntologyGraph.model_validate(json.loads(LUX.read_text()))
    assert all(e.origin == "table" and e.absorbed_into is None for e in g.entities.values())
    assert all(b.rollups == {} for e in g.entities.values() for b in e.bindings)
    assert all(r.origin == "join_map" for r in g.relationships.values())
    assert not parts_of(g, g.entities["Order"]) and lapsed_parts(g) == {}


# ── a detail binding: many rows per object, read through its rollups ────────────────────────

def test_a_detail_binding_is_counted_on_reach_and_its_rollups_equal_their_hand_written_references(db, graph):
    order = bind(graph, db, "Order", "lines", LINES)
    [lines] = order.bindings
    (n_orders_with_lines,) = ints(db, "SELECT COUNT(DISTINCT order_id) FROM order_items")
    assert (lines.kind, lines.verified, lines.covered, sorted(lines.properties)) == (
        "detail", True, n_orders_with_lines, ["line_count", "top_unit_price", "units"])
    assert lines.properties["units"].data_type == graph.entities["OrderItem"].properties["quantity"].data_type
    assert lines.properties["units"].is_derived and lines.properties["units"].semantic_type == "measure"
    assert "how many" in lines.properties["line_count"].description and binding_problem(order, lines) == ""

    big = compile_({"object_type": "order", "filters": [{"path": "units", "op": ">", "value": 8}],
                    "measures": [{"agg": "count"}]}, graph)
    (expected,) = ints(db, "SELECT COUNT(*) FROM orders o JOIN (SELECT order_id, SUM(quantity) AS u FROM order_items "
                           "GROUP BY 1) l ON l.order_id = o.order_id WHERE l.u > 8")
    assert big.bindings[0]["treatment"] == "rolled up"
    assert ints(db, big.sql) == [expected]

    total = compile_({"object_type": "order", "measures": [{"agg": "sum", "path": "units"},
                                                           {"agg": "max", "path": "top_unit_price"}]}, graph)
    assert rows(db, total.sql) == rows(db, "SELECT SUM(quantity), MAX(unit_price) FROM order_items")

    page = get_object(graph, db, "order", "O000001")
    read = {p["name"]: p for p in page.properties if p.get("binding")}
    (units, count) = ints(db, "SELECT SUM(quantity), COUNT(item_id) FROM order_items WHERE order_id = 'O000001'")
    assert (int(read["units"]["value"]), int(read["line_count"]["value"])) == (units, count)
    assert read["units"]["binding"]["rollup"] == "the sum of quantity over each object's lines rows"


def test_a_detail_binding_never_multiplies_the_objects_and_its_rows_are_not_a_readings_set(db, graph):
    bind(graph, db, "Order", "lines", LINES)
    counted = compile_({"object_type": "order", "filters": [{"path": "units", "op": ">=", "value": 1}],
                        "measures": [{"agg": "count"}]}, graph)
    assert ints(db, counted.sql) == ints(db, "SELECT COUNT(DISTINCT order_id) FROM order_items")
    why = refusal({"object_type": "order", "measures": [{"agg": "sum", "path": "lines.quantity"}]}, graph).reason
    assert "detail binding" in why and "link" in why


def test_a_detail_spec_is_refused_without_rollups_and_a_static_one_with_them():
    assert "at least one rollup" in spec_problem("lines", {"table": "order_items", "key": "order_id", "kind": "detail"})
    assert "`rollups` roll up a detail" in spec_problem("x", {"table": "t", "key": "k", "rollups": {"n": {"column": "c"}}})
    assert "no time column" in spec_problem("x", {**LINES, "time_column": "ts"})
    assert "instead of `properties`" in spec_problem("x", {**LINES, "properties": {"q": "quantity"}})
    assert "unknown agg" in spec_problem("x", {**LINES, "rollups": {"n": {"column": "quantity", "agg": "median"}}})
    assert spec_problem("lines", LINES) == ""


def test_a_rollup_over_a_column_the_source_lacks_does_not_bind(db, graph):
    from aughor.ontology.bindings import bind_binding
    entry = bind_binding(graph.entities["Order"], "lines", {**LINES, "rollups": {"n": {"column": "nope", "agg": "sum"}}},
                         graph, describe_with(db))
    assert entry["bound"] is False and "reads 'nope'" in entry["note"]
    taken = bind_binding(graph.entities["Order"], "lines", {**LINES, "rollups": {"item_count": {"column": "quantity"}}},
                         graph, describe_with(db))
    assert taken["bound"] is False and "already has the property item_count" in taken["note"]


def test_the_detail_fragment_groups_by_the_key_and_a_rebuilt_binding_round_trips_its_spec(db, graph):
    order = bind(graph, db, "Order", "lines", LINES)
    [lines] = order.bindings
    sql = detail_from(lines, "b")
    assert sql.startswith("(SELECT d.order_id AS order_id, SUM(d.quantity) AS units") and sql.endswith("GROUP BY d.order_id) AS b")
    assert binding_spec(lines) == {"kind": "detail", "key": "order_id", "table": "order_items",
                                   "rollups": {k: {"column": v["column"], "agg": v.get("agg", "sum")}
                                               for k, v in LINES["rollups"].items()}}


def test_the_data_proposes_a_table_with_many_rows_per_object_as_a_part(db, graph):
    from aughor.ontology.backing import apply_backing_measurements
    from aughor.ontology.bindings import propose_bindings
    graph.entities["Payment"] = payment_type()
    apply_backing_measurements(graph, db)
    propose_bindings(graph, db)
    by_name = {p.name: p for p in graph.entities["Order"].proposed_bindings}
    assert by_name["payments"].kind == "static"
    part = by_name["order_items"]
    assert (part.kind, part.verified, sorted(part.rollups)) == ("detail", True, ["order_items_count"])
    assert part.rollups["order_items_count"].agg == "count" and part.rollups["order_items_count"].column == "item_id"
    assert "no property" in refusal({"object_type": "order", "filters": [{"path": "order_items_count", "value": 1}],
                                     "measures": [{"agg": "count"}]}, graph).reason   # a proposal is read by nothing


# ── a part: a type absorbed into another ────────────────────────────────────────────────────

def test_a_type_is_a_part_only_while_its_parent_binds_its_table(db, graph):
    item = graph.entities["OrderItem"]
    assert "has no binding over order_items" in absorb_problem(graph, "Order", item)
    order = bind(graph, db, "Order", "lines", LINES)
    assert absorb_problem(graph, "Order", item) == ""
    item.absorbed_into = "Order"
    assert part_of(graph, item) is order and [(p.id, b.name) for p, b in parts_of(graph, order)] == [("OrderItem", "lines")]

    shown = object_type_map(graph)
    by_type = {t["object_type"]: t for t in shown["object_types"]}
    assert by_type["order_item"]["absorbed_into"] == "order" and by_type["order"]["parts"] == [
        {"object_type": "order_item", "display_name": item.display_name or item.id, "binding": "lines", "kind": "detail"}]
    to_product = next(e for e in shown["links"] if e["relationship"] == "OrderItem_RELATES_TO_Product")
    assert (to_product["from"], to_product["shown_from"], to_product["shown_to"]) == ("order_item", "order", "product")
    described = describe_object_type(graph, "order_item")
    assert described["part_of"] == {"object_type": "order", "id": "Order", "display_name": "Order", "holds": True, "note": ""}
    assert describe_object_type(graph, "order")["counts"]["parts"] == 1

    # the part is still a type: its objects and its link are read by its own name
    lines = compile_({"object_type": "order_item", "measures": [{"agg": "count"}]}, graph)
    assert ints(db, lines.sql) == ints(db, "SELECT COUNT(*) FROM order_items")

    order.bindings = []                                            # the binding is removed: the mark lapses
    assert part_of(graph, item) is None and lapsed_parts(graph) == {"OrderItem": absorb_problem(graph, "Order", item)}
    assert describe_object_type(graph, "order_item")["part_of"]["holds"] is False
    assert object_type_map(graph)["object_types"] and {t["object_type"]: t["absorbed_into"]
                                                       for t in object_type_map(graph)["object_types"]}["order_item"] == ""
    assert "cannot be a part of itself" in absorb_problem(graph, "OrderItem", item)


# ── a declared entity ───────────────────────────────────────────────────────────────────────

def declare_payment(db, graph, spec=PAYMENT) -> OntologyOverride:
    fields = entity_fields(spec)
    entry = measure_declared_backing(db, fields, describe_with(db))
    assert entry["bound"], entry
    ov = OntologyOverride(target_kind="entity", target_id=spec["id"], fields=fields, binding={"backing": entry})
    save_override(*SCOPE, ov)
    return ov


def test_a_declared_entity_is_read_for_its_columns_counted_on_its_key_and_rebuilt_by_the_overlay(db, graph):
    assert entity_spec_problem(PAYMENT) == ""
    assert "PascalCase" in entity_spec_problem({**PAYMENT, "id": "payment"})
    assert "exactly one" in entity_spec_problem({**PAYMENT, "backing": {"primary_key": "payment_id"}})
    assert backs_existing_type(graph, "orders").id == "Order" and backs_existing_type(graph, "payments") is None

    ov = declare_payment(db, graph)
    (n_rows,) = ints(db, "SELECT COUNT(*) FROM payments")
    assert (ov.binding["backing"]["unique"], ov.binding["backing"]["rows"]) == (True, n_rows)
    assert "amount" in ov.binding["backing"]["columns"]

    _, report = apply_overrides(graph, *SCOPE)
    assert "entity:Payment (<declared>,display_name,origin,backing,description,domain,entity_type)" in report.applied
    payment = graph.entities["Payment"]
    assert (payment.origin, payment.entity_type, payment.domain, payment.identity_key) == ("human", "event", "Finance", "payment_id")
    assert payment.backing.verified is True and payment.backing.rows == n_rows and payment.grain_verified
    assert payment.properties["payment_id"].is_primary_key and "DECIMAL" in payment.properties["amount"].data_type.upper()
    assert graph.table_to_entity["payments"] == "Payment" and graph.entity_to_tables["Payment"] == ["payments"]

    again = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    apply_overrides(again, *SCOPE)
    apply_overrides(again, *SCOPE)                                  # twice alike
    assert again.entities["Payment"].model_dump() == payment.model_dump()

    visa = compile_({"object_type": "payment", "filters": [{"path": "psp", "value": "visa"}],
                     "measures": [{"agg": "sum", "path": "amount"}]}, graph)
    assert rows(db, visa.sql) == rows(db, "SELECT SUM(amount) FROM payments WHERE psp = 'visa'")
    assert describe_object_type(graph, "payment")["origin"] == "human"


def test_a_declared_entity_over_a_keyed_select_is_measured_on_that_select(db, graph):
    spec = {"id": "OrderLines", "display_name": "Order lines", "backing": {
        "sql": "SELECT order_id, COUNT(*) AS n, SUM(quantity) AS units FROM order_items GROUP BY 1",
        "primary_key": "order_id"}}
    ov = declare_payment(db, graph, spec)
    assert ov.binding["backing"]["unique"] is True and ov.fields["backing"]["kind"] == "query"
    apply_overrides(graph, *SCOPE)
    lines = graph.entities["OrderLines"]
    assert lines.backing.kind == "query" and lines.source_tables == [] and "units" in lines.properties
    heavy = compile_({"object_type": "order_lines", "filters": [{"path": "units", "op": ">", "value": 8}],
                      "measures": [{"agg": "count"}]}, graph)
    assert ints(db, heavy.sql) == ints(db, "SELECT COUNT(*) FROM (SELECT order_id, SUM(quantity) AS u FROM order_items "
                                           "GROUP BY 1) WHERE u > 8")


def test_a_declaration_whose_source_cannot_be_read_never_reaches_the_graph(db, graph):
    fields = entity_fields({**PAYMENT, "backing": {"table": "no_such_table", "primary_key": "id"}})
    entry = measure_declared_backing(db, fields, describe_with(db))
    assert entry["bound"] is False and "could not be read" in entry["note"]
    ov = OntologyOverride(target_kind="entity", target_id="Payment", fields=fields, binding={"backing": entry})
    assert declared_entity(ov, graph) is None
    save_override(*SCOPE, ov)
    _, report = apply_overrides(graph, *SCOPE)
    assert "Payment" not in graph.entities and any("entity:Payment" in s for s in report.skipped)
    missing_key = measure_declared_backing(db, entity_fields({**PAYMENT, "backing": {"table": "payments", "primary_key": "nope"}}),
                                           describe_with(db))
    assert missing_key["bound"] is False and "no column 'nope'" in missing_key["note"]


# ── a declared link ─────────────────────────────────────────────────────────────────────────

def declare_link(db, graph, spec=PAYS_FOR) -> OntologyOverride:
    fields = link_fields(spec)
    assert link_problem_on_graph(graph, fields) == "", link_problem_on_graph(graph, fields)
    entry = measure_declared_link(db, graph, fields)
    assert entry["bound"], entry
    ov = OntologyOverride(target_kind="link", target_id=link_id(fields), fields=fields, binding={"link": entry})
    save_override(*SCOPE, ov)
    return ov


def test_a_declared_link_is_measured_on_both_sides_and_traversed_by_the_compiler(db, graph):
    assert link_spec_problem(PAYS_FOR) == "" and "snake_case" in link_spec_problem({**PAYS_FOR, "name": "Pays For"})
    declare_payment(db, graph)
    apply_overrides(graph, *SCOPE)
    ov = declare_link(db, graph)
    (orphans,) = ints(db, "SELECT COUNT(DISTINCT order_id) FROM payments WHERE order_id NOT IN (SELECT order_id FROM orders)")
    (keyed,) = ints(db, "SELECT COUNT(DISTINCT order_id) FROM payments")
    entry = ov.binding["link"]
    assert (entry["measured_cardinality"], entry["value_overlap"]) == ("1:1", round((keyed - orphans) / keyed, 4))

    fresh = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    _, report = apply_overrides(fresh, *SCOPE)
    assert "link:Payment_pays_for_Order (<declared>,name)" in report.applied
    rel = fresh.relationships["Payment_pays_for_Order"]
    assert (rel.origin, rel.measured_cardinality, rel.join_confidence, rel.api_name, rel.reverse_api_name) == (
        "human", "1:1", "verified", "pays_for", "order_to_payment")
    assert fresh.relationship_index["Payment"] == ["Order"] and "Payment" in fresh.relationship_index["Order"]
    hop = next(h for h in object_links(fresh, fresh.entities["Payment"]) if h.name == "pays_for")
    assert link_problem(hop) == "" and hop.to_one

    delivered = compile_({"object_type": "payment", "filters": [{"path": "pays_for.status", "value": "delivered"}],
                          "measures": [{"agg": "sum", "path": "amount"}]}, fresh)
    assert rows(db, delivered.sql) == rows(db, "SELECT SUM(amount) FROM payments p JOIN orders o ON o.order_id = p.order_id "
                                               "WHERE o.status = 'delivered'")
    back = compile_({"object_type": "order", "filters": [{"path": "order_to_payment.psp", "value": "visa"}],
                     "measures": [{"agg": "count"}]}, fresh)
    assert ints(db, back.sql) == ints(db, "SELECT COUNT(*) FROM orders o JOIN payments p ON p.order_id = o.order_id "
                                          "WHERE p.psp = 'visa'")
    shown = describe_object_type(fresh, "payment")
    link = next(l for l in shown["links"] if l["relationship"] == "Payment_pays_for_Order")
    assert (link["business_name"], link["cardinality"], link["traversable"]) == ("pays_for", "1:1", True)


def test_a_declared_link_whose_keys_never_meet_is_stored_with_its_measurement_and_refused_by_the_compiler(db, graph):
    declare_payment(db, graph)
    apply_overrides(graph, *SCOPE)
    # payments.psp holds 'visa' and the like; no order_id ever equals one — the columns are wrong, the data says so
    ov = declare_link(db, graph, {**PAYS_FOR, "name": "settles", "from_column": "psp", "to_column": "order_id"})
    assert ov.binding["link"]["value_overlap"] == 0.0 and ov.binding["link"]["bound"] is True
    fresh = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    apply_overrides(fresh, *SCOPE)
    rel = fresh.relationships["Payment_settles_Order"]
    assert rel.join_confidence == "inferred" and rel.value_overlap == 0.0
    hop = next(h for h in object_links(fresh, fresh.entities["Payment"]) if h.name == "settles")
    assert "keys never meet" in link_problem(hop)
    why = refusal({"object_type": "payment", "filters": [{"path": "settles.status", "value": "delivered"}],
                   "measures": [{"agg": "count"}]}, fresh).reason
    assert "keys never meet" in why
    shown = next(l for l in describe_object_type(fresh, "payment")["links"] if l["relationship"] == "Payment_settles_Order")
    assert shown["traversable"] is False and "never meet" in shown["why_not"]


def test_a_declared_link_is_refused_where_it_cannot_land(db, graph):
    declare_payment(db, graph)
    apply_overrides(graph, *SCOPE)
    assert "no object type 'Invoice'" in link_problem_on_graph(graph, link_fields({**PAYS_FOR, "to_entity": "Invoice"}))
    assert "has no property 'nope'" in link_problem_on_graph(graph, link_fields({**PAYS_FOR, "from_column": "nope"}))
    found = link_fields({"from_entity": "OrderItem", "to_entity": "Order", "name": "belongs_to",
                         "from_column": "order_id", "to_column": "order_id"})
    assert "already joins" in link_problem_on_graph(graph, found) and "PUT /ontology/links/OrderItem_RELATES_TO_Order" in link_problem_on_graph(graph, found)
    assert "already has the property status" in link_problem_on_graph(graph, link_fields({**PAYS_FOR, "name": "status"}))
    assert "reverse name" in link_problem_on_graph(graph, link_fields({**PAYS_FOR, "reverse_name": "customer_id"}))


def test_a_declared_link_whose_type_is_withdrawn_stops_applying(db, graph):
    declare_payment(db, graph)
    apply_overrides(graph, *SCOPE)
    declare_link(db, graph)
    OV.delete_override(*SCOPE, "entity", "Payment")
    fresh = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    _, report = apply_overrides(fresh, *SCOPE)
    assert "Payment_pays_for_Order" not in fresh.relationships
    assert any(s.startswith("link:Payment_pays_for_Order") for s in report.skipped)


# ── the doors ───────────────────────────────────────────────────────────────────────────────

CONN = "object-parts-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def door(tmp_path, monkeypatch):
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", OntologyGraph.model_validate(json.loads(GRAPH.read_text())))
    path = tmp_path / "samples.duckdb"
    seed(path)

    def _open(*_a, **_k):
        return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)

    monkeypatch.setattr(C, "open_connection_for_with_schema", _open)
    return _open


def test_an_entity_a_link_and_a_part_are_declared_read_back_and_withdrawn_over_http(door, client):
    declared = client.post("/ontology/entities", params=PARAMS, json=PAYMENT)
    assert declared.status_code == 200, declared.text
    body = declared.json()
    assert (body["entity"]["origin"], body["entity"]["key"]["verified"]) == ("human", True)
    assert client.post("/ontology/entities", params=PARAMS, json=PAYMENT).status_code == 409
    doubled = client.post("/ontology/entities", params=PARAMS,
                          json={**PAYMENT, "id": "Orders", "backing": {"table": "orders", "primary_key": "order_id"}})
    assert doubled.status_code == 400 and "already backs Order" in doubled.json()["detail"]
    assert client.post("/ontology/entities", params=PARAMS, json={**PAYMENT, "id": "bad id"}).status_code == 400

    linked = client.post("/ontology/links", params=PARAMS, json=PAYS_FOR)
    assert linked.status_code == 200, linked.text
    assert (linked.json()["relationship"], linked.json()["link"]["traversable"], linked.json()["link"]["cardinality"]) == (
        "Payment_pays_for_Order", True, "1:1")
    assert client.post("/ontology/links", params=PARAMS, json=PAYS_FOR).status_code == 409
    assert client.post("/ontology/links", params=PARAMS, json={**PAYS_FOR, "name": "settles", "from_column": "nope"}).status_code == 400

    bound = client.put("/ontology/entities/Order/bindings/lines", params=PARAMS, json={**LINES, "absorb": True})
    assert bound.status_code == 200, bound.text
    assert (bound.json()["absorbed"], bound.json()["binding"]["verified"], bound.json()["binding"]["kind"]) == (
        "OrderItem", True, "detail")
    assert bound.json()["parts"][0]["object_type"] == "order_item"
    assert bound.json()["binding"]["rollups"]["units"] == "the sum of quantity over each object's lines rows"

    shown = client.get("/object-types", params=PARAMS).json()
    by_type = {t["object_type"]: t for t in shown["object_types"]}
    assert by_type["order_item"]["absorbed_into"] == "order" and by_type["payment"]["origin"] == "human"
    assert by_type["order"]["parts"][0]["binding"] == "lines"
    edge = next(e for e in shown["links"] if e["relationship"] == "OrderItem_RELATES_TO_Product")
    assert edge["shown_from"] == "order"
    assert next(e for e in shown["links"] if e["relationship"] == "Payment_pays_for_Order")["origin"] == "human"

    query = {"object_type": "order", "filters": [{"path": "units", "op": ">", "value": 8}], "measures": [{"agg": "count"}]}
    compiled = client.post("/objects/query", params=PARAMS, json=query).json()
    assert compiled["path"] == "compiled", compiled
    conn = door()
    try:
        (expected,) = ints(conn, "SELECT COUNT(*) FROM orders o JOIN (SELECT order_id, SUM(quantity) AS u FROM order_items "
                                 "GROUP BY 1) l ON l.order_id = o.order_id WHERE l.u > 8")
    finally:
        conn.close()
    assert int(compiled["rows"][0][0]) == expected and compiled["bindings"][0]["treatment"] == "rolled up"

    measured = client.post("/ontology/measure", params=PARAMS).json()
    assert measured["declared_links"][0]["link"] == "Payment_pays_for_Order"
    assert "Order.lines" in measured["bindings"]["verified"]

    released = client.put("/ontology/entities/OrderItem", params=PARAMS, json={"absorbed_into": ""})
    assert released.status_code == 200
    assert client.get("/object-types/order_item", params=PARAMS).json()["part_of"] is None
    re_marked = client.put("/ontology/entities/OrderItem", params=PARAMS, json={"absorbed_into": "Order"})
    assert re_marked.status_code == 200 and re_marked.json()["verified"] is True
    unheld = client.put("/ontology/entities/Review", params=PARAMS, json={"absorbed_into": "Order"})
    assert unheld.status_code == 200 and unheld.json()["verified"] is False and "no binding over reviews" in unheld.json()["warnings"][0]

    assert client.delete("/ontology/entities/Order/bindings/lines", params=PARAMS).status_code == 200
    assert client.get("/object-types/order_item", params=PARAMS).json()["part_of"]["holds"] is False   # lapsed, said so

    assert client.delete("/ontology/links/Payment_pays_for_Order", params=PARAMS).status_code == 200
    assert client.delete("/ontology/links/Payment_pays_for_Order", params=PARAMS).status_code == 404
    assert client.delete("/ontology/links/OrderItem_RELATES_TO_Order", params=PARAMS).status_code == 404
    assert client.delete("/ontology/entities/Payment", params=PARAMS).status_code == 200
    kept = client.delete("/ontology/entities/Order", params=PARAMS)
    assert kept.status_code == 404 and "built from its table" in kept.json()["detail"]
    assert "payment" not in {t["object_type"] for t in client.get("/object-types", params=PARAMS).json()["object_types"]}
