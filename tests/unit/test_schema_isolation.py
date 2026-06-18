"""Schema isolation for the Briefing/Domains views — findings must scope to the SELECTED
schema even when sibling schemas share table names.

Regression: a workspace folds ecommerce + missimi, both with `orders`/`customers`/
`products`. Bare-name matching leaked every ecommerce insight into the `missimi` view
(and vice versa). Matching on the SCHEMA-QUALIFIED ref fixes it.
"""
from aughor.routers.exploration import _tables_from_sql, _insight_refs, _refs_in_schema, _qualified_set


def test_tables_from_sql_returns_qualified_and_bare():
    refs = _tables_from_sql("SELECT * FROM missimi.orders o JOIN ecommerce.products p ON 1=1")
    assert "missimi.orders" in refs and "ecommerce.products" in refs   # qualified
    assert "orders" in refs and "products" in refs                     # bare (fallback)


# ecommerce and missimi BOTH have an `orders` table — the collision case.
ECOM = {"orders", "customers", "products", "order_items", "reviews"}
MISSIMI = {"orders", "customers", "products", "order_items", "brands", "warehouses"}


def test_qualified_insight_isolates_to_its_schema():
    ins = {"sql": "SELECT status, COUNT(*) FROM ecommerce.orders GROUP BY 1", "entities_involved": []}
    refs = _insight_refs(ins)
    assert _refs_in_schema(refs, ECOM, _qualified_set("ecommerce", ECOM))         # shows under ecommerce
    assert not _refs_in_schema(refs, MISSIMI, _qualified_set("missimi", MISSIMI))  # NOT under missimi


def test_other_schema_insight_excluded_despite_shared_table_name():
    ins = {"sql": "SELECT * FROM missimi.orders", "entities_involved": []}
    refs = _insight_refs(ins)
    assert _refs_in_schema(refs, MISSIMI, _qualified_set("missimi", MISSIMI))
    assert not _refs_in_schema(refs, ECOM, _qualified_set("ecommerce", ECOM))


def test_cross_schema_insight_appears_in_both():
    ins = {"sql": "SELECT * FROM bakehouse.sales_transactions b JOIN ecommerce.orders o ON 1=1",
           "entities_involved": []}
    refs = _insight_refs(ins)
    assert _refs_in_schema(refs, ECOM, _qualified_set("ecommerce", ECOM))
    assert _refs_in_schema(refs, {"sales_transactions"}, _qualified_set("bakehouse", {"sales_transactions"}))


def test_unqualified_sql_falls_back_to_bare():
    # single-schema connections emit unqualified SQL — keep matching on bare names.
    ins = {"sql": "SELECT * FROM orders", "entities_involved": []}
    assert _refs_in_schema(_insight_refs(ins), ECOM, _qualified_set("ecommerce", ECOM))
