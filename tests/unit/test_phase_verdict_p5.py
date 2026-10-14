"""P5 of the canvas-output study (2026-10-14): machinery text out of the reader's prose.

Measured on 88 stored reports: 16 phase summaries carried "[stats.py: σ=3.88 — significant
anomaly]" — the machine's bracket inside the one sentence the reader sees for the phase; findings
that contradicted their verdict read "<verdict> The phase narrator wrote: <sentence>" — two
voices and a stage direction in one paragraph; and the "not independently challenged" caveat
carried the machine's reason ("the check runs only on a HIGH-confidence verdict…"). The same
facts now ride slots of their own — the phase's `verdict`, the finding's `stat_note`,
`causal_checks.refutation.why` — and every reader of the bracket reads the slot first."""
from __future__ import annotations

import aughor.agent.investigate as I
from aughor.agent.orchestrator import _phase_significance_signal, _states_normal_variance, phase_verdict
from aughor.export.document import _build_ada


def test_the_baseline_verdict_is_a_slot_with_the_sigma_the_bool_and_the_words():
    assert I.baseline_verdict(3.876, True) == {"sigma": 3.88, "significant": True, "text": "σ = 3.88 — significant anomaly"}
    assert I.baseline_verdict(0.16, False) == {"sigma": 0.16, "significant": False, "text": "σ = 0.16 — within normal variance"}
    short = I.baseline_verdict(None, None, 3)
    assert short["significant"] is None and short["sigma"] is None
    assert short["text"].startswith("significance not assessable — the baseline holds 2 period(s)")
    assert I.baseline_verdict(None, None, None) is None               # code tested nothing
    assert I.baseline_verdict(None, None, I._MIN_BASELINE_PERIODS) is None


def test_the_phase_carries_the_verdict_and_its_summary_carries_no_bracket():
    phase = I._phase_result("baseline", "Baseline", "", "complete", "Revenue rose 1.1%.", [],
                            verdict=I.baseline_verdict(0.73, False))
    assert phase["verdict"] == {"sigma": 0.73, "significant": False, "text": "σ = 0.73 — within normal variance"}
    assert "stats.py" not in phase["summary"] and "[" not in phase["summary"]
    bare = I._phase_result("decomposition", "D", "", "complete", "AOV rose.", [])
    assert "verdict" not in bare                                       # absent on a phase code did not test


def test_the_contradiction_scan_reads_the_slot_first_and_the_bracket_on_older_phases():
    slot = {"phase_name": "Baseline", "summary": "Revenue rose 1.1%.", "findings": [],
            "verdict": {"sigma": 0.73, "significant": False, "text": "σ = 0.73 — within normal variance"}}
    assert phase_verdict(slot) is False and _phase_significance_signal(slot) is False
    assert _states_normal_variance(slot) is True
    slot_pos = {**slot, "verdict": {"sigma": 2.4, "significant": True, "text": "σ = 2.40 — significant anomaly"}}
    assert phase_verdict(slot_pos) is True and _states_normal_variance(slot_pos) is False
    unassessable = {**slot, "verdict": {"sigma": None, "significant": None, "text": "significance not assessable — …"}}
    assert phase_verdict(unassessable) is None and _phase_significance_signal(unassessable) is None
    older = {"phase_name": "Baseline", "summary": "Traffic rose. [stats.py: σ=0.40 — within normal variance]", "findings": []}
    assert phase_verdict(older) is False and _states_normal_variance(older) is True


def test_the_confidence_ceiling_reads_a_short_baseline_from_the_slot():
    intake = {"phase_id": "intake", "phase_name": "Question Intake", "summary": "", "findings": [
        {"finding_id": "intake_spec", "columns": ["field", "value"], "rows": [["Comparison", "June 2026"]]}]}
    short = {"phase_id": "baseline", "phase_name": "Baseline", "summary": "Traffic rose.",
             "verdict": I.baseline_verdict(None, None, 3), "findings": [{"stat_note": None, "is_significant": False}]}
    assert I._evidence_confidence_ceiling([intake, short]) == ("MEDIUM", "the baseline is too short for a significance verdict")
    ok = {**short, "verdict": I.baseline_verdict(2.4, True)}
    assert I._evidence_confidence_ceiling([intake, ok]) == ("HIGH", "")


def test_the_narrator_reads_the_verdict_in_words_beside_the_summary():
    phase = I._phase_result("baseline", "Baseline", "", "complete", "Revenue rose 1.1%.", [],
                            verdict=I.baseline_verdict(0.73, False))
    text = I._phases_summary([phase])
    assert "[Baseline] Revenue rose 1.1%." in text and "CODE VERDICT: σ = 0.73 — within normal variance" in text
    assert "stats.py" not in text


def test_a_contradicting_interpretation_keeps_its_sentence_and_the_verdict_goes_to_the_note():
    f = {"interpretation": "The significantly higher delay in Oklahoma suggests a localized performance issue.",
         "is_significant": True, "stat_note": "z = 2.1"}
    I._lead_with_verdict(f, "This ordering is not evidence of a difference.")
    assert f["interpretation"] == "The significantly higher delay in Oklahoma suggests a localized performance issue."
    assert f["stat_note"] == "This ordering is not evidence of a difference. z = 2.1"
    assert f["is_significant"] is False
    again = dict(f)
    I._lead_with_verdict(again, "This ordering is not evidence of a difference.")
    assert again["stat_note"] == f["stat_note"]                        # not stacked twice


def test_the_unchallenged_cause_caveat_keeps_the_machines_reason_off_the_page():
    report = {"headline": "The price rise drove the drop in orders.", "executive_summary": "Orders fell 12%.",
              "closing_summary": "", "recommendations": [], "data_gaps": []}
    I._attach_causal_checks(report, "causal", {"status": "not_run", "why": "the check runs only on a HIGH-confidence verdict, and this one is MEDIUM"})
    assert report["data_gaps"] == ["Not independently challenged: this report names a cause, and no check tried to refute it."]
    assert report["causal_checks"]["refutation"]["why"].startswith("the check runs only on a HIGH-confidence")


def test_the_document_prints_the_verdict_small_under_the_summary():
    finding = {"finding_id": "baseline_0", "title": "Monthly revenue", "sql": "SELECT 1", "columns": ["month", "revenue"],
               "rows": [["2026-08", 627.9], ["2026-09", 721.8]], "row_count": 2, "error": None, "interpretation": "Up in September.",
               "key_numbers": [], "chart_type": "line", "stat_note": None, "is_significant": False}
    rep = {"headline": "h", "executive_summary": "e", "phases": [
        {"phase_id": "baseline", "phase_name": "Baseline", "summary": "Revenue rose 1.1%.", "status": "complete",
         "verdict": I.baseline_verdict(0.73, False), "findings": [finding]}]}
    blocks = _build_ada({"id": "x", "question": "q", "report": rep}).blocks
    kinds = [(b.kind, b.tag, b.text) for b in blocks if b.kind == "prose"]
    assert ("prose", "", "Revenue rose 1.1%.") in kinds
    assert ("prose", "Verdict", "σ = 0.73 — within normal variance") in kinds
