"""AT-1/2/3 — the claim licence, the pitfall vocabulary, and percent-scale grounding.

Specimens are from seven live runs of one question ("Is there a correlation between shipping
delay and customer location?", `workspace/data_co`) on 2026-08-16. Run 3's headline claimed a
cause over a cross-sectional scan; run 4 and run 7 called p = 2.4e-155 "insignificant"; run 1
shipped a grounding violation over three correct percentages. Each test below is one of those.
"""
import re

import pytest

from aughor.agent.claim_type import (admissible_verbs_directive, is_at_least,
                                     overreaching_sentences, resolve_claim_type)
from aughor.agent.investigate import _stamp_claim_type
from aughor.agent.report_checks import (PITFALLS, check_claim_type, check_grounding, pitfall,
                                        run_report_checks)


# ── the licence a design carries ─────────────────────────────────────────────

def test_a_cross_sectional_scan_licences_association_only():
    """The run-3 design. It can show two things travel together; it cannot show a cause."""
    claim_type, why = resolve_claim_type(cross_sectional=True, has_time_axis=False)
    assert claim_type == "associational"
    assert "cannot show that one brings the other about" in why


def test_a_period_comparison_licences_description_only():
    claim_type, _ = resolve_claim_type(cross_sectional=False, has_time_axis=True)
    assert claim_type == "descriptive"


def test_an_intervention_column_licences_causation():
    claim_type, why = resolve_claim_type(cross_sectional=True, has_time_axis=False,
                                         intervention_column="treatment_arm")
    assert claim_type == "causal"
    assert "treatment_arm" in why


def test_a_user_assumption_licences_causation_as_a_stated_premise():
    """A user may own an assumption the data cannot establish — but the report says so."""
    claim_type, why = resolve_claim_type(cross_sectional=True, has_time_axis=False,
                                         user_assumption="assume the promotion caused the lift")
    assert claim_type == "causal"
    assert "premise rather than a finding" in why


def test_a_model_may_narrow_the_licence_but_never_widen_it():
    """The whole point. A model that could promote its own licence would grant itself the
    causal language this module exists to withhold."""
    narrowed, _ = resolve_claim_type(cross_sectional=True, has_time_axis=False,
                                     declared="descriptive")
    assert narrowed == "descriptive"
    widened, _ = resolve_claim_type(cross_sectional=True, has_time_axis=False, declared="causal")
    assert widened == "associational"


def test_the_ladder_orders_correctly():
    assert is_at_least("causal", "associational")
    assert not is_at_least("associational", "causal")
    assert not is_at_least("", "descriptive")


# ── what the licence admits ──────────────────────────────────────────────────

_RUN3_HEADLINE = ("Shipping delay is correlated with geography, driven by localized "
                  "state-level bottlenecks rather than regional trends.")


def test_the_run3_headline_is_refused_under_an_associational_licence():
    hits = overreaching_sentences(_RUN3_HEADLINE, "associational")
    assert hits and hits[0][1].lower().startswith("driven")


def test_the_same_sentence_passes_when_the_design_earned_it():
    assert overreaching_sentences(_RUN3_HEADLINE, "causal") == []


@pytest.mark.parametrize("sentence", [
    "Shipping delays are not correlated with customer location across any geographic dimension.",
    "Location does not drive shipping delay.",
    "There is no evidence that geography causes the variation.",
    "Customer city explains only 1.1% of the variation and is not a driver of delay.",
    "Delays are consistent across all customer locations with negligible geographic impact.",
])
def test_an_honest_null_answer_is_never_overreach(sentence):
    """The report SAYING IT FOUND NOTHING must survive every gate — it necessarily uses the
    vocabulary it is denying. Four word-list guards in one day convicted prose that agreed
    with them; this is the regression test for all of them."""
    assert overreaching_sentences(sentence, "associational") == []


def test_a_correlation_claim_is_refused_under_a_descriptive_licence():
    hits = overreaching_sentences("Delay is correlated with customer city.", "descriptive")
    assert hits


def test_an_associational_claim_is_fine_under_an_associational_licence():
    assert overreaching_sentences("Delay is correlated with customer city.",
                                  "associational") == []


def test_the_directive_names_the_verbs_and_the_reason():
    d = admissible_verbs_directive("associational", "this is a cross-sectional scan")
    assert "cross-sectional scan" in d
    assert "correlated" in d and "may NOT" in d
    assert "driver" in d and "bottleneck" in d


# ── the check ────────────────────────────────────────────────────────────────

class _Synth:
    def __init__(self, headline, summary=""):
        self.headline = headline
        self.executive_summary = summary
        self.closing_summary = ""
        self.attribution_waterfall = []
        self.data_gaps = []


def test_the_check_catches_the_live_overreach_and_cites_the_pitfall():
    v = check_claim_type("associational", _RUN3_HEADLINE)
    assert v and v[0].startswith("#15 (correlation asserted as causation):")


def test_the_check_is_silent_without_a_licence():
    """No claim type resolved (an older investigation, a path that does not set it) means no
    verdict — a check that cannot decide says nothing."""
    assert check_claim_type("", _RUN3_HEADLINE) == []


