"""SQLite-backed Canvas store.

Schema: one `canvases` table, JSON-serialised scopes column.
Migration: `migrate_connections_to_legacy_canvases()` runs idempotently on startup
and creates a 1:1 legacy Canvas for every registered connection so the existing
connection_id-based API continues to work unchanged.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from aughor.canvas.models import Canvas, CanvasScope

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "canvases.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS canvases (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            scopes_json TEXT NOT NULL DEFAULT '[]',
            is_legacy   INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    c.commit()


def _row_to_canvas(row: sqlite3.Row) -> Canvas:
    scopes_raw = json.loads(row["scopes_json"] or "[]")
    scopes = [CanvasScope(**s) for s in scopes_raw]
    return Canvas(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        scopes=scopes,
        is_legacy=bool(row["is_legacy"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_canvas(
    name: str,
    scopes: List[CanvasScope],
    description: str = "",
    is_legacy: bool = False,
    canvas_id: Optional[str] = None,
) -> Canvas:
    """Create and persist a new Canvas. Returns the created Canvas."""
    if len(scopes) > 1:
        raise ValueError(
            "Multi-scope Canvases are not supported until federation ships (Sprint 28). "
            "Provide exactly one CanvasScope."
        )
    cid = canvas_id or uuid.uuid4().hex[:8]
    now = _now()
    scopes_json = json.dumps([s.model_dump() for s in scopes])
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO canvases (id, name, description, scopes_json, is_legacy, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, name, description, scopes_json, int(is_legacy), now, now),
    )
    c.commit()
    return Canvas(
        id=cid, name=name, description=description,
        scopes=scopes, is_legacy=is_legacy, created_at=now, updated_at=now,
    )


def get_canvas(canvas_id: str) -> Optional[Canvas]:
    c = _conn()
    _ensure_schema(c)
    row = c.execute("SELECT * FROM canvases WHERE id = ?", (canvas_id,)).fetchone()
    return _row_to_canvas(row) if row else None


def list_canvases(include_legacy: bool = True) -> List[Canvas]:
    c = _conn()
    _ensure_schema(c)
    if include_legacy:
        rows = c.execute("SELECT * FROM canvases ORDER BY updated_at DESC").fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM canvases WHERE is_legacy = 0 ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_canvas(r) for r in rows]


def update_canvas(
    canvas_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    scopes: Optional[List[CanvasScope]] = None,
) -> Optional[Canvas]:
    existing = get_canvas(canvas_id)
    if not existing:
        return None
    if scopes is not None and len(scopes) > 1:
        raise ValueError("Multi-scope Canvases not supported until Sprint 28.")
    now = _now()
    new_name = name if name is not None else existing.name
    new_desc = description if description is not None else existing.description
    new_scopes = scopes if scopes is not None else existing.scopes
    scopes_json = json.dumps([s.model_dump() for s in new_scopes])
    c = _conn()
    c.execute(
        "UPDATE canvases SET name=?, description=?, scopes_json=?, updated_at=? WHERE id=?",
        (new_name, new_desc, scopes_json, now, canvas_id),
    )
    c.commit()
    return get_canvas(canvas_id)


def delete_canvas(canvas_id: str) -> bool:
    c = _conn()
    _ensure_schema(c)
    affected = c.execute("DELETE FROM canvases WHERE id = ?", (canvas_id,)).rowcount
    c.commit()
    return affected > 0


# ── Resolution ────────────────────────────────────────────────────────────────

def resolve_connection_id(canvas_id: str) -> Optional[str]:
    """Return the underlying connection_id for a Canvas (first scope)."""
    canvas = get_canvas(canvas_id)
    return canvas.primary_connection_id if canvas else None


# ── Legacy migration ──────────────────────────────────────────────────────────

def delete_legacy_canvases() -> int:
    """Delete all auto-generated (legacy) Canvases. Returns the count removed.

    Auto-generated per-connection Canvases are no longer created. This purges any
    that remain from older installs so only user-created Canvases are shown.
    """
    c = _conn()
    _ensure_schema(c)
    cur = c.execute("DELETE FROM canvases WHERE is_legacy = 1")
    try:
        c.commit()
    except Exception:
        pass
    return cur.rowcount if (cur.rowcount and cur.rowcount > 0) else 0


def migrate_connections_to_legacy_canvases() -> int:
    """Deprecated no-op. Auto-generated per-connection Canvases are no longer
    created — connections and schemas never spawn a Canvas automatically.
    Retained only so existing imports/call sites keep working.
    """
    return 0


# ── Module-level singleton (lazy init) ───────────────────────────────────────

class _CanvasStore:
    """Thin façade used by api.py — delegates to module-level functions."""

    def create(self, **kwargs) -> Canvas:
        return create_canvas(**kwargs)

    def get(self, canvas_id: str) -> Optional[Canvas]:
        return get_canvas(canvas_id)

    def list(self, include_legacy: bool = True) -> List[Canvas]:
        return list_canvases(include_legacy=include_legacy)

    def update(self, canvas_id: str, **kwargs) -> Optional[Canvas]:
        return update_canvas(canvas_id, **kwargs)

    def delete(self, canvas_id: str) -> bool:
        return delete_canvas(canvas_id)


canvas_store = _CanvasStore()
