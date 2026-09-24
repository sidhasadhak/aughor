"""ON-7b — the explorer maps the business first (ROADMAP §3.15, the second movement).

An explorer reads the source catalogue and proposes the business ontology in one model call, and nothing it says is
believed. Every claim here is held to the seeded samples warehouse (orders, order_items, customers, products, reviews,
plus the payments, refunds and order_events tables `test_object_bindings` adds), through the real doors, with the model
scripted by the faux backend: the data — not the model — decides a part's kind; what the data refutes is refused and
never written; what survives lands at once with `origin: model` and the provenance of the model that answered, and a
compiled query reads it; a second run writes nothing; a proposal a person withdrew is not proposed again; a person's
confirmation makes a proposal theirs and keeps who proposed it; and the grouping comparison names a fusion as the thing
that keeps a draft from shipping default-on.
"""
from __future__ import annotations

import json

import duckdb
import pytest
import yaml

from aughor.db.connection import open_connection
from aughor.ontology import drafts as DR
from aughor.ontology import overrides as OV
from aughor.ontology.explorer import (
    BusinessDraft,
    compare_groupings,
    entity_key,
    process_key,
    rule_key,
    source_catalogue,
)
from aughor.ontology.models import OntologyGraph
from tests.unit.test_object_bindings import GRAPH, ints, seed

CONN = "explorer-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}
PROVENANCE = "model:faux-coder@2"

CATEGORY_SQL = "SELECT DISTINCT category FROM products"
BUYER_SQL = "SELECT customer_id, order_id FROM orders"
DRAFT = {
    "entities": [
        {"id": "Category", "display_name": "Category", "description": "a family of products", "domain": "Catalog",
         "sql": CATEGORY_SQL, "key": "category", "reason": "products are sold by category"},
        {"id": "Buyer", "display_name": "Buyer", "sql": BUYER_SQL, "key": "customer_id",
         "reason": "a customer who bought — but one row per order, not per buyer"},
    ],
    "parts": [
        {"entity": "Order", "table": "order_items", "key": "order_id", "name": "lines", "reason": "an order has lines",
         "rollups": [{"property": "units", "column": "quantity", "agg": "SUM"},
                     {"property": "status", "column": "quantity", "agg": "sum"},
                     {"property": "top_price", "column": "no_such_column", "agg": "max"}]},
        # the model takes a column for a clock; the data says one row per order, so it is read as it is
        {"entity": "Order", "table": "payments", "key": "order_id", "name": "payment", "time_column": "installments",
         "reason": "an order is paid once"},
        {"entity": "Order", "table": "refunds", "key": "order_id", "name": "refunds", "reason": "orders get refunded"},
        {"entity": "Order", "table": "order_events", "key": "order_id", "name": "events", "time_column": "event_at",
         "reason": "an order moves through events"},
        # reviews.order_id holds order keys, never a customer's: the keys never meet
        {"entity": "Customer", "table": "reviews", "key": "order_id", "name": "reviews", "reason": "a mistake"},
        {"entity": "Invoice", "table": "payments", "key": "order_id", "reason": "no such entity"},
    ],
    "links": [
        {"from_entity": "Review", "to_entity": "Order", "verb": "reviews", "from_column": "order_id",
         "to_column": "order_id", "reason": "a review is about an order"},
        {"from_entity": "Review", "to_entity": "Product", "verb": "rates", "from_column": "customer_id",
         "to_column": "product_id", "reason": "a mistake: customer keys are never product keys"},
        {"from_entity": "Order", "to_entity": "Customer", "verb": "placed_by", "from_column": "customer_id",
         "to_column": "customer_id", "reason": "the builder already joined these"},
    ],
    "processes": [
        {"id": "OrderFulfilment", "entity": "Order", "display_name": "Order fulfilment", "reason": "orders ship, then arrive",
         "stages": [{"name": "placed", "timestamp": "order_date"}, {"name": "shipped", "timestamp": "shipped_at"},
                    {"name": "delivered", "timestamp": "delivered_at"}]},
        # a stage no order ever reaches: the data refuses it
        {"id": "order_returns", "entity": "Order", "reason": "a mistake: no order is returned",
         "stages": [{"name": "placed", "timestamp": "order_date"},
                    {"name": "returned", "state": ["returned"], "property": "status"}]},
    ],
    "rules": [
        {"id": "fulfilled_orders", "entity": "Order", "kind": "condition", "reason": "what finance counts",
         "conditions": [{"path": "status", "op": "not_in", "values": ["cancelled", "refunded"]}]},
        {"id": "eu_customers", "entity": "Customer", "kind": "value_set", "property": "country",
         "values": ["DE", "FR", "GB"], "reason": "the EU markets"},
        # two spellings the data does not hold, and a condition that excludes nothing
        {"id": "dach", "entity": "Customer", "kind": "value_set", "property": "country", "values": ["DE", "AT", "CH"],
         "reason": "the DACH markets"},
        {"id": "any_order", "entity": "Order", "kind": "condition", "reason": "every order",
         "conditions": [{"path": "order_date", "op": "not_null"}]},
    ],
}
FULFILMENT = process_key("Order", DRAFT["processes"][0]["stages"])
RETURNS = process_key("Order", DRAFT["processes"][1]["stages"])
RULES = {r["id"]: rule_key(r["entity"], r["kind"], r.get("property", ""), r.get("values"), r.get("conditions"))
         for r in DRAFT["rules"]}
