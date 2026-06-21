"""Query Builder Layer-3 — reverse-compile raw SQL → semantic chips. Pins the round-trip
mapping (columns/grains → dimensions, aggregates → measures, predicates → filters, aliases
resolved to real tables) and the honest bails. Pure SQLGlot; hermetic."""
from __future__ import annotations

from aughor.sql.decompile import decompile_sql


def test_full_query_maps_to_chips():
    r = decompile_sql(
        "SELECT DATE_TRUNC('month', o.created_at) AS m, o.region, "
        "SUM(o.amount) AS revenue, COUNT(DISTINCT o.customer_id) AS buyers, COUNT(*) AS n "
        "FROM orders o JOIN customers c ON o.customer_id = c.id "
        "WHERE o.status = 'paid' AND o.amount > 100 AND c.country IN ('US','CA') "
        "AND o.note IS NOT NULL "
        "GROUP BY 1, 2 ORDER BY revenue DESC LIMIT 50"
    )
    assert r["ok"]
    assert r["primary_table"] == "orders"
    assert r["joins"] == [{"table": "customers", "alias": "c", "side": "INNER", "on": "o.customer_id = c.id"}]
    # dimensions: a month grain + a plain column, aliases resolved to the real table
    dims = {(d["col"], d["transform"], d["table"]) for d in r["dimensions"]}
    assert ("created_at", "month", "orders") in dims
    assert ("region", None, "orders") in dims
    # measures: SUM, COUNT DISTINCT, COUNT(*)
    ms = {(m["agg"], m["col"], m["alias"]) for m in r["measures"]}
    assert ("SUM", "amount", "revenue") in ms
    assert ("COUNT DISTINCT", "customer_id", "buyers") in ms
    assert ("COUNT", "*", "n") in ms
    # filters: =, >, IN, IS NOT NULL; the customers column resolves to the real table
    fs = {(f["col"], f["op"], f["val"], f["table"]) for f in r["filters"]}
    assert ("status", "=", "'paid'", "orders") in fs
    assert ("amount", ">", "100", "orders") in fs
    assert ("country", "IN", "('US', 'CA')", "customers") in fs
    assert ("note", "IS NOT NULL", "", "orders") in fs
    assert r["order_by"] == "revenue DESC" and r["limit"] == 50


def test_like_and_flipped_comparison():
    r = decompile_sql("SELECT a FROM t WHERE name LIKE '%x%' AND 100 < amount")
    fs = {(f["col"], f["op"], f["val"]) for f in r["filters"]}
    assert ("name", "LIKE", "'%x%'") in fs
    assert ("amount", ">", "100") in fs        # flipped so the column stays on the left


def test_unmapped_filter_is_surfaced_not_dropped():
    # a cross-column predicate has no chip representation — it lands in unmapped_filters
    r = decompile_sql("SELECT a FROM t WHERE a > b AND status = 'x'")
    assert any(f["col"] == "status" for f in r["filters"])
    assert r["unmapped_filters"] and "a > b" in r["unmapped_filters"][0].replace('"', "")


def test_custom_measure_for_an_expression_aggregate():
    r = decompile_sql("SELECT SUM(a)/NULLIF(SUM(b),0) AS ratio FROM t")
    assert r["measures"][0]["agg"] == "CUSTOM"
    assert "ratio" == r["measures"][0]["alias"] and "sum" in r["measures"][0]["customExpr"].lower()


def test_bails_on_cte_setop_and_subquery_source():
    assert decompile_sql("WITH x AS (SELECT 1 AS a) SELECT a FROM x")["ok"] is False
    assert decompile_sql("SELECT a FROM t1 UNION SELECT a FROM t2")["ok"] is False
    assert decompile_sql("SELECT a FROM (SELECT a FROM t) s")["ok"] is False


def test_bails_gracefully_on_garbage():
    out = decompile_sql("not sql at all ;;;")
    assert out["ok"] is False and "reason" in out
