"""ON-9 — processes, promises and rules: declared, measured through the object door, derived by construction.

A process is a type's stages in order, each anchored to a moment or a state; a promise says when a stage must be
reached — within N calendar days of the previous one, or by a per-object deadline kept per object of the type that
carries it; a rule names a value set or a condition. Every claim here is held to a hand-written query over the seeded
samples warehouse, which gains one column for the purpose: `order_items.ship_by`, a per-line shipping deadline 2–5
days after the order (NULL on every fiftieth line). What a promise derives — the late segment, the breach rate, the
lag — compiles through the object door and equals its reference; a derived name is refused until its declaration is
measured; a promise never or always broken is flagged rather than trusted; and a graph built before this wave loads
with no processes and no rules.
"""
from __future__ import annotations

import copy
import json
from collections import Counter

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology import overrides as OV
from aughor.ontology.business_rules import (
    declared_rule,
    measure_rule,
    resolve_rule,
    rule_entry,
    rule_fields,
    rule_spec_problem,
)
from aughor.ontology.derived import derived_for, find_derived_metric
from aughor.ontology.models import EntityProperty, OntologyGraph
from aughor.ontology.overrides import OntologyOverride, apply_overrides, save_override
from aughor.ontology.processes import (
    declared_process,
    describe_process,
    measure_process,
    process_entry,
    process_fields,
    process_from_fields,
    process_spec_problem,
    quantile_cont,
    resolve_process,
)
from tests.unit.test_object_bindings import GRAPH, LUX, compile_, ints, refusal, rows, seed

_DEADLINES = """
CREATE TABLE ecommerce.order_items_with_deadline AS
SELECT i.*, CASE WHEN i.item_id % 50 = 0 THEN NULL ELSE o.order_date + CAST(2 + i.item_id % 4 AS INTEGER) END AS ship_by
FROM ecommerce.order_items i JOIN ecommerce.orders o ON o.order_id = i.order_id;
DROP TABLE ecommerce.order_items;
ALTER TABLE ecommerce.order_items_with_deadline RENAME TO order_items;
"""

FULFILMENT = {
    "id": "order_fulfilment", "display_name": "Order fulfilment", "entity": "Order", "owner": "operations",
    "stages": [
        {"name": "placed", "timestamp": "order_date"},
        {"name": "shipped", "timestamp": "shipped_at",
         "promise": {"name": "shipping", "deadline": "ship_by", "grain": "OrderItem"}},
        {"name": "delivered", "timestamp": "delivered_at",
         "promise": {"name": "delivery", "within_days": 5, "target": 0.8}},
    ],
}
SCOPE = ("object-processes-t", "ecommerce")
LINE_JOIN = "FROM ecommerce.order_items i LEFT JOIN ecommerce.orders o ON o.order_id = i.order_id"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("processes") / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute(_DEADLINES)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="processes-t")
    yield conn
    conn.close()


def fresh_graph() -> OntologyGraph:
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    g.entities["OrderItem"].properties["ship_by"] = EntityProperty(name="ship_by", data_type="DATE",
                                                                  semantic_type="timestamp", null_rate=0.02)
    return g


@pytest.fixture
def graph():
    return fresh_graph()


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def declare(graph: OntologyGraph, db, spec: dict):
    """The door's path without HTTP: shape, resolution against the graph, the count, then onto the graph."""
    assert process_spec_problem(spec) == ""
    problem, fields = resolve_process(graph, spec["id"], process_fields(spec))
    assert problem == "", problem
    measured = measure_process(db, graph, spec["id"], fields)
    graph.processes[spec["id"]] = measured
    return fields, measured


def run(db, query: dict, graph: OntologyGraph) -> list[tuple]:
    return rows(db, compile_(query, graph).sql)


# ── nothing built before changes ────────────────────────────────────────────────────────────

def test_a_graph_built_before_processes_loads_with_none_and_no_derived_name():
    g = OntologyGraph.model_validate(json.loads(LUX.read_text()))
    assert g.processes == {} and g.rules == {}
    assert all(not derived_for(g, e).segments and not derived_for(g, e).properties for e in g.entities.values())


