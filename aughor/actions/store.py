"""Action Hub persistence — triggers stored in data/action_triggers.json,
logs in data/action_logs.json (append-only)."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional


from aughor.actions.models import ActionTrigger, ActionLog, is_secret_header
from aughor.db.sqlite_util import resolve_db_path
from aughor.secretvault import encrypt_secret, decrypt_secret
from aughor.util.json_store import JsonListStore

# WP-4 — env override (AUGHOR_ACTIONS_DIR) for test isolation; both JSON stores were
# hardcoded to the live data/ dir with no override (a non-hermetic hole).
_ACTIONS_DIR   = resolve_db_path("AUGHOR_ACTIONS_DIR", Path("data"))
_TRIGGERS_PATH = _ACTIONS_DIR / "action_triggers.json"
_LOGS_PATH     = _ACTIONS_DIR / "action_logs.json"
_triggers = JsonListStore(_TRIGGERS_PATH)
_logs     = JsonListStore(_LOGS_PATH)


# The trigger `url` (a Slack/webhook URL grants posting access) and any auth-bearing
# `headers` (Authorization, X-Api-Key, …) are credentials, so they're encrypted at rest
# and only decrypted in-process to fire. Load returns the plaintext values (for the
# executor); the API masks them (see ActionTrigger.to_safe_dict).
def _enc_headers(h: dict | None) -> dict:
    return {k: (encrypt_secret(v) if is_secret_header(k) and isinstance(v, str) else v)
            for k, v in (h or {}).items()}


def _dec_headers(h: dict | None) -> dict:
    return {k: (decrypt_secret(v) if is_secret_header(k) and isinstance(v, str) else v)
            for k, v in (h or {}).items()}


def _load_decrypted(d: dict) -> ActionTrigger:
    d = {**d, "url": decrypt_secret(d.get("url", "")), "headers": _dec_headers(d.get("headers"))}
    return ActionTrigger.from_dict(d)


# ── Trigger CRUD ──────────────────────────────────────────────────────────────

def list_triggers() -> list[ActionTrigger]:
    return [_load_decrypted(d) for d in _triggers.all()]


def get_trigger(trigger_id: str) -> Optional[ActionTrigger]:
    d = _triggers.get(trigger_id)
    return _load_decrypted(d) if d else None


def save_trigger(trigger: ActionTrigger) -> ActionTrigger:
    """Create or update a trigger (upsert by id). The URL + auth headers are
    encrypted at rest."""
    if not trigger.id:
        trigger.id = str(uuid.uuid4())[:8]
    record = {**trigger.to_dict(),
              "url": encrypt_secret(trigger.url),
              "headers": _enc_headers(trigger.headers)}
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
