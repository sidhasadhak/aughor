"""A first cockpit, written by code from cards a person already has (Arc CT, CT-4; CT-7).

**No model.** A person with cards should not need one to get a cockpit: this
groups the cards by their kind into sections, in a fixed order, and the result is kept like
any other spec — through the validator, as a version, with the person's name on it.
CT-5 is where a model arranges; this is what a person starts from without one.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

#: A card's kind → the section it starts in, in the order the sections are drawn.
SECTIONS = (
    ("kpi", "figures", "Figures", 4),
    ("chart", "charts", "Charts", 2),
    ("watch", "watches", "Watches", 3),
    ("note", "notes", "Notes", 2),
)
_FALLBACK = "chart"          # a card of a kind nobody has named yet is drawn with the charts

_KEY = re.compile(r"[^A-Za-z0-9_-]")


def default_spec(title: str, cards: Iterable[Any], order: Iterable[str] = ()) -> dict:
    """The spec for ``cards`` (each with ``id``, ``kind`` and ``title``), or a spec with no
    sections when there are none — which the validator refuses, and rightly.

    ``order`` is the card ids in the order a person already arranged them (the Briefing kept
    each card's place before cockpits had names). Within a section cards keep that order;
    a card it does not name follows, by title."""
    rank = {str(card_id): i for i, card_id in enumerate(order)}
    known = {kind for kind, *_ in SECTIONS}
    by_kind: dict[str, list[Any]] = {}
    for card in sorted(cards, key=lambda c: (rank.get(str(c.id), len(rank)),
                                             str(c.title or "").lower(), str(c.id))):
        kind = card.kind if card.kind in known else _FALLBACK
        by_kind.setdefault(kind, []).append(card)

    elements: dict[str, dict] = {}
    sections: list[str] = []
    for kind, slug, heading, columns in SECTIONS:
        held = by_kind.get(kind) or []
        if not held:
            continue
        keys = []
        for card in held:
            key = f"card-{_KEY.sub('-', str(card.id))}"
            elements[key] = {"type": "Card", "props": {"card": str(card.id)}, "children": []}
            keys.append(key)
        section = f"sec-{slug}"
        elements[section] = {"type": "Section",
                             "props": {"title": heading, "columns": min(columns, len(keys))},
                             "children": keys}
        sections.append(section)

    name = (title or "").strip()[:120] or "Cockpit"
    return {"root": "cockpit",
            "elements": {"cockpit": {"type": "Cockpit", "props": {"title": name},
                                     "children": sections}, **elements}}