# ── a process: its stages and transitions, counted ──────────────────────────────────────────

def test_each_stage_and_transition_is_counted_and_equals_its_hand_written_reference(db, graph):
    _, p = declare(graph, db, FULFILMENT)
    objects, placed, shipped, delivered = ints(
        db, "SELECT COUNT(*), COUNT(order_date), COUNT(shipped_at), COUNT(delivered_at) FROM ecommerce.orders")
    assert p.objects == objects and [s.reached for s in p.stages] == [placed, shipped, delivered]
    both, skipped, early = ints(db, "SELECT COUNT(*) FILTER (WHERE order_date IS NOT NULL AND shipped_at IS NOT NULL), "
                                    "COUNT(*) FILTER (WHERE shipped_at IS NOT NULL AND order_date IS NULL), "
                                    "COUNT(*) FILTER (WHERE shipped_at < order_date) FROM ecommerce.orders")
    shipped_stage = p.stages[1]
    assert (shipped_stage.both, shipped_stage.skipped, shipped_stage.out_of_order) == (both, skipped, early)
    lag = "date_diff('day', order_date, shipped_at)"
    [reference] = rows(db, f"SELECT quantile_cont({lag}, 0.5), quantile_cont({lag}, 0.9), quantile_cont({lag}, 0.95) "
                           "FROM ecommerce.orders WHERE order_date IS NOT NULL AND shipped_at IS NOT NULL")
    assert tuple(round(v, 4) for v in (shipped_stage.p50_days, shipped_stage.p90_days, shipped_stage.p95_days)) == reference
    assert p.stages[0].both is None and p.stages[0].p50_days is None           # the first stage has no transition
    assert p.verified is True and all(s.verified for s in p.stages) and p.measured_at


def test_a_deadline_promise_is_kept_per_line_through_the_measured_link_and_equals_its_reference(db, graph):
    _, p = declare(graph, db, FULFILMENT)
    promise = p.stages[1].promise
    assert (promise.grain, promise.via) == ("OrderItem", "order_item_to_order")
    lines, reached, breached, still_open = ints(db, (
        "SELECT COUNT(*), COUNT(*) FILTER (WHERE o.shipped_at IS NOT NULL AND i.ship_by IS NOT NULL), "
        "COUNT(*) FILTER (WHERE o.shipped_at > i.ship_by), "
        f"COUNT(*) FILTER (WHERE o.shipped_at IS NULL AND i.ship_by IS NOT NULL) {LINE_JOIN}"))
    assert (promise.objects, promise.reached, promise.breached, promise.open, promise.kept) == (
        lines, reached, breached, still_open, reached - breached)
    assert 0 < breached < reached and promise.flags == [] and promise.verified is True
    assert promise.breach_rate == round(breached / reached, 6)
    [(as_of,)] = rows(db, f"SELECT MAX(o.shipped_at) {LINE_JOIN}")
    assert promise.as_of[:10] == str(as_of)[:10]
    (overdue,) = ints(db, f"SELECT COUNT(*) {LINE_JOIN} WHERE o.shipped_at IS NULL AND i.ship_by IS NOT NULL "
                          f"AND i.ship_by < DATE '{promise.as_of[:10]}'")
    assert promise.open_overdue == overdue and overdue > 0


def test_a_promise_within_days_counts_calendar_days_from_the_previous_stage(db, graph):
    _, p = declare(graph, db, FULFILMENT)
    promise = p.stages[2].promise
    reached, breached, still_open = ints(db, (
        "SELECT COUNT(*) FILTER (WHERE shipped_at IS NOT NULL AND delivered_at IS NOT NULL), "
        "COUNT(*) FILTER (WHERE date_diff('day', shipped_at, delivered_at) > 5), "
        "COUNT(*) FILTER (WHERE shipped_at IS NOT NULL AND delivered_at IS NULL) FROM ecommerce.orders"))
    assert (promise.reached, promise.breached, promise.open) == (reached, breached, still_open)
    assert 0 < breached < reached
    (overdue,) = ints(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE shipped_at IS NOT NULL AND delivered_at IS NULL "
                          f"AND date_diff('day', shipped_at, DATE '{promise.as_of[:10]}') > 5")
    assert promise.open_overdue == overdue


