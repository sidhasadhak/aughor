"""Deterministic identifier repair — the camelCase Phase-8 fix.

Pins: snake_case→camelCase remap (the dominant Bakehouse Binder class), exact columns
untouched, invented columns left alone, table-scoped, ambiguity-safe, fail-safe.
"""
from aughor.sql.identifiers import repair_identifiers

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
