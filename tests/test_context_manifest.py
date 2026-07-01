"""P2 Agent Context surface: the context manifest + rescope (pure, no LLM/DB)."""
from __future__ import annotations

from aughor.tools.context_manifest import (
    build_context_manifest,
    estimate_tokens,
    rescope_schema,
)

SCHEMA = """TABLE: sales.orders
  order_id  BIGINT
  customer_id  BIGINT
  total_amount  DOUBLE

TABLE: sales.customers
  customer_id  BIGINT
  name  VARCHAR

TABLE: sales.line_items
  order_id  BIGINT
  product_id  BIGINT
  qty  INTEGER
"""


def test_manifest_parses_tables_tokens_and_joins():
    m = build_context_manifest(SCHEMA)
    assert set(m.tables) == {"sales.orders", "sales.customers", "sales.line_items"}
    assert m.table_count == 3
    assert m.estimated_tokens > 0
    # orders↔customers (customer_id) and orders↔line_items (order_id) should be found,
    # and rendered with populated from/to (regression guard for the join-key parsing).
    assert m.joins, "expected FK join hints"
    assert all(j["from"] and j["to"] for j in m.joins)


def test_rescope_exclude_drops_table_and_saves_tokens():
    full = build_context_manifest(SCHEMA)
    scoped, m = rescope_schema(SCHEMA, exclude=["sales.line_items"], expand_fk=False)
    assert "sales.line_items" not in m.tables
    assert m.table_count == 2
    assert m.estimated_tokens < full.estimated_tokens  # trimming context lowers the budget


def test_rescope_keep_is_an_allowlist():
    _, m = rescope_schema(SCHEMA, keep=["sales.orders"], expand_fk=False)
    assert m.tables == ["sales.orders"]


def test_rescope_add_reintroduces_a_table():
    _, m = rescope_schema(SCHEMA, exclude=["sales.customers", "sales.line_items"],
                          add=["sales.line_items"], expand_fk=False)
    assert set(m.tables) == {"sales.orders", "sales.line_items"}


def test_estimate_tokens_monotonic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 40) == 10
    assert estimate_tokens("x" * 400) > estimate_tokens("x" * 40)
