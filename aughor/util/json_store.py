"""Small JSON-file persistence primitives — one home for the load/save/LRU/upsert
plumbing that was re-implemented in ~17 store modules.

Each store keeps its own typed public API and domain (de)serialization (TableProfile,
OntologyGraph, ActionTrigger, …); only the file I/O is shared here. All writes are
best-effort (a failed write never raises into the caller) and reads return an empty
container on a missing/corrupt file.

Two shapes:
  - `KeyedJsonStore`  — a dict keyed by id (optionally LRU-capped), e.g. the profile /
    ontology / schema caches.
  - `JsonListStore`   — a list of dicts with upsert/delete by an id field, e.g. action
    triggers, brief subscriptions, playbooks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union


class KeyedJsonStore:
    """K0: a FACADE over the kernel Ledger (aughor/kernel/ledger.py). The API and
    best-effort contract are unchanged, but storage is now a transactional SQLite
    table — the unlocked load→mutate→save race that corrupted the ontology /
    profile caches under concurrent builds is gone by construction.

    The legacy JSON file is imported ONCE on first use (marker in ledger meta)
    and then left on disk untouched. If the ledger is unavailable for any
    reason, every method falls back to the original file behaviour."""

    def __init__(self, path: Union[str, Path], *, max_entries: Optional[int] = None, indent: int = 2):
        self.path = Path(path)
        self.max_entries = max_entries
        self.indent = indent
        self._store_id = str(self.path)
        self._migrated = False

    # ── ledger plumbing ──────────────────────────────────────────────────────

    def _ledger(self):
        from aughor.kernel.ledger import Ledger
        led = Ledger.default()
        if not self._migrated:
            marker = f"migrated:{self._store_id}"
            if not led.meta_get(marker):
                legacy = self._file_load()
                if legacy:
                    led.kv_replace_all(self._store_id, legacy, max_entries=self.max_entries)
                led.meta_set(marker, "1")
            self._migrated = True
        return led

    # ── original file primitives (fallback path) ─────────────────────────────

    def _file_load(self) -> dict:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text())
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "JSON store read is best-effort; empty container returned on missing/corrupt file", counter="json_store.read")
        return {}

    def _file_save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=self.indent, default=str))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "JSON store write is best-effort; a failed write never raises into the caller", counter="json_store.write")

    # ── public API (unchanged) ───────────────────────────────────────────────

    def load(self) -> dict:
        try:
            return self._ledger().kv_load_all(self._store_id)
        except Exception:
            return self._file_load()

    def save(self, data: dict) -> None:
        try:
            self._ledger().kv_replace_all(self._store_id, data, max_entries=self.max_entries)
        except Exception:
            self._file_save(data)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self._ledger().kv_get(self._store_id, key, default)
        except Exception:
            return self._file_load().get(key, default)

    def put(self, key: str, value: Any) -> None:
        """Insert/update `key` as most-recently-used; evict oldest past `max_entries`."""
        try:
            self._ledger().kv_put(self._store_id, key, value, max_entries=self.max_entries)
        except Exception:
            cache = self._file_load()
            cache.pop(key, None)          # move-to-end (MRU on insertion order)
            cache[key] = value
            if self.max_entries:
                while len(cache) > self.max_entries:
                    del cache[next(iter(cache))]
            self._file_save(cache)

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key starting with `prefix`. Returns how many were removed."""
        try:
            return self._ledger().kv_invalidate_prefix(self._store_id, prefix)
        except Exception:
            cache = self._file_load()
            evict = [k for k in cache if k.startswith(prefix)]
            for k in evict:
                del cache[k]
            if evict:
                self._file_save(cache)
            return len(evict)


class JsonListStore:
    def __init__(self, path: Union[str, Path], *, id_field: str = "id", indent: int = 2):
        self.path = Path(path)
        self.id_field = id_field
        self.indent = indent

    def all(self) -> list[dict]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                return data if isinstance(data, list) else []
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "JSON list-store read is best-effort; empty list returned on missing/corrupt file", counter="json_store.list_read")
        return []

    def save_all(self, items: list[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(items, indent=self.indent, default=str))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "JSON list-store write is best-effort; a failed write never raises into the caller", counter="json_store.list_write")

    def get(self, id_: str) -> Optional[dict]:
        return next((d for d in self.all() if d.get(self.id_field) == id_), None)

    def upsert(self, item: dict) -> None:
        """Replace any existing item with the same id, else append."""
        items = [d for d in self.all() if d.get(self.id_field) != item.get(self.id_field)]
        items.append(item)
        self.save_all(items)

    def delete(self, id_: str) -> bool:
        items = self.all()
        kept = [d for d in items if d.get(self.id_field) != id_]
        if len(kept) == len(items):
            return False
        self.save_all(kept)
        return True

    def append(self, item: dict) -> None:
        """Append-only (logs)."""
        items = self.all()
        items.append(item)
        self.save_all(items)
