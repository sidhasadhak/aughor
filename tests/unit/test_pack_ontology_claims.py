"""ON-0a part 3: a pack's industry map is a set of claims the builder measures.

Pins the `ontology.yaml` part, the `extends` chain, deterministic matching, the claim tiers
on the committed LuxExperience graph (with and without data), the end-state names moving
out of code into the core pack, and the measure door taking a pack id.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from aughor.db.connection import open_connection
from aughor.ontology.lifecycle import default_end_state_names
from aughor.ontology.models import OntologyGraph
from aughor.packs.ontology_map import (
    apply_core_claims, end_state_names_for_pack, load_pack_by_id, match_objects, resolve_ontology,
)

REPO = Path(__file__).resolve().parents[2]
LUX_MEASURED = REPO / "evals" / "ablation_luxexperience_ontology_measured.json"


def _lux() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(LUX_MEASURED.read_text()))


def test_the_core_pack_carries_the_four_parts_and_no_alias_values():
    pack = load_pack_by_id("core-ecommerce")
    assert pack is not None and pack.ontology is not None
    po = pack.ontology
    assert {o.name for o in po.objects} >= {"Customer", "Order", "OrderItem", "Product", "Payment", "Shipment", "Return"}
    assert 10 <= len(po.objects) <= 20                      # a map, not a reference model
    assert all(lk.cardinality in ("1:1", "1:N", "N:1", "N:N") for lk in po.links)
    assert {lc.object for lc in po.lifecycles} >= {"Order", "Payment"}
    assert all(a.values == {} for a in po.aliases)           # the core declares, the business fills


def test_extends_folds_the_parent_in_and_the_child_adds_without_replacing():
    core = resolve_ontology("core-ecommerce")
    fashion = resolve_ontology("fashion-ecommerce")
    assert {o.name for o in core.objects} < {o.name for o in fashion.objects}
    assert {o.name for o in fashion.objects} - {o.name for o in core.objects} == {"Brand", "Season", "Collection", "Variant"}
    assert len(fashion.links) == len(core.links) + 4
    assert [lc.object for lc in fashion.lifecycles] == [lc.object for lc in core.lifecycles]
    assert resolve_ontology("no-such-pack") is None


def test_end_state_names_live_in_the_pack_and_the_lifecycle_module_reads_them():
    names = end_state_names_for_pack("core-ecommerce")
    assert {"refunded", "returned", "rejected", "delivered"} <= names
    assert "captured" not in names                            # a refund leaves it: not an end state
    assert default_end_state_names() == frozenset(n.lower() for n in names)


def test_matching_is_by_name_and_alias_and_table_stem_and_never_double_books():
    po = resolve_ontology("fashion-ecommerce")
    matched = match_objects(po, _lux())
    assert matched["OrderItem"] == "OrderItem" and matched["Return"] == "Return" and matched["Brand"] == "Brand"
    assert "Review" not in matched and "Seller" not in matched and "Category" not in matched
    assert len(set(matched.values())) == len(matched)


def test_claims_on_the_measured_luxexperience_graph_without_data():
    g = _lux()
    report = apply_core_claims(g, resolve_ontology("core-ecommerce"), "core-ecommerce")
    by = {(c.kind, c.subject): c for c in report.claims}
    # a link the builder found, measured, agreeing with the core
    assert by[("link", "OrderItem → Order")].tier == "measured-true" and by[("link", "OrderItem → Order")].measured == "N:1"
    # stored the other way round (products → order_items 1:N) — oriented before comparing
    assert by[("link", "OrderItem → Product")].tier == "measured-true"
    # the builder never found orders.customer_id → customers: the core expected it, honestly
    assert by[("link", "Order → Customer")].tier == "expected" and "no join found" in by[("link", "Order → Customer")].note
    # the built join between returns and order_items is on order_id, the core expects order_item_id
    assert by[("link", "Return → OrderItem")].tier == "expected" and "the core expects order_item_id" in by[("link", "Return → OrderItem")].note
    # objects present are measured-true, absent ones expected
    assert by[("object", "Order")].tier == "measured-true" and by[("object", "Review")].tier == "expected"
    # lifecycles without a data connection stay expected; an unmarked column is named
    assert by[("lifecycle", "Order")].tier == "expected" and "no lifecycle detected" in by[("lifecycle", "Order")].note
    assert by[("alias", "country")].tier == "expected"
    assert report.by_tier()["measured-false"] == 0
    mine = lambda: [c for c in g.core_claims if c.provenance == "pack:core-ecommerce"]  # noqa: E731
    assert mine() == report.claims                           # recorded on the graph, never rendered
    # re-applying the same pack replaces, never duplicates; another pack's claims stay
    others = [c for c in g.core_claims if c.provenance != "pack:core-ecommerce"]
    apply_core_claims(g, resolve_ontology("core-ecommerce"), "core-ecommerce")
    assert len(mine()) == len(report.claims)
    assert [c for c in g.core_claims if c.provenance != "pack:core-ecommerce"] == others


def test_claims_with_data_measure_the_payment_lifecycle(tmp_path):
    g = _lux()
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE SCHEMA luxexperience;
        CREATE TABLE luxexperience.payments (payment_id INT, status VARCHAR);
        INSERT INTO luxexperience.payments VALUES (1,'captured'), (2,'refunded'), (3,'failed');
    """)
    con.close()
    db = open_connection("duckdb", str(path), connection_id="t")
    try:
        report = apply_core_claims(g, resolve_ontology("core-ecommerce"), "core-ecommerce", db)
    finally:
        db.close()
    by = {c.subject: c for c in report.claims if c.kind == "lifecycle"}
    assert by["Payment.status terminal 'failed'"].tier == "measured-true"
    assert by["Payment.status terminal 'refunded'"].tier == "expected"
    assert "NOT in the built terminal set" in by["Payment.status terminal 'refunded'"].note


