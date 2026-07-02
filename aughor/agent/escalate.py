"""Progressive escalation — when a cheap answer doesn't settle the question, offer depth.

Phase 5 of the unified-answer-path arc (``docs/UNIFIED_ANSWER_PATH.md``): the BIRD-INTERACT
"interaction is a scaling axis" idea (the ITS Law). The router starts a question on the
cheap path; if the *result* turns out inconclusive, the agent should be able to escalate to
the deep investigation instead of leaving the user with a thin answer.

Done as **auto + transparency**: this is a deterministic *suggestion*, not a forced re-run —
it emits an "investigate this?" affordance the user clicks (which re-runs the same question
at ``depth=deep``), with a one-line reason. Suggesting (not auto-escalating) keeps it cheap
and unsurprising, and respects the read-first / no-runaway-cost posture.

Deterministic and low-false-positive by design (no model): it fires only on clear signals —
an errored query, an empty result on an analytical question, or a causal "why" answered by a
single shallow figure. Pure, so it runs at the end of the quick path for free, and is
unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from aughor.agent.complexity import assess_complexity

Signal = str  # "error" | "no_rows" | "causal_thin"


@dataclass(frozen=True)
class EscalationVerdict:
    """Whether to offer a deeper investigation after a quick answer, and why."""
    should_offer: bool
    signal: Signal = ""
    reason: str = ""

    def to_event(self) -> dict:
        return {"signal": self.signal, "reason": self.reason}


def assess_escalation(question: str, *, columns=None, rows=None, error: str = "",
                      route_depth: str = "quick") -> EscalationVerdict:
    """Decide whether a quick answer should offer to escalate to a deep investigation.

    Only the cheap path escalates (``route_depth == "quick"``). Conservative: a healthy
    direct lookup ("what is total revenue?" → one number) does NOT escalate — only a
    genuinely inconclusive result does."""
    if route_depth != "quick":
        return EscalationVerdict(False)

    rows = rows or []
    n = len(rows)
    verdict = assess_complexity(question or "")
    causal = verdict.signals.get("causal", 0) > 0
    # Analytical intent (a breakdown / cause / comparison / multi-step) — distinguishes a
    # meaningful empty result from a legitimately-empty trivial lookup ("orders today" → 0).
    analytical = any(verdict.signals.get(k, 0) > 0
                     for k in ("aggregate", "causal", "compare", "multistep"))

    # 1. The quick query errored — the deep path carries the repair battery + decomposition.
    if error:
        return EscalationVerdict(
            True, "error",
            "the quick query hit an error — a full investigation can repair and decompose it",
        )

    # 2. Empty result on an analytical question — a wrong filter (cf. the 'Womenswear' case),
    #    a grain issue, or genuinely nothing; the investigation checks filters + finds what's there.
    if n == 0 and analytical:
        return EscalationVerdict(
            True, "no_rows",
            "the quick query returned no rows — an investigation can check the filters and surface what's there",
        )

    # 3. A causal "why / what drove" question answered by a single shallow figure — wants drivers.
    if causal and n <= 1:
        return EscalationVerdict(
            True, "causal_thin",
            "you asked why — a deeper investigation can decompose the drivers",
        )

    return EscalationVerdict(False)
