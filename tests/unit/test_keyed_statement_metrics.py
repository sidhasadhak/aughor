"""Arc OC-3 — the object door reads an approved metric by the entity it measures (ROADMAP §3.56).

Before: an approved metric is a whole statement and the object compiler re-anchors only flat expressions, so it
refused one — "revenue for delivered orders" could be computed by the agent's own SQL, never by the approved
definition. Behind `ontology.keyed_metrics`, a metric a person keyed to an entity is read as its whole statement, with
every read of the entity's table restricted to the objects the query selected; each figure here equals a query
written by hand over the seeded samples warehouse. A breakdown, a ratio over it, a metric keyed to another entity, one
that does not read the entity's table and an expression-only one are each refused with why.
"""
from __future__ import annotations

import json

import pytest

from aughor.db.connection import open_connection
from aughor.ontology.models import OntologyGraph
from aughor.semantic.metrics import MetricDefinition
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, keyed_metrics_for
from tests.unit.test_object_bindings import GRAPH, rows, seed

LINE_REVENUE = MetricDefinition(
    name="line_revenue", connection="keyed-t", label="Line revenue", entity="OrderItem", entity_confirmed_by="ana",
    status="approved", sql="SELECT SUM(quantity * unit_price) AS line_revenue FROM ecommerce.order_items")
BIG_LINES = MetricDefinition(
    name="big_lines", connection="keyed-t", label="Big lines", entity="OrderItem", status="approved",
    sql="WITH big AS (SELECT item_id FROM ecommerce.order_items WHERE quantity >= 3) SELECT COUNT(*) FROM big")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("keyed") / "samples.duckdb"
    seed(path)
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="keyed-t")
    yield conn
    conn.close()


@pytest.fixture
def graph():
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _run(db, query: dict, graph, metrics=(LINE_REVENUE, BIG_LINES)):
    out = rows(db, compile_object_query(query, graph, metrics=list(metrics)).sql)
    if not query.get("by") and not query.get("grain"):
        # An ungrouped read is ONE row. Every test here read only the first, and a keyed metric came back once per
        # object — the value a thousand times over on theLook's live receipt (2026-10-09) — while all stayed green.
        assert len(out) == 1, f"an ungrouped read is one row, not {len(out)}"
    return out


def _one(db, sql: str):
    return rows(db, sql)[0][0]


def test_over_every_object_the_figure_is_the_statements_own(db, graph):
    (got,) = _run(db, {"object_type": "order_item", "measures": [{"metric": "line_revenue"}]}, graph)
    assert got[0] == _one(db, LINE_REVENUE.sql)


def test_over_a_filtered_set_the_statement_reads_only_those_objects(db, graph):
    # Line revenue for delivered orders: the filter reaches Order through the measured to-one link, and the
    # statement's order_items is restricted to the lines it selected.
    got = _run(db, {"object_type": "order_item", "filters": [{"path": "order.status", "value": "delivered"}],
                    "measures": [{"metric": "line_revenue"}, {"agg": "count"}]}, graph)[0]
    want = rows(db, "SELECT SUM(i.quantity * i.unit_price), COUNT(*) FROM ecommerce.order_items i "
                    "JOIN ecommerce.orders o ON o.order_id = i.order_id WHERE o.status = 'delivered'")[0]
    assert float(got[0]) == pytest.approx(float(want[0])) and got[1] == want[1]
    assert float(got[0]) < float(_one(db, LINE_REVENUE.sql))           # a subset, not the whole


def test_a_read_inside_a_cte_is_restricted_too(db, graph):
    got = _run(db, {"object_type": "order_item", "filters": [{"path": "order.status", "value": "delivered"}],
                    "measures": [{"metric": "big_lines"}]}, graph)[0][0]
    want = _one(db, "SELECT COUNT(*) FROM ecommerce.order_items i JOIN ecommerce.orders o ON o.order_id = i.order_id "
                    "WHERE o.status = 'delivered' AND i.quantity >= 3")
    assert got == want


def test_the_plan_says_whose_definition_it_computed(graph):
    compiled = compile_object_query({"object_type": "order_item", "measures": [{"metric": "line_revenue"}]}, graph,
                                    metrics=[LINE_REVENUE])
    assert any("approved, keyed to OrderItem by ana" in step for step in compiled.plan)


