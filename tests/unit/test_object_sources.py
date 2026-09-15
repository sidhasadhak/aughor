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
from contextlib import contextmanager
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
from aughor.ontology.business_rules import describe_rule
from aughor.ontology.domains import (
    DomainRefused,
    bind_source,
    declare_entity,
    declare_link,
    declare_process,
    declare_rule,
    domain_graph,
    domain_names,
    measure_domain,
    resolve_domain,
    set_display_property,
)
from aughor.ontology.models import OntologyGraph
from aughor.ontology.processes import describe_process
from aughor.ontology.sources import binding_source, entity_source, link_crosses
from aughor.semantic import cross_source as XS
from aughor.semantic.object_instances import ObjectNotFound, get_object, list_linked, titles
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
CREATE TABLE ecommerce.country_managers AS
SELECT * FROM (VALUES ('US', 'Avery'), ('CA', 'Blake'), ('BR', 'Cruz'), ('GB', 'Drew'), ('FR', 'Eden'), ('DE', 'Finn'),
                      ('JP', 'Gray'), ('IN', 'Hale'), ('AU', 'Ira')) AS t(country, manager);
CREATE TABLE ecommerce.payment_events AS
SELECT printf('O%06d', i) AS order_id, TIMESTAMP '2024-01-01 00:00:00' + to_days(i % 30) + to_hours(e) AS event_at,
       CASE e WHEN 0 THEN 'authorized' WHEN 1 THEN 'captured' ELSE 'settled' END AS status,
       ROUND(((i * 7 + e * 13) % 400)::NUMERIC, 2) AS amount
