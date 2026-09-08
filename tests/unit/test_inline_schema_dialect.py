"""Two schema dialects reach the schema-string parsers, and only one was read.

The house format gives every column its own two-space-indented line. Five
warehouse connectors — BigQuery, Snowflake, MySQL, MotherDuck, Exasol — render
the whole column list inline in brackets on the ``TABLE:`` line instead::

    TABLE: orders (124920 rows) [order_id INTEGER, user_id INTEGER, ...]

``_parse_schema_tables`` learned that dialect, but the three parsers in
``tools.schema`` each carry their own copy of the column loop and none of them
did. A table in the inline dialect therefore parsed as having zero columns —
which is indistinguishable from a table that genuinely has none, so nothing
raised: the ERD drew empty cards, no join was inferred, and
``col_types_from_schema`` — "the single source of truth for the aggregate↔type
guard" — returned an empty mapping and passed every aggregate.

The fixture below is theLook's real cached BigQuery schema, trimmed.
"""

from aughor.db.schema_render import parse_inline_columns, parse_schema_tables
from aughor.tools.schema import (
    build_mermaid_er,
    build_rich_schema,
    col_types_from_schema,
)

# theLook, as the BigQuery connector renders it (aughor/connectors/warehouse/bigquery.py).
# `user_id` appears on two tables because that shared name is what the join map
# keys on — one table carrying it in isolation infers nothing, in either dialect.
INLINE = """\
TABLE: distribution_centers (10 rows) [id INTEGER, name STRING, latitude FLOAT]
TABLE: orders (124920 rows) [order_id INTEGER, user_id INTEGER, status STRING, \
created_at TIMESTAMP]
TABLE: order_items (181651 rows) [id INTEGER, order_id INTEGER, user_id INTEGER, \
sale_price FLOAT]
TABLE: users (100000 rows) [id INTEGER, first_name STRING, email STRING, \
country STRING, created_at TIMESTAMP]
"""

# The same shape in the house dialect, to pin that this stays untouched.
HOUSE = """\
TABLE: orders  (124,920 rows)
  -- Orders placed by users.
  order_id  INTEGER  ~ e.g. '1', '2'  [Unique identifier for the order.]
  user_id  INTEGER  ~ e.g. '7', '9'  [The user who placed it.]
  status  VARCHAR  ~ e.g. 'Complete'  [Fulfilment state.]
TABLE: order_items  (181,651 rows)
  id  INTEGER  ~ e.g. '1', '2'  [Unique identifier for the line item.]
  order_id  INTEGER  ~ e.g. '1', '2'  [The order it belongs to.]
  user_id  INTEGER  ~ e.g. '7', '9'  [The user who placed it.]
TABLE: users  (100,000 rows)
  id  INTEGER  ~ e.g. '7', '9'  [Unique identifier for the user.]
  email  VARCHAR  ~ e.g. 'a@b.c'  [Contact address.]
"""


class TestParseInlineColumns:
    def test_reads_name_and_type_from_the_bracket_list(self):
        cols = parse_inline_columns(
            "TABLE: orders (124920 rows) [order_id INTEGER, created_at TIMESTAMP]"
        )
        assert cols == [("order_id", "INTEGER"), ("created_at", "TIMESTAMP")]

    def test_house_format_table_line_yields_nothing(self):
        # No bracket, so a caller can apply this unconditionally.
        assert parse_inline_columns("TABLE: orders  (124,920 rows)") == []

    def test_a_parenthesised_type_does_not_invent_a_column(self):
        # A bare comma-split makes "2)" out of DECIMAL(10,2); it is not a column.
        cols = parse_inline_columns("TABLE: t [amount DECIMAL(10,2), name STRING]")
        assert [c for c, _ in cols] == ["amount", "name"]

    def test_the_s3_source_annotation_is_not_a_column_list(self):
        # aughor/connectors/file/s3.py renders `[source: s3://bucket/prefix]`.
        assert parse_inline_columns("TABLE: events  [source: s3://bucket/prefix]") == []

    def test_a_column_with_no_type_still_parses(self):
        assert parse_inline_columns("TABLE: t [id, name STRING]")[0] == ("id", "VARCHAR")


class TestInlineDialectReachesEveryParser:
    def test_parse_schema_tables_reads_it(self):
        tables = parse_schema_tables(INLINE)
        assert tables["orders"] == ["order_id", "user_id", "status", "created_at"]

    def test_rich_schema_has_columns_and_row_counts(self):
        rich = build_rich_schema(INLINE)
        by_name = {t["name"]: t for t in rich["tables"]}
        assert set(by_name) == {
            "distribution_centers", "orders", "order_items", "users",
        }
        assert [c["name"] for c in by_name["orders"]["columns"]] == [
            "order_id", "user_id", "status", "created_at",
        ]
        assert by_name["orders"]["row_count"] == "124920"
        assert by_name["orders"]["columns"][0]["type"] == "INTEGER"

    def test_rich_schema_infers_a_join_it_previously_could_not_see(self):
        rich = build_rich_schema(INLINE)
        assert rich["joins"], "no join inferred — the parser read zero columns"
        assert [(j["t1"], j["c1"], j["t2"], j["c2"]) for j in rich["joins"]] == [
            ("orders", "order_id", "order_items", "order_id"),
        ]

    def test_the_two_dialects_infer_the_same_joins(self):
        # The point of the fix: which dialect the connector happens to emit must
        # not change what Aughor believes about the schema.
        def shape(s):
            return sorted(
                (j["t1"], j["c1"], j["t2"], j["c2"], j["match"])
                for j in build_rich_schema(s)["joins"]
            )
        assert shape(INLINE) == shape(HOUSE)

    def test_the_aggregate_type_guard_gets_its_types(self):
        # Fails open by design, so an empty mapping silently passes every
        # aggregate rather than raising. That is what it used to return here.
        types = col_types_from_schema(INLINE)
        assert types["orders.status"] == "STRING"
        assert types["orders.order_id"] == "INTEGER"

    def test_mermaid_entities_carry_their_attributes(self):
        er = build_mermaid_er(INLINE)
        assert "order_id INTEGER" in er
        assert er.count("{") >= 3, "entities rendered without attribute blocks"


class TestHouseDialectUnchanged:
    def test_columns_types_and_descriptions_still_parse(self):
        rich = build_rich_schema(HOUSE)
        orders = next(t for t in rich["tables"] if t["name"] == "orders")
        assert [c["name"] for c in orders["columns"]] == ["order_id", "user_id", "status"]
        assert orders["row_count"] == "124920"
        assert orders["columns"][0]["description"] == "Unique identifier for the order."

    def test_the_comment_lines_are_still_not_columns(self):
        rich = build_rich_schema(HOUSE)
        orders = next(t for t in rich["tables"] if t["name"] == "orders")
        assert not any(c["name"].startswith("--") for c in orders["columns"])

    def test_join_inference_is_unaffected(self):
        rich = build_rich_schema(HOUSE)
        assert [(j["t1"], j["c1"], j["t2"], j["c2"]) for j in rich["joins"]] == [
            ("orders", "order_id", "order_items", "order_id"),
        ]
