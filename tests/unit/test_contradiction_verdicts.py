"""The significance-flip detector keys on code-written verdicts, not adjectives — CA-2.

Specimen cb37be54: the baseline summary said "notable peak", the decomposition summary said "no
significant variation" (over a window compared against itself), and the detector — reading
prose word-lists only — ordered the model to "resolve this tension". It also matched
`\\bsignificant\\b` inside "no significant variation", so one phase could contradict itself.
"""
from __future__ import annotations

from aughor.agent.orchestrator import _phase_significance_signal, detect_contradictions


def test_code_marker_on_the_summary_is_the_verdict():
    pos = {"phase_name": "Baseline", "summary": "Traffic rose. [stats.py: σ=2.40 — significant anomaly]", "findings": []}
    neg = {"phase_name": "Baseline", "summary": "Traffic rose. [stats.py: σ=0.40 — within normal variance]", "findings": []}
    assert _phase_significance_signal(pos) is True
    assert _phase_significance_signal(neg) is False


def test_finding_flags_and_code_notes_decide_before_prose():
    # prose says "notable", but no finding is flagged (and a code note calls it noise) → negative
    p = {"phase_name": "Decomposition",
         "summary": "A notable concentration in Desktop traffic.",
         "findings": [{"is_significant": False, "stat_note": "this ordering is not evidence of a difference"}]}
    assert _phase_significance_signal(p) is False
    # unflagged findings with no note are the same verdict: the phase claimed nothing
    assert _phase_significance_signal({"phase_name": "D", "summary": "A notable peak.",
                                       "findings": [{"is_significant": False}]}) is False
    # a flagged finding → positive, whatever the prose says
    q = {"phase_name": "Dimensional", "summary": "Everything looks within normal variance.",
         "findings": [{"is_significant": True, "stat_note": "one-way ANOVA p = 1e-26"}]}
    assert _phase_significance_signal(q) is True


def test_no_structured_signal_falls_back_to_prose():
    assert _phase_significance_signal({"phase_name": "x", "summary": "A notable peak.", "findings": []}) is None
    phases = [
        {"phase_name": "Baseline", "summary": "Revenue shows a significant anomalous drop (z=-2.4)."},
        {"phase_name": "Dimensional", "summary": "All segments are within normal variance."},
    ]
    report = detect_contradictions(phases)
    assert report.has_contradictions and report.items[0].kind == "significance_flip"


def test_no_significant_variation_is_not_read_as_both():
    # one phase saying "no significant variation" used to match the POSITIVE list too
    phases = [
        {"phase_name": "Baseline", "summary": "Traffic moved within the usual range."},
        {"phase_name": "Decomposition", "summary": "Decomposition shows no significant variation across segments."},
    ]
    assert not detect_contradictions(phases).has_contradictions


def test_the_specimen_shape_no_longer_manufactures_a_flip():
    # the baseline's prose says "notable peak" but none of its findings is flagged; the
    # decomposition's prose says "no significant variation" and none of its findings is flagged
    # either. Both phases carry the same structured verdict (no claim) — no tension to order
    # the model to resolve. The adjectives are narration, not verdicts.
    phases = [
        {"phase_name": "Baseline & Anomaly Assessment",
         "summary": "Traffic in 'Direkteingabe' experienced a notable peak of 37,925 visits in July 2026.",
         "findings": [{"is_significant": False, "stat_note": None}]},
        {"phase_name": "Metric Decomposition",
         "summary": "Decomposition shows no significant variation; the observed peak is a volume-based increase.",
         "findings": [{"is_significant": False, "stat_note": None}]},
    ]
    assert not detect_contradictions(phases).has_contradictions
