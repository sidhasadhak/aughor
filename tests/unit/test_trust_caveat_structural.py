"""Trust caveat → structural, not just a confidence label (fix 4, 2026-07-09).

Deep-Analysis audit finding (inv1): a formula/computation trust_caveat fired on the evidence, but
its ONLY effect was demoting HIGH→MEDIUM confidence — the corrupted numbers still rode into the
LLM-written headline/executive_summary (a 73% refund rate the guard had already flagged as a
conditioned-denominator artifact). `_reframe_on_trust_caveat` makes a computation-ERROR caveat
structural: lead the exec summary with the honest reframe and floor confidence to LOW, while a mild
advisory keeps the existing MEDIUM cap. See aughor/agent/investigate.py.
"""
from aughor.agent.investigate import (
    _reframe_on_trust_caveat,
    _cap_confidence_on_trust_advisory,
)


class _Synth:
    def __init__(self, confidence="HIGH", exec_summary="Fragrance refund rate is 73%."):
        self.confidence = confidence
        self.confidence_justification = ""
        self.executive_summary = exec_summary


def _phases_with_caveat(caveat):
    return [{"phase_id": "cross_section", "findings": [
        {"title": "Refund rate by segment", "trust_caveat": caveat},
        {"title": "Clean finding", "trust_caveat": None},
    ]}]


def test_computation_error_caveat_floors_to_low_and_reframes():
    synth = _Synth()
    phases = _phases_with_caveat(
        "metric-computation error: conditioned denominator — the true global refund rate is 10.4%.")
    acted = _reframe_on_trust_caveat(synth, phases)
    assert acted is True
    assert synth.confidence == "LOW"
    assert synth.executive_summary.startswith("⚠")
    assert "NOT reliable" in synth.executive_summary
    # the original prose is preserved after the reframe
    assert "73%" in synth.executive_summary


def test_mild_advisory_does_not_trigger_reframe():
    """A caveat that does not signal a WRONG number leaves the summary/confidence to the MEDIUM cap."""
    synth = _Synth()
    phases = _phases_with_caveat("small sample size in one segment; interpret with care.")
    acted = _reframe_on_trust_caveat(synth, phases)
    assert acted is False
    assert synth.confidence == "HIGH"          # untouched by this reframer
    assert not synth.executive_summary.startswith("⚠")


def test_no_caveats_is_noop():
    synth = _Synth()
    phases = [{"phase_id": "cross_section", "findings": [{"title": "x", "trust_caveat": None}]}]
    assert _reframe_on_trust_caveat(synth, phases) is False
    assert synth.confidence == "HIGH"


def test_idempotent_reframe():
    """Running twice must not stack two reframe prefixes."""
    synth = _Synth()
    phases = _phases_with_caveat("fan-out corrupts the ratio; grain-correct recompute needed.")
    _reframe_on_trust_caveat(synth, phases)
    first = synth.executive_summary
    _reframe_on_trust_caveat(synth, phases)
    assert synth.executive_summary == first


def test_composes_with_confidence_cap():
    """The mild-advisory MEDIUM cap and the computation-error LOW floor compose: an error caveat
    ends at LOW regardless of the cap running first."""
    synth = _Synth(confidence="HIGH")
    phases = _phases_with_caveat("metric-computation error: fan-out artifact, values not trustworthy.")
    _cap_confidence_on_trust_advisory(synth, phases)   # HIGH → MEDIUM
    assert synth.confidence == "MEDIUM"
    _reframe_on_trust_caveat(synth, phases)            # MEDIUM → LOW
    assert synth.confidence == "LOW"
