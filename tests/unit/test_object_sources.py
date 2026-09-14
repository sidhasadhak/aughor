"""ON-8 — one ontology, many sources: the organisation's ontology, whose types and bindings live on any connection and
whose links across two are read by key.

Every claim is held to the single statement. The seeded samples warehouse — plus `payments` (one row for 4,500 of the
5,000 orders, and 7 payments for orders that do not exist) and `regions` (one row per country) — is written whole into
one DuckDB file and split across two more: `shop` keeps orders and order items; `crm` keeps customers, products,
reviews, payments and regions. The same declarations are made twice — in `default`, each type on the connection that
holds its rows, and in `reference`, every type on the whole file — so a claim measured across two connections must count
exactly what it counts on one, and a query across two must return exactly the rows the same query returns as one
statement. What does not cross by key is refused with the reason.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

import aughor.connectors.remote_join as RJ
from aughor.db import registry
from aughor.db.connection import open_connection_for
from aughor.demo.setup import _seed_ecommerce
from aughor.ontology import overrides as OV
from aughor.ontology import store as ST
from aughor.ontology.domains import (
    DomainRefused,
    bind_source,
    declare_entity,
    declare_link,
    domain_graph,
    domain_names,
    measure_domain,
    resolve_domain,
)
from aughor.ontology.models import OntologyGraph
from aughor.ontology.sources import binding_source, entity_source, link_crosses
from aughor.semantic import cross_source as XS
from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, find_object_type
from aughor.util.json_store import KeyedJsonStore

REPO = Path(__file__).resolve().parents[2]
CATALOGUE = REPO / "evals" / "ablation_samples_ecommerce_ontology_measured.json"
LUX = REPO / "evals" / "ablation_luxexperience_ontology.json"

_EXTRA = """
CREATE TABLE ecommerce.payments AS
SELECT printf('PAY%06d', i) AS payment_id, printf('O%06d', i) AS order_id,
       CASE i % 3 WHEN 0 THEN 'visa' WHEN 1 THEN 'mastercard' ELSE 'amex' END AS psp,
       CASE WHEN i % 4 = 0 THEN 'captured' ELSE 'settled' END AS status,
       ROUND((15 + (i * 23.7) % 485)::NUMERIC, 2) AS amount
FROM range(1, 5001) t(i) WHERE i % 10 <> 0
UNION ALL
SELECT printf('PAYX%03d', i), printf('O9%05d', i), 'visa', 'settled', 1.00 FROM range(1, 8) t(i);
CREATE TABLE ecommerce.regions AS
SELECT * FROM (VALUES ('US', 'Americas'), ('CA', 'Americas'), ('BR', 'Americas'), ('GB', 'Europe'), ('FR', 'Europe'),
                      ('DE', 'Europe'), ('JP', 'Asia'), ('IN', 'Asia'), ('AU', 'Oceania'), ('NG', 'Africa'))
       AS t(country, region);
"""
SPLIT = {"shop": ("orders", "order_items"), "crm": ("customers", "products", "reviews", "payments", "regions")}

PLACED_BY = {"from_entity": "Order", "to_entity": "Customer", "name": "placed_by", "from_column": "customer_id",
             "to_column": "customer_id"}
BELONGS_TO = {"from_entity": "OrderItem", "to_entity": "Order", "name": "belongs_to", "from_column": "order_id",
              "to_column": "order_id"}
LOCATED_IN = {"from_entity": "Customer", "to_entity": "Region", "name": "located_in", "from_column": "country",
              "to_column": "country"}
IS_FOR = {"from_entity": "OrderItem", "to_entity": "Product", "name": "is_for", "from_column": "product_id",
          "to_column": "product_id"}
PAYMENT = {"schema_name": "ecommerce", "table": "payments", "key": "order_id",
           "properties": {"psp": "psp", "paid_amount": "amount", "payment_status": "status"}}
SPEND = {"sql": "SELECT customer_id, lifetime_spend AS spend FROM ecommerce.customers", "key": "customer_id",
         "properties": {"spend": "spend"}}


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    """Three registered DuckDB connections: the whole warehouse, and the two halves of it."""
    base = tmp_path_factory.mktemp("sources")
    whole = base / "whole.duckdb"
    con = duckdb.connect(str(whole))
    _seed_ecommerce(con)
    con.execute(_EXTRA)
    con.close()
    for name, tables in SPLIT.items():
        con = duckdb.connect(str(base / f"{name}.duckdb"))
        con.execute(f"ATTACH '{whole}' AS whole (READ_ONLY)")
        con.execute("CREATE SCHEMA ecommerce")
        for table in tables:
            con.execute(f"CREATE TABLE ecommerce.{table} AS SELECT * FROM whole.ecommerce.{table}")
        con.execute("DETACH whole")
        con.close()
    return {name: registry.add_connection(f"on8-{name}", "duckdb", str(base / f"{name}.duckdb"))
            for name in ("whole", "shop", "crm")}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch, sources):
    """Every test declares into its own tree; each half has the builder's catalogue its columns borrow roles from."""
    monkeypatch.setattr(OV, "_ROOT", tmp_path / "ontology_overrides")
    monkeypatch.setattr(ST, "_store", KeyedJsonStore(tmp_path / "onto_cache.json", max_entries=20))
    catalogue = json.loads(CATALOGUE.read_text())
    for name in ("whole", "shop", "crm"):
        ST.save_ontology(sources[name], "ecommerce", "fp",
                         OntologyGraph.model_validate({**catalogue, "connection_id": sources[name]}))


