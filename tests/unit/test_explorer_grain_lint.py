"""Two grain bugs the explorer narrated as confident wrong numbers (verified live via
evals/test_explorer_recurrence.py): integer division of aggregates (avg_items_per_order=1.0
→ "all orders 3 items") and a single-join COUNT(*) aliased as a parent entity ("2000
products" = 25 products × 80 order_items). detect_fanout deliberately skips both (it
ignores COUNT(*) and needs ≥2 satellites). These pin the two new high-precision linters —
they must FIRE on the bug and stay SILENT on legitimate SQL (the false-positive guard is
the whole point: a clumsy version would suppress valid insights)."""
from aughor.sql.fanout import (
    integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
    avg_over_chasm_fanout, sum_over_chasm_fanout, cte_grain_mismatch_fanout,
)

# products is the PARENT (order_items.product_id references it); orders is a many-side child.
TC = {
    "ecommerce.products": ["product_id", "category", "unit_price"],
    "ecommerce.order_items": ["item_id", "order_id", "product_id", "quantity"],
    "ecommerce.orders": ["order_id", "customer_id", "total_amount"],
    "ecommerce.customers": ["customer_id", "region"],
}


class TestIntegerDivision:
    def test_count_over_count_flagged(self):
        assert integer_division_risk("SELECT COUNT(a)/COUNT(b) FROM t")

    def test_the_original_bug(self):
        assert integer_division_risk(
            "SELECT COUNT(oi.item_id) / COUNT(*) AS avg_items FROM orders o JOIN order_items oi")

    def test_sum_over_count_flagged(self):
        assert integer_division_risk("SELECT SUM(qty)/COUNT(*) FROM t")

    def test_float_multiply_is_safe(self):
        assert integer_division_risk("SELECT COUNT(a)*1.0/COUNT(b) FROM t") is None

    def test_cast_is_safe(self):
        assert integer_division_risk("SELECT CAST(COUNT(a) AS DOUBLE)/COUNT(b) FROM t") is None

    def test_avg_is_safe(self):
        assert integer_division_risk("SELECT AVG(total_amount) FROM orders") is None

    def test_divide_by_float_literal_is_safe(self):
        assert integer_division_risk("SELECT SUM(a)/100.0 FROM t") is None

    def test_no_division_is_safe(self):
        assert integer_division_risk("SELECT COUNT(*) FROM t") is None


class TestCountStarFanout:
    def test_parent_count_star_flagged(self):
        # the "2000 products" bug
        sql = ("SELECT p.category, COUNT(*) AS product_count "
               "FROM ecommerce.products p JOIN ecommerce.order_items oi "
               "ON p.product_id = oi.product_id GROUP BY p.category")
        assert count_star_entity_fanout(sql, TC)

    def test_many_side_count_star_not_flagged(self):
        # orders is the many-side of orders⋈customers — COUNT(*) AS order_count is CORRECT
        sql = ("SELECT COUNT(*) AS order_count FROM ecommerce.orders o "
               "JOIN ecommerce.customers c ON o.customer_id = c.customer_id")
        assert count_star_entity_fanout(sql, TC) is None

    def test_count_distinct_not_flagged(self):
        sql = ("SELECT COUNT(DISTINCT p.product_id) AS product_count "
               "FROM ecommerce.products p JOIN ecommerce.order_items oi "
               "ON p.product_id = oi.product_id")
        assert count_star_entity_fanout(sql, TC) is None

    def test_row_count_alias_not_flagged(self):
        sql = "SELECT COUNT(*) AS row_count FROM ecommerce.products p JOIN ecommerce.order_items oi"
        assert count_star_entity_fanout(sql, TC) is None

    def test_no_join_not_flagged(self):
        assert count_star_entity_fanout("SELECT COUNT(*) AS product_count FROM ecommerce.products", TC) is None


