"""HB-2 — the departures ledger: every gate decision, departed or held, with its reasons.

A held departure is not an error to grep for — it is a governed record a person reviews:
the probation queue reads it, the declarer's verdict lands on it, an owner answers the
question it asks, and `platform_audit`'s family of sinks gains a sibling. Registered
hermetically in the SAME commit as this file (`AUGHOR_DEPARTURES_DB` in `tests/conftest.py`
and `scripts/dump_openapi.py`) — a store is not hermetic until its env name is in the
allowlist.

The remainder of the wave grew the row (the receipt, the guard outcomes, the question, the
repeat fingerprint) additively: a ledger written before it opens with the new columns
added in place, and every row it already held keeps meaning what it meant.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.migrations import add_column_if_missing
from aughor.db.sqlite_util import resolve_db_path
from aughor.util.time import now_iso_z

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "departures.db"


def _db_path() -> Path:
    return resolve_db_path("AUGHOR_DEPARTURES_DB", _DEFAULT_PATH)


_LOCK = threading.RLock()

#: Columns the wave's remainder added, each with its default — created with the table on a
#: fresh ledger, added in place on one written before them.
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source_kind", "TEXT NOT NULL DEFAULT ''"),   # automation | monitor | briefing | alert_rule | finding | analysis
    ("source_id", "TEXT NOT NULL DEFAULT ''"),
    ("origin", "TEXT NOT NULL DEFAULT ''"),        # unattended | person
    ("about", "TEXT NOT NULL DEFAULT ''"),         # the securable the message is about
    ("guards", "TEXT NOT NULL DEFAULT '{}'"),      # guard -> outcome word
    ("receipt", "TEXT NOT NULL DEFAULT '{}'"),     # law 8 — what travelled with the message
    ("fingerprint", "TEXT NOT NULL DEFAULT ''"),   # law 7 — the message without its numbers
    ("numerals", "TEXT NOT NULL DEFAULT '[]'"),    # law 7 — the numbers it stated, in order
    ("as_of", "TEXT NOT NULL DEFAULT ''"),
    ("question", "TEXT NOT NULL DEFAULT '{}'"),    # law 6 — what the owner is asked
    ("answer", "TEXT NOT NULL DEFAULT ''"),
    ("answered_by", "TEXT NOT NULL DEFAULT ''"),
    ("answered_at", "TEXT NOT NULL DEFAULT ''"),
)

_DDL = """
CREATE TABLE IF NOT EXISTS departures (
    id               TEXT PRIMARY KEY,
    ts               TEXT NOT NULL DEFAULT '',
    org_id           TEXT NOT NULL DEFAULT '',
    kind             TEXT NOT NULL DEFAULT '',
    state            TEXT NOT NULL DEFAULT '',   -- departed | held | held_probation | held_owner
    conn_id          TEXT NOT NULL DEFAULT '',
    automation_id    TEXT NOT NULL DEFAULT '',
    automation_name  TEXT NOT NULL DEFAULT '',
    actor            TEXT NOT NULL DEFAULT '',
    target           TEXT NOT NULL DEFAULT '',
    addressed_to     TEXT NOT NULL DEFAULT '',   -- the declarer (probation) or the owner (a question)
    reasons          TEXT NOT NULL DEFAULT '[]',
    checks           TEXT NOT NULL DEFAULT '{}',
    text_preview     TEXT NOT NULL DEFAULT '',
    investigation_id TEXT NOT NULL DEFAULT '',
    verdict          TEXT NOT NULL DEFAULT '',   -- '' | accept | correct | reject
    verdict_note     TEXT NOT NULL DEFAULT '',
    verdict_at       TEXT NOT NULL DEFAULT '',
""" + ",\n".join(f"    {name} {coldef}" for name, coldef in _ADDED_COLUMNS) + """
);
CREATE INDEX IF NOT EXISTS idx_dep_state ON departures (state);
CREATE INDEX IF NOT EXISTS idx_dep_auto  ON departures (automation_id);
CREATE INDEX IF NOT EXISTS idx_dep_ts    ON departures (ts DESC);
"""

#: Indexes over added columns — created only after the columns exist.
_DDL_AFTER_COLUMNS = """
CREATE INDEX IF NOT EXISTS idx_dep_repeat    ON departures (target, fingerprint);
CREATE INDEX IF NOT EXISTS idx_dep_addressed ON departures (addressed_to);
"""

#: Ledger files already brought up to the current columns in this process.
_READY: set[str] = set()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    key = str(path)
    # A file that is not there yet (or was removed since) always gets its schema, whatever
    # this process remembers about the path.
    if not Path(path).exists():
        _READY.discard(key)
    conn = connect_store(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if key not in _READY:
        conn.executescript(_DDL)
        for name, coldef in _ADDED_COLUMNS:
            add_column_if_missing(conn, "departures", name, coldef)
        conn.executescript(_DDL_AFTER_COLUMNS)
        conn.commit()
        _READY.add(key)
    return conn


def record_departure(**fields) -> str:
    """Insert one gate decision; returns its id."""
    row = {"ts": now_iso_z(), "verdict": "", "verdict_note": "", "verdict_at": "", **fields}
    cols = ", ".join(row)
    binds = ", ".join(f":{c}" for c in row)
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(f"INSERT INTO departures ({cols}) VALUES ({binds})", row)
            conn.commit()
        finally:
            conn.close()
    return str(row["id"])


def list_departures(state: Optional[str] = None, automation_id: Optional[str] = None,
                    limit: int = 50, *, states: Optional[list[str]] = None,
                    addressed_to: Optional[str] = None, kind: Optional[str] = None,
                    awaiting: bool = False) -> list[dict]:
    """The ledger, newest first. ``awaiting`` narrows to rows a person still owes something:
    an unmarked probation departure or an unanswered owner question."""
    clauses, params = [], []
    wanted = [s for s in ([state] if state else []) + list(states or []) if s]
    if wanted:
        clauses.append(f"state IN ({', '.join('?' for _ in wanted)})")
        params.extend(wanted)
    if automation_id:
        clauses.append("automation_id = ?"); params.append(automation_id)
    if addressed_to:
        clauses.append("addressed_to = ?"); params.append(addressed_to)
    if kind:
        clauses.append("kind = ?"); params.append(kind)
    if awaiting:
        clauses.append("((state = 'held_probation' AND verdict = '') "
                       "OR (question != '{}' AND answer = ''))")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM departures {where} ORDER BY ts DESC LIMIT ?",
                [*params, max(1, min(int(limit), 500))]).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_departure(departure_id: str) -> Optional[dict]:
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM departures WHERE id = ?",
                               (departure_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def summary_counts(since: str = "") -> dict:
    """How many departures took each state (optionally since an ISO time), and how many a
    person still owes — the number the departures screen's badge shows."""
    with _LOCK:
        conn = _connect()
        try:
            where, params = ("WHERE ts >= ?", [since]) if since else ("", [])
            by_state = {r["state"]: r["n"] for r in conn.execute(
                f"SELECT state, COUNT(*) AS n FROM departures {where} GROUP BY state",
                params).fetchall()}
            awaiting = conn.execute(
                "SELECT COUNT(*) AS n FROM departures WHERE "
                "(state = 'held_probation' AND verdict = '') "
                "OR (question != '{}' AND answer = '')").fetchone()["n"]
        finally:
            conn.close()
    return {"by_state": by_state, "total": sum(by_state.values()), "awaiting": awaiting}