def typed(type_id: str, table: str, key: str, connection: str) -> dict:
    return {"id": type_id, "display_name": type_id,
            "backing": {"connection_id": connection, "schema_name": "ecommerce", "table": table, "primary_key": key}}


def model(sources: dict, name: str, *, shop: str, crm: str):
    """Order and OrderItem where `shop` names; Customer, Product and Region where `crm` names; Order placed_by Customer,
    OrderItem belongs_to Order and is_for Product, Customer located_in Region; payments bound onto Order and a keyed
    SELECT onto Customer."""
    domain = resolve_domain(name)
    for type_id, table, key, where in (("Order", "orders", "order_id", shop), ("OrderItem", "order_items", "item_id", shop),
                                       ("Customer", "customers", "customer_id", crm),
                                       ("Product", "products", "product_id", crm), ("Region", "regions", "country", crm)):
        declare_entity(domain, typed(type_id, table, key, sources[where]), open_connection_for)
    for link in (PLACED_BY, BELONGS_TO, LOCATED_IN, IS_FOR):
        declare_link(domain, link, open_connection_for)
    bind_source(domain, "Order", "payment", {**PAYMENT, "connection_id": sources[crm]}, open_connection_for)
    bind_source(domain, "Customer", "spend", {**SPEND, "connection_id": sources[crm]}, open_connection_for)
    return domain


@pytest.fixture
def both(sources):
    """``(across, reference)``: the same ontology declared across the two halves, and on the whole file."""
    return model(sources, "default", shop="shop", crm="crm"), model(sources, "reference", shop="whole", crm="whole")


def normal(rows) -> list[tuple]:
    def cell(v):
        if v is None or v == "NULL":
            return None
        try:
            return round(float(v), 4)
        except (TypeError, ValueError):
            return str(v)
    return sorted((tuple(cell(v) for v in row) for row in rows), key=repr)


def answer(domain, query: dict, **kw):
    """``(rows, compiled, result)``: the query compiled over the domain and run — split across its sources when it crosses
    one, and as one statement on its anchor's connection when it does not."""
    graph = domain_graph(domain)
    compiled = compile_object_query(query, graph, fiscal_start_month=1)
    home = entity_source(graph, find_object_type(graph, query["object_type"]))
    db = open_connection_for(home)
    try:
        if compiled.cross_source is not None:
            result, _ = XS.execute_plan(compiled.cross_source, home_connection_id=home, home_db=db,
                                        open_source=open_connection_for, display_sql=compiled.sql)
        else:
            result = db.execute("objects", compiled.sql)
    finally:
        db.close()
    return normal(result.rows), compiled, result


def reference(sources, sql: str) -> list[tuple]:
    db = open_connection_for(sources["whole"])
    try:
        result = db.execute("reference", sql)
    finally:
        db.close()
    assert not result.error, (result.error, sql)
    return normal(result.rows)


# ── the model: nothing built before changes ────────────────────────────────────────────────────


def test_a_graph_built_before_the_wave_loads_with_every_new_field_at_its_default():
    graph = OntologyGraph.model_validate(json.loads(LUX.read_text()))
    assert graph.scope == ""
    assert all(e.backing is None or e.backing.connection_id == "" for e in graph.entities.values())
    assert all(b.connection_id == "" for e in graph.entities.values() for b in e.bindings)
    assert {r.traversal for r in graph.relationships.values()} == {"join"}
    assert {entity_source(graph, e) for e in graph.entities.values()} == {graph.connection_id}
    assert not any(link_crosses(graph, r) for r in graph.relationships.values())


def test_a_domain_is_keyed_by_the_organisation_and_kept_beside_the_connections(sources):
    domain = resolve_domain()
    assert (domain.key, domain.tree) == ("default/default", ("org=default", "default"))
    assert resolve_domain("finance").key == "default/finance"
    with pytest.raises(DomainRefused) as bad:
        resolve_domain("Finance Team")
    assert bad.value.status == 400
    assert domain_names() == []
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    assert domain_names() == ["default"]
    assert (OV._ROOT / "org=default" / "default" / "entity" / "Order.yaml").exists()


# ── declarations, each read and counted on its own connection ──────────────────────────────────


def test_a_type_is_declared_on_its_own_connection_counted_there_and_borrows_its_roles(sources):
    domain = resolve_domain()
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    graph = domain_graph(domain)
    order = graph.entities["Order"]
    assert (graph.scope, graph.connection_id) == ("default/default", "org=default")
    assert (order.backing.connection_id, order.backing.table, order.origin) == (sources["shop"], "ecommerce.orders", "human")
    assert (order.backing.verified, order.backing.rows) == (True, 5000)
    assert entity_source(graph, order) == sources["shop"]
    built = json.loads(CATALOGUE.read_text())["entities"]["Order"]["properties"]
    assert order.properties["total_amount"].semantic_type == built["total_amount"]["semantic_type"] != ""
    assert order.properties["order_id"].is_primary_key


