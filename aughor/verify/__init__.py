"""Verification substrate (Bet 0) — human ground-truth capture.

The non-circular anchor for the trust economy: a system that grades its own confidence is
overconfident exactly when it's wrong. Captured human verdicts (accept / correct / reject)
are the external signal that future calibration and the self-improving flywheel must be
scored against — never self-assessment. See docs/DOMAIN_EXPERTISE_PACKS_10X.md §0.7.
"""
from aughor.verify.verdicts import (
    VERDICTS,
    record_verdict,
    verdict_stats,
    list_verdicts,
)
from aughor.verify.gate import (
    is_compoundable,
    can_act_autonomously,
    COMPOUND_MIN_CONFIDENCE,
)

__all__ = [
    "VERDICTS", "record_verdict", "verdict_stats", "list_verdicts",
    "is_compoundable", "can_act_autonomously", "COMPOUND_MIN_CONFIDENCE",
]
