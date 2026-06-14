"""Deterministic semantic column repair — the invention-starvation fix.

Pins the REAL Phase-8 starvation cases (a domain inventing location_country / region /
total_amount while the schema has country / state / totalPrice) AND the safety guards:
unique-target-only, grain-aware money, no-concept left alone, ambiguous left alone, aliases
untouched, fail-safe.
"""
from aughor.sql.semantic_repair import repair_semantic_columns, _concept

WORKSPACE = {
    "bakehouse.sales_customers":    ["customerID", "first_name", "city", "state", "country", "continent", "gender"],
    "bakehouse.sales_transactions": ["transactionID", "customerID", "quantity", "unitPrice", "totalPrice"],
    "bakehouse.sales_suppliers":    ["supplierID", "name", "ingredient", "continent", "city", "district"],
}


def _norm(s):
    return " ".join(s.split()).lower()


class TestConcept:
    def test_geo_levels(self):
        assert _concept("location_country") == _concept("country") == "geo_country"
        assert _concept("region") == _concept("state") == _concept("province") == "geo_region"
        assert _concept("continent") == "geo_continent"

    def test_money_is_grain_aware(self):
        assert _concept("total_amount") == _concept("totalPrice") == "money_total"
        assert _concept("unitPrice") == "money_unit"
        assert _concept("line_total") == "money_line"
        assert _concept("price") is None        # bare price — too ambiguous to map

    def test_no_concept(self):
        assert _concept("segment") is None and _concept("customer_type") is None
        assert _concept("quantity") is None and _concept("customerID") is None

    def test_mixed_geo_is_ambiguous(self):
        assert _concept("country_region") is None   # two geo levels → no single concept


class TestRepair:
    def test_geo_prefix_invention_repaired(self):
        out = repair_semantic_columns(
            "SELECT location_country, COUNT(*) FROM bakehouse.sales_customers GROUP BY location_country", WORKSPACE)
        assert "country" in out and "location_country" not in out

    def test_region_maps_to_state(self):
        out = repair_semantic_columns("SELECT region FROM bakehouse.sales_customers", WORKSPACE)
        assert "state" in out and "region" not in out

    def test_total_amount_maps_to_totalprice_not_unitprice(self):
        out = repair_semantic_columns(
            "SELECT SUM(total_amount) AS rev FROM bakehouse.sales_transactions", WORKSPACE)
        assert "totalPrice" in out and "total_amount" not in out and "unitPrice" not in out

    def test_real_column_untouched(self):
        sql = "SELECT country, state FROM bakehouse.sales_customers"
        assert _norm(repair_semantic_columns(sql, WORKSPACE)) == _norm(sql)

    def test_no_concept_invention_left(self):
        # 'segment' has no concept → a genuine hallucination, the gate's job to skip
        sql = "SELECT segment FROM bakehouse.sales_customers"
        assert "segment" in repair_semantic_columns(sql, WORKSPACE)

    def test_ambiguous_target_left(self):
        ambig = {"t": ["state", "province", "id"]}     # two geo_region columns → never guess
        sql = "SELECT region FROM t"
        assert repair_semantic_columns(sql, ambig) == sql

    def test_line_total_left_when_no_line_money_column(self):
        # conservative: line_total (money_line) has no money_line target here → leave it
        # (mapping it onto totalPrice would risk a ×quantity double-count)
        sql = "SELECT line_total FROM bakehouse.sales_transactions"
        assert "line_total" in repair_semantic_columns(sql, WORKSPACE)

    def test_select_alias_not_rewritten(self):
        # total_amount is a query-defined ALIAS here, not an invented column
        sql = ("SELECT SUM(totalPrice) AS total_amount FROM bakehouse.sales_transactions "
               "ORDER BY total_amount")
        out = repair_semantic_columns(sql, WORKSPACE)
        assert "AS total_amount" in out or "AS TOTAL_AMOUNT" in out.upper()

    def test_join_repairs_in_scope_only(self):
        out = repair_semantic_columns(
            "SELECT sc.location_country, SUM(st.total_amount) FROM bakehouse.sales_customers sc "
            "JOIN bakehouse.sales_transactions st ON sc.customerID = st.customerID "
            "GROUP BY sc.location_country", WORKSPACE)
        assert "country" in out and "totalPrice" in out
        assert "location_country" not in out and "total_amount" not in out

    def test_unknown_table_is_noop(self):
        sql = "SELECT location_country FROM mystery_table"
        assert repair_semantic_columns(sql, WORKSPACE) == sql

    def test_fail_safe(self):
        assert repair_semantic_columns("this <<< not sql", WORKSPACE) == "this <<< not sql"
        assert repair_semantic_columns("", WORKSPACE) == ""
        assert repair_semantic_columns("SELECT 1", {}) == "SELECT 1"
