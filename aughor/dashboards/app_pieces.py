"""Arc AP-4 — a dashboard built from a structure of pieces (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
§3, and the user's ask of 2026-10-11, showing Workshop's blank app: "a widget based structure would be really helpful").

A section holds pieces on its own grid, or is laid out in columns, rows or tabs of sections of its own; a section may
hold nothing yet, for a builder to offer it a piece; and a section split into sections may go untitled. The web's rules
hold the structure's shape from the catalog the browser draws with (`web/lib/cockpit/rules.ts`, `checkStructure`).
What they cannot know is whether the structure is on here, so the server refuses a spec that says any of it while
`dashboard.app_pieces` is off — an install that has not turned it on keeps the dashboard it had, and its writer is told
nothing about it (`validate.grammar`).

The same flag holds what the builder's picker adds (the study's §4.4): a list of objects as cards, a map, a timeline, a
choose-one, a search, and a drawer that opens beside the page on a chosen object. What each piece reads is checked as a
table's is (`pieces.not_resolved`).
"""
from __future__ import annotations

from typing import Any

FLAG = "dashboard.app_pieces"
#: What the builder's picker adds — placed by a person, as every piece bound to the ontology is.
PIECES = ("ObjectList", "ObjectMap", "ObjectTimeline", "ChooseOne", "ObjectSearch", "Drawer")


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def structured(spec: Any) -> list[str]:
    """The element keys only a dashboard built from a structure of pieces says, each once, in the spec's order: a section
    laid out in columns, rows or tabs, one that says its width among them, one that holds nothing yet, and one that goes
    untitled."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    out: list[str] = []
    for key, el in (elements if isinstance(elements, dict) else {}).items():
        if not isinstance(el, dict) or el.get("type") != "Section" or not isinstance(el.get("props"), dict):
            continue
        props = el["props"]
        children = el.get("children") if isinstance(el.get("children"), list) else None
        if props.get("layout") is not None or props.get("w") is not None or not props.get("title") or children == []:
            out.append(str(key))
    return out


def added(spec: Any) -> list[str]:
    """The element keys of what the picker adds, each once, in the spec's order."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    return [str(key) for key, el in (elements if isinstance(elements, dict) else {}).items()
            if isinstance(el, dict) and el.get("type") in PIECES]


def _keys(keys: list[str]) -> str:
    return f"{', '.join(keys[:6])}{'…' if len(keys) > 6 else ''}"


def refused_off(spec: Any) -> list[str]:
    """A sentence for each of the structure and the picker's pieces that ``spec`` says while they are off here — what a
    keep is refused with. Empty when it says neither, whatever the flag says, so a dashboard whose sections hold the
    pieces before them keeps as it did."""
    split, new = structured(spec), added(spec)
    if not (split or new) or on():
        return []
    said = []
    if split:
        said.append(f"The dashboard is split into sections, or holds a section with nothing in it yet — {_keys(split)} — "
                    "and splitting a dashboard into sections is off on this install.")
    if new:
        said.append(f"The dashboard holds a list, a map, a timeline, a choose-one, a search or a drawer — {_keys(new)} — "
                    "and adding those is off on this install.")
    return said
