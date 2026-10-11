"""Arc AP-5 — shapes in the starter, as the server reads them (ROADMAP §3.57; the study's §4.6).

A shape is offered when the ontology says it fits, with one sentence of why whose numbers are the door's: a queue for
things waiting past a measured promise with actions on them (or a platform-owned type whose status moves as declared),
a map for coordinates, one object for a name and several kinds of objects linking to it, a timeline for two moments, an
overview for every entity. One to three are offered, the best first and the overview after it; a map placed one link
away never leads. Nothing is offered that the install cannot build, and off, the starter's proposal is the one before.
"""
from __future__ import annotations

import pytest

from aughor.cockpit import from_object, shapes
from aughor.ontology.models import EditStateMachine, EntityProperty, Promise
from tests.unit.test_cockpit_pieces import _graph


def _promised():
    """The test graph with its order fulfilment's shipping stage promised within two days, measured."""
    g = _graph()
    process = g.processes["order_fulfilment"]
    process.stages[0].verified = True
    process.stages[1].verified = True
    process.stages[1].promise = Promise(name="dispatch", within_days=2, verified=True, as_of="2026-10-01")
    return g


def _sig(g, name, *, wiring=True, pieces=True):
    from aughor.semantic.object_query import find_object_type
    return shapes.signals(g, find_object_type(g, name), wiring=wiring, pieces=pieces)


def test_a_queue_is_read_from_a_measured_promise_and_the_actions_on_its_objects():
    sig = _sig(_promised(), "order")
    assert sig["queue"] == {"kind": "promise", "process": "order_fulfilment", "noun": "dispatch", "placed": "order_date",
                            "reached": "shipped_at", "stage": "shipped", "overdue": "overdue_dispatch",
                            "late": "late_dispatch", "promise": "2 days"}
    # the order is filled from the chosen one; a reason it may go without is not asked
    assert sig["actions"] == [{"id": "flag_for_review", "label": "flag for review",
                               "params": [{"name": "order", "source": "chosen"}]}]
    assert sig["lines"]["entity"] == "order_item" and sig["lines"]["path"] == "order_id"
    assert [o["shape"] for o in shapes.offered(sig)] == ["queue", "overview", "timeline"]


def test_no_queue_without_a_measured_promise_without_actions_or_without_wiring(monkeypatch):
    unmeasured = _graph()                                           # its process holds no promise
    assert _sig(unmeasured, "order")["queue"] is None
    assert _sig(_promised(), "order", wiring=False)["queue"] is None
    monkeypatch.setattr(shapes, "_actions", lambda graph, entity: [])
    assert _sig(_promised(), "order")["queue"] is None             # nothing to do about what waits


def test_a_platform_owned_queue_waits_on_a_status_a_move_still_leaves():
    g = _promised()
    case = g.entities["Customer"]                                  # stands in for a platform-owned type
    case.edit_states = {"tier": EditStateMachine(states=["open", "working", "resolved"],
                                                 moves=[["", "open"], ["open", "working"], ["working", "resolved"]])}
    from aughor.ontology.models import Backing
    case.backing = Backing(kind="platform")
    q = shapes.signals(g, case, wiring=True, pieces=True)["queue"]
    assert q == {"kind": "states", "status": "tier", "final": ["resolved"], "moves": "open → working → resolved"}


def test_a_map_reads_its_own_coordinates_first_and_one_a_link_reaches_follows_the_overview():
    g = _promised()
    customer = g.entities["Customer"]
    for n in ("latitude", "longitude"):
        customer.properties[n] = EntityProperty(name=n, data_type="DOUBLE", semantic_type="key")   # a role says nothing
    assert _sig(g, "customer")["places"] == {"lat": "latitude", "lng": "longitude", "via": ""}
    through = _sig(g, "order")["places"]
    assert through["lat"].endswith(".latitude") and through["through"] == "Customer"
    order = shapes.offered(_sig(g, "order"))
    assert [o["shape"] for o in order] == ["queue", "overview", "timeline"]      # the map through a link falls off
    review = shapes.offered(_sig(g, "review"))
    assert [o["shape"] for o in review][:2] == ["overview", "map"]               # never what a review is for
    assert _sig(g, "customer", pieces=False)["places"] is None


def test_one_object_needs_a_name_and_three_kinds_linking_to_it(monkeypatch):
    g = _promised()
    sig = _sig(g, "customer")
    assert sig["one"] is None                                       # orders and reviews: two kinds
    monkeypatch.setattr(shapes, "MIN_LINKED_KINDS", 2)
    sig = _sig(g, "customer")
    assert sig["one"]["label"] == "full_name" and {x["entity"] for x in sig["one"]["links"]} == {"order", "review"}
    assert shapes.offered(sig)[0]["shape"] == "one"
    assert _sig(g, "customer", wiring=False)["one"] is None


