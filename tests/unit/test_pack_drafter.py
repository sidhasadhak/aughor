"""An industry pack guides the ontology; the data decides what exists (2026-10-10).

The user's rule: a pack lays out how an industry is usually shaped, and the objects built are the ones the
connection's tables hold — a business whose head office is its warehouse gets no Warehouse because a pack says so.
These hold the pack drafter (`aughor/packs/drafter.py`) and its door to that rule, on the real samples and theLook
graphs: what the data holds is grouped, named and staged the industry's way; what it does not hold is never proposed
and never mentioned; every proposal goes through the explorer's own path with the pack's provenance, never a model's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aughor.ontology import drafts as DR
from aughor.ontology import overrides as OV
from aughor.ontology.explorer import Answerer
from aughor.ontology.models import KineticAction, OntologyEntity, OntologyGraph
from aughor.packs.drafter import pack_draft
from aughor.packs.ontology_map import apply_core_claims, match_objects, resolve_ontology

REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
THELOOK = REPO / "evals" / "ablation_thelook_business_ontology.json"
ABSENT = ("Payment", "Shipment", "Warehouse", "InventoryLot", "Refund", "Promotion", "Cart", "Supplier", "Brand", "SKU")


def _graph(path: Path) -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(path.read_text()))


def _core():
    po = resolve_ontology("core-ecommerce")
    assert po is not None
    return po


def _said(draft) -> str:
    return json.dumps(draft.model_dump())


def test_the_core_pack_lays_out_patterns_not_objects_to_make():
    po = _core()
    assert 10 <= len(po.objects) <= 20
    objects = {o.name for o in po.objects}
    assert {o.name: o.parts for o in po.objects if o.parts} == {"Order": ["OrderItem"], "Cart": ["CartItem"]}
    assert all(lk.verb and lk.reverse_verb for lk in po.links), "every link is read both ways"
    assert all({lk.from_object, lk.to_object} <= objects for lk in po.links)
    assert {a.object for a in po.actions} <= objects and any(a.name == "Ship an order" for a in po.actions)
    # a child pack replaces by name: fashion's order_to_delivery, with approval and its promises, wins over the core's
    fashion = resolve_ontology("fashion-ecommerce")
    [process] = fashion.processes
    assert [s.name for s in process.stages] == ["placed", "approved", "dispatched", "delivered"]


def test_on_the_samples_warehouse_what_it_holds_is_shaped_the_industry_way():
    draft = pack_draft(_graph(SAMPLES), _core(), "core-ecommerce")
    assert draft.entities == []                                   # every object comes from a table, never the pack
    assert [(p.entity, p.table, p.key) for p in draft.parts] == [("Order", "order_items", "order_id")]
    names = {n.link: n.name for n in draft.link_names}
    # the builder oriented this one Customer → Order, so the reverse verb names it
    assert names["Customer_RELATES_TO_Order"] == "customer_places_order"
    assert names["OrderItem_RELATES_TO_Order"] == "order_item_belongs_to_order"
    assert names["OrderItem_RELATES_TO_Product"] == "order_item_references_product"
    assert names["Customer_RELATES_TO_Review"] == "customer_writes_review"
    assert "OrderItem_RELATES_TO_Review" not in names              # no pattern joins a line to a review
    # reviews carry order_id and nothing joined them to orders: proposed on the pack's key, to be counted
    assert [(lk.from_entity, lk.to_entity, lk.from_column, lk.to_column) for lk in draft.links] == [
        ("Review", "Order", "order_id", "order_id")]
    [process] = draft.processes
    assert (process.id, process.entity) == ("order_to_delivery", "Order")
    assert [(s.name, s.timestamp) for s in process.stages] == [
        ("placed", "order_date"), ("shipped", "shipped_at"), ("delivered", "delivered_at")]


def test_an_object_the_data_does_not_hold_is_never_proposed_or_mentioned():
    for path in (SAMPLES, THELOOK):
        said = _said(pack_draft(_graph(path), _core(), "core-ecommerce"))
        matched = match_objects(_core(), _graph(path))
        for name in ABSENT:
            if name not in matched:
                assert name not in said, f"{path.name}: {name} is not in this data, and the draft speaks of it"


def test_orders_with_no_line_table_get_no_part():
    g = _graph(SAMPLES)
    del g.entities["OrderItem"]
    g.relationships = {k: r for k, r in g.relationships.items() if "OrderItem" not in (r.from_entity, r.to_entity)}
    draft = pack_draft(g, _core(), "core-ecommerce")
    assert draft.parts == [] and "OrderItem" not in _said(draft)
    assert [p.entity for p in draft.processes] == ["Order"]       # the order itself is still shaped


def test_a_schema_from_another_industry_gets_nothing():
    flights = OntologyGraph(connection_id="c", schema_fingerprint="f", entities={
        "Flight": OntologyEntity(id="Flight", display_name="Flight", source_tables=["flights"], identity_key="flight_id",
                                 grain_verified=True),
        "Airport": OntologyEntity(id="Airport", display_name="Airport", source_tables=["airports"],
                                  identity_key="iata", grain_verified=True)})
    assert pack_draft(flights, _core(), "core-ecommerce").model_dump() == {
        "entities": [], "parts": [], "links": [], "link_names": [], "processes": [], "rules": []}


def test_on_thelook_its_own_words_stay_and_a_person_s_work_is_not_redone():
    g = _graph(THELOOK)
    matched = match_objects(_core(), g)
    # the company's words stay the type names; the pack only recognises them
    assert (matched["Customer"], matched["Warehouse"], matched["InventoryLot"]) == ("User", "DistributionCenter",
                                                                                    "InventoryItem")
    draft = pack_draft(g, _core(), "core-ecommerce")
    names = {n.link: n.name for n in draft.link_names}
    # declared twice on the same two columns is one join: the builder's copy is named
    assert names["Order_RELATES_TO_User"] == "order_placed_by_user"
    assert names["Product_RELATES_TO_DistributionCenter"] == "product_stocked_at_distribution_center"
    assert names["OrderItem_RELATES_TO_InventoryItem"] == "order_item_fulfilled_from_inventory_item"
    # a link only a person declared carries the name its declarer gave it
    assert not any(k.startswith("InventoryItem_stored_at") for k in names)
    assert not any(n.link.startswith(("Order_placed_by", "OrderItem_of_product")) for n in draft.link_names)
    assert any(p.entity == "Order" for p in (g.processes or {}).values())   # theLook declared order_fulfilment
    assert draft.processes == []                                   # and a declared process settles it


def test_actions_are_offered_only_on_objects_the_data_holds_and_settled_once_declared():
    g = _graph(SAMPLES)
    report = apply_core_claims(g, _core(), "core-ecommerce")
    actions = [c for c in report.claims if c.kind == "action"]
    assert {c.subject.split(":")[0] for c in actions} <= {"Order", "Customer", "Product", "Review"}
    assert all(c.tier == "expected" and "action designer" in c.note for c in actions)
    assert "Order: Ship an order" in {c.subject for c in actions}
    assert not any(c.subject.startswith(("Payment", "Shipment", "Refund")) for c in actions)
    g.kinetic_actions["ship_an_order"] = KineticAction(id="ship_an_order", display_name="Ship an order", entity="Order",
                                                       kind="annotate")
    again = {c.subject: c.tier for c in apply_core_claims(g, _core(), "core-ecommerce").claims if c.kind == "action"}
    assert again["Order: Ship an order"] == "human"


def test_an_offered_action_is_not_booked_into_the_record_as_a_claim_about_the_business(monkeypatch):
    from aughor.record import writers
    booked = []
    monkeypatch.setattr(writers._claims, "book", lambda claim, **kw: booked.append(kw["key"]))
    report = apply_core_claims(_graph(SAMPLES), _core(), "core-ecommerce")
    writers.book_pack_claims(report, connection_id="c1", schema_name="shop")
    assert booked and not any("-action-" in key or ":action:" in key for key in booked)
    assert len(booked) == len([c for c in report.claims if c.kind != "action"])


def test_a_pack_run_is_named_for_the_pack_never_for_a_model():
    assert Answerer(backend="pack", model="core-ecommerce", source="pack", version="2").provenance == \
        "pack:core-ecommerce@2"
    assert Answerer(backend="ollama", model="m").provenance.startswith("model:m@")


# ── the door, on the seeded samples warehouse ─────────────────────────────────────────────────

CONN = "pack-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce", "pack": "core-ecommerce"}


@pytest.fixture(autouse=True)
def _isolated_trees(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_DRAFT_ROOT", tmp_path / "ontology_overrides_draft")
    monkeypatch.setattr(DR, "_ROOT", tmp_path / "ontology_drafts")


@pytest.fixture
def door(tmp_path, monkeypatch):
    import aughor.db.connection as C
    from aughor.db.connection import open_connection
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore
    from tests.unit.test_object_bindings import GRAPH, seed

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology(CONN, "ecommerce", "fp", OntologyGraph.model_validate(json.loads(GRAPH.read_text())))
    path = tmp_path / "samples.duckdb"
    seed(path)
    from aughor.routers._shared import invalidate_schema_cache
    invalidate_schema_cache(CONN)               # the served graph is cached per connection, across tests
    monkeypatch.setattr(C, "open_connection_for_with_schema",
                        lambda *_a, **_k: open_connection("duckdb", str(path), schema_name="ecommerce",
                                                          connection_id=CONN))


def test_the_door_writes_the_pack_s_structure_as_proposals_with_the_pack_s_provenance(door, client):
    res = client.post("/ontology/explore/pack", params=PARAMS)
    assert res.status_code == 200, res.text
    body = res.json()
    written = {(o["kind"], o["key"]) for o in body["outcomes"] if o["outcome"] == "written"}
    assert ("part", "part:Order:order_items") in written
    assert any(kind == "link_name" for kind, _ in written)
    assert body["run"]["provenance"] == "pack:core-ecommerce@2" and body["run"]["backend"] == "pack"
    proposals = DR.load_draft(CONN, "ecommerce").proposals
    assert proposals and all(p.provenance == "pack:core-ecommerce@2" for p in proposals.values())
    assert any(a["subject"] == "Order: Ship an order" for a in body["suggested_actions"])
    # a second run writes nothing twice
    again = client.post("/ontology/explore/pack", params=PARAMS).json()
    assert not [o for o in again["outcomes"] if o["outcome"] == "written"]


def test_the_door_refuses_a_pack_with_no_map(door, client):
    res = client.post("/ontology/explore/pack", params={**PARAMS, "pack": "no-such-pack"})
    assert res.status_code == 404 and "no pack" in res.json()["detail"]


# ── the birth rite: a deployed pack shapes first, and the explorer still runs ──────────────────

@pytest.mark.parametrize("bound", [[], ["core-ecommerce"]], ids=["nothing bound", "a draft pack bound"])
def test_with_no_pack_deployed_the_rite_is_exactly_what_it_was(monkeypatch, bound):
    # deployed = bound AND active: core-ecommerce ships as a draft, so binding it alone runs nothing
    from aughor.packs import bindings
    from aughor.routers import _shared
    monkeypatch.setattr(bindings, "packs_bound_on", lambda conn, schema="": list(bound))
    seen = []
    assert _shared.run_pack_structure("c1", "shop", lambda *a, **k: seen.append(a)) == "none"
    assert seen == []


def test_a_pack_run_on_the_scope_does_not_stop_the_business_explorer(monkeypatch):
    from types import SimpleNamespace

    import aughor.licensing.resolver as resolver
    import aughor.ontology.drafts as drafts
    import aughor.ontology.store as ontology_store
    import aughor.routers.ontology as ontology
    from aughor.routers import _shared
    calls = []
    monkeypatch.setattr(ontology, "explore_ontology",
                        lambda connection_id, schema_name=None: calls.append(connection_id) or {"run": {"id": "r"}})
    monkeypatch.setattr(resolver, "has_capability", lambda cap, conn_id=None: True)
    monkeypatch.setattr(ontology_store, "load_latest_ontology", lambda conn, schema=None: object())
    monkeypatch.setattr(drafts, "load_draft",
                        lambda conn, schema: SimpleNamespace(runs=[SimpleNamespace(provenance="pack:core-ecommerce@2")]))
    assert _shared.run_business_terms("c1", "shop", lambda *a, **k: None) == "done" and calls == ["c1"]
