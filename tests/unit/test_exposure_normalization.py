"""A share of the total is not a finding until you know the share of the population.

A cross-sectional scan ranks groups by an additive total and reports each one's `pct_of_total`.
That number alone cannot answer "where are we losing money", because on almost any additive
metric the largest group leads BY BEING LARGEST. The shipped report headlined

    "Men department accounts for over half of total cost, indicating cost concentration"

on 53.2% — and Men is 50.3% of the rows. The finding was a restatement of the department's size,
dressed as a diagnosis, and it pointed at the most productive part of the business.

The scan already selects a per-group count, so the exposure base needs no extra query — only the
division nobody was doing. The verdict is shown to the narrator BEFORE it writes (prevention) and
stamped onto the finding (backstop), the same two-sided treatment the significance verdict gets.
"""
from __future__ import annotations

from aughor.agent.investigate import _concentration_note

# The real rows, from bigquery-public-data.thelook_ecommerce.inventory_items.
THELOOK_DEPT = (["product_department", "metric_total", "n"],
                [["Men", "7485064.945264877", "246775"],
                 ["Women", "6584682.566935055", "244003"]])


def test_the_shipped_finding_is_named_proportional():
    note = _concentration_note(*THELOOK_DEPT)
    assert note and "PROPORTIONAL" in note
    assert "53.2% of the metric" in note and "50.3% of the rows" in note
    # The reader must be told what to DO with that, not just handed two numbers.
    assert "largest group" in note


def test_a_real_concentration_is_still_called_out():
    """The guard must not simply always say 'proportional' — then it would suppress the true
    findings along with the false ones."""
    note = _concentration_note(["region", "metric_total", "n"],
                               [["APAC", "900000", "10000"], ["EMEA", "100000", "90000"]])
    assert note and "CONCENTRATED" in note and "9.00×" in note


def test_a_leader_carrying_less_than_its_size_is_named_too():
    note = _concentration_note(["region", "metric_total", "n"],
                               [["Big", "520000", "900000"], ["Small", "480000", "100000"]])
    assert note and "UNDER-REPRESENTED" in note


def test_it_declines_when_the_shape_cannot_support_the_claim():
    """A wrong exposure verdict is worse than none: it would license a reader to dismiss a real
    finding as 'just size'. No count column, one row, or unusable numbers ⇒ silence."""
    assert _concentration_note(["period", "metric_total"], [["Jan", "5"], ["Feb", "6"]]) is None
    assert _concentration_note(["g", "m", "n"], [["only", "5", "5"]]) is None
    assert _concentration_note([], []) is None
    assert _concentration_note(["g", "m", "n"], [["a", "NULL", "0"], ["b", "NULL", "0"]]) is None


def test_the_connector_null_string_is_not_read_as_a_number():
    """The connector renders SQL NULL as the literal string 'NULL' — a bare float() would raise
    and a lenient parse would count it as zero exposure."""
    assert _concentration_note(["g", "m", "n"],
                               [["a", "100", "NULL"], ["b", "10", "NULL"]]) is None
