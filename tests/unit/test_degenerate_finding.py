"""Degenerate ("no data") finding guard — explorer drops empty Phase-8 results so they
never become Briefing findings or broken monitors. See agent.is_degenerate_result and
the frontend isDegenerateFinding mirror in web/components/BriefingPanel.tsx.

Origin: a user created a monitor from a finding whose query returned a single all-NULL
row (a broken cross-dataset join) → "The query returned no data: 0 customers were found"
→ the monitor fired "No condition met" forever.
"""
from aughor.explorer.verify import is_degenerate_result, has_fabricated_dimension, clamp_novelty


def test_all_null_single_row_is_degenerate():
    assert is_degenerate_result([(None, None, None)]) is True
    assert is_degenerate_result([{"a": None, "b": None}]) is True


def test_all_zero_is_degenerate():
    # "No zero on cards" (f224d2e): an all-zero numeric result is a query/grain artifact
    # (broken join, ROUND-destroyed weight), not a finding — dropped. This supersedes the
    # older "a 0 COUNT is a real finding" stance.
    assert is_degenerate_result([(0,)]) is True
    assert is_degenerate_result([("EU", 0, 0.0)]) is True


def test_mixed_zero_and_nonzero_survives():
    # Only a FLAT-zero metric is dropped; a column with some zero and some non-zero
    # values is real signal and survives.
    assert is_degenerate_result([("EU", 0), ("US", 1200)]) is False


def test_rate_pinned_at_ceiling_is_degenerate():
    # A bounded rate at its MAX across every segment is the same artifact as all-zero,
    # one boundary up — a broken denominator (cart→order conversion counting only
    # converted carts → "100% conversion across all traffic sources", impossible).
    conv = [("Google", "Mobile", "1.0"), ("TikTok", "Mobile", "1.0"), ("Email", "Desktop", "1.0")]
    assert is_degenerate_result(conv, "cart-to-order conversion rate of exactly 1.0 (100%)",
                                 "SELECT traffic_source, device, ... AS conversion_rate") is True
    pct = [("Google", "100.0"), ("Meta", "100.0")]
    assert is_degenerate_result(pct, "conversion rate 100% in every segment", "AS conversion_pct") is True


def test_rate_not_at_ceiling_survives():
    # A real, varying rate is signal; payment success ~89% is below the ceiling → survives.
    varying = [("Google", "0.15"), ("Email", "0.28"), ("TikTok", "0.21")]
    assert is_degenerate_result(varying, "conversion varies by channel", "AS conversion_rate") is False
    success = [("CC", "0.8923"), ("PayPal", "0.8926"), ("ApplePay", "0.8935")]
    assert is_degenerate_result(success, "payment success rate ~89%", "AS success_rate") is False


def test_constant_one_without_rate_context_survives():
    # A count-of-1 or an always-true flag is legitimately constant at 1 — NOT a saturated
    # rate. Without a rate signal in the SQL/text it must survive (no false positive).
    counts = [("cust1", "1"), ("cust2", "1"), ("cust3", "1")]
    assert is_degenerate_result(counts, "each customer placed exactly 1 order",
                                 "SELECT customer_id, COUNT(*) AS order_count") is False


def test_single_row_at_ceiling_survives():
    # The ceiling rule needs ≥2 rows ("all segments") — a single 100% could be a real
    # small-sample result, so it isn't dropped on shape alone.
    assert is_degenerate_result([("x", "1.0")], "conversion rate", "AS conversion_rate") is False


def test_real_rows_not_degenerate():
    assert is_degenerate_result([("EU", 1200, 4.5)]) is False
    assert is_degenerate_result([{"region": "EU", "rev": 1200}]) is False


# ── Profile sane-range applied to findings ───────────────────────────────────────
# The profile DECLARES each metric's range, which tells a bounded conversion (0-1, so
# 1.41 is impossible) from an unbounded ROAS (0-∞, so 2.3 is fine) — a distinction the
# keyword guess can't make. Origin: a "conversion 1.4138 by channel" card leaked.

from types import SimpleNamespace as _NS
from aughor.profile.validate import profile_metric_ranges as _ranges

_PROFILE = _NS(north_star_metrics=[
    _NS(name="Cart-to-Order Conversion Rate", unit_or_range="ratio 0-1"),
    _NS(name="Channel-Level Marketing ROAS", unit_or_range="ratio 0-∞"),
    _NS(name="Gross Margin %", unit_or_range="percent 0-100"),
])
_R = _ranges(_PROFILE)


