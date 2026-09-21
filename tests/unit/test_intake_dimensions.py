"""JD-2's surviving defect: `dimensions` was validated against the schema nowhere.

`metric_table` had a validator and `dimensions` did not. JD-2 measured 1,449 of 1,449 real
dimensions as names the model had been shown, so this catches a rare failure — which is why it
fails OPEN wherever it could only be wrong: a false alarm buys a paid LLM retry.
"""
from aughor.agent.investigate import _validate_intake_dimensions

SCHEMA = (
    "TABLE: thelook.order_items\n"
    "  id  INT64\n"
    "  order_date  DATE\n"
    "  status  STRING\n"
    "TABLE: thelook.users\n"
    "  country  STRING\n"
)


def test_a_dimension_that_names_no_column_is_an_error():
    err = _validate_intake_dimensions(["status", "region"], SCHEMA)
    assert err and "'region'" in err and "'status'" not in err


def test_real_columns_pass_including_qualified_and_cross_table_ones():
    """A dimension on a joined table is legitimate, so the check is against every column in the
    schema, not only the metric table's."""
    assert _validate_intake_dimensions(["status", "order_items.order_date", "country"],
                                       SCHEMA) is None


def test_matching_is_by_column_name_not_substring():
    """`order` is a substring of `order_date`. A substring test would pass it — the error in the
    direction that makes a bad spec look valid."""
    assert "'order'" in (_validate_intake_dimensions(["order"], SCHEMA) or "")


def test_an_expression_is_not_flagged():
    """Not a plain identifier, so this check cannot judge it — and guessing wrong costs a paid
    retry. Fails open."""
    assert _validate_intake_dimensions(["DATE_TRUNC('month', order_date)"], SCHEMA) is None


def test_a_schema_with_no_parseable_columns_does_not_fire():
    """If the parser found nothing, every dimension would look unknown. Fails open rather than
    sending every question to a retry."""
    assert _validate_intake_dimensions(["status"], "no table headers here") is None
    assert _validate_intake_dimensions([], SCHEMA) is None
    assert _validate_intake_dimensions(["status"], "") is None


def test_the_sample_block_is_not_read_as_columns():
    """`_typed_columns` stops at a table's sample rows; a value there must not count as a
    column, or a dimension named after a data value would pass."""
    schema = SCHEMA + "  Sample (2 rows)\n  shipped  2024-01-01\n"
    assert "'shipped'" in (_validate_intake_dimensions(["shipped"], schema) or "")
