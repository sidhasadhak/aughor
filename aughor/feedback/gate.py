"""The trust gate (§0.4) — what may consume a run, made executable.

The rule that keeps the 10x tower safe: *nothing consumes a run above its earned trust.*
This module turns that invariant into a predicate the downstream bets call:
  • the flywheel (Bet 1) may COMPOUND only verified runs (else garbage compounds);
  • autonomous action (Bet 5) additionally requires the action be reversible or human-gated.

Pure functions over the VerificationManifest the substrate already produces. No I/O, no LLM.
"""
from __future__ import annotations

from typing import Optional

from aughor.agent.state import VerificationManifest

# A run must reach at least this earned confidence to be allowed to compound into an expert.
COMPOUND_MIN_CONFIDENCE = 0.7


def is_compoundable(
    manifest: Optional[VerificationManifest],
    min_confidence: float = COMPOUND_MIN_CONFIDENCE,
) -> tuple[bool, list[str]]:
    """May the self-improving flywheel learn from this run? True only when it is VERIFIED:
    every guard ran, earned confidence clears the bar, and no check actively failed
    (refuted headline, triangulation divergence, or a silent stats failure). Returns
    (allowed, blocking_reasons) — reasons is empty iff allowed."""
    if manifest is None:
        return False, ["no verification manifest — run is unverified"]

    reasons: list[str] = []
    if manifest.coverage < 1.0:
        reasons.append("not all guards ran (coverage < 100%)")
    if manifest.earned_confidence < min_confidence:
        reasons.append(f"earned confidence {manifest.earned_confidence} < {min_confidence}")

    for c in manifest.checks:
        detail = (c.detail or "")
        if c.name == "stats_attached" and c.status == "not_run":
            reasons.append("statistical signals silently failed to attach")
        if c.name == "triangulation" and "DISAGREE" in detail:
            reasons.append("a rate failed independent-path triangulation")
        if c.name == "adversarial_refute" and c.status == "ran" and "REFUTED" in detail:
            reasons.append("the headline was refuted by the adversarial pass")

    return (not reasons), reasons


def can_act_autonomously(
    manifest: Optional[VerificationManifest],
    reversible: bool,
    min_confidence: float = COMPOUND_MIN_CONFIDENCE,
) -> tuple[bool, list[str]]:
    """May a standing agent ACT on this run without a human? Requires the run be compoundable
    AND the action reversible (an irreversible action always needs a human gate). Returns
    (allowed, blocking_reasons)."""
    ok, reasons = is_compoundable(manifest, min_confidence)
    reasons = list(reasons)
    if not reversible:
        reasons.append("action is irreversible — requires a human gate")
    return (ok and reversible), reasons