def last_departed(*, source: str, target: str, fingerprint: str, since: str) -> Optional[dict]:
    """Law 7's lookup: the latest row that actually DEPARTED from this source to this
    target saying the same thing (same fingerprint) since ``since``. A held row never
    counts — a message nobody received cannot have been heard before."""
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM departures WHERE state = 'departed' AND target = ? "
                "AND fingerprint = ? AND ts >= ? AND (automation_id = ? OR source_id = ?) "
                "ORDER BY ts DESC LIMIT 1",
                (target, fingerprint, since, source, source)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def mark_departure(departure_id: str, verdict: str, note: str = "") -> Optional[dict]:
    """The declarer's mark on one departure — accept / correct / reject. Returns the
    updated row, or None when the id is unknown. Re-marking overwrites (the latest
    reading of a departure is the one that counts, same as the feedback plane)."""
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE departures SET verdict = ?, verdict_note = ?, verdict_at = ? "
                "WHERE id = ?", (verdict, note, now_iso_z(), departure_id))
            conn.commit()
            if cur.rowcount == 0:
                return None
        finally:
            conn.close()
    return get_departure(departure_id)


def record_answer(departure_id: str, answer: str, answered_by: str = "") -> Optional[dict]:
    """The owner's answer to the question a held departure asked (law 6)."""
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE departures SET answer = ?, answered_by = ?, answered_at = ? "
                "WHERE id = ?", (answer, answered_by, now_iso_z(), departure_id))
            conn.commit()
            if cur.rowcount == 0:
                return None
        finally:
            conn.close()
    return get_departure(departure_id)


def precision_for(automation_id: str) -> dict:
    """Measured departure precision for one automation: marked verdicts over its rows.
    `correct` counts toward precision (a finding worth correcting reached a person
    worth reaching); `reject` is the wasted push.

    HB-3's falsifier rides the denominator: a probation push left unmarked past
    ``PROBATION_WINDOW_DAYS`` is an **unlanded** push and counts against precision —
    an automation whose queue nobody reads cannot graduate by silence. A fresh
    unmarked push (still inside the window) counts nothing yet."""
    from datetime import datetime, timedelta, timezone

    from aughor.govern.departure import PROBATION_WINDOW_DAYS
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PROBATION_WINDOW_DAYS)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT verdict, COUNT(*) AS n FROM departures "
                "WHERE automation_id = ? AND verdict != '' GROUP BY verdict",
                (automation_id,)).fetchall()
            unlanded = conn.execute(
                "SELECT COUNT(*) AS n FROM departures WHERE automation_id = ? "
                "AND state = 'held_probation' AND verdict = '' AND ts < ?",
                (automation_id, cutoff)).fetchone()["n"]
        finally:
            conn.close()
    counts = {r["verdict"]: r["n"] for r in rows}
    marked = sum(counts.values())
    useful = counts.get("accept", 0) + counts.get("correct", 0)
    denominator = marked + unlanded
    return {"automation_id": automation_id, "marked": marked, "counts": counts,
            "unlanded": unlanded,
            "precision": (useful / denominator) if denominator else None}
