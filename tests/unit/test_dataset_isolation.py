"""Multi-dataset exploration isolation — Phase 8 must not join unrelated uploaded
datasets (separate schemas). Origin: a `workspace` connection held a bakehouse CRM
(`bakehouse.*`) + an ecommerce store (`ecommerce.*`); exploration generated
`bakehouse.sales_customers ⋈ ecommerce.orders` — a hallucinated cross-dataset join that
binder-errored and produced a "no data" finding. See agent._crosses_datasets.
"""
from aughor.explorer.agent import _dataset_of, _tables_in_sql, _crosses_datasets


def test_dataset_of():
    assert _dataset_of("bakehouse.sales_customers") == "bakehouse"
    assert _dataset_of("ecommerce.orders") == "ecommerce"
    assert _dataset_of("catalog.ecommerce.orders") == "catalog.ecommerce"
    assert _dataset_of("orders") == ""        # unqualified


def test_tables_in_sql_extracts_real_tables():
    sql = ("WITH co AS (SELECT * FROM ecommerce.orders) "
           "SELECT * FROM co JOIN bakehouse.sales_customers c ON co.id = c.id")
    tables = _tables_in_sql(sql)
    assert "ecommerce.orders" in tables
    assert "bakehouse.sales_customers" in tables
    assert "co" not in tables                 # CTE name excluded


def test_crosses_datasets_flags_the_garbage_join():
    sql = ("SELECT COUNT(*) FROM bakehouse.sales_customers c "
           "JOIN ecommerce.orders o ON c.customer_id = o.customer_id "
           "WHERE o.order_date >= '2023-12-31'")
    assert _crosses_datasets(sql) is True


def test_within_dataset_join_is_allowed():
    sql = ("SELECT * FROM bakehouse.sales_customers c "
           "JOIN bakehouse.sales_transactions t ON c.customerID = t.customerID")
    assert _crosses_datasets(sql) is False


def test_single_schema_warehouse_not_flagged():
    # TPC-DS-style: all tables in one schema, real joins — never cross-dataset.
    sql = ("SELECT * FROM main.store_sales ss JOIN main.date_dim d "
           "ON ss.ss_sold_date_sk = d.d_date_sk")
    assert _crosses_datasets(sql) is False


def test_unqualified_tables_not_flagged():
    # No schema qualifiers → can't be cross-dataset → never blocked.
    sql = "SELECT * FROM orders o JOIN customers c ON o.cid = c.id"
    assert _crosses_datasets(sql) is False


def test_cte_masked_cross_dataset_is_flagged():
    # Both schema refs hidden inside CTE bodies; the outer refs are CTE aliases.
    # The shared CTE-safe extractor must still surface the real cross-schema join.
    sql = ("WITH a AS (SELECT * FROM ecommerce.orders), "
           "b AS (SELECT * FROM bakehouse.sales_customers) "
           "SELECT * FROM a JOIN b ON a.id = b.id")
    assert _crosses_datasets(sql) is True


def test_cte_alias_not_mistaken_for_schema():
    # `co` is a CTE alias, not a real table — must be excluded from extraction.
    sql = ("WITH co AS (SELECT * FROM ecommerce.orders) "
           "SELECT * FROM co JOIN bakehouse.sales_customers c ON co.id = c.id")
    tables = _tables_in_sql(sql)
    assert "ecommerce.orders" in tables and "bakehouse.sales_customers" in tables
    assert "co" not in tables
