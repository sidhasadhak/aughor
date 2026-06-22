"""Fix A (#159) — general ratio-across-a-dimension-join de-fan. The FK-root chasm guards
(detect_fanout / _chasm_roots / sum_over_chasm_fanout) only see joins on a shared FK ROOT;
they MISS two fact tables joined on the categorical dimension they're grouped by, with a ratio
drawing its numerator from one table and denominator from the other (the missimi revenue÷spend
shape). This module proves the new `dimension_ratio_chasm` detector + `build_dim_ratio_rewrite`
cure: pre-aggregate each side to the dimension grain, 1:1-join, divide — correct for ANY
cardinality, high-precision (fires only on the exact shape)."""
from __future__ import annotations

import duckdb

from aughor.sql.fanout import (
    dimension_ratio_chasm, build_dim_ratio_rewrite, defan, detect_fanout,
)

# revenue (orders) ÷ spend (marketing_performance), joined on the channel DIMENSION they group by.
_ROAS = (
    "SELECT o.marketing_channel, SUM(o.attributed_revenue) / NULLIF(SUM(mp.spend), 0) AS roas "
    "FROM orders o JOIN marketing_performance mp ON o.marketing_channel = mp.channel "
    "GROUP BY o.marketing_channel ORDER BY roas DESC"
)


# ── detection ────────────────────────────────────────────────────────────────────

def test_detects_the_cross_table_dimension_ratio():
    f = dimension_ratio_chasm(_ROAS)
    assert f is not None and f.kind == "dim_ratio"
    assert set(f.satellites) == {"orders", "marketing_performance"}
    assert f.hub_root in ("marketing_channel", "channel")


def test_fk_root_chasm_guard_alone_misses_this_shape():
    # The point of Fix A: detect_fanout (FK-root based) does NOT see a dimension-value join.
    assert detect_fanout(_ROAS, {"orders": ["marketing_channel", "attributed_revenue"],
                                 "marketing_performance": ["channel", "spend"]}) is None


# ── precision: shapes that must NOT fire ───────────────────────────────────────────

def test_same_table_ratio_no_join_is_ignored():
    assert dimension_ratio_chasm(
        "SELECT customer_country, SUM(freight_value)/NULLIF(SUM(order_value),0) AS pct "
        "FROM orders GROUP BY customer_country") is None


def test_ratio_grouped_by_non_join_column_is_ignored():
    # join on order_id (FK) but grouped by region — independent pre-agg is NOT valid here.
    assert dimension_ratio_chasm(
        "SELECT o.region, SUM(o.value)/NULLIF(SUM(p.amount),0) AS m "
        "FROM orders o JOIN payments p ON o.order_id=p.order_id GROUP BY o.region") is None


def test_numerator_and_denominator_same_table_is_ignored():
    assert dimension_ratio_chasm(
        "SELECT o.channel, SUM(o.rev)/NULLIF(SUM(o.cost),0) AS m "
        "FROM orders o JOIN dim d ON o.channel=d.channel GROUP BY o.channel") is None


def test_already_pre_aggregated_ctes_is_ignored():
    assert dimension_ratio_chasm(
        "WITH a AS (SELECT ch, SUM(r) s FROM o GROUP BY ch), "
        "b AS (SELECT ch, SUM(sp) s FROM m GROUP BY ch) "
        "SELECT a.ch, a.s/b.s AS m FROM a JOIN b ON a.ch=b.ch") is None


def test_plain_sum_no_ratio_is_ignored():
    assert dimension_ratio_chasm(
        "SELECT o.channel, SUM(o.rev) FROM orders o JOIN m ON o.channel=m.channel "
        "GROUP BY o.channel") is None


def test_three_tables_is_ignored():
    assert dimension_ratio_chasm(
        "SELECT o.ch, SUM(o.r)/NULLIF(SUM(m.s),0) AS x FROM o JOIN m ON o.ch=m.ch "
        "JOIN p ON o.ch=p.ch GROUP BY o.ch") is None


