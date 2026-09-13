"""ON-10 — the question framed against the declared ontology before anything reads it.

A frame is resolved from the question's words and the declared names alone — no model, no database — and every
definition it hands on is COMPILED by the object door. So every claim here is held to one of two things: a hand-written
expectation of what the words resolve to on the samples warehouse (declared with ON-9's order-fulfilment process and
its rules, exactly as ON-9's own tests declare them), or a hand-written query whose result the frame's compiled SQL
must equal. The served Olist graph (`evals/ablation_olist_business_ontology.json`) holds the questions the movement is
measured on: the dispatch question reads as the promise the business declared, from the line it is kept per.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology import overrides as OV
from aughor.ontology.framing import Frame, frame_question, frame_reading, render_frame_block, stem
from aughor.ontology.models import OntologyGraph
from aughor.ontology.processes import process_fields, process_from_fields, resolve_process
from tests.unit.test_object_bindings import rows, seed
from tests.unit.test_object_processes import (  # noqa: F401 — `door` is a fixture, used by name
    _DEADLINES,
    EU_CORE,
    FULFILMENT,
    PARAMS,
    declare,
    declare_rule,
    door,
    fresh_graph,
)

REPO = Path(__file__).resolve().parents[2]
OLIST = REPO / "evals" / "ablation_olist_business_ontology.json"
LINES = ("FROM ecommerce.order_items i LEFT JOIN ecommerce.orders o ON o.order_id = i.order_id "
         "LEFT JOIN ecommerce.products p ON p.product_id = i.product_id "
         "LEFT JOIN ecommerce.customers c ON c.customer_id = o.customer_id")
BROKE = "o.shipped_at > i.ship_by"
REACHED = "o.shipped_at IS NOT NULL AND i.ship_by IS NOT NULL"
OPEN_ORDERS = {"id": "open_orders", "entity": "Order", "kind": "condition",
               "conditions": [{"path": "status", "op": "not_in", "values": ["cancelled", "refunded"]}]}
FIVE_STAR = {"id": "five_star", "entity": "Review", "kind": "condition",
             "conditions": [{"path": "rating", "op": "=", "value": 5}]}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("framing") / "samples.duckdb"
    seed(path)
    con = duckdb.connect(str(path))
    con.execute(_DEADLINES)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="framing-t")
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


@pytest.fixture(scope="module")
def declared(db) -> OntologyGraph:
    """The samples graph with ON-9's fulfilment process and three rules declared and counted against the warehouse."""
    graph = fresh_graph()
    declare(graph, db, FULFILMENT)
    for spec in (EU_CORE, OPEN_ORDERS, FIVE_STAR):
        declare_rule(graph, db, spec)
    return graph


def run(db, sql: str) -> list[tuple]:
    return rows(db, sql)


def olist() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(OLIST.read_text()))


# ── words ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("family", [
    ("dispatch", "dispatched", "dispatches", "dispatching"),
    ("delivery", "delivered", "deliveries", "deliver"),
    ("category", "categories"),
    ("fulfilled", "fulfilment", "fulfillment"),
    ("shipping", "shipped", "shipment", "ship"),
    ("state", "states"),
    ("approved", "approval", "approve"),
    ("promise", "promises", "promised"),
    ("cancelled", "canceled"),
])
def test_the_inflections_of_a_business_word_share_one_stem(family):
    assert len({stem(w) for w in family}) == 1, {w: stem(w) for w in family}


# ── nothing declared, nothing framed ────────────────────────────────────────────────────────


def test_a_question_that_reaches_no_declaration_defines_nothing_and_renders_nothing(declared):
    frame = frame_question("How many customers are there in each country?", declared)
    assert [t.kind for t in frame.terms] == ["entity", "property"]
    assert not frame.defines and frame.outcomes == [] and render_frame_block(frame) == "" and frame_reading(frame) == ""
    bare = frame_question("Which orders were shipped late?", fresh_graph())          # nothing declared on it
    assert not bare.defines and render_frame_block(bare) == ""
    assert frame_question("anything", None) == Frame(question="anything")


def test_a_declaration_never_counted_defines_nothing(db):
    graph = fresh_graph()
    problem, fields = resolve_process(graph, FULFILMENT["id"], process_fields(FULFILMENT))
    assert problem == ""
    graph.processes[FULFILMENT["id"]] = process_from_fields(FULFILMENT["id"], fields)    # declared, not measured
    frame = frame_question("Which order lines were shipped late?", graph)
    [outcome] = frame.outcomes
    assert (outcome.name, outcome.usable) == ("shipping_breach_rate", False) and "has not been measured" in outcome.why_not
    assert frame.chosen is None and not frame.defines and render_frame_block(frame) == ""


