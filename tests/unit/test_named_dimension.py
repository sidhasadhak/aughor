"""The breakdown the question named is the breakdown the report gives.

Live, from an exported deep report. "Give me route wise number of flights" produced a
report whose sections were:

    Market-wise Flight Count Ranking …
    Origin-wise Flight Count Ranking …
    Destination-wise Flight Count Ranking …
    Haul-wise Flight Count Ranking …

Every dimension except the one asked for. The intake model chooses the drill-down
dimensions, and it simply dropped `route`. A question that says which cut it wants is
not the model's to overrule.

The same report framed each section as a weakness scan ("does not represent a
performance deficit") for a question that asked for a count — see the framing tests.
"""
from __future__ import annotations

import pytest

from aughor.agent.investigate import _norm_col, _question_named_dimensions

_AIRLINE = """\
TABLE: main.flights  (1981 rows)
  flight_id  BIGINT
  route_id  VARCHAR
  origin  VARCHAR
  destination  VARCHAR
  market  VARCHAR
  haul  VARCHAR
  carrier  VARCHAR
TABLE: main.airports  (312 rows)
  airport_code  VARCHAR
  city  VARCHAR
"""


def test_the_named_breakdown_is_found():
    assert _question_named_dimensions(
        "Give me route wise number of flights", _AIRLINE, "main.flights",
    ) == ["main.flights.route_id"]


def test_several_named_dimensions_all_come_back():
    got = _question_named_dimensions(
        "volume by origin and destination", _AIRLINE, "main.flights")
    assert got == ["main.flights.origin", "main.flights.destination"]


def test_a_table_s_own_key_is_not_a_dimension():
    """`flight_id` on `flights` is the table's key — grouping by it yields one row per
    record, so the noun "flights" naming it is the SUBJECT, never the breakdown. The
    `_id` suffix cannot be the test: `route_id` on the same table is a real dimension."""
    assert _question_named_dimensions(
        "how many flights are there", _AIRLINE, "main.flights") == []


@pytest.mark.parametrize("q", [
    "give me the total revenue",          # names nothing in this schema
    "why did volume drop",                # a cause question names no cut
])
def test_a_question_naming_no_column_adds_nothing(q):
    assert _question_named_dimensions(q, _AIRLINE, "main.flights") == []


def test_the_metric_s_own_table_leads():
    """Two tables can share a column name; the grain being counted wins."""
    schema = _AIRLINE + "TABLE: main.sales\n  city  VARCHAR\n  amount  DOUBLE\n"
    got = _question_named_dimensions("revenue by city", schema, "main.sales")
    assert got[0] == "main.sales.city"


def test_the_word_and_the_column_meet_through_case_separators_and_suffix():
    assert _norm_col("route") == _norm_col("route_id") == _norm_col("Route IDs")
    assert _norm_col("order_items") == _norm_col("Order Items")


def test_a_missing_schema_is_not_an_error():
    assert _question_named_dimensions("route wise flights", "", "t") == []
    assert _question_named_dimensions("", _AIRLINE, "t") == []


# ── the pin has to survive the scan's own ranking ────────────────────────────
# Putting the named dimension first in the intake was not enough. The cross-sectional
# scan re-sorts by a priority heuristic — customer → channel → category → geo → other —
# and `route_id` matches none of those keywords, so it sank to the bottom and the
# per-phase cap dropped it. The report ranked market, origin, destination and haul, and
# the narrator explained the missing route breakdown away as a data gap.

_DIMS = ["main.flights.route_id", "main.flights.market", "main.flights.origin",
         "main.flights.destination", "main.flights.haul"]


def test_a_named_dimension_outranks_the_heuristic():
    from aughor.agent.investigate import _prioritize_dimensions

    got = _prioritize_dimensions(_DIMS, pinned=["main.flights.route_id"])

    assert got[0] == "main.flights.route_id"


def test_it_survives_a_cap_that_would_otherwise_cut_it():
    """The cap is the mechanism that actually lost it — ordering only matters because
    the list is then truncated."""
    from aughor.agent.investigate import _prioritize_dimensions

    top2 = _prioritize_dimensions(_DIMS, pinned=["main.flights.route_id"])[:2]

    assert "main.flights.route_id" in top2


def test_without_a_pin_the_heuristic_is_untouched():
    """The ranking is right for a scan that has no stated cut to honour; the pin must
    not become a general reordering."""
    from aughor.agent.investigate import _prioritize_dimensions
    assert _prioritize_dimensions(_DIMS) == _prioritize_dimensions(_DIMS, pinned=[])


def test_a_causal_dimension_still_floats_on_a_why_scan():
    """`causal_first` exists so the causal cut survives the same cap. A pin outranks it
    — the question was explicit — but with no pin it must still lead."""
    from aughor.agent.investigate import _prioritize_dimensions

    dims = ["main.orders.region", "main.orders.return_reason"]
    assert _prioritize_dimensions(dims, causal_first=True)[0] == "main.orders.return_reason"


def test_the_spec_carries_the_named_dimensions_for_the_scan_to_read():
    from aughor.agent.prompts_investigate import IntakeOutput
    assert IntakeOutput.model_fields["named_dimensions"].default_factory() == []
