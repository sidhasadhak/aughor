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

import re
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


# SP-7 — the OPEN-CHOICES door, registered the same way. The inbox must refuse to accept an
# automation draft that still has a choice nobody made (a Slack channel the request never
# named), and it must say so BEFORE its resolve-once update, so the proposal stays pending
# for a draft that fills it. The rule lives with the automation model; this only looks it up.
_HOLES: Optional[Callable[[dict], list]] = None


def register_automation_holes(fn: Callable[[dict], list]) -> None:
    """Called by the automations store at import, beside the save door."""
    global _HOLES
    _HOLES = fn


def automation_payload_holes(params: dict) -> list[str]:
    """The open choices in an authoring-shaped payload ("Action 2 needs channel"), or []
    when there are none. Also [] when no door is registered — the save door then refuses
    the accept on its own, in its own words."""
    if _HOLES is None:
        return []
    return [str(h) for h in _HOLES(dict(params or {}))]


#: The hole sentence `fill_required_holes` writes ("Action 2 needs channel"), parsed
#: back into its parts. ONE format with both ends here, so the writer and every reader
#: (the inbox's accept-time fills, the card's open-choice fields) cannot drift apart —
#: a test pins a round trip through this exact pair.
_HOLE_RX = re.compile(r"^Action (\d+) needs (\w+)$")


def parse_hole(sentence: str) -> Optional[tuple[int, str]]:
    """``"Action 2 needs channel"`` → ``(2, "channel")``, or None for any other text."""
    m = _HOLE_RX.match(str(sentence or ""))
    return (int(m.group(1)), m.group(2)) if m else None
