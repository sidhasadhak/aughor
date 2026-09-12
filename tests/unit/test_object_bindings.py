"""ON-1b — bindings: each property knows its source.

An object type's first binding is its backing; a further binding is a table or keyed SELECT joined to the object on
its key. Every claim here is held to a hand-written count or query over the seeded samples warehouse, plus three
tables this file adds: `payments` (one row for 4,500 of the 5,000 orders, and 7 payments for orders that do not
exist), `refunds` (several rows for some orders) and `order_events` (many rows per order over time). A static binding
is joined only when the data proves it one row per object; a refuted or unmeasured one is refused with the reason
(a timeseries binding is reduced to each object's latest row instead — ON-5, `test_object_timeseries`); a proposal changes nothing until a person binds it; and a compiled query that reads a bound
property equals its hand-written reference.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
import yaml

import aughor.mcp.knowledge_tools as KT
from aughor.db.connection import open_connection
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology.backing import apply_backing_measurements
from aughor.ontology.bindings import (
    bind_binding,
    binding_block,
    binding_spec,
    column_profiles,
    declared_bindings,
    describe_with,
    measure_binding,
    propose_bindings,
    select_lineage,
)
from aughor.ontology.filetree import export_tree, import_tree
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
from aughor.semantic.object_instances import get_object
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
from aughor.semantic.object_types import describe_object_type, object_type_map

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
LUX = REPO / "evals" / "ablation_luxexperience_ontology.json"

_EXTRA = """
CREATE TABLE ecommerce.payments AS
SELECT printf('PAY%06d', i) AS payment_id, printf('O%06d', i) AS order_id,
       CASE i % 3 WHEN 0 THEN 'visa' WHEN 1 THEN 'mastercard' ELSE 'amex' END AS psp,
       CASE WHEN i % 4 = 0 THEN 'captured' ELSE 'settled' END AS status,
       ROUND((15 + (i * 23.7) % 485)::NUMERIC, 2) AS amount,
       i % 11 = 0 AS fraud_flag,
       1 + i % 6 AS installments
FROM range(1, 5001) t(i) WHERE i % 10 <> 0
UNION ALL
SELECT printf('PAYX%03d', i), printf('O9%05d', i), 'visa', 'settled', 1.00, false, 1 FROM range(1, 8) t(i);
CREATE TABLE ecommerce.refunds AS
SELECT printf('O%06d', 1 + (i * 7) % 300) AS order_id, ROUND((i % 50) + 0.5, 2) AS refund_amount
FROM range(1, 401) t(i);
CREATE TABLE ecommerce.order_events AS
SELECT printf('O%06d', 1 + i % 2000) AS order_id, TIMESTAMP '2023-01-01 00:00:00' + (i || ' hours')::INTERVAL AS event_at,
       CASE i % 3 WHEN 0 THEN 'packed' WHEN 1 THEN 'in_transit' ELSE 'delivered' END AS event
FROM range(1, 6001) t(i);
"""

PAYMENTS = {"table": "payments", "key": "order_id"}


def seed(path: Path) -> None:
    con = duckdb.connect(str(path))
    _seed_ecommerce(con)
    con.execute(_EXTRA)
    con.close()


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("bindings") / "samples.duckdb"
    seed(path)
    conn = open_connection("duckdb", str(path), schema_name="ecommerce", connection_id="bindings-t")
    yield conn
    conn.close()


def payment_type() -> OntologyEntity:
    """The type the builder makes of `payments` — its profile is what a binding from that table borrows."""
    columns = [("payment_id", "VARCHAR", "key"), ("order_id", "VARCHAR", "key"), ("psp", "VARCHAR", "dimension"),
               ("status", "VARCHAR", "dimension"), ("amount", "DECIMAL(18,2)", "measure"),
               ("fraud_flag", "BOOLEAN", "flag"), ("installments", "BIGINT", "ordinal")]
    return OntologyEntity(id="Payment", display_name="Payment", source_tables=["payments"], identity_key="payment_id",
                          grain_verified=True,
                          properties={c: EntityProperty(name=c, data_type=t, semantic_type=r,
                                                        is_primary_key=c == "payment_id") for c, t, r in columns})


@pytest.fixture
def graph():
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    g.entities["Payment"] = payment_type()
    return g


@pytest.fixture(autouse=True)
def _isolated_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")


def bind(graph: OntologyGraph, db, entity_id: str, name: str, spec: dict, *, count: bool = True) -> OntologyEntity:
    """The door's path without HTTP: bind against the warehouse, rebuild as the overlay will, count, attach."""
    entity = graph.entities[entity_id]
    entry = bind_binding(entity, name, spec, graph, describe_with(db))
    assert entry["bound"], entry["note"]
    built, skipped = declared_bindings(entity.model_copy(update={"bindings": []}), {name: entry["spec"]},
                                       {"entries": {name: entry}}, graph)
    assert not skipped, skipped
    [binding] = built
    if count:
        measure_binding(db, entity, binding).stamp(binding)
    entity.bindings = [*entity.bindings, binding]
    return entity


