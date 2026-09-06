"""The automation-save door — SP-3's H5 glue, as a REGISTRY rather than an import.

The action inbox's ``automation_draft`` accept must SAVE a chain, and the layering
rules are absolute in both directions: K may not import A (two guards), and this
package may not import its own callers either (a caller-neutral module that imports a
caller is the cycle wearing a different hat — the third guard says so in as many
words). So the door is REGISTERED: ``aughor.automations.store`` hangs its save here at
import time, the way a write door should introduce itself, and the inbox only looks it
up. Nothing here imports anything.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

_SAVE: Optional[Callable[[dict], tuple[bool, Any]]] = None


def register_automation_save(fn: Callable[[dict], tuple[bool, Any]]) -> None:
    """Called by the automations store at import — the one write door, introducing
    itself. Last registration wins, which only matters to tests replacing it."""
    global _SAVE
    _SAVE = fn


def save_automation_payload(params: dict) -> tuple[bool, Any]:
    """Save an authoring-shaped payload through the registered write door.

    Returns ``(True, {"automation_id", "name"})``, or ``(False, reason)`` — the
    model's own validation and the store's integrity refusals, verbatim, because the
    human who staged the draft can act on a sentence. An unregistered door is its own
    honest refusal rather than an import that would close the layering cycle.
    """
    if _SAVE is None:
        return False, ("automation write door not registered — the automations "
                       "package has not been imported in this process")
    return _SAVE(dict(params or {}))
