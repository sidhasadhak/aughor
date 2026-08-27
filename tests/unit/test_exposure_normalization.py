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


# ── where the check must stay SILENT (both regressions, found in shipped reports) ──────

def test_a_time_bucket_is_not_a_group_with_exposure():
    """Shipped, and actively harmful. The temporal phase reported "2026-08 at 87676.13 vs the
    25028.91 baseline — a 100th percentile anomaly", and directly beneath it this check said
    "2026-08 holds 8.3% of the metric and 7.9% of the rows — PROPORTIONAL — 2026-08 leads because
    it is the largest group". Every month holds roughly its share of the rows by construction, so
    the verdict is vacuous — and a guard that argues with a correct anomaly detection is worse
    than no guard."""
    assert _concentration_note(
        ["period", "metric_value", "n"],
        [["2026-08-01 00:00:00+00:00", "87676.13", "14392"],
         ["2026-07-01 00:00:00+00:00", "25028.91", "14100"]]) is None
    # by column name alone, even when the values are opaque
    assert _concentration_note(["month", "m", "n"], [["A", "9", "1"], ["B", "1", "9"]]) is None
    assert _concentration_note(["order_date", "m", "n"], [["A", "9", "1"], ["B", "1", "9"]]) is None


def test_a_metric_that_lives_in_one_group_by_definition_is_not_concentration():
    """Also shipped: "Returned holds 100.0% of the metric and 9.7% of the rows — CONCENTRATED —
    10.32×". The metric IS refunded sales, so grouping it by order status puts 100% in 'Returned'
    because that is what the metric MEANS. Reporting a definitional split as a 10x finding is noise
    that teaches a reader to skip the real ones."""
    assert _concentration_note(
        ["status", "metric_total", "n"],
        [["Returned", "1055898", "17605"], ["Complete", "0", "31284"],
         ["Shipped", "0", "37062"], ["Cancelled", "0", "18719"]]) is None


def test_suppressing_those_two_did_not_silence_the_real_ones():
    """The point of the guard survives both suppressions."""
    real = _concentration_note(["region", "metric_total", "n"],
                               [["APAC", "900000", "10000"], ["EMEA", "100000", "90000"]])
    assert real and "CONCENTRATED" in real
    men = _concentration_note(*THELOOK_DEPT)
    assert men and "PROPORTIONAL" in men
