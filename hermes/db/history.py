"""SQLite-backed investigation history store.

Investigation lifecycle:
  running   — created, agent loop in progress
  complete  — synthesize_report finished normally; indexed in Qdrant
  timed_out — wall-clock deadline exceeded; NOT indexed
  failed    — unexpected exception; NOT indexed

Only complete investigations are eligible for Qdrant indexing and cache hits.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "history.db"

InvStatus = Literal["running", "complete", "timed_out", "failed", "paused"]


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS investigations (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT DEFAULT 'running',
            hypothesis_count INTEGER DEFAULT 0,
            query_count INTEGER DEFAULT 0,
            headline TEXT,
            report_json TEXT,
            hypotheses_json TEXT,
            query_history_json TEXT,
            kind TEXT DEFAULT 'investigation'
        )
    """)
    # Safe migrations
    for col, default in [
        ("status TEXT DEFAULT 'running'", "status"),
        ("kind TEXT DEFAULT 'investigation'", "kind"),
    ]:
        try:
            c.execute(f"ALTER TABLE investigations ADD COLUMN {col}")
        except Exception:
            pass  # already exists
    # Backfill status for pre-status rows
    c.execute("""
        UPDATE investigations SET status = 'complete'
        WHERE status = 'running' AND completed_at IS NOT NULL
    """)
    c.commit()


def create_investigation(question: str, connection_id: str) -> str:
    """Insert a new in-progress row and return its ID."""
    inv_id = uuid.uuid4().hex[:8]
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO investigations (id, question, connection_id, started_at, status) VALUES (?,?,?,?,?)",
        (inv_id, question, connection_id, _now(), "running"),
    )
    c.commit()
    c.close()
    return inv_id


def complete_investigation(
    inv_id: str,
    report: Any,
    hypotheses: list,
    query_history: list,
    question: str = "",
    connection_id: str = "",
    skip_index: bool = False,
) -> None:
    """Persist the final state and optionally index in Qdrant. Only called on clean completion."""
    report_dict = report.model_dump() if hasattr(report, "model_dump") else report
    hypotheses_list = [h.model_dump() if hasattr(h, "model_dump") else h for h in hypotheses]
    queries_list = [q.model_dump() if hasattr(q, "model_dump") else q for q in query_history]
    headline = report_dict.get("headline", "") if report_dict else ""

    c = _conn()
    _ensure_schema(c)
    c.execute(
        """UPDATE investigations SET
            completed_at = ?,
            status = 'complete',
            headline = ?,
            hypothesis_count = ?,
            query_count = ?,
            report_json = ?,
            hypotheses_json = ?,
            query_history_json = ?
        WHERE id = ?""",
        (
            _now(), headline,
            len(hypotheses_list), len(queries_list),
            json.dumps(report_dict),
            json.dumps(hypotheses_list),
            json.dumps(queries_list),
            inv_id,
        ),
    )
    c.commit()
    c.close()

    # Index in Qdrant — only for investigate-mode completions (not direct queries)
    if report_dict and not skip_index:
        key_findings = [f.get("claim", "") for f in (report_dict.get("key_findings") or [])]
        from hermes.tools.prior_analyses import index_investigation
        index_investigation(inv_id, question=question, headline=headline, key_findings=key_findings, connection_id=connection_id)


def pause_investigation(inv_id: str) -> None:
    """Mark an investigation as paused, awaiting human feedback."""
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "UPDATE investigations SET status = 'paused' WHERE id = ?",
        (inv_id,),
    )
    c.commit()
    c.close()


def fail_investigation(inv_id: str, status: InvStatus = "timed_out") -> None:
    """
    Mark an investigation as timed_out or failed.
    Deliberately does NOT index — partial results must not pollute the cache.
    """
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "UPDATE investigations SET completed_at = ?, status = ? WHERE id = ?",
        (_now(), status, inv_id),
    )
    c.commit()
    c.close()


def save_chat_turn(
    question: str,
    connection_id: str,
    headline: str,
    sql: str,
) -> str:
    """Persist a completed chat (Ask/Investigate-via-chat) turn as a history row."""
    inv_id = uuid.uuid4().hex[:8]
    now = _now()
    c = _conn()
    _ensure_schema(c)
    c.execute(
        """INSERT INTO investigations
           (id, question, connection_id, started_at, completed_at,
            status, hypothesis_count, query_count, headline,
            report_json, kind)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (inv_id, question, connection_id, now, now,
         "complete", 0, 1, headline,
         json.dumps({"headline": headline, "sql": sql}),
         "chat"),
    )
    c.commit()
    c.close()
    return inv_id


def delete_investigation(inv_id: str) -> bool:
    """Delete a history row by ID. Returns True if a row was deleted."""
    c = _conn()
    _ensure_schema(c)
    cursor = c.execute("DELETE FROM investigations WHERE id = ?", (inv_id,))
    deleted = cursor.rowcount > 0
    c.commit()
    c.close()
    return deleted


def list_investigations(limit: int = 50) -> list[dict]:
    """Return summary rows, newest first."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        """SELECT id, question, connection_id, started_at, completed_at,
                  status, hypothesis_count, query_count, headline,
                  COALESCE(kind, 'investigation') as kind
           FROM investigations
           ORDER BY started_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_investigation(inv_id: str) -> Optional[dict]:
    """Return the full investigation record including parsed JSON fields."""
    c = _conn()
    _ensure_schema(c)
    row = c.execute(
        "SELECT * FROM investigations WHERE id = ?", (inv_id,)
    ).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    for field in ("report_json", "hypotheses_json", "query_history_json"):
        raw = d.pop(field, None)
        key = field.replace("_json", "")
        d[key] = json.loads(raw) if raw else None
    return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