# ── what a promise derives, compiled ────────────────────────────────────────────────────────

def test_what_a_promise_derives_compiles_through_the_object_door_and_equals_its_reference(db, graph):
    _, p = declare(graph, db, FULFILMENT)
    shipping, delivery = p.stages[1].promise, p.stages[2].promise
    assert run(db, {"object_type": "order_item", "segment": "late_shipping", "measures": [{"agg": "count"}]},
               graph) == [(shipping.breached,)]
    assert run(db, {"object_type": "order_item", "measures": [{"metric": "shipping_breach_rate"}]},
               graph) == [(round(shipping.breached / shipping.reached, 4),)]
    by_category = run(db, {"object_type": "order_item", "segment": "late_shipping",
                           "by": ["order_item_to_product.category"], "measures": [{"agg": "count"}]}, graph)
    assert by_category == rows(db, "SELECT p.category, COUNT(*) FROM ecommerce.order_items i "
                                   "JOIN ecommerce.orders o ON o.order_id = i.order_id "
                                   "JOIN ecommerce.products p ON p.product_id = i.product_id "
                                   "WHERE o.shipped_at > i.ship_by GROUP BY 1")
    assert run(db, {"object_type": "order", "measures": [{"agg": "avg", "path": "delivery_lag_days"}]}, graph) == rows(
        db, "SELECT AVG(date_diff('day', shipped_at, delivered_at)) FROM ecommerce.orders")
    assert run(db, {"object_type": "order", "segment": "late_delivery", "measures": [{"agg": "count"}]},
               graph) == [(delivery.breached,)]
    assert run(db, {"object_type": "order", "filters": [{"path": "shipping_lag_days", "op": ">", "value": 4}],
                    "measures": [{"agg": "count"}]}, graph) == rows(
        db, "SELECT COUNT(*) FROM ecommerce.orders WHERE date_diff('day', order_date, shipped_at) > 4")
    assert find_derived_metric(graph, graph.entities["Order"], "delivery_breach_rate").target_value == 0.2
    plan = compile_({"object_type": "order_item", "segment": "late_shipping", "measures": [{"agg": "count"}]}, graph).plan
    assert any("derived from the shipping promise of process order_fulfilment" in line for line in plan)


def test_a_derived_name_is_refused_until_its_declaration_is_measured(graph):
    problem, fields = resolve_process(graph, "order_fulfilment", process_fields(FULFILMENT))
    assert problem == ""
    graph.processes["order_fulfilment"] = process_from_fields("order_fulfilment", fields)    # declared, never counted
    for query in ({"object_type": "order_item", "segment": "late_shipping", "measures": [{"agg": "count"}]},
                  {"object_type": "order_item", "measures": [{"metric": "shipping_breach_rate"}]},
                  {"object_type": "order", "measures": [{"agg": "avg", "path": "delivery_lag_days"}]}):
        assert "has not been measured" in refusal(query, graph).reason


def test_a_stage_no_object_reaches_is_measured_false_and_its_lag_is_refused(db, graph):
    spec = {"id": "lost_parcels", "entity": "Order", "stages": [
        {"name": "placed", "timestamp": "order_date"}, {"name": "lost", "state": ["lost_in_transit"]}]}
    _, p = declare(graph, db, spec)
    assert (p.stages[1].reached, p.stages[1].verified, p.verified) == (0, False, False)
    assert "no Order object is in lost_in_transit" in p.stages[1].note
    _, fulfilment = declare(graph, db, FULFILMENT)
    fulfilment.stages[2].verified = False                                    # as if no order were ever delivered
    fulfilment.stages[2].note = "no Order object reaches delivered"
    assert "no object reaches stage delivered" in refusal(
        {"object_type": "order", "measures": [{"agg": "avg", "path": "delivery_lag_days"}]}, graph).reason


