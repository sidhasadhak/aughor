"""Data-shape-aware temporal planning — the coverage clamp (both surfaces).

Repro class (user-reported, 2026-06-10): bakehouse holds 17 DAYS of data
(2024-05-01 → 2024-05-17) beside ecommerce's 24 months on the same `workspace`
connection, yet the explorer framed findings as "the last 12 months" and ADA ran
a 12-month observation vs an empty prior-12-month comparison, reporting NULLs.

Three deterministic fixes under test:
1. `_role_aware_time_window` clamps the window start to the earliest fact.
2. `_window_for_tables` derives a per-dataset window (bakehouse must not inherit
   ecommerce's anchor).
3. ADA: `_extract_data_date_range(scan, table)` reads the metric table's own
   profile line (the global scan mixes datasets), and `_clamp_intake_to_coverage`
   enforces window fitting in code rather than asking the LLM to comply.
"""
from types import SimpleNamespace

from aughor.explorer.windowing import (
    role_aware_time_window as _role_aware_time_window,
    window_for_tables as _window_for_tables,
    _table_min,
)
from aughor.agent.investigate import (
    _extract_data_date_range,
    _clamp_intake_to_coverage,
    _months_between,
    _resolve_probe_ref,
    _sparse_comparison_decision,
    _flag_sparse_comparison,
    _POP_MISMATCH_SIGNATURE,
)


def _prof(rng, rows=1000, measures=True):
    cols = {"amount": SimpleNamespace(is_measure=True)} if measures else {}
    return SimpleNamespace(
        date_range=rng,
        effective_date_range=rng,
        row_count=rows,
        columns=cols,
    )


def _cp(measures=True):
    # column profiles keyed by table: anything with a numeric/measure column
    return {"amount": SimpleNamespace(semantic_type="measure", dtype="DOUBLE")}


BAKE = ("2024-05-01", "2024-05-17")
ECOM = ("2023-01-01", "2024-12-30")


class TestExplorerWindowClamp:
    def test_short_history_clamps_start_to_first_fact(self):
        tp = {"bakehouse.sales_transactions": _prof(BAKE, rows=3333)}
        cp = {"bakehouse.sales_transactions": _cp()}
        start, end, _ = _role_aware_time_window(tp, cp)
        assert start == "2024-05-01", f"start must clamp to first fact, got {start}"
        assert end >= "2024-05-17"

    def test_long_history_keeps_12_month_window(self):
        tp = {"ecommerce.orders": _prof(ECOM, rows=10000)}
        cp = {"ecommerce.orders": _cp()}
        start, end, _ = _role_aware_time_window(tp, cp)
        # 24 months of data: the 12-month window must NOT collapse to the data min
        assert start > "2023-01-01"
        assert start.startswith("2024-0") or start.startswith("2023-12")

    def test_table_min_filters_sentinels(self):
        assert _table_min(_prof(("1900-01-01", "2024-05-17"))) is None
        assert _table_min(_prof(BAKE)) == "2024-05-01"


class TestPerDatasetWindow:
    def test_domain_window_anchors_on_its_own_dataset(self):
        tp = {
            "bakehouse.sales_transactions": _prof(BAKE, rows=3333),
            "ecommerce.orders": _prof(ECOM, rows=10000),
        }
        cp = {t: _cp() for t in tp}
        win = _window_for_tables(tp, cp, {"bakehouse.sales_transactions"})
        assert win is not None
        start, end = win
        # Must anchor on bakehouse (May 2024), not ecommerce (Dec 2024)
        assert start == "2024-05-01"
        assert end < "2024-08-01"

    def test_bare_table_names_match_qualified_profiles(self):
        tp = {"bakehouse.sales_transactions": _prof(BAKE, rows=3333)}
        cp = {"bakehouse.sales_transactions": _cp()}
        assert _window_for_tables(tp, cp, {"sales_transactions"}) is not None

    def test_unknown_tables_return_none(self):
        tp = {"ecommerce.orders": _prof(ECOM)}
        assert _window_for_tables(tp, {}, {"nope.missing"}) is None


