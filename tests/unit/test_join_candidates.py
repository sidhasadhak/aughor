"""Join-candidate generation — the entity-match guard on the legacy non-key path.

Pins the real bug: two tables both having a `continent` / `quantity` / `district` column
is a coincidence, not a foreign key, and was being proposed as a join (then wasting an
orphan-check and polluting neighbour-grounding). A non-suffixed join root now joins only
when it NAMES AN ENTITY (a table); key-suffixed FKs (customerID, customer_id) are unaffected.
"""
from aughor.tools.schema import _compute_join_map, _entity_roots


def _pairs(jm):
    return {(j["c1"], j["c2"]) for j in jm["joins"]} | {(j["c2"], j["c1"]) for j in jm["joins"]}


class TestEntityMatch:
    def test_dimension_coincidence_not_joined(self):
        # both tables have `continent` and `quantity` — neither names a table → not a join
        tc = {
            "sales_customers": ["customerID", "continent", "city"],
            "sales_suppliers": ["supplierID", "continent", "quantity"],
            "sales_orders":    ["orderID", "quantity"],
        }
        pairs = _pairs(_compute_join_map(tc))
        assert ("continent", "continent") not in pairs
        assert ("quantity", "quantity") not in pairs

    def test_entity_reference_join_kept(self):
        # a bare `product` column names the `products` table → a real entity reference
        tc = {
            "products":     ["product_id", "name"],
            "order_lines":  ["line_id", "product"],
        }
        pairs = _pairs(_compute_join_map(tc))
        assert ("product", "product_id") in pairs or ("product_id", "product") in pairs

    def test_key_suffix_fks_unaffected(self):
        # the camelCase + snake_case FK paths must still join (not the legacy path)
        tc = {
            "customers":    ["customer_id", "name"],
            "orders":       ["order_id", "customer_id"],
            "transactions": ["txn_id", "customerID"],
        }
        pairs = _pairs(_compute_join_map(tc))
        # customer_id is shared → orders↔customers join exists
        assert any(c1 == "customer_id" or c2 == "customer_id" for c1, c2 in pairs)

    def test_entity_roots_include_head_noun(self):
        roots = _entity_roots({"bakehouse.sales_customers": [], "ecommerce.order_items": []})
        assert "customer" in roots and "customers" in roots   # head noun + plural
        assert "item" in roots
        assert "continent" not in roots and "quantity" not in roots

    def test_pure_dimension_schema_yields_no_spurious_joins(self):
        # the workspace failure shape: geo/measure columns shared across unrelated tables
        tc = {
            "bakehouse.sales_customers":  ["customerID", "continent", "district"],
            "bakehouse.sales_suppliers":  ["supplierID", "continent", "district", "ingredient"],
            "ecommerce.order_items":      ["item_id", "quantity"],
            "bakehouse.sales_transactions": ["transactionID", "quantity"],
        }
        pairs = _pairs(_compute_join_map(tc))
        for noise in ("continent", "district", "ingredient", "quantity"):
            assert (noise, noise) not in pairs, f"{noise} should not be a join key"