# COUNT(*) over a CHASM — ≥2 satellites of one hub joined directly — the FAN-b gap
# detect_fanout deliberately skips (it can't attribute COUNT(*) to a satellite and
# defan() can't rewrite a cross-product count). High-precision DROP signal.
CHASM_TC = {
    "ads.campaigns":   ["campaign_id", "name", "budget"],
    "ads.clicks":      ["click_id", "campaign_id", "ts"],
    "ads.impressions": ["impression_id", "campaign_id", "ts"],
    "ads.customers":   ["customer_id", "region"],
}
_J = ("JOIN clicks k ON c.campaign_id=k.campaign_id "
      "JOIN impressions i ON c.campaign_id=i.campaign_id")


class TestCountStarChasm:
    def test_chasm_count_star_flagged(self):
        # clicks × impressions per campaign — the textbook chasm
        sql = f"SELECT c.name, COUNT(*) FROM campaigns c {_J} GROUP BY c.name"
        assert count_star_chasm_fanout(sql, CHASM_TC)

    def test_chasm_count_one_flagged(self):
        assert count_star_chasm_fanout(f"SELECT COUNT(1) FROM campaigns c {_J}", CHASM_TC)

    def test_single_join_not_a_chasm(self):
        # hub ⋈ one satellite is NOT a chasm — no cross-product, must stay silent
        sql = "SELECT COUNT(*) FROM campaigns c JOIN clicks k ON c.campaign_id=k.campaign_id"
        assert count_star_chasm_fanout(sql, CHASM_TC) is None

    def test_count_distinct_not_flagged(self):
        assert count_star_chasm_fanout(f"SELECT COUNT(DISTINCT k.click_id) FROM campaigns c {_J}", CHASM_TC) is None

    def test_qualified_count_left_to_detect_fanout(self):
        # COUNT(<col>) is detect_fanout's job; this linter only owns bare COUNT(*)
        assert count_star_chasm_fanout(f"SELECT COUNT(k.click_id) FROM campaigns c {_J}", CHASM_TC) is None

    def test_no_join_not_flagged(self):
        assert count_star_chasm_fanout("SELECT COUNT(*) FROM clicks", CHASM_TC) is None

    def test_unrelated_join_not_flagged(self):
        # two tables that don't share a hub FK root → not a chasm
        sql = "SELECT COUNT(*) FROM campaigns c JOIN customers cu ON c.campaign_id=cu.customer_id"
        assert count_star_chasm_fanout(sql, CHASM_TC) is None

    def test_pre_aggregated_ctes_are_the_fix_not_flagged(self):
        # the CORRECT rewrite — each satellite pre-aggregated in a CTE — must NOT be flagged
        sql = ("WITH k AS (SELECT campaign_id, COUNT(*) n FROM clicks GROUP BY 1), "
               "i AS (SELECT campaign_id, COUNT(*) n FROM impressions GROUP BY 1) "
               "SELECT COUNT(*) FROM campaigns c JOIN k ON c.campaign_id=k.campaign_id "
               "JOIN i ON c.campaign_id=i.campaign_id")
        assert count_star_chasm_fanout(sql, CHASM_TC) is None

    def test_malformed_sql_never_raises(self):
        assert count_star_chasm_fanout("this is not sql", CHASM_TC) is None
        assert count_star_chasm_fanout("", CHASM_TC) is None


