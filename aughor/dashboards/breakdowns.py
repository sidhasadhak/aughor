"""A breakdown on a dashboard (the Grist study §10, 2026-10-28; flag ``dashboard.breakdowns``, off).

An entity's objects grouped by one property, a measure or three per group, read through the object door's own grouping
(``ObjectQuery.by``) — the largest groups first, the rest one Other row, those with no value their own row, so the
groups always add up to the whole and the piece says whether they do. A click on a group is the filter column's click.

The piece itself is the web's (``web/components/dashboards/OntologyPieces.tsx``, ``ObjectBreakdownPiece``); the server
holds a kept spec to the flag here, and compiles each breakdown's query with the other pieces' (``pieces.py``).
"""
from __future__ import annotations

from typing import Any

FLAG = "dashboard.breakdowns"
KIND = "ObjectBreakdown"


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def held(spec: Any) -> list[str]:
    """The element keys of the breakdowns a spec holds, in its order."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    return [str(key) for key, el in (elements if isinstance(elements, dict) else {}).items()
            if isinstance(el, dict) and el.get("type") == KIND]


def refused_off(spec: Any) -> list[str]:
    """The sentence a keep is refused with when a spec holds a breakdown while they are off here — none when it holds
    none, whatever the flag says, so every other dashboard keeps as it did."""
    keys = held(spec)
    if not keys or on():
        return []
    return [f"The dashboard holds a breakdown — {', '.join(keys[:6])}{'…' if len(keys) > 6 else ''} — and breakdowns "
            "are off on this install."]