def test_a_declaration_on_no_connection_an_unknown_one_or_another_organisations_is_refused(sources, tmp_path):
    from aughor.org.context import reset_org_id, set_org_id
    domain = resolve_domain()
    unnamed = typed("Order", "orders", "order_id", sources["shop"])
    unnamed["backing"].pop("connection_id")
    with pytest.raises(DomainRefused) as none:
        declare_entity(domain, unnamed, open_connection_for)
    with pytest.raises(DomainRefused) as unknown:
        declare_entity(domain, typed("Order", "orders", "order_id", "nosuch01"), open_connection_for)
    token = set_org_id("another-org")
    try:
        theirs = registry.add_connection("on8-theirs", "duckdb", str(tmp_path / "theirs.duckdb"))
    finally:
        reset_org_id(token)
    with pytest.raises(DomainRefused) as foreign:
        declare_entity(domain, typed("Order", "orders", "order_id", theirs), open_connection_for)
    assert (none.value.status, unknown.value.status, foreign.value.status) == (400, 404, 403)
    assert domain_graph(domain).entities == {}


def test_a_link_across_two_connections_is_measured_as_the_same_link_is_on_one(both):
    across, same = both
    link, one = (OV.find_override(*d.tree, "link", "Order_placed_by_Customer").binding["link"] for d in (across, same))
    counted = ("measured_cardinality", "value_overlap", "from_rows", "from_non_null", "from_distinct", "to_rows",
               "to_non_null", "to_distinct")
    assert {k: link[k] for k in counted} == {k: one[k] for k in counted}
    assert (link["measured_cardinality"], link["value_overlap"], link["from_distinct"], link["to_distinct"]) == \
           ("N:1", 1.0, 500, 500)
    assert "two connections" in link["note"] and "two connections" not in one["note"]
    served = domain_graph(across).relationships
    assert served["Order_placed_by_Customer"].traversal == "cross-source"
    assert served["OrderItem_is_for_Product"].traversal == "cross-source"
    assert served["OrderItem_belongs_to_Order"].traversal == "join"
    assert served["Customer_located_in_Region"].traversal == "join"
    assert {r.traversal for r in domain_graph(same).relationships.values()} == {"join"}


def test_a_binding_across_two_connections_is_counted_as_the_same_binding_is_on_one(both, sources):
    across, same = both
    counted = ("rows", "non_null", "distinct", "objects", "covered", "orphans", "verified")
    far, near = (next(b for b in domain_graph(d).entities["Order"].bindings if b.name == "payment") for d in (across, same))
    assert {k: getattr(far, k) for k in counted} == {k: getattr(near, k) for k in counted}
    assert (far.rows, far.distinct, far.objects, far.covered, far.orphans, far.verified) == (4507, 4507, 5000, 4500, 7, True)
    graph = domain_graph(across)
    assert far.connection_id == sources["crm"] and near.connection_id == ""
    assert binding_source(graph, graph.entities["Order"], far) == sources["crm"]
    assert "met in memory" in far.note and "met in memory" not in near.note


def test_a_binding_read_across_two_connections_binds_only_static(sources):
    domain = resolve_domain()
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    rolled = {"connection_id": sources["crm"], "schema_name": "ecommerce", "table": "reviews", "key": "order_id",
              "kind": "detail", "rollups": {"review_count": {"column": "review_id", "agg": "count"}}}
    with pytest.raises(DomainRefused) as detail:
        bind_source(domain, "Order", "reviews", rolled, open_connection_for)
    with pytest.raises(DomainRefused) as absorbed:
        bind_source(domain, "Order", "payment", {**PAYMENT, "connection_id": sources["crm"], "absorb": True},
                    open_connection_for)
    assert (detail.value.status, absorbed.value.status) == (400, 400)
    assert "static" in detail.value.detail
    assert domain_graph(domain).entities["Order"].bindings == []


# ── queries across two connections equal the single statement ──────────────────────────────────

QUERIES = {
    "orders by customer country": {
        "object_type": "Order", "measures": [{"agg": "count", "name": "orders"}], "by": ["placed_by.country"]},
    "delivered revenue by country": {
        "object_type": "Order", "filters": [{"path": "status", "value": "delivered"}],
        "measures": [{"agg": "sum", "path": "total_amount"}], "by": ["placed_by.country"]},
    "the average order of German customers": {
        "object_type": "Order", "filters": [{"path": "placed_by.country", "value": "DE"}],
        "measures": [{"agg": "avg", "path": "total_amount"}]},
    "customers who ordered, per city and month of 2023": {
        "object_type": "Order", "measures": [{"agg": "count_distinct", "path": "customer_id", "name": "customers"}],
        "by": ["placed_by.city"], "time": "order_date", "grain": "month", "start": "2023-01-01", "end": "2024-01-01"},
    "paid amount and orders by payment provider": {
        "object_type": "Order", "measures": [{"agg": "sum", "path": "paid_amount"}, {"agg": "count", "name": "orders"}],
        "by": ["psp"]},
    "the share of revenue paid, by country": {
        "object_type": "Order", "by": ["placed_by.country"],
        "measures": [{"agg": "sum", "path": "paid_amount", "name": "paid_share", "scale": 100, "decimals": 2,
                      "divide_by": {"agg": "sum", "path": "total_amount"}}]},
    "units by customer country, one join then a keyed read": {
        "object_type": "OrderItem", "measures": [{"agg": "sum", "path": "quantity"}], "by": ["belongs_to.placed_by.country"]},
    "revenue by product category and customer country, two keyed reads": {
        "object_type": "OrderItem", "measures": [{"agg": "sum", "path": "line_total"}],
        "by": ["is_for.category", "belongs_to.placed_by.country"]},
    "customers per country among captured payments": {
        "object_type": "Order", "filters": [{"path": "payment_status", "value": "captured"}],
        "measures": [{"agg": "count_distinct", "path": "placed_by", "name": "customers"}], "by": ["placed_by.country"]},
}


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_a_query_across_two_connections_returns_exactly_the_rows_of_the_single_statement(both, name):
    across, same = both
    rows, compiled, result = answer(across, QUERIES[name])
    single, one, _ = answer(same, QUERIES[name])
    assert compiled.cross_source is not None and one.cross_source is None
    assert not result.error, result.error
    assert rows and rows == single