# ── a promise, read from the type it is kept per ────────────────────────────────────────────


def test_a_promised_stage_asked_about_as_late_reads_as_its_promise_from_the_line_it_is_kept_per(db, declared):
    frame = frame_question("Which product categories are shipped late most often?", declared)
    outcome = frame.outcome
    assert (outcome.kind, outcome.name, outcome.segment, frame.chosen_by) == (
        "promise", "shipping_breach_rate", "late_shipping", "names")
    assert frame.start["entity"] == "OrderItem" and frame.start["object_type"] == "order_item"
    assert frame.drivers[0].path == "order_item_to_product.category" and frame.drivers[0].named
    assert "shipped" in outcome.matched
    compiled = frame.compiled["by order_item_to_product.category"]
    assert run(db, compiled["sql"]) == run(db, f"SELECT p.category, 1.0 * COUNT(*) FILTER (WHERE {BROKE}) / "
                                               f"NULLIF(COUNT(*) FILTER (WHERE {REACHED}), 0) {LINES} GROUP BY 1")
    promise = declared.processes["order_fulfilment"].stages[1].promise
    assert run(db, frame.compiled["late_shipping"]["sql"]) == [(promise.breached,)]
    assert run(db, frame.compiled["shipping_breach_rate"]["sql"]) == [(round(promise.breached / promise.reached, 4),)]


@pytest.mark.parametrize("question, kind, name", [
    ("How long does shipping take?", "lag", "shipping_lag_days"),
    ("What is causing delivery delays?", "promise", "delivery_breach_rate"),
    ("What is the average delivery delay in days?", "lag", "delivery_lag_days"),
    ("Which categories have the worst shipping record?", "promise", "shipping_breach_rate"),
    ("Were deliveries on time?", "promise", "delivery_breach_rate"),
    ("How is late_shipping trending?", "promise", "shipping_breach_rate"),
])
def test_what_is_asked_of_a_stage_decides_between_its_promise_and_its_lag(declared, question, kind, name):
    frame = frame_question(question, declared)
    assert (frame.outcome.kind, frame.outcome.name) == (kind, name), [(o.name, o.score) for o in frame.outcomes]


def test_a_lag_compiles_to_the_calendar_days_between_the_two_moments(db, declared):
    frame = frame_question("How long does shipping take?", declared)
    assert frame.start["entity"] == "Order"
    assert run(db, frame.compiled["shipping_lag_days"]["sql"]) == run(
        db, "SELECT AVG(date_diff('day', order_date, shipped_at)) FROM ecommerce.orders")


# ── "late" with no stage named: the link graph ranks the promises ───────────────────────────


def test_late_with_no_stage_named_is_read_as_the_promise_whose_type_reaches_what_the_question_names(declared):
    categories = frame_question("Which categories are late?", declared)
    assert categories.outcome.name == "shipping_breach_rate" and categories.chosen_by == "names"
    assert [o.name for o in categories.outcomes] == ["shipping_breach_rate", "delivery_breach_rate"]
    assert any("kept per Order, which reaches no category" in n for n in categories.notes)
    orders = frame_question("Which orders were late?", declared)
    assert orders.outcome.name == "delivery_breach_rate" and orders.start["entity"] == "Order"


def test_words_that_fit_two_promises_equally_choose_neither_and_list_both(db, declared):
    frame = frame_question("What was late last month?", declared)
    assert frame.ambiguous and frame.chosen is None and frame.start is None and frame.drivers == []
    assert {o.name for o in frame.candidates()} == {"shipping_breach_rate", "delivery_breach_rate"}
    block = render_frame_block(frame)
    assert "fit 2 declared definitions" in block and "(1)" in block and "(2)" in block
    for key in ("late_shipping", "shipping_breach_rate", "late_delivery", "delivery_breach_rate"):
        assert not frame.compiled[key].get("refused"), frame.compiled[key]
        run(db, frame.compiled[key]["sql"])
    assert frame.model_dump()["ambiguous"] is True


def test_a_choice_chooses_only_among_the_candidates(declared):
    chosen = frame_question("What was late last month?", declared, choice="delivery_breach_rate", chosen_by="model")
    assert (chosen.outcome.name, chosen.chosen_by, chosen.start["entity"]) == ("delivery_breach_rate", "model", "Order")
    invented = frame_question("What was late last month?", declared, choice="revenue_at_risk")
    assert invented.chosen is None and invented.ambiguous
    assert "'revenue_at_risk' is not one of the declared definitions" in invented.notes[0]
    unrelated = frame_question("Which order lines were shipped late?", declared, choice="late_delivery")
    assert unrelated.chosen is None or unrelated.outcome.name == "shipping_breach_rate"