def test_a_promise_never_or_always_broken_is_flagged_rather_than_trusted(db, graph):
    spec = {"id": "suspicious", "entity": "Order", "stages": [
        {"name": "placed", "timestamp": "order_date"},
        {"name": "shipped", "timestamp": "shipped_at", "promise": {"name": "before_delivery", "deadline": "delivered_at"}},
        {"name": "delivered", "timestamp": "delivered_at", "promise": {"name": "after_order", "deadline": "order_date"}}]}
    _, p = declare(graph, db, spec)
    never, always = p.stages[1].promise, p.stages[2].promise
    assert never.verified is True and never.breached == 0 and never.flags[0].startswith("never broken")
    assert always.verified is True and always.breached == always.reached and always.flags[0].startswith("always broken")
    compiled = compile_({"object_type": "order", "measures": [{"metric": "after_order_breach_rate"}]}, graph)
    assert any("always broken" in c for c in compiled.caveats)


# ── the declaration's shape and its resolution ──────────────────────────────────────────────

@pytest.mark.parametrize("change, fragment", [
    (lambda s: [s["stages"].pop(), s["stages"].pop()], "from 2 to"),
    (lambda s: s["stages"][0].update(state=["pending"]), "exactly one of `timestamp`"),
    (lambda s: s["stages"][1].update(name="Shipped"), "snake_case"),
    (lambda s: s["stages"][2].update(name="shipped"), "named twice"),
    (lambda s: s["stages"][0].update(promise={"target": 0.9}), "exactly one of `within_days`"),
    (lambda s: s["stages"][1]["promise"].update(within_days=2), "exactly one of `within_days`"),
    (lambda s: s["stages"][2]["promise"].update(target=1.5), "`target`"),
    (lambda s: s["stages"][1]["promise"].pop("grain") and s["stages"][1]["promise"].update(via="order_item_to_order"),
     "needs a `grain`"),
    (lambda s: s["stages"][2]["promise"].update(name="shipping"), "derive names from 'shipping'"),
])
def test_a_declaration_whose_shape_is_wrong_is_refused_with_the_reason(change, fragment):
    spec = copy.deepcopy(FULFILMENT)
    change(spec)
    assert fragment in process_spec_problem(spec)


def test_a_within_days_promise_on_the_first_stage_or_after_a_state_is_refused():
    first = copy.deepcopy(FULFILMENT)
    first["stages"][0]["promise"] = {"name": "instant", "within_days": 0}
    assert "first stage" in process_spec_problem(first)
    after_state = {"id": "p", "entity": "Order", "stages": [
        {"name": "pending", "state": ["pending"]}, {"name": "shipped", "timestamp": "shipped_at",
                                                    "promise": {"within_days": 2}}]}
    assert "anchored to a state, which has no clock" in process_spec_problem(after_state)


@pytest.mark.parametrize("change, fragment", [
    (lambda s: s["stages"][1].update(timestamp="total_amount"), "is not a date or timestamp"),
    (lambda s: s["stages"][1].update(timestamp="packed_at"), "no property 'packed_at'"),
    (lambda s: s["stages"][1]["promise"].update(grain="Customer", deadline="signup_date"),
     "no measured to-one link from Customer to Order"),
    (lambda s: s["stages"][1]["promise"].update(grain="Review", deadline="review_date",
                                                via="review_to_customer.customer_to_order"), "is to-many"),
    (lambda s: s.update(entity="Shipment"), "no object type 'Shipment'"),
])
def test_a_declaration_the_graph_cannot_read_is_refused_before_anything_is_counted(graph, change, fragment):
    spec = copy.deepcopy(FULFILMENT)
    change(spec)
    assert process_spec_problem(spec) == ""
    problem, _ = resolve_process(graph, spec["id"], process_fields(spec))
    assert fragment in problem


def test_a_second_process_cannot_derive_a_name_another_already_derives(db, graph):
    declare(graph, db, FULFILMENT)
    twin = copy.deepcopy(FULFILMENT)
    twin["id"] = "order_fulfilment_again"
    problem, _ = resolve_process(graph, twin["id"], process_fields(twin))
    assert "already derived" in problem


