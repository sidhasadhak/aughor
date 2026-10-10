"""Arc OC-5 — impacts: one promise's bearing on another, declared with its mechanism and measured.

Every figure is held to a query written by hand over the seeded samples warehouse (`test_object_processes`): the
fulfilment process keeps a per-LINE shipping deadline and a per-ORDER delivery window, so "an order whose lines missed
their shipping limit" crosses a to-many link and must read each order once; a second process keeps a dispatch window
and a delivery window on the same order, whose lag is the delivery stage's own.
"""
from __future__ import annotations

import copy

import pytest

from aughor.ontology import overrides as OV
from aughor.ontology.impacts import (
    MIN_GROUP,
    declared_impact,
    impact_entry,
    impact_fields,
    impact_spec_problem,
    impact_words,
    impacts_into,
    measure_impact,
    resolve_impact,
)
from aughor.ontology.overrides import OntologyOverride, apply_overrides, save_override
from tests.unit.test_object_bindings import ints
from tests.unit.test_object_processes import FULFILMENT, db, declare, door, fresh_graph  # noqa: F401 — the warehouse

WINDOWS = {"id": "fulfilment_days", "display_name": "Fulfilment in days", "entity": "Order", "stages": [
    {"name": "placed", "timestamp": "order_date"},
    {"name": "shipped", "timestamp": "shipped_at", "promise": {"name": "dispatch", "within_days": 2}},
    {"name": "delivered", "timestamp": "delivered_at", "promise": {"name": "delivery", "within_days": 5}}]}
DELIVERED = "o.shipped_at IS NOT NULL AND o.delivered_at IS NOT NULL"
LATE_DELIVERY = "date_diff('day', o.shipped_at, o.delivered_at) > 5"


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    return fresh_graph()


def _resolved(graph, upstream: str, downstream: str, **more):
    spec = {"id": "under_test", "upstream": upstream, "downstream": downstream, **more}
    assert impact_spec_problem(spec) == ""
    problem, fields = resolve_impact(graph, spec["id"], impact_fields(spec))
    assert problem == "", problem
    return fields


def _reference(db, where_up_broke: str, where_up_reached: str, population: str = DELIVERED):  # noqa: F811 — the warehouse fixture, by name
    return ints(db, (
        f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {where_up_broke}), "
        f"COUNT(*) FILTER (WHERE {where_up_broke} AND {LATE_DELIVERY}), "
        f"COUNT(*) FILTER (WHERE {where_up_reached}), "
        f"COUNT(*) FILTER (WHERE {where_up_reached} AND {LATE_DELIVERY}) "
        f"FROM ecommerce.orders o WHERE {population}"))


def _held_to(impact, reference) -> None:
    objects, n_broke, b_broke, n_reached, b_reached = reference
    assert (impact.objects, impact.upstream_broke, impact.upstream_kept) == (objects, n_broke, n_reached - n_broke)
    assert impact.rate_when_broke == round(b_broke / n_broke, 6)
    assert impact.rate_when_kept == round((b_reached - b_broke) / (n_reached - n_broke), 6)


def test_an_order_whose_lines_missed_their_limit_is_read_once_and_equals_its_reference(db, graph):  # noqa: F811 — the warehouse fixture, by name
    declare(graph, db, FULFILMENT)
    fields = _resolved(graph, "order_fulfilment.shipping", "order_fulfilment.delivery")
    assert (fields["lead"], fields["to_many"]) == ("Order", True) and fields["path"]
    impact = measure_impact(db, graph, "under_test", fields)
    line = "SELECT 1 FROM ecommerce.order_items i WHERE i.order_id = o.order_id"
    _held_to(impact, _reference(db, f"EXISTS ({line} AND o.shipped_at > i.ship_by)",
                                f"EXISTS ({line} AND o.shipped_at IS NOT NULL) AND EXISTS ({line} AND i.ship_by IS NOT NULL)"))
    assert impact.lag_days is None                       # the two moments are not both the lead object's own clock
    assert any("to-many link" in f for f in impact.flags)
    (orders,) = ints(db, f"SELECT COUNT(*) FROM ecommerce.orders o WHERE {DELIVERED}")
    assert impact.objects == orders                      # each order once, never once per line


