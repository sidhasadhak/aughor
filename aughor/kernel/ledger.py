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
  events(seq, at, kind, conn_id, canvas_id, job_id, trace_id, payload)  — append-only.
  meta(k, v)  — kernel bookkeeping (e.g. one-time legacy-import markers).
  session_events(...)  — the agent-session log (Wave E1, flag `obs.session_log`).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.org.context import current_org_id

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "system.db"

# Amortise session-log retention over inserts (see Ledger._session_events_maybe_prune).
_SESSION_EVENT_PRUNE_EVERY = 500

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
CREATE TABLE IF NOT EXISTS artifacts (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  natural_key  TEXT NOT NULL,
  version      INTEGER NOT NULL,
  conn_id      TEXT,
  canvas_id    TEXT,
  org_id       TEXT NOT NULL DEFAULT 'default',
  payload      TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  created_by_job TEXT,
  superseded_by  TEXT
);
CREATE INDEX IF NOT EXISTS artifacts_nk ON artifacts(natural_key, version);
CREATE TABLE IF NOT EXISTS lineage (
  artifact_id  TEXT NOT NULL,
  relation     TEXT NOT NULL,
  ref          TEXT NOT NULL,
  detail       TEXT,
  org_id       TEXT NOT NULL DEFAULT 'default'
);
CREATE INDEX IF NOT EXISTS lineage_artifact ON lineage(artifact_id);
CREATE TABLE IF NOT EXISTS jobs (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,
  conn_id         TEXT,
  canvas_id       TEXT,
  org_id          TEXT NOT NULL DEFAULT 'default',
  state           TEXT NOT NULL,
  payload         TEXT,
  error           TEXT,
  idempotency_key TEXT,
  attempt         INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL,
  started_at      TEXT,
  heartbeat_at    TEXT,
  finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_scope ON jobs(conn_id, canvas_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add_kernel_org_ids(c: sqlite3.Connection) -> None:
    """Tenant key on the kernel's job/artifact/lineage rows (back-fills to 'default')."""
    add_column_if_missing(c, "jobs", "org_id", "TEXT NOT NULL DEFAULT 'default'")
    add_column_if_missing(c, "artifacts", "org_id", "TEXT NOT NULL DEFAULT 'default'")
    add_column_if_missing(c, "lineage", "org_id", "TEXT NOT NULL DEFAULT 'default'")


def _create_task_history(c: sqlite3.Connection) -> None:
    """The `task_history` spine (Rec 4 of the 2026-07-11 platform study, flag
    `obs.task_table`): one append-only row per span, with Spice's exact shape, so
    "what did the agent actually do" is a SELECT instead of a log grep. It is a
    SINK for the span events telemetry already emits — the writer only fires under
    the flag, so an unflagged DB keeps this table empty (byte-identical)."""
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS task_history (
          span_id        TEXT PRIMARY KEY,
          trace_id       TEXT,
          parent_span_id TEXT,
          task           TEXT NOT NULL,
          input          TEXT,
          captured_output TEXT,
          start_time     TEXT NOT NULL,
          end_time       TEXT,
          duration_ms    REAL,
          error_message  TEXT,
          labels         TEXT,
          org_id         TEXT NOT NULL DEFAULT 'default'
        );
        CREATE INDEX IF NOT EXISTS task_history_trace ON task_history(trace_id, start_time);
        CREATE INDEX IF NOT EXISTS task_history_task ON task_history(task, start_time);
        """
    )


def _create_session_events(c: sqlite3.Connection) -> None:
    """The `session_events` log (Wave E1, flag `obs.session_log`): one append-only
    row per agent-session event, so "reconstruct this run" is a single ordered
    SELECT.

    Distinct from `task_history`, which is SPAN-shaped — one row per *completed*
    unit of work, ordered by a start-time string. This is EVENT-shaped: separate
    records with a monotonic `seq`, written as things happen. That difference is
    the point. A `tool_call` is written on entry, so a call that hangs, is
    cancelled, or dies with the process still leaves evidence; a span row only
    ever appears after the body returns. It also carries the identity
    (`session_id`/`user_id`/`agent_id`) and the explicit `ok` boolean that
    `task_history` has no column for.

    A pure SINK: nothing writes here unless `obs.session_log` is on.
    """
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS session_events (
          seq              INTEGER PRIMARY KEY AUTOINCREMENT,
          at               TEXT NOT NULL,
          trace_id         TEXT NOT NULL,
          kind             TEXT NOT NULL,
          name             TEXT,
          span_id          TEXT,
          parent_span_id   TEXT,
          ok               INTEGER,
          duration_ms      REAL,
          error_class      TEXT,
          investigation_id TEXT,
          session_id       TEXT,
          user_id          TEXT,
          agent_id         TEXT,
          conn_id          TEXT,
          org_id           TEXT NOT NULL DEFAULT 'default',
          payload          TEXT
        );
        CREATE INDEX IF NOT EXISTS session_events_trace ON session_events(trace_id, seq);
        CREATE INDEX IF NOT EXISTS session_events_kind ON session_events(kind, seq);
        CREATE INDEX IF NOT EXISTS session_events_session ON session_events(session_id, seq);
        """
    )


# Schema evolution (DATA-05). The kernel tables in _SCHEMA are v1; changes are Migration(v>=2).
_MIGRATIONS = [
    Migration(2, "per-run compute metering (jobs.metrics)",
              lambda c: add_column_if_missing(c, "jobs", "metrics", "TEXT")),
    Migration(3, "tenant key on jobs/artifacts/lineage", _add_kernel_org_ids),
    Migration(4, "task_history spans-as-a-table (obs.task_table)", _create_task_history),
    Migration(5, "session_events agent-session log (obs.session_log)", _create_session_events),
    # Wave E1: correlate the journal to the run that produced it. All ~29 event
    # kinds gain this at once because emit() defaults it from the ambient trace —
    # no call site changes. Until now `node.span` smuggled the trace into job_id
    # and nothing else in the journal was correlated at all.
    Migration(6, "correlation key: trace_id on events",
              lambda c: add_column_if_missing(c, "events", "trace_id", "TEXT NOT NULL DEFAULT ''")),
]


class Ledger:
    """Thread-safe transactional store. One instance per database path."""

    _instances: dict[str, "Ledger"] = {}
    _instances_lock = threading.Lock()

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._session_event_writes = 0  # drives amortised session-log retention
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")  # wait for a lock, don't SQLITE_BUSY instantly (DATA-02)
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            with self._conn:
                self._conn.executescript(_SCHEMA)
            # Schema evolution through the versioned framework (DATA-05). Idempotent +
            # forward-only; back-fills existing rows to the bootstrap org.
            run_migrations(self._conn, _MIGRATIONS, store="ledger")

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

    # ── artifacts + lineage: versioned outputs with provenance (K3) ──────────
    # Supersede, never delete — the preserve-artifacts rule at schema level.
    # A Trust Receipt is a SELECT over these two tables, not a feature build.

    def artifact_write(
        self,
        kind: str,
        natural_key: str,
        payload: Any,
        *,
        conn_id: Optional[str] = None,
        canvas_id: Optional[str] = None,
        org_id: Optional[str] = None,
        created_by_job: Optional[str] = None,
        lineage: Optional[list[tuple[str, str, Optional[str]]]] = None,
    ) -> str:
        """Write a new VERSION of an artifact (id returned). The previous
        version (if any) gets `superseded_by` set — never deleted. ``lineage``
        is a list of (relation, ref, detail) provenance edges. ``org_id`` defaults
        to the current tenant context so every receipt is tenant-keyed."""
        import uuid as _uuid
        art_id = _uuid.uuid4().hex[:12]
        oid = org_id or current_org_id()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id, version FROM artifacts WHERE natural_key=? AND superseded_by IS NULL "
                "ORDER BY version DESC LIMIT 1", (natural_key,)
            ).fetchone()
            prev_id, prev_ver = (row[0], row[1]) if row else (None, 0)
            self._conn.execute(
                "INSERT INTO artifacts (id, kind, natural_key, version, conn_id, canvas_id, "
                "org_id, payload, created_at, created_by_job) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (art_id, kind, natural_key, prev_ver + 1, conn_id, canvas_id,
                 oid, json.dumps(payload, default=str), _now(), created_by_job),
            )
            if prev_id:
                self._conn.execute(
                    "UPDATE artifacts SET superseded_by=? WHERE id=?", (art_id, prev_id)
                )
            for relation, ref, detail in (lineage or []):
                self._conn.execute(
                    "INSERT INTO lineage (artifact_id, relation, ref, detail, org_id) VALUES (?,?,?,?,?)",
                    (art_id, relation, ref, detail, oid),
                )
        return art_id

    @staticmethod
    def _artifact_row(cur, row) -> Optional[dict]:
        """A fetched artifacts row → dict with its JSON payload decoded (best-effort — a
        non-JSON payload stays a string). Shared by artifact_latest/artifact_by_id."""
        if row is None:
            return None
        out = dict(zip([d[0] for d in cur.description], row))
        try:
            out["payload"] = json.loads(out["payload"])
        except Exception:
            pass
        return out

    def artifact_latest(self, natural_key: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM artifacts WHERE natural_key=? ORDER BY version DESC LIMIT 1",
                (natural_key,),
            )
            return self._artifact_row(cur, cur.fetchone())

    def artifact_by_id(self, art_id: str) -> Optional[dict]:
        """One artifact by its stable id (the receipt id — WP-10), payload decoded.
        Unlike ``artifact_latest`` (keyed by natural_key → newest version) this resolves
        the EXACT version a caller was handed, so a receipt link is immutable."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM artifacts WHERE id=? LIMIT 1", (art_id,))
            return self._artifact_row(cur, cur.fetchone())

    def _receipt_from_artifact(self, art: Optional[dict]) -> Optional[dict]:
        """Assemble the Trust Receipt view from a resolved artifact: provenance edges
        + the job that computed it + one normalized cost field."""
        if art is None:
            return None
        with self._lock:
            edges = self._conn.execute(
                "SELECT relation, ref, detail FROM lineage WHERE artifact_id=?", (art["id"],)
            ).fetchall()
        job = self.job_get(art["created_by_job"]) if art.get("created_by_job") else None
        job_view = (
            {k: job.get(k) for k in ("id", "kind", "state", "started_at", "finished_at", "metrics")}
            if job else None
        )
        # One normalized cost field for consumers: the job-row metrics (full per-run
        # total) when this artifact was produced by a kernel job, else the cost
        # stamped on the artifact itself (the synchronous chat/insight path has no job).
        cost = None
        if job_view and job_view.get("metrics"):
            cost = job_view["metrics"]
        elif isinstance(art.get("payload"), dict):
            cost = art["payload"].get("cost")
        return {
            "artifact": art,
            "lineage": [{"relation": r, "ref": ref, "detail": d} for r, ref, d in edges],
            "job": job_view,
            "cost": cost,
        }

    def receipt(self, natural_key: str) -> Optional[dict]:
        """The Trust Receipt: the latest artifact version + its provenance edges
        + the job that computed it. One query path answers 'why should I trust
        this number'."""
        return self._receipt_from_artifact(self.artifact_latest(natural_key))

    def receipt_by_id(self, art_id: str) -> Optional[dict]:
        """The Trust Receipt for one EXACT artifact id (the receipt id — WP-10's unified
        `GET /receipt/{id}`), rather than the latest version of a natural_key."""
        return self._receipt_from_artifact(self.artifact_by_id(art_id))

    # ── jobs: rows for the K1 job kernel (state machine lives in jobs.py) ────

    def job_insert(self, row: dict) -> None:
        cols = ("id", "kind", "conn_id", "canvas_id", "org_id", "state", "payload", "error",
                "idempotency_key", "attempt", "created_at", "started_at",
                "heartbeat_at", "finished_at")
        row = {**row, "org_id": row.get("org_id") or current_org_id()}
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                tuple(
                    json.dumps(row.get(c), default=str) if c == "payload" and row.get(c) is not None
                    else row.get(c)
                    for c in cols
                ),
            )

    def job_update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id)
            )

    def job_get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
        out = dict(zip(cols, row))
        for _jf in ("payload", "metrics"):
            if out.get(_jf):
                try:
                    out[_jf] = json.loads(out[_jf])
                except Exception:
                    pass
        return out

    def jobs_where(self, *, states: Optional[list[str]] = None,
                   conn_id: Optional[str] = None, canvas_id: Optional[str] = None,
                   idempotency_key: Optional[str] = None, limit: int = 500) -> list[dict]:
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if states:
            q += f" AND state IN ({','.join('?' * len(states))})"; args.extend(states)
        if conn_id is not None:
            q += " AND conn_id=?"; args.append(conn_id)
        if canvas_id is not None:
            q += " AND canvas_id=?"; args.append(canvas_id)
        if idempotency_key is not None:
            q += " AND idempotency_key=?"; args.append(idempotency_key)
        q += " ORDER BY created_at DESC LIMIT ?"; args.append(int(limit))
        with self._lock:
            cur = self._conn.execute(q, args)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            for _jf in ("payload", "metrics"):
                if d.get(_jf):
                    try:
                        d[_jf] = json.loads(d[_jf])
                    except Exception:
                        pass
            out.append(d)
        return out

    # ── events: the append-only journal ──────────────────────────────────────

    def emit(
        self,
        kind: str,
        payload: Any = None,
        *,
        conn_id: Optional[str] = None,
        canvas_id: Optional[str] = None,
        job_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> int:
        """Append one event; returns its seq. Every state transition the kernel
        cares about flows through here — 'why did X happen at 14:32' becomes a
        query instead of an archaeology dig.

        ``trace_id`` defaults to the ambient run, so every kind correlates to the
        run that caused it without a single call site being touched."""
        if trace_id is None:
            try:
                from aughor.telemetry import current_trace_id
                trace_id = current_trace_id()
            except Exception:
                trace_id = ""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (at, kind, conn_id, canvas_id, job_id, payload, trace_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (_now(), kind, conn_id, canvas_id, job_id,
                 json.dumps(payload, default=str) if payload is not None else None,
                 trace_id or ""),
            )
        return int(cur.lastrowid)

    def events(
        self,
        *,
        kind: Optional[str] = None,
        conn_id: Optional[str] = None,
        job_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        since_seq: Optional[int] = None,
        limit: int = 200,
    ) -> list[dict]:
        q = ("SELECT seq, at, kind, conn_id, canvas_id, job_id, payload, trace_id "
             "FROM events WHERE 1=1")
        args: list[Any] = []
        if trace_id:
            q += " AND trace_id=?"; args.append(trace_id)
        if kind:
            q += " AND kind=?"; args.append(kind)
        if conn_id:
            q += " AND conn_id=?"; args.append(conn_id)
        if job_id:
            q += " AND job_id=?"; args.append(job_id)
        if since_seq is not None:
            q += " AND seq>?"; args.append(since_seq)
        q += " ORDER BY seq DESC LIMIT ?"; args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for seq, at, k, c, cv, j, p, tid in rows:
            out.append({
                "seq": seq, "at": at, "kind": k, "conn_id": c,
                "canvas_id": cv, "job_id": j, "trace_id": tid,
                "payload": json.loads(p) if p else None,
            })
        return out

    # ── task_history: spans as a queryable table (Rec 4, flag obs.task_table) ──

    def task_history_insert(self, row: dict) -> None:
        """Append one span row. Idempotent on ``span_id`` (INSERT OR REPLACE) so a
        double-emit — a retried wave, a redelivered event — never duplicates. The
        writer (``telemetry.span``) only calls this under the ``obs.task_table``
        flag; an unflagged process leaves the table empty."""
        labels = row.get("labels")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO task_history "
                "(span_id, trace_id, parent_span_id, task, input, captured_output, "
                " start_time, end_time, duration_ms, error_message, labels, org_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["span_id"], row.get("trace_id"), row.get("parent_span_id"),
                    row["task"], row.get("input"), row.get("captured_output"),
                    row["start_time"], row.get("end_time"), row.get("duration_ms"),
                    row.get("error_message"),
                    json.dumps(labels, default=str) if labels is not None else None,
                    row.get("org_id") or "default",
                ),
            )

    def task_history(
        self,
        *,
        trace_id: Optional[str] = None,
        task: Optional[str] = None,
        task_prefix: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Read span rows, newest first. ``task_prefix`` matches a taxonomy family
        (e.g. ``ada.node.`` or ``tool.``); ``task`` matches exactly."""
        q = ("SELECT span_id, trace_id, parent_span_id, task, input, captured_output, "
             "start_time, end_time, duration_ms, error_message, labels, org_id "
             "FROM task_history WHERE 1=1")
        args: list[Any] = []
        if trace_id:
            q += " AND trace_id=?"; args.append(trace_id)
        if task:
            q += " AND task=?"; args.append(task)
        if task_prefix:
            q += " AND task LIKE ?"; args.append(task_prefix.replace("%", r"\%") + "%")
        if org_id:
            q += " AND org_id=?"; args.append(org_id)
        q += " ORDER BY start_time DESC, rowid DESC LIMIT ?"; args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for (sid, tid, pid, task_, inp, outp, st, et, dur, err, lbl, org) in rows:
            out.append({
                "span_id": sid, "trace_id": tid, "parent_span_id": pid,
                "task": task_, "input": inp, "captured_output": outp,
                "start_time": st, "end_time": et, "duration_ms": dur,
                "error_message": err,
                "labels": json.loads(lbl) if lbl else None, "org_id": org,
            })
        return out

    # ── session_events: the agent-session log (Wave E1, flag obs.session_log) ──

    _SESSION_EVENT_COLS = (
        "seq", "at", "trace_id", "kind", "name", "span_id", "parent_span_id",
        "ok", "duration_ms", "error_class", "investigation_id", "session_id",
        "user_id", "agent_id", "conn_id", "org_id", "payload",
    )

    def session_event_insert(self, row: dict) -> int:
        """Append one session event; returns its ``seq``.

        Unlike ``task_history_insert`` this is NOT idempotent on a key — every
        call is a distinct occurrence, and ``seq`` (AUTOINCREMENT) is the
        within-run ordering that ``task_history``'s start-time string cannot give
        (equal-millisecond spans there tie-break on a random span id).

        Retention runs opportunistically here rather than from a sweep so the
        table cannot grow unbounded if no scheduler is running — the failure mode
        `events`/`task_history` both have today.
        """
        payload = row.get("payload")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO session_events "
                "(at, trace_id, kind, name, span_id, parent_span_id, ok, duration_ms, "
                " error_class, investigation_id, session_id, user_id, agent_id, conn_id, "
                " org_id, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row.get("at") or _now(), row["trace_id"], row["kind"], row.get("name"),
                    row.get("span_id"), row.get("parent_span_id"),
                    None if row.get("ok") is None else int(bool(row["ok"])),
                    row.get("duration_ms"), row.get("error_class"),
                    row.get("investigation_id"), row.get("session_id"),
                    row.get("user_id"), row.get("agent_id"), row.get("conn_id"),
                    row.get("org_id") or "default",
                    json.dumps(payload, default=str) if payload is not None else None,
                ),
            )
            seq = int(cur.lastrowid)
        self._session_events_maybe_prune()
        return seq

    def session_events(
        self,
        *,
        trace_id: Optional[str] = None,
        kind: Optional[str] = None,
        session_id: Optional[str] = None,
        investigation_id: Optional[str] = None,
        org_id: Optional[str] = None,
        since_seq: Optional[int] = None,
        limit: int = 500,
        ascending: bool = False,
    ) -> list[dict]:
        """Read session events. Defaults to newest-first (the feed shape); pass
        ``ascending=True`` for replay order, which is what reconstructing a single
        run wants."""
        q = f"SELECT {', '.join(self._SESSION_EVENT_COLS)} FROM session_events WHERE 1=1"
        args: list[Any] = []
        if trace_id:
            q += " AND trace_id=?"; args.append(trace_id)
        if kind:
            q += " AND kind=?"; args.append(kind)
        if session_id:
            q += " AND session_id=?"; args.append(session_id)
        if investigation_id:
            q += " AND investigation_id=?"; args.append(investigation_id)
        if org_id:
            q += " AND org_id=?"; args.append(org_id)
        if since_seq is not None:
            q += " AND seq>?"; args.append(since_seq)
        q += f" ORDER BY seq {'ASC' if ascending else 'DESC'} LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(zip(self._SESSION_EVENT_COLS, r))
            if d.get("ok") is not None:
                d["ok"] = bool(d["ok"])
            if d.get("payload"):
                try:
                    d["payload"] = json.loads(d["payload"])
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, f"session_events seq={d.get('seq')} has an unparseable "
                                  "payload; serving it as the raw string",
                             counter="obs.session_log.bad_payload")
            out.append(d)
        return out

    def session_events_clear(self, *, trace_id: Optional[str] = None,
                             org_id: Optional[str] = None) -> int:
        """Delete a run's session log (or the whole table when unscoped); returns
        rows deleted. Distinct from :meth:`session_events_prune`, which is
        age/size retention — this is a deliberate purge of a named run, the
        primitive a "forget this session" request needs."""
        q = "DELETE FROM session_events WHERE 1=1"
        args: list[Any] = []
        if trace_id:
            q += " AND trace_id=?"; args.append(trace_id)
        if org_id:
            q += " AND org_id=?"; args.append(org_id)
        with self._lock, self._conn:
            return max(self._conn.execute(q, args).rowcount, 0)

    def _session_events_maybe_prune(self) -> None:
        """Prune every ``_SESSION_EVENT_PRUNE_EVERY`` inserts (amortised, so the
        common insert stays one statement). Best-effort: a prune failure must
        never surface to the answer path that produced the event."""
        with self._lock:
            self._session_event_writes += 1
            due = self._session_event_writes % _SESSION_EVENT_PRUNE_EVERY == 0
        if not due:
            return
        try:
            self.session_events_prune()
        except Exception as exc:
            logger.debug("session_events prune failed: %s", exc)

    def session_events_prune(self, *, keep_days: Optional[int] = None,
                             max_rows: Optional[int] = None) -> int:
        """Delete events older than ``keep_days`` and any beyond ``max_rows``
        (newest kept). Returns rows deleted. Env-tunable via
        ``AUGHOR_SESSION_LOG_KEEP_DAYS`` / ``AUGHOR_SESSION_LOG_MAX_ROWS``; set
        either to 0 to disable that half."""
        if keep_days is None:
            keep_days = int(os.environ.get("AUGHOR_SESSION_LOG_KEEP_DAYS", "14") or 0)
        if max_rows is None:
            max_rows = int(os.environ.get("AUGHOR_SESSION_LOG_MAX_ROWS", "200000") or 0)
        deleted = 0
        with self._lock, self._conn:
            if keep_days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
                deleted += self._conn.execute(
                    "DELETE FROM session_events WHERE at < ?", (cutoff,)).rowcount
            if max_rows > 0:
                deleted += self._conn.execute(
                    "DELETE FROM session_events WHERE seq NOT IN ("
                    "  SELECT seq FROM session_events ORDER BY seq DESC LIMIT ?)",
                    (max_rows,),
                ).rowcount
        return max(deleted, 0)
