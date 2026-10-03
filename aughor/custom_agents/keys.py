"""The credential behind a custom agent's HTTP door (Arc AO-5b).

The shape is the webhook token's (`automations/webhooks.py`) and the supervisor key's,
deliberately: mint 32 random bytes, store the ciphertext in its own store (never a column
on the agent — `GET /agents/custom` returns the record whole), return the plaintext exactly
once, and make every later read a constant-time COMPARISON. Revocation is deletion: the
absence IS the closed door. One key per agent; a rotation is the same gesture as a first
issue, which is what makes rotation something a person will do.

What the key opens: `POST /doors/agents/{id}/ask` and the webhook and A2A doors beside it —
the agent answering AS ITSELF, with its own brief, documents, packs and grants, for a caller
that has no session. What it does not open: anything else on the API. A caller holding an
agent's key is that agent's caller, not an operator.
"""
from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path
from aughor.secretvault import decrypt_secret, encrypt_secret
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

_DIR = resolve_db_path("AUGHOR_AGENTS_DIR", Path("data"))
_STORE = LedgerListStore(_DIR / "agent_keys.json")
_TOKEN_BYTES = 32


def _row(agent_id: str) -> dict | None:
    return next((r for r in _STORE.all() if r.get("id") == str(agent_id)), None)


def issue_agent_key(agent_id: str) -> str:
    """Mint the agent's key, store it encrypted, return it ONCE. Issuing replaces."""
    raw = secrets.token_urlsafe(_TOKEN_BYTES)
    _STORE.upsert({"id": str(agent_id), "key": encrypt_secret(raw), "created_at": now_iso_z()})
    return raw


def revoke_agent_key(agent_id: str) -> bool:
    """Delete the key. The door reads closed because the row is gone."""
    return bool(_STORE.delete(str(agent_id)))


def agent_key_issued_at(agent_id: str) -> str:
    """When the key was minted, or "" when none exists. Never the key."""
    row = _row(agent_id)
    return str(row.get("created_at", "")) if row else ""


def agent_key_matches(agent_id: str, candidate: str) -> bool:
    """Constant-time comparison. False on EVERY failure path — no key, no candidate, a vault
    that cannot decrypt — so a caller learns nothing about which agents have doors."""
    row = _row(agent_id)
    if not row or not candidate:
        return False
    try:
        stored = decrypt_secret(str(row.get("key", "")) or "") or ""
    except Exception:
        return False
    return bool(stored) and hmac.compare_digest(stored, candidate)
