"""Report-quality wiring gap #2 — reconcile confidence with the trust advisory.

A report cannot honestly stand at HIGH confidence while a trust advisory (an
unverified/flagged finding) is shown unreconciled beneath it. The GMV brand-tier
report did exactly that: "High confidence" beside "claim not grounded". The floor
caps HIGH -> MEDIUM when any finding carries a trust_caveat. Deliberately downstream
of the claim-grounding check being derived-number-aware (#3) so a valid % derivation
never costs confidence.
"""
from types import SimpleNamespace

from aughor.agent.investigate import (
    _cap_confidence_on_trust_advisory,
    _reframe_on_pop_duration_mismatch,
    _POP_MISMATCH_SIGNATURE,
)


def _synth(conf="HIGH", just=""):
    return SimpleNamespace(confidence=conf, confidence_justification=just)


def _phases(*caveats):
    """One phase whose findings carry the given trust_caveats (None = a clean finding)."""
    return [{"findings": [{"trust_caveat": c} for c in caveats]}]


class TestTrustAdvisoryFloor:
    def test_high_capped_to_medium_when_caveat_fires(self):
        s = _synth("HIGH", "multiple phases converge on the cause")
        assert _cap_confidence_on_trust_advisory(s, _phases("claim not grounded: ...")) is True
        assert s.confidence == "MEDIUM"
        assert "trust advisory" in s.confidence_justification.lower()
        # the LLM's original justification is preserved, not discarded
        assert "multiple phases converge" in s.confidence_justification

    def test_high_untouched_when_no_caveat(self):
        s = _synth("HIGH", "solid")
        assert _cap_confidence_on_trust_advisory(s, _phases(None, None)) is False
        assert s.confidence == "HIGH"

    def test_medium_never_promoted_or_touched(self):
        s = _synth("MEDIUM")
        assert _cap_confidence_on_trust_advisory(s, _phases("caveat")) is False
        assert s.confidence == "MEDIUM"

    def test_multiple_caveats_are_counted(self):
        s = _synth("HIGH")
        _cap_confidence_on_trust_advisory(s, _phases("c1", "c2", "c3"))
        assert s.confidence == "MEDIUM"
        assert "+2 more" in s.confidence_justification

    def test_none_synth_and_empty_phases_are_safe(self):
        assert _cap_confidence_on_trust_advisory(None, _phases("c")) is False
        assert _cap_confidence_on_trust_advisory(_synth("HIGH"), []) is False
        assert _cap_confidence_on_trust_advisory(_synth("HIGH"), [{"findings": []}]) is False


def _synth_full(**kw):
    base = dict(
        confidence="HIGH", confidence_justification="",
        executive_summary="Total GMV rose +€39,945,224 across all brand tiers.",
        attribution_waterfall=[{"amount_label": "+€14.8M", "pct_of_total": 37}],
        data_gaps=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestPoPDurationReframe:
    """Enforcing half of fix #1: when the coverage clamp flagged a duration mismatch, the
    synthesis is deterministically reframed to run-rate rather than trusting the narrator."""

    def test_reframe_fires_on_signature(self):
        s = _synth_full()
        intake_data = {"intake_notes": f"DATA COVERAGE: prior window is {_POP_MISMATCH_SIGNATURE}, "
                                       "not run-rate shifts; report run-rate."}
        assert _reframe_on_pop_duration_mismatch(s, intake_data, "why did total GMV change?") is True
        assert s.attribution_waterfall == []                    # absolute decomposition neutralised
        assert "run-rate" in s.executive_summary.lower()        # reframed to run-rate
        assert "€39,945,224" in s.executive_summary             # original summary preserved after reframe
        assert any("run-rate" in g.lower() for g in s.data_gaps)

    def test_no_signature_is_no_op(self):
        s = _synth_full()
        wf = s.attribution_waterfall
        assert _reframe_on_pop_duration_mismatch(s, {"intake_notes": "ordinary clip note"}, "q") is False
        assert s.attribution_waterfall is wf                    # untouched
        assert "run-rate" not in (s.executive_summary or "").lower()

    def test_idempotent_second_pass(self):
        s = _synth_full()
        intake_data = {"intake_notes": _POP_MISMATCH_SIGNATURE}
        _reframe_on_pop_duration_mismatch(s, intake_data, "q")
        es1 = s.executive_summary
        _reframe_on_pop_duration_mismatch(s, intake_data, "q")  # must not double-prepend
        assert s.executive_summary == es1

    def test_none_synth_safe(self):
        assert _reframe_on_pop_duration_mismatch(None, {"intake_notes": _POP_MISMATCH_SIGNATURE}, "q") is False