def ints(db, sql: str) -> list[int]:
    result = db.execute("reference", sql)
    assert not result.error, (result.error, sql)
    return [int(v) for v in result.rows[0]]                     # the connection hands cells back as text


def rows(db, sql: str) -> list[tuple]:
    result = db.execute("reference", sql)
    assert not result.error, (result.error, sql)

    def cell(v):
        if v is None:
            return None
        try:
            return round(float(v), 4)
        except (TypeError, ValueError):
            return str(v)
    return sorted((tuple(cell(v) for v in row) for row in result.rows), key=repr)


def compile_(query: dict, graph: OntologyGraph):
    return compile_object_query(query, graph, fiscal_start_month=1)


def refusal(query: dict, graph: OntologyGraph) -> ObjectQueryRefused:
    with pytest.raises(ObjectQueryRefused) as exc:
        compile_(query, graph)
    return exc.value


# ── the model: nothing built before changes ─────────────────────────────────────────────────

def test_a_graph_built_before_bindings_loads_with_none_and_every_field_unchanged():
    raw = json.loads(LUX.read_text())
    g = OntologyGraph.model_validate(raw)
    for eid, e in g.entities.items():
        assert e.bindings == [] and e.proposed_bindings == []
        dumped = e.model_dump()
        assert all(dumped[k] == raw["entities"][eid][k] for k in raw["entities"][eid])   # byte-identical, nested too
    compiled = compile_({"object_type": "order", "measures": [{"agg": "count"}]}, g)
    assert compiled.bindings == [] and "JOIN" not in compiled.sql


# ── the measurement ─────────────────────────────────────────────────────────────────────────

def test_a_static_binding_on_the_objects_key_is_counted_one_row_per_object_with_its_coverage(db, graph):
    [binding] = bind(graph, db, "Order", "payments", PAYMENTS).bindings
    rows_, non_null, distinct = ints(db, "SELECT COUNT(*), COUNT(order_id), COUNT(DISTINCT order_id) FROM payments")
    (objects,) = ints(db, "SELECT COUNT(DISTINCT order_id) FROM orders")
    (covered,) = ints(db, "SELECT COUNT(*) FROM orders o WHERE EXISTS "
                          "(SELECT 1 FROM payments p WHERE p.order_id = o.order_id)")
    (orphans,) = ints(db, "SELECT COUNT(DISTINCT p.order_id) FROM payments p WHERE NOT EXISTS "
                          "(SELECT 1 FROM orders o WHERE o.order_id = p.order_id)")
    assert (binding.rows, binding.non_null, binding.distinct, binding.objects, binding.covered, binding.orphans) == (
        rows_, non_null, distinct, objects, covered, orphans)
    assert (covered, orphans, binding.verified) == (4500, 7, True)    # the fixture's shape, measured, not assumed
    assert "covers 4,500 of 5,000 Order objects; 7 of its keys reach no Order" in binding.note
    assert set(binding.properties) == {"payment_id", "psp", "amount", "fraud_flag", "installments"}
    assert binding.skipped["status"].startswith("Order already has the property status")
    assert binding.properties["amount"].data_type == "DECIMAL(18,2)"    # the profile of the table, borrowed


def test_a_binding_whose_key_repeats_is_refuted_and_never_joined_or_read(db, graph):
    order = bind(graph, db, "Order", "refunds", {"table": "refunds", "key": "order_id"})
    [binding] = order.bindings
    assert binding.verified is False and "NOT one row per Order" in binding.note
    why = refusal({"object_type": "order", "filters": [{"path": "refund_amount", "op": ">", "value": 10}],
                   "measures": [{"agg": "count"}]}, graph).reason
    assert "refunds" in why and "refuted by measurement" in why
    page = get_object(graph, db, "order", "O000008")
    assert not any(p.get("binding") for p in page.properties)
    assert any(c.startswith("not read from refunds:") for c in page.caveats)


