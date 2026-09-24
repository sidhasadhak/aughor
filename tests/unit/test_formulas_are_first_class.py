"""PENDING item 27 — formula fields and computed properties are first-class.

Measured 2026-09-24 by reading, each fixed at its cause:

* an expression read the backing's own columns only — a formula could not use a type's linked tables;
* it was verified on ONE row (the builder's computed properties too), so a formula that fails past the first row
  verified;
* neither kind was ever shown on the object page — neither is a column of the backing row;
* the builder's own verified computed properties (`Customer.days_since_signup`) could not be used in object queries;
* a formula on a type read from another connection was read as a column (tests/unit/test_object_sources.py).

On the real samples warehouse, every value checked against hand-written SQL.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.expressions import expression_problem, probe_expression
from aughor.ontology.models import ExpressionProperty, OntologyGraph
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query

GRAPH = Path(__file__).resolve().parents[2] / "evals" / "ablation_samples_ecommerce_ontology_measured.json"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples27") / "samples.duckdb"
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.close()
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="formulas-27")
    yield conn
    conn.close()


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr("aughor.explorer.store.get_findings", lambda key: [])
    return OntologyGraph.model_validate(json.loads(GRAPH.read_text()))


def _declared(graph, type_id, name, expression):
    entity = graph.entities[type_id]
    entity.expressions[name] = ExpressionProperty(expression=expression, verified=True)
    entity.properties[name] = entity.expressions[name].as_property(name)


def _one(db, sql):
    return db.execute("reference", sql).rows[0]


def _run(db, graph, query):
    return db.execute("probe", compile_object_query(query, graph, dialect="duckdb").sql).rows


# ── the builder's computed properties, in queries ────────────────────────────────────────────

def test_a_computed_property_the_builder_verified_is_a_property_the_door_reads(db, graph):
    rows = _run(db, graph, {"object_type": "customer", "filters": [{"path": "customer_id", "value": "C00042"}],
                            "measures": [{"name": "d", "agg": "max", "path": "days_since_signup"},
                                         {"name": "aov", "agg": "max", "path": "avg_order_value"}]})
    assert rows[0] == list(_one(db, "SELECT CURRENT_DATE - signup_date, lifetime_spend / NULLIF(lifetime_orders, 0) "
                                    "FROM customers WHERE customer_id = 'C00042'"))
    over_a_year = _run(db, graph, {"object_type": "customer", "measures": [{"name": "n", "agg": "count"}],
                                   "filters": [{"path": "days_since_signup", "op": ">", "value": 365}]})
    assert over_a_year[0][0] == _one(db, "SELECT COUNT(*) FROM customers WHERE CURRENT_DATE - signup_date > 365")[0]


# ── formulas over linked tables ─────────────────────────────────────────────────────────────

def test_a_formula_reads_a_linked_type_and_another_formula(db, graph):
    _declared(graph, "Order", "spend_share", "total_amount / NULLIF(order_to_customer.lifetime_spend, 0)")
    _declared(graph, "Order", "shipped_late", "days_to_ship > 3")          # over a computed property
    rows = _run(db, graph, {"object_type": "order", "filters": [{"path": "order_id", "value": "O000123"}],
                            "measures": [{"name": "s", "agg": "max", "path": "spend_share"},
                                         {"name": "l", "agg": "max", "path": "shipped_late"}]})
    assert rows[0] == list(_one(db, "SELECT o.total_amount / NULLIF(c.lifetime_spend, 0), "
                                    "(o.shipped_at - o.order_date) > 3 FROM orders o "
                                    "JOIN customers c USING (customer_id) WHERE o.order_id = 'O000123'"))


def test_a_formula_that_reaches_itself_is_refused_with_the_chain(graph):
    _declared(graph, "Order", "loop_a", "loop_b + 1")
    _declared(graph, "Order", "loop_b", "loop_a + 1")
    with pytest.raises(ObjectQueryRefused, match=r"reaches itself \(Order.loop_a → Order.loop_b → Order.loop_a\)"):
        compile_object_query({"object_type": "order", "measures": [{"name": "x", "agg": "max", "path": "loop_a"}]},
                             graph)


def test_the_door_reads_what_the_compiler_reads_and_says_why_not(graph):
    order = graph.entities["Order"]
    ok = {"expression": "total_amount / NULLIF(order_to_customer.lifetime_spend, 0)", "semantic_type": "measure"}
    assert expression_problem(order, "spend_share", ok, graph) == ""
    stray = {"expression": "order_to_customer.no_such_column * 2", "semantic_type": "measure"}
    assert "Customer has no property 'no_such_column'" in expression_problem(order, "x", stray, graph)
    itself = {"expression": "spend_share + 1", "semantic_type": "measure"}
    assert "reads itself" in expression_problem(order, "spend_share", itself, graph)


# ── verified on more than one row ────────────────────────────────────────────────────────────

def test_a_formula_that_fails_past_the_first_row_does_not_verify(db, graph):
    first = _one(db, "SELECT customer_id FROM customers LIMIT 1")[0]
    breaks = f"CAST(CASE WHEN customer_id = '{first}' THEN '1' ELSE 'x' END AS INTEGER)"
    assert db.execute("old", f"SELECT ({breaks}) FROM customers LIMIT 1").error is None, "the old one-row probe binds it"
    verdict = probe_expression(db, graph, graph.entities["Customer"], breaks, name="breaks")
    assert verdict["bound"] is False and "did not execute" in verdict["note"]


def test_a_formula_that_is_empty_on_every_object_does_not_verify(db, graph):
    verdict = probe_expression(db, graph, graph.entities["Customer"], "CASE WHEN 1 = 0 THEN 1 END", name="never")
    assert verdict["bound"] is False and "empty on every one of the" in verdict["note"]


def test_a_good_formula_verifies_on_the_objects_it_was_checked_on(db, graph):
    verdict = probe_expression(db, graph, graph.entities["Order"],
                               "total_amount / NULLIF(order_to_customer.lifetime_spend, 0)", name="spend_share")
    n = min(1000, int(_one(db, "SELECT COUNT(*) FROM orders")[0]))
    assert verdict["bound"] is True and verdict["rows_checked"] == n and verdict["non_null"] > 0


def test_the_builders_computed_properties_are_verified_on_many_rows_too(db):
    from aughor.ontology.validator import _verify_formula_rows
    first = _one(db, "SELECT customer_id FROM customers LIMIT 1")[0]
    assert _verify_formula_rows(db, "CURRENT_DATE - signup_date", "customers") == (True, "")
    ok, note = _verify_formula_rows(db, f"CAST(CASE WHEN customer_id = '{first}' THEN '1' ELSE 'x' END AS INTEGER)",
                                    "customers")
    assert ok is False and "did not execute" in note


# ── shown on the object page ─────────────────────────────────────────────────────────────────

def test_the_object_page_shows_each_formula_evaluated_for_the_object(db, graph):
    from aughor.semantic.object_instances import get_object
    _declared(graph, "Customer", "spend_per_signup_day", "lifetime_spend / NULLIF(days_since_signup, 0)")
    customer = get_object(graph, db, "customer", "C00042")
    shown = {p["name"]: p for p in customer.properties if p.get("formula")}
    assert set(shown) >= {"days_since_signup", "avg_order_value", "spend_per_signup_day"}
    days, aov = _one(db, "SELECT CURRENT_DATE - signup_date, lifetime_spend / NULLIF(lifetime_orders, 0) "
                         "FROM customers WHERE customer_id = 'C00042'")
    assert str(shown["days_since_signup"]["value"]) == str(days) and shown["days_since_signup"]["formula"] == {
        "expression": "CURRENT_DATE - signup_date", "kind": "computed"}
    assert str(shown["avg_order_value"]["value"]) == str(aov)
    assert shown["spend_per_signup_day"]["formula"]["kind"] == "expression"


def test_a_formula_the_compiler_refuses_is_said_on_the_page_and_costs_only_itself(db, graph):
    from aughor.ontology.models import ComputedProperty
    from aughor.semantic.object_instances import get_object
    graph.entities["Customer"].computed_properties.insert(      # FIRST, so the ones after it prove it cost only itself
        0, ComputedProperty(id="orders_ever", label="Orders ever", formula_sql="COUNT(*)", verified=True))
    customer = get_object(graph, db, "customer", "C00042")
    assert any(c.startswith("orders_ever is not shown") and "aggregate" in c for c in customer.caveats)
    assert any(p["name"] == "days_since_signup" for p in customer.properties)
