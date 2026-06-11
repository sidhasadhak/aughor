"""Deterministic temporal re-anchoring in _clamp_intake_to_coverage (WCH-DS follow-up).

The bug a user caught by re-running: the intake LLM picks "last 12 months" = calendar 2023
when the data runs 2023→2024, and the clamp only CLIPPED (2023 is in range) so it stuck —
analysing the OLDER year and forfeiting the 2024-vs-2023 YoY the data supports. The clamp now
RE-ANCHORS a relative window to end at the data's max date, leaving SPECIFIC periods literal.
These pin every use case (the fix is fully deterministic, so it's exhaustively testable)."""
from aughor.agent.investigate import _clamp_intake_to_coverage, _question_pins_period


class FakeIntake:
    def __init__(self, os, oe, cs="", ce="", label="Last 12 months", clabel="Prior 12 months"):
        self.cross_sectional = False
        self.observation_start, self.observation_end = os, oe
        self.comparison_start, self.comparison_end = cs, ce
        self.observation_label, self.comparison_label = label, clabel


TWO_YR = ("2023-01-01", "2024-12-30")   # data spans two full years


class TestReanchorsRelativeWindow:
    def test_the_bug_last_12_months_anchored_to_old_year(self):
        # LLM put "last 12 months" at calendar 2023; data runs through 2024-12-30.
        it = FakeIntake("2023-01-01", "2023-12-31", "2022-01-01", "2022-12-31")
        note = _clamp_intake_to_coverage(it, *TWO_YR, question="why did AOV change in the last 12 months?")
        assert it.observation_end == "2024-12-30"          # re-anchored to the data's latest point
        assert it.observation_start.startswith("2024")     # observation is now the recent year
        assert it.comparison_start.startswith("2023")      # prior-period comparison now lands in 2023
        assert it.comparison_end.startswith("2023")
        assert "re-anchored" in (note or "")

    def test_last_3_months_anchored_recently(self):
        it = FakeIntake("2023-01-01", "2023-03-31")   # an old 3-month window
        _clamp_intake_to_coverage(it, *TWO_YR, question="revenue trend over the last 3 months")
        assert it.observation_end == "2024-12-30"
        # ~3-month window preserved
        assert it.observation_start.startswith("2024")

    def test_no_date_in_question_is_relative(self):
        it = FakeIntake("2023-01-01", "2023-12-31")
        _clamp_intake_to_coverage(it, *TWO_YR, question="how is average order value doing?")
        assert it.observation_end == "2024-12-30"


class TestLeavesSpecificPeriodsLiteral:
    def test_explicit_year_is_pinned(self):
        it = FakeIntake("2023-01-01", "2023-12-31", "2022-01-01", "2022-12-31")
        _clamp_intake_to_coverage(it, *TWO_YR, question="what happened to AOV in 2023?")
        assert it.observation_start == "2023-01-01"   # NOT re-anchored — user asked for 2023
        assert it.observation_end == "2023-12-31"

    def test_specific_month_with_year_pinned(self):
        it = FakeIntake("2024-05-01", "2024-05-31", "2024-04-01", "2024-04-30")
        _clamp_intake_to_coverage(it, *TWO_YR, question="why did revenue drop in May 2024?")
        assert it.observation_start == "2024-05-01"   # already recent AND year-pinned

    def test_year_over_year_request_pinned(self):
        it = FakeIntake("2024-01-01", "2024-12-31", "2023-01-01", "2023-12-31")
        _clamp_intake_to_coverage(it, *TWO_YR, question="compare 2024 vs 2023")
        assert it.observation_start == "2024-01-01"


class TestNoChangeWhenAlreadyCorrect:
    def test_window_already_ends_at_dmax(self):
        it = FakeIntake("2024-01-01", "2024-12-30", "2023-01-01", "2023-12-30")
        _clamp_intake_to_coverage(it, *TWO_YR, question="last 12 months trend")
        assert it.observation_start == "2024-01-01"   # gap ~0 → untouched
        assert it.observation_end == "2024-12-30"

    def test_cross_sectional_untouched(self):
        it = FakeIntake("2023-01-01", "2023-12-31")
        it.cross_sectional = True
        assert _clamp_intake_to_coverage(it, *TWO_YR, question="which region is weakest?") is None
        assert it.observation_start == "2023-01-01"

    def test_single_year_data_no_phantom_comparison(self):
        # data is ONE year — re-anchor must not invent a prior period; comparison collapses.
        it = FakeIntake("2023-01-01", "2023-12-31", "2022-01-01", "2022-12-31")
        _clamp_intake_to_coverage(it, "2023-01-01", "2023-12-31", question="last 12 months")
        assert it.observation_start == "2023-01-01" and it.observation_end == "2023-12-31"  # gap 0
        assert it.comparison_start == it.observation_start  # collapsed: no prior period
        assert "no prior period" in (it.comparison_label or "").lower()


class TestQuestionPinsPeriodHelper:
    def test_year_match(self):
        assert _question_pins_period("revenue in 2023", "2023-01-01", "2023-12-31") is True

    def test_year_mismatch_not_pinned(self):
        assert _question_pins_period("revenue in 2022", "2023-01-01", "2023-12-31") is False

    def test_no_year_relative(self):
        assert _question_pins_period("last 12 months", "2023-01-01", "2023-12-31") is False