def test_a_unique_binding_whose_key_reaches_no_object_is_refuted(db, graph):
    [binding] = bind(graph, db, "Order", "payments_by_id", {"table": "payments", "key": "payment_id"}).bindings
    (payments,) = ints(db, "SELECT COUNT(DISTINCT payment_id) FROM payments")
    assert (binding.verified, binding.distinct, binding.covered, binding.orphans) == (False, payments, 0, payments)
    assert binding.note.endswith("its key reaches no Order")        # unique, and joined on the wrong key
    why = refusal({"object_type": "order", "filters": [{"path": "psp", "value": "visa"}],
                   "measures": [{"agg": "count"}]}, graph).reason
    assert "refuted by measurement" in why


def test_an_unmeasured_binding_is_refused_until_it_is_counted(db, graph):
    order = bind(graph, db, "Order", "payments", PAYMENTS, count=False)
    query = {"object_type": "order", "filters": [{"path": "psp", "value": "visa"}], "measures": [{"agg": "count"}]}
    assert "unmeasured" in refusal(query, graph).reason
    measure_binding(db, order, order.bindings[0]).stamp(order.bindings[0])
    assert compile_(query, graph).bindings[0]["binding"] == "payments"


def test_a_timeseries_binding_is_counted_on_reach_not_on_uniqueness(db, graph):
    """Its key repeats by definition, so the static verdict would refute every one of them. What is counted is
    whether it REACHES objects; what is then read is each object's latest row (ON-5, test_object_timeseries)."""
    spec = {"table": "order_events", "key": "order_id", "kind": "timeseries", "time_column": "event_at"}
    [binding] = bind(graph, db, "Order", "events", spec).bindings
    non_null, distinct = ints(db, "SELECT COUNT(order_id), COUNT(DISTINCT order_id) FROM order_events")
    assert distinct < non_null                      # many rows per object — a static binding would be refuted here
    assert (binding.verified, binding.non_null, binding.distinct, binding.covered, binding.orphans) == (
        True, non_null, distinct, distinct, 0)
    compiled = compile_({"object_type": "order", "filters": [{"path": "event", "value": "packed"}],
                         "measures": [{"agg": "count"}]}, graph)
    assert compiled.bindings[0]["treatment"] == "latest"
    page = get_object(graph, db, "order", "O000001")
    assert {p["name"] for p in page.properties if p.get("binding")} == {"event_at", "event"} and not page.caveats


# ── names: a binding adds properties and never shadows one ──────────────────────────────────

def test_a_binding_adds_properties_and_refuses_what_it_cannot_take(db, graph):
    order, describe = graph.entities["Order"], describe_with(db)
    renamed = bind_binding(order, "payments", {"table": "payments", "key": "ORDER_ID",
                                               "properties": {"payment_status": "status", "psp": "PSP"}},
                           graph, describe)
    assert renamed["bound"] and renamed["supplies"] == {"payment_status": "status", "psp": "psp"}
    assert renamed["spec"]["key"] == "order_id"                     # spelled as the warehouse spells it
    refused = [
        ({"table": "payments", "key": "order_id", "properties": {"status": "status"}}, "already has the property status"),
        ({"table": "payments", "key": "order_id", "properties": {"order_to_customer": "psp"}}, "has a link named"),
        ({"table": "payments", "key": "order_ref"}, "no column 'order_ref'"),
        ({"table": "payments", "key": "order_id", "properties": {"method": "nope"}}, "no column 'nope'"),
        ({"table": "payments", "key": "order_id", "properties": {"order_id": "order_id"}}, "binding's key"),
        ({"table": "orders", "key": "order_id"}, "already backs Order"),
        ({"table": "no_such_table", "key": "order_id"}, "could not be read"),
        ({"table": "payments", "key": "order_id", "kind": "timeseries"}, "names its `time_column`"),
        ({"table": "order_events", "key": "order_id", "kind": "timeseries", "time_column": "at"}, "no time column"),
        ({"table": "payments", "key": "order_id", "time_column": "amount"}, "belongs to a timeseries"),
        ({"table": "payments", "sql": "SELECT 1", "key": "order_id"}, "exactly one of"),
        ({"sql": "SELECT * FROM payments; DROP TABLE orders", "key": "order_id"}, "one SELECT"),
        ({"table": "payments; DROP TABLE orders", "key": "order_id"}, "not a table identifier"),
    ]
    for spec, why in refused:
        entry = bind_binding(order, "payments", spec, graph, describe)
        assert entry["bound"] is False and why in entry["note"], (spec, entry)
    assert "snake_case" in bind_binding(order, "Payments", PAYMENTS, graph, describe)["note"]
    assert "backing" in bind_binding(order, "orders", PAYMENTS, graph, describe)["note"]


def _numeric(data_type: str) -> bool:
    return any(t in data_type.upper() for t in ("DECIMAL", "DOUBLE", "INT", "NUMERIC", "FLOAT", "REAL"))


