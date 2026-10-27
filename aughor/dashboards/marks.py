"""Rows marked by a declared rule (the Grist study §10, 2026-10-28; flag ``dashboard.marks``, off).

A table's or a list's ``marked`` — a segment the ontology declares on the entity (a business rule's own, a process's,
a verified one) and one of the five tones — marks the rows it admits, read through the object door as ``in_set``; the
legend says what it means and how many it marks. No formula: a dashboard marks by nothing the ontology does not declare.

The marking is the web's (``web/components/dashboards/OntologyPieces.tsx``, ``useMarked``); the server holds a kept spec
to the flag here, and compiles each mark's read with the pieces' (`not_resolved`), so a segment the entity does not
declare is refused at the keep, not discovered by a reader.
"""
from __future__ import annotations

from typing import Any

FLAG = "dashboard.marks"
MARKED = ("ObjectTable", "ObjectList")


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def held(spec: Any) -> list[tuple[str, dict]]:
    """Each element a spec marks: ``(key, its mark)``, in the spec's order."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    out: list[tuple[str, dict]] = []
    for key, el in (elements if isinstance(elements, dict) else {}).items():
        if isinstance(el, dict) and el.get("type") in MARKED:
            mark = (el.get("props") or {}).get("marked")
            if isinstance(mark, dict) and mark.get("segment"):
                out.append((str(key), mark))
    return out


def refused_off(spec: Any) -> list[str]:
    """The sentence a keep is refused with when a spec marks rows while marks are off here — none when it marks none."""
    keys = [k for k, _ in held(spec)]
    if not keys or on():
        return []
    return [f"The dashboard marks rows by a rule — {', '.join(keys[:6])}{'…' if len(keys) > 6 else ''} — and marking rows "
            "is off on this install."]


def probes(props: dict, entity: str, scope: dict) -> list[tuple[str, dict]]:
    """The count a mark's legend asks, as what a refusal names and its body: the listing's objects in the segment."""
    mark = props.get("marked")
    if not isinstance(mark, dict) or not mark.get("segment"):
        return []
    in_set = {"path": "", "op": "in_set", "sets": [{"entity": entity, "segment": str(mark["segment"])}]}
    return [(f'its mark "{mark["segment"]}"', {"object_type": entity, **{k: v for k, v in scope.items() if k != "filters"},
                                               "measures": [{"name": "n", "agg": "count"}],
                                               "filters": [*(scope.get("filters") or []), in_set]})]