class TestAvgOverChasm:
    def test_avg_over_chasm_flagged(self):
        # AVG(clicks.value) over campaigns⋈clicks⋈impressions — biased by the
        # impressions fan-out (each click row repeated per impression)
        sql = f"SELECT c.name, AVG(k.ts) FROM campaigns c {_J} GROUP BY c.name"
        reason = avg_over_chasm_fanout(sql, CHASM_TC)
        assert reason and "biased mean" in reason

    def test_avg_of_hub_column_also_flagged(self):
        # even AVG of a hub column is biased — the hub row is duplicated by the
        # satellite cross-product
        sql = f"SELECT AVG(c.budget) FROM campaigns c {_J}"
        assert avg_over_chasm_fanout(sql, CHASM_TC)

    def test_min_max_not_flagged(self):
        # MIN/MAX survive row duplication unchanged — NOT a bug, must stay silent
        assert avg_over_chasm_fanout(f"SELECT MIN(k.ts) FROM campaigns c {_J}", CHASM_TC) is None
        assert avg_over_chasm_fanout(f"SELECT MAX(k.ts) FROM campaigns c {_J}", CHASM_TC) is None

    def test_avg_distinct_not_flagged(self):
        assert avg_over_chasm_fanout(f"SELECT AVG(DISTINCT k.ts) FROM campaigns c {_J}", CHASM_TC) is None

    def test_windowed_avg_not_flagged(self):
        # AVG(...) OVER (...) doesn't collapse rows — different construct
        sql = f"SELECT AVG(k.ts) OVER (PARTITION BY c.name) FROM campaigns c {_J}"
        assert avg_over_chasm_fanout(sql, CHASM_TC) is None

    def test_single_join_not_a_chasm(self):
        sql = "SELECT AVG(k.ts) FROM campaigns c JOIN clicks k ON c.campaign_id=k.campaign_id"
        assert avg_over_chasm_fanout(sql, CHASM_TC) is None

    def test_no_avg_not_flagged(self):
        sql = f"SELECT SUM(k.ts) FROM campaigns c {_J}"
        assert avg_over_chasm_fanout(sql, CHASM_TC) is None

    def test_pre_aggregated_ctes_not_flagged(self):
        sql = ("WITH k AS (SELECT campaign_id, AVG(ts) a FROM clicks GROUP BY 1), "
               "i AS (SELECT campaign_id, AVG(ts) a FROM impressions GROUP BY 1) "
               "SELECT AVG(k.a) FROM campaigns c JOIN k ON c.campaign_id=k.campaign_id "
               "JOIN i ON c.campaign_id=i.campaign_id")
        assert avg_over_chasm_fanout(sql, CHASM_TC) is None

    def test_malformed_sql_never_raises(self):
        assert avg_over_chasm_fanout("this is not sql", CHASM_TC) is None
        assert avg_over_chasm_fanout("", CHASM_TC) is None


class TestSumOverChasm:
    def test_sum_over_chasm_flagged(self):
        # SUM(clicks.amount) over campaigns⋈clicks⋈impressions — over-counted by the
        # impressions fan-out (each click row repeated per impression). The ROAS
        # $48T fan-out trap is this shape: SUM of one satellite's measure across a
        # join to a SECOND independent satellite of the same hub.
        sql = f"SELECT c.name, SUM(k.ts) FROM campaigns c {_J} GROUP BY c.name"
        reason = sum_over_chasm_fanout(sql, CHASM_TC)
        assert reason and "chasm" in reason.lower()

    def test_sum_of_hub_column_also_flagged(self):
        # even SUM of a hub column over-counts — the hub row is duplicated by the
        # satellite cross-product (the campaigns.spend → 2.3M× over-count)
        sql = f"SELECT SUM(c.budget) FROM campaigns c {_J}"
        assert sum_over_chasm_fanout(sql, CHASM_TC)

    def test_sum_distinct_not_flagged(self):
        assert sum_over_chasm_fanout(f"SELECT SUM(DISTINCT k.ts) FROM campaigns c {_J}", CHASM_TC) is None

    def test_windowed_sum_not_flagged(self):
        # SUM(...) OVER (...) doesn't collapse rows — different construct
        sql = f"SELECT SUM(k.ts) OVER (PARTITION BY c.name) FROM campaigns c {_J}"
        assert sum_over_chasm_fanout(sql, CHASM_TC) is None

    def test_single_join_not_a_chasm(self):
        sql = "SELECT SUM(k.ts) FROM campaigns c JOIN clicks k ON c.campaign_id=k.campaign_id"
        assert sum_over_chasm_fanout(sql, CHASM_TC) is None

    def test_no_sum_not_flagged(self):
        sql = f"SELECT AVG(k.ts) FROM campaigns c {_J}"
        assert sum_over_chasm_fanout(sql, CHASM_TC) is None

    def test_pre_aggregated_ctes_are_the_fix_not_flagged(self):
        # pre-aggregating each satellite to the hub key in its own CTE is the FIX
        sql = ("WITH k AS (SELECT campaign_id, SUM(ts) s FROM clicks GROUP BY 1), "
               "i AS (SELECT campaign_id, SUM(ts) s FROM impressions GROUP BY 1) "
               "SELECT SUM(k.s) FROM campaigns c JOIN k ON c.campaign_id=k.campaign_id "
               "JOIN i ON c.campaign_id=i.campaign_id")
        assert sum_over_chasm_fanout(sql, CHASM_TC) is None

    def test_malformed_sql_never_raises(self):
        assert sum_over_chasm_fanout("this is not sql", CHASM_TC) is None
        assert sum_over_chasm_fanout("", CHASM_TC) is None


