"""BeautyCommerce demo-seed dataset integrity.

Seeds the dataset into an in-memory DuckDB (no side effects on the real data dir) and pins
the properties a demo must hold: row counts, foreign-key consistency (every order_item points
at a real order + product; every order at a real customer), and the two baked-in patterns the
Canvas insights claim (top loyalty tiers carry a higher AOV; Fragrance/Skincare lead category
revenue). A demo whose insights don't match its data is worse than no demo.
"""
import pytest


def _seeded():
    duckdb = pytest.importorskip("duckdb")
    from aughor.samples.beautycommerce import _seed_beauty_db
    c = duckdb.connect(":memory:")
    _seed_beauty_db(c)
    return c


class TestDataset:
    def test_row_counts(self):
        c = _seeded()
        n = lambda t: c.execute(f"SELECT COUNT(*) FROM beauty.{t}").fetchone()[0]
        assert n("products") == 120 and n("customers") == 600 and n("campaigns") == 12
        assert n("orders") == 6000 and n("order_items") == 15000 and n("reviews") == 3500

    def test_foreign_keys_have_no_orphans(self):
        c = _seeded()
        z = lambda q: c.execute(q).fetchone()[0]
        assert z("SELECT COUNT(*) FROM beauty.order_items oi LEFT JOIN beauty.orders o USING(order_id) WHERE o.order_id IS NULL") == 0
        assert z("SELECT COUNT(*) FROM beauty.order_items oi LEFT JOIN beauty.products p USING(product_id) WHERE p.product_id IS NULL") == 0
        assert z("SELECT COUNT(*) FROM beauty.orders o LEFT JOIN beauty.customers c USING(customer_id) WHERE c.customer_id IS NULL") == 0
        assert z("SELECT COUNT(*) FROM beauty.reviews r LEFT JOIN beauty.products p USING(product_id) WHERE p.product_id IS NULL") == 0

    def test_line_total_matches_product_price(self):
        # order_items price is derived from the product → internally consistent
        c = _seeded()
        bad = c.execute(
            "SELECT COUNT(*) FROM beauty.order_items oi JOIN beauty.products p USING(product_id) "
            "WHERE ROUND(p.price * oi.quantity, 2) <> oi.line_total"
        ).fetchone()[0]
        assert bad == 0

    def test_loyalty_tier_aov_pattern(self):
        c = _seeded()
        aov = dict(c.execute(
            "SELECT c.loyalty_tier, AVG(o.total_amount) FROM beauty.orders o "
            "JOIN beauty.customers c USING(customer_id) GROUP BY 1"
        ).fetchall())
        assert aov["Platinum"] > aov["Bronze"] and aov["Gold"] > aov["Silver"]

    def test_category_revenue_pattern(self):
        c = _seeded()
        cats = [r[0] for r in c.execute(
            "SELECT p.category FROM beauty.order_items oi JOIN beauty.products p USING(product_id) "
            "GROUP BY 1 ORDER BY SUM(oi.line_total) DESC"
        ).fetchall()]
        assert cats[0] in ("Fragrance", "Skincare") and cats[1] in ("Fragrance", "Skincare")
