"""Action Hub persistence — triggers stored in data/action_triggers.json,
logs in data/action_logs.json (append-only)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from aughor.actions.models import ActionTrigger, ActionLog
from aughor.util.json_store import JsonListStore

_TRIGGERS_PATH = Path("data/action_triggers.json")
_LOGS_PATH     = Path("data/action_logs.json")
_triggers = JsonListStore(_TRIGGERS_PATH)
_logs     = JsonListStore(_LOGS_PATH)


# ── Trigger CRUD ──────────────────────────────────────────────────────────────

def list_triggers() -> list[ActionTrigger]:
    return [ActionTrigger.from_dict(d) for d in _triggers.all()]


def get_trigger(trigger_id: str) -> Optional[ActionTrigger]:
    d = _triggers.get(trigger_id)
    return ActionTrigger.from_dict(d) if d else None


def save_trigger(trigger: ActionTrigger) -> ActionTrigger:
    """Create or update a trigger (upsert by id)."""
    if not trigger.id:
        trigger.id = str(uuid.uuid4())[:8]
    _triggers.upsert(trigger.to_dict())
    return trigger


def delete_trigger(trigger_id: str) -> bool:
    return _triggers.delete(trigger_id)


# ── Action log (append-only) ──────────────────────────────────────────────────

def log_action(log: ActionLog) -> None:
    _logs.append(log.to_dict())


def list_logs(limit: int = 100, trigger_id: Optional[str] = None) -> list[dict]:
    logs = _logs.all()
    if trigger_id:
        logs = [l for l in logs if l.get("trigger_id") == trigger_id]
    return logs[-limit:]