def test_the_rows_across_two_connections_equal_hand_written_references(both, sources):
    across, _ = both
    by_country, _, _ = answer(across, QUERIES["orders by customer country"])
    assert by_country == reference(sources, (
        "SELECT c.country, COUNT(*) FROM ecommerce.orders o LEFT JOIN ecommerce.customers c "
        "ON o.customer_id = c.customer_id GROUP BY 1"))
    by_psp, _, _ = answer(across, QUERIES["paid amount and orders by payment provider"])
    assert by_psp == reference(sources, (
        "SELECT p.psp, SUM(p.amount), COUNT(*) FROM ecommerce.orders o LEFT JOIN ecommerce.payments p "
        "ON o.order_id = p.order_id GROUP BY 1"))
    assert (None, None, 500.0) in by_psp                      # the 500 unpaid orders stay, in a group of their own
    units, _, _ = answer(across, QUERIES["units by customer country, one join then a keyed read"])
    assert units == reference(sources, (
        "SELECT c.country, SUM(i.quantity) FROM ecommerce.order_items i LEFT JOIN ecommerce.orders o "
        "ON i.order_id = o.order_id LEFT JOIN ecommerce.customers c ON o.customer_id = c.customer_id GROUP BY 1"))


def test_the_split_computes_row_values_at_home_and_every_aggregate_in_the_stage(both, sources):
    across, _ = both
    compiled = compile_object_query(QUERIES["delivered revenue by country"], domain_graph(across), fiscal_start_month=1)
    plan = compiled.cross_source
    home, stage = plan.home_sql.upper(), plan.stage_sql.upper()
    assert "GROUP BY" not in home and "SUM(" not in home and "__FAR" not in home and "'DELIVERED'" in home
    assert "GROUP BY" in stage and "SUM(" in stage and "__FAR_" in stage and "DELIVERED" not in stage
    [read] = plan.reads
    assert (read.kind, read.connection_id, read.table, read.key, read.columns) == \
           ("link", sources["crm"], "ecommerce.customers", "customer_id", ["country"])
    assert [link["treatment"] for link in compiled.links] == ["read by key"]
    assert any(line.startswith("cross-source:") for line in compiled.plan)
    assert sources["crm"] in compiled.sql and "__far" not in compiled.sql
    assert compiled.to_dict()["cross_source"]["reads"][0]["connection_id"] == sources["crm"]


def test_the_split_keeps_a_date_truncated_as_a_date_on_a_dialect_that_tells_the_two_apart(both):
    across, _ = both
    compiled = compile_object_query(QUERIES["customers who ordered, per city and month of 2023"], domain_graph(across),
                                    dialect="bigquery", fiscal_start_month=1)
    home = compiled.cross_source.home_sql.upper()
    assert "DATE_TRUNC(" in home and "TIMESTAMP_TRUNC(" not in home


def test_a_query_that_reads_nothing_on_another_connection_stays_one_statement(both):
    across, _ = both
    compiled = compile_object_query({"object_type": "OrderItem", "measures": [{"agg": "sum", "path": "quantity"}],
                                     "by": ["belongs_to.status"]}, domain_graph(across), fiscal_start_month=1)
    assert compiled.cross_source is None and "__far" not in compiled.sql
    assert [link["treatment"] for link in compiled.links] == ["joined"]


