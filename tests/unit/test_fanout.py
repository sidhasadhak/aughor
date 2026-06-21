"""Fan-out detection — the #1 model-invariant correctness failure (join amplification).

Locks the existing multi-satellite chasm-trap detection AND the new single parent-measure
fan-out case. High-precision contract: NEVER flag a correct query.
See aughor/sql/fanout.py.
"""
from aughor.sql.fanout import detect_fanout

COLS = {
    "orders":       ["order_id", "customer_id", "order_total", "status", "order_ts"],
    "order_items":  ["order_item_id", "order_id", "product_id", "quantity", "unit_price"],
    "campaigns":    ["campaign_id", "name", "budget"],
    "clicks":       ["click_id", "campaign_id", "click_ts"],
    "impressions":  ["impression_id", "campaign_id", "imp_ts"],
    "products":     ["product_id", "name", "list_price"],
}


# ── Existing behaviour: multi-satellite chasm trap (lock it) ──────────────────────

def test_multi_satellite_chasm_is_flagged():
    sql = ("SELECT ca.name, COUNT(c.click_id) AS clicks, COUNT(i.impression_id) AS imps "
           "FROM campaigns ca JOIN clicks c ON c.campaign_id = ca.campaign_id "
           "JOIN impressions i ON i.campaign_id = ca.campaign_id GROUP BY ca.name")
    f = detect_fanout(sql, COLS)
    assert f is not None
    assert set(f.satellites) == {"clicks", "impressions"}
    assert f.hub_root == "campaign"


def test_cte_preaggregated_is_not_flagged():
    sql = ("WITH c AS (SELECT campaign_id, COUNT(*) n FROM clicks GROUP BY 1), "
           "i AS (SELECT campaign_id, COUNT(*) n FROM impressions GROUP BY 1) "
           "SELECT ca.name, c.n, i.n FROM campaigns ca JOIN c ON c.campaign_id=ca.campaign_id "
           "JOIN i ON i.campaign_id=ca.campaign_id")
    assert detect_fanout(sql, COLS) is None


def test_count_distinct_is_not_flagged():
    sql = ("SELECT ca.name, COUNT(DISTINCT c.click_id), COUNT(DISTINCT i.impression_id) "
           "FROM campaigns ca JOIN clicks c ON c.campaign_id=ca.campaign_id "
           "JOIN impressions i ON i.campaign_id=ca.campaign_id GROUP BY ca.name")
    assert detect_fanout(sql, COLS) is None


def test_single_table_is_not_flagged():
    assert detect_fanout("SELECT SUM(order_total) FROM orders", COLS) is None


# ── New: single parent-measure fan-out (one-to-many) ─────────────────────────────

def test_parent_measure_summed_across_child_join_is_flagged():
    # SUM(orders.order_total) is duplicated by the join to the finer-grained order_items.
    sql = ("SELECT SUM(o.order_total) FROM orders o "
           "JOIN order_items oi ON oi.order_id = o.order_id")
    f = detect_fanout(sql, COLS)
    assert f is not None, "single parent-measure fan-out must be flagged"
    assert f.kind == "parent_fanout"
    assert f.satellites == ["orders"]
    assert "order_items" in f.children
    assert "FAN-OUT" in f.to_prompt_text()


def test_aggregating_the_child_is_correct_and_not_flagged():
    # SUM(order_items.unit_price) grouped by the parent is the CORRECT pattern.
    sql = ("SELECT o.order_id, SUM(oi.unit_price) FROM orders o "
           "JOIN order_items oi ON oi.order_id = o.order_id GROUP BY o.order_id")
    assert detect_fanout(sql, COLS) is None


def test_unrelated_tables_not_flagged():
    sql = ("SELECT SUM(o.order_total) FROM orders o "
           "JOIN products p ON p.product_id = o.order_id")  # no shared root
    # orders↔products share no FK root → no fan-out claim
    assert detect_fanout(sql, COLS) is None


# ── Measure × key arithmetic — measure multiplied by / aggregated over a nominal id ──
# The real-path scar: SUM(unit_price * order_item_id) for "revenue" multiplies price by
# the row's PRIMARY KEY (a fake €150M when order_items has no quantity column). The
# fan-out detectors watch row-multiplication across joins; this catches measure×key
# WITHIN one table. High-precision: an id is never a legitimate multiplicand/SUM arg.