# ── the comparison the promise is made of ───────────────────────────────────────────────────

def test_two_properties_of_one_object_compare_row_by_row_and_equal_the_reference(db, graph):
    assert run(db, {"object_type": "order", "filters": [{"path": "delivered_at", "op": ">", "value_path": "shipped_at"}],
                    "measures": [{"agg": "count"}]}, graph) == rows(
        db, "SELECT COUNT(*) FROM ecommerce.orders WHERE delivered_at > shipped_at")
    assert run(db, {"object_type": "order_item", "filters": [
        {"path": "order_item_to_order.shipped_at", "op": "<=", "value_path": "ship_by"}],
        "measures": [{"agg": "count"}]}, graph) == rows(db, f"SELECT COUNT(*) {LINE_JOIN} WHERE o.shipped_at <= i.ship_by")


@pytest.mark.parametrize("flt, fragment", [
    ({"path": "order_to_order_item.ship_by", "op": ">", "value_path": "shipped_at"}, "to-many link"),
    ({"path": "shipped_at", "op": ">", "value_path": "total_amount"}, "compares a point in time with a number"),
    ({"path": "shipped_at", "op": "in", "value_path": "delivered_at"}, "takes =, !=, >, >=, < or <="),
    ({"path": "shipped_at", "op": ">", "value": "2024-01-01", "value_path": "delivered_at"}, "names a value AND"),
])
def test_a_comparison_the_object_grain_cannot_hold_is_refused(graph, flt, fragment):
    assert fragment in refusal({"object_type": "order", "filters": [flt], "measures": [{"agg": "count"}]}, graph).reason


# ── the percentiles ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("values", [[3], [1, 2], [0, 0, 1, 5, 5, 9], [-2, 3, 3, 3, 8, 40, 41], list(range(-5, 97, 3))])
def test_percentiles_from_a_per_day_count_equal_the_warehouse_percentiles(values):
    con = duckdb.connect()
    histogram = list(Counter(values).items())
    for q in (0.5, 0.9, 0.95):
        (want,) = con.execute(f"SELECT quantile_cont(v, {q}) FROM (SELECT UNNEST({values}) AS v)").fetchone()
        assert quantile_cont(histogram, q) == pytest.approx(want)
    con.close()
    assert quantile_cont([], 0.5) is None


# ── the override file ───────────────────────────────────────────────────────────────────────

def test_the_overlay_rebuilds_a_measured_process_and_forgets_the_count_when_its_stages_change(db, graph):
    fields, measured = declare(graph, db, FULFILMENT)
    ov = OntologyOverride(target_kind="process", target_id="order_fulfilment", fields=fields,
                          binding={"process": process_entry(fields, measured)})
    save_override(*SCOPE, ov)
    served = fresh_graph()
    _, report = apply_overrides(served, *SCOPE)
    assert "process:order_fulfilment (<declared>)" in report.applied
    rebuilt = served.processes["order_fulfilment"]
    assert rebuilt.model_dump() == measured.model_dump()
    assert run(db, {"object_type": "order_item", "segment": "late_shipping", "measures": [{"agg": "count"}]},
               served) == [(measured.stages[1].promise.breached,)]
    renamed = declared_process(OntologyOverride(target_kind="process", target_id="order_fulfilment",
                                                fields={**fields, "display_name": "Fulfilment, end to end"},
                                                binding=ov.binding), served)
    assert renamed.display_name == "Fulfilment, end to end" and renamed.verified is True
    changed = copy.deepcopy(fields)
    changed["stages"][2]["promise"]["within_days"] = 3
    again = declared_process(OntologyOverride(target_kind="process", target_id="order_fulfilment", fields=changed,
                                              binding=ov.binding), served)
    assert again.verified is None and again.stages[2].promise.breached is None and "changed since" in again.note


