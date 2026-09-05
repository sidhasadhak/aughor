"""link_schema's trailing pass — the enrichment sections must survive a filtered slice.

The old pass selected trailing content by LINE SHAPE (`^\\s{2}\\w+` ⇒ "column line,
drop it"), but a join-hint detail or a metric formula line is indistinguishable from
a column line by shape (`  orders.customer_id → …`, `  REVENUE (Revenue): SUM(…)`).
Verified live 2026-09-04: a filtered slice kept the bare DETECTED JOIN PATHS /
NO DIRECT FOREIGN KEY / METRICS CATALOG headers with their bodies stripped — a
header asserting content that wasn't there — while `  -- col  [values]`
enumerations from DROPPED tables leaked in after them, detached from any table.
Consumers hit: the /ask fallback prompt and the GET /ask/context schema_slice
receipt (the deep path worked around it by re-running infer_joins — investigate.py).

The pass now finds where the trailing region STARTS (structurally — the first
unindented, non-blank, non-TABLE:, non-`--` line after the tables, so a new
section kind can never reintroduce the bug by being missing from a header list)
and keeps everything from there verbatim.
"""
from aughor.tools.schema_linker import link_schema

# A question matching `orders` only, so pruning is deterministic (zero-signal
# tables are dropped: the keep set requires score > 0).
QUESTION = "total orders revenue"

SCHEMA = """TABLE: orders  (1,000 rows)
  order_id  BIGINT
  customer_id  BIGINT
  revenue  DOUBLE
  status  VARCHAR
  -- status  [pending, shipped]

TABLE: customers  (100 rows)
  customer_id  BIGINT
  country  VARCHAR
  -- country  [US, DE, IN]

DETECTED JOIN PATHS (use these to write correct JOINs):
  orders.customer_id → customers.customer_id  [exact]
NO DIRECT FOREIGN KEY between these table pairs — join them through an intermediate table if the question needs both; do not invent a shared key:
  orders ↔ customers: no shared key detected

METRICS CATALOG (use these exact SQL expressions — do not re-derive):
  REVENUE (Revenue): SUM(revenue)
    Tables: orders

ENTITY RELATIONSHIPS (verified against live data — prefer these joins):
- orders.customer_id → customers.customer_id  [many-to-one, verified]
"""


def _slice() -> str:
    out = link_schema(QUESTION, SCHEMA, top_k_tables=1, top_k_cols=8, char_budget=20_000)
    assert out != SCHEMA, "the fixture must actually be filtered to exercise the trailing pass"
    assert "TABLE: customers" not in out
    return out


def test_join_hint_detail_lines_survive_the_filtered_slice():
    out = _slice()
    assert "  orders.customer_id → customers.customer_id  [exact]" in out
    assert "  orders ↔ customers: no shared key detected" in out


def test_no_section_header_is_emitted_with_its_body_stripped():
    # The failure mode was not a missing section but a LYING one: the header
    # survived over an empty body. Each header must be followed by its content.
    out = _slice()
    lines = out.splitlines()
    for header, body in [
        ("DETECTED JOIN PATHS", "  orders.customer_id"),
        ("NO DIRECT FOREIGN KEY", "  orders ↔ customers"),
        ("METRICS CATALOG", "  REVENUE"),
    ]:
        idx = next(i for i, ln in enumerate(lines) if ln.startswith(header))
        assert lines[idx + 1].startswith(body), f"{header} must keep its first detail line"


def test_metric_formula_lines_survive():
    out = _slice()
    assert "  REVENUE (Revenue): SUM(revenue)" in out
    assert "    Tables: orders" in out


def test_relationship_bullet_lines_survive():
    # Mirrors test_relationship_block.py::test_relationship_lines_survive_schema_linking:
    # the ENTITY RELATIONSHIPS renderer chose `- `-bullets precisely to survive
    # this pass, so bullets surviving is a cross-branch contract, not an accident.
    out = _slice()
    assert "- orders.customer_id → customers.customer_id  [many-to-one, verified]" in out


def test_dropped_tables_leave_no_orphaned_annotations_behind():
    # The old pass appended `  -- col  [values]` enumerations from EVERY table —
    # including dropped ones — after the blocks, detached from any table.
    out = _slice()
    assert "country  [US, DE, IN]" not in out


def test_a_shard_note_between_blocks_does_not_open_the_trailing_region():
    # compress_schema emits top-level `-- + N more sharded tables …` notes between
    # TABLE blocks. If one opened the trailing region, every block after it would
    # be appended verbatim on top of the packer's output — duplicated tables.
    sharded = "".join(
        f"TABLE: events_2021_{m:02d}\n  event_id  INTEGER\n  payload  VARCHAR\n\n"
        for m in (1, 2, 3)
    ) + SCHEMA
    out = link_schema(QUESTION, sharded, top_k_tables=1, top_k_cols=8, char_budget=20_000)
    assert out.count("TABLE: orders") == 1
    assert "  orders.customer_id → customers.customer_id  [exact]" in out


def test_a_schema_with_no_trailing_sections_gains_none():
    bare = "TABLE: orders  (10 rows)\n  order_id  BIGINT\n  revenue  DOUBLE\n\n" \
           "TABLE: audit_log  (5 rows)\n  log_id  BIGINT\n"
    out = link_schema(QUESTION, bare, top_k_tables=1, top_k_cols=8, char_budget=20_000)
    assert "audit_log" not in out
    assert out.strip().splitlines()[-1].startswith("  "), "nothing but the kept block"