def test_two_windows_on_one_order_read_the_delivery_stages_own_lag(db, graph):  # noqa: F811 — the warehouse fixture, by name
    _, measured = declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery")
    assert (fields["lead"], fields["path"], fields["to_many"]) == ("Order", "", False)
    impact = measure_impact(db, graph, "under_test", fields)
    late_dispatch = "date_diff('day', o.order_date, o.shipped_at) > 2"
    _held_to(impact, _reference(db, late_dispatch, "o.order_date IS NOT NULL AND o.shipped_at IS NOT NULL"))
    assert impact.lag_days == measured.stages[2].p50_days and impact.lag_days is not None
    assert impact.verified is ((impact.rate_when_broke > impact.rate_when_kept)
                               and min(impact.upstream_broke, impact.upstream_kept) >= MIN_GROUP)


def test_a_window_reads_only_the_last_days_of_the_data(db, graph):  # noqa: F811 — the warehouse fixture, by name
    _, measured = declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery", window_days=60)
    impact = measure_impact(db, graph, "under_test", fields)
    as_of = measured.stages[2].promise.as_of[:10]
    (inside,) = ints(db, f"SELECT COUNT(*) FROM ecommerce.orders o WHERE {DELIVERED} "
                         f"AND o.delivered_at >= DATE '{as_of}' - INTERVAL 60 DAY")
    assert impact.objects == inside and impact.window.startswith("the 60 days to")


def test_a_formula_is_exact_by_definition_and_never_measured(db, graph):  # noqa: F811 — the warehouse fixture, by name
    declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery", mechanism="formula",
                       formula="the delivery window starts when the order ships")
    impact = measure_impact(None, graph, "under_test", fields)          # no warehouse is touched
    assert impact.verified is None and impact.objects is None and "nothing is measured" in impact.note
    assert impact_words(graph, impact).endswith("by definition: the delivery window starts when the order ships")


@pytest.mark.parametrize("spec, says", [
    ({"upstream": "fulfilment_days", "downstream": "fulfilment_days.delivery"}, "names a promise as"),
    ({"upstream": "fulfilment_days.delivery", "downstream": "fulfilment_days.delivery"}, "ANOTHER"),
    ({"mechanism": "formula"}, "says, in `formula`"),
    ({"mechanism": "validated"}, "names its recorded evidence"),
    ({"window_days": 0}, "window_days"),
])
def test_a_declaration_that_cannot_be_read_says_why(spec, says):
    base = {"id": "x", "upstream": "fulfilment_days.dispatch", "downstream": "fulfilment_days.delivery"}
    assert says in impact_spec_problem({**base, **spec})


def test_a_promise_not_declared_or_not_measured_is_refused_before_anything_is_counted(db, graph):  # noqa: F811 — the warehouse fixture, by name
    declare(graph, db, WINDOWS)
    spec = impact_fields({"id": "x", "upstream": "fulfilment_days.packing", "downstream": "fulfilment_days.delivery"})
    assert "not a declared promise" in resolve_impact(graph, "x", spec)[0]
    unmeasured = copy.deepcopy(graph)
    unmeasured.processes["fulfilment_days"].stages[1].promise.verified = None
    spec = impact_fields({"id": "x", "upstream": "fulfilment_days.dispatch", "downstream": "fulfilment_days.delivery"})
    assert "has not been measured" in resolve_impact(unmeasured, "x", spec)[0]