@pytest.mark.parametrize("query, metrics, says", [
    ({"object_type": "order_item", "by": ["product.category"], "measures": [{"metric": "line_revenue"}]},
     [LINE_REVENUE], "not broken down"),
    ({"object_type": "order_item", "measures": [{"metric": "line_revenue", "divide_by": {"agg": "count"}}]},
     [LINE_REVENUE], "not divided again"),
    ({"object_type": "order", "measures": [{"metric": "line_revenue"}]}, [LINE_REVENUE], "measures OrderItem"),
    ({"object_type": "order_item", "measures": [{"metric": "orders_count"}]},
     [MetricDefinition(name="orders_count", connection="keyed-t", label="Orders", entity="OrderItem",
                       status="approved", sql="SELECT COUNT(*) FROM ecommerce.orders")], "does not read"),
    ({"object_type": "order_item", "measures": [{"metric": "units"}]},
     [MetricDefinition(name="units", connection="keyed-t", label="Units", entity="OrderItem", status="approved",
                       sql="SUM(quantity)")], "is an expression"),
    ({"object_type": "order_item", "measures": [{"metric": "blank"}]},
     [MetricDefinition(name="blank", connection="keyed-t", label="Blank", entity="OrderItem", status="approved",
                       sql="")], "has no statement"),
])
def test_what_cannot_be_read_over_a_set_is_refused_with_why(graph, query, metrics, says):
    with pytest.raises(ObjectQueryRefused, match=says):
        compile_object_query(query, graph, metrics=metrics)


def test_without_keyed_metrics_the_door_reads_as_before(graph):
    with pytest.raises(ObjectQueryRefused, match="no metric 'line_revenue'"):
        compile_object_query({"object_type": "order_item", "measures": [{"metric": "line_revenue"}]}, graph)


def test_the_flag_decides_which_metrics_the_door_is_handed(monkeypatch, tmp_path):
    from aughor.semantic import metrics as M
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    M.save_metric(LINE_REVENUE)
    M.save_metric(LINE_REVENUE.model_copy(update={"name": "draft_revenue", "status": "draft"}))
    M.save_metric(LINE_REVENUE.model_copy(update={"name": "unkeyed", "entity": None}))
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: False)
    assert keyed_metrics_for("keyed-t") == []
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda name: name == "ontology.keyed_metrics")
    assert [m.name for m in keyed_metrics_for("keyed-t")] == ["line_revenue"]     # approved and keyed only


def test_an_entity_with_no_key_cannot_hand_its_objects_to_a_statement(graph):
    # theLook's Event had no key on the live graph (2026-10-09): the restriction rendered an empty column name.
    item = graph.entities["OrderItem"]
    item.identity_key = ""
    if item.backing is not None:
        item.backing.primary_key = ""
    with pytest.raises(ObjectQueryRefused, match="has no key"):
        compile_object_query({"object_type": "order_item", "filters": [{"path": "order.status", "value": "delivered"}],
                              "measures": [{"metric": "line_revenue"}]}, graph, metrics=[LINE_REVENUE])


def test_a_keyed_metric_wins_over_the_graphs_own_copy_of_the_same_name(db, graph):
    # theLook's graph held each approved metric again as an ontology metric, its whole statement as a formula the
    # compiler cannot re-anchor; the keyed, approved definition is the one read.
    from aughor.ontology.models import OntologyMetric
    graph.metrics["line_revenue"] = OntologyMetric(id="line_revenue", display_name="Line revenue", entity="OrderItem",
                                                   formula_sql=LINE_REVENUE.sql, verified=True)
    got = _run(db, {"object_type": "order_item", "measures": [{"metric": "line_revenue"}]}, graph)[0][0]
    assert got == _one(db, LINE_REVENUE.sql)


def test_every_read_of_the_entitys_table_is_restricted(db, graph):
    # A share of big lines reads order_items twice; over delivered orders both reads are the delivered lines.
    share = MetricDefinition(name="big_share", connection="keyed-t", label="Big share", entity="OrderItem",
                             status="approved",
                             sql="SELECT (SELECT COUNT(*) FROM ecommerce.order_items WHERE quantity >= 3) * 1.0 / "
                                 "(SELECT COUNT(*) FROM ecommerce.order_items)")
    got = _run(db, {"object_type": "order_item", "filters": [{"path": "order.status", "value": "delivered"}],
                    "measures": [{"metric": "big_share"}]}, graph, metrics=[share])[0][0]
    want = _one(db, "SELECT COUNT(*) FILTER (WHERE i.quantity >= 3) * 1.0 / COUNT(*) FROM ecommerce.order_items i "
                    "JOIN ecommerce.orders o ON o.order_id = i.order_id WHERE o.status = 'delivered'")
    assert float(got) == pytest.approx(float(want))


def test_a_cte_named_like_the_table_still_restricts_the_table_it_reads(db, graph):
    shadow = MetricDefinition(name="shadow", connection="keyed-t", label="Shadow", entity="OrderItem", status="approved",
                              sql="WITH order_items AS (SELECT * FROM ecommerce.order_items WHERE quantity >= 3) "
                                  "SELECT COUNT(*) FROM order_items")
    got = _run(db, {"object_type": "order_item", "filters": [{"path": "order.status", "value": "delivered"}],
                    "measures": [{"metric": "shadow"}]}, graph, metrics=[shadow])[0][0]
    want = _one(db, "SELECT COUNT(*) FROM ecommerce.order_items i JOIN ecommerce.orders o ON o.order_id = i.order_id "
                    "WHERE o.status = 'delivered' AND i.quantity >= 3")
    assert got == want
