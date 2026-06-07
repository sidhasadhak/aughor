"""Unit tests for the canonical table-name primitive (aughor.tools.table_names).

These pin the behaviour that previously had to be re-fixed three times: comparing
schema-qualified names against bare names. If this module regresses, the ERD /
ontology / multi-schema bugs come back.
"""
from aughor.tools.table_names import (
    TableRef, bare, leaf, qualify, resolve, resolve_in, same_table, schema_of, split_ref,
)


def test_leaf_preserves_case_strips_schema_and_quotes():
    assert leaf("analytics.Orders") == "Orders"
    assert leaf('"analytics"."Order_Items"') == "Order_Items"
    assert leaf("orders") == "orders"
    assert leaf("memory.bakehouse.Reviews") == "Reviews"


def test_bare_is_lowercased_leaf():
    assert bare("Analytics.Orders") == "orders"
    assert bare("ecommerce.order_items") == "order_items"
    assert bare("ORDERS") == "orders"


def test_schema_of_handles_two_and_three_part():
    assert schema_of("analytics.orders") == "analytics"
    assert schema_of("memory.bakehouse.reviews") == "bakehouse"
    assert schema_of("orders") is None


def test_split_ref():
    assert split_ref("analytics.Orders") == ("analytics", "Orders")
    assert split_ref("orders") == (None, "orders")


def test_qualify_passthrough_and_apply():
    assert qualify("orders", "analytics") == "analytics.orders"
    assert qualify("analytics.orders", "analytics") == "analytics.orders"  # already qualified
    assert qualify("orders", None) == "orders"


def test_same_table_tolerates_qualified_vs_bare():
    # The exact bug: these must be considered the same table.
    assert same_table("analytics.order_items", "order_items")
    assert same_table("order_items", "analytics.order_items")
    assert same_table("BAKEHOUSE.Media_Reviews", "media_reviews")
    assert not same_table("analytics.orders", "analytics.customers")


def test_same_table_schema_strict():
    # bare still matches qualified (absence of schema = "any")
    assert same_table("orders", "analytics.orders", schema_strict=True)
    # but two different qualified schemas with same leaf do NOT match in strict mode
    assert not same_table("raw.orders", "analytics.orders", schema_strict=True)
    assert same_table("raw.orders", "analytics.orders", schema_strict=False)


def test_resolve_in_replaces_the_bandaid():
    # table_to_entity keyed by BARE names, join carries QUALIFIED name.
    t2e = {"order_items": "OrderItem", "orders": "Order"}
    assert resolve_in(t2e, "analytics.order_items") == "OrderItem"
    assert resolve_in(t2e, "order_items") == "OrderItem"
    assert resolve_in(t2e, "analytics.unknown") is None
    # And the reverse: keyed by QUALIFIED, looked up BARE.
    t2e_q = {"analytics.order_items": "OrderItem"}
    assert resolve_in(t2e_q, "order_items") == "OrderItem"


def test_resolve_prefers_exact_then_tolerant():
    cands = ["analytics.orders", "orders_backup"]
    assert resolve("analytics.orders", cands) == "analytics.orders"   # exact
    assert resolve("orders", cands) == "analytics.orders"             # tolerant


def test_tableref_roundtrip():
    r = TableRef.parse("analytics.Orders")
    assert r.schema == "analytics" and r.name == "Orders"
    assert r.bare == "orders"
    assert r.qualified() == "analytics.Orders"
    assert str(TableRef.parse("orders")) == "orders"
