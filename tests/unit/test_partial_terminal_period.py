"""A time series whose last period is incomplete says so — CA-0.

Specimen cb37be54: monthly Direkteingabe traffic Jun 29,903 · Jul 37,925 · Aug 32,912 over data
ending 2026-08-18. The narrator wrote "partially correcting in August". August held 18 of 31
days and was per day the highest month (1,828 vs 1,223). The verdict is code-written and rides
`stat_note`, so the narrator reads it before writing and the evidence log carries it.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.investigate import (
    _partial_terminal_period_note,
    _results_text_with_verdicts,
    _stamp_partial_period_verdicts,
)

COLS = ["period", "total_traffic"]
ROWS = [["2026-06-01 00:00:00", "29903"], ["2026-07-01 00:00:00", "37925"], ["2026-08-01 00:00:00", "32912"]]


def test_specimen_august_is_flagged_partial_with_per_day_rates():
    note = _partial_terminal_period_note(COLS, ROWS, "2026-08-18")
    assert note and note.startswith("PARTIAL FINAL PERIOD: August 2026 holds 18 of 31 days (58%)")
    assert "not comparable to a full month" in note
    assert "Per day: August 2026 1,828 vs previous month 1,223" in note


def test_a_complete_final_month_is_not_flagged():
    assert _partial_terminal_period_note(COLS, ROWS, "2026-08-31") is None
    assert _partial_terminal_period_note(COLS, ROWS, "2026-09-03") is None


def test_weekly_grain_and_non_period_columns():
    weekly = [["2026-07-06", 100], ["2026-07-13", 110], ["2026-07-20", 120], ["2026-07-27", 60]]
    note = _partial_terminal_period_note(["week", "sessions"], weekly, "2026-07-29")
    assert note and "week of 2026-07-27 holds 3 of 7 days" in note
    # categorical first column → nothing to say
    assert _partial_terminal_period_note(["browser", "sessions"], [["Chrome", 1], ["Safari", 2]], "2026-08-18") is None
    # daily grain: a day is present or absent, never partial
    daily = [["2026-08-16", 1], ["2026-08-17", 2], ["2026-08-18", 3]]
    assert _partial_terminal_period_note(["d", "v"], daily, "2026-08-18") is None


def test_verdict_reaches_the_interpret_text_and_the_finding():
    r = SimpleNamespace(columns=COLS, rows=ROWS, error=None, row_count=3, sql="SELECT 1",
                        truncated=False, stats=[], duration_ms=0)
    text = _results_text_with_verdicts([r], 20, coverage_end="2026-08-18")
    assert "STATISTICAL VERDICT for this query — PARTIAL FINAL PERIOD: August 2026" in text
    findings = [{"finding_id": "baseline_1", "stat_note": "σ unavailable"}]
    _stamp_partial_period_verdicts(findings, [(None, r)], "2026-08-18")
    assert findings[0]["stat_note"].startswith("σ unavailable PARTIAL FINAL PERIOD")