def test_a_keyed_select_carries_the_warehouse_types_and_borrows_roles_only_through_pass_through_columns(db, graph):
    spec = {"sql": "SELECT p.order_id, p.payment_id, p.psp AS processor, p.amount AS settled, p.amount * 2 AS doubled, "
                   "CAST(p.amount AS VARCHAR) AS amount_text, p.fraud_flag FROM payments p WHERE p.status = 'settled'",
            "key": "order_id"}
    [binding] = bind(graph, db, "Order", "settlements", spec).bindings
    assert binding.reads == "query" and binding.verified is True
    props = binding.properties
    assert set(props) == {"payment_id", "processor", "settled", "doubled", "amount_text", "fraud_flag"}
    # a pass-through column borrows its source column's profile — renamed — and keeps the type the warehouse reported
    assert (props["processor"].semantic_type, props["processor"].data_type) == ("dimension", "VARCHAR")
    assert props["settled"].semantic_type == "measure" and _numeric(props["settled"].data_type)
    assert props["payment_id"].semantic_type == "key" and props["fraud_flag"].semantic_type == "flag"
    assert "BOOL" in props["fraud_flag"].data_type.upper()
    # a computed column keeps the type it was reported with and borrows no role; a cast is not the column it casts
    assert props["doubled"].semantic_type == "" and _numeric(props["doubled"].data_type)
    assert (props["amount_text"].semantic_type, props["amount_text"].data_type) == ("", "VARCHAR")

    by_processor = compile_({"object_type": "order", "by": ["processor"],
                             "measures": [{"agg": "sum", "path": "settled", "decimals": 2},
                                          {"agg": "sum", "path": "doubled", "decimals": 2}]}, graph)
    assert rows(db, by_processor.sql) == rows(db, "SELECT p.psp, ROUND(SUM(p.amount), 2), ROUND(SUM(p.amount * 2), 2) "
                                                  "FROM orders o LEFT JOIN (SELECT * FROM payments WHERE status = "
                                                  "'settled') p ON p.order_id = o.order_id GROUP BY 1")
    over = compile_({"object_type": "order", "filters": [{"path": "settled", "op": ">", "value": "400"}],
                     "measures": [{"agg": "count"}]}, graph)
    assert "> 400" in over.sql and "'400'" not in over.sql          # a numeric string meets a typed column as a number
    assert rows(db, over.sql) == rows(db, "SELECT COUNT(*) FROM orders o JOIN payments p ON p.order_id = o.order_id "
                                          "WHERE p.status = 'settled' AND p.amount > 400")
    assert "identifier" in refusal({"object_type": "order", "measures": [{"agg": "sum", "path": "payment_id"}]},
                                   graph).reason
    assert "not a known quantity" in refusal({"object_type": "order",
                                              "measures": [{"agg": "sum", "path": "amount_text"}]}, graph).reason


def test_lineage_traces_only_a_column_the_select_passes_through_from_one_of_its_own_tables(graph):
    traced = select_lineage(
        "SELECT o.order_id, p.psp AS processor, status, amount, o.total_amount * 2 AS twice, "
        "CAST(p.amount AS VARCHAR) AS amount_text, (SELECT MAX(rating) FROM reviews) AS best "
        "FROM orders o JOIN payments AS p ON p.order_id = o.order_id", graph)
    assert traced["order_id"] == ("orders", "order_id") and traced["processor"] == ("payments", "psp")
    assert traced["amount"] == ("payments", "amount")           # unqualified, and only payments carries it
    assert "status" not in traced                                # orders and payments both carry status: not guessed
    assert not {"twice", "amount_text", "best"} & set(traced)    # an expression, a cast, a subquery
    assert set(select_lineage("SELECT p.* FROM payments p JOIN orders o ON o.order_id = p.order_id", graph)) == set(
        graph.entities["Payment"].properties)
    assert select_lineage("WITH x AS (SELECT * FROM payments) SELECT x.psp FROM x", graph) == {}
    assert select_lineage("SELECT psp FROM (SELECT * FROM payments) s", graph) == {}
    assert select_lineage("SELECT * FROM payments p JOIN orders o ON o.order_id = p.order_id", graph) == {}
    assert select_lineage("SELECT order_id FROM payments UNION SELECT order_id FROM orders", graph) == {}
    assert select_lineage("this is not a select", graph) == {}