def test_a_causal_licence_never_gates_the_report():
    assert check_claim_type("causal", _RUN3_HEADLINE) == []


def test_the_run7_report_passes_the_licence_gate():
    """Run 7's conclusion was right; only its justification was wrong. The licence check must
    not add noise to a report the other checks already handle."""
    synth = _Synth(
        "Shipping delays are not correlated with customer location across any geographic dimension.",
        "There is no meaningful correlation between customer location and shipping delays.")
    assert check_claim_type("associational", synth.headline + " " + synth.executive_summary) == []


def test_run_report_checks_threads_the_licence():
    synth = _Synth(_RUN3_HEADLINE, "Ilam drives the delay.")
    v = run_report_checks(synth, "does location matter?", "evidence", None, "associational")
    assert any("#15" in s for s in v)


# ── intake stamps it ─────────────────────────────────────────────────────────

class _Intake:
    def __init__(self, cross_sectional=True, date_column="", intervention_column="",
                 claim_type_suggestion=""):
        self.cross_sectional = cross_sectional
        self.date_column = date_column
        self.intervention_column = intervention_column
        self.claim_type_suggestion = claim_type_suggestion
        self.intake_notes = "original notes"


def test_intake_records_the_licence_and_its_reason():
    intake = _Intake()
    assert _stamp_claim_type(intake, "Is there a correlation between delay and location?") == \
        "associational"
    assert intake.claim_type_suggestion == "associational"
    assert intake.intake_notes.startswith("CLAIM LICENCE: associational —")
    assert "original notes" in intake.intake_notes


def test_a_user_written_assumption_in_the_question_reaches_the_licence():
    intake = _Intake()
    got = _stamp_claim_type(intake, "Assuming the promotion caused the lift, how big was it?")
    assert got == "causal"
    assert "premise" in intake.intake_notes


def test_an_ordinary_question_never_reaches_causal():
    intake = _Intake()
    assert _stamp_claim_type(intake, "Why did revenue drop in March?") == "associational"


# ── AT-2: the pitfall vocabulary ─────────────────────────────────────────────

def test_every_enforced_pitfall_is_documented():
    """The doc and the registry are one contract; a row claiming enforcement without a check
    reads as covered when it is not."""
    from pathlib import Path
    doc = Path(__file__).resolve().parents[2] / "docs" / "PITFALLS.md"
    text = doc.read_text()
    enforced = text.split("## Advisory")[0]
    for number, name in PITFALLS.items():
        assert re.search(rf"^\|\s*{number}\s*\|", enforced, re.M), f"#{number} undocumented"
        assert name in enforced, f"#{number} name drifted from the doc"


def test_the_prefix_reads_as_a_citation():
    assert pitfall(3) == "#3 (statistically significant is not important):"
    assert pitfall(999) == "#999:"


def test_the_live_violations_all_cite_a_number():
    """A reader meets a pitfall number in `confidence_justification`; it has to be there."""
    synth = _Synth("Ilam drives delay", "The 3.2 day figure at 91827.5 is notable.")
    phases = [{"phase_name": "x", "findings": [{
        "sql": "", "columns": ["Order State", "m", "n"], "rows": [["Ilam", "3.2", "5"]],
        "row_count": 15, "error": None, "interpretation": "", "trust_caveat": None,
        "key_numbers": [], "chart_type": "bar_horizontal", "is_significant": False,
        "stat_note": "This ordering is not evidence of a difference (p = 0.8274)."}]}]
    v = run_report_checks(synth, "q", "evidence log with no such number", phases, "associational")
    assert v
    assert all(s.startswith("#") for s in v), v


# ── AT-3: percent-scale grounding ────────────────────────────────────────────

def test_a_percentage_is_grounded_by_the_fraction_it_came_from():
    """Run 1 shipped "these figures do not appear anywhere in FULL EVIDENCE" over 73.21,
    81.32 and 60.27 — every one correct, stored as a fraction."""
    evidence = ("Customer City | metric_total | n\nDenton | 0.8131868131868132 | 91\n"
                "Tulare | 0.7321428571428571 | 56\nNM | 0.6027397260273972 | 146")
    prose = ("City-level rates range from 73.21% to 81.32%, while state-level rates reach "
             "60.27%.")
    assert check_grounding(prose, evidence) == []


def test_a_fraction_is_grounded_by_the_percentage_it_came_from():
    assert check_grounding("The rate is 0.55 of all orders.",
                           "segment | rate\nLate | 54.83") == []


def test_a_fabricated_figure_is_still_caught():
    """The cross-scale widening must not blind the check — this is the failure it exists for."""
    v = check_grounding("Revenue reached 48,120 in March.", "month | revenue\nMarch | 31002")
    assert v and "#36" in v[0]


def test_an_ordinary_magnitude_does_not_manufacture_a_match():
    """406.08 must not ground a claimed 40608 — the scale widening is bounded to rate ranges."""
    v = check_grounding("The total was 40608 units.", "item | total\nwidget | 406.08")
    assert v
