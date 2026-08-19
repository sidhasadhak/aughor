"""The evidence bounds confidence; the model may only lower it — CA-2.

Facts the ceiling reads off the phases: the intake spec's Comparison row saying no prior period
exists (a "why did it change" answered without a comparison cannot be HIGH), the baseline's
"significance not assessable" marker (CA-2's minimum-periods rule), and any trust caveat.
"""
from __future__ import annotations

from types import SimpleNamespace

from aughor.agent.investigate import _cap_confidence_on_trust_advisory, _evidence_confidence_ceiling


def _synth(conf="HIGH"):
    return SimpleNamespace(confidence=conf, confidence_justification="The phases converge.")


INTAKE_NO_PRIOR = {"phase_id": "intake", "phase_name": "Question Intake", "summary": "",
                   "findings": [{"finding_id": "intake_spec", "columns": ["field", "value"],
                                 "rows": [["Metric", "traffic (SUM(TRAFFIC))"],
                                          ["Comparison", "No prior period exists in the data"]]}]}
INTAKE_OK = {"phase_id": "intake", "phase_name": "Question Intake", "summary": "",
             "findings": [{"finding_id": "intake_spec", "columns": ["field", "value"],
                           "rows": [["Comparison", "June 2026 (MoM) (2026-06-01 → 2026-06-30)"]]}]}
BASELINE_SHORT = {"phase_id": "baseline", "phase_name": "Baseline",
                  "summary": "Traffic rose. [stats.py: significance not assessable — the baseline holds 2 period(s); at least 6 are needed]",
                  "findings": [{"stat_note": None, "is_significant": False}]}
BASELINE_OK = {"phase_id": "baseline", "phase_name": "Baseline", "summary": "Traffic rose. [stats.py: σ=2.40 — significant anomaly]",
               "findings": [{"stat_note": "z = 2.4 — significant", "is_significant": True}]}


def test_no_prior_period_caps_at_medium():
    ceiling, reason = _evidence_confidence_ceiling([INTAKE_NO_PRIOR, BASELINE_OK])
    assert ceiling == "MEDIUM" and "no prior period" in reason
    s = _synth("HIGH")
    assert _cap_confidence_on_trust_advisory(s, [INTAKE_NO_PRIOR, BASELINE_OK])
    assert s.confidence == "MEDIUM" and s.confidence_justification.startswith("Capped below HIGH — no prior period")


def test_short_baseline_caps_at_medium():
    ceiling, reason = _evidence_confidence_ceiling([INTAKE_OK, BASELINE_SHORT])
    assert ceiling == "MEDIUM" and "too short" in reason


def test_clean_evidence_leaves_high_alone():
    assert _evidence_confidence_ceiling([INTAKE_OK, BASELINE_OK]) == ("HIGH", "")
    s = _synth("HIGH")
    assert not _cap_confidence_on_trust_advisory(s, [INTAKE_OK, BASELINE_OK])
    assert s.confidence == "HIGH"


def test_the_model_may_only_lower():
    # a model that already said MEDIUM or LOW is never touched (the ceiling is a cap, not a floor)
    s = _synth("LOW")
    assert not _cap_confidence_on_trust_advisory(s, [INTAKE_NO_PRIOR, BASELINE_SHORT])
    assert s.confidence == "LOW"


def test_trust_caveat_still_caps():
    phases = [INTAKE_OK, {"phase_id": "decomposition", "phase_name": "D", "summary": "",
                          "findings": [{"trust_caveat": "join guard: keys share only 12% of values"}]}]
    s = _synth("HIGH")
    assert _cap_confidence_on_trust_advisory(s, phases)
    assert "trust advisory" in s.confidence_justification
