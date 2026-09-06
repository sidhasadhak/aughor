"""The automation-state door — SP-3's second registered door, same law as the first.

The action inbox's ``automation_state`` accept must pause or resume a chain, and the
layering rules that shaped :mod:`aughor.runners.automation_save` are unchanged: K may
not import A, and this package may not import its own callers. So the door is
REGISTERED — ``aughor.automations.store`` hangs its state-change here at import time,
and the inbox only looks it up. Nothing here imports anything.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

_STATE: Optional[Callable[[dict], tuple[bool, Any]]] = None


def register_automation_state(fn: Callable[[dict], tuple[bool, Any]]) -> None:
    """Called by the automations store at import — the one state door, introducing
    itself. Last registration wins, which only matters to tests replacing it."""
    global _STATE
    _STATE = fn


def set_automation_state_payload(params: dict) -> tuple[bool, Any]:
    """Apply a pause/resume payload through the registered state door.

    Returns ``(True, {"automation_id", "name", "paused_until"})``, or
    ``(False, reason)`` in the store's own words. An unregistered door is its own
    honest refusal rather than an import that would close the layering cycle.
    """
    if _STATE is None:
        return False, ("automation state door not registered — the automations "
                       "package has not been imported in this process")
    return _STATE(dict(params or {}))