def test_a_connector_without_typed_results_still_binds_and_the_profile_types_its_pass_through_columns(db, graph):
    class Untyped:                                  # reports columns, never types
        def execute(self, label, sql):
            return db.execute(label, sql)

    sql = "SELECT p.order_id, p.amount AS settled, p.amount * 2 AS doubled FROM payments p"
    entry = bind_binding(graph.entities["Order"], "settlements", {"sql": sql, "key": "order_id"}, graph,
                         describe_with(Untyped()))
    assert entry["bound"] and entry["columns"] == {"order_id": "", "settled": "", "doubled": ""}
    typed = column_profiles(graph, None, entry["columns"], sql)
    assert typed["settled"].data_type == "DECIMAL(18,2)" and typed["settled"].semantic_type == "measure"
    assert (typed["doubled"].data_type, typed["doubled"].semantic_type) == ("", "")   # nothing typed it: not added up

    class Misaligned(Untyped):                      # reports fewer types than columns — positional, so none is trusted
        def execute_typed(self, label, sql):
            return db.execute(label, sql), {"types": ["VARCHAR"]}

    columns, error = describe_with(Misaligned())(f"({sql}) AS b")
    assert error is None and columns == {"order_id": "", "settled": "", "doubled": ""}


def test_a_table_the_graph_never_profiled_binds_with_the_types_the_warehouse_reports(db, graph):
    [binding] = bind(graph, db, "Order", "refunds", {"table": "refunds", "key": "order_id"}).bindings
    assert _numeric(binding.properties["refund_amount"].data_type)


# ── the receipt: a compiled query through the key join equals its hand-written reference ────

BOUND_CASES = [
    ("filter_on_a_bound_property",
     {"object_type": "order", "filters": [{"path": "psp", "value": "amex"}],
      "measures": [{"agg": "count"}, {"agg": "sum", "path": "total_amount", "decimals": 2}]},
     "SELECT COUNT(*), ROUND(SUM(o.total_amount), 2) FROM orders o JOIN payments p ON p.order_id = o.order_id "
     "WHERE p.psp = 'amex'"),
    ("renamed_property_keeps_its_column",
     {"object_type": "order", "filters": [{"path": "payment_status", "value": "captured"}],
      "measures": [{"agg": "count"}]},
     "SELECT COUNT(*) FROM orders o JOIN payments p ON p.order_id = o.order_id WHERE p.status = 'captured'"),
    ("dimension_from_a_bound_property_keeps_the_unpaid",
     {"object_type": "order", "by": ["psp"], "measures": [{"agg": "count"}]},
     "SELECT p.psp, COUNT(*) FROM orders o LEFT JOIN payments p ON p.order_id = o.order_id GROUP BY 1"),
    ("sum_of_a_bound_measure",
     {"object_type": "order", "by": ["status"], "measures": [{"agg": "sum", "path": "amount", "decimals": 2}]},
     "SELECT o.status, ROUND(SUM(p.amount), 2) FROM orders o LEFT JOIN payments p ON p.order_id = o.order_id "
     "GROUP BY 1"),
    ("share_of_a_bound_flag",
     {"object_type": "order", "measures": [{"agg": "avg", "path": "fraud_flag", "scale": 100, "decimals": 2}]},
     "SELECT ROUND(100.0 * AVG(CAST(p.fraud_flag AS INTEGER)), 2) FROM orders o "
     "JOIN payments p ON p.order_id = o.order_id"),
    ("through_a_to_one_link",
     {"object_type": "order_item", "filters": [{"path": "order.psp", "value": "visa"}],
      "measures": [{"agg": "sum", "path": "line_total", "decimals": 2}]},
     "SELECT ROUND(SUM(oi.line_total), 2) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
     "JOIN payments p ON p.order_id = o.order_id WHERE p.psp = 'visa'"),
    ("exists_through_a_to_many_link",
     {"object_type": "customer", "filters": [{"path": "order.psp", "value": "amex"}], "measures": [{"agg": "count"}]},
     "SELECT COUNT(*) FROM customers c WHERE EXISTS (SELECT 1 FROM orders o JOIN payments p "
     "ON p.order_id = o.order_id WHERE o.customer_id = c.customer_id AND p.psp = 'amex')"),
    # Every GB customer's orders are the unpaid tenth (order i % 10 == 0), so GB is kept and reads empty: the customers
    # exist, their orders carry no payment row. The reference is the question's own chain of LEFT JOINs.
    ("pre_aggregated_through_a_to_many_link",
     {"object_type": "customer", "by": ["country"], "measures": [{"agg": "sum", "path": "order.amount", "decimals": 2}]},
     "SELECT c.country, ROUND(SUM(p.amount), 2) FROM customers c LEFT JOIN orders o ON o.customer_id = c.customer_id "
     "LEFT JOIN payments p ON p.order_id = o.order_id GROUP BY 1"),
]


