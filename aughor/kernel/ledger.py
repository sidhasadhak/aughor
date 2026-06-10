"""The Ledger — the kernel's single transactional state store (stage K0).

One SQLite database (``data/system.db``, WAL mode) replaces the ad-hoc JSON cache
files whose unlocked load→mutate→save round-trips were a confirmed corruption
class (concurrent ontology builds, profile cache races). It also hosts the
append-only **event journal** — the platform's own transaction log — which K1's
job kernel and K2's UI event stream build on.

Design constraints honoured here:
- **Leverage, don't duplicate** (user principle): SQLite is already the house
  pattern (history.db, evidence_ledger.db, …). This adds kernel tables, not a
  new technology. Existing domain SQLite stores are untouched in K0.
- **Never a rewrite**: ``KeyedJsonStore`` keeps its exact API and becomes a
  facade over the ledger (see aughor/util/json_store.py); legacy JSON files are
  imported once and left on disk untouched.
- **Loud kernel, quiet facade**: Ledger methods raise on real failures (kernel
  errors must be visible); the facade preserves the old best-effort contract.

Tables:
  kv(store, key, value, seq, updated_at)  — the cache backend; ``seq`` is a
      ledger-monotonic counter giving each store an MRU order (oldest = lowest).
  events(seq, at, kind, conn_id, canvas_id, job_id, payload)  — append-only.
  meta(k, v)  — kernel bookkeeping (e.g. one-time legacy-import markers).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "system.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  store      TEXT NOT NULL,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (store, key)
);
CREATE INDEX IF NOT EXISTS kv_store_seq ON kv(store, seq);
CREATE TABLE IF NOT EXISTS events (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  at        TEXT NOT NULL,
  kind      TEXT NOT NULL,
  conn_id   TEXT,
  canvas_id TEXT,
  job_id    TEXT,
  payload   TEXT
);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, seq);
CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY,
  v TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    """Thread-safe transactional store. One instance per database path."""

    _instances: dict[str, "Ledger"] = {}
    _instances_lock = threading.Lock()

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    @classmethod
    def default(cls) -> "Ledger":
        """The process-wide ledger. ``AUGHOR_SYSTEM_DB`` overrides the path
        (tests point it at a tmp dir so runs stay hermetic)."""
        path = str(Path(os.environ.get("AUGHOR_SYSTEM_DB", _DEFAULT_DB)))
        with cls._instances_lock:
            inst = cls._instances.get(path)
            if inst is None:
                inst = cls._instances[path] = cls(path)
            return inst

    # ── kv: the cache backend ────────────────────────────────────────────────

    def _next_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM kv").fetchone()
        return int(row[0])

    def kv_get(self, store: str, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv WHERE store=? AND key=?", (store, key)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def kv_put(self, store: str, key: str, value: Any, *, max_entries: Optional[int] = None) -> None:
        """Atomic insert/update as most-recently-used; evicts oldest past the cap.
        This single transaction replaces the load-all→mutate→save-all round-trip
        that made concurrent puts last-write-wins corrupt each other."""
        payload = json.dumps(value, default=str)
        with self._lock, self._conn:
            seq = self._next_seq()
            self._conn.execute(
                "INSERT INTO kv (store, key, value, seq, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(store, key) DO UPDATE SET value=excluded.value, "
                "seq=excluded.seq, updated_at=excluded.updated_at",
                (store, key, payload, seq, _now()),
            )
            if max_entries:
                self._conn.execute(
                    "DELETE FROM kv WHERE store=? AND key NOT IN ("
                    "  SELECT key FROM kv WHERE store=? ORDER BY seq DESC LIMIT ?)",
                    (store, store, max_entries),
                )

    def kv_delete(self, store: str, key: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM kv WHERE store=? AND key=?", (store, key))
        return cur.rowcount > 0

    def kv_load_all(self, store: str) -> dict:
        """Whole store as a dict, oldest-first (parity with the JSON file whose
        insertion order encoded MRU — ``next(iter(d))`` is the eviction victim)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM kv WHERE store=? ORDER BY seq ASC", (store,)
            ).fetchall()
        return {k: json.loads(v) for k, v in rows}

    def kv_replace_all(self, store: str, data: dict, *, max_entries: Optional[int] = None) -> None:
        """Atomically replace the whole store (the facade's ``save``)."""
        items = list(data.items())
        if max_entries and len(items) > max_entries:
            items = items[-max_entries:]          # keep the newest (end of dict)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM kv WHERE store=?", (store,))
            seq = self._next_seq()
            now = _now()
            for i, (k, v) in enumerate(items):
                self._conn.execute(
                    "INSERT INTO kv (store, key, value, seq, updated_at) VALUES (?,?,?,?,?)",
                    (store, k, json.dumps(v, default=str), seq + i, now),
                )

    def kv_invalidate_prefix(self, store: str, prefix: str) -> int:
        with self._lock, self._conn:
            keys = [
                r[0] for r in self._conn.execute(
                    "SELECT key FROM kv WHERE store=?", (store,)
                ).fetchall()
                if r[0].startswith(prefix)
            ]
            for k in keys:
                self._conn.execute("DELETE FROM kv WHERE store=? AND key=?", (store, k))
        return len(keys)

    # ── meta ─────────────────────────────────────────────────────────────────

    def meta_get(self, k: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def meta_set(self, k: str, v: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO meta (k, v) VALUES (?,?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, v),
            )

    # ── events: the append-only journal ──────────────────────────────────────

    def emit(
        self,
        kind: str,
        payload: Any = None,
        *,
        conn_id: Optional[str] = None,
        canvas_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> int:
        """Append one event; returns its seq. Every state transition the kernel
        cares about flows through here — 'why did X happen at 14:32' becomes a
        query instead of an archaeology dig."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (at, kind, conn_id, canvas_id, job_id, payload) "
                "VALUES (?,?,?,?,?,?)",
                (_now(), kind, conn_id, canvas_id, job_id,
                 json.dumps(payload, default=str) if payload is not None else None),
            )
        return int(cur.lastrowid)

    def events(
        self,
        *,
        kind: Optional[str] = None,
        conn_id: Optional[str] = None,
        since_seq: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict]:
        q = "SELECT seq, at, kind, conn_id, canvas_id, job_id, payload FROM events WHERE 1=1"
        args: list[Any] = []
        if kind:
            q += " AND kind=?"; args.append(kind)
        if conn_id:
            q += " AND conn_id=?"; args.append(conn_id)
        if since_seq is not None:
            q += " AND seq>?"; args.append(since_seq)
        q += " ORDER BY seq DESC LIMIT ?"; args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for seq, at, k, c, cv, j, p in rows:
            out.append({
                "seq": seq, "at": at, "kind": k, "conn_id": c,
                "canvas_id": cv, "job_id": j,
                "payload": json.loads(p) if p else None,
            })
        return out
