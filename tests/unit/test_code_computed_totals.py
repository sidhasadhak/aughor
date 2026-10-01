"""Item 6 — code computes totals; a figure that fails the trace check is withheld.

Measured 2026-09-30 on the Agent answer to "top 10 categories by revenue, last 6 months"
(theLook): the writer said the ten made 1,299,882.88 together; its own ten rows sum to
1,299,928.70. The trace check named the figure, the one repair kept it, and it shipped with
only a clause in the confidence note. A correct total could not have passed either: no row
holds it, and the check credits a difference of two values, not a sum of ten.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.report_checks import check_grounding, reader_disclosure, withhold_untraced
from aughor.tools.postproc import column_totals

Q2_SQL = ("SELECT p.category, SUM(oi.sale_price) AS total_revenue, "
          "SUM(oi.sale_price) / COUNT(DISTINCT oi.order_id) AS average_order_value "
          "FROM `order_items` AS oi JOIN `products` AS p ON oi.product_id = p.id "
          "WHERE oi.created_at >= '2026-03-01' AND oi.created_at < '2026-09-01' "
          "AND oi.status <> 'Cancelled' GROUP BY 1 ORDER BY total_revenue DESC LIMIT 10")
Q2_COLS = ["category", "total_revenue", "average_order_value"]
Q2_ROWS = [
    ["Outerwear & Coats", "233889.7898349762", "152.27199859047928"],
    ["Jeans", "220935.50022029877", "100.7917428012312"],
    ["Sweaters", "148217.66984558105", "76.59827898996437"],
    ["Suits & Sport Coats", "114486.4700126648", "125.94771178510979"],
    ["Swim", "114013.31015872955", "57.757502613338175"],
    ["Fashion Hoodies & Sweatshirts", "110644.90009593964", "54.55862923862901"],
    ["Sleep & Lounge", "99955.62027454376", "50.66174367691017"],
    ["Shorts", "93145.1302857399", "47.11438051883657"],
    ["Tops & Tees", "84580.13026165962", "42.22672504326491"],
    ["Active", "80060.18006968498", "50.47930647521121"],
]


# ── Code computes the total ───────────────────────────────────────────────────────────

def test_a_sum_is_totalled_and_an_average_never_is():
    assert column_totals(Q2_SQL, Q2_COLS, Q2_ROWS, 10) == [("total_revenue", "1299928.70")]


def test_no_total_unless_every_row_of_the_result_is_in_hand():
    assert column_totals(Q2_SQL, Q2_COLS, Q2_ROWS[:5], 10) == []     # a first page is not the whole
    assert column_totals(Q2_SQL, Q2_COLS, Q2_ROWS[:1], 1) == []      # one row is its own total


def test_what_does_not_add_across_rows_is_not_totalled():
    rows = [["a", "10", "4"], ["b", "20", "7"]]
    distinct = "SELECT c, SUM(x) AS revenue, COUNT(DISTINCT customer_id) AS customers FROM t GROUP BY c"
    assert column_totals(distinct, ["c", "revenue", "customers"], rows) == [("revenue", "30")]
    window = "SELECT c, SUM(SUM(x)) OVER (ORDER BY c) AS revenue FROM t GROUP BY c"
    assert column_totals(window, ["c", "revenue"], [r[:2] for r in rows]) == []
    rollup = "SELECT c, SUM(x) AS revenue FROM t GROUP BY ROLLUP (c)"
    assert column_totals(rollup, ["c", "revenue"], [r[:2] for r in rows]) == []


def test_a_sum_named_through_a_cte_is_still_a_sum():
    sql = ("WITH r AS (SELECT c, ROUND(SUM(x), 2) AS revenue, COUNT(*) AS orders FROM t GROUP BY c) "
           "SELECT c, revenue, orders FROM r ORDER BY revenue DESC")
    rows = [["a", "10.5", "3"], ["b", "20.25", "4"]]
    assert column_totals(sql, ["c", "revenue", "orders"], rows) == [("revenue", "30.75"), ("orders", "7")]


def test_the_writer_evidence_carries_the_total():
    from aughor.agent.investigate import _one_phase_evidence
    finding = {"sql": Q2_SQL, "columns": Q2_COLS, "rows": Q2_ROWS, "row_count": 10, "error": "",
               "stat_note": "", "trust_caveat": "", "interpretation": ""}
    block = _one_phase_evidence({"phase_name": "Top categories", "findings": [finding]})
    assert ("TOTAL over all 10 rows of this result, computed by code — quote it, never add rows "
            "yourself: total_revenue 1299928.70") in block


# ── The trace check finds the right total and refuses the wrong one ───────────────────

def _evidence() -> str:
    lines = ["category | total_revenue | average_order_value"] + [" | ".join(r) for r in Q2_ROWS]
    return "\n".join(lines + ["TOTAL over all 10 rows: total_revenue 1299928.70", "LIMIT 100"])


def test_the_code_total_quoted_passes_and_a_hand_added_one_does_not():
    ev = _evidence()
    assert check_grounding("The ten made $1,299,928.70 together.", ev) == []
    v = check_grounding("The ten made $1,299,882.88 together.", ev)
    assert v and v[0].figures == ("1,299,882.88",)


def test_a_figure_written_to_cents_matches_its_value():
    assert check_grounding("East made 406.10 in March.", "region | revenue\nEast | 406.1") == []


def test_a_percent_derivation_licenses_only_a_percentage():
    """The evidence holds 100 (a LIMIT) and the total: a figure within 1% of the total is a
    "share of 100" only if it is written as a percentage."""
    ev = _evidence()
    assert check_grounding("Outerwear & Coats took 18.0% of the ten.", ev) == []     # 233,889.79 / 1,299,928.70
    assert check_grounding("The ten made 1,300,500.00 together.", ev)


# ── What still fails after the repair is withheld, and said ───────────────────────────

def _draft():
    return SimpleNamespace(
        headline="Top 10 categories by revenue (March–August 2026)",
        executive_summary=("The top 10 categories generated a combined revenue of $1,299,882.88. "
                           "Outerwear & Coats led with $233,889.79."),
        closing_summary="Apparel dominates.", confidence="MEDIUM", confidence_justification="")


def test_the_sentence_stating_an_untraced_figure_is_withheld_and_the_answer_says_so():
    synth = _draft()
    v = check_grounding(synth.executive_summary, _evidence())
    assert withhold_untraced(synth, v, "Which 10 categories?") == ["1,299,882.88"]
    assert "1,299,882.88" not in synth.executive_summary
    assert synth.executive_summary.startswith("Outerwear & Coats led with $233,889.79.")
    assert synth.executive_summary.endswith(
        "A figure in this answer could not be traced to the query results, so the sentence "
        "stating it was withheld.")
    assert synth.headline == "Top 10 categories by revenue (March–August 2026)"
    assert "1,299,882.88" not in reader_disclosure(v) and "withheld" in reader_disclosure(v)


def test_a_headline_stating_one_is_replaced_by_the_question():
    synth = _draft()
    synth.headline = "Top 10 categories made $1,299,882.88"
    v = check_grounding(synth.headline, _evidence())
    withhold_untraced(synth, v, "Which 10 categories?")
    assert synth.headline == "Which 10 categories?"
    assert "the 2 sentences stating it were withheld" in synth.executive_summary


def test_nothing_to_withhold_leaves_the_answer_as_written():
    synth = _draft()
    assert withhold_untraced(synth, [], "q") == []
    assert withhold_untraced(synth, ["#12: a plain string violation"], "q") == []
    assert synth.executive_summary == _draft().executive_summary


# ── A small figure written with decimals is a measurement too (2026-10-01) ────────────

CENTRES = "centre | total_days\nNY/NJ | 4.0378\nLos Angeles | 4.0048\nNew Orleans | 3.9312"


def test_a_small_decimal_is_checked_and_a_small_whole_number_is_not():
    """Q4's headline gave "approximately 3.98 days across all distribution centers" — the
    model's own average of the centre averages — and #36 never looked, because it was < 10."""
    v = check_grounding("Orders take about 3.98 days across all centres.", CENTRES)
    assert v and v[0].figures == ("3.98",)
    assert check_grounding("NY/NJ is slowest at 4.04 days.", CENTRES) == []      # quoted, rounded
    assert check_grounding("The 3 slowest centres are in the east.", CENTRES) == []


def test_a_rate_a_ratio_and_a_threshold_are_read_as_what_they_are():
    rates = "cohort | repeat_rate\n2025-01 | 0.06946\n2025-12 | 0.12068"
    assert check_grounding("January's repeat rate was 6.9%.", rates) == []        # fraction → percent
    assert check_grounding("December's rate is 1.74x January's.", rates) == []    # b / a, as a multiple
    assert check_grounding("The months differ (p < 0.05).", rates) == []           # a convention
