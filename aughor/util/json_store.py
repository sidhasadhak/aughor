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
    def __init__(self, path: Union[str, Path], *, max_entries: Optional[int] = None, indent: int = 2):
        self.path = Path(path)
        self.max_entries = max_entries
        self.indent = indent

    def load(self) -> dict:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text())
        except Exception:
            pass
        return {}

    def save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=self.indent, default=str))
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get(key, default)

    def put(self, key: str, value: Any) -> None:
        """Insert/update `key` as most-recently-used; evict oldest past `max_entries`."""
        cache = self.load()
        cache.pop(key, None)          # move-to-end (MRU on insertion order)
        cache[key] = value
        if self.max_entries:
            while len(cache) > self.max_entries:
                del cache[next(iter(cache))]
        self.save(cache)

    def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key starting with `prefix`. Returns how many were removed."""
        cache = self.load()
        evict = [k for k in cache if k.startswith(prefix)]
        for k in evict:
            del cache[k]
        if evict:
            self.save(cache)
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
        except Exception:
            pass
        return []

    def save_all(self, items: list[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(items, indent=self.indent, default=str))
        except Exception:
            pass

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