def test_left_join_is_ignored():
    assert dimension_ratio_chasm(
        "SELECT o.ch, SUM(o.r)/NULLIF(SUM(m.s),0) AS x FROM o LEFT JOIN m ON o.ch=m.ch "
        "GROUP BY o.ch") is None


# ── rewrite shape + dispatch ───────────────────────────────────────────────────────

def test_rewrite_pre_aggregates_each_side_then_divides():
    f = dimension_ratio_chasm(_ROAS)
    rw = defan(_ROAS, f)              # dispatches kind=='dim_ratio'
    assert rw == build_dim_ratio_rewrite(_ROAS, f)
    low = rw.lower()
    assert "with" in low and "group by marketing_channel" in low and "group by channel" in low
    assert "nullif" in low and "/" in rw
    assert low.count("sum(") == 2     # one per side, pre-aggregated
    assert "order by roas desc" in low


def test_rewrite_preserves_percent_scale():
    sql = ("SELECT o.ch, 100.0 * SUM(o.r) / NULLIF(SUM(m.s),0) AS pct "
           "FROM orders o JOIN m ON o.ch=m.ch GROUP BY o.ch")
    f = dimension_ratio_chasm(sql)
    assert f is not None
    rw = build_dim_ratio_rewrite(sql, f)
    assert "100.0" in rw


def test_defan_returns_none_for_non_dim_ratio_kind():
    from aughor.sql.fanout import FanoutFinding
    assert build_dim_ratio_rewrite(_ROAS, FanoutFinding(hub_root="x", satellites=["a"], kind="chasm")) is None


def test_prompt_text_names_both_tables_and_dimension():
    t = dimension_ratio_chasm(_ROAS).to_prompt_text()
    assert "orders" in t and "marketing_performance" in t and "marketing_channel" in t


# ── numeric correctness: the rewrite fixes a corrupted ratio (asymmetric fan-out) ──

def test_rewrite_corrects_the_fanned_ratio_numerically():
    con = duckdb.connect()
    con.execute("CREATE TABLE orders(marketing_channel VARCHAR, attributed_revenue DOUBLE)")
    # email: 3 orders, revenue 300 ; display: 1 order, revenue 50
    con.execute("INSERT INTO orders VALUES ('email',100),('email',100),('email',100),('display',50)")
    con.execute("CREATE TABLE marketing_performance(channel VARCHAR, spend DOUBLE)")
    # email: 2 perf rows, spend 100 ; display: 1 perf row, spend 25
    con.execute("INSERT INTO marketing_performance VALUES ('email',60),('email',40),('display',25)")
    # TRUE ROAS: email 300/100 = 3.0 ; display 50/25 = 2.0
    rw = build_dim_ratio_rewrite(_ROAS, dimension_ratio_chasm(_ROAS))

    raw = dict(con.execute(_ROAS).fetchall())
    fixed = dict(con.execute(rw).fetchall())
    assert round(raw["email"], 4) == 2.0          # fanned: num×2, den×3 → 600/300 (WRONG)
    assert round(fixed["email"], 4) == 3.0        # corrected
    assert round(fixed["display"], 4) == 2.0


def test_rewrite_pushes_satellite_where_into_its_cte():
    sql = ("SELECT o.ch, SUM(o.r)/NULLIF(SUM(m.s),0) AS x FROM orders o JOIN m ON o.ch=m.ch "
           "WHERE o.region = 'EU' GROUP BY o.ch")
    f = dimension_ratio_chasm(sql)
    assert f is not None
    rw = build_dim_ratio_rewrite(sql, f).lower()
    # the o.region predicate must land in the orders CTE (alias-stripped), not the outer query.
    assert "region = 'eu'" in rw
    assert rw.index("region") < rw.index("group by")  # inside a CTE, before its group by


def test_mixed_table_where_predicate_bails():
    # an OR / cross-table conjunct can't be attributed to one CTE → no rewrite (safe bail).
    sql = ("SELECT o.ch, SUM(o.r)/NULLIF(SUM(m.s),0) AS x FROM orders o JOIN m ON o.ch=m.ch "
           "WHERE o.region = m.zone GROUP BY o.ch")
    assert dimension_ratio_chasm(sql) is None
