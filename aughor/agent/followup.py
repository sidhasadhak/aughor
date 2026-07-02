"""Deterministic follow-up detection — is this turn a continuation of the last one?

Phase 4 of the unified-answer-path arc (``docs/UNIFIED_ANSWER_PATH.md``): the
conversational / state-dependent axis from BIRD-INTERACT. A follow-up like "now break
that down by region" or "filter that to enterprise" should compose on the **previous**
query — keep its metric, filters, grain, and window unless the new ask changes them —
and resolve references ("that", "those", "the top one") against the previous result.

This module makes the *detection* deterministic (no model): a small lexicon of
continuation / reference / refinement markers. The caller pairs a positive verdict with
the conversation context (prior SQL + a result digest) and a "treat the last query as the
base" instruction, so the generator composes instead of starting from scratch.

Pure and cheap, so it runs at the door on every turn; unit-tested.
"""
from __future__ import annotations

import re

# Reference / continuation / refinement markers. Word-boundary, case-insensitive.
# Deliberately conservative — a fresh "revenue by region" is NOT a follow-up; the signal
# is a pronoun, a continuation lead, or an explicit refine-the-previous verb.
_FOLLOWUP_RE = re.compile(
    # leading continuation words ("now …", "and …", "then …", "what about …")
    r"^\s*(and|now|then|also|ok(ay)?|what about|how about|what if)\b"
    # pronoun references to the prior result (bare "it" excluded — too noisy; caught via verbs)
    r"|\b(those|these|them|the same|same as)\b"
    # superlative reference — requires "one/ones" so a fresh superlative ("the highest product")
    # is NOT flagged ("show me the top one" / "why is that one different" ARE)
    r"|\b(that|the (top|bottom|first|last|highest|lowest|biggest|largest|smallest)) ones?\b"
    # explicit refine-the-previous verbs (verb + the prior object)
    r"|\b(break (it|that|them|this) down|drill (in|down|into)|zoom in|add (a|the|in)|"
    r"narrow (it|that|this|down)|filter (it|that|this|to|by|down)|just (the|those|that)|"
    r"only (the|those|that)|exclude|remove|instead|split (it|that|this)|group (it|that|this)\s*by)\b",
    re.IGNORECASE,
)


def is_followup(question: str) -> bool:
    """True when the question reads as a continuation of the previous turn.

    Conservative by design: it should fire on "now break that down by region",
    "filter that to last quarter", "what about Europe?", "exclude returns" — and NOT on
    a self-contained fresh question like "revenue by region last month"."""
    q = (question or "").strip()
    if not q:
        return False
    return bool(_FOLLOWUP_RE.search(q))
