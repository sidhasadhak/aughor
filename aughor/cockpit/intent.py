"""Is this chat message asking for a COCKPIT, not a figure? (Arc CT leftovers, PENDING: Cockpit.)

A cockpit is drafted in the Briefing — its Cockpit tab takes the area a person names and runs
the one drafting model there (CT-9, `cockpit/ask.py`); since CT-7 the chat drafts none. So a
request typed into the chat — "Build me a returns cockpit" — was read as a question about data:
the clarify gate asked "which metric, and over what time period?" of two of the ten asks in the
CT receipt, and the rest were answered as queries, with nothing anywhere saying where cockpits
are made. The door now recognises the request and says where.

Deterministic and conservative: the word must be there (cockpit, dashboard, board) AND it must
be asked for — a verb that makes or changes one, or a bare noun phrase that orders one
("Cockpit with revenue, units and AOV."). "Which dashboard metrics moved?" is a question.
"""
from __future__ import annotations

import re

_THING = re.compile(r"\b(cockpits?|dashboards?|boards?)\b", re.IGNORECASE)
_ASKED = re.compile(
    r"\b(build|make|create|set\s+up|setup|design|draft|put\s+together|give\s+me|i\s+want|"
    r"i\s+need|i'd\s+like|add|edit|change|rearrange|update)\b", re.IGNORECASE)
_ORDERED = re.compile(r"^\s*(?:an?\s+|my\s+|the\s+)?(?:\w+\s+)?(cockpit|dashboard|board)\s+"
                      r"(?:with|for|of|showing)\b", re.IGNORECASE)


def is_cockpit_ask(question: str) -> bool:
    """True when the message asks for a cockpit (or a dashboard, a board) to be made or changed."""
    q = question or ""
    return bool(_THING.search(q) and (_ASKED.search(q) or _ORDERED.match(q)))


def where_cockpits_are_made(cockpits_on: bool) -> str:
    """The sentence the chat answers a cockpit request with — no model call."""
    if not cockpits_on:
        return ("Cockpits are switched off on this install — \"A cockpit in each Data Canvas\" "
                "under Settings → Flags turns them on. This chat answers questions about the data.")
    return ("Cockpits are drafted in the Briefing, in its Cockpit tab: name the area — returns, "
            "pricing, the operations team — and a model drafts one there for you to keep or "
            "discard. This chat answers questions about the data.")
