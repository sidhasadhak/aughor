"""The unified ``/ask`` door — decide a question's *depth* before any body runs.

Phase 0 of merging the Insight (quick) and Deep-Analysis (investigation) paths into
one conversational entry (see ``docs/UNIFIED_ANSWER_PATH.md``). Today the user picks
a mode up front; here a **deterministic-first** router makes that call instead, so the
two existing streaming bodies (``_stream_chat`` and ``_stream_investigation``) can be
dispatched behind one endpoint without changing either.

Design invariants (from Aughor's prior conclusions — see the design doc §2/§9):

* **Deterministic spine.** ``assess_complexity`` (pure, µs, no model) decides the
  obvious cases — a clear lookup goes ``quick``; a causal / complex question goes
  ``deep``. The LLM intent classifier (``classify_question``) is a *secondary signal*
  invoked **only on the borderline**, so the latency-sensitive quick path pays for no
  extra model round-trip on the clear cases, and an LLM never sits alone in the
  decision path (the R4 ablation lesson).
* **License-safe.** ``deep`` requires the ``DEEP_ANALYSIS`` capability; when it is
  absent the route *degrades gracefully* to ``quick`` with a transparent reason
  instead of bypassing the gate or hard-failing.
* **Explicit overrides win.** The dossier drill (``insight_id``), the "Investigate
  deeper" escalation (``deep_flag``), and the auto+transparency re-run
  (``depth_override``) are honoured deterministically, with no model call.

The decision is a pure function (``decide_ask_route``) with the classifier injected,
so it is fully unit-testable without a live LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional

from aughor.agent.complexity import assess_complexity

Depth = Literal["quick", "deep"]

# The two bodies behind the door: "quick" -> _stream_chat (Insight),
# "deep" -> _stream_investigation (ADA / explore graph).


@dataclass(frozen=True)
class AskRoute:
    """The routing verdict for one ``/ask`` turn — the payload of the ``route`` SSE
    event the frontend renders as a depth banner with a one-click re-run."""

    depth: Depth
    mode: str                 # door intent: direct | final_text | investigate | explore
    tier: str                 # complexity tier: simple | moderate | complex
    score: float              # 0..1 difficulty
    confidence: float         # 1.0 for deterministic/explicit; classifier conf on tiebreak
    ambiguous: bool           # under-specified — the seam for the Phase-3 clarification arc
    why: str                  # one-line, user-facing reason for the depth call
    forced: Optional[str] = None           # override that decided it (not auto)
    downgraded_from: Optional[str] = None  # "deep" when capability-gated down to quick
    used_classifier: bool = False          # did the LLM tiebreak run?

    def to_event(self) -> dict:
        """Serialize for the ``route`` SSE event."""
        alternatives = ["quick"] if self.depth == "deep" else ["deep"]
        return {
            "depth": self.depth,
            "mode": self.mode,
            "tier": self.tier,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 3),
            "ambiguous": self.ambiguous,
            "why": self.why,
            "alternatives": alternatives,
            "forced": self.forced,
            "downgraded_from": self.downgraded_from,
        }


# A classifier returns ``(effective_mode, decision)`` where decision carries
# ``.confidence`` and ``.reasoning`` — exactly ``classify_question``'s contract.
Classifier = Callable[[str], tuple]


def _default_classifier(question: str) -> tuple:
    # Imported lazily: nodes.py pulls in the heavy agent graph; the obvious cases
    # never reach here, so the clear-path import cost stays at zero.
    from aughor.agent.nodes import classify_question
    return classify_question(question)


def decide_ask_route(
    question: str,
    *,
    depth_override: str = "auto",
    deep_flag: bool = False,
    insight_id: Optional[str] = None,
    has_deep: bool = True,
    classifier: Optional[Classifier] = None,
) -> AskRoute:
    """Decide whether a ``/ask`` turn runs the quick body or the deep body.

    ``depth_override`` is the auto+transparency re-run hint (``auto`` | ``quick`` |
    ``deep``); ``deep_flag`` is the explicit "Investigate deeper" escalation;
    ``insight_id`` (without ``deep_flag``) is a dossier drill. ``has_deep`` is the
    resolved ``DEEP_ANALYSIS`` capability — a deep route degrades to quick when it is
    False. ``classifier`` is injected for testing; it defaults to ``classify_question``
    and is consulted only for borderline questions.
    """
    verdict = assess_complexity(question or "")

    def _route(depth: Depth, mode: str, why: str, *, forced: Optional[str] = None,
               confidence: float = 1.0, used: bool = False) -> AskRoute:
        downgraded: Optional[str] = None
        if depth == "deep" and not has_deep:
            # Cannot grant deep compute without the licence — degrade, don't bypass.
            depth = "quick"
            mode = "direct"
            downgraded = "deep"
            why = "deep analysis needs an upgrade — answering quickly instead"
            confidence = 1.0
        return AskRoute(
            depth=depth, mode=mode, tier=verdict.tier, score=verdict.score,
            confidence=confidence, ambiguous=verdict.ambiguous, why=why,
            forced=forced, downgraded_from=downgraded, used_classifier=used,
        )

    # 1) Explicit overrides — deterministic, no model call. ───────────────────────
    if insight_id and not deep_flag:
        return _route("deep", "investigate", "opening the saved finding's investigation",
                      forced="dossier")
    if deep_flag:
        return _route("deep", "investigate", "running a deeper investigation",
                      forced="deep_flag")
    if depth_override == "quick":
        return _route("quick", "direct", "answering directly, as you asked",
                      forced="quick")
    if depth_override == "deep":
        return _route("deep", "investigate", "investigating, as you asked",
                      forced="deep")

    # 2) Auto — deterministic-first. The obvious cases never touch the model. ──────
    causal = verdict.signals.get("causal", 0) > 0
    if causal or verdict.tier == "complex":
        return _route("deep", "investigate",
                      "this asks for a cause or a multi-step breakdown")
    if verdict.tier == "simple" and not verdict.ambiguous:
        return _route("quick", "direct", "a direct lookup")

    # 3) Borderline (moderate, or simple-but-ambiguous) — the LLM intent classifier
    #    breaks the tie. This is the only path that pays for a routing model call.
    classify = classifier or _default_classifier
    try:
        effective_mode, decision = classify(question)
    except Exception:
        # Never fail the turn on a routing hiccup: a moderate question is safer deep.
        return _route("deep", "investigate", "investigating to be thorough")
    depth: Depth = "deep" if effective_mode in ("investigate", "explore") else "quick"
    why = getattr(decision, "reasoning", "") or (
        "investigating" if depth == "deep" else "answering directly")
    return _route(depth, effective_mode, why,
                  confidence=float(getattr(decision, "confidence", 1.0) or 1.0),
                  used=True)
