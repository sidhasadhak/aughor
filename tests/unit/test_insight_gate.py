"""Pre-emission insight verification gate — regression tests built from the exact
nonsense the BeautyCommerce runs leaked (and the good insights that must survive).

The gate treats a generated finding as untrusted until it passes a deterministic
battery: self-ratio tautology, fan-out (incl. CTE-hidden + parent), boundary-saturated
rate (scale-robust), part>whole, and claim-grounding.
"""
from aughor.sql.fanout import self_ratio_tautology
from aughor.explorer.verify import (
    is_degenerate_result, _part_exceeds_whole, _claim_numbers_grounded, verify_insight,
)

REPEAT_RANGE = [(frozenset({"repeat", "purchase"}), "ratio01", 1.0)]   # declared ratio 0-1
MARGIN_RANGE = [(frozenset({"gross", "margin"}), "pct100", 100.0)]      # declared percent 0-100


class TestTautology:
    def test_self_ratio_flagged(self):
        assert self_ratio_tautology("SELECT SUM(gm_usd)/NULLIF(SUM(gm_usd),0) FROM t")

    def test_real_rate_not_flagged(self):
        assert self_ratio_tautology("SELECT (SUM(rev)-SUM(cogs))/NULLIF(SUM(rev),0) FROM t") is None
        assert self_ratio_tautology("SELECT SUM(a)/NULLIF(SUM(a+b),0) FROM t") is None


class TestBoundarySaturation:
    def test_percent_value_on_ratio_metric_single_row(self):
        # "100% repeat buyers": value 100.0 but metric declared ratio 0-1 → saturated
        assert is_degenerate_result([["100.0"]], "100% of customers are repeat buyers", "", REPEAT_RANGE)

    def test_self_ratio_caught_by_gate_not_value_check(self):
        # a bare 1.0 on a percent metric is NOT value-flagged (could be a real 1%) — the
        # value check stays conservative; the underlying self-ratio bug is caught by the
        # SQL tautology guard in the full gate instead.
        assert not is_degenerate_result([["1.0"], ["1.0"]], "gross margin 100%", "", MARGIN_RANGE)
        ok, why = verify_insight([["1.0"], ["1.0"]], "gross margin 100%",
                                 "SELECT m, SUM(gm)/NULLIF(SUM(gm),0) FROM t GROUP BY 1", MARGIN_RANGE)
        assert not ok and "self-referential" in why

    def test_mixed_rates_survive(self):
        # genuine tier variation 91.67–100 is real signal, NOT degenerate
        rows = [["100.0"], ["97.79"], ["96.88"], ["91.67"]]
        assert not is_degenerate_result(rows, "repeat purchase rate by tier", "", REPEAT_RANGE)

    def test_healthy_rate_survives(self):
        assert not is_degenerate_result([["66.3"], ["66.2"]], "gross margin 66%", "", MARGIN_RANGE)


class TestPartExceedsWhole:
    def test_category_exceeds_total(self):
        # gmv constant 251717 across rows, category_gmv up to 457199 → impossible
        rows = [["251717.40", "Apparel", "457199.94"], ["251717.40", "Acc", "453629.71"]]
        assert _part_exceeds_whole(rows)

    def test_constant_rate_beside_count_not_flagged(self):
        # a constant rate (0.5) next to larger counts must NOT trip it (magnitude guard)
        assert _part_exceeds_whole([["0.5", "1200"], ["0.5", "3400"]]) is None

    def test_single_row_not_flagged(self):
        assert _part_exceeds_whole([["251717", "457199"]]) is None


class TestClaimGrounding:
    def test_fabricated_numbers_flagged(self):
        rows = [["Skincare", "12"], ["Makeup", "9"]]            # only small counts present
        assert _claim_numbers_grounded("Revenue was $931,720.00 across 59,314 orders", rows)

    def test_grounded_numbers_survive(self):
        rows = [["Apparel", "931720.0"]]
        assert _claim_numbers_grounded("Apparel led with $931,720.00", rows) is None

    def test_percent_matches_fraction(self):
        rows = [["0.663"]]                                      # 66.3% ↔ 0.663
        assert _claim_numbers_grounded("margin 66.3% and 66.2%", rows) is None


class TestVerifyInsightEndToEnd:
    def test_tautology_dropped(self):
        ok, why = verify_insight([["1.0"]], "100% margin", "SELECT SUM(x)/NULLIF(SUM(x),0) FROM t")
        assert not ok and "self-referential" in why

    def test_clean_insight_passes(self):
        ok, why = verify_insight(
            [["Fragrance", "92.1"], ["Makeup", "73.7"]],
            "Fragrance has the highest margin at 92.1%",
            "SELECT category, margin FROM v", MARGIN_RANGE)
        assert ok, why

    def test_fail_open_on_garbage(self):
        # internal error path must not suppress (fail-open)
        ok, _ = verify_insight(None, "x", "not sql")
        assert ok
