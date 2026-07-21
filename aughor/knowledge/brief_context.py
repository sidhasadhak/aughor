"""The briefing, as grounding context for a question asked *about* it.

"Ask this briefing" is a follow-up on an artifact the user is looking at — the verdict, the
findings behind it, the synthesis prose. Without that context the model answers as if the
question arrived cold, so "why is that?" or "break that down" has no referent.

The block is built SERVER-SIDE from the cached brief rather than posted up by the client. Three
reasons, all of which matter more than the small amount of plumbing it saves:

* **One artifact.** The answer is grounded in exactly the brief on screen — the same
  `conn:schema` cache entry the Briefing rendered — instead of whatever subset a component
  happened to serialize. The old ask box sent five lines: theme, headline, three findings.
* **No drift.** A client-assembled blob is a second, silently-diverging copy of the brief.
* **No prose on the wire** every turn, and nothing a caller can spoof into the prompt.

Bounded on purpose: a brief can carry dozens of findings, and this rides in front of a QUICK
answer. Caps below keep it to roughly a screenful.
"""
from __future__ import annotations

from typing import Any

# A brief's verdict + a handful of its cited findings is the useful part; the long tail is
# already reachable by asking. These bound the prompt cost of every single ask.
MAX_CITATIONS = 8
MAX_FINDING_CHARS = 260
MAX_NARRATIVE_CHARS = 1200


def build_brief_block(brief: dict[str, Any] | None) -> str:
    """A prompt block describing the brief in view, or "" when there is nothing to say.

    Empty is the honest default: no brief cached for this scope means the user is not looking
    at one, and inventing context would be worse than having none."""
    if not isinstance(brief, dict):
        return ""
    theme = (brief.get("headline_theme") or "").strip()
    narrative = (brief.get("narrative") or "").strip()
    citations = brief.get("citations") or []
    if not (theme or narrative or citations):
        return ""

    lines: list[str] = [
        "THE BRIEFING THE USER IS LOOKING AT — the question is most likely ABOUT this.",
        "Use it to resolve references ('that', 'the drop', 'those brands') and to stay on the",
        "same entities and time window. It is CONTEXT, not a source of numbers: every figure",
        "in your answer must still come from the query you run.",
        "",
    ]
    if theme:
        lines.append(f"VERDICT: {theme}")
    if narrative:
        text = narrative[:MAX_NARRATIVE_CHARS]
        if len(narrative) > MAX_NARRATIVE_CHARS:
            text += "…"
        lines.append(f"SYNTHESIS: {text}")
    if citations:
        lines.append("FINDINGS IT CITES:")
        for c in citations[:MAX_CITATIONS]:
            if not isinstance(c, dict):
                continue
            finding = (c.get("finding") or "").strip()
            if not finding:
                continue
            if len(finding) > MAX_FINDING_CHARS:
                finding = finding[:MAX_FINDING_CHARS] + "…"
            domain = (c.get("domain") or "").strip()
            lines.append(f"  - {f'[{domain}] ' if domain else ''}{finding}")
    lines.append("")
    return "\n".join(lines)


def brief_block_for_scope(connection_id: str, schema: str | None, canvas_id: str | None = None) -> str:
    """The brief block for a (connection, schema) or canvas — "" when none is cached.

    Mirrors the scope key the briefing route stamps, so the ask is grounded in the SAME entry
    the user is reading and can never pick up a different schema's brief."""
    from aughor.knowledge.briefing import peek_briefing

    scope_key = f"canvas:{canvas_id}" if canvas_id else (
        f"{connection_id}:{schema}" if schema else connection_id
    )
    return build_brief_block(peek_briefing(scope_key))
