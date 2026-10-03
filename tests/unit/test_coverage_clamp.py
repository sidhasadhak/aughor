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
    _trailing_partial_decision,
    _flag_trailing_partial,
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
        # CA-0: no prior period exists → the comparison is CLEARED and the verdict typed,
        # never collapsed onto the observation window.
        assert (it.comparison_start, it.comparison_end) == ("", "")
        assert it.no_prior_period is True
        assert "no prior period" in it.comparison_label.lower()
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

    def test_a_window_ending_today_is_trimmed_to_the_last_complete_day(self):
        """The 43-vs-1,733 shape, found live 2026-09-02: the 09:00 briefing compared
        nine hours of today against all of yesterday and headlined a 97.5% collapse.
        A day in progress cannot be a complete period."""
        it = _intake(
            observation_start="2026-08-27", observation_end="2026-09-02",
            comparison_start="2026-08-20", comparison_end="2026-08-26",
        )
        note = _clamp_intake_to_coverage(it, "2025-01-01", "2026-09-02",
                                         question="what changed in the last week?",
                                         today="2026-09-02")
        assert it.observation_end == "2026-09-01"
        assert it.observation_start == "2026-08-27"
        assert note and "day still in progress" in note
        assert "false collapse" in note

    def test_the_briefing_shape_cascades_to_full_prior_days(self):
        """One-day observation = today, comparison = yesterday. After the trim the
        comparison IS the observation — the tautology machinery must then hand back
        the preceding complete day, so the briefing reports yesterday vs the day
        before, both whole."""
        it = _intake(
            observation_start="2026-09-02", observation_end="2026-09-02",
            comparison_start="2026-09-01", comparison_end="2026-09-01",
        )
        note = _clamp_intake_to_coverage(it, "2025-01-01", "2026-09-02",
                                         question="What changed in theLook in the last day?",
                                         today="2026-09-02")
        assert (it.observation_start, it.observation_end) == ("2026-09-01", "2026-09-01")
        assert (it.comparison_start, it.comparison_end) == ("2026-08-31", "2026-08-31")
        assert it.no_prior_period is False
        assert note and "day still in progress" in note

    def test_a_closed_dataset_keeps_its_final_day(self):
        """dmax far in the past ⇒ the terminal day is as complete as it will ever be.
        Trimming it would erase real data on every run forever."""
        it = _intake(
            observation_start="2024-05-01", observation_end="2024-05-17",
            comparison_start="2024-04-14", comparison_end="2024-04-30",
        )
        note = _clamp_intake_to_coverage(it, "2024-01-01", "2024-05-17",
                                         today="2026-09-02")
        assert it.observation_end == "2024-05-17"
        assert not (note and "day still in progress" in note)

    def test_a_question_that_pins_today_keeps_it_and_gets_the_warning(self):
        """'September 2nd, 2026' asked ON September 2nd: the reader named the partial
        day knowingly — the window stays, the note says PARTIAL."""
        it = _intake(
            observation_start="2026-09-02", observation_end="2026-09-02",
            comparison_start="2026-09-01", comparison_end="2026-09-01",
        )
        note = _clamp_intake_to_coverage(
            it, "2025-01-01", "2026-09-02",
            question="how are orders on September 2nd, 2026?", today="2026-09-02")
        assert it.observation_end == "2026-09-02"
        assert note and "PARTIAL" in note

    def test_a_reanchored_stale_window_lands_on_complete_days(self):
        """The re-anchor pulls a mis-placed relative window to the data's most recent
        point — which must be the last COMPLETE day when the data reaches today, or
        the re-anchor reintroduces the artifact the trim exists to prevent."""
        it = _intake(
            observation_start="2026-05-01", observation_end="2026-06-30",
            comparison_start="2026-03-01", comparison_end="2026-04-30",
        )
        note = _clamp_intake_to_coverage(it, "2025-01-01", "2026-09-02",
                                         question="last 2 months of revenue?",
                                         today="2026-09-02")
        assert it.observation_end == "2026-09-01", "re-anchor must not land on the partial day"
        assert note and "re-anchored" in note

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

    def test_cross_sectional_is_clamped_too(self):
        """A cross-sectional intake was exempt, and its window still reached every
        SQL-writing prompt through the spec: the "last 6 months" a model placed in 2024
        was re-anchored on the temporal path and answered for 2024 on this one (theLook,
        2026-09-29). The same rules now apply on both."""
        it = _intake(cross_sectional=True)
        note = _clamp_intake_to_coverage(it, "2024-05-01", "2024-05-17")
        assert note and "clipped" in note
        assert (it.observation_start, it.observation_end) == ("2024-05-01", "2024-05-17")

    def test_a_stale_relative_window_is_reanchored_on_a_cross_sectional_intake(self):
        it = _intake(cross_sectional=True, observation_start="2024-06-01", observation_end="2024-11-30",
                     observation_label="Last 6 months", comparison_start="2023-12-01",
                     comparison_end="2024-05-31")
        note = _clamp_intake_to_coverage(it, "2019-01-09", "2026-10-02", question="last 6 months",
                                         today="2026-09-30")
        assert note and "re-anchored" in note
        assert it.observation_end == "2026-09-29" and it.observation_start == "2026-03-30"   # six months to the day

    def test_a_window_the_question_gives_a_length_is_that_long(self):
        """Q2, 2026-10-03: the intake model counted "the last 6 months" to the settled day 4 September from
        4 March — six months and a day (on 10-02 it was right). Code counts it from the window's end; whole
        months stay whole, and a comparison that ran up to the window still does."""
        q2 = "Which 10 product categories brought in the most revenue in the last 6 months?"
        it = _intake(cross_sectional=True, observation_start="2026-03-04", observation_end="2026-09-04")
        note = _clamp_intake_to_coverage(it, "2019-01-09", "2026-10-02", question=q2, today="2026-10-03",
                                         settle_days=29)
        assert (it.observation_start, it.observation_end) == ("2026-03-05", "2026-09-04")
        assert note and "began 2026-03-04" in note
        it = _intake(observation_start="2025-09-01", observation_end="2026-08-31",
                     comparison_start="2024-09-01", comparison_end="2025-08-31")
        assert _clamp_intake_to_coverage(it, "2019-01-09", "2026-10-02", question="over the last 12 months",
                                         today="2026-10-03", settle_days=29) is None
        assert it.observation_start == "2025-09-01"
        it = _intake(observation_start="2026-03-04", observation_end="2026-09-04",
                     comparison_start="2025-09-04", comparison_end="2026-03-03")
        _clamp_intake_to_coverage(it, "2019-01-09", "2026-10-02", today="2026-10-03", settle_days=29,
                                  question="revenue in the last six months vs the six months before")
        assert (it.comparison_start, it.comparison_end) == ("2025-09-05", "2026-03-04")

    def test_a_cross_sectional_intake_gets_no_comparison_verdict(self):
        """The Q2 re-run, 2026-09-30: a cross-sectional intake carried a placeholder
        one-day comparison, the window-length guard judged it against six months, and a
        duration-artifact caveat opened an answer that compared nothing. The observation
        rules reach this intake; the comparison ones do not."""
        it = _intake(cross_sectional=True, observation_start="2026-03-02", observation_end="2026-09-01",
                     observation_label="Last 6 months", comparison_start="2026-03-01",
                     comparison_end="2026-03-01", comparison_label="")
        note = _clamp_intake_to_coverage(it, "2019-01-09", "2026-10-02", question="last 6 months",
                                         today="2026-09-30", settle_days=29)
        assert note is None or "DURATION ARTIFACTS" not in note
        assert (it.comparison_start, it.comparison_end) == ("2026-03-01", "2026-03-01")
        assert not getattr(it, "no_prior_period", False)
        assert (it.observation_start, it.observation_end) == ("2026-03-02", "2026-09-01")

    def test_a_comparison_the_data_start_did_not_cut_is_not_called_a_short_prior(self):
        """2026-10-02, monthly revenue: the intake's "comparison" was the observation's own last month, seven
        years after the data begins; the guard called it "Prior ~1 month(s) available (data begins 2019-01-11)",
        and a duration-artifact warning opened an answer that compared months."""
        it = _intake(observation_start="2025-09-01", observation_end="2026-08-31", observation_label="Sep 2025 – Aug 2026",
                     comparison_start="2026-08-01", comparison_end="2026-08-31", comparison_label="Previous month")
        note = _clamp_intake_to_coverage(it, "2019-01-11", "2026-10-01")
        assert it.comparison_label == "Previous month"
        assert note is None or "duration artifact" not in note.lower()

    def test_a_warning_put_in_front_of_an_answer_never_cuts_it(self):
        from aughor.agent.investigate import _POP_MISMATCH_SIGNATURE, _reframe_on_pop_duration_mismatch
        table = "\n".join(f"| {y}-{m:02d}-01 | completed orders | {m * 1000} |"
                          for y in (2024, 2025, 2026) for m in range(1, 13))
        synth = SimpleNamespace(executive_summary="Revenue by month:\n\n| Month | Kind | Revenue |\n" + table,
                                attribution_waterfall=[], data_gaps=[])
        assert len(synth.executive_summary) > 900
        assert _reframe_on_pop_duration_mismatch(synth, {"intake_notes": _POP_MISMATCH_SIGNATURE})
        assert synth.executive_summary.startswith("The observation and prior windows differ sharply")
        assert synth.executive_summary.endswith("| 2026-12-01 | completed orders | 12000 |")   # to its last row

    def test_the_trust_banner_is_put_in_front_and_cuts_nothing(self):
        from aughor.agent.investigate import _reframe_on_trust_caveat
        table = "\n".join(f"| {y}-{m:02d}-01 | completed orders | {m * 1000 + 73} |"
                          for y in (2024, 2025, 2026) for m in range(1, 13))
        synth = SimpleNamespace(headline="h", executive_summary="Refund rate is 73.0%.\n\n" + table,
                                confidence="HIGH", confidence_justification="", data_gaps=[])
        phases = [{"findings": [{"trust_caveat": "conditioned denominator: the rate is corrupt",
                                 "rows": [["Fragrance", 73.0]]}]}]
        assert len(synth.executive_summary) > 900 and _reframe_on_trust_caveat(synth, phases)
        assert synth.executive_summary.startswith("⚠ ")
        assert synth.executive_summary.endswith("| 2026-12-01 | completed orders | 12073 |")

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


