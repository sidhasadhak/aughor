"""grounding.full_schema_first — the size-gated bypass of the schema linker.

The linker prunes to top-k tables/columns even when the ENTIRE compressed schema
fits the char budget the packer would have spent anyway — on a small schema that
buys no tokens and costs structure (a column dropped by top_k_cols is invisible
to the model even though it fits). WrenAI measured full-schema beating pruning
below ~30k chars (2026-08-14 study: complete join paths beat isolated
fragments); the flag exists so OUR E4 grid can settle it on the reference suite.

Off by default. These tests pin BOTH states, so the grid measures a real axis
and graduation (either direction) knows exactly what behaviour it is adopting.
"""
from aughor.kernel.flags import flag_overrides
from aughor.tools.schema_linker import link_schema

# A question that matches `orders` only — under the default path, zero-signal
# tables are dropped (keep set requires score > 0), so pruning is deterministic.
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


def test_default_off_prunes_zero_signal_tables():
    out = link_schema(QUESTION, SCHEMA)
    assert "TABLE: orders" in out
    assert "audit_log" not in out, "default pruning must be unchanged while the flag is off"


def test_flag_on_small_schema_is_sent_whole():
    with flag_overrides({"grounding.full_schema_first": True}):
        out = link_schema(QUESTION, SCHEMA)
    assert out == SCHEMA


def test_flag_on_over_budget_still_prunes():
    # The bypass is size-gated, not unconditional: past the budget, ranking is
    # still what decides what falls off the end.
    with flag_overrides({"grounding.full_schema_first": True}):
        out = link_schema(QUESTION, SCHEMA, char_budget=90)
    assert out != SCHEMA
    assert "TABLE: orders" in out


def test_flag_on_still_collapses_sharded_families():
    # The bypass sits AFTER shard compression on purpose — a thousand date
    # partitions must never ride the "it fits" exemption in raw form.
    with flag_overrides({"grounding.full_schema_first": True}):
        out = link_schema(QUESTION, SHARDED)
    assert out != SHARDED
    assert "more sharded tables" in out
    assert "TABLE: audit_log" in out, "non-sharded tables survive whole under the bypass"
