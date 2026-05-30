"""Action Hub persistence — triggers stored in data/action_triggers.json,
logs in data/action_logs.json (append-only)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from aughor.actions.models import ActionTrigger, ActionLog

_TRIGGERS_PATH = Path("data/action_triggers.json")
_LOGS_PATH     = Path("data/action_logs.json")


# ── Trigger CRUD ──────────────────────────────────────────────────────────────

def _load_triggers() -> list[dict]:
    try:
        if _TRIGGERS_PATH.exists():
            return json.loads(_TRIGGERS_PATH.read_text())
    except Exception:
        pass
    return []


def _save_triggers(triggers: list[dict]) -> None:
    _TRIGGERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TRIGGERS_PATH.write_text(json.dumps(triggers, indent=2))


def list_triggers() -> list[ActionTrigger]:
    return [ActionTrigger.from_dict(d) for d in _load_triggers()]


def get_trigger(trigger_id: str) -> Optional[ActionTrigger]:
    for d in _load_triggers():
        if d["id"] == trigger_id:
            return ActionTrigger.from_dict(d)
    return None


def save_trigger(trigger: ActionTrigger) -> ActionTrigger:
    """Create or update a trigger (upsert by id)."""
    if not trigger.id:
        trigger.id = str(uuid.uuid4())[:8]
    triggers = [d for d in _load_triggers() if d["id"] != trigger.id]
    triggers.append(trigger.to_dict())
    _save_triggers(triggers)
    return trigger


def delete_trigger(trigger_id: str) -> bool:
    triggers = _load_triggers()
    filtered = [d for d in triggers if d["id"] != trigger_id]
    if len(filtered) == len(triggers):
        return False
    _save_triggers(filtered)
    return True


# ── Action log (append-only) ──────────────────────────────────────────────────

def log_action(log: ActionLog) -> None:
    logs = []
    try:
        if _LOGS_PATH.exists():
            logs = json.loads(_LOGS_PATH.read_text())
    except Exception:
        pass
    logs.append(log.to_dict())
    _LOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOGS_PATH.write_text(json.dumps(logs, indent=2))


def list_logs(limit: int = 100, trigger_id: Optional[str] = None) -> list[dict]:
    try:
        if not _LOGS_PATH.exists():
            return []
        logs = json.loads(_LOGS_PATH.read_text())
        if trigger_id:
            logs = [l for l in logs if l.get("trigger_id") == trigger_id]
        return logs[-limit:]
    except Exception:
        return []
