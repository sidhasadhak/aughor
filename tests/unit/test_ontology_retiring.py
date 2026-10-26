"""Arc FA, FA-3 — a declaration marked *retiring*: still served, moving to a successor by a date (ROADMAP §3.60).

The user's word, 2026-10-26: "retiring on <date> — use <successor> instead". Held here: any change to the mark is a
MEANING change, classed before a kind's own rules; the successor must exist and be of the same kind, refused with a
sentence otherwise; the agent's semantic block, the entity's detail and its objects' pages say it; after the date it
still serves and says "past its retiring date"; a refused withdrawal suggests it; a built segment marked retiring is
served exactly as it was built. Off, the door refuses, and the classifier, the block and every page are as before.

Hermetic: the overrides tree, its draft layer and the ledger are per test; the door flow reads the seeded samples
warehouse's graph, as the release suite does.
"""
from __future__ import annotations

import copy
import json
from datetime import date

import pytest

from aughor.ontology import compatibility as COMPAT
from aughor.ontology import overrides as OV
from aughor.ontology import retiring as RT
from aughor.ontology.models import OntologyGraph
from aughor.ontology.overrides import OntologyOverride, apply_overrides, find_override, save_override, viewing
from aughor.ontology.semantic_block import render_semantic_layer
from tests.unit.test_object_bindings import GRAPH
from tests.unit.test_object_processes import FULFILMENT, PARAMS, door  # noqa: F401 — `door` is a fixture

MARK = {"successor": "Customer", "on": "2999-12-01", "note": "merged into customers"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from aughor.kernel.ledger import Ledger
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(OV, "_SEED_ROOT", tmp_path / "seed")
    monkeypatch.setattr(OV, "_DRAFT_ROOT", tmp_path / "ontology_overrides_draft")
    ledger = Ledger(str(tmp_path / "system.db"))
    monkeypatch.setattr(Ledger, "default", classmethod(lambda cls: ledger))
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")
    monkeypatch.setattr("aughor.automations.store.list_automations", lambda *a, **k: [])


def _flags(monkeypatch, *on: str) -> None:
    names = set(on)
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name in names)


@pytest.fixture
def graph() -> OntologyGraph:
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    g.connection_id, g.schema_name = "retiring-t", "ecommerce"
    return g


# ── the catalogue: a mark is a change of meaning, whatever the kind ─────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["entity", "object_set", "process", "rule", "link", "metric", "action", "impact"])
def test_any_change_to_the_mark_is_a_meaning_change(kind):
    base = {"display_name": "Old"}
    marked = {**base, "retiring": MARK}
    assert COMPAT.classify(kind, base, marked)[0] == "MEANING"
    assert COMPAT.classify(kind, marked, base)[0] == "MEANING"
    moved = {**base, "retiring": {**MARK, "on": "2999-12-31"}}
    cls, reasons = COMPAT.classify(kind, marked, moved)
    assert cls == "MEANING" and "2999-12-01" in reasons[0]["why"] and "2999-12-31" in reasons[0]["why"]
    assert not any("does not class it" in r["why"] for r in reasons)          # never an unknown field


def test_a_mark_is_classed_before_the_kinds_own_rules_which_read_the_rest():
    before = {"filter_sql": "a"}
    cls, reasons = COMPAT.classify("object_set", before, {"filter_sql": "b", "retiring": MARK})
    assert cls == "MEANING" and reasons[0]["why"].startswith("it is marked retiring on 2999-12-01")
    assert any("filter sql" in r["why"] for r in reasons)
    backing = {"backing": {"kind": "table", "table": "orders", "primary_key": "id"}}
    moved = {"backing": {"kind": "table", "table": "orders", "primary_key": "order_id"}, "retiring": MARK}
    assert COMPAT.classify("entity", backing, moved)[0] == "ERR"               # a key change still breaks


def test_a_built_element_marked_or_unmarked_is_the_mark_alone_never_an_add_or_a_withdrawal():
    deps = [{"consumer": "automation", "id": "a", "name": "Watch", "how": "reads it"}]
    cls, reasons = COMPAT.classify("object_set", None, {"retiring": MARK})
    assert cls == "MEANING" and len(reasons) == 1 and "it is added" not in reasons[0]["why"]
    cls, reasons = COMPAT.classify("object_set", {"retiring": MARK}, None, dependents=deps)
    assert cls == "MEANING" and "no longer marked retiring" in reasons[0]["why"]
    # a declared element withdrawn while retiring is a withdrawal like any other
    assert COMPAT.classify("rule", {"entity": "Customer", "retiring": MARK}, None, dependents=deps)[0] == "ERR"