def test_the_panel_reads_each_stage_its_timing_and_each_promise_with_what_it_derives(db, graph):
    _, p = declare(graph, db, FULFILMENT)
    described = describe_process(graph, p)
    placed, shipped, delivered = described["stages"]
    assert placed["transition"] is None and shipped["transition"]["from"] == "placed"
    assert shipped["promise"]["grain"] == "order_item" and shipped["promise"]["segment"] == "late_shipping"
    assert delivered["promise"]["metric"] == "delivery_breach_rate" and delivered["promise"]["kind"] == "within_days"
    assert {d["name"] for d in described["derived"]["properties"]} == {"shipping_lag_days", "delivery_lag_days"}


# ── rules ───────────────────────────────────────────────────────────────────────────────────

EU_CORE = {"id": "eu_core", "display_name": "EU core", "entity": "Customer", "kind": "value_set",
           "property": "country", "values": ["DE", "FR", "XX"], "owner": "finance"}


def declare_rule(graph, db, spec):
    assert rule_spec_problem(spec) == ""
    problem, fields = resolve_rule(graph, spec["id"], rule_fields(spec))
    assert problem == "", problem
    rule = measure_rule(db, graph, spec["id"], fields)
    graph.rules[spec["id"]] = rule
    return fields, rule


def test_a_value_set_counts_each_value_flags_one_no_row_holds_and_reads_as_a_segment(db, graph):
    _, rule = declare_rule(graph, db, EU_CORE)
    de, fr, customers = ints(db, "SELECT COUNT(*) FILTER (WHERE country = 'DE'), COUNT(*) FILTER (WHERE country = 'FR'), "
                                 "COUNT(*) FROM ecommerce.customers")
    assert rule.observed == {"DE": de, "FR": fr} and rule.missing == ["XX"]
    assert (rule.admitted, rule.objects, rule.verified) == (de + fr, customers, True)
    assert rule.flags[0].startswith("never observed: XX")
    assert run(db, {"object_type": "customer", "segment": "eu_core", "measures": [{"agg": "count"}]}, graph) == [(de + fr,)]


def test_a_condition_rule_is_counted_and_one_that_admits_nothing_is_refused_as_a_segment(db, graph):
    _, open_orders = declare_rule(graph, db, {"id": "open_orders", "entity": "Order", "kind": "condition",
                                              "conditions": [{"path": "status", "op": "not_in",
                                                              "values": ["cancelled", "refunded"]}]})
    (admitted,) = ints(db, "SELECT COUNT(*) FROM ecommerce.orders WHERE status NOT IN ('cancelled', 'refunded')")
    assert (open_orders.admitted, open_orders.verified, open_orders.flags) == (admitted, True, [])
    _, everything = declare_rule(graph, db, {"id": "dated", "entity": "Order", "kind": "condition",
                                             "conditions": [{"path": "order_date", "op": "not_null"}]})
    assert everything.flags[0].startswith("admits every one")
    _, nothing = declare_rule(graph, db, {"id": "teleported", "entity": "Order", "kind": "condition",
                                          "conditions": [{"path": "status", "op": "=", "value": "teleported"}]})
    assert (nothing.admitted, nothing.verified) == (0, False)
    assert "does not hold" in refusal({"object_type": "order", "segment": "teleported",
                                       "measures": [{"agg": "count"}]}, graph).reason


def test_a_rule_that_would_shadow_a_segment_or_that_the_compiler_refuses_is_not_declared(graph):
    problem, _ = resolve_rule(graph, "active_orders", rule_fields(
        {"id": "active_orders", "entity": "Order", "conditions": [{"path": "status", "op": "=", "value": "shipped"}]}))
    assert "already has a segment active_orders" in problem
    problem, _ = resolve_rule(graph, "odd", rule_fields(
        {"id": "odd", "entity": "Order", "conditions": [{"path": "order_to_customer.nickname", "op": "not_null"}]}))
    assert "no property 'nickname'" in problem
    assert "lists each value once" in rule_spec_problem({**EU_CORE, "values": ["DE", "DE"]})


def test_the_overlay_rebuilds_a_measured_rule(db, graph):
    fields, rule = declare_rule(graph, db, EU_CORE)
    ov = OntologyOverride(target_kind="rule", target_id="eu_core", fields=fields, binding={"rule": rule_entry(fields, rule)})
    served = fresh_graph()
    assert declared_rule(ov, served).model_dump() == rule.model_dump()
    edited = declared_rule(OntologyOverride(target_kind="rule", target_id="eu_core",
                                            fields={**fields, "values": ["DE", "AT", "CH"]}, binding=ov.binding), served)
    assert edited.verified is None and edited.observed == {}


