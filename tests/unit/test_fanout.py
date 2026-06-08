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