# ── what readers are told ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_sentence_and_after_the_day_it_still_serves_and_says_so():
    assert RT.said(MARK, "Customer", today=date(2999, 11, 1)) == "retiring on 2999-12-01 — use Customer instead"
    assert RT.said(MARK, "Customer", today=date(2999, 12, 1)) == "retiring on 2999-12-01 — use Customer instead"
    assert RT.said(MARK, "Customer", today=date(2999, 12, 2)) == \
        "past its retiring date, 2999-12-01 — use Customer instead"


def test_the_semantic_block_says_it_and_off_is_exactly_what_it_was(graph, monkeypatch):
    _flags(monkeypatch)
    before = render_semantic_layer(graph, ["orders"])
    save_override("retiring-t", "ecommerce", OntologyOverride(target_kind="entity", target_id="Order",
                                                              fields={"retiring": MARK}))
    assert render_semantic_layer(graph, ["orders"]) == before                  # off: nothing reads the mark
    _flags(monkeypatch, "ontology.retiring")
    block = render_semantic_layer(graph, ["orders"])
    assert block.startswith(before) and "RETIRING" in block
    assert '"Order" (entity) is retiring on 2999-12-01 — use "Customer" instead (merged into customers)' in block
    assert "RETIRING" not in render_semantic_layer(graph, ["products"])        # scoped to the question's tables


def test_a_built_segment_marked_retiring_is_served_exactly_as_built(graph, monkeypatch):
    _flags(monkeypatch, "ontology.retiring")
    plain, _ = apply_overrides(copy.deepcopy(graph), "retiring-t", "ecommerce")
    save_override("retiring-t", "ecommerce", OntologyOverride(
        target_kind="object_set", target_id="Order::active_orders",
        fields={"retiring": {**MARK, "successor": "Order::delivered_orders"}}))
    marked, report = apply_overrides(copy.deepcopy(graph), "retiring-t", "ecommerce")
    assert marked.entities["Order"].segments == plain.entities["Order"].segments
    assert any(a.startswith("object_set:Order::active_orders") for a in report.applied)
    segments = graph.entities["Order"].segments
    old, new = segments["active_orders"].display_name, segments["delivered_orders"].display_name
    assert f'"{old}" (segment) is retiring on 2999-12-01 — use "{new}" instead' in render_semantic_layer(marked, ["orders"])


def test_a_refused_withdrawal_suggests_retiring_only_while_on(monkeypatch):
    from aughor.ontology.dependents import refusal
    rows = [{"consumer": "automation", "id": "a", "name": "Watch", "how": "reads its promise"}]
    _flags(monkeypatch)
    assert "retiring" not in refusal("process", "order_fulfilment", rows)
    _flags(monkeypatch, "ontology.retiring")
    said = refusal("process", "order_fulfilment", rows)
    assert said.startswith("process 'order_fulfilment' is not withdrawn — 1 thing depends on it")
    assert "Or mark the process retiring — name its successor and a day" in said


def test_the_successor_must_exist_and_be_of_the_same_kind(graph):
    assert RT.problem(graph, "entity", "Order", MARK) == (0, "")
    assert RT.problem(graph, "entity", "Nope", MARK)[0] == 404
    status, why = RT.problem(graph, "entity", "Order", {**MARK, "successor": "Order::active_orders"})
    assert status == 400 and "no entity 'Order::active_orders' on this ontology to use instead" in why
    assert "of the same kind" in why
    assert RT.problem(graph, "object_set", "Order::active_orders", {**MARK, "successor": "Order"})[0] == 400
    assert RT.problem(graph, "object_set", "Order::active_orders",
                      {**MARK, "successor": "Order::delivered_orders"}) == (0, "")
    assert "its own successor" in RT.problem(graph, "entity", "Order", {**MARK, "successor": "Order"})[1]
    assert "not a day" in RT.problem(graph, "entity", "Order", {**MARK, "on": "next month"})[1]
    assert "name the entity to use instead" in RT.problem(graph, "entity", "Order", {**MARK, "successor": ""})[1]


