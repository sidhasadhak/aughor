"""Decision records — every closed-set choice the platform makes, in a trainable shape.

The platform is full of small decisions whose output is a pick from a list that existed
before the call: which route a question takes, which tool a converse step runs, which
declared definition an ambiguous term means. Today each of those is decided (mostly by an
LLM) and the *choice itself* evaporates — the session log keeps what ran, not what the
menu was. This store keeps the menu: one row per decision, holding the context the
decider saw, the options it chose among, which one it picked, and — once known — whether
the pick worked. That is exactly the `{context, options, label}` shape a selection model
trains on, so the exporter beside it (`exporters.export_decisions`) can turn accumulated
traffic into a corpus without a labeling pass.

Recording is OBSERVATION, never control: `record_decision` sits on request paths (the
tool loop, the route classifier), so it must never raise and never slow a turn — a failed
write is a tolerated counter, not a failed answer. Registered hermetically in the SAME
commit as this file (`AUGHOR_DECISIONS_DB` in `tests/conftest.py` and
`scripts/dump_openapi.py`) — a store is not hermetic until its env name is in both lists.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "decisions.db"

#: Caps on what one row may carry. A decision's context is a routing glimpse, not a
#: transcript — an uncapped context field would quietly become a second session log and
#: drag tool results (with their data rows) into a store the exporter ships out.
_MAX_CONTEXT = 2000
_MAX_OPTION = 400
_MAX_OPTIONS = 64


def _db_path() -> Path:
    return resolve_db_path("AUGHOR_DECISIONS_DB", _DEFAULT_PATH)


_LOCK = threading.RLock()

_DDL = """
CREATE TABLE IF NOT EXISTS decision_record (
    id         TEXT PRIMARY KEY,
    ts         TEXT NOT NULL DEFAULT '',
    org_id     TEXT NOT NULL DEFAULT 'default',
    site       TEXT NOT NULL DEFAULT '',    -- ask.route | converse.tool | framing.definition | ...
    conn_id    TEXT NOT NULL DEFAULT '',
    trace_id   TEXT NOT NULL DEFAULT '',
    context    TEXT NOT NULL DEFAULT '',
    options    TEXT NOT NULL DEFAULT '[]',  -- JSON list, the menu as the decider saw it
    label      INTEGER NOT NULL DEFAULT -1, -- index into options; -1 = chose none of them
    chosen     TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'llm', -- llm | rule | reflex
    confidence REAL NOT NULL DEFAULT 0.0,   -- the decider's own, 0.0 when it offers none
    outcome    TEXT NOT NULL DEFAULT ''     -- '' unknown | ok | error | accepted | rejected
);
CREATE INDEX IF NOT EXISTS idx_decision_site ON decision_record (site, ts DESC);
CREATE INDEX IF NOT EXISTS idx_decision_ts   ON decision_record (ts DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = connect_store(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    return conn


def _now() -> str:
    from aughor.util.time import now_iso_z
    return now_iso_z()


def record_decision(site: str, context: str, options: list, *,
                    chosen: str = "", label: Optional[int] = None,
                    source: str = "llm", confidence: float = 0.0,
                    outcome: str = "", conn_id: str = "", trace_id: str = "",
                    org_id: Optional[str] = None) -> str:
    """Record one closed-set choice; returns its id, or '' when the write failed.

    `label` is derived from `chosen` when not given (exact match against `options`);
    a `chosen` that matches nothing records as -1 — "picked none of the listed" is a
    real outcome, and the exporter decides what to do with it, not this function.
    Never raises: this sits on the answer path, and a decision that could not be
    recorded must cost nothing but a counter.
    """
    try:
        opts = [str(o)[:_MAX_OPTION] for o in list(options)[:_MAX_OPTIONS]]
        if label is None:
            capped = str(chosen)[:_MAX_OPTION]
            label = opts.index(capped) if capped in opts else -1
        if not (0 <= int(label) < len(opts)):
            label = -1
        from aughor.org.context import current_org_id
        row = {
            "id": uuid.uuid4().hex, "ts": _now(),
            "org_id": org_id or current_org_id() or "default",
            "site": str(site), "conn_id": str(conn_id), "trace_id": str(trace_id),
            "context": str(context)[:_MAX_CONTEXT],
            "options": json.dumps(opts, ensure_ascii=False),
            "label": int(label), "chosen": str(chosen)[:_MAX_OPTION],
            "source": str(source), "confidence": float(confidence),
            "outcome": str(outcome),
        }
        cols = ", ".join(row)
        binds = ", ".join(f":{c}" for c in row)
        with _LOCK:
            conn = _connect()
            try:
                conn.execute(f"INSERT INTO decision_record ({cols}) VALUES ({binds})", row)
                conn.commit()
            finally:
                conn.close()
        return row["id"]
    except Exception as exc:  # noqa: BLE001 — observation must never fail the observed
        from aughor.kernel.errors import tolerate
        tolerate(exc, "a decision that could not be recorded still happened; the turn goes on",
                 counter="learning.decision_record")
        return ""


def mark_outcome(decision_id: str, outcome: str) -> bool:
    """Close the loop on one decision once its result is known. Best-effort, never raises."""
    try:
        with _LOCK:
            conn = _connect()
            try:
                cur = conn.execute("UPDATE decision_record SET outcome = ? WHERE id = ?",
                                   (str(outcome), decision_id))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an outcome that could not be marked leaves the decision unlabeled, not lost",
                 counter="learning.decision_outcome")
        return False


def list_decisions(site: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Recent rows, newest first, options decoded — the observability read."""
    clauses, params = [], []
    if site:
        clauses.append("site = ?"); params.append(site)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM decision_record {where} ORDER BY ts DESC, rowid DESC LIMIT ?",
                [*params, max(1, min(int(limit), 500))]).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d.get("options") or "[]")
        out.append(d)
    return out


def list_for_export(site: str, limit: int = 100000) -> list[dict]:
    """Every trainable row for one site, oldest first: a listed option was chosen and
    the menu had a real choice in it (two options minimum — jevlike's own floor)."""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM decision_record WHERE site = ? AND label >= 0 "
                "ORDER BY ts ASC, rowid ASC LIMIT ?", (site, int(limit))).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d.get("options") or "[]")
        if len(d["options"]) >= 2 and 0 <= d["label"] < len(d["options"]):
            out.append(d)
    return out


def site_stats() -> dict:
    """Per-site accumulation — total rows, trainable rows (a listed option was chosen),
    and rows whose outcome landed. The volume half of "is this decision learnable"."""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT site, COUNT(*) AS total, "
                "SUM(CASE WHEN label >= 0 THEN 1 ELSE 0 END) AS labeled, "
                "SUM(CASE WHEN outcome != '' THEN 1 ELSE 0 END) AS with_outcome "
                "FROM decision_record GROUP BY site ORDER BY site").fetchall()
        finally:
            conn.close()
    return {r["site"]: {"total": int(r["total"]), "labeled": int(r["labeled"] or 0),
                        "with_outcome": int(r["with_outcome"] or 0)} for r in rows}


def sites() -> list[str]:
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT DISTINCT site FROM decision_record ORDER BY site").fetchall()
        finally:
            conn.close()
    return [r["site"] for r in rows]
