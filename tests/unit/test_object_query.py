"""ON-2 — the compiled object-query door: guards by construction, not by guard.

Every compiled query here runs on the bundled samples warehouse (seeded in a temp file — the
same deterministic SQL every install gets) against the MEASURED samples ontology the ON-0a door
wrote, and its rows are compared with a hand-written reference. The laws are §3.15's: a link is
traversed only when its cardinality was measured; a to-one join carries dimensions and filters,
never a SUM of the one side; a to-many link is pre-aggregated before the join; N:N is refused; a
ratio is a ratio of aggregates; every unresolved name is a refusal that names what exists.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from aughor.demo.setup import _seed_ecommerce
from aughor.ontology.models import Backing, OntologyGraph
from aughor.semantic.object_query import (
    ObjectQueryRefused,
    compile_object_query,
    object_catalog,
    render_object_catalog,
)

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.execute("SET search_path = 'ecommerce'")
    yield con
    con.close()


def _graph() -> OntologyGraph:
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _rows(con, sql: str) -> list[tuple]:
    def cell(v):
        return round(float(v), 4) if isinstance(v, (float, Decimal)) else v
    return sorted(tuple(cell(v) for v in row) for row in con.execute(sql).fetchall())


def _compile(query: dict, graph: OntologyGraph | None = None, **kw):
    return compile_object_query(query, graph or _graph(), fiscal_start_month=1, **kw)


def _refusal(query: dict, graph: OntologyGraph | None = None) -> ObjectQueryRefused:
    with pytest.raises(ObjectQueryRefused) as exc:
        _compile(query, graph)
    return exc.value


# ── answers equal their references ──────────────────────────────────────────────────────

CASES = [
    ("count", {"object_type": "order", "measures": [{"agg": "count"}]},
     "SELECT COUNT(*) FROM orders"),
    ("named_metric", {"object_type": "order", "measures": [{"metric": "revenue", "decimals": 2}]},
     "SELECT ROUND(SUM(total_amount), 2) FROM orders"),
    ("share_with_where", {"object_type": "order", "measures": [
        {"agg": "count", "where": [{"path": "status", "value": "cancelled"}],
         "divide_by": {"agg": "count"}, "scale": 100, "decimals": 2}]},
     "SELECT ROUND(100.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) FROM orders"),
    ("not_in", {"object_type": "order", "filters": [
        {"path": "status", "op": "not_in", "value": ["delivered", "cancelled", "refunded"]}],
        "measures": [{"agg": "count"}]},
     "SELECT COUNT(*) FROM orders WHERE status NOT IN ('delivered', 'cancelled', 'refunded')"),
    ("dimension_through_to_one", {"object_type": "order_item", "by": ["product.category"],
                                  "measures": [{"agg": "sum", "path": "line_total", "decimals": 2}]},
     "SELECT p.category, ROUND(SUM(oi.line_total), 2) FROM order_items oi "
     "JOIN products p ON p.product_id = oi.product_id GROUP BY 1"),
    ("distinct_orders_per_category", {"object_type": "order_item", "by": ["product.category"],
                                      "measures": [{"agg": "count_distinct", "path": "order_id"}]},
     "SELECT p.category, COUNT(DISTINCT oi.order_id) FROM order_items oi "
     "JOIN products p ON p.product_id = oi.product_id GROUP BY 1"),
    ("verified_segment", {"object_type": "order", "segment": "delivered_orders",
                          "measures": [{"agg": "avg", "path": "total_amount", "decimals": 2}]},
     "SELECT ROUND(AVG(total_amount), 2) FROM orders WHERE status = 'delivered'"),
    ("revenue_by_customer_country", {"object_type": "order", "by": ["customer.country"],
                                     "measures": [{"agg": "sum", "path": "total_amount", "decimals": 2}]},
     "SELECT c.country, ROUND(SUM(o.total_amount), 2) FROM orders o "
     "JOIN customers c ON c.customer_id = o.customer_id GROUP BY 1"),
    ("lines_per_order", {"object_type": "order", "filters": [{"path": "order_item", "op": "exists"}],
                         "measures": [{"agg": "count", "path": "order_item", "divide_by": {"agg": "count"},
                                       "decimals": 3}]},
     "SELECT ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT order_id), 3) FROM order_items"),
    # the shape of the ON-0 hard set's l13 miss: order value and items per order, per platform
    ("aov_and_items_per_order", {"object_type": "order", "by": ["payment_method"], "measures": [
        {"name": "aov", "agg": "avg", "path": "total_amount", "decimals": 2},
        {"name": "items_per_order", "agg": "count", "path": "order_item", "divide_by": {"agg": "count"},
         "decimals": 3}]},
     "WITH per_order AS (SELECT o.payment_method, o.order_id, o.total_amount, COUNT(oi.item_id) AS n "
     "FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.order_id GROUP BY 1, 2, 3) "
     "SELECT payment_method, ROUND(AVG(total_amount), 2), ROUND(AVG(n), 3) FROM per_order GROUP BY 1"),
    ("month_window_end_exclusive", {"object_type": "order", "grain": "month", "start": "2023-03-01",
                                    "end": "2023-06-01", "measures": [{"metric": "revenue"}]},
     "SELECT date_trunc('month', order_date), SUM(total_amount) FROM orders "
     "WHERE order_date >= '2023-03-01' AND order_date < '2023-06-01' GROUP BY 1"),
    ("flag_average_is_a_share", {"object_type": "product", "measures": [
        {"agg": "avg", "path": "is_out_of_stock", "scale": 100, "decimals": 2}]},
     "SELECT ROUND(100.0 * AVG(CASE WHEN is_out_of_stock THEN 1 ELSE 0 END), 2) FROM products"),
]


@pytest.mark.parametrize("case_id,query,reference", CASES, ids=[c[0] for c in CASES])
def test_compiled_answers_equal_the_hand_written_reference(warehouse, case_id, query, reference):
    compiled = _compile(query)
    assert _rows(warehouse, compiled.sql) == _rows(warehouse, reference), compiled.sql


# ── by construction ─────────────────────────────────────────────────────────────────────

def test_a_to_many_measure_is_pre_aggregated_so_the_join_cannot_fan_out(warehouse):
    compiled = _compile({"object_type": "order", "by": ["payment_method"], "measures": [
        {"name": "revenue", "agg": "sum", "path": "total_amount"},
        {"name": "lines", "agg": "count", "path": "order_item"}]})
    right = _rows(warehouse, "SELECT payment_method, SUM(total_amount), "
                             "(SELECT COUNT(*) FROM order_items i JOIN orders o2 ON o2.order_id = i.order_id "
                             " WHERE o2.payment_method = o.payment_method) FROM orders o GROUP BY 1")
    naive = _rows(warehouse, "SELECT o.payment_method, SUM(o.total_amount), COUNT(*) FROM orders o "
                             "JOIN order_items i ON i.order_id = o.order_id GROUP BY 1")
    assert _rows(warehouse, compiled.sql) == right
    assert naive != right                                   # the join the model writes does fan out here
    assert [link["treatment"] for link in compiled.links] == ["pre-aggregated"]
    assert compiled.links[0]["cardinality"] == "1:N" and compiled.links[0]["measured"] is True
    assert any("pre-aggregated per order_id before the join" in line for line in compiled.plan)


def test_a_sum_across_a_to_one_link_is_refused_as_the_fan_out():
    refused = _refusal({"object_type": "order_item", "measures": [{"agg": "sum", "path": "order.total_amount"}]})
    assert "once per OrderItem row" in refused.reason and "that is the fan-out" in refused.reason
    assert "Anchor the query on Order (object_type 'order')" in refused.reason


def test_what_repetition_cannot_change_may_cross_a_to_one_link(warehouse):
    compiled = _compile({"object_type": "order_item", "measures": [
        {"name": "orders", "agg": "count_distinct", "path": "order"},
        {"name": "biggest", "agg": "max", "path": "order.total_amount"}]})
    assert _rows(warehouse, compiled.sql) == _rows(
        warehouse, "SELECT COUNT(DISTINCT i.order_id), MAX(o.total_amount) FROM order_items i "
                   "LEFT JOIN orders o ON o.order_id = i.order_id")


def test_an_average_across_a_to_many_link_is_a_ratio_of_sums(warehouse):
    compiled = _compile({"object_type": "order", "segment": "delivered_orders",
                         "measures": [{"agg": "avg", "path": "order_item.unit_price", "decimals": 4}]})
    assert _rows(warehouse, compiled.sql) == _rows(
        warehouse, "SELECT ROUND(AVG(i.unit_price), 4) FROM order_items i "
                   "JOIN orders o ON o.order_id = i.order_id WHERE o.status = 'delivered'")
    assert any("a ratio of sums" in line for line in compiled.plan)


def test_a_filter_through_a_to_many_link_keeps_objects_with_a_match_and_not_exists_is_an_anti_join(warehouse):
    with_cancel = _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                            "filters": [{"path": "order.status", "value": "cancelled"}]})
    assert _rows(warehouse, with_cancel.sql) == _rows(
        warehouse, "SELECT COUNT(*) FROM customers c WHERE EXISTS "
                   "(SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.status = 'cancelled')")
    never = _compile({"object_type": "customer", "measures": [{"agg": "count"}],
                      "filters": [{"path": "order", "op": "not_exists"}]})
    assert _rows(warehouse, never.sql) == _rows(
        warehouse, "SELECT COUNT(*) FROM customers c WHERE NOT EXISTS "
                   "(SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id)")
    assert [link["treatment"] for link in never.links] == ["anti-join"]


def test_a_measure_where_restricts_its_rows_never_the_object_set(warehouse):
    compiled = _compile({"object_type": "order", "measures": [
        {"name": "all_orders", "agg": "count"},
        {"name": "cancelled", "agg": "count", "where": [{"path": "status", "value": "cancelled"}]}]})
    assert _rows(warehouse, compiled.sql) == _rows(
        warehouse, "SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'cancelled') FROM orders")


def test_a_segment_is_anchored_on_the_object_so_a_join_cannot_rebind_its_columns(warehouse):
    compiled = _compile({"object_type": "order", "segment": "active_orders", "by": ["customer.country"],
                         "measures": [{"agg": "count"}]})
    assert "t0.status IN ('delivered', 'cancelled')" in compiled.sql      # rendered as NOT t0.status IN (…)
    assert _rows(warehouse, compiled.sql) == _rows(
        warehouse, "SELECT c.country, COUNT(*) FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
                   "WHERE o.status NOT IN ('delivered', 'cancelled') GROUP BY 1")


def test_a_literal_is_typed_by_the_column_it_meets(warehouse):
    as_text = _compile({"object_type": "order", "measures": [{"agg": "count"}], "filters": [
        {"path": "total_amount", "op": ">", "value": "400"},
        {"path": "payment_method", "op": "in", "values": ["card", "paypal"]}]})
    assert "t0.total_amount > 400" in as_text.sql and "'400'" not in as_text.sql
    assert _rows(warehouse, as_text.sql) == _rows(
        warehouse, "SELECT COUNT(*) FROM orders WHERE total_amount > 400 AND payment_method IN ('card', 'paypal')")
    flag = _compile({"object_type": "product", "measures": [{"agg": "count"}],
                     "filters": [{"path": "is_out_of_stock", "value": "true"}]})
    assert "t0.is_out_of_stock = TRUE" in flag.sql
    assert _rows(warehouse, flag.sql) == _rows(warehouse, "SELECT COUNT(*) FROM products WHERE is_out_of_stock")
    not_a_number = _compile({"object_type": "order", "measures": [{"agg": "count"}],
                             "filters": [{"path": "total_amount", "op": ">", "value": "1; DROP TABLE orders"}]})
    assert "'1; DROP TABLE orders'" in not_a_number.sql               # stays a quoted string, never SQL


def test_literals_are_escaped_never_spliced(warehouse):
    compiled = _compile({"object_type": "order", "measures": [{"agg": "count"}],
                         "filters": [{"path": "status", "value": "x' OR '1'='1"}]})
    assert "'x'' OR ''1''=''1'" in compiled.sql
    assert _rows(warehouse, compiled.sql) == [(0,)]


# ── refusals: never a guess ─────────────────────────────────────────────────────────────

def test_an_nn_link_is_refused_both_ways():
    refused = _refusal({"object_type": "order_item", "measures": [{"agg": "count", "path": "review"}]})
    assert "is N:N by measurement" in refused.reason


def test_an_unmeasured_link_is_refused_and_the_refusal_names_the_measure_door():
    graph = _graph()
    rel = next(r for r in graph.relationships.values() if r.to_entity == "Product")
    rel.measured_cardinality = None
    refused = _refusal({"object_type": "order_item", "by": ["product.category"], "measures": [{"agg": "count"}]},
                       graph)
    assert "has never been measured" in refused.reason and "POST /ontology/measure" in refused.reason


def test_a_link_to_a_query_backed_type_is_refused_until_measured_on_that_backing():
    graph = _graph()
    graph.entities["Product"].backing = Backing(kind="query", sql="SELECT * FROM products", primary_key="product_id")
    refused = _refusal({"object_type": "order_item", "by": ["product.category"], "measures": [{"agg": "count"}]},
                       graph)
    assert "query backing" in refused.reason


def test_count_distinct_across_a_to_many_link_is_refused():
    refused = _refusal({"object_type": "order", "measures": [{"agg": "count_distinct",
                                                              "path": "order_item.product_id"}]})
    assert "does not add up over Order objects" in refused.reason


@pytest.mark.parametrize("path,phrase", [("order_id", "identifier"), ("order_date", "point in time"),
                                         ("status", "dimension")])
def test_aggregates_that_mean_nothing_are_refused(path, phrase):
    assert phrase in _refusal({"object_type": "order", "measures": [{"agg": "sum", "path": path}]}).reason


def test_unknown_names_are_refused_with_the_names_that_exist():
    typo = _refusal({"object_type": "order", "measures": [{"agg": "sum", "path": "total_amnt"}]})
    assert "did you mean 'total_amount'" in typo.reason
    no_type = _refusal({"object_type": "invoices", "measures": [{"agg": "count"}]})
    assert "order" in no_type.available and "order_item" in no_type.available
    no_link = _refusal({"object_type": "order", "measures": [{"agg": "count"}],
                        "filters": [{"path": "review", "op": "exists"}]})
    assert "its links: order_to_customer, order_to_order_item" in no_link.reason


def test_unverified_segments_and_metrics_are_refused():
    graph = _graph()
    graph.entities["Order"].segments["delivered_orders"].verified = False
    graph.metrics["revenue"].verified = False
    assert "is not verified" in _refusal({"object_type": "order", "segment": "delivered_orders",
                                          "measures": [{"agg": "count"}]}, graph).reason
    assert "is not verified" in _refusal({"object_type": "order", "measures": [{"metric": "revenue"}]},
                                         graph).reason


def test_a_malformed_query_and_a_bad_window_are_refusals_not_crashes():
    assert "malformed" in _refusal({"object_type": "order"}).reason
    assert "ISO date" in _refusal({"object_type": "order", "start": "last quarter",
                                   "measures": [{"agg": "count"}]}).reason


def test_the_query_renders_for_the_connections_dialect():
    query = {"object_type": "order", "grain": "month", "measures": [{"metric": "revenue"}]}
    bigquery = _compile(query, dialect="bigquery")
    # order_date is a DATE: BigQuery's TIMESTAMP_TRUNC would reject it, so the trunc is typed
    assert bigquery.dialect == "bigquery" and "DATE_TRUNC(t0.order_date, MONTH)" in bigquery.sql
    assert "DATE_TRUNC('MONTH', t0.order_date)" in _compile(query, dialect="postgres").sql


# ── the catalog names only what compiles ────────────────────────────────────────────────

def test_the_catalog_lists_usable_links_and_says_why_the_others_are_not():
    catalog = {t["object_type"]: t for t in object_catalog(_graph())["object_types"]}
    order_links = {link["name"]: link for link in catalog["order"]["links"]}
    assert order_links["order_to_order_item"]["usable"] and order_links["order_to_order_item"]["cardinality"] == "1:N"
    review = next(link for link in catalog["order_item"]["links"] if link["to"] == "review")
    assert review["usable"] is False and "N:N" in review["why_not"]
    assert "delivered_orders" in catalog["order"]["segments"] and catalog["order"]["metrics"] == ["aov", "revenue"]
    text = render_object_catalog(object_catalog(_graph()))
    assert "order_to_order_item → order_item [1:N]" in text and "not traversable: order_item_to_review [N:N]" in text