@pytest.mark.parametrize("case_id,query,reference", BOUND_CASES, ids=[c[0] for c in BOUND_CASES])
def test_a_query_reading_a_bound_property_equals_its_hand_written_reference(db, graph, case_id, query, reference):
    bind(graph, db, "Order", "payments",
         {**PAYMENTS, "properties": {"psp": "psp", "amount": "amount", "fraud_flag": "fraud_flag",
                                     "payment_status": "status"}})
    compiled = compile_(query, graph)
    assert rows(db, compiled.sql) == rows(db, reference), compiled.sql
    assert [b["binding"] for b in compiled.bindings] == ["payments"]
    assert any(line.startswith("binding payments on Order: payments joined on order_id = order_id") for line in compiled.plan)


def test_joining_a_binding_never_multiplies_the_objects(db, graph):
    bind(graph, db, "Order", "payments", PAYMENTS)
    compiled = compile_({"object_type": "order", "by": ["psp"], "measures": [{"agg": "count"}]}, graph)
    assert sum(int(r[1]) for r in rows(db, compiled.sql)) == ints(db, "SELECT COUNT(*) FROM orders")[0]


# ── the proposal: the data names a binding, and nothing reads it ────────────────────────────

def test_proposals_name_tables_that_carry_a_key_one_row_per_object_and_change_nothing(db, graph):
    graph.entities["Refund"] = OntologyEntity(
        id="Refund", display_name="Refund", source_tables=["refunds"], identity_key="order_id", grain_verified=False,
        properties={"order_id": EntityProperty(name="order_id", data_type="VARCHAR", semantic_type="key"),
                    "refund_amount": EntityProperty(name="refund_amount", data_type="DECIMAL", semantic_type="measure")})
    apply_backing_measurements(graph, db)
    asked = propose_bindings(graph, db)
    order = graph.entities["Order"]
    [proposal] = [p for p in order.proposed_bindings if p.kind == "static"]
    assert (proposal.name, proposal.table, proposal.key, proposal.source, proposal.verified) == (
        "payments", "payments", "order_id", "proposed", True)
    assert "status" in proposal.skipped and proposal.covered == 4500
    refuted = {m.name: m.verified for m in asked if m.entity_id == "Order" and m.kind == "static"}
    assert refuted["refunds"] is False and refuted["order_items"] is False       # asked, and the data said no
    # ON-7 — a key that REPEATS is many rows per object: proposed as a part (a detail binding), never as static
    assert {p.name for p in order.proposed_bindings if p.kind == "detail"} >= {"refunds", "order_items"}
    assert all(p.kind == "detail" for eid, e in graph.entities.items() if eid != "Order" for p in e.proposed_bindings)

    query = {"object_type": "order", "filters": [{"path": "psp", "value": "visa"}], "measures": [{"agg": "count"}]}
    assert "no property 'psp'" in refusal(query, graph).reason                  # a proposal is read by nothing
    assert not any(p.get("binding") for p in get_object(graph, db, "order", "O000001").properties)
    described = describe_object_type(graph, "order")
    assert len(described["bindings"]) == 1
    payments = next(p for p in described["proposed_bindings"] if p["name"] == "payments")
    assert payments["spec"] == {"kind": "static", "key": "order_id", "table": "payments"}

    bind(graph, db, "Order", "payments", payments["spec"])
    assert compile_(query, graph).bindings[0]["binding"] == "payments"          # bound by a person, it is read
    assert not any(p["kind"] == "static" for p in describe_object_type(graph, "order")["proposed_bindings"])   # and no longer proposed


# ── what a person and the agent read ────────────────────────────────────────────────────────

def test_the_type_lists_every_binding_and_every_property_with_its_source(db, graph):
    order = bind(graph, db, "Order", "payments",
                 {**PAYMENTS, "properties": {"payment_status": "status", "psp": "psp", "amount": "amount"}})
    d = describe_object_type(graph, "order")
    primary, payments = d["bindings"]
    assert (primary["name"], primary["primary"], primary["kind"], primary["reads"], primary["table"]) == (
        "orders", True, "static", "table", "orders")
    assert (payments["name"], payments["kind"], payments["table"], payments["key"], payments["object_key"],
            payments["verified"], payments["usable"], payments["supplies"], payments["covered"]) == (
        "payments", "static", "payments", "order_id", "order_id", True, True, 3, 4500)
    sources = {p["name"]: p["source"] for p in d["properties"]}
    assert sources["payment_status"] == {"binding": "payments", "table": "payments", "column": "status", "kind": "static"}
    assert sources["total_amount"] == {"binding": "orders", "table": "orders", "column": "total_amount"}
    assert d["counts"]["bindings"] == 2 and d["counts"]["properties"] == len(order.properties) + 3
    assert ", 3 from payments (a static binding)" in d["summary"]
    row = next(t for t in object_type_map(graph)["object_types"] if t["object_type"] == "order")
    assert (row["bindings"], row["properties"]) == (2, len(order.properties) + 3)

    order.bindings[0].verified = None
    assert "(a static binding the compiler does not read yet)" in describe_object_type(graph, "order")["summary"]
    unread = {p["name"]: p["source"] for p in describe_object_type(graph, "order")["properties"]}
    assert unread["psp"]["read"] is False


