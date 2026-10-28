"""The unified ``/ask`` door — decide a question's *depth* before any body runs.

Phase 0 of merging the Insight (quick) and Deep-Analysis (investigation) paths into
one conversational entry (see ``docs/UNIFIED_ANSWER_PATH.md``). Today the user picks
a mode up front; here a **deterministic-first** router makes that call instead, so the
two existing streaming bodies (``_stream_chat`` and ``_stream_investigation``) can be
dispatched behind one endpoint without changing either.

Design invariants (from Aughor's prior conclusions — see the design doc §2/§9):

* **The shape decides, by code first.** A question's SHAPE — describe, check, diagnose,
  survey (`agent/question_shape.py`, the one vocabulary for a question's kind) — is read
  from its words with no model; the depth follows the shape (a describe or a check is
  quick, a diagnosis or a survey is deep), and the body mode is derived from both. The
  LLM classifier (``classify_question``) is a *secondary signal* consulted **only on the
  borderline** — a question no rule reads, or a read-ask the complexity assessment finds
  under-specified — and it speaks the same four words, so the latency-sensitive quick
  path pays for no extra model round-trip on the clear cases and an LLM never sits alone
  in the decision path (the R4 ablation lesson).
* **Agent versus Quick is depth only.** An explicit depth changes the budget, never the
  frame: a check at ``deep`` is still a check.
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

from aughor.agent.complexity import ComplexityVerdict, assess_complexity
from aughor.agent.question_shape import body_for, is_wide, question_shape, shape_for_body, shape_reading

Depth = Literal["quick", "deep"]

# The two bodies behind the door: "quick" -> _stream_chat (Insight),
# "deep" -> _stream_investigation (ADA / explore graph).


@dataclass(frozen=True)
class AskRoute:
    """The routing verdict for one ``/ask`` turn — the payload of the ``route`` SSE
    event the frontend renders as a depth banner with a one-click re-run."""

    depth: Depth
    mode: str                 # body mode (frozen): direct | final_text | investigate | explore
    tier: str                 # complexity tier: simple | moderate | complex
    score: float              # 0..1 difficulty
    confidence: float         # 1.0 for deterministic/explicit; classifier conf on tiebreak
    ambiguous: bool           # under-specified — the seam for the Phase-3 clarification arc
    why: str                  # one-line, user-facing reason for the depth call
    forced: Optional[str] = None           # override that decided it (not auto)
    downgraded_from: Optional[str] = None  # "deep" when capability-gated down to quick
    used_classifier: bool = False          # did the LLM tiebreak run?
    shape: str = ""                        # the question's shape: describe | check | diagnose | survey

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
            # The question's shape, on the receipt for every turn — the trace reads it while the
            # run streams, and the body it is handed to serves it (no re-reading at the door).
            "question_shape": self.shape,
        }


# A classifier returns ``(effective_mode, decision)`` where decision carries
# ``.confidence`` and ``.reasoning`` — exactly ``classify_question``'s contract — and,
# since the two classifiers speak one vocabulary, ``.shape`` when it knows it.
Classifier = Callable[[str], tuple]


def _default_classifier(question: str) -> tuple:
    # Imported lazily: nodes.py pulls in the heavy agent graph; the obvious cases
    # never reach here, so the clear-path import cost stays at zero.
    from aughor.agent.nodes import classify_question
    return classify_question(question)


# ── Wide / landscape detection → the explore wave (R9) ────────────────────────
# A genuinely BROAD question — "characterize / profile / map the landscape / how does X
# vary across …" — is answered best by the multi-cut explore subgraph (independent cuts of
# one landscape), not a single ADA investigation. This is the SURVEY shape
# (`question_shape.is_wide`): deterministic (no model in the routing decision — the R4 ablation
# lesson), and it yields to causal/driver questions, which are investigations, so it never
# poaches a real "why". It reaches the wave when a person asks for depth (`body_for`, a starter's declared path); the
# automatic route behind `explore.route_wide` was deleted 2026-10-28 (ROADMAP §3.65), off and never measured.


def is_wide_question(question: str, verdict: ComplexityVerdict) -> bool:
    """Deterministically decide whether a question is a broad *landscape* scan best served by
    the explore wave — the survey shape. ``verdict`` is accepted for the callers that pass it;
    the causal yield reads the same lexicon the verdict counted."""
    return is_wide(question)


def decide_ask_route(
    question: str,
    *,
    depth_override: str = "auto",
    deep_flag: bool = False,
    insight_id: Optional[str] = None,
    has_deep: bool = True,
    classifier: Optional[Classifier] = None,
    mode_override: Optional[str] = None,
) -> AskRoute:
    """Decide whether a ``/ask`` turn runs the quick body or the deep body.

    ``depth_override`` is the auto+transparency re-run hint (``auto`` | ``quick`` |
    ``deep``); ``deep_flag`` is the explicit "Investigate deeper" escalation;
    ``insight_id`` (without ``deep_flag``) is a dossier drill. ``has_deep`` is the
    resolved ``DEEP_ANALYSIS`` capability — a deep route degrades to quick when it is
    False. ``classifier`` is injected for testing; it defaults to ``classify_question``
    and is consulted only for borderline questions. ``mode_override`` (R13) is a named starter's declared path —
    ``investigate`` pins the deep investigation, ``explore`` pins the landscape wave; deterministic, no model call,
    explicit per request.
    """
    verdict = assess_complexity(question or "")
    # The question's shape, read once by code. None on the borderline — a question no rule
    # reads — which is the only case the model classifier is asked about.
    shape = question_shape(question or "", default=None)

    def _route(depth: Depth, mode: str, why: str, *, forced: Optional[str] = None,
               confidence: float = 1.0, used: bool = False,
               shape_said: Optional[str] = None) -> AskRoute:
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
            # The shape is the question's, whatever body an override pinned; when the
            # question's words read as none, the body implies one.
            shape=shape or shape_said or shape_for_body(mode),
        )

    # 1) Explicit overrides — deterministic, no model call. A forced depth changes the budget,
    #    never the frame: the shape rides the route and the body keeps it. ─────────────────
    if mode_override in ("investigate", "explore"):
        return _route("deep", mode_override,
                      "running the starter's chosen research path", forced="mode")
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
        return _route("deep", body_for(shape or "diagnose", "deep"), "investigating, as you asked",
                      forced="deep")

    # 2) Auto — the shape decides, by code first. The obvious cases never touch the model. ──

    # 2a) A survey is read for depth like any question (2c below). Its automatic route to the explore wave (R9,
    #     `explore.route_wide`) was off and never measured, and was deleted 2026-10-28 (ROADMAP §3.65).

    # 2b) A check is a verdict and its counts — a step or two; a diagnosis is an investigation.
    #     Left to the classifier a check was "investigate", and the deep body framed a metric, a
    #     date and a window for it (LuxExperience d14f276b, 2026-10-15).
    if shape == "check":
        return _route("quick", "direct", shape_reading("check"))
    if shape == "diagnose":
        return _route("deep", "investigate", shape_reading("diagnose"))

    # 2c) A describe is quick — unless the complexity assessment reads a multi-step question,
    #     which takes the analyst's budget and keeps its frame (depth, not kind). An
    #     under-specified read-ask ("how is performance lately?") is the borderline below.
    #     A survey follows the same depth rule.
    causal = verdict.signals.get("causal", 0) > 0
    if shape in ("describe", "survey") and not verdict.ambiguous:
        if causal or verdict.tier == "complex":
            return _route("deep", "investigate",
                          "this asks for a multi-step read — measured with the deeper budget")
        if verdict.tier == "simple" or shape == "describe":
            return _route("quick", "direct", "a direct lookup")

    # 3) Borderline — a question no rule reads, an ambiguous read-ask, or a moderate survey: the LLM classifier breaks the tie, speaking the same four shapes. This is
    #    the only path that pays for a routing model call.
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
                  used=True, shape_said=getattr(decision, "shape", "") or None)
