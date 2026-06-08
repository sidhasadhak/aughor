"""Earned autonomy (trust → L0–L3 ladder) — inert stubs.

See aughor.memory.__init__. Inert mode reports L0 ("manual"): the agent proposes,
the human approves. Replace with real reflection-signal accounting to let a
connection earn higher autonomy.
"""
from __future__ import annotations

# L0 manual is the safe floor: nothing is auto-executed.
_LEVELS = {0: "manual", 1: "assisted", 2: "supervised", 3: "autonomous"}


def autonomy_level(connection_id: str) -> dict:
    """The connection's earned L0–L3 autonomy level. Inert: L0 manual."""
    return {
        "connection_id": connection_id,
        "level": 0,
        "label": _LEVELS[0],
        "signals": {},
        "reason": "Autonomy subsystem not active — operating in manual (L0) mode.",
    }


def skill_autonomy(usage_count: int, connection_id: str) -> dict:
    """Per-skill autonomy from its usage_count. Inert: L0 manual."""
    return {
        "connection_id": connection_id,
        "usage_count": usage_count,
        "level": 0,
        "label": _LEVELS[0],
    }