def test_it_is_kept_in_the_tree_and_read_back_with_its_measurement_and_worded_as_an_association(db, graph):  # noqa: F811 — the warehouse fixture, by name
    declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery")
    measured = measure_impact(db, graph, "late_dispatch_late_delivery", fields)
    save_override("impacts-t", "ecommerce", OntologyOverride(
        target_kind="impact", target_id="late_dispatch_late_delivery", fields=fields,
        binding={"impact": impact_entry(fields, measured)}))
    served, report = apply_overrides(graph, "impacts-t", "ecommerce")
    read = served.impacts["late_dispatch_late_delivery"]
    assert (read.objects, read.rate_when_broke, read.verified) == (measured.objects, measured.rate_when_broke,
                                                                   measured.verified)
    assert [i.id for i in impacts_into(served, "fulfilment_days", "delivery")] == ["late_dispatch_late_delivery"]
    from aughor.agent.claim_type import sentence_claims
    read.verified = True
    words = impact_words(served, read)
    assert words.startswith("where the dispatch promise of Fulfilment in days was broken, the delivery promise")
    assert sentence_claims(words) == []                  # descriptive: it departs without an analysis's licence
    moved = OntologyOverride(target_kind="impact", target_id="x", fields={**fields, "window_days": 30},
                             binding={"impact": impact_entry(fields, measured)})
    assert "changed since it was counted" in declared_impact(moved, served).note


# ── the frame reads it first ────────────────────────────────────────────────────────────────────────────────────────

def test_a_question_about_late_delivery_starts_from_the_measured_impact_before_any_dimension(db, graph):  # noqa: F811 — the warehouse fixture, by name
    from aughor.agent.investigate import _frame_breakdowns
    from aughor.ontology.framing import frame_question, render_frame_block
    from tests.unit.test_object_bindings import rows
    declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery")
    impact = measure_impact(db, graph, "late_dispatch_late_delivery", fields)
    impact.verified = True                                # the frame reads a measured-true one; its numbers are real
    graph.impacts[impact.id] = impact
    frame = frame_question("what is causing late delivery", graph)
    assert frame.outcome is not None and frame.outcome.promise == "delivery"
    first = [d for d in frame.drivers if not d.named][0]
    assert (first.impact, first.path) == ("late_dispatch_late_delivery", "impact:late_dispatch_late_delivery")
    sql = frame.compiled[f"by {first.path}"]["sql"]
    [(where_broke, overall, n_broke, n)] = rows(db, sql)
    assert (n_broke, n) == (impact.upstream_broke, impact.objects)
    assert round(float(where_broke), 6) == impact.rate_when_broke
    block = render_frame_block(frame)
    assert "an association, never a cause" in block and first.reading in block
    breakdowns = _frame_breakdowns(frame.model_dump(mode="json"))
    assert list(breakdowns)[0] == "impact.late_dispatch_late_delivery"


def test_an_impact_the_data_does_not_bear_out_is_no_driver(db, graph):  # noqa: F811 — the warehouse fixture, by name
    from aughor.ontology.framing import frame_question
    declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery")
    impact = measure_impact(db, graph, "x", fields)
    impact.verified = False
    graph.impacts[impact.id] = impact
    assert not any(d.impact for d in frame_question("what is causing late delivery", graph).drivers)


def test_the_briefing_reads_a_moved_promise_beside_what_is_measured_upstream_of_it(db, graph, monkeypatch):  # noqa: F811 — the warehouse fixture, by name
    from aughor.knowledge import promise_chains
    declare(graph, db, WINDOWS)
    fields = _resolved(graph, "fulfilment_days.dispatch", "fulfilment_days.delivery")
    impact = measure_impact(db, graph, "late_dispatch_late_delivery", fields)
    graph.impacts[impact.id] = impact
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda conn, schema=None: graph)
    impact.verified = True
    said = promise_chains._upstream("c1", "fulfilment_days.delivery")
    assert said == impact_words(graph, impact) and said.startswith("where the dispatch promise")
    impact.verified = False
    assert promise_chains._upstream("c1", "fulfilment_days.delivery") == ""
    assert promise_chains._upstream("c1", "fulfilment_days.dispatch") == ""      # nothing is upstream of dispatch


# ── what a link carries, and the objects a stage touches ────────────────────────────────────────────────────────────

