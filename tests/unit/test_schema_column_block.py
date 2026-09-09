"""A TABLE: block ends at the first line that is not a column.

The terminator used to be a hand-written list of section headers, so every section
header nobody had added to it was parsed as COLUMNS OF THE PRECEDING TABLE. Measured
on the live instance before the fix:

    GET /connections/baef6c3e/schema/rich
    → main.superstore: 26 columns, the last five of which were
      "order_reviews.review_comment_title: NULL = data quality issue — value should exist"
      "  active:"
      "order_items.order_id → order_payments.order_id"

— because `EXPLORATION INTELLIGENCE`, `NULL SEMANTICS`, `ENTITY LIFECYCLE` and
`JOIN INTEGRITY` were not on the list. Everything downstream inherited them: the SQL
editor offered them as column completions, and its "expand wildcard" wrote them into
a SELECT list.

The rule is structural now, so it cannot go stale — which is what these tests pin.
A guard whose population is a list beside its expectation cannot fail.
"""
from __future__ import annotations

from aughor.db.schema_render import ends_column_block
from aughor.tools.schema import build_rich_schema, parse_schema_tables

# The shape the live renderer emits, trimmed to the parts that matter.
SCHEMA = """TABLE: main.superstore  (9,994 rows)
  -- The superstore table contains sales transaction records.
  Row ID  INTEGER  ~ e.g. '1', '2'
  Profit  FLOAT  ~ e.g. '41.9'  [Net profit in dollars]

EXPLORATION INTELLIGENCE [DOMAIN_INTEL] — background cartography:

NULL SEMANTICS (verified — NULL in these columns carries business meaning):
  order_reviews.review_comment_title: NULL = data quality issue  (0% null rate)

ENTITY LIFECYCLE (verified state machines):
  Order:
    active:   invoiced, processing
    active filter: order_status NOT IN ('canceled')

JOIN INTEGRITY (caution — orphaned FK rows detected):
  order_items.order_id → order_payments.order_id  (3 orphan rows)
"""


def test_columns_stop_at_the_first_section_header():
    cols = parse_schema_tables(SCHEMA)
    assert cols["main.superstore"] == ["Row ID", "Profit"], (
        "annotation prose is being read as columns — the exact defect that put "
        "'order_items.order_id → order_payments.order_id' in a SELECT list"
    )


def test_rich_schema_carries_only_real_columns():
    rich = build_rich_schema(SCHEMA)
    table = next(t for t in rich["tables"] if t["name"] == "main.superstore")
    assert [c["name"] for c in table["columns"]] == ["Row ID", "Profit"]


def test_a_header_nobody_listed_still_ends_the_block():
    """The point of the structural rule: a section invented tomorrow ends the block
    without anyone editing a regex."""
    schema = SCHEMA.replace("NULL SEMANTICS", "SOME FUTURE SECTION")
    assert parse_schema_tables(schema)["main.superstore"] == ["Row ID", "Profit"]


def test_ends_column_block_is_about_indentation_not_vocabulary():
    assert ends_column_block("NULL SEMANTICS (verified):")
    assert ends_column_block("ANYTHING AT ALL")
    assert ends_column_block("-- a divider at column 0")
    # An INDENTED comment belongs to the block — it is how the renderer writes a
    # table's description, and the column parsers skip it themselves.
    assert not ends_column_block("  -- The superstore table contains sales records.")
    assert not ends_column_block("  Row ID  INTEGER")   # a column
    assert not ends_column_block("")                    # a blank line separates, not ends
    assert not ends_column_block("TABLE: main.orders  (1 rows)")  # the caller owns this