FROM range(1, 5001) t(i), range(0, 3) s(e) WHERE i % 5 <> 0 AND (e < 2 OR i % 2 = 0);
"""
SPLIT = {"shop": ("orders", "order_items", "country_managers"),
         "crm": ("customers", "products", "reviews", "payments", "regions", "payment_events")}

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
MANAGED_BY = {"from_entity": "Region", "to_entity": "Manager", "name": "managed_by", "from_column": "country",
              "to_column": "country"}
ORDER_COUNT = {"sql": "SELECT customer_id, COUNT(*) AS order_count FROM ecommerce.orders GROUP BY customer_id",
               "key": "customer_id", "properties": {"order_count": "order_count"}}
PAYMENT_LATEST = {"schema_name": "ecommerce", "table": "payment_events", "key": "order_id", "kind": "timeseries",
                  "time_column": "event_at", "properties": {"latest_status": "status", "latest_amount": "amount"}}
PAYMENT_EVENTS = {"schema_name": "ecommerce", "table": "payment_events", "key": "order_id", "kind": "detail",
                  "rollups": {"event_count": {"column": "status", "agg": "count"},
                              "paid_total": {"column": "amount", "agg": "sum"}}}


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


def wide_model(sources: dict, name: str, *, shop: str, crm: str):
    """`model`, and what reaches past a type read by key: a Manager per country where `shop` names (Region managed_by
    Manager — a link from a type on `crm` to one on `shop`), the orders each customer placed read from `shop` onto
    Customer, and each order's payment events read from `crm` onto Order — its latest event (timeseries) and its
    rollups (detail)."""
    domain = model(sources, name, shop=shop, crm=crm)
    declare_entity(domain, typed("Manager", "country_managers", "country", sources[shop]), open_connection_for)
    declare_link(domain, MANAGED_BY, open_connection_for)
    bind_source(domain, "Customer", "orders_placed", {**ORDER_COUNT, "connection_id": sources[shop]}, open_connection_for)
    bind_source(domain, "Order", "payment_latest", {**PAYMENT_LATEST, "connection_id": sources[crm]}, open_connection_for)
    bind_source(domain, "Order", "payment_events", {**PAYMENT_EVENTS, "connection_id": sources[crm]}, open_connection_for)
    return domain


@pytest.fixture
def wide(sources):
    """``(across, reference)`` for `wide_model`."""
    return (wide_model(sources, "default", shop="shop", crm="crm"),
            wide_model(sources, "reference", shop="whole", crm="whole"))


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


def test_a_binding_read_across_two_connections_binds_whatever_its_kind_but_is_never_absorbed(sources):
    """O3 — read by key, a detail binding is its rollups per object and a timeseries binding its latest row per object:
    one row per object either way, so both bind across two connections. Absorbing a part still belongs to the ontology
    of the connection that holds both tables."""
    domain = resolve_domain()
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_connection_for)
    rolled = {"connection_id": sources["crm"], "schema_name": "ecommerce", "table": "reviews", "key": "order_id",
              "kind": "detail", "rollups": {"review_count": {"column": "review_id", "agg": "count"}}}
    bind_source(domain, "Order", "reviews", rolled, open_connection_for)
    with pytest.raises(DomainRefused) as absorbed:
        bind_source(domain, "Order", "payment", {**PAYMENT, "connection_id": sources["crm"], "absorb": True},
                    open_connection_for)
    assert absorbed.value.status == 400
    [reviews] = domain_graph(domain).entities["Order"].bindings
    assert (reviews.name, reviews.kind, reviews.connection_id) == ("reviews", "detail", sources["crm"])


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


def test_the_split_computes_row_values_at_home_groups_them_at_the_keys_grain_and_rolls_them_up_in_the_stage(both, sources):
    across, _ = both
    compiled = compile_object_query(QUERIES["delivered revenue by country"], domain_graph(across), fiscal_start_month=1)
    plan = compiled.cross_source
    home, stage = plan.home_sql.upper(), plan.stage_sql.upper()
    assert plan.grouped and plan.to_dict()["grouped"] is True
    assert "GROUP BY" in home and "COUNT(*) AS __N" in home and "__FAR" not in home and "'DELIVERED'" in home
    assert "GROUP BY" in stage and "SUM(H.__A1)" in stage and "__FAR_" in stage and "DELIVERED" not in stage
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


# O2/O3 — reads past a type read by key, and the shapes that cross as one row per key: each held to the single statement.
DEEPER = {
    "orders by customer region, a join inside a keyed read": {
        "object_type": "Order", "measures": [{"agg": "count", "name": "orders"}], "by": ["placed_by.located_in.region"]},
    "distinct customers by region, a far type's own key read beside a join inside its read": {
        "object_type": "Order", "measures": [{"agg": "count_distinct", "path": "placed_by", "name": "customers"}],
        "by": ["placed_by.located_in.region"]},
    "revenue from big spenders, a binding of a type read by key": {
        "object_type": "Order", "filters": [{"path": "placed_by.spend", "op": ">", "value": 5000}],
        "measures": [{"agg": "sum", "path": "total_amount"}], "by": ["status"]},
    "orders by region manager, a keyed read keyed by a keyed read": {
        "object_type": "Order", "measures": [{"agg": "count", "name": "orders"}],
        "by": ["placed_by.located_in.managed_by.manager"]},
    "units by their customer's order count, a binding read by a keyed read": {
        "object_type": "OrderItem", "measures": [{"agg": "sum", "path": "quantity"}],
        "by": ["belongs_to.placed_by.order_count"]},
    "orders by latest payment event, a timeseries binding read by key": {
        "object_type": "Order", "measures": [{"agg": "count", "name": "orders"}], "by": ["latest_status"]},
    "paid total by order status, a detail binding read by key": {
        "object_type": "Order", "measures": [{"agg": "sum", "path": "paid_total"}, {"agg": "sum", "path": "event_count"}],
        "by": ["status"]},
    "payment readings by order status, pre-aggregated by key": {
        "object_type": "Order", "by": ["status"],
        "measures": [{"agg": "sum", "path": "payment_latest.latest_amount"},
                     {"agg": "count", "path": "payment_latest", "name": "readings"}]},
    "orders with a captured payment reading, tested by key": {
        "object_type": "Order", "filters": [{"path": "payment_latest.latest_status", "value": "captured"}],
        "measures": [{"agg": "count", "name": "orders"}]},
    "customer revenue by country, a to-many link pre-aggregated by key": {
        "object_type": "Customer", "by": ["country"],
        "measures": [{"agg": "sum", "path": "customer_to_order.total_amount"},
                     {"agg": "count", "path": "customer_to_order", "name": "orders"},
                     {"agg": "avg", "path": "customer_to_order.total_amount"}]},
    "customers with a delivered order, an EXISTS read by key": {
        "object_type": "Customer", "filters": [{"path": "customer_to_order.status", "value": "delivered"}],
        "measures": [{"agg": "count", "name": "customers"}], "by": ["country"]},
    "customers without an order, a NOT EXISTS read by key": {
        "object_type": "Customer", "filters": [{"path": "customer_to_order", "op": "not_exists"}],
        "measures": [{"agg": "count", "name": "customers"}]},
    "products in a delivered order, an EXISTS read by key that joins on its own connection": {
        "object_type": "Product", "filters": [{"path": "product_to_order_item.belongs_to.status", "value": "delivered"}],
        "measures": [{"agg": "count", "name": "products"}], "by": ["category"]},
    "delivered units by category, a pre-aggregation read by key that joins on its own connection": {
        "object_type": "Product", "by": ["category"],
        "measures": [{"agg": "sum", "path": "product_to_order_item.quantity",
                      "where": [{"path": "belongs_to.status", "value": "delivered"}]}]},
}


@pytest.mark.parametrize("name", sorted(DEEPER))
def test_what_reaches_past_a_type_read_by_key_returns_exactly_the_rows_of_the_single_statement(wide, name):
    across, same = wide
    rows, compiled, result = answer(across, DEEPER[name])
    single, one, _ = answer(same, DEEPER[name])
    assert compiled.cross_source is not None and one.cross_source is None
    assert not result.error, result.error
    assert rows and rows == single


def test_a_read_past_a_type_read_by_key_joins_on_its_own_connection_and_chains_to_another(wide, sources):
    across, _ = wide
    graph = domain_graph(across)
    region = compile_object_query(DEEPER["orders by customer region, a join inside a keyed read"], graph,
                                  fiscal_start_month=1)
    [read] = region.cross_source.reads
    assert (read.connection_id, read.via, len(read.joins)) == (sources["crm"], "", 1)
    assert "regions" in read.from_clause() and [name for name, _ in read.projections]
    manager = compile_object_query(DEEPER["orders by region manager, a keyed read keyed by a keyed read"], graph,
                                   fiscal_start_month=1)
    parent, child = manager.cross_source.reads
    assert (parent.connection_id, child.connection_id, child.via) == (sources["crm"], sources["shop"], parent.alias)
    assert child.local in [name for name, _ in parent.projections]
    assert f"{parent.alias}.__jk_{child.alias}" in manager.cross_source.stage_sql
    absent = compile_object_query(DEEPER["customers without an order, a NOT EXISTS read by key"], graph,
                                  fiscal_start_month=1)
    [semi] = absent.cross_source.reads
    assert semi.kind == "exists" and semi.columns == ["__present"] and "IS NULL" in absent.cross_source.stage_sql.upper()
    latest = compile_object_query(DEEPER["orders by latest payment event, a timeseries binding read by key"], graph,
                                  fiscal_start_month=1)
    [binding] = latest.cross_source.reads
    assert binding.kind == "binding" and binding.base.startswith("(SELECT DISTINCT")
    spend = compile_object_query(DEEPER["revenue from big spenders, a binding of a type read by key"], graph,
                                 fiscal_start_month=1)
    [spent] = spend.cross_source.reads                     # Customer's binding joined inside Customer's own keyed read
    assert (spent.connection_id, len(spent.joins), spent.via) == (sources["crm"], 1, "")
    # A keyed read's own statement names each column once: DuckDB renames a repeated one inside a subquery, but Postgres
    # refuses the ambiguous reference, so the key a query also reads is projected once beside the joins' columns.
    distinct = compile_object_query(
        DEEPER["distinct customers by region, a far type's own key read beside a join inside its read"], graph,
        fiscal_start_month=1)
    [keyed] = distinct.cross_source.reads
    assert "customer_id" in keyed.columns and keyed.projections
    import sqlglot
    statement = keyed.from_clause()
    select = sqlglot.parse_one(statement[1:statement.rindex(") AS __far")], read="duckdb")
    names = [e.alias_or_name for e in select.expressions]
    assert "customer_id" in names and len(names) == len(set(names)), names


REFUSED = {
    "an EXISTS from a type read by key": (
        {"object_type": "Order", "filters": [{"path": "placed_by.customer_to_order", "op": "exists"}],
         "measures": [{"agg": "count"}]},
        "from inside a type read by key"),
    "a to-many link crossed from inside a keyed EXISTS": (
        {"object_type": "Customer", "measures": [{"agg": "count"}],
         "filters": [{"path": "customer_to_order.order_to_order_item.is_for.category", "value": "Kitchen"}]},
        "from inside a pre-aggregated link or an EXISTS"),
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


def test_a_timeseries_and_a_detail_binding_on_another_connection_bind_and_are_measured(wide, sources):
    across, _ = wide
    order = domain_graph(across).entities["Order"]
    latest = next(b for b in order.bindings if b.name == "payment_latest")
    events = next(b for b in order.bindings if b.name == "payment_events")
    assert (latest.kind, latest.connection_id, latest.verified) == ("timeseries", sources["crm"], True)
    assert (events.kind, events.connection_id, events.verified) == ("detail", sources["crm"], True)


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


# ── processes and rules across connections (O5) ─────────────────────────────────────────────────

#: An order's journey from its customer's signup — read by key from `crm` — to placed and shipped on `shop`, with a
#: promise on each move; and two rules: one over a type on one connection, one that reads a type on the other.
JOURNEY = {"id": "customer_journey", "entity": "Order", "owner": "growth", "stages": [
    {"name": "signed_up", "timestamp": "placed_by.signup_date"},
    {"name": "placed", "timestamp": "order_date", "promise": {"name": "first_order", "within_days": 365}},
    {"name": "shipped", "timestamp": "shipped_at", "promise": {"name": "dispatch", "within_days": 3}},
]}
EU_CUSTOMERS = {"id": "eu_customers", "entity": "Customer", "kind": "value_set", "property": "country",
                "values": ["DE", "FR", "GB", "XX"]}
EU_ORDERS = {"id": "eu_orders", "entity": "Order", "kind": "condition",
             "conditions": [{"path": "placed_by.country", "op": "in", "values": ["DE", "FR", "GB"]}]}


def counted(domain) -> dict:
    """Every process and rule in the domain as the panel reads it, without the moment it was counted."""
    graph = domain_graph(domain)
    rows = {p.id: describe_process(graph, p) for p in graph.processes.values()}
    rows |= {r.id: describe_rule(graph, r) for r in graph.rules.values()}
    for row in rows.values():
        row.pop("measured_at", None)
    return rows


def test_a_process_and_rules_across_two_connections_count_exactly_what_they_count_on_one(wide, sources):
    across, one = wide
    for domain in wide:
        declare_process(domain, JOURNEY, open_connection_for)
        declare_rule(domain, EU_CUSTOMERS, open_connection_for)
        declare_rule(domain, EU_ORDERS, open_connection_for)
    signed_up = {"object_type": "Order",
                 "measures": [{"agg": "count", "where": [{"path": "placed_by.signup_date", "op": "not_null"}]}]}
    assert compile_object_query(signed_up, domain_graph(across), fiscal_start_month=1).cross_source is not None
    counts = counted(across)
    assert counts == counted(one)
    journey = counts["customer_journey"]
    [reached] = reference(sources, ("SELECT COUNT(c.signup_date), COUNT(o.order_date), COUNT(o.shipped_at) "
                                    "FROM ecommerce.orders o LEFT JOIN ecommerce.customers c ON c.customer_id = o.customer_id"))
    assert (journey["verified"], tuple(stage["reached"] for stage in journey["stages"])) == (True, reached)
    assert [stage["promise"]["verified"] for stage in journey["stages"][1:]] == [True, True]
    [(admitted,)] = reference(sources, ("SELECT COUNT(*) FROM ecommerce.orders o JOIN ecommerce.customers c "
                                        "ON c.customer_id = o.customer_id WHERE c.country IN ('DE', 'FR', 'GB')"))
    assert (counts["eu_orders"]["admitted"], counts["eu_orders"]["verified"]) == (admitted, True)
    assert (counts["eu_customers"]["observed"], counts["eu_customers"]["missing"]) == (
        {"DE": 50, "FR": 50, "GB": 50}, ["XX"])
    # what they derive reads across the two as the single statement reads it
    for query in ({"object_type": "Order", "measures": [{"metric": "first_order_breach_rate", "scale": 100, "decimals": 2}]},
                  {"object_type": "Order", "segment": "late_dispatch", "measures": [{"agg": "count"}],
                   "by": ["placed_by.country"]},
                  {"object_type": "Order", "segment": "eu_orders", "measures": [{"agg": "sum", "path": "total_amount"}]},
                  {"object_type": "Customer", "segment": "eu_customers", "measures": [{"agg": "count"}]}):
        rows, _, result = answer(across, query)
        assert result.error is None and rows and rows == answer(one, query)[0], query


def test_the_measure_pass_counts_a_domains_processes_and_rules_again_and_says_when_one_no_longer_resolves(wide):
    across, _ = wide
    for domain in wide:
        declare_process(domain, JOURNEY, open_connection_for)
        declare_rule(domain, EU_ORDERS, open_connection_for)
    measured, on_one = (measure_domain(domain, open_connection_for) for domain in wide)
    assert (measured["processes"], measured["rules"]) == (on_one["processes"], on_one["rules"])
    assert [(p["process"], p["verified"], [x["promise"] for x in p["promises"]]) for p in measured["processes"]] == [
        ("customer_journey", True, ["first_order", "dispatch"])]
    assert [(r["rule"], r["verified"]) for r in measured["rules"]] == [("eu_orders", True)]
    OV.delete_organisation_override(*across.tree, "link", "Order_placed_by_Customer")
    unlinked = measure_domain(across, open_connection_for)
    assert [(row["verified"], "no longer resolves" in row["note"]) for row in unlinked["processes"] + unlinked["rules"]] == [
        (False, True), (False, True)]
    recorded = [OV.find_override(*across.tree, kind, name).binding[kind]["measured"]["verified"]
                for kind, name in (("process", "customer_journey"), ("rule", "eu_orders"))]
    assert recorded == [False, False]                       # written back through the organisation's own writer


def test_a_process_or_rule_reading_another_organisations_connection_is_refused_before_anything_is_counted(
        wide, sources, monkeypatch):
    across, _ = wide
    monkeypatch.setattr(registry, "get_connection_org", lambda cid: "another-org" if cid == sources["crm"] else "")

    def never(_connection_id):
        raise AssertionError("a declaration on another organisation's connection was counted")
    for declare, spec in ((declare_process, JOURNEY), (declare_rule, EU_ORDERS)):
        with pytest.raises(DomainRefused) as refused:
            declare(across, spec, never)
        assert refused.value.status == 403 and sources["crm"] in refused.value.detail
    assert (domain_graph(across).processes, domain_graph(across).rules) == ({}, {})


# ── an object's page, what it links to and its name, across connections (O5) ───────────────────────────────────


@contextmanager
def opened_sources():
    """``source_db`` as the doors hand it: each connection opened the first time a read needs it, all closed at the end."""
    opened: dict = {}

    def source_db(connection_id: str):
        if connection_id not in opened:
            opened[connection_id] = open_connection_for(connection_id)
        return opened[connection_id]
    try:
        yield source_db
    finally:
        for db in opened.values():
            db.close()


def page_of(domain, object_type: str, pk: str) -> dict:
    with opened_sources() as source_db:
        return get_object(domain_graph(domain), None, object_type, pk, source_db=source_db).to_dict()


def test_an_objects_page_across_two_connections_reads_what_it_reads_on_one(wide, sources):
    across, one = wide
    for domain, where in zip(wide, ("crm", "whole")):
        # a payment is found from its order by `order_id`, a column of the payment that is not its key: the page
        # looks it up where the payments live
        declare_entity(domain, typed("Payment", "payments", "payment_id", sources[where]), open_connection_for)
        declare_link(domain, {"from_entity": "Order", "to_entity": "Payment", "name": "paid_by", "from_column": "order_id",
                              "to_column": "order_id"}, open_connection_for)
    for object_type, pk in (("Order", "O000002"), ("Order", "O000010"), ("Customer", "C00001"), ("Region", "DE")):
        assert page_of(across, object_type, pk) == page_of(one, object_type, pk), (object_type, pk)
    order = page_of(across, "Order", "O000002")
    values = {p["name"]: p["value"] for p in order["properties"]}
    assert normal([[values["psp"], values["latest_status"], values["event_count"], values["paid_total"]]]) == reference(
        sources, ("SELECT (SELECT psp FROM ecommerce.payments WHERE order_id = 'O000002'), "
                  "(SELECT status FROM ecommerce.payment_events WHERE order_id = 'O000002' ORDER BY event_at DESC LIMIT 1), "
                  "(SELECT COUNT(status) FROM ecommerce.payment_events WHERE order_id = 'O000002'), "
                  "(SELECT SUM(amount) FROM ecommerce.payment_events WHERE order_id = 'O000002')"))
    assert [len(series["rows"]) for series in order["timeseries"]] == [3]       # the readings behind the latest, on crm
    [(payment,)] = reference(sources, "SELECT payment_id FROM ecommerce.payments WHERE order_id = 'O000002'")
    paid_by = next(link for link in order["links"] if link["name"] == "paid_by")
    assert (paid_by["kind"], paid_by["pk"]) == ("to-one", payment)
    links = {link["name"]: link for link in page_of(across, "Customer", "C00001")["links"]}
    [(placed,)] = reference(sources, "SELECT COUNT(*) FROM ecommerce.orders WHERE customer_id = 'C00001'")
    assert (links["customer_to_order"]["kind"], links["customer_to_order"]["count"]) == ("to-many", placed)
    with pytest.raises(ObjectNotFound):
        page_of(across, "Order", "O999999")


def test_the_objects_a_link_reaches_across_two_connections_are_listed_as_on_one(wide, sources):
    listed = []
    for domain in wide:
        with opened_sources() as source_db:
            listed.append(list_linked(domain_graph(domain), None, "Customer", "C00001", "customer_to_order",
                                      limit=2, offset=1, source_db=source_db))
    assert listed[0] == listed[1]
    [(placed,)] = reference(sources, "SELECT COUNT(*) FROM ecommerce.orders WHERE customer_id = 'C00001'")
    at = listed[0]["columns"].index("order_id")
    assert [(row[at],) for row in listed[0]["rows"]] == reference(sources, (
        "SELECT order_id FROM ecommerce.orders WHERE customer_id = 'C00001' ORDER BY order_id LIMIT 2 OFFSET 1"))
    assert listed[0]["has_more"] is (placed > 3)


def test_a_type_is_named_by_its_row_or_by_a_binding_on_another_connection_counted_where_it_is_read(
        wide, sources, monkeypatch):
    across, _ = wide
    for domain in wide:
        set_display_property(domain, "Customer", "full_name", open_connection_for)
        set_display_property(domain, "Order", "psp", open_connection_for)     # read from `payments` on crm; Order is on shop
    keys = ["O000001", "O000002", "O000010", "O900001", "O999999"]         # no payment · a payment for no order · no order
    named = []
    for domain in wide:
        with opened_sources() as source_db:
            named.append(titles(domain_graph(domain), None, "Order", keys, source_db=source_db))
    assert named[0] == named[1]
    assert (named[0]["through"], named[0]["titles"]) == ("payment", dict(reference(sources, (
        "SELECT o.order_id, p.psp FROM ecommerce.orders o JOIN ecommerce.payments p ON p.order_id = o.order_id "
        "WHERE o.order_id IN ('O000001', 'O000002', 'O000010', 'O900001', 'O999999')"))))
    [(full_name,)] = reference(sources, "SELECT full_name FROM ecommerce.customers WHERE customer_id = 'C00001'")
    [(psp,)] = reference(sources, "SELECT psp FROM ecommerce.payments WHERE order_id = 'O000002'")
    assert (page_of(across, "Customer", "C00001")["title"], page_of(across, "Order", "O000002")["title"]) == (full_name, psp)
    entry = OV.find_override(*across.tree, "entity", "Order").binding["display_property"]
    [(rows, non_null, distinct)] = reference(sources, "SELECT COUNT(*), COUNT(psp), COUNT(DISTINCT psp) FROM ecommerce.payments")
    assert (entry["connection_id"], entry["rows"], entry["non_null"], entry["distinct"], entry["verified"]) == (
        sources["crm"], rows, non_null, distinct, False)       # three providers are a category; a person may name by it
    with pytest.raises(DomainRefused) as moving:
        set_display_property(across, "Order", "latest_status", open_connection_for)
    assert moving.value.status == 400 and "timeseries" in moving.value.detail
    report = measure_domain(across, open_connection_for)
    assert [(r["entity"], r["property"], r["connection_id"], r["bound"]) for r in report["display_properties"]] == [
        ("Customer", "full_name", sources["crm"], True), ("Order", "psp", sources["crm"], True)]
    monkeypatch.setattr(registry, "get_connection_org", lambda cid: "another-org" if cid == sources["crm"] else "")
    with pytest.raises(DomainRefused) as foreign:
        set_display_property(across, "Order", "psp", open_connection_for)
    assert foreign.value.status == 403


# ── the home rows grouped at the key's grain (O4) ───────────────────────────────────────────────────────────────

#: Each way a group's rows roll up in the stage: an aggregate over home values computed per group, and one that reads a far
#: value weighed by how many rows its group holds — over groups of one row and over groups of many.
ROLLED = {
    # orders over 250 only: every seeded customer placed ten orders and a status keeps the same share of each one's, so
    # groups of one size would let an average of the groups' averages pass for the average — an amount does not
    "the smallest, largest and average order over 250 and the orders per customer city (home values rolled up)": {
        "object_type": "Order", "by": ["placed_by.city"], "filters": [{"path": "total_amount", "op": ">", "value": 250}],
        "measures": [{"agg": "min", "path": "total_amount"}, {"agg": "max", "path": "total_amount"},
                     {"agg": "avg", "path": "total_amount"}, {"agg": "count", "name": "orders"}]},
    "delivered orders by customer country (a home condition inside a count)": {
        "object_type": "Order", "by": ["placed_by.country"],
        "measures": [{"agg": "count", "name": "delivered", "where": [{"path": "status", "value": "delivered"}]}]},
    "orders of customers in a country nobody lives in (a count over no rows is zero)": {
        "object_type": "Order", "filters": [{"path": "placed_by.country", "value": "XX"}], "measures": [{"agg": "count"}]},
    # a far value itself is summed only where it is one per object (the compiler refuses the fan-out), so a group of many
    # rows meets a far value through a condition: one customer's orders share their customer's country
    "German customers' orders by status (a far condition counted over groups of many)": {
        "object_type": "Order", "by": ["status"],
        "measures": [{"agg": "count", "name": "german", "where": [{"path": "placed_by.country", "value": "DE"}]}]},
    "items German customers ordered, by status (a far condition inside a sum over groups of many)": {
        "object_type": "Order", "by": ["status"],
        "measures": [{"agg": "sum", "path": "item_count", "where": [{"path": "placed_by.country", "value": "DE"}]}]},
    "the average items of a German customer's order, by status (a far condition inside an average over groups of many)": {
        "object_type": "Order", "by": ["status"],
        "measures": [{"agg": "avg", "path": "item_count", "where": [{"path": "placed_by.country", "value": "DE"}]}]},
    "the average paid amount by customer country (a far value averaged over groups of one)": {
        "object_type": "Order", "by": ["placed_by.country"], "measures": [{"agg": "avg", "path": "paid_amount"}]},
    "the latest customer signup by status (a far maximum)": {
        "object_type": "Order", "by": ["status"], "measures": [{"agg": "max", "path": "placed_by.signup_date"}]},
    "distinct customers per payment provider (a home value counted distinct beside a far group)": {
        "object_type": "Order", "by": ["psp"], "measures": [{"agg": "count_distinct", "path": "customer_id"}]},
    "revenue among captured payments by status (a far condition inside a sum of a home value)": {
        "object_type": "Order", "by": ["status"],
        "measures": [{"agg": "sum", "path": "total_amount", "where": [{"path": "payment_status", "value": "captured"}]}]},
}


@pytest.mark.parametrize("name", sorted(ROLLED))
def test_home_rows_grouped_at_the_keys_grain_roll_up_to_exactly_the_rows_of_the_single_statement(both, name):
    across, one = both
    rows, compiled, result = answer(across, ROLLED[name])
    assert result.error is None and compiled.cross_source.grouped is True, result.error
    assert rows == answer(one, ROLLED[name])[0]


def test_every_aggregate_shape_across_two_connections_reads_its_home_rows_in_groups(wide):
    graph = domain_graph(wide[0])
    shapes = {**QUERIES, **DEEPER}
    assert [name for name, query in shapes.items()
            if not compile_object_query(query, graph, fiscal_start_month=1).cross_source.grouped] == []


def test_what_no_group_rolls_up_keeps_the_home_rows_one_per_object(sources):
    read = XS.KeyedRead(alias="x1", kind="link", connection_id=sources["crm"], table="ecommerce.customers", sql=None,
                        key="customer_id", local="t0.customer_id", label="placed_by", target="Customer",
                        columns=["country"])
    joined = "FROM ecommerce.orders AS t0 LEFT JOIN __far_x1 AS x1 ON x1.customer_id = t0.customer_id"
    for select, grouped in (("x1.country, COUNT(*) AS n", True), ("x1.country, MEDIAN(t0.total_amount) AS m", False),
                            ("x1.country, STDDEV_SAMP(t0.total_amount) AS s", False),
                            ("x1.country, SUM(t0.total_amount) OVER () AS w", False), ("x1.country, t0.order_id", False)):
        tail = " GROUP BY x1.country" if "(" in select and "OVER" not in select else ""
        plan = XS.split(f"SELECT {select} {joined}{tail}", {"x1": read}, dialect="duckdb", date_cols=set())
        assert (plan.grouped, "GROUP BY" in plan.home_sql.upper()) == (grouped, grouped), select


def test_the_home_cap_counts_groups_so_more_objects_than_it_holds_are_answered_from_their_groups(both, sources, monkeypatch):
    across, one = both
    [(orders, customers)] = reference(sources, "SELECT COUNT(*), COUNT(DISTINCT customer_id) FROM ecommerce.orders")
    monkeypatch.setattr(XS, "MAX_HOME_ROWS", int(customers))           # fewer than the orders, as many as their customers
    query = QUERIES["orders by customer country"]
    compiled = compile_object_query(query, domain_graph(across), fiscal_start_month=1)
    db = open_connection_for(sources["shop"])
    try:
        result, timings = XS.execute_plan(compiled.cross_source, home_connection_id=sources["shop"], home_db=db,
                                          open_source=open_connection_for, display_sql=compiled.sql)
    finally:
        db.close()
    assert result.error is None and normal(result.rows) == answer(one, query)[0]
    assert (timings[0]["read"], timings[0]["rows"], timings[0]["objects"]) == ("home", customers, orders)


# ── a source that runs SQL as it is written, in its own dialect (O1b) ───────────────────────────────────────────


class ReadAsBigQuery:
    """A connection that runs every statement as BigQuery reads it, over a DuckDB file. BigQuery, MySQL, Snowflake and
    Exasol run the SQL they are handed as written (`writes_native_sql`), and on the backtick engines a double-quoted
    identifier is a string literal — so SQL written for DuckDB reads nothing there, silently."""
    dialect, writes_native_sql = "bigquery", True

    def __init__(self, inner):
        self.inner = inner
        if hasattr(inner, "execute_typed"):
            self.execute_typed = lambda label, sql: inner.execute_typed(label, self.read(sql))

    @staticmethod
    def read(sql: str) -> str:
        """The statement as BigQuery takes it: a double-quoted token names nothing there (sqlglot's reader lets one stand
        for a table's name, which BigQuery never does), so one is refused before anything is read."""
        import re

        import sqlglot
        if '"' in re.sub(r"'(?:[^']|'')*'", "", sql):
            raise ValueError(f"BigQuery reads a double-quoted token as a string, never as a name: {sql[:120]}")
        return sqlglot.transpile(sql, read="bigquery", write="duckdb")[0]

    def execute(self, label, sql):
        return self.inner.execute(label, self.read(sql))

    def execute_bounded(self, label, sql, max_rows):
        return self.inner.execute_bounded(label, self.read(sql), max_rows)

    def read_typed_rows(self, label, sql, max_rows):
        return self.inner.read_typed_rows(label, self.read(sql), max_rows)

    def close(self):
        self.inner.close()


#: One customer's segment — from a table and columns whose names need quoting, which only a builder's catalogue reaches
#: (a declaration names identifiers alone), and the same rows under plain names, for a declaration to bind.
SEGMENTS = """
CREATE SCHEMA ecommerce;
CREATE TABLE ecommerce."customer segments" AS
SELECT printf('C%05d', i) AS "customer id", CASE WHEN i % 3 = 0 THEN 'Gold' ELSE 'Blue' END AS "Segment Name"
FROM range(1, 501) t(i);
CREATE TABLE ecommerce.customer_segments AS
SELECT "customer id" AS customer_id, "Segment Name" AS segment_name FROM ecommerce."customer segments";
"""


@pytest.fixture(scope="module")
def segments(tmp_path_factory):
    """A registered DuckDB file holding `SEGMENTS`."""
    path = tmp_path_factory.mktemp("segments") / "segments.duckdb"
    con = duckdb.connect(str(path))
    con.execute(SEGMENTS)
    con.close()
    return registry.add_connection("on8-segments", "duckdb", str(path))


def reading_as_bigquery(*connection_ids):
    """An opener that hands back the named connections read as BigQuery reads SQL, and every other as it is."""
    def open_source(connection_id: str):
        db = open_connection_for(connection_id)
        return ReadAsBigQuery(db) if connection_id in connection_ids else db
    return open_source


def answered(domain, query: dict, open_source) -> list[tuple]:
    """`answer`, compiled in the dialect of the connection its anchor lives on, as the object door compiles it."""
    graph = domain_graph(domain)
    home = entity_source(graph, find_object_type(graph, query["object_type"]))
    db = open_source(home)
    try:
        compiled = compile_object_query(query, graph, dialect=db.dialect, fiscal_start_month=1)
        if compiled.cross_source is not None:
            result, _ = XS.execute_plan(compiled.cross_source, home_connection_id=home, home_db=db,
                                        open_source=open_source, display_sql=compiled.sql)
        else:
            result = db.execute("objects", compiled.sql)
    finally:
        db.close()
    assert result.error is None, result.error
    return normal(result.rows)


def test_sources_that_run_sql_as_bigquery_reads_it_are_measured_bound_and_read_in_their_own_dialect(sources, segments):
    open_source = reading_as_bigquery(sources["crm"], segments)
    domain = resolve_domain("native")
    declare_entity(domain, typed("Order", "orders", "order_id", sources["shop"]), open_source)
    declare_entity(domain, typed("Customer", "customers", "customer_id", sources["crm"]), open_source)
    declare_link(domain, PLACED_BY, open_source)
    bind_source(domain, "Order", "payment", {**PAYMENT, "connection_id": sources["crm"]}, open_source)
    bind_source(domain, "Customer", "segment", {"schema_name": "ecommerce", "table": "customer_segments",
                                                "key": "customer_id", "properties": {"segment": "segment_name"},
                                                "connection_id": segments}, open_source)
    set_display_property(domain, "Customer", "segment", open_source)
    graph = domain_graph(domain)
    customer, placed = graph.entities["Customer"], graph.relationships["Order_placed_by_Customer"]
    bound = {b.name: b.verified for b in [*graph.entities["Order"].bindings, *customer.bindings]}
    assert (customer.backing.verified, placed.measured_cardinality, placed.value_overlap, bound) == (
        True, "N:1", 1.0, {"payment": True, "segment": True})
    assert customer.display_property.distinct == 2                        # counted on the segments source, as BigQuery

    [(gold, blue)] = normal(duckdb.connect().execute(
        "SELECT COUNT(*) FILTER (WHERE i % 3 = 0), COUNT(*) FILTER (WHERE i % 3 <> 0) FROM range(1, 501) t(i)").fetchall())
    assert answered(domain, QUERIES["orders by customer country"], open_source) == reference(sources, (
        "SELECT c.country, COUNT(*) FROM ecommerce.orders o LEFT JOIN ecommerce.customers c "
        "ON o.customer_id = c.customer_id GROUP BY 1"))                    # Customer read by key where BigQuery reads it
    assert answered(domain, {"object_type": "Customer", "measures": [{"agg": "count"}], "by": ["segment"]},
                    open_source) == normal([["Gold", gold], ["Blue", blue]])  # a BigQuery home, and a far read on it

    opened: dict = {}

    def source_db(connection_id: str):
        if connection_id not in opened:
            opened[connection_id] = open_source(connection_id)
        return opened[connection_id]
    try:
        page = get_object(graph, None, "Customer", "C00003", source_db=source_db).to_dict()
        order = get_object(graph, None, "Order", "O000002", source_db=source_db).to_dict()
    finally:
        for db in opened.values():
            db.close()
    [(psp,)] = reference(sources, "SELECT psp FROM ecommerce.payments WHERE order_id = 'O000002'")
    assert (page["title"], {p["name"]: p["value"] for p in order["properties"]}["psp"]) == ("Gold", psp)


def test_every_measurement_probe_reads_a_source_that_runs_sql_as_bigquery_reads_it(segments):
    from aughor.ontology.backing import measure_key
    from aughor.ontology.bindings import describe_with, measure_binding
    from aughor.ontology.cardinality import measure_side
    from aughor.ontology.declared import _count_side, measure_declared_link
    from aughor.ontology.display import measure_display
    from aughor.ontology.lifecycle import observed_states
    from aughor.ontology.models import Backing, Binding, EntityProperty, OntologyEntity
    from aughor.ontology.sources import distinct_keys
    from aughor.semantic.object_instances import _read

    source = 'ecommerce."customer segments"'
    columns = {"customer id": EntityProperty(name="customer id", data_type="VARCHAR", semantic_type="key"),
               "Segment Name": EntityProperty(name="Segment Name", data_type="VARCHAR", semantic_type="dimension")}

    def segment_type(type_id: str) -> OntologyEntity:
        return OntologyEntity(id=type_id, display_name=type_id, source_tables=["ecommerce.customer segments"],
                              properties=dict(columns), identity_key="customer id", grain_verified=True,
                              backing=Backing(kind="table", table="ecommerce.customer segments", primary_key="customer id"))
    entity = segment_type("Segment")
    graph = OntologyGraph(connection_id=segments, schema_name="ecommerce", schema_fingerprint="",
                          entities={"Segment": entity, "Tier": segment_type("Tier")})
    tier = Binding(name="tier", kind="static", table="ecommerce.customer segments", key="customer id",
                   properties={"tier": EntityProperty(name="tier", data_type="VARCHAR")},
                   columns={"tier": "Segment Name"}, verified=True, note="one row per Segment")

    class Beside:
        """Another connection object over the same connection, as a binding's objects on a second one are read."""
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def beside(db):
        return ReadAsBigQuery(db.inner) if isinstance(db, ReadAsBigQuery) else Beside(db)

    def probes(db) -> dict:
        return {"side": measure_side(db, "ecommerce.customer segments", "customer id"),
                "key": measure_key(db, source, "customer id"),
                "states": observed_states(db, "ecommerce.customer segments", "Segment Name"),
                "keys": distinct_keys(db, f"{source} AS s", "s", "customer id"),
                "columns": describe_with(db)(source),
                "display": measure_display(db, entity, "Segment Name", "human"),
                "binding": measure_binding(db, entity, tier),
                "binding across": measure_binding(db, entity, tier, object_db=beside(db)),
                "link side": _count_side(db, entity, "customer id"),
                "link": measure_declared_link(db, graph, {"from_entity": "Segment", "to_entity": "Tier", "name": "is",
                                                          "from_column": "customer id", "to_column": "customer id"}),
                "page": list(_read(db, f'SELECT s."Segment Name" FROM {source} AS s WHERE s."customer id" = \'C00003\'',
                                   "a segment").rows)}
    plain = open_connection_for(segments)
    try:
        expected = probes(plain)
    finally:
        plain.close()
    native = ReadAsBigQuery(open_connection_for(segments))
    try:
        read = probes(native)
    finally:
        native.close()
    assert read == expected
    assert (expected["side"].distinct, expected["key"][0], expected["states"], len(expected["keys"][0])) == (
        500, (500, 500, 500), {"Blue": 334, "Gold": 166}, 500)
    assert set(expected["columns"][0]) == {"customer id", "Segment Name"} and expected["page"] == [["Gold"]]
    assert (expected["binding"].covered, expected["binding across"].covered, expected["link side"],
            expected["link"]["value_overlap"]) == (500, 500, (500, 500, 500), 1.0)


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
    many = client.post("/objects/query", params=domain,
                       json={"object_type": "Customer", "measures": [{"agg": "count", "path": "customer_to_order"}]}).json()
    assert many["path"] == "compiled" and many["error"] is None       # O3 — a to-many link across two connections
    assert normal(many["rows"]) == reference(sources, (
        "SELECT COUNT(*) FROM ecommerce.customers c JOIN ecommerce.orders o ON o.customer_id = c.customer_id"))
    refused = client.post("/objects/query", params=domain, json={
        "object_type": "Customer", "measures": [{"agg": "count_distinct", "path": "customer_to_order.status"}]})
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


def test_the_process_rule_and_frame_doors_take_an_organisations_ontology_over_http(client, wide):
    domain = {"domain": "default"}
    declared = client.post("/ontology/processes", params=domain, json=JOURNEY)
    assert declared.status_code == 200, declared.text
    on_one = client.post("/ontology/processes", params={"domain": "reference"}, json=JOURNEY)
    assert (declared.json()["domain"], declared.json()["process"]["verified"]) == ("default/default", True)
    assert {**declared.json()["process"], "measured_at": None} == {**on_one.json()["process"], "measured_at": None}
    assert client.post("/ontology/processes", params=domain, json=JOURNEY).status_code == 409
    proposed = client.post("/ontology/processes", params=domain, json={**JOURNEY, "id": "proposed", "origin": "model"})
    assert proposed.status_code == 400 and "edited by people only" in proposed.json()["detail"]
    unreadable = client.post("/ontology/processes", params=domain, json={"id": "unreadable", "entity": "Order", "stages": [
        {"name": "signed_up", "timestamp": "placed_by.nickname"}, {"name": "placed", "timestamp": "order_date"}]})
    assert unreadable.status_code == 400 and "nickname" in unreadable.json()["detail"]

    ruled = client.post("/ontology/rules", params=domain, json=EU_ORDERS)
    assert ruled.status_code == 200, ruled.text
    assert ruled.json()["rule"]["admitted"] == client.post("/ontology/rules", params={"domain": "reference"},
                                                           json=EU_ORDERS).json()["rule"]["admitted"]
    assert client.post("/ontology/rules", params=domain,
                       json={**EU_ORDERS, "provenance": "model:some-model@1"}).status_code == 400

    listed = client.get("/ontology/processes", params=domain)
    assert listed.status_code == 200, listed.text
    assert (listed.json()["domain"], [p["id"] for p in listed.json()["processes"]],
            [r["id"] for r in listed.json()["rules"]]) == ("default/default", ["customer_journey"], ["eu_orders"])
    carried = client.get("/ontology/processes", params={"connection_id": "domain:default", "domain": "default"})
    assert carried.json() == listed.json()                 # the scope the web carries an organisation's ontology in
    rate = client.post("/objects/query", params=domain, json={
        "object_type": "Order", "by": ["placed_by.country"],
        "measures": [{"metric": "dispatch_breach_rate", "scale": 100, "decimals": 2}]}).json()
    assert (rate["path"], rate["error"]) == ("compiled", None), rate

    framed = client.post("/ontology/frame", params=domain,
                         json={"question": "Which customer countries break the dispatch promise most often?"})
    assert framed.status_code == 200, framed.text
    frame = framed.json()["frame"]
    assert (frame["defines"], frame["outcomes"][frame["chosen"]]["name"], frame["start"]["entity"]) == (
        True, "dispatch_breach_rate", "Order")
    assert (frame["drivers"][0]["path"], frame["drivers"][0]["named"]) == ("placed_by.country", True)   # read by key
    assert "late_dispatch" in frame["compiled"] and framed.json()["domain"] == "default/default"

    remeasured = client.post("/ontology/measure", params=domain).json()
    assert [(p["process"], p["verified"]) for p in remeasured["processes"]] == [("customer_journey", True)]
    assert [(r["rule"], r["verified"]) for r in remeasured["rules"]] == [("eu_orders", True)]
    assert client.delete("/ontology/processes/customer_journey", params=domain).status_code == 200
    assert client.delete("/ontology/processes/customer_journey", params=domain).status_code == 404
    assert client.delete("/ontology/rules/eu_orders", params=domain).status_code == 200
    assert client.get("/ontology/processes", params=domain).json() == {"domain": "default/default", "processes": [],
                                                                      "rules": []}
    gone = client.post("/objects/query", params=domain,
                       json={"object_type": "Order", "segment": "late_dispatch", "measures": [{"agg": "count"}]}).json()
    assert gone["path"] == "refused"
    assert not (OV._ROOT / "domain_default").exists()



def test_the_object_doors_open_an_organisations_objects_where_they_live_over_http(client, wide, sources, monkeypatch):
    domain = {"domain": "default"}
    named = client.put("/ontology/entities/Customer", params=domain, json={"display_property": "full_name"})
    assert named.status_code == 200, named.text
    assert (named.json()["domain"], named.json()["override"]["fields"]["display_property"]) == ("default/default",
                                                                                               "full_name")
    worded = client.put("/ontology/entities/Customer", params=domain, json={"description": "people who buy"})
    assert worded.status_code == 400 and "display property" in worded.json()["detail"]
    moving = client.put("/ontology/entities/Order", params=domain, json={"display_property": "latest_status"})
    assert moving.status_code == 400 and "timeseries" in moving.json()["detail"]
    unknown = client.put("/ontology/entities/Order", params=domain, json={"display_property": "nickname"})
    assert unknown.status_code == 400 and "has no property 'nickname'" in unknown.json()["detail"]

    [(full_name,)] = reference(sources, "SELECT full_name FROM ecommerce.customers WHERE customer_id = 'C00001'")
    [(placed,)] = reference(sources, "SELECT COUNT(*) FROM ecommerce.orders WHERE customer_id = 'C00001'")
    opened = client.get("/objects/Customer/C00001", params=domain)
    assert opened.status_code == 200, opened.text
    assert (opened.json()["path"], opened.json()["domain"], opened.json()["connection_id"], opened.json()["title"]) == (
        "object", "default/default", sources["crm"], full_name)
    carried = client.get("/objects/Customer/C00001", params={"connection_id": "domain:default", "domain": "default"})
    assert carried.json() == opened.json()                 # the scope the web carries an organisation's ontology in
    stray = client.get("/objects/Customer/C00001", params={"connection_id": "domain:default"})
    assert stray.status_code == 400 and "?domain=" in stray.json()["detail"]
    assert client.get("/objects/Customer/C99999", params=domain).status_code == 404
    assert client.get("/objects/Nothing/1", params=domain).json()["path"] == "refused"
    linked = client.get("/objects/Customer/C00001/links/customer_to_order", params={**domain, "limit": 2}).json()
    assert (linked["path"], linked["connection_id"], len(linked["rows"])) == ("links", sources["shop"], min(2, placed))
    titled = client.post("/objects/titles", params=domain, json={"object_type": "Customer", "keys": ["C00001", "C99999"]})
    assert (titled.json()["path"], titled.json()["titles"]) == ("titles", {"C00001": full_name})

    # a page that would read a connection the organisation does not hold is refused, never read part-way
    monkeypatch.setattr(registry, "get_connection_org", lambda cid: "another-org" if cid == sources["crm"] else "")
    assert client.get("/objects/Order/O000002", params=domain).status_code == 403



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
    assert client.delete("/ontology/overrides/entity/Order", params=carried).status_code == 400
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