def test_a_link_carries_the_promise_kept_through_it_and_a_stage_names_its_lead_object(db, graph):  # noqa: F811 — the warehouse fixture, by name
    from aughor.ontology.purpose import link_purposes, stage_roles
    from aughor.semantic.object_types import object_type_map
    declare(graph, db, FULFILMENT)
    process = graph.processes["order_fulfilment"]
    via = process.stages[1].promise.via
    rel = next(r for r in graph.relationships.values() if via in (r.api_name, r.reverse_api_name))
    carried = link_purposes(graph)[rel.id]
    assert {"process": "order_fulfilment", "process_label": "Order fulfilment", "promise": "shipping",
            "how": "the shipping promise is kept per OrderItem and reaches Order through it"} in carried
    roles = stage_roles(graph, process, 1)
    lead = next(r for r in roles if r["role"] == "the lead object its promise is kept per")
    assert lead["entity"] == "OrderItem" and "every hop to-one" in lead["why"]
    assert next(r for r in roles if r["role"] == "goes through the process")["entity"] == "Order"
    edge = next(e for e in object_type_map(graph)["links"] if e["relationship"] == rel.id)
    assert edge["carries"] == carried
    unrelated = [r.id for r in graph.relationships.values() if r.id != rel.id and r.id not in link_purposes(graph)]
    assert unrelated, "a link no declaration reads carries nothing"


# ── moves between stages, and every timestamp checked ───────────────────────────────────────────────────────────────

def test_the_moves_the_data_makes_are_counted_and_set_against_those_declared(db, graph):  # noqa: F811 — the warehouse fixture, by name
    from aughor.ontology.processes import process_spec_problem
    spec = {**WINDOWS, "id": "moves", "leaves": {"property": "status", "values": ["cancelled", "refunded"]},
            "transitions": [{"from": "placed", "to": "shipped"}, {"from": "shipped", "to": "delivered"},
                            {"from": "delivered", "to": "left"}]}
    assert process_spec_problem(spec) == ""
    _, p = declare(graph, db, spec)
    moves = {(t.from_stage, t.to_stage): t for t in p.observed}
    o = "ecommerce.orders"
    ps, sd, pd, sl, pl = ints(db, (
        "SELECT COUNT(*) FILTER (WHERE order_date IS NOT NULL AND shipped_at IS NOT NULL), "
        "COUNT(*) FILTER (WHERE shipped_at IS NOT NULL AND delivered_at IS NOT NULL), "
        "COUNT(*) FILTER (WHERE order_date IS NOT NULL AND delivered_at IS NOT NULL AND shipped_at IS NULL), "
        "COUNT(*) FILTER (WHERE shipped_at IS NOT NULL AND delivered_at IS NULL AND status IN ('cancelled', 'refunded')), "
        f"COUNT(*) FILTER (WHERE order_date IS NOT NULL AND shipped_at IS NULL AND delivered_at IS NULL AND status IN ('cancelled', 'refunded')) FROM {o}"))
    assert moves[("placed", "shipped")].objects == ps and moves[("shipped", "delivered")].objects == sd
    assert moves[("placed", "shipped")].declared and moves[("shipped", "delivered")].declared
    assert pd + sl + pl > 0, "the samples hold moves nobody declared — the check is not vacuous"
    for pair, n in ((("placed", "delivered"), pd), (("shipped", "left"), sl), (("placed", "left"), pl)):
        assert (moves[pair].objects if pair in moves else 0) == n
        said = f"{pair[0]} → {pair[1]}"
        assert (said in p.conformance["seen_only_in_data"]) == bool(n), said        # nobody declared these
    assert sl == 1100 and "delivered → left" in p.conformance["never_observed"]     # declared; no delivered order left
    (before,) = ints(db, f"SELECT COUNT(*) FROM {o} WHERE delivered_at < order_date")
    assert p.stages[2].precedes.get("placed", 0) == before


