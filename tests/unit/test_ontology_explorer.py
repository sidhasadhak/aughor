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

import pytest
import yaml

from aughor.db.connection import open_connection
from aughor.ontology import drafts as DR
from aughor.ontology import overrides as OV
from aughor.ontology.explorer import BusinessDraft, compare_groupings, entity_key, source_catalogue
from aughor.ontology.models import OntologyGraph
from tests.unit.test_object_bindings import GRAPH, ints, seed

CONN = "explorer-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}
PROVENANCE = "model:faux-coder@1"

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
}
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

    run = body["run"]
    assert (run["written"], run["refused"], run["already"], run["withdrawn"]) == (6, 4, 1, 0)
    assert (run["provenance"], run["backend"], run["fallback"]) == (PROVENANCE, "faux", False)
    assert run["said"] == {"entities": 2, "parts": 6, "links": 3}
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
    [part] = order["parts"]
    assert (part["object_type"], part["binding"], part["origin"], part["provenance"]) == (
        "order_item", "lines", "model", PROVENANCE)

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

    view = client.get("/ontology/draft", params=PARAMS).json()
    assert view["counts"] == {"proposed": 6, "confirmed": 0, "released": 0, "withdrawn": 0, "refused": 4}
    assert view["grouping"]["Order"] == ["order_events", "order_items", "orders", "payments", "refunds"]
    assert "OrderItem" not in view["grouping"] and [r["id"] for r in view["runs"]] == [run["id"]]


def test_a_second_run_writes_nothing_twice_and_a_withdrawn_proposal_is_not_proposed_again(door, client, faux_llm):
    faux_llm.set_responses([DRAFT, DRAFT, DRAFT])
    explore(client)
    before = tree()
    again = explore(client)["run"]
    assert (again["written"], again["already"], again["refused"]) == (0, 7, 4)
    assert tree() == before                                            # not one override file touched

    assert client.delete("/ontology/entities/Category", params=PARAMS).status_code == 200
    assert client.delete("/ontology/entities/Order/bindings/refunds", params=PARAMS).status_code == 200
    assert client.put("/ontology/entities/OrderItem", params=PARAMS, json={"absorbed_into": ""}).status_code == 200
    tiers = {p["key"]: p["tier"] for p in client.get("/ontology/draft", params=PARAMS).json()["proposals"]}
    assert (tiers[CATEGORY], tiers[REFUNDS], tiers[LINES], tiers[PAYMENT]) == ("withdrawn", "withdrawn", "released", "proposed")

    third = explore(client)
    outcome = {o["key"]: o for o in third["outcomes"]}
    assert {k: outcome[k]["outcome"] for k in (CATEGORY, REFUNDS, LINES)} == dict.fromkeys((CATEGORY, REFUNDS, LINES),
                                                                                         "withdrawn")
    assert third["run"]["written"] == 0 and "withdrew" in outcome[CATEGORY]["note"] and "released" in outcome[LINES]["note"]
    assert "category" not in {t["object_type"] for t in client.get("/object-types", params=PARAMS).json()["object_types"]}
    order = client.get("/object-types/order", params=PARAMS).json()
    assert "refunds" not in {b["name"] for b in order["bindings"]} and order["parts"] == []


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
    assert len(everything["confirmed"]) == 5 and everything["refused"] == []
    assert everything["counts"] == {"proposed": 0, "confirmed": 6, "released": 0, "withdrawn": 0, "refused": 4}
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