class TestTrailingPartialGuard:
    """An incomplete final observation month (far fewer rows than typical) reads as a false drop —
    the profiler computes this but the intake never consumed it."""

    def test_incomplete_final_month_flagged(self):
        it = _intake()
        note = _trailing_partial_decision(it, [("2025-04", 30), ("2025-05", 32), ("2025-06", 5)])
        assert note and "2025-06" in note
        assert "incomplete" in note.lower() or "partial" in note.lower()
        assert "may be incomplete" in it.observation_label   # honest relabel
        assert it.observation_label.endswith("June 2025 may be incomplete"), "the month in words, not 2025-06"

    def test_full_final_month_not_flagged(self):
        it = _intake()
        assert _trailing_partial_decision(it, [("2025-04", 30), ("2025-05", 32), ("2025-06", 31)]) is None

    def test_too_few_months_no_op(self):
        it = _intake()
        assert _trailing_partial_decision(it, [("2025-05", 30), ("2025-06", 2)]) is None  # < 3 months

    def test_empty_counts_no_op(self):
        it = _intake()
        assert _trailing_partial_decision(it, None) is None
        assert _trailing_partial_decision(it, []) is None

    def test_flag_skips_cross_sectional(self):
        assert _flag_trailing_partial(_intake(cross_sectional=True), "c", "t", "d") is None