# ── the doors ───────────────────────────────────────────────────────────────────────────────

CONN = "object-processes-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def door(tmp_path, monkeypatch):
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", fresh_graph())
    path = tmp_path / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute(_DEADLINES)
    con.close()

    def _open(*_a, **_k):
        return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)

    monkeypatch.setattr(C, "open_connection_for_with_schema", _open)
    return _open


def test_a_process_and_a_rule_are_declared_counted_read_back_and_withdrawn_over_http(door, client):
    declared = client.post("/ontology/processes", params=PARAMS, json=FULFILMENT)
    assert declared.status_code == 200, declared.text
    process = declared.json()["process"]
    shipping = process["stages"][1]["promise"]
    assert (process["verified"], shipping["grain"], shipping["segment"], shipping["verified"]) == (
        True, "order_item", "late_shipping", True)
    assert client.post("/ontology/processes", params=PARAMS, json=FULFILMENT).status_code == 409
    unknown = client.post("/ontology/processes", params=PARAMS, json={**FULFILMENT, "id": "other", "entity": "Shipment"})
    assert unknown.status_code == 400 and "no object type 'Shipment'" in unknown.json()["detail"]
    malformed = client.post("/ontology/processes", params=PARAMS, json={**FULFILMENT, "id": "Bad Id"})
    assert malformed.status_code == 400

    rate = client.post("/objects/query", params=PARAMS, json={
        "object_type": "order_item", "measures": [{"metric": "shipping_breach_rate", "scale": 100, "decimals": 2}]}).json()
    assert rate["path"] == "compiled", rate
    assert abs(float(rate["rows"][0][0]) - 100 * shipping["breached"] / shipping["reached"]) < 0.006

    listed = client.get("/ontology/processes", params=PARAMS).json()
    assert [p["id"] for p in listed["processes"]] == ["order_fulfilment"]
    line = client.get("/object-types/order_item", params=PARAMS).json()
    assert line["processes"][0]["roles"] == ["keeps its shipping promise"]
    assert "late_shipping" in [d["name"] for d in line["derived"]["segments"]]
    mapped = client.get("/object-types", params=PARAMS).json()
    assert mapped["processes"][0]["promises"][0]["name"] == "shipping"

    rule = client.post("/ontology/rules", params=PARAMS, json=EU_CORE)
    assert rule.status_code == 200, rule.text
    assert (rule.json()["rule"]["missing"], rule.json()["rule"]["verified"]) == (["XX"], True)
    shadow = client.post("/ontology/rules", params=PARAMS, json={
        "id": "active_orders", "entity": "Order", "conditions": [{"path": "status", "op": "=", "value": "shipped"}]})
    assert shadow.status_code == 400 and "already has a segment" in shadow.json()["detail"]

    measured = client.post("/ontology/measure", params=PARAMS).json()
    assert [(p["process"], p["verified"]) for p in measured["processes"]] == [("order_fulfilment", True)]
    assert measured["processes"][0]["promises"][0]["breached"] == shipping["breached"]
    assert [r["rule"] for r in measured["rules"]] == ["eu_core"]

    assert client.delete("/ontology/processes/order_fulfilment", params=PARAMS).status_code == 200
    assert client.delete("/ontology/processes/order_fulfilment", params=PARAMS).status_code == 404
    gone = client.post("/objects/query", params=PARAMS, json={
        "object_type": "order_item", "segment": "late_shipping", "measures": [{"agg": "count"}]}).json()
    assert gone["path"] == "refused" and "no segment 'late_shipping'" in gone["refused"]
    assert client.delete("/ontology/rules/eu_core", params=PARAMS).status_code == 200
    assert client.get("/ontology/processes", params=PARAMS).json() == {
        "connection_id": CONN, "schema_name": "ecommerce", "processes": [], "rules": []}
