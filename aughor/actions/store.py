"""Action Hub persistence — triggers stored in data/action_triggers.json,
logs in data/action_logs.json (append-only)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from aughor.actions.models import ActionTrigger, ActionLog
from aughor.secretvault import encrypt_secret, decrypt_secret
from aughor.util.json_store import JsonListStore

_TRIGGERS_PATH = Path("data/action_triggers.json")
_LOGS_PATH     = Path("data/action_logs.json")
_triggers = JsonListStore(_TRIGGERS_PATH)
_logs     = JsonListStore(_LOGS_PATH)


# The trigger `url` is a credential (a Slack/webhook URL grants posting access), so it
# is encrypted at rest and only ever decrypted in-process to fire. Load returns the
# plaintext URL (for the executor); the API masks it (see ActionTrigger.to_safe_dict).
def _load_decrypted(d: dict) -> ActionTrigger:
    d = {**d, "url": decrypt_secret(d.get("url", ""))}
    return ActionTrigger.from_dict(d)


# ── Trigger CRUD ──────────────────────────────────────────────────────────────

def list_triggers() -> list[ActionTrigger]:
    return [_load_decrypted(d) for d in _triggers.all()]


def get_trigger(trigger_id: str) -> Optional[ActionTrigger]:
    d = _triggers.get(trigger_id)
    return _load_decrypted(d) if d else None


def save_trigger(trigger: ActionTrigger) -> ActionTrigger:
    """Create or update a trigger (upsert by id). The URL is encrypted at rest."""
    if not trigger.id:
        trigger.id = str(uuid.uuid4())[:8]
    record = {**trigger.to_dict(), "url": encrypt_secret(trigger.url)}
    _triggers.upsert(record)
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
