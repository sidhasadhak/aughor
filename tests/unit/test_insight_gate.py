"""Pre-emission insight verification gate — regression tests built from the exact
nonsense the BeautyCommerce runs leaked (and the good insights that must survive).

The gate treats a generated finding as untrusted until it passes a deterministic
battery: self-ratio tautology, fan-out (incl. CTE-hidden + parent), boundary-saturated
rate (scale-robust), part>whole, and claim-grounding.
"""
from aughor.sql.fanout import self_ratio_tautology, group_by_continuous_measure
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

    def test_derived_percent_change_not_flagged(self):
        # the GMV repro: +1,506% is (15.84M - 986K)/986K·100 — a valid derivation from the
        # cells, not a fabrication. Must NOT flag just because the % appears in no single cell.
        rows = [["luxury", "15840000", "986000"], ["ultra", "15240000", "964000"]]
        assert _claim_numbers_grounded(
            "Luxury grew +1,506% and ultra +1,481% over the window", rows) is None

    def test_true_fabrication_still_flagged_when_derivation_aware(self):
        # two asserted figures, neither present nor derivable from the cells → still flagged
        rows = [["A", "10"], ["B", "20"]]
        assert _claim_numbers_grounded("Total was $8,451,207 across 44,910 orders", rows)


class TestVerifyInsightEndToEnd:
    def test_tautology_dropped(self):
        ok, why = verify_insight([["1.0"]], "100% margin", "SELECT SUM(x)/NULLIF(SUM(x),0) FROM t")
        assert not ok and "self-referential" in why

    def test_null_side_group_demotion_dropped(self):
        # The luxexperience "Beauty and jewelry_watches … 100% return rate": a LEFT JOIN
        # demoted by GROUP BY-ing on the null (returns) side, so the preserved-side
        # denominator is silently restricted and the rate is 1.0 in every bucket. The
        # syntactic self_ratio_tautology can't see it (two different expressions); the
        # semantic guard does. Qualified `r.category` so no table_cols is needed.
        ok, why = verify_insight(
            [["Beauty", "1.0"], ["jewelry_watches", "1.0"]],
            "Beauty and jewelry_watches both maintain a 100% return rate.",
            "SELECT r.category, COUNT(DISTINCT r.order_id) * 1.0 "
            "/ NULLIF(COUNT(DISTINCT o.order_id), 0) AS return_rate "
            "FROM orders o LEFT JOIN returns r ON o.order_id = r.order_id GROUP BY r.category")
        assert not ok
        assert "null-side" in why

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


class TestAggregateTypeGate:
    """Generation-side guard (#182 type check, lifted from the display stamp to the source):
    a non-additive aggregate over a non-numeric column is DROPPED at the emission gate — never
    stored — using the conn's DECLARED column types. SUM(signup_fy) where signup_fy is a
    VARCHAR fiscal-year label makes DuckDB coerce and sum the year-strings into a real-looking,
    meaningless number; the query 'succeeds', so grounding can't catch it — the column's type can."""

    _SCHEMA = (
        "TABLE: customers (1000 rows)\n"
        "  signup_fy  VARCHAR\n"
        "  revenue  DECIMAL(18,2)\n"
        "  tier  VARCHAR\n"
    )

    class _Conn:
        """Minimal conn: the gate only needs get_schema() for the type map (the oracle /
        metric-vocab lookups fail-open without a live cursor)."""
        def __init__(self, schema):
            self._schema = schema

        def get_schema(self):
            return self._schema

    def _conn(self):
        return self._Conn(self._SCHEMA)

    def test_sum_over_varchar_dropped_at_gate(self):
        ok, why = verify_insight(
            [["enterprise", "2493788"], ["smb", "1200000"]],
            "Signups total 2,493,788 across the base, led by the enterprise tier.",
            "SELECT tier, SUM(signup_fy) AS signups FROM customers GROUP BY tier",
            conn=self._conn())
        assert not ok
        assert "signup_fy" in why          # the reason names the offending column

    def test_sum_over_numeric_survives(self):
        # SUM over a real numeric column is a legitimate measure — must pass the type gate.
        ok, why = verify_insight(
            [["enterprise", "8200000"], ["smb", "3100000"]],
            "Enterprise revenue leads at 8.2M.",
            "SELECT tier, SUM(revenue) AS rev FROM customers GROUP BY tier",
            conn=self._conn())
        assert ok, why

    def test_no_conn_leaves_type_gate_off(self):
        # Without a conn there are no declared types → the aggregate-type check cannot fire
        # (fail-open, backward-compatible). Guards the "no conn → no-op" contract that keeps
        # every pre-existing verify_insight call site unchanged.
        ok, _ = verify_insight(
            [["enterprise", "2493788"], ["smb", "1200000"]],
            "Signups total 2,493,788 across the base.",
            "SELECT tier, SUM(signup_fy) AS signups FROM customers GROUP BY tier")
        assert ok


