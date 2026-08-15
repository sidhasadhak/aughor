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


# ── grain claims are verified against the data before they are stored (2026-08-15) ──
# The Superstore `returns` table was seeded "one row per returned order_id" — 800 rows over
# 296 distinct order_ids — and every "how many orders were returned?" then wrote COUNT(*)
# (800, not 296) because the schema TOLD the model each row was an order. A false grain
# claim is worse than none.

def _duck():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE returns AS SELECT * FROM (VALUES "
                "('o1', 'a'), ('o1', 'b'), ('o2', 'c'), ('o3', 'd')) t(order_id, item)")
    con.execute("CREATE TABLE customers AS SELECT * FROM (VALUES "
                "('c1', 'Ann'), ('c2', 'Bo')) t(customer_id, name)")
    return con


def test_false_grain_claim_is_rewritten_to_the_data():
    from aughor.semantic.autoseed import verify_grain_claim
    out = verify_grain_claim("one row per returned order_id", "returns", {"order_id", "item"}, _duck())
    assert "NOT one row per order_id" in out
    assert "4 rows over 3 distinct order_id" in out
    assert "COUNT(DISTINCT order_id)" in out
    assert "Seeded claim was: one row per returned order_id" in out, "the original guess stays visible"


def test_true_grain_claim_is_kept_verbatim():
    from aughor.semantic.autoseed import verify_grain_claim
    assert verify_grain_claim("one row per customer_id", "customers", {"customer_id", "name"}, _duck()) == "one row per customer_id"


def test_grain_noun_resolves_to_its_id_column():
    from aughor.semantic.autoseed import verify_grain_claim
    # "one row per order" — the noun is not a column, order_id is
    out = verify_grain_claim("One row per order", "returns", {"order_id", "item"}, _duck())
    assert "NOT one row per order_id" in out


def test_unverifiable_claims_pass_through():
    from aughor.semantic.autoseed import verify_grain_claim
    con = _duck()
    # no conn · no key named · key not a column · a table the query cannot reach
    assert verify_grain_claim("one row per order_id", "returns", {"order_id"}, None) == "one row per order_id"
    assert verify_grain_claim("a snapshot of the warehouse", "returns", {"order_id"}, con) == "a snapshot of the warehouse"
    assert verify_grain_claim("one row per shipment", "returns", {"order_id", "item"}, con) == "one row per shipment"
    assert verify_grain_claim("one row per order_id", "no_such_table", {"order_id"}, con) == "one row per order_id"


def test_composite_and_identified_by_grains_are_judged_correctly():
    # Audit 2026-08-15: 3 of 9 "contradictions" were COMPOSITE grains the verifier judged
    # on one swept word ("per ticket per flight" → refused on flight_id). A composite
    # claim is left alone; an "identified by X" claim is judged on X, not the noun.
    import duckdb
    from aughor.semantic.autoseed import verify_grain_claim
    con = duckdb.connect()
    con.execute("CREATE TABLE baggage AS SELECT * FROM (VALUES "
                "('t1','f1'),('t2','f1'),('t3','f2')) t(ticket_id, flight_id)")
    con.execute("CREATE TABLE chunks AS SELECT * FROM (VALUES "
                "('r1', 1),('r1', 2),('r2', 1)) t(review_id, chunk_no)")
    cols = {"ticket_id", "flight_id"}
    # composite: true claim, must NOT be rewritten even though flight_id repeats
    assert verify_grain_claim("One row per ticket per flight", "baggage", cols, con) == "One row per ticket per flight"
    assert verify_grain_claim("one row per platform-segment-year", "baggage", cols, con) == "one row per platform-segment-year"
    # identified-by: judged on review_id (which repeats) → corrected
    out = verify_grain_claim("One row per chunk of a review, identified by review_id", "chunks", {"review_id", "chunk_no"}, con)
    assert "NOT one row per review_id" in out


def test_phantom_identified_by_column_falls_back_to_the_noun():
    # main.orders (Superstore) was seeded "one row per order (identified by o_orderkey)" —
    # a TPC-H column name that does not exist on the table. The phantom key must not
    # launder the false claim: judge "order" → order_id (9,994 rows over 5,009).
    import duckdb
    from aughor.semantic.autoseed import verify_grain_claim
    con = duckdb.connect()
    con.execute("CREATE TABLE orders AS SELECT * FROM (VALUES "
                "(1,'o1'),(2,'o1'),(3,'o2')) t(row_id, order_id)")
    out = verify_grain_claim("one row per order (identified by o_orderkey)", "orders", {"row_id", "order_id"}, con)
    assert "NOT one row per order_id" in out