REFUSED = {
    "a path past a type read by key": (
        {"object_type": "Order", "measures": [{"agg": "count"}], "by": ["placed_by.located_in.region"]},
        "does not continue past a cross-source link"),
    "a binding of a type read by key": (
        {"object_type": "Order", "measures": [{"agg": "count"}], "by": ["placed_by.spend"]},
        "not a column of Customer's backing"),
    "a to-many link across two connections": (
        {"object_type": "Customer", "measures": [{"agg": "count", "path": "customer_to_order"}]},
        "to-many and crosses to another connection"),
    "an EXISTS across two connections": (
        {"object_type": "Customer", "filters": [{"path": "customer_to_order", "op": "exists"}],
         "measures": [{"agg": "count"}]},
        "inside an EXISTS"),
    "a keyed read inside a pre-aggregated link": (
        {"object_type": "Order", "measures": [{"agg": "max", "path": "order_to_order_item.is_for.price"}]},
        "from inside a pre-aggregated link or an EXISTS"),
    "a keyed read inside an EXISTS": (
        {"object_type": "Order", "filters": [{"path": "order_to_order_item.is_for.category", "value": "Kitchen"}],
         "measures": [{"agg": "count"}]},
        "from inside a pre-aggregated link or an EXISTS"),
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_what_does_not_cross_by_key_is_refused_with_the_reason_and_answers_on_one_connection(both, name):
    across, same = both
    query, reason = REFUSED[name]
    with pytest.raises(ObjectQueryRefused) as refused:
        compile_object_query(query, domain_graph(across), fiscal_start_month=1)
    assert reason in refused.value.reason
    rows, one, result = answer(same, query)                  # the same question, on one connection, is one statement
    assert one.cross_source is None and not result.error and rows


def test_a_binding_on_another_connection_that_is_not_static_is_refused_by_the_compiler_too(both):
    across, _ = both
    graph = domain_graph(across)
    payment = next(b for b in graph.entities["Order"].bindings if b.name == "payment")
    payment.kind, payment.time_column = "timeseries", "order_id"            # as though it had been bound that way
    with pytest.raises(ObjectQueryRefused) as latest:
        compile_object_query({"object_type": "Order", "measures": [{"agg": "count"}], "by": ["psp"]}, graph,
                             fiscal_start_month=1)
    with pytest.raises(ObjectQueryRefused) as readings:
        compile_object_query({"object_type": "Order", "measures": [{"agg": "sum", "path": "payment.paid_amount"}]}, graph,
                             fiscal_start_month=1)
    assert "only a static one" in latest.value.reason
    assert "not read across two connections" in readings.value.reason


def test_one_table_name_on_two_connections_is_two_tables_and_on_one_is_a_duplicate(sources):
    domain = resolve_domain("archive")
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    declare_entity(domain, typed("ArchivedOrder", "orders", "order_id", sources["whole"]), open_connection_for)
    with pytest.raises(DomainRefused) as twice:
        declare_entity(domain, typed("OrderAgain", "orders", "order_id", sources["shop"]), open_connection_for)
    assert twice.value.status == 400 and "already backs Order" in twice.value.detail
    assert set(domain_graph(domain).entities) == {"Order", "ArchivedOrder"}


def test_keys_that_cannot_all_be_read_leave_a_claim_unmeasured_and_unread(sources, monkeypatch):
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.ontology import sources as SRC

    class Partial:
        def execute_bounded(self, label, sql, max_rows):
            return QueryResult(hypothesis_id=label, sql=sql, columns=["k"], rows=[["a"], ["b"]], row_count=5)

    keys, why = SRC.distinct_keys(Partial(), "t AS o", "o", "k")
    assert keys is None and "2 of at least 5" in why
    monkeypatch.setattr(SRC, "MAX_KEYS", 100)
    capped = model(sources, "capped", shop="shop", crm="crm")
    graph = domain_graph(capped)
    payment = next(b for b in graph.entities["Order"].bindings if b.name == "payment")
    assert payment.verified is None and "more than 100 distinct keys" in payment.note
    assert graph.relationships["Order_placed_by_Customer"].value_overlap is None
    with pytest.raises(ObjectQueryRefused) as unread:
        compile_object_query({"object_type": "Order", "measures": [{"agg": "count"}], "by": ["psp"]}, graph,
                             fiscal_start_month=1)
    assert "unmeasured" in unread.value.reason


def test_the_answer_across_two_connections_passes_every_gate_a_single_statement_passes(both, sources, monkeypatch):
    import aughor.db.connection as C
    from aughor.control_plane.contracts.execution import QueryResult
    across, _ = both
    seen: dict = {"pre": [], "post": []}
    real_pre, real_post = C.security_pre, C.security_post

    def pre(connection_id, label, sql):
        seen["pre"].append((connection_id, label))
        return real_pre(connection_id, label, sql)

    def post(connection_id, label, sql, result, ms, also_read=()):
        seen["post"].append((connection_id, label, result.row_count, list(also_read)))
        return real_post(connection_id, label, sql, result, ms, also_read)

    monkeypatch.setattr(C, "security_pre", pre)
    monkeypatch.setattr(C, "security_post", post)
    rows, _, _ = answer(across, QUERIES["orders by customer country"])
    assert seen["pre"] == [(sources["shop"], "objects"), (sources["crm"], "objects")]
    assert seen["post"] == [(sources["shop"], "objects", len(rows), [sources["crm"]])]
    # the far connection's audit trail records the answer its rows reached, not only the home connection's
    from aughor.security.audit import AuditLogger
    assert any(r["verdict"] == "safe" for r in AuditLogger.recent(200, connection_id=sources["crm"], label="objects"))

    blocked = QueryResult(hypothesis_id="objects", sql="", columns=[], rows=[], row_count=0, error="[BLOCKED] by policy")
    monkeypatch.setattr(C, "security_pre", lambda connection_id, label, sql: blocked if connection_id == sources["crm"] else None)
    rows, _, result = answer(across, QUERIES["orders by customer country"])
    assert rows == [] and result.error == "[BLOCKED] by policy"


def test_a_keyed_read_past_its_cap_is_refused_with_the_cap(both, monkeypatch):
    across, _ = both
    monkeypatch.setattr(XS, "MAX_KEYED_ROWS", 5)
    rows, _, result = answer(across, QUERIES["orders by customer country"])
    assert rows == [] and "more than 5 rows" in result.error


def test_a_far_key_that_now_meets_two_rows_is_refused_rather_than_joined(both, monkeypatch):
    across, _ = both
    real = RJ.fetch_by_keys

    def doubled(*args, **kwargs):
        columns, types, rows, error = real(*args, **kwargs)
        return columns, types, rows + rows[:1], error

    monkeypatch.setattr(RJ, "fetch_by_keys", doubled)
    rows, _, result = answer(across, QUERIES["orders by customer country"])
    assert rows == [] and "now meet more than one row" in result.error


def test_a_query_past_the_home_cap_is_refused_with_the_cap_never_answered_from_part(both, monkeypatch):
    across, _ = both
    monkeypatch.setattr(XS, "MAX_HOME_ROWS", 10)
    rows, _, result = answer(across, QUERIES["orders by customer country"])
    assert rows == [] and "more than 10" in result.error


def test_the_typed_read_is_plumbing_only_and_says_when_it_stopped(sources):
    db = open_connection_for(sources["whole"])
    try:
        with pytest.raises(ValueError):
            db.read_typed_rows("objects", "SELECT 1", 10)
        result, payload = db.read_typed_rows(
            "__objects_home__", "SELECT total_amount, order_date FROM ecommerce.orders ORDER BY order_id LIMIT 2", 10)
        assert payload["types"][0].startswith("DECIMAL") and payload["types"][1] == "DATE"
        assert isinstance(payload["rows"][0][0], Decimal) and not isinstance(payload["rows"][0][1], str)
        assert result.rows[0][0] == str(payload["rows"][0][0])       # the caller-facing rows are the same, as text
        cut, cut_payload = db.read_typed_rows("__objects_home__", "SELECT order_id FROM ecommerce.orders", 10)
        assert cut_payload["truncated"] is True and len(cut_payload["rows"]) == 10 and cut.row_count == 5000
    finally:
        db.close()


def test_the_measure_pass_counts_every_declaration_again_on_the_connections_it_names(both, sources):
    across, _ = both
    report = measure_domain(across, open_connection_for)
    assert {(r["entity"], r["connection_id"], r["unique"]) for r in report["entities"]} == {
        ("Order", sources["shop"], True), ("OrderItem", sources["shop"], True), ("Customer", sources["crm"], True),
        ("Product", sources["crm"], True), ("Region", sources["crm"], True)}
    payment = next(r for r in report["bindings"] if r["binding"] == "Order.payment")
    assert (payment["cross_source"], payment["covered"], payment["orphans"], payment["verified"]) == (True, 4500, 7, True)
    spend = next(r for r in report["bindings"] if r["binding"] == "Customer.spend")
    assert (spend["cross_source"], spend["covered"]) == (False, 500)
    placed = next(r for r in report["links"] if r["link"] == "Order_placed_by_Customer")
    assert (placed["traversal"], placed["measured_cardinality"], placed["value_overlap"]) == ("cross-source", "N:1", 1.0)


# ── the doors ───────────────────────────────────────────────────────────────────────────────────


def test_the_doors_declare_query_measure_and_withdraw_an_organisations_ontology_over_http(client, sources):
    domain = {"domain": "default"}
    declared = client.post("/ontology/entities", params=domain, json=typed("Order", "orders", "order_id", sources["shop"]))
    assert declared.status_code == 200, declared.text
    assert (declared.json()["domain"], declared.json()["entity"]["connection_id"]) == ("default/default", sources["shop"])
    assert client.post("/ontology/entities", params=domain,
                       json=typed("Customer", "customers", "customer_id", sources["crm"])).status_code == 200
    assert client.post("/ontology/entities", params=domain,
                       json=typed("Order", "orders", "order_id", sources["shop"])).status_code == 409
    unnamed = typed("Region", "regions", "country", sources["crm"])
    unnamed["backing"].pop("connection_id")
    assert client.post("/ontology/entities", params=domain, json=unnamed).status_code == 400
    linked = client.post("/ontology/links", params=domain, json=PLACED_BY)
    assert linked.status_code == 200, linked.text
    assert (linked.json()["link"]["traversal"], linked.json()["link"]["traversable"]) == ("cross-source", True)
    bound = client.put("/ontology/entities/Order/bindings/payment", params=domain,
                       json={**PAYMENT, "connection_id": sources["crm"]})
    assert bound.status_code == 200, bound.text
    assert (bound.json()["binding"]["connection_id"], bound.json()["binding"]["covered"]) == (sources["crm"], 4500)

    listed = client.get("/ontology/domains").json()
    row = next(d for d in listed["domains"] if d["domain"] == "default")
    assert (row["object_types"], row["links"], row["cross_source_links"]) == (2, 1, 1)
    assert row["connections"] == sorted([sources["shop"], sources["crm"]])
    mapped = client.get("/object-types", params=domain).json()
    assert {t["id"]: t["connection_id"] for t in mapped["object_types"]} == {"Order": sources["shop"],
                                                                           "Customer": sources["crm"]}
    assert [e["traversal"] for e in mapped["links"]] == ["cross-source"]

    planned = client.post("/objects/query", params={**domain, "execute": "false"},
                          json=QUERIES["orders by customer country"]).json()
    assert planned["path"] == "compiled" and "rows" not in planned
    assert planned["cross_source"]["reads"][0]["connection_id"] == sources["crm"]
    ran = client.post("/objects/query", params=domain, json=QUERIES["orders by customer country"]).json()
    assert ran["error"] is None and ran["connection_id"] == sources["shop"]
    assert normal(ran["rows"]) == reference(sources, (
        "SELECT c.country, COUNT(*) FROM ecommerce.orders o LEFT JOIN ecommerce.customers c "
        "ON o.customer_id = c.customer_id GROUP BY 1"))
    assert [t["read"] for t in ran["timings"]][0] == "home" and ran["timings"][-1]["read"] == "stage"
    far = next(t for t in ran["timings"] if t.get("kind") == "link")
    assert (far["keys"], far["rows"], far["queries"]) == (500, 500, 1)
    refused = client.post("/objects/query", params=domain,
                          json={"object_type": "Customer", "measures": [{"agg": "count", "path": "customer_to_order"}]})
    assert refused.json()["path"] == "refused"

    measured = client.post("/ontology/measure", params=domain).json()
    assert [link["traversal"] for link in measured["links"]] == ["cross-source"]
    assert client.delete("/ontology/entities/Order/bindings/payment", params=domain).status_code == 200
    assert client.delete("/ontology/links/Order_placed_by_Customer", params=domain).status_code == 200
    assert client.delete("/ontology/links/Order_placed_by_Customer", params=domain).status_code == 404
    assert client.delete("/ontology/entities/Customer", params=domain).status_code == 200
    empty = client.get("/object-types", params={"domain": "nothing-here"})
    assert empty.status_code == 200, empty.text                  # the map's empty state is where a first type is declared
    assert (empty.json()["domain"], empty.json()["object_types"]) == ("default/nothing-here", [])
    assert client.post("/objects/query", params={"domain": "nothing-here"},
                       json=QUERIES["orders by customer country"]).status_code == 404


def test_one_connections_ontology_refuses_a_source_on_another_and_says_where_it_belongs(client, sources):
    params = {"connection_id": sources["shop"], "schema_name": "ecommerce"}
    bound = client.put("/ontology/entities/Order/bindings/payment", params=params,
                       json={**PAYMENT, "connection_id": sources["crm"]})
    declared = client.post("/ontology/entities", params=params,
                           json=typed("Buyer", "customers", "customer_id", sources["crm"]))
    assert (bound.status_code, declared.status_code) == (400, 400)
    assert "?domain=" in bound.json()["detail"] and "?domain=" in declared.json()["detail"]
    # the scope the web carries an organisation's ontology in never reaches a door that edits one connection's graph
    stray = client.put("/ontology/entities/Order", params={"connection_id": "domain:default"},
                       json={"display_property": "order_id"})
    assert stray.status_code == 400 and "?domain=" in stray.json()["detail"]
    assert not (OV._ROOT / "domain_default").exists()


# ── edited by people only, and never reached by naming its tree (the user's rules, 2026-09-14) ─────────────────────


def test_an_organisations_ontology_takes_a_persons_declaration_only(sources):
    domain = resolve_domain()
    order = typed("Order", "orders", "order_id", sources["shop"])
    with pytest.raises(DomainRefused) as proposed:
        declare_entity(domain, {**order, "origin": "model"}, open_connection_for)
    with pytest.raises(DomainRefused) as attributed:
        declare_entity(domain, {**order, "provenance": "model:some-model@1"}, open_connection_for)
    assert (proposed.value.status, attributed.value.status) == (400, 400)
    assert "edited by people only" in proposed.value.detail
    assert domain_graph(domain).entities == {}
    declare_entity(domain, order, open_connection_for)
    declare_entity(domain, typed("Customer", "customers", "customer_id", sources["crm"]), open_connection_for)
    with pytest.raises(DomainRefused) as link:
        declare_link(domain, {**PLACED_BY, "origin": "model"}, open_connection_for)
    with pytest.raises(DomainRefused) as binding:
        bind_source(domain, "Order", "payment", {**PAYMENT, "connection_id": sources["crm"], "origin": "model"},
                    open_connection_for)
    assert (link.value.status, binding.value.status) == (400, 400)
    graph = domain_graph(domain)
    assert graph.relationships == {} and not graph.entities["Order"].bindings
    assert {e.origin for e in graph.entities.values()} == {"human"}


def test_only_the_organisations_own_writer_writes_its_tree_and_only_a_persons_declaration(sources):
    domain = resolve_domain()
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    conn, name = domain.tree
    mine = OV.find_override(conn, name, "entity", "Order")
    for scope in (conn, "domain:default"):
        with pytest.raises(ValueError):
            OV.save_override(scope, name, mine)
        with pytest.raises(ValueError):
            OV.delete_override(scope, name, "entity", "Order")
    with pytest.raises(ValueError):
        OV.save_organisation_override(sources["shop"], "ecommerce", mine)    # one connection's scope is not an organisation's
    proposals = (
        mine.model_copy(update={"fields": {**mine.fields, "origin": "model"}}),
        mine.model_copy(update={"fields": {**mine.fields, "provenance": "model:some-model@1"}}),
        mine.model_copy(update={"source": "pack"}),
        mine.model_copy(update={"binding": {**mine.binding, "bindings": {"entries": {
            "payment": {"spec": PAYMENT, "bound": True, "origin": "model", "provenance": "model:some-model@1"}}}}}),
    )
    for ov in proposals:
        with pytest.raises(ValueError, match="edited by people only"):
            OV.save_organisation_override(conn, name, ov)
    assert OV.find_override(conn, name, "entity", "Order") == mine
    assert not (OV._ROOT / "domain_default").exists()
    assert OV.delete_organisation_override(conn, name, "entity", "Order") is True
    assert domain_graph(domain).entities == {}


def test_no_door_reaches_an_organisations_ontology_by_naming_its_tree_as_a_connection(client, sources):
    assert client.post("/ontology/entities", params={"domain": "default"},
                       json=typed("Order", "orders", "order_id", sources["shop"])).status_code == 200
    tree = {"connection_id": "org=default", "schema_name": "default"}
    answers = {
        "list": client.get("/ontology/overrides", params=tree),
        "withdraw": client.delete("/ontology/overrides/entity/Order", params=tree),
        "edit": client.put("/ontology/entities/Order", params=tree, json={"display_property": "order_id"}),
        "declare": client.post("/ontology/entities", params=tree,
                               json=typed("Buyer", "customers", "customer_id", sources["crm"])),
        "unbind": client.delete("/ontology/entities/Order/bindings/payment", params=tree),
        "map": client.get("/object-types", params=tree),
        "query": client.post("/objects/query", params=tree, json=QUERIES["orders by customer country"]),
        "compare": client.get("/ontology/draft", params={"connection_id": sources["shop"], "schema_name": "ecommerce",
                                                         "reference_connection_id": "org=default"}),
    }
    assert {what: r.status_code for what, r in answers.items()} == dict.fromkeys(answers, 400)
    assert all("?domain=" in r.json()["detail"] for r in answers.values())
    assert (OV._ROOT / "org=default" / "default" / "entity" / "Order.yaml").exists()
    # the scope the web carries an organisation's ontology in reaches a door that takes ?domain=, and no other
    carried = {"connection_id": "domain:default", "domain": "default"}
    assert [t["id"] for t in client.get("/object-types", params=carried).json()["object_types"]] == ["Order"]
    assert client.put("/ontology/entities/Order", params=carried,
                      json={"display_property": "order_id"}).status_code == 400
    assert not (OV._ROOT / "domain_default").exists()


def test_the_explorer_is_refused_an_organisations_ontology_before_any_model_is_asked(client, sources, monkeypatch):
    import aughor.llm.provider as provider

    def no_model(*_args, **_kwargs):
        raise AssertionError("the explorer asked a model about an organisation's ontology")
    monkeypatch.setattr(provider, "get_provider", no_model)
    assert client.post("/ontology/entities", params={"domain": "default"},
                       json=typed("Order", "orders", "order_id", sources["shop"])).status_code == 200
    before = {p: p.read_text() for p in OV._ROOT.rglob("*.yaml")}
    for scope in ({"connection_id": "domain:default", "domain": "default"}, {"connection_id": "domain:default"},
                  {"connection_id": "org=default", "schema_name": "default"}):
        explored = client.post("/ontology/explore", params=scope)
        confirmed = client.post("/ontology/draft/confirm", params=scope, json={"all": True, "actor": "a person"})
        drafted = client.get("/ontology/draft", params=scope)
        assert (explored.status_code, confirmed.status_code, drafted.status_code) == (400, 400, 400), scope
        assert "the explorer drafts one connection's ontology" in explored.json()["detail"]
    assert {p: p.read_text() for p in OV._ROOT.rglob("*.yaml")} == before


def test_a_copied_column_profile_keeps_what_was_measured_and_no_words(sources):
    from aughor.ontology.bindings import PROFILE_COPIED, profile_record, recorded_profiles
    from aughor.ontology.models import EntityProperty
    domain = resolve_domain()
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    conn, name = domain.tree
    kept = OV.find_override(conn, name, "entity", "Order").binding["backing"]["profiles"]
    assert (kept["total_amount"]["measure_grain"], kept["total_amount"]["unit"]) == ("per_unit", "USD")
    assert all(set(profile) <= set(PROFILE_COPIED) for profile in kept.values())   # the catalogue describes order_id
    worded = EntityProperty(name="note", semantic_type="dimension", description="what a model wrote",
                            null_meaning="what the explorer said a null means")
    assert profile_record({"note": worded}) == {"note": {"name": "note", "semantic_type": "dimension"}}
    older = {**kept, "total_amount": {**kept["total_amount"], "description": "what a model wrote"}}
    assert recorded_profiles(older)["total_amount"].description == ""
    ov = OV.find_override(conn, name, "entity", "Order")
    ov.binding["backing"]["profiles"] = older
    OV.save_organisation_override(conn, name, ov)
    measure_domain(domain, open_connection_for)
    cleaned = OV.find_override(conn, name, "entity", "Order").binding["backing"]["profiles"]
    assert "description" not in cleaned["total_amount"] and cleaned["total_amount"]["unit"] == "USD"
    # a binding's copy, made before the rule, is kept to what was measured the next time it is counted
    bind_source(domain, "Order", "payment", {**PAYMENT, "connection_id": sources["crm"]}, open_connection_for)
    ov = OV.find_override(conn, name, "entity", "Order")
    ov.binding["bindings"]["entries"]["payment"]["profiles"] = {
        "amount": {"name": "amount", "semantic_type": "measure", "description": "what a model wrote"}}
    OV.save_organisation_override(conn, name, ov)
    measure_domain(domain, open_connection_for)
    payment = OV.find_override(conn, name, "entity", "Order").binding["bindings"]["entries"]["payment"]
    assert payment["profiles"] == {"amount": {"name": "amount", "semantic_type": "measure"}}


def test_a_declaration_that_names_a_proposer_is_refused_at_the_domain_doors(client, sources):
    """E5 × the user's rule: now that the doors carry `provenance`, a declaration naming a proposer reaches the
    organisation's doors — and is refused there, since an organisation's ontology is edited by people only."""
    domain = {"domain": "provenance-t"}
    entity = client.post("/ontology/entities", params=domain,
                         json={**typed("Order", "orders", "order_id", sources["shop"]), "provenance": "model:some-model@1"})
    assert entity.status_code == 400 and "edited by people only" in entity.json()["detail"]
    link = client.post("/ontology/links", params=domain, json={**PLACED_BY, "provenance": "model:some-model@1"})
    assert link.status_code == 400 and "edited by people only" in link.json()["detail"]
