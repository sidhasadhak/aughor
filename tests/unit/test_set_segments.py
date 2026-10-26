"""Arc FA, FA-4 — a set becomes a segment: a dashboard set kept as a condition rule, read as the segment it names.

A dashboard set's conditions are the object door's own (`web/lib/dashboards/sets.ts` flattens them, `segmentRule`), and
the one a rule refused was `in_last` — "placed in the last 14 days". Behind ``ontology.set_segments`` a rule's condition
may count the last days, so a set of fixed conditions keeps as a segment that reads the very objects the set read; off,
the rule door refuses `in_last` as it always did. Held on the seeded samples warehouse through the real compiler.
"""
from __future__ import annotations

import pytest

from aughor.ontology.business_rules import resolve_rule, rule_fields, rule_spec_problem
from tests.unit.test_object_processes import _isolated_overrides, db, declare_rule, graph, run  # noqa: F401

#: A dashboard's set "Placed recently and shipped", as `segmentRule` flattens it with the author's window in place.
KEPT = {"id": "placed_recently_and_shipped", "display_name": "Placed recently and shipped", "entity": "Order",
        "kind": "condition", "origin": "human",
        "conditions": [{"path": "status", "op": "=", "value": "shipped"},
                       {"path": "order_date", "op": "in_last", "value": 1200}]}


def test_off_a_rule_refuses_the_last_days_as_it_always_did(monkeypatch):
    monkeypatch.delenv("AUGHOR_ONTOLOGY_SET_SEGMENTS", raising=False)
    problem = rule_spec_problem(KEPT)
    assert problem.startswith("a condition's op is one of") and "in_last" not in problem
    # and a rule without it reads exactly as before
    assert rule_spec_problem({**KEPT, "conditions": KEPT["conditions"][:1]}) == ""


def test_on_a_kept_set_counts_the_objects_the_set_read_and_reads_as_its_segment(db, graph, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SET_SEGMENTS", "1")
    fields, rule = declare_rule(graph, db, KEPT)
    assert fields["origin"] == "human" and fields["conditions"][1] == {"path": "order_date", "op": "in_last", "value": 1200}
    # the set, as the object door read it on the dashboard
    [(held,)] = run(db, {"object_type": "order", "filters": KEPT["conditions"], "measures": [{"agg": "count"}]}, graph)
    assert 0 < held < rule.objects
    assert (rule.admitted, rule.verified) == (held, True)
    # the falsifier: the segment it names reads the very objects the set read
    assert run(db, {"object_type": "order", "segment": KEPT["id"], "measures": [{"agg": "count"}]}, graph) == [(held,)]
    # and says what it keeps as the set said it
    from aughor.ontology.derived import rule_derivations
    assert rule_derivations(rule).segments[0].description == "status = shipped; order_date in the last 1200 days"


def test_on_a_window_the_compiler_cannot_read_is_refused_with_its_reason(graph, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SET_SEGMENTS", "1")
    bad = {**KEPT, "conditions": [{"path": "status", "op": "in_last", "value": 14}]}
    assert rule_spec_problem(bad) == ""
    problem, _ = resolve_rule(graph, bad["id"], rule_fields(bad))
    assert problem.startswith(f"rule {bad['id']}:") and "status" in problem


@pytest.mark.parametrize("days", [0, "fourteen"])
def test_on_a_window_that_is_no_number_of_days_is_refused(graph, monkeypatch, days):  # noqa: F811
    monkeypatch.setenv("AUGHOR_ONTOLOGY_SET_SEGMENTS", "1")
    bad = {**KEPT, "conditions": [{"path": "order_date", "op": "in_last", "value": days}]}
    problem, _ = resolve_rule(graph, bad["id"], rule_fields(bad))
    assert problem.startswith(f"rule {bad['id']}:")
