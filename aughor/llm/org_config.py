"""CI-5b — org-scoped BYOK: each org's own provider keys and per-role model picks.

The runtime ``llm_config.json`` cannot persist on serverless — a UI model choice
reverts on every cold start, which is why CI-5a made env vars the operator default.
This store is the org-scoped layer ABOVE both: a ``store_*``-backed row per org
(SQLite locally, the Postgres store schema in production), so an org's binding
survives cold starts and never touches another tenant's.

Resolution order, per request (provider.py consults this module first):

    org row (this store)  →  runtime file config  →  env  →  built-in defaults

Two properties are the point, and both are tested by name:

* **Keys are encrypted at rest and never returned.** Same secretvault Fernet as the
  connection registry's DSNs; the read API reports only which keys are set.
* **Applying an org's config touches ONLY that org.** ``POST /llm/config``'s
  reload-everything behaviour clears every cached provider in the process — the
  reload that cancels a running exploration. The org path instead bumps a per-org
  fingerprint that participates in the provider cache key: this org's next call
  rebuilds, every other tenant's in-flight work never notices.

Cross-process staleness is bounded by a short TTL (``AUGHOR_ORG_LLM_TTL``, default
30s): a warm serverless instance serves at most that much stale binding after an
org saves from another instance — the same freshness class as every other
store-backed setting, and infinitely better than the config file's "reverts on
cold start".
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.store_pool import ensure_once
from aughor.org.context import DEFAULT_ORG_ID

logger = logging.getLogger(__name__)

_DB_PATH = resolve_db_path(
    "AUGHOR_ORG_LLM_DB", Path(__file__).parent.parent.parent / "data" / "org_llm.db")

_TTL_SECONDS = float(os.getenv("AUGHOR_ORG_LLM_TTL", "30") or 30)

_LOCK = threading.Lock()
#: org_id → (expires_at, raw_row_or_None). The raw row keeps keys ENCRYPTED — they
#: are decrypted only at the one place a client is built (provider._active_key).
_cache: dict[str, tuple[float, Optional[dict]]] = {}


def _conn():
    c = connect_store(_DB_PATH)
    ensure_once(c, _ensure_schema)
    return c


def _ensure_schema(c) -> None:
    c.execute(
        """CREATE TABLE IF NOT EXISTS org_llm_config (
               org_id     TEXT PRIMARY KEY,
               backend    TEXT DEFAULT '',
               models     TEXT DEFAULT '{}',
               keys       TEXT DEFAULT '{}',
               updated_at TEXT DEFAULT ''
           )"""
    )
    c.commit()


def _row(org_id: str) -> Optional[dict]:
    c = _conn()
    try:
        cur = c.execute(
            "SELECT backend, models, keys, updated_at FROM org_llm_config WHERE org_id = ?",
            (org_id,))
        r = cur.fetchone()
    finally:
        c.close()
    if not r:
        return None
    backend, models, keys, updated_at = r[0], r[1], r[2], r[3]

    def _obj(raw: Any) -> dict:
        try:
            d = json.loads(raw) if isinstance(raw, str) else {}
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    return {"backend": (backend or "").strip(), "models": _obj(models),
            "keys": _obj(keys), "updated_at": updated_at or ""}


def overlay_for(org_id: str) -> dict:
    """The org's stored config for the provider's resolution chain — ``{}`` when the
    org has none, so the default org and every unconfigured tenant fall through to
    the deployment config byte-identically. Keys stay encrypted in the return value.
    """
    org_id = org_id or DEFAULT_ORG_ID
    now = time.monotonic()
    with _LOCK:
        hit = _cache.get(org_id)
        if hit and hit[0] > now:
            return dict(hit[1] or {})
    try:
        row = _row(org_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an unreadable org LLM config must fail open to the deployment "
                 "config, never take inference down", counter="org_llm.read")
        row = None
    with _LOCK:
        _cache[org_id] = (now + _TTL_SECONDS, row)
    return dict(row or {})


def config_stamp(org_id: str) -> str:
    """A cache-key component that changes when the org's config does.

    The provider cache keys on this, which is what makes an org save invalidate
    exactly one tenant's providers: this org's fingerprint moves, every other
    org's cached entries keep their keys and are never rebuilt — the surgical
    alternative to ``load_config()``'s global version bump.
    """
    overlay = overlay_for(org_id)
    return overlay.get("updated_at", "") if overlay else ""


def evict(org_id: str) -> None:
    with _LOCK:
        _cache.pop(org_id or DEFAULT_ORG_ID, None)


def save_org_config(org_id: str, patch: dict) -> dict:
    """Merge ``patch`` into the org's row — the same semantics as the deployment
    ``set_config``: a non-empty value sets, ``""`` clears, a masked key is left
    unchanged, new keys are encrypted before they touch disk, and a paid OpenRouter
    model requires ``allow_paid`` (the free-by-default ratchet applies to tenants
    exactly as it does to the operator).
    """
    from aughor.llm.provider import (BACKENDS, NEEDS_KEY, ROLES, active_backend,
                                     ensure_free_or_allowed)
    from aughor.secretvault import encrypt_secret, is_masked

    org_id = org_id or DEFAULT_ORG_ID
    current = _row(org_id) or {"backend": "", "models": {}, "keys": {}}

    if patch.get("backend") is not None:
        backend = str(patch["backend"]).strip()
        if backend and backend not in BACKENDS:
            raise ValueError(f"unknown backend {backend!r}")
        current["backend"] = backend

    if isinstance(patch.get("models"), dict):
        # The ratchet checks against the backend the model will actually SERVE on: the
        # org's own when set, else the deployment's — an org model over an openrouter
        # deployment must not slip a paid binding past the free-by-default rule.
        effective_backend = current.get("backend") or active_backend()
        allow_paid = bool(patch.get("allow_paid"))
        models = dict(current.get("models") or {})
        for role, model in patch["models"].items():
            if role not in ROLES:
                continue
            if model and str(model).strip():
                ensure_free_or_allowed(effective_backend, str(model).strip(),
                                       allow_paid=allow_paid)
                models[role] = str(model).strip()
            else:
                models.pop(role, None)
        current["models"] = models

    if isinstance(patch.get("keys"), dict):
        keys = dict(current.get("keys") or {})
        for backend, key in patch["keys"].items():
            if backend not in NEEDS_KEY:
                continue
            if key is None or is_masked(key):
                continue  # unchanged
            if str(key).strip() == "":
                keys.pop(backend, None)
            else:
                keys[backend] = encrypt_secret(str(key).strip())
        current["keys"] = keys

    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    try:
        c.execute(
            """INSERT INTO org_llm_config (org_id, backend, models, keys, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(org_id) DO UPDATE SET
                   backend = excluded.backend, models = excluded.models,
                   keys = excluded.keys, updated_at = excluded.updated_at""",
            (org_id, current.get("backend", ""),
             json.dumps(current.get("models") or {}),
             json.dumps(current.get("keys") or {}), now))
        c.commit()
    finally:
        c.close()
    evict(org_id)
    return describe_org_config(org_id)


def clear_org_config(org_id: str) -> None:
    """Remove the org's row entirely — it falls back to the deployment config."""
    org_id = org_id or DEFAULT_ORG_ID
    c = _conn()
    try:
        c.execute("DELETE FROM org_llm_config WHERE org_id = ?", (org_id,))
        c.commit()
    finally:
        c.close()
    evict(org_id)


def describe_org_config(org_id: str) -> dict:
    """The secret-free view for the org panel: backend, models, which keys are set
    — never a key value, masked or otherwise (masking is a preview convenience for
    the deployment settings; a tenant surface gets a boolean and nothing more)."""
    overlay = overlay_for(org_id or DEFAULT_ORG_ID)
    return {
        "configured": bool(overlay),
        "backend": overlay.get("backend", ""),
        "models": dict(overlay.get("models") or {}),
        "keys_set": {b: True for b in (overlay.get("keys") or {})},
        "updated_at": overlay.get("updated_at", ""),
    }
