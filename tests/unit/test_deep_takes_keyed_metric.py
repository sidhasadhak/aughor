"""Arc OC-3 — the deep analysis computes a keyed metric the question frame resolved, as declared (ROADMAP §3.56).

Live on theLook (2026-10-09) *What was revenue from completed orders in 2025?* framed to the approved Revenue over the
OrderItem objects rule completed_orders admits — and the intake re-parsed it. The model wrote the frame's compiled
statement into the metric, the over-count guard read its subquery as unsafe and fell back to ``SUM(sale_price)``, and
the rule was lost: 2,098,609.88 (every line not cancelled) published where completed orders measure 610,184.21.

Now the frame carries the keyed metric in the shape an analysis computes a measure in — its one measure, its table,
the rows its statement keeps and the objects the question's rules chose, the object door's own condition — the intake
takes it, and every statement the run executes that computes it is put over those rows and objects by the executor's
declared-filter guard. A statement that is more than one measure over its entity's table is not taken, and said.
"""
from __future__ import annotations

import contextvars
import json
from pathlib import Path
from types import SimpleNamespace as NS

import aughor.agent.investigate as I
from aughor.agent.investigate import _take_framed_metric, framed_rules
from aughor.agent.prompts_investigate import IntakeOutput
from aughor.ontology.framing import frame_question
from aughor.ontology.models import OntologyGraph
from aughor.semantic import enforcement as E
from aughor.semantic.object_query import compile_object_query
from aughor.sql.metric_filter_guard import enforce_metric_filters
from tests.unit.test_keyed_statement_metrics import LINE_REVENUE, db  # noqa: F401 — the samples warehouse fixture
from tests.unit.test_object_bindings import GRAPH as SAMPLES, rows

REPO = Path(__file__).resolve().parents[2]
THELOOK = OntologyGraph.model_validate(json.loads((REPO / "evals" / "ablation_thelook_business_ontology.json").read_text()))
QUESTION = "What was revenue from completed orders in 2025?"


def _metric(name: str, entity: str, sql: str, filters=()) -> NS:
    return NS(name=name, label=name.replace("_", " ").capitalize(), entity=entity, sql=sql, filters=list(filters),
              approved_by="finance", entity_confirmed_by="ana", status="approved")


REVENUE = _metric("revenue", "OrderItem", "SELECT (SUM(sale_price)) AS revenue FROM order_items WHERE status <> 'Cancelled'",
                  ["status <> 'Cancelled'"])
MARGIN = _metric("gross_margin_percentage", "OrderItem",
                 "SELECT 100.0 * SUM(oi.sale_price - ii.cost) / NULLIF(SUM(oi.sale_price), 0) "
                 "FROM order_items oi JOIN inventory_items ii ON oi.inventory_item_id = ii.id")


# ── the door says which objects it read a statement over ───────────────────────────────────────────────────────────

def test_the_objects_a_statement_was_read_over_are_a_condition_on_its_table(db):  # noqa: F811
    graph = OntologyGraph.model_validate(json.loads(SAMPLES.read_text()))
    query = {"object_type": "order_item", "filters": [{"path": "order.status", "value": "delivered"}],
             "measures": [{"metric": "line_revenue"}]}
    compiled = compile_object_query(query, graph, metrics=[LINE_REVENUE])
    assert " IN (SELECT DISTINCT t0." in compiled.objects
    (door,) = rows(db, compiled.sql)
    (taken,) = rows(db, f"SELECT SUM(quantity * unit_price) FROM ecommerce.order_items WHERE {compiled.objects}")
    (whole,) = rows(db, LINE_REVENUE.sql)
    assert taken == door and taken[0] < whole[0]                          # the door's own figure, over a subset
    every = compile_object_query({"object_type": "order_item", "measures": [{"metric": "line_revenue"}]}, graph,
                                 metrics=[LINE_REVENUE])
    assert every.objects == ""                                            # every object: nothing to restrict


