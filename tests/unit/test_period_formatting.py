"""Reader-facing prose wears reader-facing formatting.

Two shipped reports carried 52 and 56 raw warehouse timestamps between them —
`2026-08-01 00:00:00+00:00` — in prose AND in phase titles, alongside unrounded floats:

    "⚠ Period concentration: 2026-08-01 00:00:00+00:00 at 87676.13 vs the 25028.91 baseline"
    phase title: "Cross-Sectional Scan · 2026-08-01 00:00:00+00:00"

`_fmt_period` and `_fmt_compact_num` already existed for exactly this and were reaching only the
key numbers. The one sentence a person actually reads was the one not using them.
"""
from __future__ import annotations

import pytest

from aughor.agent.investigate import _fmt_num_or_raw, _fmt_period


@pytest.mark.parametrize("raw,want", [
    ("2026-08-01 00:00:00+00:00", "Aug 2026"),   # BigQuery's DATE_TRUNC rendering
    ("2023-11-01", "Nov 2023"),
    ("2022-07", "Jul 2022"),
])
def test_a_warehouse_timestamp_becomes_a_month_label(raw, want):
    assert _fmt_period(raw) == want


@pytest.mark.parametrize("raw,want", [("87676.13", "87.7K"), ("25028.91", "25.0K"),
                                      ("1951747", "1.95M")])
def test_a_metric_value_is_scaled_for_prose(raw, want):
    assert _fmt_num_or_raw(raw) == want


def test_anything_unrecognised_passes_through_untouched():
    """Fail-open: a label that is not a period, and a value that is not a number, must survive
    verbatim rather than becoming an exception or an empty cell."""
    assert _fmt_period("not a date") == "not a date"
    assert _fmt_period("") == ""
    assert _fmt_num_or_raw("abc") == "abc"
    assert _fmt_num_or_raw(None) == "None"


def test_a_month_out_of_range_is_not_mangled_into_a_label():
    """`2022-13` is not December-adjacent — it is not a month at all."""
    assert _fmt_period("2022-13") == "2022-13"