def test_a_timeline_draws_between_an_objects_own_two_moments():
    g = _promised()
    assert _sig(g, "order")["moments"] == {"start": "order_date", "end": "shipped_at"}
    assert _sig(g, "customer")["moments"] is None                  # one moment
    assert _sig(g, "order", pieces=False)["moments"] is None


def test_off_or_with_nothing_to_build_an_object_is_offered_its_overview_alone():
    sig = _sig(_promised(), "order", wiring=False, pieces=False)
    assert [o["shape"] for o in shapes.offered(sig)] == ["overview"]
    assert len(shapes.offered(_sig(_promised(), "order"))) <= shapes.MAX_OFFERED


def test_each_sentence_says_the_doors_numbers_and_leaves_out_a_number_it_was_not_given():
    g = _promised()
    sig = _sig(g, "order")
    assert shapes.why("queue", sig, {"waiting": 1375}) == (
        "Order has a dispatch promise of 2 days; 1,375 orders placed in the last 14 days are past it, and 1 action is "
        "declared on it.")
    assert shapes.why("queue", sig, {}) == "Order has a dispatch promise of 2 days, and 1 action is declared on it."
    assert shapes.why("timeline", sig, {"both": 4346}) == "Each order holds two moments, order date and shipped at — 4,346 hold both."


def test_the_numbers_are_read_through_the_door_and_a_refused_read_says_less():
    g = _promised()
    sig = _sig(g, "order")
    asked = []

    def run(q):
        asked.append(q)
        return ["n"], [["1375"]], []
    got = shapes.measure(sig, ["queue", "timeline"], run)
    assert got == {"waiting": 1375, "both": 1375}
    assert asked[0]["segment"] == "overdue_dispatch" and asked[0]["filters"] == [
        {"path": "order_date", "op": "in_last", "value": shapes.WINDOW_DAYS}]

    def refused(q):
        raise RuntimeError("the warehouse did not answer")
    assert shapes.measure(sig, ["queue"], refused) == {"waiting": None}


def _counts(q):
    """A door that answers every count: one row, the counts' names as its columns."""
    names = [m.get("name") or "n" for m in q.get("measures", [])]
    if q.get("by"):
        return [q["by"][0], "n"], [["Shipped", 3], ["Processing", 2]], []
    if q.get("time"):
        return ["day", "n"], [], []
    return names, [[5 for _ in names]], []


def test_the_starter_offers_shapes_only_while_they_are_on_and_is_the_one_before_off(monkeypatch):
    g = _promised()
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    off = from_object.propose(g, "order", _counts)
    assert "shapes" not in off and "signals" not in off
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda name: name in {shapes.FLAG, "cockpit.wiring", "cockpit.app_pieces"})
    on = from_object.propose(g, "order", _counts)
    assert {k: v for k, v in on.items() if k not in ("shapes", "signals")} == off
    assert [o["shape"] for o in on["shapes"]] == ["queue", "overview", "timeline"]
    assert on["shapes"][0]["why"].startswith("Order has a dispatch promise of 2 days; 5 orders placed in the last 14 days")
    assert on["signals"]["queue"]["overdue"] == "overdue_dispatch" and on["signals"]["window"] == shapes.WINDOW_DAYS


def test_a_case_is_startable_its_counts_read_from_the_edit_layer():
    """The study measured the starter refusing a case: the starter's reader now counts a platform-owned type where its
    cases live."""
    from aughor.ontology.models import Backing
    g = _promised()
    g.entities["Customer"].backing = Backing(kind="platform")
    assert from_object.platform_counts(g, {"object_type": "order", "measures": [{"agg": "count"}]}, []) is None
    cols, rows, _ = from_object.platform_counts(g, {"object_type": "customer", "measures": [{"name": "n", "agg": "count"}]}, [])
    assert cols == ["n"] and rows == [[0]]
    with pytest.raises(Exception, match="counted, never drawn over days"):
        from_object.platform_counts(g, {"object_type": "customer", "measures": [{"agg": "count"}], "time": "signup_date",
                                        "grain": "day"}, [])


