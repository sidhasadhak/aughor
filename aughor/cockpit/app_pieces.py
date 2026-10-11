"""Arc AP-4 — a cockpit built from a structure of pieces (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md
§3, and the user's ask of 2026-10-11, showing Workshop's blank app: "a widget based structure would be really helpful").

A section holds pieces on its own grid, or is laid out in columns, rows or tabs of sections of its own; a section may
hold nothing yet, for a builder to offer it a piece; and a section split into sections may go untitled. The web's rules
hold the structure's shape from the catalog the browser draws with (`web/lib/cockpit/rules.ts`, `checkStructure`).
What they cannot know is whether the structure is on here, so the server refuses a spec that says any of it while
`cockpit.app_pieces` is off — an install that has not turned it on keeps the cockpit it had, and its writer is told
nothing about it (`validate.grammar`).
"""
from __future__ import annotations

from typing import Any

FLAG = "cockpit.app_pieces"


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def structured(spec: Any) -> list[str]:
    """The element keys only a cockpit built from a structure of pieces says, each once, in the spec's order: a section
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


def refused_off(spec: Any) -> list[str]:
    """A sentence when ``spec`` is built from a structure of pieces and that is off here — what a keep is refused with.
    Empty when it says none of it, whatever the flag says, so a cockpit whose sections hold pieces keeps as it did."""
    said = structured(spec)
    if not said or on():
        return []
    return [f"The cockpit is split into sections, or holds a section with nothing in it yet — {', '.join(said[:6])}"
            f"{'…' if len(said) > 6 else ''} — and splitting a cockpit into sections is off on this install."]