SCAN = (
    "  [PROFILE] bakehouse.sales_transactions — 3,333 rows | grain: transactionID ✓ | 2024-05-01 → 2024-05-17\n"
    "  [PROFILE] ecommerce.orders — 9,994 rows | grain: order_id ✓ | 2023-01-01 → 2024-12-30\n"
)


class TestTableScopedDateRange:
    def test_table_scoped_range_ignores_sibling_dataset(self):
        dmin, dmax = _extract_data_date_range(SCAN, "bakehouse.sales_transactions")
        assert (dmin, dmax) == ("2024-05-01", "2024-05-17")

    def test_bare_name_matches(self):
        dmin, dmax = _extract_data_date_range(SCAN, "sales_transactions")
        assert (dmin, dmax) == ("2024-05-01", "2024-05-17")

    def test_global_fallback_when_table_absent(self):
        dmin, dmax = _extract_data_date_range(SCAN, "not_a_table")
        assert (dmin, dmax) == ("2023-01-01", "2024-12-30")


def _intake(**kw):
    base = dict(
        observation_start="2023-06-01", observation_end="2024-05-31",
        observation_label="Last 12 months (Jun 2023 – May 2024)",
        comparison_start="2022-06-01", comparison_end="2023-05-31",
        comparison_label="Prior 12 months (Jun 2022 – May 2023)",
        cross_sectional=False, intake_notes="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestIntakeCoverageClamp:
    def test_the_bakehouse_repro(self):
        """The exact user-reported shape: 12-month obs + empty prior-12-month
        comparison over 17 days of data."""
        it = _intake()
        note = _clamp_intake_to_coverage(it, "2024-05-01", "2024-05-17")
        assert it.observation_start == "2024-05-01"
        assert it.observation_end == "2024-05-17"
        assert "Available history" in it.observation_label
        # Comparison collapsed — no prior period exists
        assert it.comparison_start == it.observation_start
        assert it.comparison_end == it.observation_end
        assert "no prior period" in it.comparison_label
        assert note and "DATA COVERAGE" in note
        assert "year-over-year" in note or "not applicable" in note

    def test_full_coverage_untouched(self):
        it = _intake(
            observation_start="2024-01-01", observation_end="2024-12-30",
            comparison_start="2023-01-01", comparison_end="2023-12-31",
        )
        note = _clamp_intake_to_coverage(it, "2023-01-01", "2024-12-30")
        assert note is None
        assert it.observation_start == "2024-01-01"
        assert "Prior" in it.comparison_label

    def test_partial_overlap_clips_not_collapses(self):
        it = _intake(
            observation_start="2024-01-01", observation_end="2024-12-31",
            comparison_start="2023-01-01", comparison_end="2023-12-31",
        )
        note = _clamp_intake_to_coverage(it, "2023-06-01", "2024-06-30")
        assert it.observation_end == "2024-06-30"
        assert it.comparison_start == "2023-06-01"  # clipped — has real overlap, not collapsed
        assert "no prior period" not in it.comparison_label
        assert note is not None

    def test_duration_mismatch_relabels_and_warns(self):
        """The GMV brand-tier repro: a ~57-month observation whose 'prior 56 months'
        window was clipped to the ~3 real months that exist before the data starts.
        The absolute PoP total between them is an ~18x duration artifact — the guard
        must relabel the stub comparison honestly and steer to run-rate."""
        it = _intake(
            observation_start="2020-10-01", observation_end="2025-06-30",
            comparison_start="2016-02-01", comparison_end="2020-09-30",
            comparison_label="Prior 56 months",
        )
        note = _clamp_intake_to_coverage(it, "2020-07-01", "2025-06-30")
        # observation is left intact (it already ends at dmax → no re-anchor)
        assert it.observation_start == "2020-10-01"
        assert it.observation_end == "2025-06-30"
        # prior window clipped to the real ~3 months, and relabelled honestly (not "56")
        assert it.comparison_start == "2020-07-01"
        assert it.comparison_end == "2020-09-30"
        assert "56" not in it.comparison_label
        assert "2020-07-01" in it.comparison_label
        # the note carries the duration-artifact warning + the run-rate steer
        assert note and "DATA COVERAGE" in note
        assert "duration artifact" in note.lower()
        assert "run-rate" in note.lower()

    def test_equal_length_windows_do_not_trip_mismatch(self):
        """A legitimate 12-vs-12 comparison must NOT trip the duration guard."""
        it = _intake(
            observation_start="2024-01-01", observation_end="2024-12-30",
            comparison_start="2023-01-01", comparison_end="2023-12-31",
            comparison_label="Prior 12 months",
        )
        note = _clamp_intake_to_coverage(it, "2023-01-01", "2024-12-30")
        assert note is None
        assert it.comparison_label == "Prior 12 months"

    def test_cross_sectional_skipped(self):
        it = _intake(cross_sectional=True)
        assert _clamp_intake_to_coverage(it, "2024-05-01", "2024-05-17") is None

    def test_missing_range_noop(self):
        it = _intake()
        assert _clamp_intake_to_coverage(it, None, None) is None
        assert it.observation_start == "2023-06-01"


class TestDensityGuard:
    """The density guard catches what the date-span guard structurally cannot: a comparison
    window whose calendar span looks fine but is sparsely populated (an internal gap / slow ramp)."""

    def test_months_between_inclusive(self):
        assert _months_between("2020-07-01", "2020-09-30") == 3
        assert _months_between("2024-01-01", "2024-12-31") == 12
        assert _months_between("2022-01-15", "2023-01-02") == 13
        assert _months_between("garbage", "2024-01-01") is None

    def test_resolve_probe_ref(self):
        assert _resolve_probe_ref("orders", "order_date") == ("orders", "order_date")
        assert _resolve_probe_ref("shop.orders", "order_date") == ("shop.orders", "order_date")
        # date column qualified with its own table (lives elsewhere than the metric table)
        assert _resolve_probe_ref("order_items", "shop.orders.order_ts") == ("shop.orders", "order_ts")
        # two-part date col borrows the metric table's schema
        assert _resolve_probe_ref("shop.order_items", "orders.order_ts") == ("shop.orders", "order_ts")

    def test_sparse_decision_flags_thin_baseline(self):
        it = _intake()
        note = _sparse_comparison_decision(it, span_months=12, populated=3)
        assert note and _POP_MISMATCH_SIGNATURE in note
        assert "3 of ~12" in it.comparison_label       # honest relabel
        assert "run-rate" in note.lower()

    def test_dense_window_not_flagged(self):
        it = _intake()
        assert _sparse_comparison_decision(it, span_months=12, populated=11) is None  # 11 ≥ 0.66·12

    def test_short_window_not_flagged(self):
        it = _intake()
        assert _sparse_comparison_decision(it, span_months=3, populated=1) is None     # span < min

    def test_unknown_counts_are_no_op(self):
        it = _intake()
        assert _sparse_comparison_decision(it, None, 3) is None
        assert _sparse_comparison_decision(it, 12, None) is None

    def test_flag_skips_when_span_guard_already_fired(self):
        # span guard already flagged the window → no double-flag, and no DB probe
        assert _flag_sparse_comparison(_intake(), "conn", "t", "d", span_guard_fired=True) is None

    def test_flag_skips_cross_sectional_and_same_period(self):
        assert _flag_sparse_comparison(_intake(cross_sectional=True), "c", "t", "d", False) is None
        # comparison == observation → no distinct prior period to probe
        same = _intake(comparison_start="2023-06-01", comparison_end="2024-05-31")
        assert _flag_sparse_comparison(same, "c", "t", "d", False) is None
