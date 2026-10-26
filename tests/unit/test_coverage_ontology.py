"""Arc MC, MC-4 — the metrics the ontology's declarations derive: each measured promise's on-time rate, each stage's
conversion from the one before, each measured rule's share — compiled through the object door, and counted against the
ontology's own measurement at the same moment.

On the seeded samples warehouse with ON-9's order-fulfilment process (a per-line shipping deadline, delivery within five
days). MC-4's falsifier: a derived metric whose count differs from the ontology's own — the count gate refuses it, with
both counts, and a mutant negation proves the gate sees it.
"""
from __future__ import annotations

import pytest

from aughor.packs import knowledge
from aughor.semantic import coverage_proposals as CP
from aughor.semantic import metric_coverage
from aughor.semantic.metric_map import map_of
from tests.unit.test_object_processes import FULFILMENT, _isolated_overrides, db, declare, graph  # noqa: F401


@pytest.fixture
def retail_map(monkeypatch):
    monkeypatch.setattr(metric_coverage, "tables_of", lambda *a, **k: [])
    return map_of([p for p in knowledge.packages() if p.layer != "industry" or p.industry == "retail"])


def _value(db, sql: str) -> float:  # noqa: F811
    result = db.execute("reference", sql)
    assert not result.error, (result.error, sql)
    return float(list(result.rows[0])[0])


def test_each_measured_promise_proposes_its_on_time_rate_counted_as_the_ontology_counts_it(db, graph, retail_map):  # noqa: F811
    _, p = declare(graph, db, FULFILMENT)
    out = {x["name"]: x for x in CP.ontology_proposals("processes-t", "ecommerce", graph, db, retail_map)}
    for noun, index, column in (("shipping", 1, "orders.shipped_at"), ("delivery", 2, "orders.delivered_at")):
        promise = p.stages[index].promise
        rate = out[f"{noun}_on_time_rate"]
        assert rate["gates"]["count"] == {"ok": True, "why": f"{promise.kept:,} kept of {promise.reached:,}, as the "
                                                               "ontology counts"}
        assert _value(db, rate["sql"]) == pytest.approx(promise.kept / promise.reached)
        assert (rate["area"], rate["time_column"], rate["source"]) == ("fulfilment", column, CP.SOURCE_ONTOLOGY)
        assert rate["derived_from"] == f"the {noun} promise of process order_fulfilment"


def test_each_stage_after_another_proposes_its_conversion(db, graph, retail_map):  # noqa: F811
    _, p = declare(graph, db, FULFILMENT)
    out = {x["name"]: x for x in CP.ontology_proposals("processes-t", "ecommerce", graph, db, retail_map)}
    shipped = out["order_fulfilment_placed_to_shipped"]
    assert shipped["gates"]["count"]["ok"] is True
    assert _value(db, shipped["sql"]) == pytest.approx(p.stages[1].both / p.stages[0].reached)
    assert shipped["time_column"] == "orders.order_date"


def test_a_derived_count_that_differs_from_the_ontologys_is_refused_with_both_counts(db, graph, retail_map, monkeypatch):  # noqa: F811
    """The mutant: a kept-promise filter written `<` where the breach is `>` drops the lines exactly on the deadline."""
    declare(graph, db, FULFILMENT)
    monkeypatch.setattr(CP, "_negate", lambda c: {**c, "op": "<"} if c.get("op") == ">" else None)
    out = {x["name"]: x for x in CP.ontology_proposals("processes-t", "ecommerce", graph, db, retail_map)}
    count = out["shipping_on_time_rate"]["gates"]["count"]
    assert count["ok"] is False and "where the ontology counts" in count["why"]


def test_an_unmeasured_promise_proposes_nothing(db, graph, retail_map):  # noqa: F811
    _, p = declare(graph, db, FULFILMENT)
    p.stages[2].promise.verified = None
    names = {x["name"] for x in CP.ontology_proposals("processes-t", "ecommerce", graph, db, retail_map)}
    assert "shipping_on_time_rate" in names and "delivery_on_time_rate" not in names


def test_negation_flips_only_a_comparison():
    assert CP._negate({"path": "x", "op": ">", "value": 5}) == {"path": "x", "op": "<=", "value": 5}
    assert CP._negate({"path": "x", "op": "not_null"}) is None