def test_an_object_page_reads_its_bound_properties_by_its_key(db, graph):
    bind(graph, db, "Order", "payments", {**PAYMENTS, "properties": {"psp": "psp", "payment_status": "status"}})
    page = get_object(graph, db, "order", "O000004")
    bound = {p["name"]: p for p in page.properties if p.get("binding")}
    [[psp, status]] = [[str(v) for v in r] for r in db.execute(
        "reference", "SELECT psp, status FROM payments WHERE order_id = 'O000004'").rows]
    assert (str(bound["psp"]["value"]), str(bound["payment_status"]["value"])) == (psp, status)
    assert bound["payment_status"]["binding"] == {"name": "payments", "kind": "static", "source": "payments",
                                                  "column": "status"}
    unpaid = get_object(graph, db, "order", "O000010")          # i % 10 == 0: no payment row
    assert {p["name"]: p["value"] for p in unpaid.properties if p.get("binding")} == {"psp": None, "payment_status": None}


def test_describe_entity_leaves_out_a_binding_read_from_a_withheld_table(db, graph, monkeypatch):
    bind(graph, db, "Order", "payments", PAYMENTS)
    monkeypatch.setattr(KT, "_served_ontology", lambda *a, **k: graph)
    monkeypatch.setattr(KT, "_accepted_edits", lambda *a, **k: [])
    cleared = KT.describe_entity("bindings-t", "order")
    assert [b["name"] for b in cleared["object_type"]["bindings"]] == ["orders", "payments"]

    def trim(nodes, *_args):
        kept = [n for n in nodes if "payments" not in n["data"]["source_tables"]]
        return kept, ("1 table withheld by data governance" if len(kept) < len(nodes) else "")
    monkeypatch.setattr(KT, "_trim_nodes", trim)
    out = KT.describe_entity("bindings-t", "order")
    body = out["object_type"]
    assert out["available"] and [b["name"] for b in body["bindings"]] == ["orders"]
    assert not any(p["source"]["binding"] == "payments" for p in body["properties"])
    assert "payments" not in out["summary"] and out["notice"] == "1 table withheld by data governance"


# ── the overrides tree: what the bind and the count recorded, carried without a database ────

def test_the_overlay_rebuilds_a_bound_binding_from_its_entry_twice_alike_and_never_a_stale_one(db, graph):
    order = graph.entities["Order"]
    spec = {**PAYMENTS, "properties": {"psp": "psp", "payment_status": "status"}}
    entry = bind_binding(order, "payments", spec, graph, describe_with(db))
    built, _ = declared_bindings(order, {"payments": entry["spec"]}, {"entries": {"payments": entry}}, graph)
    counted = measure_binding(db, order, built[0])
    entry["measured"] = {"spec": entry["spec"], **counted.counts()}
    OV.save_override("c", "ecommerce", OV.OntologyOverride(
        target_kind="entity", target_id="Order", fields={"description": "an order", "bindings": {"payments": entry["spec"]}},
        binding={"bindings": binding_block({"payments": entry})}))

    fresh = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    fresh.entities["Payment"] = payment_type()
    OV.apply_overrides(fresh, "c", "ecommerce")
    [binding] = fresh.entities["Order"].bindings
    assert (binding.verified, binding.covered, binding.columns) == (True, counted.covered, {"payment_status": "status"})
    assert binding.properties["payment_status"].semantic_type == "dimension"      # the profile, without a database
    once = fresh.entities["Order"].model_dump()
    OV.apply_overrides(fresh, "c", "ecommerce")
    assert fresh.entities["Order"].model_dump() == once                           # a second apply builds the same

    ov = OV.find_override("c", "ecommerce", "entity", "Order")
    ov.fields["bindings"]["payments"]["key"] = "payment_id"                       # edited by hand after the bind
    OV.save_override("c", "ecommerce", ov)
    stale = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    OV.apply_overrides(stale, "c", "ecommerce")
    assert stale.entities["Order"].bindings == [] and stale.entities["Order"].description == "an order"


