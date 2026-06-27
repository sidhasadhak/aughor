"""Standing, goal-driven agents (Bet 5) — a mandate + KPI, not just Q&A.

A specialist can hold a MANDATE ("keep NRR ≥ 110%; watch it; on drift, investigate, draft the
fix, bring the receipt"). This module models the mandate and decides, on a fresh metric value,
whether it's breached and what to do — gated by the trust tier elsewhere (safe only for a
TRUSTED expert, per Bet 4). Pure; the scheduling/execution rides the existing Job Kernel.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Mandate:
    metric: str
    operator: str            # "gte" (keep ≥) | "lte" (keep ≤)
    threshold: float
    reversible_action: bool = True   # may a TRUSTED agent act without a human?


@dataclass
class MandateOutcome:
    breached: bool
    severity: str            # "ok" | "warn" | "breach"
    should_investigate: bool
    should_escalate: bool
    message: str = ""


def evaluate_mandate(mandate: Mandate, current_value: float, warn_margin: float = 0.05) -> MandateOutcome:
    """Compare a fresh metric value to the mandate. Breach → investigate; a breach that is
    severe (beyond the warn margin on the wrong side) → escalate."""
    t = mandate.threshold
    if mandate.operator == "gte":
        breached = current_value < t
        severe = current_value < t * (1 - warn_margin)
        warn = (not breached) and current_value < t * (1 + warn_margin)
    elif mandate.operator == "lte":
        breached = current_value > t
        severe = current_value > t * (1 + warn_margin)
        warn = (not breached) and current_value > t * (1 - warn_margin)
    else:
        return MandateOutcome(False, "ok", False, False, f"unknown operator {mandate.operator!r}")

    if breached:
        return MandateOutcome(
            breached=True, severity="breach", should_investigate=True, should_escalate=severe,
            message=f"{mandate.metric} = {current_value} violates {mandate.operator} {t}")
    if warn:
        return MandateOutcome(False, "warn", True, False,
                              f"{mandate.metric} = {current_value} is near the {mandate.operator} {t} threshold")
    return MandateOutcome(False, "ok", False, False, f"{mandate.metric} within mandate")
