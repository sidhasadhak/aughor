"""Deterministic identifier repair — the camelCase Phase-8 fix.

Pins: snake_case→camelCase remap (the dominant Bakehouse Binder class), exact columns
untouched, invented columns left alone, table-scoped, ambiguity-safe, fail-safe.
"""
from aughor.sql.identifiers import repair_identifiers, unresolved_identifiers

CUSTOMERS = {"bakehouse.sales_customers": ["customerID", "first_name", "city"]}
TWO = {
    "bakehouse.sales_customers":    ["customerID", "first_name"],
    "bakehouse.sales_transactions": ["transactionID", "customerID", "total_amount"],
}


def _norm(s):  # whitespace-insensitive compare for the rewritten SQL
    return " ".join(s.split()).lower()


class TestRepair:
    def test_snake_to_camel_remap(self):
        out = repair_identifiers(
            "SELECT sc.customer_id FROM bakehouse.sales_customers sc", CUSTOMERS)
        assert "customerID" in out and "customer_id" not in out

    def test_join_both_sides_repaired(self):
        out = repair_identifiers(
            "SELECT * FROM bakehouse.sales_customers sc "
            "JOIN bakehouse.sales_transactions st ON sc.customer_id = st.customer_id", TWO)
        assert "customer_id" not in out and out.count("customerID") == 2

    def test_exact_column_untouched(self):
        sql = "SELECT customerID, first_name FROM bakehouse.sales_customers"
        assert _norm(repair_identifiers(sql, CUSTOMERS)) == _norm(sql)

    def test_invented_column_left_alone(self):
        # 'segment' has no schema match → it's a hallucination, not a casing slip
        sql = "SELECT segment FROM bakehouse.sales_customers"
        assert "segment" in repair_identifiers(sql, CUSTOMERS)

    def test_only_repairs_columns_of_query_tables(self):
        # a column matching a DIFFERENT table's column is not touched
        other = {"other_table": ["customerID"]}
        sql = "SELECT customer_id FROM bakehouse.sales_customers"
        assert repair_identifiers(sql, other) == sql   # sales_customers not in table_cols

    def test_ambiguous_norm_is_skipped(self):
        # two real columns normalise to the same key → never guess
        ambig = {"t": ["customerID", "customer_id"]}
        sql = "SELECT customerid FROM t"
        # 'customerid' is ambiguous (maps to both) → left unchanged
        assert repair_identifiers(sql, ambig) == sql

    def test_parse_failure_is_fail_safe(self):
        junk = "this is not <<< valid sql"
        assert repair_identifiers(junk, CUSTOMERS) == junk

    def test_empty_inputs(self):
        assert repair_identifiers("", CUSTOMERS) == ""
        assert repair_identifiers("SELECT 1", {}) == "SELECT 1"


# ── Static schema-grounding gate (the pre-execution residual catcher) ──────────────────
WORKSPACE = {
    "bakehouse.sales_customers":    ["customerID", "first_name", "city", "franchiseID"],
    "bakehouse.sales_transactions": ["transactionID", "customerID", "totalPrice", "quantity"],
    "ecommerce.reviews":            ["review_id", "rating", "body"],
}


class TestUnresolved:
    def test_invented_bare_column_is_flagged(self):
        # the real residual: `segment` exists in NO bakehouse table — a free elaboration
        sql = ("SELECT sc.segment, SUM(st.totalPrice) FROM bakehouse.sales_customers sc "
               "JOIN bakehouse.sales_transactions st ON sc.customerID = st.customerID "
               "GROUP BY sc.segment")
        cols, tbls = unresolved_identifiers(sql, WORKSPACE)
        assert cols == {"segment"} and tbls == set()

    def test_real_columns_not_flagged(self):
        sql = ("SELECT sc.customerID, SUM(st.totalPrice) AS rev FROM bakehouse.sales_customers sc "
               "JOIN bakehouse.sales_transactions st ON sc.customerID = st.customerID "
               "GROUP BY sc.customerID ORDER BY rev DESC")
        assert unresolved_identifiers(sql, WORKSPACE) == (set(), set())

    def test_casing_slip_is_not_flagged(self):
        # snake_case `customer_id` norm-matches `customerID` → repair's job, not an invention
        sql = "SELECT customer_id FROM bakehouse.sales_customers"
        assert unresolved_identifiers(sql, WORKSPACE) == (set(), set())

    def test_select_alias_in_order_by_not_flagged(self):
        sql = "SELECT SUM(totalPrice) AS total_revenue FROM bakehouse.sales_transactions ORDER BY total_revenue"
        assert unresolved_identifiers(sql, WORKSPACE) == (set(), set())

    def test_cte_passthrough_and_derived_not_flagged(self):
        sql = ("WITH cs AS (SELECT customerID, SUM(totalPrice) AS spent FROM bakehouse.sales_transactions "
               "GROUP BY customerID) SELECT customerID, spent FROM cs ORDER BY spent DESC")
        assert unresolved_identifiers(sql, WORKSPACE) == (set(), set())

    def test_missing_table_is_flagged(self):
        # `reviews` is bare but the residual case is an invented table that resolves nowhere
        sql = "SELECT * FROM product_items WHERE qty > 0"
        cols, tbls = unresolved_identifiers(sql, WORKSPACE)
        assert tbls == {"product_items"}

    def test_bare_known_table_resolves(self):
        # `reviews` exists as ecommerce.reviews → known by bare name, columns checked against it
        sql = "SELECT review_id, rating FROM reviews"
        assert unresolved_identifiers(sql, WORKSPACE) == (set(), set())

    def test_unknown_table_suppresses_column_check(self):
        # an unknown table means columns may come from outside the schema → report only the table
        sql = "SELECT foo, bar FROM mystery_table"
        cols, tbls = unresolved_identifiers(sql, WORKSPACE)
        assert tbls == {"mystery_table"} and cols == set()

    def test_generic_id_invention_flagged(self):
        # `sc.id` — the LLM assumed a generic PK; sales_customers has customerID, not id
        sql = "SELECT sc.id FROM bakehouse.sales_customers sc"
        cols, _ = unresolved_identifiers(sql, WORKSPACE)
        assert cols == {"id"}

    def test_parse_failure_and_empty_are_fail_safe(self):
        assert unresolved_identifiers("this <<< not sql", WORKSPACE) == (set(), set())
        assert unresolved_identifiers("", WORKSPACE) == (set(), set())
        assert unresolved_identifiers("SELECT 1", {}) == (set(), set())