def test_an_exported_tree_carries_each_bindings_spec_and_reimports_as_no_change(tmp_path, db, graph):
    bind(graph, db, "Order", "payments", {**PAYMENTS, "properties": {"psp": "psp", "payment_status": "status"}})
    export_tree(tmp_path, graph)
    doc = yaml.safe_load((tmp_path / "entities" / "Order.yaml").read_text())
    assert doc["editable"]["bindings"] == {"payments": binding_spec(graph.entities["Order"].bindings[0])} == {
        "payments": {"kind": "static", "key": "order_id", "table": "payments",
                     "properties": {"psp": "psp", "payment_status": "status"}}}
    assert import_tree(tmp_path, graph) == []


# ── the doors, over HTTP ────────────────────────────────────────────────────────────────────

CONN = "object-bindings-door-t"
PARAMS = {"connection_id": CONN, "schema_name": "ecommerce"}


@pytest.fixture
def door(tmp_path, monkeypatch):
    """A cached graph for CONN/ecommerce (with the Payment type), an empty overrides tree, and a warehouse every
    opener resolves to."""
    import aughor.db.connection as C
    from aughor.ontology import store as ST
    from aughor.util.json_store import KeyedJsonStore

    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    g = OntologyGraph.model_validate(json.loads(GRAPH.read_text()))
    g.entities["Payment"] = payment_type()
    ST.save_ontology(CONN, "ecommerce", "fp", g)
    path = tmp_path / "samples.duckdb"
    seed(path)

    def _open(*_a, **_k):
        return open_connection("duckdb", str(path), schema_name="ecommerce", connection_id=CONN)

    monkeypatch.setattr(C, "open_connection_for_with_schema", _open)
    return _open


def test_a_binding_is_bound_counted_compiled_proposed_and_removed_over_http(door, client):
    spec = {**PAYMENTS, "properties": {"psp": "psp", "amount": "amount", "payment_status": "status"}}
    bound = client.put("/ontology/entities/Order/bindings/payments", params=PARAMS, json=spec)
    assert bound.status_code == 200, bound.text
    row = bound.json()["binding"]
    assert (row["verified"], row["covered"], row["orphans"], row["usable"]) == (True, 4500, 7, True)
    assert bound.json()["override"]["fields"]["bindings"]["payments"] == {"kind": "static", **spec}

    typed = client.get("/object-types/order", params=PARAMS).json()
    assert {p["name"]: p["source"] for p in typed["properties"]}["payment_status"]["column"] == "status"
    query = {"object_type": "order", "filters": [{"path": "payment_status", "value": "captured"}],
             "measures": [{"agg": "count"}]}
    compiled = client.post("/objects/query", params=PARAMS, json=query).json()
    assert compiled["path"] == "compiled", compiled
    conn = door()
    try:
        (expected,) = ints(conn, "SELECT COUNT(*) FROM orders o JOIN payments p ON p.order_id = o.order_id "
                                 "WHERE p.status = 'captured'")
    finally:
        conn.close()
    assert int(compiled["rows"][0][0]) == expected and compiled["bindings"][0]["binding"] == "payments"

    collision = client.put("/ontology/entities/Order/bindings/receipts", params=PARAMS,
                           json={**PAYMENTS, "properties": {"psp": "psp"}})
    assert collision.status_code == 400 and "already reads psp from the binding payments" in collision.json()["detail"]
    assert client.put("/ontology/entities/Invoice/bindings/x", params=PARAMS, json=PAYMENTS).status_code == 404

    measured = client.post("/ontology/measure", params=PARAMS).json()["bindings"]
    assert "Order.payments" in measured["verified"] and "Order.payments" in measured["overrides_measured"]
    assert "Order.payments" in [p["binding"] for p in measured["proposed"]]
    assert not any(p["kind"] == "static" for p in
                   client.get("/object-types/order", params=PARAMS).json()["proposed_bindings"])   # already bound

    removed = client.delete("/ontology/entities/Order/bindings/payments", params=PARAMS)
    assert removed.status_code == 200 and removed.json()["removed"] is True
    after = client.get("/object-types/order", params=PARAMS).json()
    assert len(after["bindings"]) == 1 and "payments" in {p["name"] for p in after["proposed_bindings"]}
    assert client.post("/objects/query", params=PARAMS, json=query).json()["path"] == "refused"
    assert client.delete("/ontology/entities/Order/bindings/payments", params=PARAMS).status_code == 404
