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
from typing import Any, Optional, Sequence, Union


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

    def delete(self, key: str) -> bool:
        """Drop one key. Returns whether it existed — callers count removals to report
        an invalidation that actually removed something vs one that found nothing."""
        try:
            return self._ledger().kv_delete(self._store_id, key)
        except Exception:
            cache = self._file_load()
            if key not in cache:
                return False
            del cache[key]
            self._file_save(cache)
            return True

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


class FileFamilyStore(KeyedJsonStore):
    """A KeyedJsonStore for a family whose LEGACY layout was one file PER KEY
    (``{prefix}{key}.json`` in a directory) rather than one dict file.

    The exploration / business-profile stores wrote ``exploration_{conn}.json``,
    ``business_profile_{conn}__{schema}.json``, … — so the base class's import-the-
    one-legacy-file-once contract doesn't fit. Here each KEY imports on first touch,
    and listing / purging consider both the store and any not-yet-imported files, so
    a deployment mid-migration never sees a partial family. Legacy files are read
    and (on purge) unlinked, but never rewritten.
    """

    def __init__(self, dir_path: Union[str, Path], file_prefix: str):
        self.dir = Path(dir_path)
        self.prefix = file_prefix
        super().__init__(self.dir / f"{file_prefix.rstrip('_')}__family.json")

    def _legacy_path(self, key: str) -> Path:
        return self.dir / f"{self.prefix}{key}.json"

    def get_entry(self, key: str) -> Optional[dict]:
        """The entry for ``key`` — from the store, else imported from its legacy file."""
        value = self.get(key)
        if value is not None:
            return value
        p = self._legacy_path(key)
        if p.exists():
            try:
                value = json.loads(p.read_text())
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "family-store legacy read is best-effort; corrupt file treated as absent",
                         counter="json_store.family_read")
                return None
            self.put(key, value)   # import once; the file stays as the on-disk record
            return value
        return None

    def has_entry(self, key: str) -> bool:
        return self.get(key) is not None or self._legacy_path(key).exists()

    def keys_with_prefix(self, key_prefix: str) -> list[str]:
        """Every key starting with ``key_prefix`` — store keys and legacy files, deduped."""
        keys = {k for k in self.load() if k.startswith(key_prefix)}
        for p in self.dir.glob(f"{self.prefix}{key_prefix}*.json"):
            if p.name != self.path.name:
                keys.add(p.stem[len(self.prefix):])
        return sorted(keys)

    def purge_entries(self, *, exact: Sequence[str] = (), key_prefix: Optional[str] = None) -> int:
        """Remove entries by exact key and/or key prefix — store row AND legacy file,
        counted once per KEY (an imported entry exists in both places but is one
        thing). This is the seam the purge cascade calls, so deletion semantics live
        with the store rather than as filename globs in db/purge.py."""
        candidates = set(exact)
        if key_prefix is not None:
            candidates.update(self.keys_with_prefix(key_prefix))
        removed: set[str] = set()
        for key in candidates:
            if self.delete(key):
                removed.add(key)
            p = self._legacy_path(key)
            if p.exists():
                try:
                    p.unlink()
                    removed.add(key)
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "family-store legacy unlink is best-effort; the store row is gone",
                             counter="json_store.family_purge")
        return len(removed)


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


class LedgerListStore(JsonListStore):
    """A :class:`JsonListStore` whose truth is the kernel Ledger — list-shaped K0.

    Same API and best-effort contract; the rows live in the Ledger's transactional
    kv table keyed by ``id_field``, in insertion order (the kv ``seq`` preserves
    it), so ``all()`` reads back in the order rows were first saved and ``upsert``
    moves a row to the end exactly as the file version's remove-then-append did.

    Exists for the list stores that must survive a serverless instance. The file
    version wrote under ``data/``, which a read-only bundle both ships empty and
    refuses to write — so on Vercel a brief subscription "created" there
    evaporated with the response, and every cron tick evaluated zero briefs. The
    Ledger rides ``AUGHOR_DB_URL`` (Postgres on serverless), which is durable.

    The legacy JSON file is imported once (marker in Ledger meta) and then left
    on disk untouched; every method falls back to the original file behaviour
    when the Ledger is unavailable, exactly as :class:`KeyedJsonStore` does.
    """

    def __init__(self, path: Union[str, Path], *, id_field: str = "id", indent: int = 2):
        super().__init__(path, id_field=id_field, indent=indent)
        self._store_id = str(self.path)
        self._migrated = False

    def _key(self, item_or_id: Any) -> str:
        if isinstance(item_or_id, dict):
            return str(item_or_id.get(self.id_field))
        return str(item_or_id)

    def _as_dict(self, items: list[dict]) -> dict:
        return {self._key(d): d for d in items}

    def _ledger(self):
        from aughor.kernel.ledger import Ledger
        led = Ledger.default()
        if not self._migrated:
            marker = f"migrated:{self._store_id}"
            if not led.meta_get(marker):
                legacy = super().all()          # the file, read the original way
                if legacy:
                    led.kv_replace_all(self._store_id, self._as_dict(legacy))
                led.meta_set(marker, "1")
            self._migrated = True
        return led

    def all(self) -> list[dict]:
        try:
            return list(self._ledger().kv_load_all(self._store_id).values())
        except Exception:
            return super().all()

    def save_all(self, items: list[dict]) -> None:
        try:
            self._ledger().kv_replace_all(self._store_id, self._as_dict(items))
        except Exception:
            super().save_all(items)

    def get(self, id_: str) -> Optional[dict]:
        try:
            return self._ledger().kv_get(self._store_id, self._key(id_), None)
        except Exception:
            return super().get(id_)

    def upsert(self, item: dict) -> None:
        try:
            self._ledger().kv_put(self._store_id, self._key(item), item)
        except Exception:
            super().upsert(item)

    def delete(self, id_: str) -> bool:
        try:
            return bool(self._ledger().kv_delete(self._store_id, self._key(id_)))
        except Exception:
            return super().delete(id_)
