"""Arc OC-3 — the question frame resolves an approved metric a person keyed to the entity it measures (ROADMAP §3.56).

Before: an approved metric named in a question was a term that defined nothing, so "revenue from completed orders" was
read as the rule alone, starting from Order, and the revenue was lost. Handed the keyed metrics (`ontology.keyed_metrics`
on), the frame offers the metric as a declared definition, starts from its entity, applies the rules the question names
from there through measured links, and compiles the metric's own statement through the object door. Handed none, it
reads exactly as before. On theLook's frozen graph (`evals/framing_matcher_eval.py --keyed`) the twelve pre-registered
metric questions went from 0 to 9 at first measurement, and to 12 after the two general fixes tested here.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from aughor.ontology.framing import frame_question
from aughor.ontology.models import OntologyGraph

GRAPH = "evals/ablation_thelook_business_ontology.json"


def _metric(name: str, label: str, entity: str, sql: str = "") -> NS:
    return NS(name=name, label=label, entity=entity, sql=sql, approved_by="finance", entity_confirmed_by="ana")


REVENUE = _metric("revenue", "Revenue", "OrderItem", "SELECT SUM(sale_price) AS revenue FROM order_items")
AOV = _metric("average_order_value_aov", "Average order value (AOV)", "OrderItem",
              "SELECT SUM(sale_price) / COUNT(DISTINCT order_id) FROM order_items")
LEAD = _metric("average_ship_to_delivery_lead_time", "Average ship to delivery lead time", "OrderItem",
               "SELECT AVG(DATE_DIFF('day', shipped_at, delivered_at)) FROM order_items")


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(open(GRAPH).read()))


def test_a_named_keyed_metric_is_the_definition_and_starts_from_its_entity(graph):
    f = frame_question("What was revenue last month?", graph, metrics=[REVENUE])
    assert f.outcome is not None and (f.outcome.kind, f.outcome.name) == ("metric", "revenue")
    assert f.start["entity"] == "OrderItem"
    assert "keyed to OrderItem by ana" in f.outcome.measured and "approved by finance" in f.outcome.measured
    assert "sql" in f.compiled["revenue"], f.compiled["revenue"]          # its statement, through the object door
    assert "SUM(sale_price)" in f.compiled["revenue"]["sql"]


def test_a_rule_the_question_names_applies_from_the_metrics_entity(graph):
    f = frame_question("What was revenue from completed orders in 2025?", graph, metrics=[REVENUE])
    assert (f.outcome.name, f.start["entity"]) == ("revenue", "OrderItem")
    assert [r.id for r in f.rules if r.usable] == ["completed_orders"]
    compiled = f.compiled["revenue"]
    assert compiled["query"]["filters"]                                   # the rule, through OrderItem → Order
    assert "restricted to the OrderItem objects selected" in " ".join(compiled["plan"])


def test_handed_no_keyed_metric_the_frame_reads_as_before(graph):
    q = "What was revenue from completed orders in 2025?"
    assert frame_question(q, graph).model_dump() == frame_question(q, graph, metrics=()).model_dump()
    assert frame_question(q, graph).outcome.name == "completed_orders"     # the rule alone, as before


def test_a_labels_abbreviation_and_its_words_each_name_the_metric(graph):
    for q in ("What is the average order value?", "What is our AOV this month?"):
        f = frame_question(q, graph, metrics=[AOV])
        assert f.outcome is not None and f.outcome.name == "average_order_value_aov", q


def test_words_spent_on_a_metrics_whole_name_raise_no_rival_definitions(graph):
    f = frame_question("What is the average ship to delivery lead time?", graph, metrics=[LEAD])
    assert [o.name for o in f.candidates()] == ["average_ship_to_delivery_lead_time"]
    assert f.outcome.name == "average_ship_to_delivery_lead_time"


def test_a_metric_keyed_to_an_entity_the_scope_does_not_serve_says_so(graph):
    f = frame_question("What was refund volume?", graph, metrics=[_metric("refund_volume", "Refund volume", "Refund")])
    (o,) = [o for o in f.outcomes if o.kind == "metric"]
    assert not o.usable and "does not serve" in o.why_not and f.outcome is None


def test_the_graphs_own_copy_of_a_keyed_name_stops_being_a_term(graph):
    f = frame_question("What was revenue last month?", graph, metrics=[REVENUE])
    assert {t.target for t in f.terms if t.kind == "metric"} == {"keyed:revenue"}
