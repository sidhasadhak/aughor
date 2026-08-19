"""The coverage clamp never compares a window against itself — CA-0.

Specimen cb37be54 (2026-08-19): data 2026-06-01 → 2026-08-18; the intake model answered
observation "February 2025" (the schema's own example label) with a January-2025 comparison.
The old clamp clipped the observation to the full span, kept the model's label, and set the
comparison EQUAL to the observation ("Same period (no prior period exists in the data)").
Every decomposition row then came back obs == comp and the narrator reported "no significant
variation". Now: a comparison that cannot be honoured becomes the preceding window when the
data holds it, and otherwise a typed `no_prior_period` verdict the router reads.
"""
from __future__ import annotations

from aughor.agent.investigate import (
    _clamp_intake_to_coverage,
    _preceding_window,
    _window_label,
    route_after_baseline,
)
from aughor.agent.prompts_investigate import IntakeOutput


def _intake(**kw) -> IntakeOutput:
    base = dict(
        metric_label="traffic", metric_sql="SUM(TRAFFIC)",
        observation_start="2026-07-01", observation_end="2026-07-31", observation_label="July 2026",
        comparison_start="2026-06-01", comparison_end="2026-06-30", comparison_label="June 2026 (MoM)",
        date_column="traffic.all_dimesnsions_2.CALENDAR_DATE", metric_table="traffic.all_dimesnsions_2",
        dimensions=["traffic.all_dimesnsions_2.BROWSER_NAME"], intake_notes="",
    )
    base.update(kw)
    return IntakeOutput(**base)


DMIN, DMAX = "2026-06-01", "2026-08-18"


def test_specimen_window_is_described_not_compared_against_itself():
    it = _intake(observation_start="2025-02-01", observation_end="2025-02-28", observation_label="February 2025",
                 comparison_start="2025-01-01", comparison_end="2025-01-31", comparison_label="January 2025 (MoM)")
    note = _clamp_intake_to_coverage(it, DMIN, DMAX, "Why is traffic in Direkteingabe going up?")
    assert (it.observation_start, it.observation_end) == (DMIN, DMAX)
    assert it.observation_label != "February 2025"
    assert it.observation_label == "2026-06-01 → 2026-08-18"
    # no equal-length window before the full span → typed verdict, comparison CLEARED
    assert it.no_prior_period is True
    assert (it.comparison_start, it.comparison_end) == ("", "")
    assert it.comparison_label == "No prior period exists in the data"
    assert "Same period" not in it.comparison_label
    assert note and "no period before the observation window" in note


def test_a_missing_yoy_comparison_becomes_the_preceding_month():
    it = _intake(comparison_start="2025-07-01", comparison_end="2025-07-31", comparison_label="July 2025 (YoY)")
    _clamp_intake_to_coverage(it, DMIN, DMAX, "why did traffic rise in July?")
    assert it.no_prior_period is False
    assert (it.comparison_start, it.comparison_end) == ("2026-06-01", "2026-06-30")
    assert it.comparison_label.startswith("Preceding period")
    assert "June 2026" in it.comparison_label


def test_a_model_that_set_comparison_equal_to_observation_is_corrected():
    it = _intake(comparison_start="2026-07-01", comparison_end="2026-07-31", comparison_label="Same period")
    _clamp_intake_to_coverage(it, DMIN, DMAX, "why did traffic rise in July?")
    assert (it.comparison_start, it.comparison_end) == ("2026-06-01", "2026-06-30")
    assert it.no_prior_period is False


def test_a_valid_comparison_is_left_alone():
    it = _intake()
    _clamp_intake_to_coverage(it, DMIN, DMAX, "why did traffic rise in July?")
    assert (it.comparison_start, it.comparison_end) == ("2026-06-01", "2026-06-30")
    assert it.comparison_label == "June 2026 (MoM)"
    assert it.observation_label == "July 2026"
    assert it.no_prior_period is False


def test_preceding_window_shapes():
    assert _preceding_window("2026-07-01", "2026-07-31", "2026-06-01") == ("2026-06-01", "2026-06-30")
    assert _preceding_window("2026-07-01", "2026-08-31", "2026-05-01") == ("2026-05-01", "2026-06-30")
    assert _preceding_window("2026-07-10", "2026-07-20", "2026-06-01") == ("2026-06-29", "2026-07-09")
    assert _preceding_window("2026-06-01", "2026-08-18", "2026-06-01") is None
    assert _preceding_window("2026-06-03", "2026-07-03", "2026-06-01") is None   # 31 days back lands well before dmin


def test_window_label_reads_as_a_human_period():
    assert _window_label("2026-07-01", "2026-07-31") == "July 2026"
    assert _window_label("2026-06-01", "2026-08-31") == "June–August 2026"
    assert _window_label("2025-11-01", "2026-01-31") == "November 2025–January 2026"
    assert _window_label("2026-06-01", "2026-08-18") == "2026-06-01 → 2026-08-18"


def test_router_skips_period_over_period_phases_without_a_prior_period():
    state = {"question": "Why is traffic in Direkteingabe going up? What is the reason behind it?",
             "_ada_intake": {"no_prior_period": True}, "investigation_phases": []}
    assert route_after_baseline(state) == "ada_synthesize"
    # a dimension ask would normally force decomposition — not when there is nothing to compare
    state["question"] = "Which browser drove the traffic increase?"
    assert route_after_baseline(state) == "ada_synthesize"