# ── rules and moments ───────────────────────────────────────────────────────────────────────


def test_a_rule_filters_from_the_start_through_measured_to_one_links_and_equals_its_reference(db, declared):
    frame = frame_question("What share of order lines for EU core customers were shipped late?", declared)
    assert frame.outcome.name == "shipping_breach_rate" and frame.start["entity"] == "OrderItem"
    [rule] = frame.rules
    assert (rule.id, rule.via, rule.usable) == ("eu_core", "order_item_to_order.order_to_customer", True)
    assert rule.filters == [{"path": "order_item_to_order.order_to_customer.country", "op": "in",
                             "values": ["DE", "FR", "XX"]}]
    assert run(db, frame.compiled["shipping_breach_rate"]["sql"]) == run(
        db, f"SELECT 1.0 * COUNT(*) FILTER (WHERE {BROKE}) / NULLIF(COUNT(*) FILTER (WHERE {REACHED}), 0) {LINES} "
            "WHERE c.country IN ('DE', 'FR', 'XX')")
    assert "EU core" in frame.reading and "order_item_to_order.order_to_customer" in frame.reading


def test_a_rule_on_a_type_the_start_cannot_reach_is_said_and_never_applied(declared):
    frame = frame_question("Were order lines with five star reviews shipped late?", declared)
    [rule] = frame.rules
    assert rule.id == "five_star" and not rule.usable and rule.filters == []
    assert "Review is not reachable from OrderItem" in rule.why_not
    assert frame.defines and "which this frame cannot apply" in render_frame_block(frame)
    assert "order_item_to_review" not in json.dumps(frame.compiled)


def test_a_rule_alone_is_the_outcome_and_a_stage_named_for_its_moment_is_read_as_that_moment(db, declared):
    frame = frame_question("How many open orders were placed in 2024?", declared)
    assert (frame.outcome.kind, frame.outcome.name, frame.start["entity"]) == ("rule", "open_orders", "Order")
    [moment] = frame.moments
    assert (moment.stage, moment.timestamp) == ("placed", "order_date")
    assert run(db, frame.compiled["open_orders"]["sql"]) == run(
        db, "SELECT COUNT(*) FROM ecommerce.orders WHERE status NOT IN ('cancelled', 'refunded')")
    assert frame.reading.count("rule open_orders") == 1


# ── names ───────────────────────────────────────────────────────────────────────────────────


def test_a_longer_declared_name_wins_its_words_and_a_person_s_synonym_is_a_name(declared):
    shipped = frame_question("Which order lines were shipped late?", declared)
    assert [(t.kind, t.target) for t in shipped.terms if t.text == "shipped"] == [("promise", "order_fulfilment.shipped")]
    lines = frame_question("How many order lines are there?", declared)
    assert [(t.text, t.target, t.via) for t in lines.terms] == [("order lines", "OrderItem", "display name")]
    renamed = declared.model_copy(deep=True)
    renamed.entities["Order"].source_tables = ["purchases"]                    # a table not spelled like its type
    by_table = frame_question("How many purchases were shipped late?", renamed)
    assert [(t.text, t.target, t.via) for t in by_table.terms][0] == ("purchases", "Order", "table")
    handover = frame_question("Which handovers were late?", declared,
                              synonyms=[("term", "order_fulfilment.shipped", "handover")])
    assert handover.outcome.name == "shipping_breach_rate"
    assert [(t.kind, t.via) for t in handover.terms] == [("stage", "synonym")]
    assert frame_question("Which handovers were late?", declared).outcome is None or \
        frame_question("Which handovers were late?", declared).ambiguous


# ── drivers ─────────────────────────────────────────────────────────────────────────────────


def test_a_driver_is_reachable_only_by_measured_to_one_links_within_the_hops(declared):
    q = "Which product categories are shipped late most often?"
    two = {d.path for d in frame_question(q, declared, hops=2).drivers}
    one = {d.path for d in frame_question(q, declared, hops=1).drivers}
    assert {"order_item_to_product.category", "order_item_to_order.status", "order_item_to_order.payment_method",
            "order_item_to_order.order_to_customer.country"} <= two
    assert "order_item_to_order.order_to_customer.country" not in one and "order_item_to_product.category" in one
    assert not any("review" in p for p in two)                                   # N:N, never followed
    unmeasured = declared.model_copy(deep=True)
    unmeasured.relationships["OrderItem_RELATES_TO_Product"].measured_cardinality = None
    frame = frame_question(q, unmeasured)
    assert not any(d.path.startswith("order_item_to_product") for d in frame.drivers)
    assert any("category is on Product, which OrderItem does not reach" in n for n in frame.notes)


# ── what the frame hands on ─────────────────────────────────────────────────────────────────


