"""HB-2 — the departures ledger: every gate decision, departed or held, with its reasons.

A held departure is not an error to grep for — it is a governed record a person reviews:
the probation queue reads it, the declarer's verdict lands on it, and `platform_audit`'s
family of sinks gains a sibling. Registered hermetically in the SAME commit as this file
(`AUGHOR_DEPARTURES_DB` in `tests/conftest.py` and `scripts/dump_openapi.py`) — a store
is not hermetic until its env name is in the allowlist.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.util.time import now_iso_z

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "departures.db"


def _db_path() -> Path:
    return resolve_db_path("AUGHOR_DEPARTURES_DB", _DEFAULT_PATH)


_LOCK = threading.RLock()

_DDL = """
CREATE TABLE IF NOT EXISTS departures (
    id               TEXT PRIMARY KEY,
    ts               TEXT NOT NULL DEFAULT '',
    org_id           TEXT NOT NULL DEFAULT '',
    kind             TEXT NOT NULL DEFAULT '',
    state            TEXT NOT NULL DEFAULT '',   -- departed | held | held_probation
    conn_id          TEXT NOT NULL DEFAULT '',
    automation_id    TEXT NOT NULL DEFAULT '',
    automation_name  TEXT NOT NULL DEFAULT '',
    actor            TEXT NOT NULL DEFAULT '',
    target           TEXT NOT NULL DEFAULT '',
    addressed_to     TEXT NOT NULL DEFAULT '',   -- the declarer, for probation rows
    reasons          TEXT NOT NULL DEFAULT '[]',
    checks           TEXT NOT NULL DEFAULT '{}',
    text_preview     TEXT NOT NULL DEFAULT '',
    investigation_id TEXT NOT NULL DEFAULT '',
    verdict          TEXT NOT NULL DEFAULT '',   -- '' | accept | correct | reject
    verdict_note     TEXT NOT NULL DEFAULT '',
    verdict_at       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dep_state ON departures (state);
CREATE INDEX IF NOT EXISTS idx_dep_auto  ON departures (automation_id);
CREATE INDEX IF NOT EXISTS idx_dep_ts    ON departures (ts DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = connect_store(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
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
                    limit: int = 50) -> list[dict]:
    clauses, params = [], []
    if state:
        clauses.append("state = ?"); params.append(state)
    if automation_id:
        clauses.append("automation_id = ?"); params.append(automation_id)
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
