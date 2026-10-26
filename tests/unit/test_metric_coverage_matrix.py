"""Arc MC, MC-2 — every table and metric placed in the areas it serves, each with why, and the coverage matrix.

Measured on LuxExperience 2026-10-26: 33 tables, 12 metrics over 12 of them. These place its real table names and its
real metric names against retail's map, with no warehouse. MC-2's falsifier: a table with a metric placed in no area,
or an area said covered by a metric that reads one value in every month.
"""
from __future__ import annotations

import pytest

from aughor.packs import knowledge
from aughor.semantic import metric_coverage as C
from aughor.semantic import metric_map as M
from aughor.semantic.metrics import MetricDefinition

LUX_TABLES = {  # name: (rows, main date) — as the profiler read them
    "brand_collaborations": (62, "launch_date"), "brands": (70, ""), "clienteling_interactions": (7399, "interaction_date"),
    "consent": (35136, "consent_updated"), "corporate_entities": (6, ""), "corporate_events": (14, "event_date"),
    "countries": (35, ""), "customer_service": (13699, "created_date"), "customers": (35136, ""),
    "dim_date": (2309, "date"), "email_engagement": (35136, ""), "event_attendance": (1642, ""),
    "events": (66, "event_date"), "financial_summary": (25, ""), "group_financials": (6, ""),
    "inventory_snapshots": (172000, "snapshot_date"), "marketing_attribution": (145896, ""),
    "marketing_campaigns": (453, ""), "order_items": (274014, ""), "orders": (145896, "order_date"),
    "ownership": (12, "effective_from"), "payments": (145896, ""), "platforms": (5, ""),
    "price_history": (26005, "effective_date"), "product_variants": (37783, ""), "products": (8600, ""),
    "return_logistics": (85885, "received_date"), "returns": (85885, "return_date"),
    "shipments": (140070, "ship_date"), "stylists": (60, ""), "warehouses": (8, ""),
    "web_events": (4164697, "event_time"), "web_sessions": (4810356, ""),
}


def _m(name, label, sql, status="approved"):
    return MetricDefinition(name=name, label=label, sql=sql, connection="lux", status=status, time_kind="flow",
                            time_column="orders.order_date")


LUX_METRICS = [
    _m("gmv", "GMV", "SELECT SUM(unit_price_eur * quantity) FROM order_items"),
    _m("aov", "Average Order Value", "SELECT SUM(unit_price_eur) / COUNT(DISTINCT order_id) FROM order_items"),
    _m("gross_margin", "Gross Margin %", "SELECT 1 - SUM(cost_eur) / SUM(unit_price_eur) FROM order_items"),
    _m("item_return_rate", "Item Return Rate", "SELECT AVG(CASE WHEN returned THEN 1.0 ELSE 0 END) FROM order_items"),
    _m("session_conversion_rate", "Session Conversion Rate", "SELECT AVG(CASE WHEN converted THEN 1.0 ELSE 0 END) "
                                                             "FROM web_sessions"),
    _m("repeat_purchase_rate", "Repeat Purchase Rate", "SELECT COUNT(*) FROM orders"),
    _m("markdown_penetration", "Markdown Penetration", "SELECT AVG(CASE WHEN is_markdown THEN 1.0 ELSE 0 END) "
                                                       "FROM price_history"),
    _m("weeks_of_cover", "Average Inventory Weeks of Cover", "SELECT AVG(weeks_of_cover) FROM inventory_snapshots"),
    _m("clienteling_gmv", "Clienteling GMV per Interaction", "SELECT AVG(gmv_influenced_eur) "
                                                             "FROM clienteling_interactions"),
    _m("marketing_roas", "Marketing ROAS", "SELECT SUM(attributed_gmv_eur) / SUM(spend_eur) FROM marketing_campaigns"),
    _m("platform_share", "Platform Share", "SELECT COUNT(*) FROM platforms"),
]


@pytest.fixture
def lux(monkeypatch):
    pkgs = [p for p in knowledge.packages() if p.layer != "industry" or p.industry == "retail"]
    mmap = M.map_of(pkgs)
    facts = [C.TableFacts(name=n, rows=r, date_column=d, grain="date" if n == "dim_date" else "")
             for n, (r, d) in sorted(LUX_TABLES.items())]
    monkeypatch.setattr(C, "tables_of", lambda *a, **k: facts)
    monkeypatch.setattr(C, "_domains", lambda *a, **k: {})
    monkeypatch.setattr(C, "defined_metrics", lambda *a, **k: list(LUX_METRICS))
    moves = {m.name: {"ok": True, "why": ""} for m in LUX_METRICS}
    monkeypatch.setattr(C, "_moves", lambda *a, **k: moves)
    from aughor.semantic import coverage_proposals
    monkeypatch.setattr(coverage_proposals, "proposals_by_area", lambda *a, **k: {})
    return mmap, moves


def test_luxexperiences_tables_are_placed_by_their_names_with_why(lux):
    mmap, _ = lux
    areas = mmap.readable
    placed = {n: [p.area for p in C.place_table(C.TableFacts(n), areas)] for n in LUX_TABLES}
    assert placed["customer_service"] == ["service"]
    assert placed["web_events"] == ["traffic_conversion"] and placed["web_sessions"] == ["traffic_conversion"]
    assert placed["events"] == ["clienteling_events"] and placed["stylists"] == ["clienteling_events"]
    assert set(placed["return_logistics"]) == {"returns", "fulfilment"}
    assert placed["shipments"] == ["fulfilment"] and placed["payments"] == ["payments"]
    assert placed["consent"] == ["crm_consent"] and placed["email_engagement"] == ["crm_consent"]
    assert placed["marketing_attribution"] == ["marketing"] and placed["price_history"] == ["margin_pricing"]
    assert C.place_table(C.TableFacts("shipments"), areas)[0].why == "its name says shipment"


