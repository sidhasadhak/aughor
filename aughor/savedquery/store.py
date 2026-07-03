"""SQLite-backed saved-query store.

Mirrors aughor/canvas/store.py: one `saved_queries` table, JSON-serialised `spec` column,
idempotent schema creation on every operation. Connection-scoped (list filters by connection).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from aughor.savedquery.models import SavedQuery
from aughor.util.time import now_iso as _now
from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path("AUGHOR_SAVEDQUERY_DB", Path(__file__).parent.parent.parent / "data" / "saved_queries.db")


def _conn() -> sqlite3.Connection:
    c = tune(sqlite3.connect(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS saved_queries (
            id            TEXT PRIMARY KEY,
            connection_id TEXT NOT NULL,
            name          TEXT NOT NULL,
            sql           TEXT DEFAULT '',
            spec_json     TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_saved_queries_conn ON saved_queries(connection_id)")
    c.commit()


def _row_to_query(row: sqlite3.Row) -> SavedQuery:
    spec = {}
    try:
        spec = json.loads(row["spec_json"] or "{}")
    except Exception:
        spec = {}
    return SavedQuery(
        id=row["id"],
        connection_id=row["connection_id"],
        name=row["name"],
        sql=row["sql"] or "",
        spec=spec if isinstance(spec, dict) else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_saved_query(
    connection_id: str,
    name: str,
    sql: str = "",
    spec: Optional[dict] = None,
    query_id: Optional[str] = None,
) -> SavedQuery:
    qid = query_id or uuid.uuid4().hex[:8]
    now = _now()
    spec_json = json.dumps(spec or {})
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO saved_queries (id, connection_id, name, sql, spec_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (qid, connection_id, name, sql, spec_json, now, now),
    )
    c.commit()
    return SavedQuery(
        id=qid, connection_id=connection_id, name=name, sql=sql,
        spec=spec or {}, created_at=now, updated_at=now,
    )


def get_saved_query(query_id: str) -> Optional[SavedQuery]:
    c = _conn()
    _ensure_schema(c)
    row = c.execute("SELECT * FROM saved_queries WHERE id = ?", (query_id,)).fetchone()
    return _row_to_query(row) if row else None


def list_saved_queries(connection_id: Optional[str] = None) -> List[SavedQuery]:
    c = _conn()
    _ensure_schema(c)
    if connection_id:
        rows = c.execute(
            "SELECT * FROM saved_queries WHERE connection_id = ? ORDER BY updated_at DESC",
            (connection_id,),
        ).fetchall()
    else:
        rows = c.execute("SELECT * FROM saved_queries ORDER BY updated_at DESC").fetchall()
    return [_row_to_query(r) for r in rows]


def update_saved_query(
    query_id: str,
    name: Optional[str] = None,
    sql: Optional[str] = None,
    spec: Optional[dict] = None,
) -> Optional[SavedQuery]:
    existing = get_saved_query(query_id)
    if not existing:
        return None
    new_name = name if name is not None else existing.name
    new_sql = sql if sql is not None else existing.sql
    new_spec = spec if spec is not None else existing.spec
    now = _now()
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "UPDATE saved_queries SET name=?, sql=?, spec_json=?, updated_at=? WHERE id=?",
        (new_name, new_sql, json.dumps(new_spec or {}), now, query_id),
    )
    c.commit()
    return get_saved_query(query_id)


def delete_saved_query(query_id: str) -> bool:
    c = _conn()
    _ensure_schema(c)
    affected = c.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,)).rowcount
    c.commit()
    return bool(affected and affected > 0)
