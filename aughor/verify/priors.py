"""Plan-time priors — read the captured feedback loop BACK into the planner (P1).

Aughor already *captures* two feedback channels but never *reads them back* when
planning the next answer, so the loop is open: a mistake a human corrected last
week gets made again this week. This module closes it. Given a question +
connection it assembles a single prompt section from:

1. **Verified query patterns** — data-team-reviewed known-correct SQL
   (:mod:`aughor.semantic.trusted_queries`), already injected in ``/chat`` but not
   in the investigate/explore graph.
2. **Past corrections** — ``reject`` / ``correct`` human verdicts
   (:mod:`aughor.verify.verdicts`), which name a mistake not to repeat, plus any
   human-supplied fix SQL.

It is deliberately conservative: token-overlap matching with a threshold, so an
unrelated question injects nothing and the section is empty (zero prompt cost, no
behaviour change) when there are no relevant priors. Gated behind
``AUGHOR_CLOSED_LOOP`` at the call sites.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from aughor.semantic.trusted_queries import (
    TrustedQuery,
    build_trusted_block,
    retrieve_trusted,
)
from aughor.verify.verdicts import list_corrections

_STOP = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by", "per",
    "each", "what", "which", "how", "many", "is", "are", "was", "were", "do",
    "does", "show", "list", "give", "me", "their", "its", "with", "that", "this",
    "why", "did", "has", "have", "over", "from", "into",
})

# Same conservative overlap threshold as trusted_queries — an unrelated question
# must inject nothing rather than pollute the plan with irrelevant corrections.
_MIN_CORRECTION_SCORE = 0.18


def closed_loop_enabled() -> bool:
    """P1 is opt-in until its delta is proven. Off ⇒ call sites are no-ops."""
    return os.getenv("AUGHOR_CLOSED_LOOP", "").strip().lower() in ("1", "true", "yes", "on")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if t not in _STOP and len(t) > 2}


@dataclass
class PriorsResult:
    trusted: list[tuple[TrustedQuery, float]] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    section: str = ""

    @property
    def fired(self) -> bool:
        return bool(self.trusted or self.corrections)


def _match_corrections(question: str, connection_id: str, limit: int) -> list[dict]:
    qtok = _tokens(question)
    if not qtok:
        return []
    out: list[tuple[float, dict]] = []
    for row in list_corrections(connection_id, limit=50):
        ctok = _tokens(row.get("headline", "")) | _tokens(row.get("note", ""))
        if not ctok:
            continue
        score = len(qtok & ctok) / len(qtok)
        if score >= _MIN_CORRECTION_SCORE:
            out.append((round(score, 3), row))
    out.sort(key=lambda x: x[0], reverse=True)
    return [r for _s, r in out[:limit]]


def _build_corrections_block(corrections: list[dict]) -> str:
    if not corrections:
        return ""
    lines = [
        "PAST CORRECTIONS (a reviewer judged earlier answers on THIS database and flagged "
        "the following — treat them as ground truth and do NOT repeat the mistake):",
    ]
    for i, row in enumerate(corrections, 1):
        verdict = row.get("verdict", "")
        headline = (row.get("headline") or "").strip()
        note = (row.get("note") or "").strip()
        tag = "WRONG — was rejected" if verdict == "reject" else "PARTIALLY WRONG — needed correction"
        line = f"\n-- Correction {i} [{tag}]"
        if headline:
            line += f'\nEarlier claim: "{headline}"'
        if note:
            line += f"\nReviewer note: {note}"
        src = (row.get("sql_source") or "").strip()
        if src:
            line += f"\nFlawed query was:\n{src[:600]}"
        fix = (row.get("corrected_sql") or "").strip()
        if fix:
            line += f"\nUSE THIS CORRECTED STRUCTURE INSTEAD:\n{fix[:600]}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def retrieve_priors(question: str, connection_id: str, *, top_k_trusted: int = 2,
                    max_corrections: int = 3) -> PriorsResult:
    """Assemble plan-time priors for a question. Returns an empty result (no section)
    when nothing relevant is stored, so callers can inject unconditionally."""
    if not closed_loop_enabled():
        return PriorsResult()
    trusted: list[tuple[TrustedQuery, float]] = []
    corrections: list[dict] = []
    try:
        trusted = retrieve_trusted(question, connection_id, top_k=top_k_trusted)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "trusted-query retrieval for priors is best-effort", counter="priors.trusted")
    try:
        corrections = _match_corrections(question, connection_id, max_corrections)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "verdict-correction retrieval for priors is best-effort", counter="priors.corrections")

    parts = [p for p in (build_trusted_block(trusted), _build_corrections_block(corrections)) if p]
    section = ("\n".join(parts) + "\n") if parts else ""
    return PriorsResult(trusted=trusted, corrections=corrections, section=section)


def build_priors_section(question: str, connection_id: str, **kwargs) -> str:
    """Convenience: just the combined prompt text (empty when no priors apply)."""
    return retrieve_priors(question, connection_id, **kwargs).section


def build_corrections_section(question: str, connection_id: str, max_corrections: int = 3) -> str:
    """Corrections-only prompt text (past reject/correct verdicts). This is the piece
    added to the direct SQL path, which ALREADY injects verified query patterns — so we
    only add the new signal there rather than double-inject trusted queries. Empty string
    when the flag is off or nothing relevant matches (zero-cost, no behaviour change)."""
    if not closed_loop_enabled():
        return ""
    try:
        corrections = _match_corrections(question, connection_id, max_corrections)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "verdict-correction retrieval is best-effort", counter="priors.corrections")
        return ""
    block = _build_corrections_block(corrections)
    return (block + "\n") if block else ""