@pytest.mark.parametrize("transitions, says", [
    ([{"from": "placed", "to": "nowhere"}], "each transition moves from one of its stages"),
    ([{"from": "placed", "to": "placed"}], "to itself is not a move"),
    ([{"from": "placed", "to": "shipped"}, {"from": "placed", "to": "shipped"}], "declared twice"),
])
def test_a_transition_that_names_no_stage_is_refused(transitions, says):
    from aughor.ontology.processes import process_spec_problem
    assert says in process_spec_problem({**WINDOWS, "transitions": transitions})


def test_a_deadline_before_the_object_entered_the_process_is_flagged_with_its_count(db, graph):  # noqa: F811 — the warehouse fixture, by name
    from tests.unit.test_object_processes import LINE_JOIN
    spec = {"id": "late_entry", "entity": "Order", "stages": [
        {"name": "shipped", "timestamp": "shipped_at"},
        {"name": "delivered", "timestamp": "delivered_at",
         "promise": {"name": "by_limit", "deadline": "ship_by", "grain": "OrderItem"}}]}
    _, p = declare(graph, db, spec)
    (early,) = ints(db, f"SELECT COUNT(*) {LINE_JOIN} WHERE i.ship_by < o.shipped_at")
    flags = [f for f in p.stages[1].promise.flags if f.startswith("deadline before entry")]
    assert early > 0 and flags and flags[0].startswith(f"deadline before entry: {early:,} OrderItem objects")


# ── the doors ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_moves_and_impacts_are_declared_counted_changed_and_withdrawn_over_http(door, client, monkeypatch):  # noqa: F811 — the door fixture, by name
    """The door's model once dropped `leaves` while every function carried it (#589): every new field is read back
    through the door itself."""
    from tests.unit.test_object_processes import PARAMS
    moves = [{"from": "placed", "to": "shipped"}, {"from": "shipped", "to": "delivered"}]
    made = client.post("/ontology/processes", params=PARAMS, json={**WINDOWS, "transitions": moves})
    assert made.status_code == 200, made.text
    read = next(p for p in client.get("/ontology/processes", params=PARAMS).json()["processes"] if p["id"] == WINDOWS["id"])
    assert [(t["from_stage"], t["to_stage"]) for t in read["transitions"]] == [("placed", "shipped"), ("shipped", "delivered")]
    assert read["observed"] and "untimed" in read["conformance"]
    assert all("roles" in s and "precedes" in s for s in read["stages"])
    later = {**WINDOWS, "stages": [*WINDOWS["stages"][:2], {**WINDOWS["stages"][2], "promise": {"name": "delivery",
                                                                                             "within_days": 3}}]}
    assert client.post("/ontology/processes/preview", params=PARAMS, json=later).status_code == 409
    counted = client.post("/ontology/processes/preview", params={**PARAMS, "replace": "true"}, json=later)
    assert counted.status_code == 200 and counted.json()["process"]["stages"][2]["promise"]["within_days"] == 3
    spec = {"id": "late_dispatch_late_delivery", "upstream": "fulfilment_days.dispatch",
            "downstream": "fulfilment_days.delivery"}
    preview = client.post("/ontology/impacts/preview", params=PARAMS, json=spec)
    assert preview.status_code == 200 and preview.json()["impact"]["objects"] > 0, preview.text
    declared = client.post("/ontology/impacts", params=PARAMS, json=spec)
    assert declared.status_code == 200, declared.text
    assert client.post("/ontology/impacts", params=PARAMS, json=spec).status_code == 409
    listed = client.get("/ontology/processes", params=PARAMS).json()["impacts"]
    assert [i["id"] for i in listed] == ["late_dispatch_late_delivery"] and listed[0]["reading"]
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.history")
    refused = client.delete(f"/ontology/processes/{WINDOWS['id']}", params=PARAMS)
    assert refused.status_code == 409 and "impact 'Late dispatch late delivery'" in refused.text
    assert client.delete("/ontology/impacts/late_dispatch_late_delivery", params=PARAMS).status_code == 200
    assert client.get("/ontology/processes", params=PARAMS).json()["impacts"] == []
