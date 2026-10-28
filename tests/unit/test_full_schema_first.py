"""Full schema first — the size-gated bypass of the schema linker (the flag
`grounding.full_schema_first` until it was made unconditional, 2026-10-28, ROADMAP §3.65).

The linker prunes to top-k tables/columns only when the ENTIRE compressed schema does not
fit the char budget the packer would have spent anyway — on a small schema pruning buys no
tokens and costs structure (a column dropped by top_k_cols is invisible to the model even
though it fits). WrenAI measured full-schema beating pruning below ~30k chars (2026-08-14
study: complete join paths beat isolated fragments); kept on its own record — in two test
runs the SQL writer seeing every table of a small schema never wrote a worse query, and
twice answered where the pruned schema could not.
"""
from aughor.tools.schema_linker import link_schema

# A question that matches `orders` only — past the budget, zero-signal tables are dropped
# (keep set requires score > 0), so pruning is deterministic.
QUESTION = "total orders revenue by month"

SCHEMA = """TABLE: orders
  order_id INTEGER
  revenue NUMERIC
  created_at DATE
TABLE: shipping_zones
  zone_id INTEGER
  zone_name VARCHAR
TABLE: audit_log
  log_id INTEGER
  actor VARCHAR
"""

SHARDED = "".join(
    f"TABLE: events_2021_{m:02d}\n  event_id INTEGER\n  payload VARCHAR\n"
    for m in (1, 2, 3)
) + SCHEMA


def test_a_small_schema_is_sent_whole():
    assert link_schema(QUESTION, SCHEMA) == SCHEMA


def test_over_budget_still_prunes_zero_signal_tables():
    # The bypass is size-gated, not unconditional: past the budget, ranking is
    # still what decides what falls off the end.
    out = link_schema(QUESTION, SCHEMA, char_budget=90)
    assert out != SCHEMA
    assert "TABLE: orders" in out
    assert "audit_log" not in out


def test_sharded_families_are_still_collapsed():
    # The bypass sits AFTER shard compression on purpose — a thousand date
    # partitions must never ride the "it fits" exemption in raw form.
    out = link_schema(QUESTION, SHARDED)
    assert out != SHARDED
    assert "more sharded tables" in out
    assert "TABLE: audit_log" in out, "non-sharded tables survive whole under the bypass"
