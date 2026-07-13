"""P5 — the adversarial-verification confidence cap + the high-stakes materiality gate.

T4-3's refuter (opt-in `ada.adversarial_verify`) fired live and recorded objections, but the
HIGH→MEDIUM confidence cap — the part that actually protects the reader from a confident wrong verdict
— was never exercised (it needs a surviving refutation of a HIGH-confidence verdict). The apply logic is
now a pure function, so the cap is tested deterministically with no LLM. P5 also adds a deterministic
materiality gate (`ada.adversarial_high_stakes`) so the refuter can earn a default-path place on the
costly-if-wrong minority without an LLM call on every decision-changing verdict.
"""
from __future__ import annotations

import types

import aughor.agent.investigate as I


def _synth(confidence="HIGH", gaps=None, just=""):
    return types.SimpleNamespace(
        confidence=confidence, confidence_justification=just,
        data_gaps=list(gaps or []), headline="X is not the problem", executive_summary="")


def _verdict(refuted=True, reason="the abstention ignores an offsetting mix shift", alt=None):
    return types.SimpleNamespace(refuted=refuted, reason=reason, alternative=alt)


# ── The cap path (the previously-unexercised part) ────────────────────────────────

def test_surviving_refutation_caps_high_to_medium():
    s = _synth(confidence="HIGH", just="Strong signal.")
    I._apply_adversarial_refutation(s, _verdict())
    assert s.confidence == "MEDIUM"
    assert "did not survive an adversarial refutation" in s.confidence_justification
    assert "Strong signal." in s.confidence_justification          # original justification preserved
    assert any("adversarial verification challenged" in g.lower() for g in s.data_gaps)


def test_refutation_note_carries_the_alternative():
    s = _synth()
    I._apply_adversarial_refutation(s, _verdict(alt="a seasonal dip, not a decline"))
    assert any("Alternative reading: a seasonal dip" in g for g in s.data_gaps)


def test_medium_confidence_is_noted_but_not_capped_further():
    # The objection is recorded, but MEDIUM is not lowered (the cap only lowers HIGH).
    s = _synth(confidence="MEDIUM")
    I._apply_adversarial_refutation(s, _verdict())
    assert s.confidence == "MEDIUM"
    assert any("adversarial verification" in g.lower() for g in s.data_gaps)


def test_non_refuting_verdict_is_a_noop():
    s = _synth(confidence="HIGH", gaps=["existing gap"], just="keep")
    I._apply_adversarial_refutation(s, _verdict(refuted=False))
    assert s.confidence == "HIGH" and s.data_gaps == ["existing gap"] and s.confidence_justification == "keep"


def test_none_verdict_is_a_noop():
    s = _synth(confidence="HIGH")
    I._apply_adversarial_refutation(s, None)
    assert s.confidence == "HIGH" and s.data_gaps == []


def test_idempotent_note_no_double_insert():
    s = _synth(confidence="MEDIUM")
    I._apply_adversarial_refutation(s, _verdict())
    I._apply_adversarial_refutation(s, _verdict())
    assert sum("adversarial verification challenged" in g.lower() for g in s.data_gaps) == 1


# ── The deterministic materiality gate ────────────────────────────────────────────

def test_full_tier_runs_on_any_decision_changing_verdict():
    assert I._adversarial_should_run(_synth("MEDIUM"), full=True, high_stakes=False)
    assert I._adversarial_should_run(_synth("LOW"), full=True, high_stakes=False)


def test_high_stakes_tier_runs_only_on_high_confidence():
    assert I._adversarial_should_run(_synth("HIGH"), full=False, high_stakes=True)
    assert not I._adversarial_should_run(_synth("MEDIUM"), full=False, high_stakes=True)
    assert not I._adversarial_should_run(_synth("LOW"), full=False, high_stakes=True)


def test_no_tier_never_runs():
    assert not I._adversarial_should_run(_synth("HIGH"), full=False, high_stakes=False)


# ── Flag registration ─────────────────────────────────────────────────────────────

def test_high_stakes_flag_registered_and_auto_elevated(monkeypatch):
    from aughor.kernel.flags import FLAG_ENV, FLAG_META, flag_enabled
    assert "ada.adversarial_high_stakes" in FLAG_ENV and "ada.adversarial_high_stakes" in FLAG_META
    # Auto-eligible + master default-ON (2026-07-13 graduation): unset ⇒ elevated; "0" kills.
    monkeypatch.delenv("AUGHOR_ADA_ADVERSARIAL_HIGH_STAKES", raising=False)
    monkeypatch.delenv("AUGHOR_CAPABILITIES_AUTO", raising=False)
    assert flag_enabled("ada.adversarial_high_stakes") is True
    monkeypatch.setenv("AUGHOR_ADA_ADVERSARIAL_HIGH_STAKES", "0")
    assert flag_enabled("ada.adversarial_high_stakes") is False
