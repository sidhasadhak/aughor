"""Evals-as-spec promotion gate (Bet 2) — a pack can't go active until it proves itself.

Evals are the DEFINITION, not an afterthought: a pack may only be promoted to `active` on a
connection when it is fully bound AND its golden/adversarial evals pass there. This is the
gate the activation flow calls; the eval RUNNER that executes each golden question against the
engine is the connection-dependent half (deferred) — it produces the EvalResult list this gate
scores. Pure; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aughor.packs.models import Pack


@dataclass
class EvalResult:
    question: str
    passed: bool
    detail: str = ""


@dataclass
class ActivationDecision:
    can_activate: bool = False
    pass_rate: Optional[float] = None
    reasons: list[str] = field(default_factory=list)   # blockers (empty iff can_activate)


def evaluate_activation(
    pack: Pack,
    eval_results: list[EvalResult],
    *,
    binding_pinned: bool,
    binding_verified: bool = True,
    missing_roles: Optional[list[str]] = None,
) -> ActivationDecision:
    """Decide whether `pack` may be promoted to active on a connection. Activation needs THREE
    distinct things, reported as separate, actionable blockers so 'evals pass' is never confused
    with 'not deployed':
      1. a DEPLOYED binding — pinned + verified (run Bind + verify), covering every role;
      2. the pack declares evals;
      3. every eval passes.
    `binding_pinned` = a binding is saved for this connection; `binding_verified` = it dry-ran;
    `missing_roles` = declared roles absent from the pinned binding."""
    reasons: list[str] = []

    # ── deployment (separate from evals) ────────────────────────────────────────
    if not binding_pinned:
        reasons.append("not deployed on this connection — run Bind + verify first")
    elif missing_roles:
        reasons.append(f"pinned binding is missing role(s): {missing_roles}")
    elif not binding_verified:
        reasons.append("binding is pinned but not verified — re-run Bind + verify")

    # ── evals ───────────────────────────────────────────────────────────────────
    if not pack.evals:
        reasons.append("pack declares no evals — cannot be promotion-gated")

    pass_rate: Optional[float] = None
    if eval_results:
        passed = sum(1 for r in eval_results if r.passed)
        pass_rate = round(passed / len(eval_results), 3)
        if passed < len(eval_results):
            failing = [r.question for r in eval_results if not r.passed][:5]
            reasons.append(f"{len(eval_results) - passed} eval(s) failing: {failing}")
    elif pack.evals:
        reasons.append("evals were not run on this connection")

    return ActivationDecision(can_activate=not reasons, pass_rate=pass_rate, reasons=reasons)