def test_luxexperiences_metrics_are_each_placed_in_one_area_with_why(lux):
    mmap, _ = lux
    tables = {n: C.place_table(C.TableFacts(n), mmap.readable) for n in LUX_TABLES}
    got = {m.name: C.place_metric(m, mmap, tables) for m in LUX_METRICS}
    assert {k: v.area for k, v in got.items()} == {
        "gmv": "orders_sales", "aov": "orders_sales", "gross_margin": "margin_pricing", "item_return_rate": "returns",
        "session_conversion_rate": "traffic_conversion", "repeat_purchase_rate": "customers",
        "markdown_penetration": "margin_pricing", "weeks_of_cover": "inventory",
        "clienteling_gmv": "clienteling_events", "marketing_roas": "marketing", "platform_share": M.OTHER}
    assert got["gmv"].why == "it is the knowledge base's Gross Merchandise Value (GMV)"
    assert got["clienteling_gmv"].why == "its name says clienteling"


def test_every_table_a_metric_reads_is_placed_in_an_area_even_one_no_word_names(lux):
    """The falsifier: `platforms` is named by no area, and the metric reading it places it."""
    out = C.coverage("lux", "luxexperience", mmap=lux[0])
    read = {"order_items", "web_sessions", "orders", "price_history", "inventory_snapshots",
            "clienteling_interactions", "marketing_campaigns", "platforms"}
    placed = {t["name"] for a in out["areas"] for t in a["tables"]}
    assert read <= placed
    other = next(a for a in out["areas"] if a["id"] == M.OTHER)
    assert {"name": "platforms", "rows": 5, "dated": False, "why": "Platform Share reads it"} in other["tables"]
    assert "platforms" not in out["unplaced_tables"]
    assert {"countries", "dim_date"} <= set(out["unplaced_tables"])


def test_an_area_is_never_said_covered_by_a_metric_that_reads_one_value_in_every_month(lux):
    mmap, moves = lux
    moves["item_return_rate"] = {"ok": False, "why": "it reads 1 in every one of the last 6 months with figures"}
    out = C.coverage("lux", "luxexperience", mmap=mmap)
    returns = next(a for a in out["areas"] if a["id"] == "returns")
    assert returns["state"] == "uncovered" and returns["has_data"]
    assert returns["said"] == ["Item Return Rate does not cover it: it reads 1 in every one of the last 6 months "
                               "with figures"]
    assert next(a for a in out["areas"] if a["id"] == "orders_sales")["state"] == "covered"


def test_the_matrix_names_areas_with_data_and_no_metric_and_an_area_no_pattern_covers(lux):
    out = C.coverage("lux", "luxexperience", mmap=lux[0])
    by_id = {a["id"]: a for a in out["areas"]}
    assert [a["id"] for a in out["areas"]][:3] == ["orders_sales", "returns", "margin_pricing"]
    for area in ("fulfilment", "payments", "crm_consent", "service"):
        assert by_id[area]["state"] == "uncovered" and by_id[area]["has_data"], area
    assert by_id["clienteling_events"]["state"] == "covered"
    assert by_id["clienteling_events"]["said"] == ["the knowledge base carries no pattern for this area yet — a "
                                                   "package can add one"]
    assert by_id["recurring_revenue"]["state"] == "no_data"
    assert out["counts"]["covered"] == 9 and out["counts"]["uncovered"] == 4


def test_an_approved_metric_whose_figures_are_unread_is_said_not_checked_and_covers_nothing(lux):
    mmap, moves = lux
    moves["marketing_roas"] = {"ok": None, "why": "its figures have not been read yet"}
    out = C.coverage("lux", "luxexperience", mmap=mmap)
    assert next(a for a in out["areas"] if a["id"] == "marketing")["state"] == "unchecked"


def test_a_dataset_of_a_connection_that_holds_several_reads_only_its_own_tables(monkeypatch):
    """Found live 2026-10-26: the workspace's airlines, zomato_data, bakehouse and amazon datasets were all placed on
    Olist's tables — the profiler keys an entry's tables by bare name, and the merged entry was every dataset's."""
    from aughor.db import registry
    from aughor.tools import profile_cache
    entry = {"tables": {"flights": {"table": "flights", "row_count": 900}, "olist_orders": {"table": "olist_orders",
                                                                                            "row_count": 99}},
             "columns": {"flights.dep_delay": {"table": "flights", "column": "dep_delay", "dtype": "integer"},
                         "olist_orders.price": {"table": "olist_orders", "column": "price", "dtype": "double"}}}
    monkeypatch.setattr(registry, "get_meta", lambda cid: {"schema_name": None})
    monkeypatch.setattr(profile_cache, "profile_entry_for", lambda cid, tables: entry)
    monkeypatch.setattr(profile_cache, "merged_profile_entry", lambda cid: entry)
    monkeypatch.setattr(C, "dataset_tables", lambda cid, schema: {"airlines": ["flights"]}.get(schema, []))
    scoped = C.dataset_entry("workspace", "airlines")
    assert list(scoped["tables"]) == ["flights"] and list(scoped["columns"]) == ["flights.dep_delay"]
    assert [t.name for t in C.tables_of("workspace", "airlines")] == ["flights"]
    assert C.dataset_entry("workspace", "never_profiled") == {}
    # a connection that declares its one dataset reads as before
    monkeypatch.setattr(registry, "get_meta", lambda cid: {"schema_name": "luxexperience"})
    assert C.dataset_entry("lux", "luxexperience") is entry
