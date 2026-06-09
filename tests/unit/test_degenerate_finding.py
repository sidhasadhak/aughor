"""Degenerate ("no data") finding guard — explorer drops empty Phase-8 results so they
never become Briefing findings or broken monitors. See agent._is_degenerate_result and
the frontend isDegenerateFinding mirror in web/components/BriefingPanel.tsx.

Origin: a user created a monitor from a finding whose query returned a single all-NULL
row (a broken cross-dataset join) → "The query returned no data: 0 customers were found"
→ the monitor fired "No condition met" forever.
"""
from aughor.explorer.agent import _is_degenerate_result, _has_fabricated_dimension, _clamp_novelty


def test_all_null_single_row_is_degenerate():
    assert _is_degenerate_result([(None, None, None)]) is True
    assert _is_degenerate_result([{"a": None, "b": None}]) is True


def test_zero_count_is_not_degenerate():
    # COUNT(...) = 0 is a REAL finding (0 ≠ NULL) and must survive.
    assert _is_degenerate_result([(0,)]) is False
    assert _is_degenerate_result([("EU", 0, 0.0)]) is False


def test_real_rows_not_degenerate():
    assert _is_degenerate_result([("EU", 1200, 4.5)]) is False
    assert _is_degenerate_result([{"region": "EU", "rev": 1200}]) is False


def test_no_data_interpretation_text_is_degenerate():
    rows = [("EU", 5)]  # rows look fine, but the interpreter said there's no data
    assert _is_degenerate_result(rows, "The query returned no data: 0 customers were found") is True
    assert _is_degenerate_result(rows, "resulting in NULL values for all review coverage metrics") is True
    assert _is_degenerate_result([], "no matching records in the window") is True


def test_normal_finding_text_survives():
    rows = [("EU", 5)]
    assert _is_degenerate_result(rows, "Revenue grew 12% QoQ driven by the EU cohort") is False
    # "found" alone (without the 0-count phrasing) must not trip the guard
    assert _is_degenerate_result(rows, "We found a strong correlation between X and Y") is False


def test_empty_rows_and_no_text_is_degenerate():
    assert _is_degenerate_result([]) is False        # empty handled by the caller's len()==0 skip
    assert _is_degenerate_result([], "") is False


# ── Fabricated-dimension guard ────────────────────────────────────────────────
# Origin: an Evidence card claimed "the 'Unknown' acquisition channel, the only
# channel represented…" — the SQL hardcoded `'Unknown' AS signup_source ... GROUP
# BY signup_source` because the real column doesn't exist. A vacuous single-group
# "breakdown" the narrator dressed up as a real category.

def test_constant_literal_grouping_is_fabricated():
    sql = ("SELECT 'Unknown' AS signup_source, SUM(oi.line_total) AS total_revenue "
           "FROM ecommerce.customers c JOIN ecommerce.orders o ON c.customer_id = o.customer_id "
           "GROUP BY signup_source ORDER BY total_revenue DESC")
    assert _has_fabricated_dimension(sql) is True


def test_group_by_raw_literal_is_fabricated():
    assert _has_fabricated_dimension("SELECT SUM(x) FROM t GROUP BY 'EUR'") is True


def test_real_breakdown_not_fabricated():
    assert _has_fabricated_dimension("SELECT category, SUM(x) FROM t GROUP BY category") is False


def test_literal_alongside_real_dimension_not_fabricated():
    # 'Unknown' is fabricated but `region` is a real grouping dimension → legit breakdown.
    sql = "SELECT 'Unknown' AS channel, region, SUM(x) FROM t GROUP BY channel, region"
    assert _has_fabricated_dimension(sql) is False


def test_case_derived_dimension_not_fabricated():
    sql = "SELECT CASE WHEN x > 0 THEN 'hi' ELSE 'lo' END AS bucket, SUM(y) FROM t GROUP BY bucket"
    assert _has_fabricated_dimension(sql) is False


def test_labeled_scalar_no_group_by_not_fabricated():
    assert _has_fabricated_dimension("SELECT 'total' AS label, SUM(x) FROM t") is False


# ── Novelty clamp ─────────────────────────────────────────────────────────────
# Origin: the same card showed NOVELTY 77568/10 and CONFIDENCE 95% — the LLM
# echoed total_revenue (77568) into the 1-5 novelty score, which pins confidence
# (0.4 + novelty*0.1, capped) and lets a junk finding own the headline.

def test_clamp_novelty_bounds_runaway_magnitude():
    assert _clamp_novelty(77568) == 5
    assert _clamp_novelty(0) == 1
    assert _clamp_novelty(-4) == 1


def test_clamp_novelty_passes_valid_scores():
    assert _clamp_novelty(3) == 3
    assert _clamp_novelty(5) == 5


def test_clamp_novelty_handles_garbage():
    assert _clamp_novelty(None) == 3
    assert _clamp_novelty("x") == 3