def test_the_measure_door_takes_a_pack_id(tmp_path, monkeypatch, client):
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore
    import aughor.db.connection as C
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    ST.save_ontology("914df862", "luxexperience", "fp", _lux())
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA luxexperience; CREATE TABLE luxexperience.payments (payment_id INT, status VARCHAR);"
                "INSERT INTO luxexperience.payments VALUES (1,'captured'), (2,'refunded'), (3,'failed');")
    con.close()
    monkeypatch.setattr(C, "open_connection_for_with_schema",
                        lambda *_a, **_k: open_connection("duckdb", str(path), connection_id="t"))
    r = client.post("/ontology/measure", params={"connection_id": "914df862", "schema_name": "luxexperience", "pack": "core-ecommerce"})
    assert r.status_code == 200, r.text
    claims = r.json()["claims"]
    assert claims["pack"] == "core-ecommerce" and claims["by_tier"]["measured-true"] >= 8
    assert any(c["subject"] == "Payment.status terminal 'failed'" and c["tier"] == "measured-true" for c in claims["claims"])
    saved = ST.load_ontology("914df862", "luxexperience", "fp")
    assert any(c.provenance == "pack:core-ecommerce" for c in saved.core_claims)
    r2 = client.post("/ontology/measure", params={"connection_id": "914df862", "schema_name": "luxexperience"})
    assert r2.status_code == 200 and r2.json()["claims"] is None   # nothing deployed, no pack named


# ── ON-9: processes and rules, expected by the map and settled by a person ─────────────────────

SAMPLES = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


def _samples() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(SAMPLES.read_text()))


def test_the_fashion_pack_expects_order_to_delivery_with_its_promises_left_to_the_business():
    fashion = resolve_ontology("fashion-ecommerce")
    [process] = fashion.processes
    assert (process.name, process.object, [s.name for s in process.stages]) == (
        "order_to_delivery", "Order", ["placed", "approved", "dispatched", "delivered"])
    promises = [s.promise for s in process.stages if s.promise is not None]
    assert [p.name for p in promises] == ["dispatch", "delivery"] and all(p.within_days is None for p in promises)
    assert [r.name for r in fashion.rules] == ["dach"] and fashion.rules[0].values == []
    assert resolve_ontology("core-ecommerce").processes == []


def test_process_and_rule_claims_match_moments_by_name_and_leave_the_terms_to_the_business():
    report = apply_core_claims(_samples(), resolve_ontology("fashion-ecommerce"), "fashion-ecommerce")
    by = {(c.kind, c.subject): c for c in report.claims}
    assert by[("process", "order_to_delivery · placed")].measured == "Order.order_date"
    assert by[("process", "order_to_delivery · dispatched")].measured == "Order.shipped_at"
    assert by[("process", "order_to_delivery · delivered")].measured == "Order.delivered_at"
    approved = by[("process", "order_to_delivery · approved")]
    assert approved.tier == "expected" and "no moment on Order" in approved.note
    promise = by[("process", "order_to_delivery · dispatched promise")]
    assert (promise.tier, promise.expected) == ("expected", "by a per-object deadline")
    assert "kept per OrderItem" in promise.note
    dach = by[("rule", "dach")]
    assert dach.tier == "expected" and "none of its values" in dach.note


def test_a_declared_process_or_rule_settles_its_claim_as_the_persons():
    from aughor.ontology.models import BusinessRule, Process, ProcessStage
    g = _samples()
    g.processes["order_fulfilment"] = Process(id="order_fulfilment", entity="Order", stages=[
        ProcessStage(name="placed", timestamp="order_date"), ProcessStage(name="shipped", timestamp="shipped_at")],
        note="5,000 Order objects; 2 of 2 stages reached")
    g.rules["dach"] = BusinessRule(id="dach", entity="Customer", kind="value_set", property="country",
                                   values=["DE", "AT", "CH"])
    report = apply_core_claims(g, resolve_ontology("fashion-ecommerce"), "fashion-ecommerce")
    by = {(c.kind, c.subject): c for c in report.claims}
    settled = by[("process", "order_to_delivery")]
    assert (settled.tier, settled.measured) == ("human", "declared as order_fulfilment: placed → shipped")
    assert not any(kind == "process" and subject.startswith("order_to_delivery ·") for kind, subject in by)
    assert (by[("rule", "dach")].tier, by[("rule", "dach")].measured) == ("human", "declared as dach: DE, AT, CH")