LINES, PAYMENT, REFUNDS, EVENTS = "part:Order:order_items", "part:Order:payments", "part:Order:refunds", "part:Order:order_events"
REVIEW_LINK = "link:Order.order_id=Review.order_id"
NEVER_MEET = "link:Product.product_id=Review.customer_id"
CATEGORY, BUYER = entity_key(sql=CATEGORY_SQL, primary_key="category"), entity_key(sql=BUYER_SQL, primary_key="customer_id")


@pytest.fixture(autouse=True)
def _isolated_trees(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(DR, "_ROOT", tmp_path / "ontology_drafts")


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


def explore(client) -> dict:
    res = client.post("/ontology/explore", params=PARAMS)
    assert res.status_code == 200, res.text
    return res.json()


def tree() -> dict[str, str]:
    root = OV._ROOT
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.yaml"))} if root.exists() else {}


# ── a draft, measured before it lands ───────────────────────────────────────────────────────

def test_a_draft_is_measured_before_it_lands_and_what_survives_is_read_at_once(door, client, faux_llm):
    faux_llm.set_responses([DRAFT])
    body = explore(client)
    (call,) = faux_llm.calls()
    assert "SOURCE CATALOGUE" in call.user and "order_items.order_id → orders.order_id" in call.user
    assert "PARTS  (parts)" in call.user and call.response_model is BusinessDraft
    assert "PROCESSES  (processes)" in call.user and "RULES  (rules)" in call.user

    run = body["run"]
    assert (run["written"], run["refused"], run["already"], run["withdrawn"]) == (9, 7, 1, 0)
    assert (run["provenance"], run["backend"], run["fallback"]) == (PROVENANCE, "faux", False)
    assert run["said"] == {"entities": 2, "parts": 6, "links": 3, "processes": 2, "rules": 4}
    # the run's model call is recorded under the run's own trace — the session log drops an event with no trace, so an
    # untraced door spends where no Spend or Activity view can see it
    from aughor.obs.session_log import recover_session
    recorded = [e for e in recover_session(run["trace_id"]) if e.get("kind") == "llm_call"]
    assert [e.get("model") for e in recorded] == ["faux-coder"]
    outcome = {o["key"]: o for o in body["outcomes"]}

    # the data decides the kind: a repeating key is many rows per order; a unique one is one row, whatever was said
    order = client.get("/object-types/order", params=PARAMS).json()
    bound = {b["name"]: b for b in order["bindings"] if not b["primary"]}
    assert {n: (b["kind"], b["source"], b["provenance"], b["usable"]) for n, b in bound.items()} == {
        "lines": ("detail", "model", PROVENANCE, True), "payment": ("static", "model", PROVENANCE, True),
        "refunds": ("detail", "model", PROVENANCE, True), "events": ("timeseries", "model", PROVENANCE, True)}
    assert "not as readings over installments" in outcome[PAYMENT]["note"]
    assert set(bound["lines"]["rollups"]) == {"units"}                 # status is Order's already; the column is not there
    assert "rollup status dropped" in outcome[LINES]["note"] and "rollup top_price dropped" in outcome[LINES]["note"]
    assert set(bound["refunds"]["rollups"]) == {"refunds_count"}       # none said: the count the data vouches for
    # PENDING item 20 — a proposal never hides a type: order_item is read as Order's lines at once, and stays a type of
    # its own until a person confirms the part (confirming absorbs it — pinned below)
    assert order["parts"] == []
    assert "OrderItem stays a type of its own until a person confirms this part" in outcome[LINES]["note"]

    # the declarations carry who said them, on the overrides tree the platform reads
    saved = yaml.safe_load((OV._ROOT / CONN / "ecommerce" / "entity" / "Order.yaml").read_text())
    assert {n: (e["origin"], e["provenance"]) for n, e in saved["binding"]["bindings"]["entries"].items()} == {
        n: ("model", PROVENANCE) for n in ("lines", "payment", "refunds", "events")}
    category = client.get("/object-types/category", params=PARAMS).json()
    assert (category["origin"], category["provenance"], category["key"]["verified"]) == ("model", PROVENANCE, True)
    review = client.get("/object-types/review", params=PARAMS).json()
    link = next(link for link in review["links"] if link["business_name"] == "reviews")
    assert (link["origin"], link["provenance"], link["traversable"]) == ("model", PROVENANCE, True)

    # what the data refutes is refused with its reason, and never written
    assert "keys never meet" in outcome["part:Customer:reviews"]["note"]
    assert "no entity 'Invoice'" in outcome["part:Invoice:payments"]["note"]
    assert "keys never meet" in outcome[NEVER_MEET]["note"]
    assert "does not name one object per row" in outcome[BUYER]["note"]
    assert outcome["link:Customer.customer_id=Order.customer_id"]["outcome"] == "already"
    types = {t["id"] for t in client.get("/object-types", params=PARAMS).json()["object_types"]}
    assert "Buyer" not in types and "Category" in types
    assert [b for b in client.get("/object-types/customer", params=PARAMS).json()["bindings"] if not b["primary"]] == []
    assert "rates" not in {link["business_name"] for link in review["links"]}

    # read at once: a compiled query over the proposed rollup equals its hand-written reference
    query = {"object_type": "order", "filters": [{"path": "units", "op": ">", "value": 8}], "measures": [{"agg": "count"}]}
    compiled = client.post("/objects/query", params=PARAMS, json=query).json()
    assert compiled["path"] == "compiled", compiled
    conn = door()
    try:
        (expected,) = ints(conn, "SELECT COUNT(*) FROM orders o JOIN (SELECT order_id, SUM(quantity) AS u FROM "
                                 "order_items GROUP BY 1) l ON l.order_id = o.order_id WHERE l.u > 8")
    finally:
        conn.close()
    assert int(compiled["rows"][0][0]) == expected

    # ON-9 — a process and the rules the data holds land as proposals; what it refutes is refused with the reason
    assert {k: outcome[k]["outcome"] for k in (FULFILMENT, RETURNS, *RULES.values())} == {
        FULFILMENT: "written", RETURNS: "refused", RULES["fulfilled_orders"]: "written", RULES["eu_customers"]: "written",
        RULES["dach"]: "refused", RULES["any_order"]: "refused"}
    assert outcome[RETURNS]["note"] and "never observed: AT, CH" in outcome[RULES["dach"]]["note"]
    assert "excludes nothing" in outcome[RULES["any_order"]]["note"]
    declared = client.get("/ontology/processes", params=PARAMS).json()
    assert [(p["id"], p["origin"], p["provenance"], p["verified"]) for p in declared["processes"]] == [
        ("order_fulfilment", "model", PROVENANCE, True)]
    assert [(r["id"], r["origin"], r["provenance"]) for r in declared["rules"]] == [
        ("eu_customers", "model", PROVENANCE), ("fulfilled_orders", "model", PROVENANCE)]
    fulfilled = client.post("/objects/query", params=PARAMS, json={
        "object_type": "order", "segment": "fulfilled_orders", "measures": [{"agg": "count"}]}).json()
    conn = door()
    try:
        (kept,) = ints(conn, "SELECT COUNT(*) FROM orders WHERE status NOT IN ('cancelled', 'refunded')")
    finally:
        conn.close()
    assert (fulfilled["path"], int(fulfilled["rows"][0][0])) == ("compiled", kept)
    from aughor.routers.ontology import served_ontology_graph
    catalogue = source_catalogue(served_ontology_graph(CONN, "ecommerce"))   # the next run reads what this one declared
    assert "process order_fulfilment on Order: placed → shipped → delivered (proposed by a model" in catalogue
    assert "rule fulfilled_orders on Order (condition, proposed by a model" in catalogue

    view = client.get("/ontology/draft", params=PARAMS).json()
    assert view["counts"] == {"proposed": 9, "confirmed": 0, "released": 0, "withdrawn": 0, "refused": 7}
    # an unconfirmed part does not move a card on the map: order_items stays with its own type until a person confirms
    # (PENDING item 20); confirming moves it under Order — `test_confirming_a_part_absorbs_its_type_and_not_before`
    assert view["grouping"]["Order"] == ["order_events", "orders", "payments", "refunds"]
    assert view["grouping"]["OrderItem"] == ["order_items"] and [r["id"] for r in view["runs"]] == [run["id"]]


def test_a_second_run_writes_nothing_twice_and_a_withdrawn_proposal_is_not_proposed_again(door, client, faux_llm):
    faux_llm.set_responses([DRAFT, DRAFT, DRAFT])
    explore(client)
    before = tree()
    again = explore(client)["run"]
    assert (again["written"], again["already"], again["refused"]) == (0, 10, 7)
    assert tree() == before                                            # not one override file touched

    assert client.delete("/ontology/entities/Category", params=PARAMS).status_code == 200
    assert client.delete("/ontology/entities/Order/bindings/refunds", params=PARAMS).status_code == 200
    # a part is absorbed when a person confirms it (PENDING item 20); releasing it is what a person does after that
    assert client.post("/ontology/draft/confirm", params=PARAMS, json={
        "targets": [{"kind": "binding", "entity": "Order", "binding": "lines"}]}).status_code == 200
    assert client.put("/ontology/entities/OrderItem", params=PARAMS, json={"absorbed_into": ""}).status_code == 200
    assert client.delete("/ontology/processes/order_fulfilment", params=PARAMS).status_code == 200
    tiers = {p["key"]: p["tier"] for p in client.get("/ontology/draft", params=PARAMS).json()["proposals"]}
    assert (tiers[CATEGORY], tiers[REFUNDS], tiers[LINES], tiers[PAYMENT], tiers[FULFILMENT]) == (
        "withdrawn", "withdrawn", "released", "proposed", "withdrawn")

    third = explore(client)
    outcome = {o["key"]: o for o in third["outcomes"]}
    assert {k: outcome[k]["outcome"] for k in (CATEGORY, REFUNDS, LINES)} == dict.fromkeys((CATEGORY, REFUNDS, LINES),
                                                                                         "withdrawn")
    assert third["run"]["written"] == 0 and "withdrew" in outcome[CATEGORY]["note"] and "released" in outcome[LINES]["note"]
    assert outcome[FULFILMENT]["outcome"] == "withdrawn"                # a withdrawn process is not proposed again
    assert "category" not in {t["object_type"] for t in client.get("/object-types", params=PARAMS).json()["object_types"]}
    order = client.get("/object-types/order", params=PARAMS).json()
    assert "refunds" not in {b["name"] for b in order["bindings"]} and order["parts"] == []


def test_confirming_a_part_absorbs_its_type_and_not_before(door, client, faux_llm):
    """PENDING item 20: absorbing hides a type from the map and the agent's catalogue, so it waits for a person."""
    faux_llm.set_responses([DRAFT])
    explore(client)
    before = client.get("/object-types/order", params=PARAMS).json()
    assert before["parts"] == []
    tiers = {p["key"]: p["tier"] for p in client.get("/ontology/draft", params=PARAMS).json()["proposals"]}
    assert tiers[LINES] == "proposed"

    confirmed = client.post("/ontology/draft/confirm", params=PARAMS, json={
        "targets": [{"kind": "binding", "entity": "Order", "binding": "lines"}], "actor": "ana"})

    assert confirmed.status_code == 200, confirmed.text
    [part] = client.get("/object-types/order", params=PARAMS).json()["parts"]
    assert (part["object_type"], part["binding"]) == ("order_item", "lines")
    assert {p["key"]: p["tier"] for p in confirmed.json()["proposals"]}[LINES] == "confirmed"
    grouping = confirmed.json()["grouping"]
    assert "order_items" in grouping["Order"] and "OrderItem" not in grouping


def test_a_table_that_reaches_few_of_its_parent_is_not_made_a_part(door, client, faux_llm):
    """PENDING item 20 — the explorer's one measured fusion, replayed with no model and no reference: LuxExperience's
    support tickets (their own type; 11,244 of 112,439 orders) were read as a part of Order. Here reviews play them —
    their own type, reaching 1,000 of 5,000 orders."""
    draft = {"entities": [], "links": [], "processes": [], "rules": [],
             "parts": [{"entity": "Order", "table": "reviews", "key": "order_id", "name": "reviews",
                        "reason": "an order has reviews"}]}
    faux_llm.set_responses([draft])

    body = explore(client)

    (outcome,) = body["outcomes"]
    assert outcome["outcome"] == "refused"
    assert "reaches only 1,000 of 5,000 Order objects (20%)" in outcome["note"]
    assert "stays its own type" in outcome["note"]
    order = client.get("/object-types/order", params=PARAMS).json()
    assert "reviews" not in {b["name"] for b in order["bindings"]} and order["parts"] == []


def test_a_person_confirms_a_proposal_and_it_keeps_who_proposed_it(door, client, faux_llm):
    faux_llm.set_responses([DRAFT])
    explore(client)
    one = client.post("/ontology/draft/confirm", params=PARAMS,
                      json={"targets": [{"kind": "binding", "entity": "Order", "binding": "payment"}], "actor": "tester"})
    assert one.status_code == 200, one.text
    assert one.json()["confirmed"] == [{"kind": "binding", "entity": "Order", "binding": "payment"}]
    tiers = {p["key"]: p["tier"] for p in one.json()["proposals"]}
    assert (tiers[PAYMENT], tiers[LINES]) == ("confirmed", "proposed")
    payment = next(b for b in client.get("/object-types/order", params=PARAMS).json()["bindings"] if b["name"] == "payment")
    assert (payment["source"], payment["provenance"], payment["usable"]) == ("human", PROVENANCE, True)
    twice = client.post("/ontology/draft/confirm", params=PARAMS,
                        json={"targets": [{"kind": "binding", "entity": "Order", "binding": "payment"}]}).json()
    assert twice["confirmed"] == [] and "bound by a person" in twice["refused"][0]["why"]

    everything = client.post("/ontology/draft/confirm", params=PARAMS, json={"all": True}).json()
    assert len(everything["confirmed"]) == 8 and everything["refused"] == []
    assert everything["counts"] == {"proposed": 0, "confirmed": 9, "released": 0, "withdrawn": 0, "refused": 7}
    declared = client.get("/ontology/processes", params=PARAMS).json()
    assert {(d["origin"], d["provenance"]) for d in [*declared["processes"], *declared["rules"]]} == {("human", PROVENANCE)}
    category = client.get("/object-types/category", params=PARAMS).json()
    assert (category["origin"], category["provenance"]) == ("human", PROVENANCE)
    link = next(link for link in client.get("/object-types/review", params=PARAMS).json()["links"]
                if link["business_name"] == "reviews")
    assert (link["origin"], link["provenance"]) == ("human", PROVENANCE)
    nothing = client.post("/ontology/draft/confirm", params=PARAMS, json={"all": True})
    assert nothing.status_code == 400 and "nothing to confirm" in nothing.json()["detail"]


def test_a_draft_the_model_could_not_give_writes_nothing(door, client, faux_llm):
    faux_llm.set_responses([RuntimeError("the model is down")])
    res = client.post("/ontology/explore", params=PARAMS)
    assert res.status_code == 502 and "nothing was proposed" in res.json()["detail"]
    assert tree() == {} and client.get("/ontology/draft", params=PARAMS).json()["runs"] == []


def test_a_table_already_bound_is_not_offered_again_as_a_data_proposal_whatever_its_qualifier():
    """Found on the live receipt: the builder proposes `luxexperience.order_items` and the explorer binds `order_items`,
    so the panel kept offering 'Bind' for four tables the draft had just bound."""
    from aughor.ontology.models import Binding, Rollup
    from aughor.semantic.object_types import describe_object_type, object_type_map
    graph = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    order = graph.entities["Order"]
    order.bindings = [Binding(name="lines", kind="detail", table="order_items", key="order_id", source="model",
                              rollups={"lines_count": Rollup(column="item_id", agg="count")}, verified=True)]
    order.proposed_bindings = [
        Binding(name="order_items", kind="detail", table="ecommerce.order_items", key="order_id", source="proposed",
                verified=True),
        Binding(name="refunds", kind="detail", table="ecommerce.refunds", key="order_id", source="proposed", verified=True)]
    assert [p["table"] for p in describe_object_type(graph, "order")["proposed_bindings"]] == ["ecommerce.refunds"]
    assert next(t for t in object_type_map(graph)["object_types"] if t["id"] == "Order")["proposed_bindings"] == 1


# ── what the model reads, and what it may send back ────────────────────────────────────────

def test_the_catalogue_is_what_the_build_measured_and_speaks_only_of_this_scope():
    graph = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    glossary = {"tables": {"orders": {"description": "one row per purchase"},
                           "somewhere_else": {"description": "another connection's table"}}}
    text = source_catalogue(graph, glossary=glossary)
    assert text == source_catalogue(graph, glossary=glossary)
    assert "- Order · table orders · key order_id" in text and "order_items.order_id → orders.order_id" in text
    assert "- orders: one row per purchase" in text and "somewhere_else" not in text
    assert "ALREADY DECLARED — do not propose these again\n- nothing yet" in text


def test_a_list_a_local_model_sent_as_a_string_is_read_back():
    said = BusinessDraft.model_validate({"parts": json.dumps(DRAFT["parts"]), "links": json.dumps(DRAFT["links"]),
                                         "entities": None})
    assert (len(said.parts), len(said.links), said.entities) == (6, 3, [])
    assert said.parts[0].rollups[0].agg == "SUM"                      # read as said; checked when it is measured


def test_the_binding_that_answered_is_recorded_not_merely_the_one_asked(faux_llm):
    from aughor.llm.provider import answered_by, get_provider
    faux_llm.set_responses([{"entities": [], "parts": [], "links": []}])
    before = answered_by()
    get_provider("coder").complete("system", "user", BusinessDraft)
    after = answered_by()
    assert after is not before and after == ("faux", "faux-coder", False)


# ── the falsifier: how the tables group ────────────────────────────────────────────────────

REFERENCE = {"Order": ["order_items", "orders", "payments"], "Customer": ["customers", "tickets"],
             "Product": ["products"]}


def test_the_grouping_comparison_names_a_fusion_as_what_keeps_a_draft_from_shipping_default_on():
    same = compare_groupings({"Ord": ["orders", "order_items", "payments"], "Cust": ["tickets", "customers"],
                              "Prod": ["products"]}, REFERENCE)
    assert (same["matched"], same["fusions"], same["splits"], same["ships_default_on"]) == (
        ["Customer", "Order", "Product"], [], [], True)
    assert same["pair_precision"] == same["pair_recall"] == 1.0

    fused = compare_groupings({"Order": ["orders", "order_items", "payments", "customers"], "Ticket": ["tickets"],
                               "Product": ["products"]}, REFERENCE)
    assert fused["fusions"] == [{"draft": "Order", "tables": ["customers", "order_items", "orders", "payments"],
                                 "fuses": ["Customer", "Order"]}]
    assert fused["splits"] == [{"reference": "Customer", "tables": ["customers", "tickets"], "into": ["Order", "Ticket"]}]
    assert (fused["matched"], fused["ships_default_on"]) == (["Product"], False)

    split = compare_groupings({"Order": ["orders"], "OrderItem": ["order_items"], "Payment": ["payments"],
                               "Customer": ["customers", "tickets"], "Product": ["products"], "Date": ["dim_date"]},
                              REFERENCE)
    assert split["fusions"] == [] and split["ships_default_on"] is True
    assert [s["reference"] for s in split["splits"]] == ["Order"] and split["only_in_draft"] == ["dim_date"]
    assert split["pair_precision"] == 1.0 and split["pair_recall"] == 0.25


WAREHOUSES = """
CREATE TABLE ecommerce.warehouses AS
SELECT printf('W%02d', i) AS warehouse_id, 'Depot ' || i AS warehouse_name FROM range(1, 6) t(i);
CREATE TABLE ecommerce.shipments AS
SELECT printf('S%04d', i) AS shipment_id, 'Depot ' || (1 + i % 5) AS warehouse FROM range(1, 41) t(i);
CREATE TABLE ecommerce.pickups AS
SELECT printf('K%03d', i) AS pickup_id, 'Dock ' || (1 + i % 5) AS depot FROM range(1, 21) t(i);
"""
SHIPS_FROM = "link:Shipment.warehouse=Warehouse.warehouse_id"
COLLECTED_AT = "link:Pickup.depot=Warehouse.warehouse_id"


def test_a_link_whose_keys_never_meet_is_counted_again_on_the_name_its_target_is_known_by(door, client, faux_llm,
                                                                                         tmp_path):
    """The live receipt's mistake: shipments carry the warehouse's NAME, and the link was proposed on its id — its keys
    never met. The explorer now counts it once more on the column the target is known by, when that column is measured
    to name one object per row, and writes it only if its keys meet there; a second run finds it already joined."""
    with duckdb.connect(str(tmp_path / "samples.duckdb")) as wh:
        wh.execute(WAREHOUSES)
    for spec in ({"id": "Warehouse", "display_name": "Warehouse", "backing": {"table": "warehouses", "primary_key": "warehouse_id"}},
                 {"id": "Shipment", "display_name": "Shipment", "backing": {"table": "shipments", "primary_key": "shipment_id"}},
                 {"id": "Pickup", "display_name": "Pickup", "backing": {"table": "pickups", "primary_key": "pickup_id"}}):
        assert client.post("/ontology/entities", params=PARAMS, json=spec).status_code == 200
    assert client.put("/ontology/entities/Warehouse", params=PARAMS,
                      json={"display_property": "warehouse_name"}).status_code == 200
    proposal = {**DRAFT, "entities": [], "parts": [], "processes": [], "rules": [], "links": [
        {"from_entity": "Shipment", "to_entity": "Warehouse", "verb": "ships_from", "from_column": "warehouse",
         "to_column": "warehouse_id"},
        {"from_entity": "Pickup", "to_entity": "Warehouse", "verb": "collected_at", "from_column": "depot",
         "to_column": "warehouse_id"}]}
    faux_llm.set_responses([proposal, proposal, proposal])

    unmeasured = {o["key"]: o for o in explore(client)["outcomes"]}[SHIPS_FROM]
    assert unmeasured["outcome"] == "refused" and "keys never meet" in unmeasured["note"]   # a name not yet measured

    assert client.post("/ontology/measure", params=PARAMS).status_code == 200
    second = {o["key"]: o for o in explore(client)["outcomes"]}
    written = second[SHIPS_FROM]
    # counted again on the name too, a column that holds neither the key nor the name still meets nothing: refused
    assert second[COLLECTED_AT]["outcome"] == "refused" and "keys never meet" in second[COLLECTED_AT]["note"]
    assert written["outcome"] == "written", written
    assert "holds the name Warehouse is known by" in written["note"] and "warehouse_name" in written["note"]
    link = next(l for l in client.get("/object-types/shipment", params=PARAMS).json()["links"]
                if l["business_name"] == "ships_from")
    assert (link["origin"], link["traversable"]) == ("model", True)
    counted = client.post("/objects/query", params=PARAMS, json={
        "object_type": "shipment", "by": ["ships_from.warehouse_id"], "measures": [{"agg": "count"}]}).json()
    assert counted["path"] == "compiled", counted
    with duckdb.connect(str(tmp_path / "samples.duckdb")) as wh:
        expected = wh.execute("SELECT w.warehouse_id, COUNT(*) FROM ecommerce.shipments s JOIN ecommerce.warehouses w "
                              "ON w.warehouse_name = s.warehouse GROUP BY 1").fetchall()
    assert sorted((str(r[0]), int(r[1])) for r in counted["rows"]) == sorted((str(k), int(n)) for k, n in expected)

    again = {o["key"]: o for o in explore(client)["outcomes"]}[SHIPS_FROM]
    assert again["outcome"] == "already"



# ── 2026-09-22 — ON-7b's next slice: the explorer names the builder's found links ──────────────────────────────────
# A found link had no name of its own, and the explorer left it unnamed on purpose while a name carried no origin — a
# model's name would have read as a person's. Now a name carries `name_origin`, the explorer proposes names for found
# links by their [id], each is PROPOSED until a person confirms it, a withdrawn name is not proposed again, and the
# person's naming door MERGES into the override (it used to replace a declared link's file with just the name).

def _order_customer_link() -> str:
    graph = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    return next(r.id for r in graph.relationships.values()
                if r.origin == "join_map" and {r.from_entity, r.to_entity} == {"Order", "Customer"})


def _link_row(client, type_id: str, rel_id: str) -> dict:
    return next(l for l in client.get(f"/object-types/{type_id}", params=PARAMS).json()["links"]
                if l["relationship"] == rel_id)


def test_the_explorer_names_a_found_link_and_a_person_confirms_it(door, client, faux_llm):
    rel_id = _order_customer_link()
    draft = {**DRAFT, "link_names": [
        {"link": f"[{rel_id}]", "name": "Placed By", "reason": "an order is placed by its customer"},
        {"link": "no_such_link", "name": "whatever", "reason": "a mistake"},
    ]}
    faux_llm.set_responses([draft])
    rows = {o["key"]: o for o in explore(client)["outcomes"]}
    assert rows[f"link_name:{rel_id}"]["outcome"] == "written"
    assert rows["link_name:no_such_link"]["outcome"] == "refused" and "[id]" in rows["link_name:no_such_link"]["note"]
    link = _link_row(client, "order", rel_id)
    assert (link["business_name"], link["business_name_source"]) == ("placed_by", "model")
    tiers = {p["key"]: p["tier"] for p in client.get("/ontology/draft", params=PARAMS).json()["proposals"]}
    assert tiers[f"link_name:{rel_id}"] == "proposed"

    one = client.post("/ontology/draft/confirm", params=PARAMS,
                      json={"targets": [{"kind": "link_name", "relationship": rel_id}], "actor": "tester"})
    assert one.status_code == 200, one.text
    assert one.json()["confirmed"] == [{"kind": "link_name", "relationship": rel_id}]
    assert _link_row(client, "order", rel_id)["business_name_source"] == "human"
    twice = client.post("/ontology/draft/confirm", params=PARAMS,
                        json={"targets": [{"kind": "link_name", "relationship": rel_id}]}).json()
    assert twice["confirmed"] == [] and "named by a person" in twice["refused"][0]["why"]

    faux_llm.set_responses([draft])
    again = {o["key"]: o["outcome"] for o in explore(client)["outcomes"]}
    assert again[f"link_name:{rel_id}"] == "already"                    # a second run writes nothing twice


def test_a_withdrawn_link_name_is_not_proposed_again(door, client, faux_llm):
    rel_id = _order_customer_link()
    draft = {**DRAFT, "link_names": [{"link": rel_id, "name": "placed_by", "reason": "r"}]}
    faux_llm.set_responses([draft])
    explore(client)
    cleared = client.put(f"/ontology/links/{rel_id}", params=PARAMS, json={"name": ""})
    assert cleared.status_code == 200, cleared.text
    assert _link_row(client, "order", rel_id)["business_name_source"] != "model"
    tiers = {p["key"]: p["tier"] for p in client.get("/ontology/draft", params=PARAMS).json()["proposals"]}
    assert tiers[f"link_name:{rel_id}"] == "withdrawn"
    faux_llm.set_responses([draft])
    rows = {o["key"]: o for o in explore(client)["outcomes"]}
    assert rows[f"link_name:{rel_id}"]["outcome"] == "withdrawn"
    assert "not proposed again" in rows[f"link_name:{rel_id}"]["note"]


def test_the_persons_naming_door_keeps_a_declared_links_declaration(door, client):
    """The door used to replace the override file with `{name}`: naming a declared link erased its declaration."""
    spec = {"from_entity": "Review", "to_entity": "Order", "name": "reviews", "from_column": "order_id",
            "to_column": "order_id"}
    declared = client.post("/ontology/links", params=PARAMS, json=spec)
    assert declared.status_code == 200, declared.text
    rel_id = "Review_reviews_Order"                                   # link_id: <from>_<name>_<to>
    renamed = client.put(f"/ontology/links/{rel_id}", params=PARAMS, json={"name": "is_about"})
    assert renamed.status_code == 200, renamed.text
    link = _link_row(client, "review", rel_id)
    assert (link["business_name"], link["business_name_source"], link["origin"]) == ("is_about", "human", "human")


def test_two_model_links_between_one_pair_of_types_no_longer_collide_on_the_reverse_name(door, client, faux_llm):
    draft = {**DRAFT, "links": [
        {"from_entity": "Review", "to_entity": "Order", "verb": "reviews", "from_column": "order_id",
         "to_column": "order_id", "reason": "a review is about an order"},
        {"from_entity": "Review", "to_entity": "Order", "verb": "written_by_buyer_of", "from_column": "customer_id",
         "to_column": "customer_id", "reason": "the reviewer bought"},
    ]}
    faux_llm.set_responses([draft])
    rows = {o["key"]: o for o in explore(client)["outcomes"]}
    first, second = rows["link:Order.order_id=Review.order_id"], rows["link:Order.customer_id=Review.customer_id"]
    assert first["outcome"] == "written", first
    assert second["outcome"] == "written", second
    rels = client.get("/ontology/relationships", params=PARAMS).json()
    reverse = {r["id"]: r["reverse_api_name"] for r in rels.values() if r.get("origin") == "model"}
    assert reverse["Review_reviews_Order"] == "order_to_review"
    assert reverse["Review_written_by_buyer_of_Order"] == "order_to_review_by_customer_id"


# ── 2026-09-22 — a person can delink from the UI: a found link and a builder-found binding are WITHDRAWABLE ──────
# A found link was "named, never deleted" and a builder binding could only be unbound if a person had bound it — so a
# join the builder guessed wrong, or a table it read under the wrong type, could not be undone from the panel. Both
# withdrawals are now recorded on the overrides (representable, restorable), the served graph leaves them out, and the
# type detail lists them with a door back.

def test_a_found_link_is_withdrawn_and_restored_over_http(door, client):
    rel_id = _order_customer_link()
    assert rel_id in client.get("/ontology/relationships", params=PARAMS).json()
    gone = client.delete(f"/ontology/links/{rel_id}", params=PARAMS)
    assert gone.status_code == 200 and gone.json()["withdrawn"] is True
    assert rel_id not in client.get("/ontology/relationships", params=PARAMS).json()      # the compiler cannot follow it
    order = client.get("/object-types/order", params=PARAMS).json()
    assert rel_id not in [l["relationship"] for l in order["links"]]
    assert [w["relationship"] for w in order["withdrawn"]["links"]] == [rel_id]
    assert client.post(f"/ontology/links/{rel_id}/restore", params=PARAMS).status_code == 200
    assert rel_id in client.get("/ontology/relationships", params=PARAMS).json()
    assert client.get("/object-types/order", params=PARAMS).json()["withdrawn"] == {"bindings": [], "links": []}
    assert client.post(f"/ontology/links/{rel_id}/restore", params=PARAMS).status_code == 404
    assert client.delete("/ontology/links/no_such_link", params=PARAMS).status_code == 404


def test_a_builder_found_binding_is_withdrawn_and_restored_over_http(door, client):
    from aughor.ontology import store as ST
    from aughor.ontology.models import Binding
    graph = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    graph.entities["Order"].bindings.append(Binding(name="lines", kind="detail", table="order_items", key="order_id",
                                                     source="proposed", verified=True))   # the data's, not a person's
    ST.save_ontology(CONN, "ecommerce", "fp", graph)
    names = lambda: [b["name"] for b in client.get("/object-types/order", params=PARAMS).json()["bindings"]]
    assert "lines" in names()
    backing = client.delete("/ontology/entities/Order/bindings/orders", params=PARAMS)
    assert backing.status_code in (400, 404)                                 # the backing is not a binding to withdraw
    gone = client.delete("/ontology/entities/Order/bindings/lines", params=PARAMS)
    assert gone.status_code == 200 and gone.json()["withdrawn"] is True
    assert "lines" not in names()
    assert client.get("/object-types/order", params=PARAMS).json()["withdrawn"]["bindings"] == ["lines"]
    assert client.post("/ontology/entities/Order/bindings/lines/restore", params=PARAMS).status_code == 200
    assert "lines" in names()
    assert client.post("/ontology/entities/Order/bindings/lines/restore", params=PARAMS).status_code == 404
    assert client.delete("/ontology/entities/Order/bindings/nothing", params=PARAMS).status_code == 404


# ── PENDING item 20 — the run is robust to its own failures ─────────────────────────────────────────────────────────

def test_an_unreadable_record_refuses_the_run_before_the_model_call(door, client, faux_llm):
    """The record holds what people withdrew. Read as empty, a run would propose every withdrawal again, and saving
    that empty record would erase them for good — so the run is refused, and nothing writes over the record."""
    faux_llm.set_responses([DRAFT])
    path = DR._path(CONN, "ecommerce")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("runs: [unclosed\n")

    res = client.post("/ontology/explore", params=PARAMS)

    assert res.status_code == 409 and "cannot be read" in res.json()["detail"]
    assert not faux_llm.calls()                                          # the model call was never spent
    assert path.read_text() == "runs: [unclosed\n"
    with pytest.raises(DR.DraftUnreadable):
        DR.save_draft(DR.OntologyDraft(connection_id=CONN, schema_name="ecommerce"))


def test_a_second_exploration_of_a_scope_waits_for_the_first(door, client, faux_llm):
    from aughor.routers.ontology import _exploration_lock
    faux_llm.set_responses([DRAFT])
    lock = _exploration_lock(CONN, "ecommerce")
    assert lock.acquire(blocking=False)             # a run already in flight — the birth rite's, say
    try:
        res = client.post("/ontology/explore", params=PARAMS)
    finally:
        lock.release()
    assert res.status_code == 409 and "already running" in res.json()["detail"]
    assert not faux_llm.calls()
    explore(client)                                 # and once it finishes, the next one runs


def test_a_run_that_fails_part_way_is_recorded_so_a_restart_does_not_pay_again(door, client, faux_llm, monkeypatch):
    import aughor.ontology.explorer as EX
    faux_llm.set_responses([DRAFT])

    def _dies(*_a, **_k):
        raise RuntimeError("the warehouse went away mid-run")
    monkeypatch.setattr(EX, "apply_draft", _dies)

    res = client.post("/ontology/explore", params=PARAMS)

    assert res.status_code == 500 and "stopped part-way" in res.json()["detail"]
    (run,) = DR.load_draft(CONN, "ecommerce").runs
    assert "the warehouse went away mid-run" in run.error
    # the birth rite skips a scope with any recorded run — exactly the check that never fired before
    from aughor.routers._shared import run_business_terms
    seen: list = []
    monkeypatch.setattr("aughor.licensing.resolver.has_capability", lambda cap, conn_id=None: True)
    monkeypatch.setattr("aughor.routers.ontology.resolve_effective_schema", lambda conn, schema=None: "ecommerce")
    assert run_business_terms(CONN, "ecommerce", lambda *a, **k: seen.append(a)) == "skipped"
