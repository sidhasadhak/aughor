"""`list_tables` is a manifest, not the schema text.

Measured 2026-10-15 on LuxExperience (33 tables, 262 columns): the schema text the tool used to
return is 82,232 characters — table descriptions, grain notes, sample values and a note per
column — and the analyst's single `list_tables` call on 99201af8 outweighed the rest of its
turn. The manifest (name, row count, columns with types) is 5,346 characters; `describe_table`
returns a table's full block for the one or two tables the model goes on to query.
"""
from aughor.db.schema_render import schema_block, schema_manifest

LUX_LIKE = """\
TABLE: brand_collaborations  (62 rows)
  -- Tracks luxury fashion brand collaborations and exclusive launches on retail platforms.
  -- Grain: One row per brand collaboration (collab_id).
  collab_id  text  ~ e.g. <data>'CL0000', 'CL0001'</data>  [Unique identifier for the collaboration.]
  brand  text  ~ e.g. <data>'Valentino', 'Saint Laurent'</data>  [Name of the luxury fashion brand.]
  launch_date  date  ~ e.g. <data>'2020-12-15', '2021-03-22'</data>  [Date the collaboration was launched.]
  est_gmv_eur  numeric  ~ e.g. <data>'125000.00'</data>  [Estimated GMV.]

TABLE: brands  (70 rows)
  brand_id  text
  tier  text  ~ e.g. <data>'luxury', 'ultra'</data>  [Positioning tier. | Values: luxury, ultra, contemporary]

DETECTED JOIN PATHS:
  brand_collaborations.brand -> brands.brand
"""


def test_the_manifest_carries_names_types_and_counts_and_nothing_else():
    m = schema_manifest(LUX_LIKE)
    assert m == ("brand_collaborations (62 rows): collab_id text, brand text, launch_date date, est_gmv_eur numeric\n"
                 "brands (70 rows): brand_id text, tier text")
    assert "e.g." not in m and "Grain" not in m and "Values:" not in m
    assert len(m) < len(LUX_LIKE) / 4


def test_the_detail_is_still_a_describe_table_away():
    block = schema_block(LUX_LIKE, "brands")
    assert "Values: luxury, ultra, contemporary" in block and block.startswith("TABLE: brands")


def test_an_unparseable_text_is_no_manifest():
    assert schema_manifest("some prose that names no table") == ""
    assert schema_manifest("") == ""
