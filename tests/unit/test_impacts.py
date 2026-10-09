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
from tests.unit.test_object_processes import FULFILMENT, db, declare, fresh_graph  # noqa: F401 — the warehouse

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
    if read.verified:
        assert impact_words(served, read).endswith("an association, not a measured cause")
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
