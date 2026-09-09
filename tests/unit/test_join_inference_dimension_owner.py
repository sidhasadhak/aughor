"""Join inference used to join fact tables to each other and miss every dimension.

Three defects, found together on theLook (BigQuery) 2026-09-08. Its five inferred
joins were all fact-to-fact and none reached `users.id` or `products.id`.

1. A dimension's own key is usually bare ``id``, and ``fk_root("id")`` is None, so
   the dimension never entered its key root's candidate list. With no owner to
   route to, the all-pairs fallback joined the facts to one another.

2. On the owner-routed path the dimension was emitted as ``t1``. Every consumer
   reads ``t1`` as the FK side — ``build_rich_schema`` badges is_fk on ``t1.c1``
   only, and the explorer's orphan probe asks which ``t1.c1`` values are absent
   from ``t2.c2``. Inverted, a healthy star schema failed its own join check,
   because a dimension row nobody has ordered read as an orphan.

3. ``postal_code`` roots to ``postal``, which names no table, and the key-aware
   path skipped the non-key blocklist entirely. The bogus edge also *suppressed* a
   real one: the first join to claim a table pair blocks every later one, so
   users↔events on postal_code hid ``events.user_id → users.id``.
"""

from aughor.db.schema_render import fk_root
from aughor.tools.schema import _compute_join_map

# theLook's shape, reduced. `users` and `products` key on bare `id`.
THELOOK = {
    "users":       ["id", "first_name", "postal_code"],
    "orders":      ["order_id", "user_id"],
    "order_items": ["id", "order_id", "user_id", "product_id"],
    "events":      ["id", "user_id", "postal_code"],
    "products":    ["id"],
}

# The fused-key convention: every column carries a short table prefix and the
# suffix is glued on (c_custkey, not customer_id). This must keep working.
TPCH = {
    "customer": ["c_custkey", "c_name", "c_nationkey"],
    "orders":   ["o_orderkey", "o_custkey"],
    "lineitem": ["l_orderkey", "l_partkey"],
    "part":     ["p_partkey", "p_name"],
}


def edges(cols):
    return {(j["t1"], j["c1"], j["t2"], j["c2"]) for j in _compute_join_map(cols)["joins"]}


class TestDimensionWithBareIdKey:
    def test_the_root_cause_is_still_the_root_cause(self):
        # Not asserting a fix here — pinning WHY the dimension went missing, so a
        # later change to fk_root does not quietly make this whole file vacuous.
        assert fk_root("id") is None
        assert fk_root("user_id") == "user"

    def test_facts_reach_the_dimension(self):
        e = edges(THELOOK)
        assert ("orders", "user_id", "users", "id") in e
        assert ("order_items", "user_id", "users", "id") in e
        assert ("events", "user_id", "users", "id") in e
        assert ("order_items", "product_id", "products", "id") in e

    def test_no_fact_joins_to_another_fact(self):
        facts = {"events", "order_items"}
        bad = [(t1, c1, t2, c2) for t1, c1, t2, c2 in edges(THELOOK)
               if t1 in facts and t2 in facts]
        assert bad == [], f"fact-to-fact joins re-appeared: {bad}"

    def test_a_dimension_only_schema_still_infers_nothing(self):
        # Two dimensions that share no key must not be joined just because both
        # have an `id` column.
        assert edges({"users": ["id", "email"], "products": ["id", "name"]}) == set()


class TestEdgeDirection:
    def test_star_path_puts_the_fact_in_fk_position(self):
        star = {
            "item":          ["item_id", "name"],
            "store_sales":   ["item_id", "amount"],
            "catalog_sales": ["item_id", "amount"],
            "web_sales":     ["item_id", "amount"],
        }
        for t1, _c1, t2, _c2 in edges(star):
            assert t2 == "item", f"{t1} → {t2}: the dimension must be the PK side"

    def test_two_table_path_puts_the_fact_in_fk_position(self):
        # Only one edge is possible here; the defect was that its direction fell
        # out of dict ordering rather than out of which table owns the key.
        assert edges({"users": ["id", "email"], "orders": ["order_id", "user_id"]}) == {
            ("orders", "user_id", "users", "id"),
        }

    def test_the_owning_table_is_the_pk_side_even_when_it_sorts_first(self):
        assert ("order_items", "order_id", "orders", "order_id") in edges(THELOOK)

    def test_an_exact_name_match_outranks_a_prefix_match(self):
        # `_names_root` accepts a prefix so `cust` can find `customer`. That also
        # lets `order_items` answer to the root `order`, and on theLook it won —
        # putting the line-item table in PK position and inverting the edge.
        e = edges({
            "orders":      ["order_id", "user_id"],
            "order_items": ["id", "order_id"],
        })
        assert e == {("order_items", "order_id", "orders", "order_id")}


class TestFusedKeysUnaffected:
    def test_tpch_prefixed_keys_still_resolve_to_their_dimension(self):
        e = edges(TPCH)
        assert ("orders", "o_custkey", "customer", "c_custkey") in e
        assert ("lineitem", "l_orderkey", "orders", "o_orderkey") in e
        assert ("lineitem", "l_partkey", "part", "p_partkey") in e

    def test_no_fused_key_edge_points_the_wrong_way(self):
        for t1, c1, t2, c2 in edges(TPCH):
            assert not (t1 == "customer" and t2 == "orders")
            assert not (t1 == "part" and t2 == "lineitem")


class TestGeographicRootsAreNotKeys:
    def test_postal_code_is_not_a_foreign_key(self):
        assert not any(c1 == "postal_code" or c2 == "postal_code"
                       for _t1, c1, _t2, c2 in edges(THELOOK))

    def test_the_bogus_edge_no_longer_steals_the_real_one(self):
        # The regression that made this worth fixing rather than tolerating: a
        # table pair can carry only one inferred join, so the wrong one wins by
        # arriving first.
        assert ("events", "user_id", "users", "id") in edges(THELOOK)

    def test_a_root_that_does_name_a_table_is_still_a_key(self):
        # The blocklist must only bite when nothing owns the root — `region` is
        # blocklisted, but a real `regions` dimension makes it a genuine key.
        e = edges({
            "regions": ["region_id", "name"],
            "stores":  ["store_id", "region_id"],
            "staff":   ["staff_id", "region_id"],
        })
        assert ("stores", "region_id", "regions", "region_id") in e
