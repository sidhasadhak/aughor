"""Trust caveat → structural, scoped to headlined figures (fix 4 + T3-1, 2026-07-09).

Deep-Analysis audit finding (inv1): a formula/computation trust_caveat fired on the evidence, but
its ONLY effect was demoting HIGH→MEDIUM confidence — the corrupted numbers still rode into the
LLM-written headline/executive_summary. `_reframe_on_trust_caveat` makes a computation-ERROR caveat
structural: lead the exec summary with the honest reframe and floor confidence to LOW.

T3-1 scopes it: floor the WHOLE report only when a flagged finding's numbers are actually HEADLINED
(the conclusion is built on a wrong number). When the flagged finding is peripheral — its numbers do
not appear in the conclusion (the inv3 case: clean channel drivers carried the answer, one internal
decomposition finding tripped) — surface the caveat in data_gaps and keep the existing cap instead of
nuking a grounded answer. See aughor/agent/investigate.py.
"""
from aughor.agent.investigate import (
    _reframe_on_trust_caveat,
    _cap_confidence_on_trust_advisory,
)


class _Synth:
    def __init__(self, confidence="HIGH", headline="", exec_summary="Fragrance refund rate is 73%."):
        self.confidence = confidence
        self.confidence_justification = ""
        self.headline = headline
        self.executive_summary = exec_summary
        self.data_gaps = []


def _phases(caveat, rows, clean_rows=None):
    """One flagged finding (with rows) + one clean finding."""
    return [{"phase_id": "cross_section", "findings": [
        {"title": "Flagged finding", "trust_caveat": caveat, "rows": rows},
        {"title": "Clean finding", "trust_caveat": None, "rows": clean_rows or [["A", "5"]]},
    ]}]


def test_headlined_error_caveat_floors_to_low_and_reframes():
    """The flagged finding's number (73) is in the exec summary → the conclusion is built on a wrong
    number → floor to LOW + reframe."""
    synth = _Synth(exec_summary="Fragrance refund rate is 73%, the worst segment.")
    phases = _phases(
        "metric-computation error: conditioned denominator — the true global refund rate is 10.4%.",
        rows=[["Fragrance", "73.0"]])
    acted = _reframe_on_trust_caveat(synth, phases)
    assert acted is True
    assert synth.confidence == "LOW"
    assert synth.executive_summary.startswith("⚠")
    assert "NOT reliable" in synth.executive_summary
    assert "73%" in synth.executive_summary          # original prose preserved


def test_peripheral_error_caveat_keeps_confidence_and_notes_gap():
    """inv3 case: the flagged finding's numbers (94939 / 7158) are NOT in the conclusion, which is
    carried by clean drivers → do NOT floor to LOW; surface the caveat in data_gaps and keep the cap."""
    synth = _Synth(confidence="MEDIUM",
                   headline="Net revenue declined -6.56%, driven by Meta channel weakness",
                   exec_summary="Meta collapsed -$45,105 (-22.39%); volume fell -110 orders.")
    phases = _phases("component exceeds total: 94939 exceeds 7158 — fan-out over-count",
                     rows=[["gross", "94939"], ["net", "7158"]])
    acted = _reframe_on_trust_caveat(synth, phases)
    assert acted is True
    assert synth.confidence == "MEDIUM"                       # NOT floored
    assert not synth.executive_summary.startswith("⚠")        # conclusion prose untouched
    assert any("trust check flagged" in g.lower() for g in synth.data_gaps)


def test_mild_advisory_does_not_trigger():
    """A caveat that does not signal a WRONG number is left to the MEDIUM cap."""
    synth = _Synth()
    phases = _phases("small sample size in one segment; interpret with care.", rows=[["x", "5"]])
    acted = _reframe_on_trust_caveat(synth, phases)
    assert acted is False
    assert synth.confidence == "HIGH"
    assert not synth.executive_summary.startswith("⚠")


def test_no_caveats_is_noop():
    synth = _Synth()
    phases = [{"phase_id": "cross_section", "findings": [{"title": "x", "trust_caveat": None, "rows": []}]}]
    assert _reframe_on_trust_caveat(synth, phases) is False
    assert synth.confidence == "HIGH"


def test_idempotent_reframe():
    """Running twice must not stack two reframe prefixes (headlined branch, salient % number)."""
    synth = _Synth(exec_summary="the fan-out ratio is 250.0% across the board.")
    phases = _phases("fan-out corrupts the ratio; grain-correct recompute needed.",
                     rows=[["seg", "250.0"]])
    _reframe_on_trust_caveat(synth, phases)
    first = synth.executive_summary
    assert first.startswith("⚠")
    _reframe_on_trust_caveat(synth, phases)
    assert synth.executive_summary == first


def test_composes_with_confidence_cap_when_headlined():
    """The mild-advisory MEDIUM cap and the computation-error LOW floor compose when the flagged
    number is headlined (as a salient % figure)."""
    synth = _Synth(confidence="HIGH", exec_summary="the fan-out ratio is 250.0%.")
    phases = _phases("metric-computation error: fan-out artifact, values not trustworthy.",
                     rows=[["seg", "250.0"]])
    _cap_confidence_on_trust_advisory(synth, phases)   # HIGH → MEDIUM
    assert synth.confidence == "MEDIUM"
    _reframe_on_trust_caveat(synth, phases)            # MEDIUM → LOW (headlined)
    assert synth.confidence == "LOW"
