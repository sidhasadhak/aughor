"""Arc OC-6 — the version of a declared action a proposal was made under and an execution ran under.

A proposal staged on Monday was accepted on Thursday against whatever the action declared on Thursday; an execution's
ledger entry named the action and never which declaration of it ran. A person approved one thing and another could
run. Each proposal now carries the pin of the action it proposes, and each execution books the pin it ran under; a
proposal whose action changed since is refused on accept, with what changed, and is proposed again.

A pin is the action's content hash — the one comparison that cannot drift — with the declaration's history version
when its history is kept (`ontology.history`) and the release in force, for a reader.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


def action_pin(action: Any, connection_id: str, schema_name: str = "") -> dict:
    """The pin of ``action`` as it stands on ``connection_id``/``schema_name`` now."""
    body = json.dumps(action.model_dump(mode="json"), sort_keys=True, default=str)
    pin: dict[str, Any] = {"hash": hashlib.sha256(body.encode()).hexdigest()[:16]}
    schema = schema_name or "default"
    try:
        from aughor.ontology import history
        if history.enabled():
            kept = history.versions(connection_id, schema, "action", action.id)
            if kept and kept[0].get("version") is not None:
                pin["version"] = kept[0]["version"]
    except Exception:  # noqa: BLE001 — the hash is the pin; the version is for a reader
        pass
    try:
        from aughor.ontology.release import current_id
        release = current_id(connection_id, schema)
        if release:
            pin["release"] = release
    except Exception:  # noqa: BLE001
        pass
    return pin


def pin_words(pin: Optional[dict]) -> str:
    if not pin:
        return "an unpinned declaration"
    return f"version {pin['version']}" if pin.get("version") is not None else f"declaration {pin.get('hash', '?')}"


def changed_since(pinned: Optional[dict], now: dict) -> str:
    """"" when the action is the one ``pinned`` (or nothing was pinned — a proposal older than pins), else the
    sentence a refusal says."""
    if not pinned or not pinned.get("hash") or pinned.get("hash") == now.get("hash"):
        return ""
    return (f"the action changed since it was proposed — proposed under {pin_words(pinned)}, it now reads "
            f"{pin_words(now)}; propose it again so the approval is of what will run")
