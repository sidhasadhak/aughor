"""A question's SHAPE — the one word for its kind, decided from its words before any body runs.

Four shapes, and the same four everywhere a question's kind is named: the ``/ask`` door's
router, the model classifier it consults on the borderline, the analyst's roster and stopping
rule, the narrator's door, the frame's reading, the report and the trace.

* ``describe`` — asks to SEE the data: a figure, a ranking, a trend, a comparison across
  segments or periods. Answered by measuring what was asked and stating it.
* ``check`` — asks to VERIFY a property of the data or the model: do these keys join, are
  there duplicates or orphans, does one table agree with another, is a value ever null. It
  frames no metric, no window and no cause; it is answered with a verdict and the counts that
  carry it.
* ``diagnose`` — asks WHY, asks what to DO, or hunts WHERE value is weak or lost. An
  investigation: a period, a baseline, hypotheses, a cause named with its size.
* ``survey`` — asks for the LANDSCAPE: characterise, profile, map, how does X vary across …
  Many cuts of one scene; the explore wave when it is available.

Until 2026-10-15 there were two vocabularies for this one concept. The quick router's model
classifier spoke the body it would dispatch to (``direct`` / ``investigate`` / ``explore``) and
the Agent turn spoke its own shape (``describe`` / ``diagnose``), and the same question was
read differently at the two doors: "Do Event and Platform really join on these keys?"
(LuxExperience d14f276b) was "investigate" to one and "diagnose" to the other, and the deep
body framed a metric, a date and a window for a yes/no about a join. The four body modes —
``direct``, ``investigate``, ``explore``, ``final_text`` — are frozen persisted identities
(`docs/GLOSSARY.md`, "Names that are frozen"); they are no longer the word for a question's
kind. They are derived from the shape and the depth by :func:`body_for`.

The decision is code-first. :func:`question_shape` reads the question's words; its rules are
conservative in the direction that has been paid for (only a clear ask to read is a describe,
only a check's own words make a check), and ``default`` is what a caller gets when no rule
fires: the Agent keeps its investigation (``"diagnose"``), the router asks the model
(``None``). A shape is decided ONCE per turn and carried into the body
(``run_analyst(shape=…)``), so the trace, the roster and the report never disagree with the
route.

This module imports nothing heavy on purpose: the router reads it on every ``/ask`` turn.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

Shape = Literal["describe", "check", "diagnose", "survey"]

#: The shapes, in the order a reader meets them. The menu every shape decision is recorded
#: against (`learning.decisions`, site ``ask.shape``) — derived from here, never hand-listed.
SHAPES: tuple[str, ...] = ("describe", "check", "diagnose", "survey")

#: A question's shape → the body mode that serves it at a given depth. The modes are the four
#: frozen ``STRUCTURAL_MODES``; ``final_text`` (a knowledge answer) is chosen later, by the
#: graph, when a describe is definitional and the knowledge base holds it.
_BODY: dict[tuple[str, str], str] = {
    ("describe", "quick"): "direct", ("describe", "deep"): "investigate",
    ("check", "quick"): "direct", ("check", "deep"): "investigate",
    ("diagnose", "quick"): "direct", ("diagnose", "deep"): "investigate",
    ("survey", "quick"): "direct", ("survey", "deep"): "explore",
}


def body_for(shape: str, depth: str = "deep") -> str:
    """The frozen body mode a shape runs as at ``depth``. A describe or a check at ``deep`` is
    the analyst keeping its frame with more budget (``investigate`` is the door, not the
    reading); a survey at ``deep`` is the explore wave; anything quick is ``direct``."""
    return _BODY.get((shape, depth), "investigate" if depth == "deep" else "direct")


def default_depth(shape: str) -> str:
    """The depth a shape takes when nothing forces one: a describe or a check is answered quickly,
    a diagnosis or a survey takes the deep body. Agent versus Quick is depth only — a check or a
    describe keeps its frame at ``deep`` and gets more budget."""
    return "deep" if shape in ("diagnose", "survey") else "quick"


#: The stopping rule for a check, stated once for every body that answers one — the analyst's
#: system prompt (`analyst._check_rules`) and the conversation's (`converse_tools`).
CHECK_RULE = (
    "This question asks you to VERIFY a property of the data — whether keys join, whether rows "
    "match, whether values are present, unique or consistent — not to measure a business figure "
    "or to explain a movement. STOPPING RULE: decide what would make the answer yes or no, "
    "measure exactly that with counts (rows, matches, orphans, duplicates, nulls — one query can "
    "carry several), and stop when the verdict is evidenced. Frame no metric, no period and no "
    "baseline, and look for no cause or anomaly the question did not ask about."
)


def shape_for_body(mode: str) -> str:
    """The shape a frozen body mode implies, for a caller that has only the mode — a pinned
    starter, a manifest override, a checkpointed run. The inverse of :func:`body_for` where
    one exists; ``direct`` reads as a describe."""
    return {"direct": "describe", "final_text": "describe", "investigate": "diagnose",
            "explore": "survey"}.get(mode, "diagnose")


# ── The rules, in the order they are read ───────────────────────────────────────────────────

#: Words that ask WHY — for a cause, a driver or an explanation. Narrower than the intake's
#: cause-words class on purpose: "which months grew or shrank the most" asks WHAT moved, which is
#: still a question about the data, and that class counts "grew" as a cause.
_ASKS_WHY_RE = re.compile(
    r"\b(why|reasons?|caus\w*|drove|drive[sn]?|driv(?:er|ers|ing)|behind|explain\w*|"
    r"contribut\w*|attribut\w*|responsible|root)\b", re.I)
#: Words that ask what to DO about the data, or where something is wrong in it.
_ASKS_ADVICE_RE = re.compile(
    r"\b(should|optimi[sz]\w*|improve\w*|recommend\w*|opportunit\w*|anomal\w*|unusual|"
    r"reduce)\b|\bhow (?:can|could|should) we\b", re.I)
#: Cross-sectional "where/which is weakest / where are we losing money" questions — these ask
#: WHICH SEGMENT, so they run a dimensional weakness scan. They do NOT imply the data has no time
#: axis; whether one exists is resolved from the schema, not from the question.
_DIAGNOSTIC_RE = re.compile(
    r"where are we losing|losing money|\b(where|which|what)\b[^?]*\b(losing|lose|lost|leak\w*|"
    r"weak\w*|worst|lowest|underperform\w*|hurting|dragging|bleeding|inefficien\w*)\b",
    re.IGNORECASE,
)
#: The ask to read the data: a question word, or a request to see or compare it.
_ASKS_TO_READ_RE = re.compile(
    r"\b(what|what's|which|who|when|where|how (?:many|much|long|often|has|have|had|did|does|"
    r"do|is|are|was|were)|show|list|give me|display|compare|rank)\b", re.I)
#: The ask to VERIFY a property of the data or the model — do these keys join, are there duplicates
#: or orphans, does one table agree with another, is a value ever null or out of range — in a
#: check's own words. Customers who "joined in March" name no key and are not one. Conservative,
#: like the read-ask: a question that could be read either way keeps the investigation.
_ASKS_TO_VERIFY_RE = re.compile(
    r"\b(?:verif\w*|validat\w*|confirm(?:s|ed)?\s+(?:that|whether|if)|sanity[- ]check\w*|"
    r"check(?:s|ed|ing)?\s+(?:whether|that|if|for)|is\s+it\s+true|"
    r"really\s+(?:join|match|agree|correspond|belong|exist)\w*|"
    r"duplicat\w*|dupes?|orphan\w*|nulls?|missing\s+(?:values?|rows?|keys?|ids?|records?)|"
    r"uniqueness|unique\s+(?:keys?|ids?|values?)|referential\s+integrity|(?:foreign|primary|join)\s+keys?|"
    r"join(?:s|ed|ing)?\s+(?:on|to|with|cleanly|correctly|properly)|"
    r"(?:match(?:es)?|agree(?:s)?|line\s+up|reconcil\w*|consistent)\s+(?:with|to|between|on|across|each\s+other)|"
    r"out\s+of\s+range|invalid|malformed|data\s+quality|integrity)\b", re.I)

#: A genuinely BROAD question — "characterize / profile / map the landscape / how does X vary
#: across …" — is answered best by many independent cuts of one scene, not one investigation.
#: Deterministic (no model in the routing decision — the R4 ablation lesson), and it yields to
#: a why: "explore why churn is rising" asks for a cause.
_WIDE_MARKERS = (
    "overview of", "an overview", "give an overview", "high-level view", "high level view",
    "landscape", "lay of the land",
    "characteristics of", "characteristic of", "characterize", "characterise",
    "profile of", "profile the", "a profile of",
    "what patterns", "patterns in", "any patterns",
    "explore the", "explore our", "explore how", "exploring the", "explore ",
    "map out", "map of the",
    "vary with", "varies with", "vary across", "varies across",
    "segment the", "segment our", "customer segments", "what segments", "which segments",
    "what factors", "which factors", "factors that",
    "optimal ", "sweet spot", "break-even", "break even", "what is a good",
)


def is_diagnostic_question(q: str) -> bool:
    """Cross-sectional 'where/which is weakest / where are we losing money' — asks WHICH SEGMENT, so
    the investigation runs a dimensional weakness scan."""
    return bool(_DIAGNOSTIC_RE.search(q or ""))


def is_wide(question: str) -> bool:
    """Deterministically: is this a broad *landscape* question? Yields to a causal 'why' — a
    cause is an investigation, never a landscape scan — so a real investigation is never
    re-routed away. The causal words are the complexity assessment's own (`agent/complexity.py`),
    so the router's depth signal and the shape's yield read one lexicon."""
    from aughor.agent.complexity import causal_hits
    q = (question or "").strip().lower()
    if not q:
        return False
    if causal_hits(q):
        return False
    # Imperative "Profile our / characterize the …" — the leading verb IS the landscape ask.
    if q.startswith(("profile ", "characterize ", "characterise ")):
        return True
    return any(m in q for m in _WIDE_MARKERS)


def question_shape(question: str, *, default: Optional[str] = "diagnose") -> Optional[str]:
    """The shape of ``question`` — ``"describe"``, ``"check"``, ``"diagnose"`` or ``"survey"`` —
    read from its words, or ``default`` when no rule fires.

    The rules, in order. Asking why outranks everything: "explore why churn is rising" and
    "why are there orphan returns" are investigations. A landscape ask is a survey. Asking
    what to do, or hunting where value is weak or lost, is a diagnosis. A check's own words
    make a check. A clear ask to read the data is a describe. Everything else is ``default``:
    the Agent turn passes ``"diagnose"`` (an unclear question keeps the investigation it
    always had — measured 2026-09-29 on five theLook questions, the cost of the other error
    was a writer replacing a table of ten centres with speculation); the ``/ask`` router passes
    ``None`` and asks the model classifier, which speaks these same four words.

    Measured 2026-10-15 on LuxExperience (d14f276b): "Do Event and Platform really join on these
    keys?" fell to diagnose, and the intake invented a metric, a date and a window for it; the
    quick path answered the same question in one step with a verdict."""
    q = question or ""
    if _ASKS_WHY_RE.search(q):
        return "diagnose"
    if is_wide(q):
        return "survey"
    if _ASKS_ADVICE_RE.search(q) or is_diagnostic_question(q):
        return "diagnose"
    if _ASKS_TO_VERIFY_RE.search(q):
        return "check"
    if _ASKS_TO_READ_RE.search(q):
        return "describe"
    return default


def shape_reading(shape: Optional[str]) -> str:
    """What the route says of a shape, in the reader's words — the one copy the receipt, the
    trace and the quick body's reason line draw from."""
    return {
        "describe": "measuring what was asked",
        "check": "checking the data directly — a verdict and its counts",
        "diagnose": "this asks for a cause, a weakness or what to do",
        "survey": "mapping this out as a landscape scan",
    }.get(shape or "", "")