def test_the_route_says_each_objects_best_fit_and_is_closed_while_shapes_are_off(monkeypatch):
    from fastapi import HTTPException

    from aughor.routers import cockpit as R
    g = _promised()
    monkeypatch.setattr("aughor.routers.ontology.served_ontology_graph", lambda conn, schema: g)
    monkeypatch.setattr(R, "_on", lambda: None)
    base = {"ontology.cockpit_pieces", "ontology.object_cockpits"}
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name in base)
    with pytest.raises(HTTPException) as off:
        R.suggested_shapes("c")
    assert off.value.status_code == 404 and "off on this install" in str(off.value.detail)
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda name: name in base | {shapes.FLAG, "cockpit.wiring", "cockpit.app_pieces"})
    out = {o["type_id"]: (o["shape"], o["short"]) for o in R.suggested_shapes("c")["objects"]}
    assert out["Order"] == ("queue", "a dispatch promise · 1 action")
    assert out["Product"][0] == "overview" and out["Customer"][0] == "overview"


def test_an_action_needing_an_object_of_another_type_is_left_out_nothing_on_the_page_holds_one(tmp_path, monkeypatch):
    """Declared through the overrides tree, as a person's declaration is."""
    from aughor.ontology import overrides as OV
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    g = _promised()
    OV.save_override("shapes-t", "ecommerce", OV.OntologyOverride(target_kind="action", target_id="tell_customer", fields={
        "display_name": "Tell the customer", "kind": "annotate", "risk": "low", "object_type": "order",
        "params": [{"name": "order", "kind": "object", "object_type": "order"},
                   {"name": "customer", "kind": "object", "object_type": "customer"}],
        "edits": [{"object": "order", "property": "told", "value": "true", "note": ""}]}))
    OV.apply_overrides(g, "shapes-t", "ecommerce")
    assert "tell_customer" in [a.id for a in g.declared_actions()]
    assert [a["id"] for a in _sig(g, "order")["actions"]] == ["flag_for_review"]


def test_a_platform_owned_count_keeps_to_the_rows_a_preview_asks_for():
    from aughor.ontology.models import Backing
    g = _promised()
    g.entities["Customer"].backing = Backing(kind="platform")
    from types import SimpleNamespace
    held = [SimpleNamespace(kind="property", object_type="customer", row_key=pk, column="country", body=country,
                            created_at=f"2026-10-0{i}") for i, (pk, country) in enumerate(
        [("c1", "Chile"), ("c2", "Chile"), ("c3", "Peru")], start=1)]
    q = {"object_type": "customer", "measures": [{"name": "n", "agg": "count"}], "by": ["country"], "limit": 1}
    _, every, _ = from_object.platform_counts(g, {**q, "limit": None}, held)
    assert every == [["Chile", 2], ["Peru", 1]]
    _, rows, _ = from_object.platform_counts(g, q, held)
    assert rows == [["Chile", 2]]


def test_a_type_that_declares_no_key_is_never_listed_so_it_gets_an_overview_and_no_table_links_to_it(monkeypatch):
    """Found on theLook: one customer's page offered a table of its events, and an event log declares no key — the
    keep door refused it. A shape lists only what the door can list."""
    g = _promised()
    review = g.entities["Review"]
    review.identity_key = ""
    if review.backing is not None:
        review.backing.primary_key = ""
    assert not shapes.listable(review) and shapes.listable(g.entities["Order"])
    for n in ("latitude", "longitude"):
        review.properties[n] = EntityProperty(name=n, data_type="DOUBLE", semantic_type="measure")
    sig = _sig(g, "review")
    assert sig["places"] is None and sig["moments"] is None and sig["queue"] is None
    assert [o["shape"] for o in shapes.offered(sig)] == ["overview"]
    links = shapes.linked_to(g, g.entities["Customer"])
    assert [(x["entity"], x["listable"]) for x in links] == [("order", True), ("review", False)]   # listed ones first
    assert _sig(g, "customer")["lines"]["entity"] == "order"                                       # never a keyless one
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    assert from_object.propose(g, "review", _counts)["listable"] is False
    assert from_object.propose(g, "order", _counts)["listable"] is True


def test_the_kinds_that_can_be_listed_come_first_and_a_queue_lists_only_one_of_them():
    g = _promised()
    order = g.entities["Order"]
    order.identity_key = ""
    if order.backing is not None:
        order.backing.primary_key = ""
    links = shapes.linked_to(g, g.entities["Customer"])
    assert [(x["entity"], x["listable"]) for x in links] == [("review", True), ("order", False)]
    assert _sig(g, "customer")["lines"]["entity"] == "review"
    review = g.entities["Review"]
    review.identity_key = ""
    if review.backing is not None:
        review.backing.primary_key = ""
    assert _sig(g, "customer")["lines"] is None                    # what links to it, none of it listable
