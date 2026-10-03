"""Fan-out detection — the #1 model-invariant correctness failure (join amplification).

Locks the existing multi-satellite chasm-trap detection AND the new single parent-measure
fan-out case. High-precision contract: NEVER flag a correct query.
See aughor/sql/fanout.py.
"""
import pytest

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


def test_a_parent_joined_on_its_own_key_is_no_satellite_and_its_condition_sums_nothing():
    """Q3 (2026-10-03): the true answer's query was called an over-count of 'user' — orders and order_items both
    carry user_id — though it joins items to their order on order_id, the order's own key, and sums the items:
    the order's status only chose which. A parent measure summed across its items still over-counts."""
    cols = {"orders": ["order_id", "user_id", "status", "num_of_item", "created_at"],
            "order_items": ["id", "order_id", "user_id", "product_id", "status", "sale_price"]}
    join = " FROM orders o JOIN order_items oi ON o.order_id = oi.order_id GROUP BY 1"
    assert detect_fanout("SELECT DATE(o.created_at), SUM(CASE WHEN o.status = 'Complete' THEN oi.sale_price "
                         "ELSE 0 END)" + join, cols) is None
    assert detect_fanout("SELECT DATE(o.created_at), SUM(IF(o.status = 'Complete', oi.sale_price, 0))" + join,
                         cols, dialect="bigquery") is None
    f = detect_fanout("SELECT DATE(o.created_at), SUM(o.num_of_item)" + join, cols)
    assert f is not None and f.kind == "parent_fanout" and f.satellites == ["orders"]
    # beside an item measure it is still the parent's sum that over-counts — not a chasm of 'user'
    f = detect_fanout("SELECT DATE(o.created_at), SUM(o.num_of_item), SUM(oi.sale_price)" + join, cols)
    assert f is not None and f.kind == "parent_fanout" and f.satellites == ["orders"]


def test_unrelated_tables_not_flagged():
    sql = ("SELECT SUM(o.order_total) FROM orders o "
           "JOIN products p ON p.product_id = o.order_id")  # no shared root
    # orders↔products share no FK root → no fan-out claim
    assert detect_fanout(sql, COLS) is None


# ── A CTE or subquery that keeps its table's rows is that table (2026-10-01) ──────────
# The fulfilment answer averaged each order's lead time over a CTE of orders joined to a CTE
# of order items — once per item — and passed clean, after the same join written over the
# two tables had been flagged twice.

_ITEMS = "SELECT oi.order_id, p.name AS centre FROM order_items AS oi JOIN products AS p ON oi.product_id = p.product_id"


def _through(items_cte: str) -> str:
    return ("WITH order_metrics AS (SELECT order_id, order_total AS lead FROM orders WHERE status = 'done'), "
            f"item_centre AS ({items_cte}) "
            "SELECT ic.centre, AVG(om.lead) AS avg_lead FROM order_metrics AS om "
            "JOIN item_centre AS ic ON om.order_id = ic.order_id GROUP BY 1")


def test_an_average_over_ctes_that_keep_their_rows_is_flagged_and_never_rewritten():
    from aughor.sql.fanout import defan
    f = detect_fanout(_through(_ITEMS), COLS)
    assert f is not None
    assert (f.kind, f.satellites, f.children, f.through_cte) == ("parent_fanout", ["orders"], ["order_items"], True)
    assert defan(_through(_ITEMS), f) is None              # said, not rewritten
    flat = ("SELECT p.name, AVG(o.order_total) FROM orders AS o JOIN order_items AS oi ON o.order_id = oi.order_id "
            "JOIN products AS p ON oi.product_id = p.product_id GROUP BY 1")
    assert detect_fanout(flat, COLS).through_cte is False   # the same join over the tables, as before
    plain = "SELECT SUM(o.order_total) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id"
    g = detect_fanout(plain, COLS)
    assert defan(plain, g)                                  # a flat join is still rewritten …
    g.through_cte = True
    assert defan(plain, g) is None                          # … and a finding read through a CTE never is


@pytest.mark.parametrize("items", [
    _ITEMS.replace("SELECT", "SELECT DISTINCT", 1),        # one row per order and centre
    _ITEMS + " GROUP BY 1, 2",
    _ITEMS.replace(" FROM", ", ROW_NUMBER() OVER (PARTITION BY oi.order_id) AS rn FROM", 1),
])
def test_a_cte_that_de_duplicates_is_still_the_fix(items):
    assert detect_fanout(_through(items), COLS) is None


def test_a_subquery_that_keeps_its_rows_is_read_the_same_way():
    sql = ("SELECT d.centre, AVG(o.order_total) FROM orders AS o "
           f"JOIN ({_ITEMS}) AS d ON d.order_id = o.order_id GROUP BY 1")
    f = detect_fanout(sql, COLS)
    assert f is not None and f.through_cte is True


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


# ── a join onto a PRIMARY KEY is not a chasm ──────────────────────────────────

_THELOOK = {
    "order_items": ["id", "order_id", "user_id", "product_id", "inventory_item_id",
                    "status", "created_at", "sale_price", "returned_at"],
    "inventory_items": ["id", "product_id", "created_at", "sold_at", "cost",
                        "product_category", "product_department", "product_brand"],
}

_PK_JOIN = (
    "SELECT inventory_items.product_department, "
    "SUM(order_items.sale_price - inventory_items.cost) AS metric_total, COUNT(*) AS n "
    "FROM order_items LEFT JOIN inventory_items "
    "ON order_items.inventory_item_id = inventory_items.id "
    "GROUP BY 1"
)


def test_a_direct_fk_to_a_primary_key_is_not_a_chasm():
    """The false positive that reached a shipped executive summary.

    `order_items` and `inventory_items` BOTH carry `product_id`, so by schema shape alone they
    look like two satellites of a `product` hub. They are not joined through `product`: the join
    is a direct FK onto `inventory_items.id`, which attaches exactly one row. Measured on the real
    warehouse — 181,721 rows in, 181,721 out, zero multiplication — while the report told the
    reader its exact totals were "inflated ... directional only" and needed "a grain-correct
    recompute". A guard that says correct numbers are wrong spends the reader's trust for nothing.
    """
    from aughor.sql.fanout import sum_over_chasm_fanout, count_star_chasm_fanout

    assert sum_over_chasm_fanout(_PK_JOIN, _THELOOK, "bigquery") is None
    assert count_star_chasm_fanout(_PK_JOIN, _THELOOK, "bigquery") is None


def test_the_genuine_two_fact_chasm_still_fires():
    """The demotion must be narrow. A real chasm joins its satellites on the HUB key
    (`order_id`), never on their own `id` — the ROAS scar this module was built for."""
    from aughor.sql.fanout import sum_over_chasm_fanout

    cols = {"orders": ["order_id", "user_id"],
            "order_items": ["id", "order_id", "sale_price"],
            "attribution": ["id", "order_id", "weight"]}
    sql = ("SELECT o.order_id, SUM(oi.sale_price * a.weight) AS m FROM orders o "
           "JOIN order_items oi ON o.order_id = oi.order_id "
           "JOIN attribution a ON o.order_id = a.order_id GROUP BY 1")
    hit = sum_over_chasm_fanout(sql, cols, "duckdb")
    assert hit and "chasm" in hit