from aughor.sql.fanout import measure_times_key_arithmetic as _idmath


def test_idmath_price_times_primary_key_is_flagged():
    # The exact eval bug (Q5, top products by revenue).
    sql = ("SELECT product_id, SUM(unit_price * order_item_id) AS revenue "
           "FROM order_items GROUP BY product_id")
    r = _idmath(sql)
    assert r is not None, "price × primary-key must be flagged"
    assert "order_item_id" in r


def test_idmath_sum_over_a_key_is_flagged():
    assert _idmath("SELECT SUM(order_id) FROM orders") is not None
    assert _idmath("SELECT AVG(customer_id) FROM customers") is not None


def test_idmath_chained_and_cast_key_is_flagged():
    assert _idmath("SELECT SUM(unit_price * quantity * order_item_id) FROM order_items") is not None
    assert _idmath("SELECT SUM(unit_price * CAST(order_item_id AS DOUBLE)) FROM order_items") is not None


def test_idmath_correct_revenue_is_not_flagged():
    # quantity × price is the CORRECT additive revenue — must stay silent.
    assert _idmath("SELECT SUM(quantity * unit_price) AS revenue FROM order_items") is None
    assert _idmath("SELECT SUM(unit_price) FROM order_items") is None


def test_idmath_count_of_keys_is_not_flagged():
    # Counting keys is valid (only SUM/AVG are magnitude-fabricators).
    assert _idmath("SELECT COUNT(order_id) FROM orders") is None
    assert _idmath("SELECT COUNT(DISTINCT customer_id) FROM orders") is None


def test_idmath_does_not_fire_on_non_key_measures():
    # TPC-H idiom and ordinary measures: no key column → no flag.
    assert _idmath("SELECT SUM(l_extendedprice * (1 - l_discount)) FROM lineitem") is None
    assert _idmath("SELECT SUM(amount * exchange_rate) FROM payments") is None
    assert _idmath("SELECT SUM(bid * 2) FROM auctions") is None          # 'bid' is not a key
    assert _idmath("SELECT SUM(paid) FROM invoices") is None             # 'paid' ends in 'id' but not a key
    assert _idmath("SELECT MIN(order_id) FROM orders") is None           # MIN/MAX not checked


def test_idmath_windowed_and_distinct_excluded():
    assert _idmath("SELECT SUM(order_id) OVER (PARTITION BY x) FROM orders") is None
    assert _idmath("SELECT SUM(DISTINCT order_id) FROM orders") is None


# ── Avg-of-row-ratios — wrong recipe for a group-level rate (eval 2026-06-21, Q23) ──
# AVG(freight/price) averages per-row ratios (over-weights small denominators); the
# correct group rate is the RATIO OF SUMS SUM(freight)/SUM(price). The eval scar: Deep
# derived freight-% as 1.48% via avg-of-ratios while Insight's ratio-of-sums gave 2.17%.

from aughor.sql.fanout import avg_of_row_ratios as _avgratio


def test_avgratio_flags_avg_of_division_by_column():
    assert _avgratio("SELECT customer_country, AVG(freight_value / price) AS r FROM orders GROUP BY 1") is not None
    assert _avgratio("SELECT AVG(freight_value / NULLIF(price, 0)) FROM orders") is not None
    assert _avgratio("SELECT AVG(CAST(a AS DOUBLE) / b) FROM t") is not None


def test_avgratio_silent_on_ratio_of_sums():
    # the CORRECT recipe — the Div is over SUMs, not inside an AVG
    assert _avgratio("SELECT SUM(freight_value) / NULLIF(SUM(order_value), 0) FROM orders") is None
    assert _avgratio("SELECT AVG(a) / AVG(b) FROM t") is None


def test_avgratio_silent_on_constant_scale_and_plain_avg():
    assert _avgratio("SELECT AVG(score / 100.0) FROM t") is None   # dividing by a constant is scaling
    assert _avgratio("SELECT AVG(price) FROM t") is None


def test_avgratio_excludes_distinct_and_windowed():
    assert _avgratio("SELECT AVG(DISTINCT a / b) FROM t") is None
    assert _avgratio("SELECT AVG(a / b) OVER (PARTITION BY z) FROM t") is None
