"""PENDING item 19 — the SQL writer can be shown what the data holds (`grounding.data_profiles`, off).

The profiler measures every table and column and caches it; the Data Catalog carries five head
rows and none of those numbers. This block renders them for the linked tables, from the cache
only, under a budget. Off by default: it changes the prompt, and a prompt change ships on a
measurement.
"""
from __future__ import annotations

import inspect

import pytest

from aughor.tools import catalog_profiles as cp

ENTRY = {
    "tables": {
        "ecommerce.orders": {"row_count": 5000, "date_range": ["2023-01-01", "2024-12-31"],
                             "primary_timestamp": "order_date"},
        "ecommerce.products": {"row_count": 200},
    },
    "columns": {
        "orders.order_id": {"table": "ecommerce.orders", "column": "order_id",
                            "semantic_type": "key", "distinct_count": 5000},
        "orders.status": {"table": "ecommerce.orders", "column": "status",
                          "semantic_type": "dimension", "distinct_count": 4,
                          "top_values": ["delivered", "shipped", "cancelled", "returned"]},
        "orders.total_amount": {"table": "ecommerce.orders", "column": "total_amount",
                                "semantic_type": "measure", "value_range": [0.5, 4200.0],
                                "p50": 88.4, "unit": "USD"},
        "orders.coupon": {"table": "ecommerce.orders", "column": "coupon",
                          "semantic_type": "dimension", "null_rate": 0.62},
        "products.category": {"table": "ecommerce.products", "column": "category",
                              "semantic_type": "dimension", "distinct_count": 9,
                              "top_values": ["Electronics", "Books", "Toys", "Garden",
                                             "Beauty", "Sports", "Home"]},
    },
}


@pytest.fixture()
def cached(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: ENTRY)


def test_the_block_carries_what_five_head_rows_cannot(cached):
    block = cp.render("c1", ["ecommerce.orders", "ecommerce.products"])

    assert block.startswith("DATA PROFILE — measured by the profiler")
    assert "ecommerce.orders: 5,000 rows, 2023-01-01 to 2024-12-31 (by order_date)" in block
    assert "  status: most frequent values: 'delivered', 'shipped', 'cancelled', 'returned'" in block
    assert "  total_amount: 0.50 to 4,200, median 88.40 (USD)" in block
    assert "  coupon: 62% null" in block
    assert "order_id" not in block                      # keys add nothing a filter needs
    assert "'Home'" not in block and "about 9 values, most frequent:" in block   # six, then more


def test_an_estimated_count_never_contradicts_the_values_listed(monkeypatch):
    """Measured on the samples warehouse: SUMMARIZE estimated 5 distinct categories and the
    profiler listed six. The list says "most frequent" and carries no count below it."""
    entry = {"tables": {"products": {"row_count": 150}},
             "columns": {"products.category": {
                 "table": "products", "column": "category", "semantic_type": "dimension",
                 "distinct_count": 5, "top_values": ["Apparel", "Electronics", "Office",
                                                     "Kitchen", "Fitness", "Accessories"]}}}
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: entry)
    block = cp.render("c1", ["products"])
    assert "  category: most frequent values: 'Apparel', 'Electronics', 'Office', 'Kitchen', 'Fitness', 'Accessories'" in block
    assert "5 values" not in block


def test_only_the_linked_tables_and_in_their_rank_order(cached):
    block = cp.render("c1", ["products"])
    assert "products: 200 rows" in block and "orders" not in block


def test_a_table_the_budget_cannot_fit_is_named_not_dropped(cached):
    block = cp.render("c1", ["ecommerce.orders", "ecommerce.products"], budget=420)
    assert "ecommerce.orders: 5,000 rows" in block
    assert "profiles for ecommerce.products are left out" in block


def test_nothing_cached_is_nothing_said(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: {})
    assert cp.render("c1", ["orders"]) == ""


def test_off_by_default_and_gated_where_the_prompt_is_built(monkeypatch):
    monkeypatch.delenv("AUGHOR_GROUNDING_DATA_PROFILES", raising=False)
    assert cp.enabled() is False
    from aughor.kernel.flags import flag_disposition
    assert flag_disposition("grounding.data_profiles") == "experiment"
    from aughor.routers.investigations import _answer_core
    src = inspect.getsource(_answer_core)
    assert "if _catalog_profiles.enabled():" in src
    assert "_catalog_profiles.render(connection_id, linked_tables)" in src
