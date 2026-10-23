"""Arc AP-1 — building a dashboard in place (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md).

A dashboard built in place says more than one arranged by name: a section laid on the twelve-column grid, each element's
room in columns and rows (`w`, `h`), the filter column's width, and a chart's measure and split. The web's rules hold
their shape, from the same catalog the browser draws with (`web/lib/dashboards/catalog.ts`). What they cannot know is
whether building in place is on here, so the server refuses a spec that says any of it while `dashboard.builder` is
off — an install that has not turned it on keeps the dashboard it had, and its writer is told nothing about the grid
(`validate.grammar`).
"""
from __future__ import annotations

from typing import Any

FLAG = "dashboard.builder"

#: The props only a cockpit built in place writes, by the component that holds them.
_BUILT: dict[str, tuple[str, ...]] = {
    "Section": ("grid",),
    "ObjectFilters": ("w",),
    "ObjectChart": ("agg", "path", "format", "split", "top"),
}
#: Every element a section places may say its room on the grid.
_ROOM = ("w", "h")
_PLACED = frozenset({"Card", "Note", "Image", "ProcessBoard", "ObjectTable", "ObjectDetail", "ObjectFigure",
                     "ObjectChart"})


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def built_in_place(spec: Any) -> list[str]:
    """The element keys whose props only a dashboard built in place writes, each once, in the spec's order. A prop that
    is absent or null is not said."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    out: list[str] = []
    for key, el in (elements if isinstance(elements, dict) else {}).items():
        if not isinstance(el, dict) or not isinstance(el.get("props"), dict):
            continue
        kind, props = el.get("type"), el["props"]
        said = _BUILT.get(str(kind), ()) + (_ROOM if kind in _PLACED else ())
        if any(props.get(name) is not None for name in said):
            out.append(str(key))
    return out


def refused(spec: Any) -> list[str]:
    """A sentence when ``spec`` says what only a dashboard built in place says and building in place is off here — what a
    keep is refused with. Empty when it says none of it, whatever the flag says, so a dashboard arranged by name keeps
    as it always did."""
    keys = built_in_place(spec)
    if not keys or on():
        return []
    return [f"The dashboard is built in place — {len(keys)} element(s) say their room on the grid or a chart's measure "
            "and split — and building dashboards in place is off on this install."]