# ── the frame carries the reading ──────────────────────────────────────────────────────────────────────────────────

def test_the_frame_reads_a_keyed_metric_as_its_measure_its_rows_and_the_rules_objects():
    f = frame_question(QUESTION, THELOOK, dialect="bigquery", metrics=[REVENUE])
    reading = f.compiled["revenue"]["reading"]
    assert (reading["formula"], reading["table"], reading["filters"]) == (
        "SUM(sale_price)", "order_items", ["status <> 'Cancelled'"])      # the field and the WHERE, said once
    assert reading["objects"] == f.compiled["revenue"]["objects"]
    assert reading["objects"].startswith("id IN (SELECT DISTINCT t0.id FROM thelook.order_items AS t0 LEFT JOIN "
                                         "thelook.orders AS j1") and "'Complete'" in reading["objects"]
    assert "objects" not in frame_question("What was revenue last month?", THELOOK, metrics=[REVENUE]
                                           ).compiled["revenue"]["reading"]   # no rule: every object


def test_a_statement_that_is_more_than_one_measure_over_its_table_is_not_read_and_says_why():
    f = frame_question("How has the gross margin percentage moved this year?", THELOOK, metrics=[MARGIN])
    reading = f.compiled["gross_margin_percentage"]["reading"]
    assert "formula" not in reading and "not one measure over OrderItem's table" in reading["why_not"]


def test_the_words_naming_the_chosen_keyed_metric_name_no_breakdown():
    # Live, "revenue" was also Order.revenue, a named driver: the run grouped revenue by revenue.
    f = frame_question(QUESTION, THELOOK, metrics=[REVENUE])
    assert not [d.path for d in f.drivers if d.named]
    unkeyed = frame_question("What was revenue by order status?", THELOOK)       # no keyed metric: as before
    assert unkeyed.outcome is None or unkeyed.outcome.kind != "metric"


# ── the intake takes it ────────────────────────────────────────────────────────────────────────────────────────────

def _intake(**over) -> IntakeOutput:
    base = dict(metric_label="Revenue from completed orders", metric_sql="SUM(price)", date_column="order_items.created_at",
                metric_table="orders", dimensions=[], intake_notes="")
    return IntakeOutput(**{**base, **over})


def test_the_intake_takes_the_measure_its_rows_and_the_objects_and_the_run_puts_them_on_every_statement():
    f = frame_question(QUESTION, THELOOK, dialect="bigquery", metrics=[REVENUE])
    intake = _intake()
    assert _take_framed_metric(intake, f, "TABLE: thelook.order_items\n  sale_price FLOAT64\n") is None
    assert (intake.metric_sql, intake.metric_table, intake.metric_filters) == (
        "SUM(sale_price)", "thelook.order_items", ["status <> 'Cancelled'"])
    taken = intake.framed_metric
    assert taken["objects"] == f.compiled["revenue"]["reading"]["objects"]
    assert taken["said"] == ("the OrderItem objects rule completed_orders admits (Order.status is one of Complete, "
                             "through order_item_to_order)")
    rules = framed_rules(intake.model_dump(), QUESTION)
    assert [(r["tables"], r["filters"], bool(r.get("chosen"))) for r in rules] == [
        (["order_items"], ["status <> 'Cancelled'"], False), (["order_items"], [taken["objects"]], True)]
    assert I._metric_definition_receipt(intake.model_dump()).startswith(
        "Revenue from completed orders — computed as `SUM(sale_price)`; over rows where `status <> 'Cancelled'` "
        "(its declared filter); for the OrderItem objects rule completed_orders admits")


def test_a_keyed_metric_the_intake_cannot_take_is_said_and_the_parse_stands():
    f = frame_question("How has the gross margin percentage moved this year?", THELOOK, metrics=[MARGIN])
    intake = _intake(metric_sql="SUM(sale_price)")
    note = _take_framed_metric(intake, f, "")
    assert "cannot compute it as declared" in note and "not one measure" in note
    assert (intake.metric_sql, intake.framed_metric, framed_rules(intake.model_dump())) == ("SUM(sale_price)", {}, [])


