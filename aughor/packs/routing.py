"""Route a question to the specialist that owns it (Bet 3 routing half).

A question selects a pack by overlap with its intent_tags / domains / canonical questions —
the same keyword-overlap idea the KB retriever uses, kept dependency-free here so it's pure
and testable. Below the confidence floor → no pack → the generalist answers (today's
behaviour). A pack only ever SHARPENS an answer; it never blocks one.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.packs.models import Pack

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "is", "are", "of", "by", "for", "to", "in", "on", "and", "or",
         "what", "which", "how", "our", "we", "do", "does", "this", "that", "with", "per"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


def score_pack(question: str, pack: Pack) -> float:
    """Overlap score between a question and a pack. intent_tags/domains count full; canonical
    question tokens count half (broader, noisier)."""
    q = _tokens(question)
    if not q:
        return 0.0
    strong = set()
    for t in pack.questions.intent_tags:
        strong |= _tokens(t)
    for d in pack.manifest.domains:
        strong |= _tokens(d)
    canonical = set()
    for c in pack.questions.canonical:
        canonical |= _tokens(c)
    return len(q & strong) * 1.0 + len(q & (canonical - strong)) * 0.5


def select_pack(question: str, packs: list[Pack], min_score: float = 1.0) -> Optional[tuple[Pack, float]]:
    """The best-matching ACTIVE pack above the floor, or None (→ generalist). Draft/deprecated
    packs are never selected for live routing."""
    best: Optional[tuple[Pack, float]] = None
    for p in packs:
        if p.manifest.status != "active":
            continue
        s = score_pack(question, p)
        if s >= min_score and (best is None or s > best[1]):
            best = (p, s)
    return best


def rank_packs(question: str, packs: list[Pack]) -> list[tuple[Pack, float]]:
    """All active packs scored, descending — for cross-domain fan-out (multiple experts)."""
    scored = [(p, score_pack(question, p)) for p in packs if p.manifest.status == "active"]
    return sorted([x for x in scored if x[1] > 0], key=lambda x: x[1], reverse=True)