# ── through the doors ──────────────────────────────────────────────────────────────────────────────────────────────

def test_through_the_door_a_mark_waits_in_the_draft_as_a_meaning_change_and_pages_say_it(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release", "ontology.retiring")
    monkeypatch.setattr("aughor.db.registry.get_meta", lambda conn: {"schema_name": "ecommerce"})
    body = {"kind": "entity", "target_id": "Review", **MARK}
    put = client.put("/ontology/retiring", params=PARAMS, json=body)
    assert put.status_code == 200, put.text
    out = put.json()
    assert out["landed"] == "draft" and out["change"]["class"] == "MEANING"
    assert out["retiring"]["said"] == "retiring on 2999-12-01 — use Customer instead"
    readers = client.get("/object-types/review", params=PARAMS).json()
    assert readers["retiring"] is None                                         # readers: not until published
    editors = client.get("/object-types/review", params={**PARAMS, "ontology_view": "draft"}).json()
    assert editors["retiring"]["successor_name"] == "Customer" and editors["retiring"]["past"] is False
    assert client.post("/ontology/release/publish", params=PARAMS).status_code == 200
    assert client.get("/object-types/review", params=PARAMS).json()["retiring"]["on"] == "2999-12-01"
    assert client.get("/object-types/order", params=PARAMS).json().get("retiring") is None

    wrong = client.put("/ontology/retiring", params=PARAMS, json={**body, "successor": "Shipment"})
    assert wrong.status_code == 400 and "no entity 'Shipment'" in wrong.json()["detail"]
    missing = client.put("/ontology/retiring", params=PARAMS, json={**body, "target_id": "Nothing"})
    assert missing.status_code == 404

    unmark = client.delete("/ontology/retiring", params={**PARAMS, "kind": "entity", "target_id": "Review"})
    assert unmark.status_code == 200, unmark.text
    assert unmark.json()["change"]["class"] == "MEANING" and unmark.json()["retiring"] is None
    again = client.delete("/ontology/retiring", params={**PARAMS, "kind": "entity", "target_id": "Order"})
    assert again.status_code == 404 and "is not marked retiring" in again.json()["detail"]


def test_a_mark_merges_into_a_declaration_and_keeps_its_counts(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.retiring")                                  # releases off: served when saved
    assert client.post("/ontology/processes", params=PARAMS, json=FULFILMENT).status_code == 200
    other = {**copy.deepcopy(FULFILMENT), "id": "order_fulfilment_v2"}
    for stage in other["stages"]:
        if stage.get("promise"):
            stage["promise"]["name"] += "_v2"                                  # its derived names are its own
    second = client.post("/ontology/processes", params=PARAMS, json=other)
    assert second.status_code == 200, second.text
    with viewing("published"):
        before = find_override(PARAMS["connection_id"], "ecommerce", "process", "order_fulfilment")
    put = client.put("/ontology/retiring", params=PARAMS, json={"kind": "process", "target_id": "order_fulfilment",
                                                               "successor": "order_fulfilment_v2", "on": "2999-01-01"})
    assert put.status_code == 200, put.text
    assert put.json()["landed"] == "published"
    after = find_override(PARAMS["connection_id"], "ecommerce", "process", "order_fulfilment")
    assert after.binding == before.binding and after.fields["stages"] == before.fields["stages"]
    assert after.fields["retiring"] == {"successor": "order_fulfilment_v2", "on": "2999-01-01"}
    processes = client.get("/ontology/processes", params=PARAMS).json()["processes"]
    assert {p["id"] for p in processes} >= {"order_fulfilment", "order_fulfilment_v2"}   # it still serves


def test_off_the_door_refuses_and_pages_are_as_before(door, client, monkeypatch):  # noqa: F811
    _flags(monkeypatch, "ontology.release")
    put = client.put("/ontology/retiring", params=PARAMS, json={"kind": "entity", "target_id": "Review", **MARK})
    assert put.status_code == 409 and "off on this install" in put.json()["detail"]
    save_override(PARAMS["connection_id"], "ecommerce", OntologyOverride(target_kind="entity", target_id="Review",
                                                                        fields={"retiring": MARK}))
    detail = client.get("/object-types/review", params={**PARAMS, "ontology_view": "draft"}).json()
    assert "retiring" not in detail and "retiring_said" not in detail