class TestGroupByContinuousMeasure:
    """(b) — GROUP BY a continuous measure is a scatter mislabelled as a breakdown. Fires only
    on a measure-named, non-dimension column whose LIVE distinct-count confirms it is continuous."""
    TC = {"luxexperience.orders": ["order_id", "revenue", "rating", "region", "price_tier"]}

    @staticmethod
    def _count(mapping):
        return lambda tbl, col: mapping.get(col)

    def test_group_by_continuous_revenue_flagged(self):
        why = group_by_continuous_measure(
            "SELECT revenue, COUNT(*) FROM orders GROUP BY revenue",
            self.TC, distinct_count=self._count({"revenue": 4000}))
        assert why and "continuous measure" in why and "revenue" in why

    def test_pre_binned_measure_is_ok(self):
        # few distinct values → a legitimate breakdown, even though 'revenue' is measure-named
        assert group_by_continuous_measure(
            "SELECT revenue, COUNT(*) FROM orders GROUP BY revenue",
            self.TC, distinct_count=self._count({"revenue": 6})) is None

    def test_dimensions_never_flagged(self):
        # rating/region are not measure-named; price_tier carries a _tier dimension marker
        for col in ("rating", "region", "price_tier"):
            assert group_by_continuous_measure(
                f"SELECT {col}, COUNT(*) FROM orders GROUP BY {col}",
                self.TC, distinct_count=self._count({col: 9999})) is None

    def test_no_probe_no_flag(self):
        # without the cardinality oracle the guard stays OFF (fail-safe, no false positives)
        assert group_by_continuous_measure(
            "SELECT revenue, COUNT(*) FROM orders GROUP BY revenue", self.TC, distinct_count=None) is None


def test_make_cardinality_oracle_probes_and_caches():
    from aughor.profile.validate import make_cardinality_oracle

    class _Conn:
        calls = 0

        def execute(self, qid, sql):
            _Conn.calls += 1

            class _R:
                error = None
                rows = [["1234"]]     # the executor returns stringified cells

            return _R()

    oracle = make_cardinality_oracle(_Conn(), {"luxexperience.orders": ["revenue"]})
    assert oracle("orders", "revenue") == 1234
    assert oracle("orders", "revenue") == 1234       # served from cache
    assert _Conn.calls == 1                           # probed exactly once


def test_col_types_from_schema_maps_bare_and_qualified():
    # The shared parse behind BOTH the insight cards/brief (routers) and the emission gate.
    from aughor.tools.schema import col_types_from_schema
    ct = col_types_from_schema(
        "TABLE: customers (10 rows)\n"
        "  signup_fy  VARCHAR\n"
        "  revenue  DECIMAL(18,2)\n"
        "TABLE: orders (20 rows)\n"
        "  revenue  BIGINT\n"                 # same bare name, different table + type
    )
    assert ct["signup_fy"] == "VARCHAR" and ct["customers.signup_fy"] == "VARCHAR"
    # Bare 'revenue' keeps the FIRST type seen; the qualified keys disambiguate the collision.
    assert ct["revenue"] == "DECIMAL(18,2)"
    assert ct["customers.revenue"] == "DECIMAL(18,2)" and ct["orders.revenue"] == "BIGINT"
    assert col_types_from_schema("") == {}     # fail-open on empty/junk
