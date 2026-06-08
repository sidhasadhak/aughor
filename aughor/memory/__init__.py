"""aughor.memory — agent procedural memory (learned skills + earned autonomy).

The full subsystem — crystallizing reusable "skills" from finished investigations
and an earned L0–L3 autonomy ladder — is not yet implemented. Several endpoints
(`/ontology/skills`, `/ontology/autonomy`, …) and the investigation stream import
from here at request time; before this package existed those imports raised
ModuleNotFoundError and surfaced as HTTP 500s.

This package provides safe, INERT implementations so everything degrades
gracefully — empty skill lists, manual (L0) autonomy, no-op run recording —
instead of crashing. Flesh these functions out to build the real feature; the
call sites and return contracts are already in place.
"""
from __future__ import annotations

from typing import Any


def record_run(inv_id: str, connection_id: str, question: str, state: dict[str, Any]) -> None:
    """Persist a run's reflection signals into agent memory. Inert no-op."""
    return None