class TestCteGrainMismatch:
    # The real scar: per-order COGS fanned across (order, category) → fabricated -149% margin.
    BUG = (
        "WITH order_revenue AS (SELECT oi.order_id, p.category, SUM(oi.line_total) AS revenue "
        "FROM order_items oi JOIN orders o ON oi.order_id=o.order_id "
        "JOIN products p ON oi.product_id=p.product_id GROUP BY oi.order_id, p.category), "
        "order_cogs AS (SELECT oi.order_id, SUM(oi.unit_price*oi.quantity) AS cogs "
        "FROM order_items oi JOIN orders o ON oi.order_id=o.order_id GROUP BY oi.order_id), "
        "combined AS (SELECT r.category, r.order_id, r.revenue, COALESCE(c.cogs,0) AS cogs "
        "FROM order_revenue r LEFT JOIN order_cogs c ON r.order_id=c.order_id) "
        "SELECT category, ROUND(100.0*SUM(revenue-cogs)/NULLIF(SUM(revenue),0),2) AS gm "
        "FROM combined GROUP BY category"
    )

    def test_the_real_bug_is_flagged(self):
        reason = cte_grain_mismatch_fanout(self.BUG)
        assert reason and "grain-mismatch" in reason and "cogs" in reason

    def test_same_grain_join_is_safe(self):
        sql = ("WITH a AS (SELECT order_id, category, SUM(rev) revenue FROM t GROUP BY order_id, category), "
               "b AS (SELECT order_id, category, SUM(cost) cogs FROM t2 GROUP BY order_id, category) "
               "SELECT a.category, SUM(a.revenue-b.cogs) FROM a JOIN b "
               "ON a.order_id=b.order_id AND a.category=b.category GROUP BY a.category")
        assert cte_grain_mismatch_fanout(sql) is None

    def test_share_ratio_denominator_is_safe(self):
        # the coarse total fans across detail but is a per-row DIVISOR — duplication cancels
        sql = ("WITH totals AS (SELECT category, SUM(rev) total FROM t GROUP BY category), "
               "detail AS (SELECT order_id, category, SUM(rev) rev FROM t GROUP BY order_id, category) "
               "SELECT d.order_id, SUM(d.rev / NULLIF(t.total,0)) AS share FROM detail d "
               "JOIN totals t ON d.category=t.category GROUP BY d.order_id")
        assert cte_grain_mismatch_fanout(sql) is None

    def test_sum_of_coarse_measure_directly_is_flagged(self):
        sql = ("WITH totals AS (SELECT category, SUM(rev) total FROM t GROUP BY category), "
               "detail AS (SELECT order_id, category, SUM(rev) rev FROM t GROUP BY order_id, category) "
               "SELECT d.order_id, SUM(t.total) FROM detail d JOIN totals t "
               "ON d.category=t.category GROUP BY d.order_id")
        assert cte_grain_mismatch_fanout(sql)

    def test_no_cte_is_safe(self):
        assert cte_grain_mismatch_fanout("SELECT category, SUM(x) FROM t GROUP BY category") is None

    def test_malformed_never_raises(self):
        assert cte_grain_mismatch_fanout("not sql at all") is None
        assert cte_grain_mismatch_fanout("") is None
