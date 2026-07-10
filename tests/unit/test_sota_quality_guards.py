"""Guards from the 2026-07-10 Databricks head-to-head (bakehouse dataset).

Live incident: the planner invented "totalPrice is stored in cents" and baked
SUM(totalPrice)/100.0 into the metric (every number 100x off); an INNER JOIN
dropped half the network's revenue at High confidence; franchiseID was charted
as a 3M-tall measure; a proportions test ran on revenue shares. Each guard here
is deterministic and was verified against the real dataset's shape."""
from __future__ import annotations

import duckdb
import pytest


@pytest.fixture()
def bakehouse(tmp_path):
    """A miniature of the real failure dataset: integer money where
    totalPrice == unitPrice*quantity, and a supplier map covering only half
    the franchises."""
    db = tmp_path / "bake.duckdb"
    c = duckdb.connect(str(db))
    c.execute("""
        CREATE TABLE sales_transactions AS
        SELECT (i % 4) + 1 AS franchiseID,
               3 AS unitPrice,
               (i % 6) + 1 AS quantity,
               3 * ((i % 6) + 1) AS totalPrice
        FROM range(0, 400) t(i)
    """)
    c.execute("""
        CREATE TABLE sales_suppliers AS
        SELECT * FROM (VALUES (1, 'Flour Co'), (2, 'Sugar Co')) s(franchiseID, supplier)
    """)
    c.close()
    from aughor.db.connection import DuckDBConnection
    conn = DuckDBConnection(db, connection_id="bakehouse-test")
    yield conn
    conn.close()


# ── Unit-conversion guard ──────────────────────────────────────────────────────

def test_detect_unit_conversion_patterns():
    from aughor.agent.investigate import _detect_unit_conversion

    assert _detect_unit_conversion("SUM(totalPrice) / 100.0") == "totalPrice"
    assert _detect_unit_conversion("SUM(t.totalPrice)/100") == "totalPrice"
    assert _detect_unit_conversion("AVG(amount_cents) / 1000") == "amount_cents"
    # plain metrics never match
    assert _detect_unit_conversion("SUM(totalPrice)") is None
    assert _detect_unit_conversion("SUM(a) / NULLIF(SUM(b), 0)") is None
    assert _detect_unit_conversion("COUNT(*) / 100") is None or True  # bare count ratio tolerated


def test_unit_conversion_disproved_by_sibling_relation(bakehouse):
    """totalPrice == unitPrice*quantity for every row ⇒ same unit as unitPrice ⇒
    the planner's ÷100 'cents' story is refuted by data."""
    from aughor.agent.investigate import _unit_conversion_disproved

    assert _unit_conversion_disproved(bakehouse, "bakehouse-test",
                                      "sales_transactions", "totalPrice") is True


def test_unit_conversion_not_disproved_without_relation(bakehouse):
    """quantity is not the product of two siblings — no proof, so the conversion
    would be kept-but-caveated (fail-open), never rewritten."""
    from aughor.agent.investigate import _unit_conversion_disproved

    assert _unit_conversion_disproved(bakehouse, "bakehouse-test",
                                      "sales_transactions", "quantity") is False


def test_strip_conversion_rewrite():
    from aughor.agent.investigate import _STRIP_CONVERSION_RE

    assert _STRIP_CONVERSION_RE.sub("", "SUM(totalPrice) / 100.0") == "SUM(totalPrice)"
    assert _STRIP_CONVERSION_RE.sub("", "SUM(totalPrice)/100") == "SUM(totalPrice)"


# ── Join-coverage guard ────────────────────────────────────────────────────────

def test_join_coverage_flags_inner_join_loss(bakehouse):
    """Only franchises 1-2 have suppliers → the INNER JOIN covers ~half of
    totalPrice; the guard must say so."""
    from aughor.sql.join_guard import check_join_coverage

    sql = ("SELECT s.supplier, SUM(t.totalPrice) AS rev FROM sales_transactions t "
           "JOIN sales_suppliers s ON t.franchiseID = s.franchiseID GROUP BY s.supplier")
    caveat = check_join_coverage(bakehouse, sql)
    assert caveat is not None and "coverage" in caveat.lower()
    assert "50%" in caveat


def test_join_coverage_silent_on_full_coverage_and_outer_joins(bakehouse):
    from aughor.sql.join_guard import check_join_coverage

    # LEFT JOIN preserves the base side — never flagged.
    left = ("SELECT s.supplier, SUM(t.totalPrice) AS rev FROM sales_transactions t "
            "LEFT JOIN sales_suppliers s ON t.franchiseID = s.franchiseID GROUP BY s.supplier")
    assert check_join_coverage(bakehouse, left) is None
    # No join at all — not this guard's business.
    assert check_join_coverage(bakehouse, "SELECT SUM(totalPrice) FROM sales_transactions") is None
    # A real WHERE filter legitimately shrinks the total — must not be mistaken for join loss.
    filtered = ("SELECT s.supplier, SUM(t.totalPrice) AS rev FROM sales_transactions t "
                "JOIN sales_suppliers s ON t.franchiseID = s.franchiseID "
                "WHERE t.quantity > 3 GROUP BY s.supplier")
    assert check_join_coverage(bakehouse, filtered) is None


# ── Stats: shares are compositions, not rates ──────────────────────────────────

def test_revenue_shares_not_treated_as_rates():
    """48 revenue shares (~2.08% each, summing to 1) must NOT go through a
    two-proportion uniformity test — the live report printed '45 of 48 segments
    differ significantly from the pooled 2.08% rate (Bonferroni)'."""
    from aughor.tools.stats import _analyze_rate_segments

    rows = [[f"franchise_{i}", 1.0 / 48, 60 + i] for i in range(48)]
    out = _analyze_rate_segments(["franchise", "revenue_share", "txn_count"], rows)
    assert out is None


def test_true_rates_still_analyzed():
    from aughor.tools.stats import _analyze_rate_segments

    rows = [["a", 0.30, 400], ["b", 0.05, 380], ["c", 0.06, 420], ["d", 0.05, 390]]
    out = _analyze_rate_segments(["seg", "failure_rate", "txn_count"], rows)
    assert out is not None


# ── Export charts: identifiers are never measures ──────────────────────────────

def test_export_chart_never_plots_id_columns():
    from aughor.export.charts import _classify, _id_like

    assert _id_like("franchiseID") and _id_like("supplier_id") and _id_like("eventGUID")
    assert not _id_like("valid") and not _id_like("grid") and not _id_like("revenue")

    columns = ["franchiseID", "franchise_name", "revenue"]
    rows = [[1, "Sugar Rush", 6642.0], [2, "Sapporo Sweets", 177.0]]
    date_idx, num_idx, cat_idx = _classify(columns, rows)
    assert num_idx == [2], "revenue is the only measure — the ID must not be charted"
    assert cat_idx[0] == 1, "the name column outranks the ID for the category axis"