# ── the guard puts the objects on every statement that computes it ─────────────────────────────────────────────────

OBJECTS = ("id IN (SELECT DISTINCT t0.id FROM thelook.order_items AS t0 LEFT JOIN thelook.orders AS j1 "
           "ON t0.order_id = j1.order_id WHERE (j1.status IN ('Complete')))")
CHOSEN = {"metric": "revenue", "formula": "SUM(sale_price)", "tables": ["order_items"], "filters": [OBJECTS],
          "chosen": True, "said": "the OrderItem objects rule completed_orders admits"}


def test_the_objects_go_on_a_statement_that_groups_by_a_column_their_rule_names():
    # The statement the live run executed: grouped by the line's status. A declared filter on status is "dealt with"
    # there; the objects the question chose are not — it is still about completed orders.
    sql, applied = enforce_metric_filters(
        "SELECT status, SUM(sale_price) AS r FROM thelook.order_items AS oi GROUP BY 1", [CHOSEN], "bigquery")
    assert "oi.id IN (SELECT DISTINCT t0.id FROM thelook.order_items AS t0" in sql
    assert "j1.status IN ('Complete')" in sql and "oi.status IN" not in sql   # its subquery's columns stay its own
    assert applied == [{"metric": "revenue", "table": "order_items", "filter": OBJECTS, "said": CHOSEN["said"]}]
    again, more = enforce_metric_filters(sql, [CHOSEN], "bigquery")
    assert (again, more) == (sql, [])                                     # once: a repaired statement keeps one copy
    other, none = enforce_metric_filters("SELECT COUNT(*) FROM thelook.order_items", [CHOSEN], "bigquery")
    assert none == [] and "IN (SELECT" not in other                       # a statement that computes no revenue
    bare = {**CHOSEN, "filters": ["order_id IN (SELECT order_id FROM thelook.orders WHERE status = 'Complete')"]}
    sql, _ = enforce_metric_filters("SELECT SUM(sale_price) FROM thelook.order_items AS oi", [bare], "bigquery")
    assert "oi.order_id IN (SELECT order_id FROM thelook.orders WHERE status = 'Complete')" in sql   # never correlated


def test_the_run_holds_its_declared_rules_and_nothing_outside_a_run_does():
    assert E.declare([CHOSEN]) is False                                   # no run: nowhere to hold it
    assert E.rules_for_statement("") is None
    with E.answering(""):
        assert E.rules_for_statement("") is None
        assert E.declare([CHOSEN]) is True
        assert E.rules_for_statement("") == [CHOSEN]
    assert E.rules_for_statement("") is None


def test_a_resumed_run_holds_what_its_intake_declared():
    ctx = contextvars.copy_context()
    ctx.run(E.holding, [CHOSEN])
    assert ctx.run(E.rules_for_statement, "") == [CHOSEN]
    assert E.rules_for_statement("") is None                              # the run's copy, never the caller's


def test_the_deep_streams_later_nodes_read_what_its_intake_declared():
    # Each node runs in the stream's one copied context, on an executor thread; a scan's workers copy it again.
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from aughor.routers.investigations import _investigation_stream

    def nodes():
        E.declare([CHOSEN])                                               # the intake
        yield {"intake": {}}
        with ThreadPoolExecutor(1) as pool:                               # a later node's worker, as a scan's is
            ctx = contextvars.copy_context()
            yield {"scan": pool.submit(ctx.run, E.rules_for_statement, "").result()}

    async def drain():
        return [e async for e in _investigation_stream(nodes())]

    events = asyncio.run(drain())
    assert events[-1] == {"scan": [CHOSEN]}
    assert E.rules_for_statement("") is None
