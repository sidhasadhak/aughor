"""F6 — schema-drift invalidation: a new connection's table must not inherit a deleted
warehouse's auto-generated glossary (phantom columns / hallucinated enum values). The
glossary is keyed by bare schema.table, so autoseed re-seeds an auto entry whose stored
columns no longer match the live table."""
from aughor.semantic.autoseed import _block_columns, _columns_drifted

BLOCK = """TABLE: analytics.orders  (4620 rows)
  -- one row per order
  order_id  VARCHAR  [id]
  cart_id  VARCHAR
  customer_id  VARCHAR
  -- channel  [Email, Meta]
  channel  VARCHAR"""


def test_block_columns_skips_comments_and_header():
    assert _block_columns(BLOCK) == {"order_id", "cart_id", "customer_id", "channel"}


def test_drift_detected_for_different_warehouse():
    old = {"order_id", "final_price_usd", "cogs_usd", "traffic_source", "quantity"}
    new = {"order_id", "cart_id", "customer_id", "channel", "loyalty_tier", "warehouse"}
    assert _columns_drifted(old, new) is True


def test_no_drift_for_identical_columns():
    cols = {"order_id", "cart_id", "customer_id", "channel"}
    assert _columns_drifted(cols, cols) is False


def test_no_drift_for_minor_addition():
    base = {"order_id", "cart_id", "customer_id", "channel", "status", "method"}
    assert _columns_drifted(base, base | {"new_col"}) is False


def test_empty_sides_never_drift():
    assert _columns_drifted(set(), {"a", "b"}) is False
    assert _columns_drifted({"a", "b"}, set()) is False