class TestProfileRange:
    def test_conversion_above_one_is_dropped(self):
        rows = [("ad_impression", "1.4138"), ("organic", "1.21"), ("email", "0.98")]
        assert is_degenerate_result(rows, "cart-to-order conversion rate: ad_impression leads at 1.4138",
                                     "AS conversion_rate", _R) is True

    def test_conversion_at_ceiling_is_dropped(self):
        rows = [("a", "1.0"), ("b", "1.0")]
        assert is_degenerate_result(rows, "cart-to-order conversion rate of 1.0", "AS conversion_rate", _R) is True

    def test_unbounded_roas_above_one_survives(self):
        rows = [("TikTok", "2.3"), ("Meta", "1.1"), ("Google", "3.4")]
        assert is_degenerate_result(rows, "channel-level marketing ROAS: TikTok at 2.3", "AS roas", _R) is False

    def test_unbounded_roas_at_one_survives(self):
        # an OPEN metric must NOT be ceiling-dropped (1.0 is a real ROAS)
        rows = [("a", "1.0"), ("b", "1.0")]
        assert is_degenerate_result(rows, "marketing ROAS is 1.0 across channels", "AS roas", _R) is False

    def test_margin_in_range_survives(self):
        rows = [("w1", "64.2"), ("w2", "64.3")]
        assert is_degenerate_result(rows, "gross margin percent trend", "AS gross_margin_pct", _R) is False

    def test_margin_above_100_is_dropped(self):
        rows = [("w1", "140.0"), ("w2", "64.0")]
        assert is_degenerate_result(rows, "gross margin percent", "AS gross_margin_pct", _R) is True

    def test_no_profile_match_falls_back_to_keyword_ceiling(self):
        rows = [("a", "1.0"), ("b", "1.0")]
        assert is_degenerate_result(rows, "some rate is 1.0 everywhere", "AS some_rate", _R) is True


def test_no_data_interpretation_text_is_degenerate():
    rows = [("EU", 5)]  # rows look fine, but the interpreter said there's no data
    assert is_degenerate_result(rows, "The query returned no data: 0 customers were found") is True
    assert is_degenerate_result(rows, "resulting in NULL values for all review coverage metrics") is True
    assert is_degenerate_result([], "no matching records in the window") is True


def test_normal_finding_text_survives():
    rows = [("EU", 5)]
    assert is_degenerate_result(rows, "Revenue grew 12% QoQ driven by the EU cohort") is False
    # "found" alone (without the 0-count phrasing) must not trip the guard
    assert is_degenerate_result(rows, "We found a strong correlation between X and Y") is False


def test_empty_rows_and_no_text_is_degenerate():
    assert is_degenerate_result([]) is False        # empty handled by the caller's len()==0 skip
    assert is_degenerate_result([], "") is False


# ── Fabricated-dimension guard ────────────────────────────────────────────────
# Origin: an Evidence card claimed "the 'Unknown' acquisition channel, the only
# channel represented…" — the SQL hardcoded `'Unknown' AS signup_source ... GROUP
# BY signup_source` because the real column doesn't exist. A vacuous single-group
# "breakdown" the narrator dressed up as a real category.

def test_constant_literal_grouping_is_fabricated():
    sql = ("SELECT 'Unknown' AS signup_source, SUM(oi.line_total) AS total_revenue "
           "FROM ecommerce.customers c JOIN ecommerce.orders o ON c.customer_id = o.customer_id "
           "GROUP BY signup_source ORDER BY total_revenue DESC")
    assert has_fabricated_dimension(sql) is True


def test_group_by_raw_literal_is_fabricated():
    assert has_fabricated_dimension("SELECT SUM(x) FROM t GROUP BY 'EUR'") is True


def test_real_breakdown_not_fabricated():
    assert has_fabricated_dimension("SELECT category, SUM(x) FROM t GROUP BY category") is False


def test_literal_alongside_real_dimension_not_fabricated():
    # 'Unknown' is fabricated but `region` is a real grouping dimension → legit breakdown.
    sql = "SELECT 'Unknown' AS channel, region, SUM(x) FROM t GROUP BY channel, region"
    assert has_fabricated_dimension(sql) is False


def test_case_derived_dimension_not_fabricated():
    sql = "SELECT CASE WHEN x > 0 THEN 'hi' ELSE 'lo' END AS bucket, SUM(y) FROM t GROUP BY bucket"
    assert has_fabricated_dimension(sql) is False


def test_labeled_scalar_no_group_by_not_fabricated():
    assert has_fabricated_dimension("SELECT 'total' AS label, SUM(x) FROM t") is False


# ── Novelty clamp ─────────────────────────────────────────────────────────────
# Origin: the same card showed NOVELTY 77568/10 and CONFIDENCE 95% — the LLM
# echoed total_revenue (77568) into the 1-5 novelty score, which pins confidence
# (0.4 + novelty*0.1, capped) and lets a junk finding own the headline.

def test_clamp_novelty_bounds_runaway_magnitude():
    assert clamp_novelty(77568) == 5
    assert clamp_novelty(0) == 1
    assert clamp_novelty(-4) == 1


def test_clamp_novelty_passes_valid_scores():
    assert clamp_novelty(3) == 3
    assert clamp_novelty(5) == 5


def test_clamp_novelty_handles_garbage():
    assert clamp_novelty(None) == 3
    assert clamp_novelty("x") == 3