def test_the_block_carries_the_definition_its_compiled_sql_the_start_and_the_drivers(declared):
    frame = frame_question("Which product categories are shipped late most often?", declared)
    block = render_frame_block(frame)
    assert block.startswith("QUESTION FRAME")
    for part in ("the shipping promise of Order fulfilment (stage shipped)", "measured:", "late_shipping, compiled",
                 "shipping_breach_rate, compiled", "by order_item_to_product.category, compiled", "Start from Order Line",
                 "order_item_to_product.category (named in the question)", "FROM ecommerce.order_items"):
        assert part in block, part
    assert Frame.model_validate(json.loads(json.dumps(frame.model_dump(mode="json")))).model_dump() == frame.model_dump()


# ── the host the movement is measured on ────────────────────────────────────────────────────


def test_on_olist_a_dispatch_delay_reads_as_the_promise_the_business_declared():
    graph = olist()
    frame = frame_question("What is causing a delay in warehouse dispatch?", graph)
    outcome = frame.outcome
    assert (outcome.name, outcome.entity, outcome.stage) == ("dispatch_breach_rate", "OrderItem", "dispatched")
    assert "shipping_limit_date" in outcome.definition and "(9.35%)" in outcome.measured
    assert frame.start["table"] == "order_items" and frame.start["key_unique"] is False
    paths = [d.path for d in frame.drivers]
    assert paths[:2] == ["order_item_to_product.product_category_name", "order_item_to_seller.seller_state"]
    block = render_frame_block(frame)
    assert "NOT unique per row" in block and "FROM ecommerce.order_items" in block

    returned = frame_question("Which three seller states have the worst dispatch record? Return the state and its breach "
                              "percentage.", graph)
    assert [d.path for d in returned.drivers if d.named] == ["order_item_to_seller.seller_state"]   # "the state" is it again
    assert {d.path for d in frame_question("Which states break the dispatch promise most often?", graph).drivers
            if d.named} == {"order_item_to_seller.seller_state",
                            "order_item_to_order.order_to_customer.customer_state"}         # bare: every state it fits
    # "product categories" also names the translation table's column, which no type reaches; it must not veto the one
    # the dispatch promise's line does reach
    assert frame_question("Which product categories are always late?", graph).outcome.name == "dispatch_breach_rate"
    worst = frame_question("Which seller states have the worst dispatch record?", graph)
    assert [(d.path, d.named) for d in worst.drivers[:2]] == [          # named first, though product sorts ahead of seller
        ("order_item_to_seller.seller_state", True), ("order_item_to_product.product_category_name", False)]

    categories = frame_question("Which categories are always late?", graph)
    assert categories.outcome.name == "dispatch_breach_rate"
    assert any("delivery promise" in n and "kept per Order" in n for n in categories.notes)

    southeast = frame_question("How does the dispatch promise hold for sellers in the Southeast versus everywhere else?",
                               graph)
    [rule] = southeast.rules
    assert (rule.id, rule.via, rule.filters[0]["path"]) == ("southeast", "order_item_to_seller",
                                                           "order_item_to_seller.seller_state")
    fulfilled = frame_question("What share of fulfilled orders broke the delivery promise?", graph)
    assert fulfilled.outcome.name == "delivery_breach_rate" and fulfilled.rules[0].filters[0]["path"] == "order_status"
    assert not frame_question("How many sellers are there in each state?", graph).defines


# ── the door ────────────────────────────────────────────────────────────────────────────────


def test_the_frame_door_frames_a_question_with_no_model_and_no_warehouse(door, client):  # noqa: F811 — `door` is the imported fixture
    assert client.post("/ontology/processes", params=PARAMS, json=FULFILMENT).status_code == 200
    framed = client.post("/ontology/frame", params=PARAMS,
                         json={"question": "Which product categories are shipped late most often?"})
    assert framed.status_code == 200, framed.text
    frame = framed.json()["frame"]
    assert frame["defines"] is True and frame["outcomes"][frame["chosen"]]["name"] == "shipping_breach_rate"
    assert frame["start"]["entity"] == "OrderItem" and frame["drivers"][0]["path"] == "order_item_to_product.category"
    assert "late_shipping" in frame["compiled"] and frame["reading"].startswith('Read "shipped"')
    nothing = client.post("/ontology/frame", params=PARAMS, json={"question": "How many customers are there?"}).json()
    assert nothing["frame"]["defines"] is False and nothing["frame"]["reading"] == ""
    assert client.post("/ontology/frame", params=PARAMS, json={"question": "  "}).status_code == 400
    assert client.post("/ontology/frame", params={**PARAMS, "schema_name": "no_such_schema"},
                       json={"question": "late?"}).status_code in (200, 404)
