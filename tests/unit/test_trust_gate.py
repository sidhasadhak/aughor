"""The trust gate (§0.4) — what may consume a run (2026-06-27).

Makes 'nothing consumes a run above its earned trust' executable: the flywheel may compound
only verified runs; autonomy additionally needs reversibility. See aughor/verify/gate.py.
"""
from aughor.verify import is_compoundable, can_act_autonomously
from aughor.agent.state import VerificationManifest, VerificationCheck


def _manifest(coverage=1.0, earned=0.9, checks=None):
    return VerificationManifest(
        checks=checks or [], coverage=coverage, earned_confidence=earned,
        confidence_band="high" if earned >= 0.7 else "low", data_trust=1.0, signals=[],
    )


def test_verified_run_is_compoundable():
    ok, reasons = is_compoundable(_manifest())
    assert ok and reasons == []


def test_low_confidence_blocks_compounding():
    ok, reasons = is_compoundable(_manifest(earned=0.4))
    assert not ok and any("earned confidence" in r for r in reasons)


def test_incomplete_coverage_blocks():
    ok, reasons = is_compoundable(_manifest(coverage=0.75))
    assert not ok and any("coverage" in r for r in reasons)


def test_refuted_headline_blocks():
    chk = VerificationCheck(name="adversarial_refute", label="x", status="ran",
                            detail="a skeptic REFUTED the headline — confidence demoted")
    ok, reasons = is_compoundable(_manifest(checks=[chk]))
    assert not ok and any("refuted" in r for r in reasons)


def test_triangulation_divergence_blocks():
    chk = VerificationCheck(name="triangulation", label="x", status="ran",
                            detail="paths DISAGREE — the rate is unreliable")
    ok, reasons = is_compoundable(_manifest(checks=[chk]))
    assert not ok and any("triangulation" in r for r in reasons)


def test_silent_stats_failure_blocks():
    chk = VerificationCheck(name="stats_attached", label="x", status="not_run")
    ok, reasons = is_compoundable(_manifest(checks=[chk]))
    assert not ok and any("silently failed" in r for r in reasons)


def test_no_manifest_is_never_compoundable():
    ok, reasons = is_compoundable(None)
    assert not ok and reasons


def test_autonomy_requires_reversibility():
    m = _manifest()
    assert can_act_autonomously(m, reversible=True)[0] is True
    ok, reasons = can_act_autonomously(m, reversible=False)
    assert not ok and any("irreversible" in r for r in reasons)


def test_autonomy_blocked_when_run_unverified_even_if_reversible():
    ok, reasons = can_act_autonomously(_manifest(earned=0.3), reversible=True)
    assert not ok and reasons
