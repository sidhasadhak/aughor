"""SQLite-backed Workspace store.

Schema: one `workspaces` table with a JSON-serialised connection_ids column.
Migration: `ensure_default_workspace()` runs idempotently on startup and creates
a single "Default" Workspace containing every registered connection, so the app
has a valid top-level scope from the first launch and nothing breaks for users
who never explicitly create a Workspace.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from aughor.workspace.models import Workspace

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "workspaces.db"
DEFAULT_WORKSPACE_ID = "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id                  TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            description         TEXT DEFAULT '',
            connection_ids_json TEXT NOT NULL DEFAULT '[]',
            is_default          INTEGER DEFAULT 0,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)
    c.commit()


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    return Workspace(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        connection_ids=json.loads(row["connection_ids_json"] or "[]"),
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_workspace(
    name: str,
    connection_ids: Optional[List[str]] = None,
    description: str = "",
    is_default: bool = False,
    workspace_id: Optional[str] = None,
) -> Workspace:
    wid = workspace_id or uuid.uuid4().hex[:8]
    now = _now()
    ids_json = json.dumps(connection_ids or [])
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO workspaces (id, name, description, connection_ids_json, is_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (wid, name, description, ids_json, int(is_default), now, now),
    )
    c.commit()
    return Workspace(
        id=wid, name=name, description=description,
        connection_ids=connection_ids or [], is_default=is_default,
        created_at=now, updated_at=now,
    )


def get_workspace(workspace_id: str) -> Optional[Workspace]:
    c = _conn()
    _ensure_schema(c)
    row = c.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return _row_to_workspace(row) if row else None


def list_workspaces() -> List[Workspace]:
    c = _conn()
    _ensure_schema(c)
    # Default workspace sorts first, then most-recently updated.
    rows = c.execute(
        "SELECT * FROM workspaces ORDER BY is_default DESC, updated_at DESC"
    ).fetchall()
    return [_row_to_workspace(r) for r in rows]


def update_workspace(
    workspace_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    connection_ids: Optional[List[str]] = None,
) -> Optional[Workspace]:
    existing = get_workspace(workspace_id)
    if not existing:
        return None
    now = _now()
    new_name = name if name is not None else existing.name
    new_desc = description if description is not None else existing.description
    new_ids = connection_ids if connection_ids is not None else existing.connection_ids
    c = _conn()
    c.execute(
        "UPDATE workspaces SET name=?, description=?, connection_ids_json=?, updated_at=? WHERE id=?",
        (new_name, new_desc, json.dumps(new_ids), now, workspace_id),
    )
    c.commit()
    return get_workspace(workspace_id)


def delete_workspace(workspace_id: str) -> bool:
    """Delete a workspace. The default workspace cannot be deleted."""
    existing = get_workspace(workspace_id)
    if not existing or existing.is_default:
        return False
    c = _conn()
    _ensure_schema(c)
    affected = c.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,)).rowcount
    c.commit()
    return affected > 0


# ── Default-workspace migration ───────────────────────────────────────────────

def ensure_default_workspace() -> bool:
    """Create the catch-all "Default" Workspace if it doesn't exist yet, and keep
    it tracking every registered connection.

    Idempotent — safe to call on every startup. The Default workspace always
    reflects the full set of connections so a newly-added connection is visible
    even before the user organises it into a custom workspace. Returns True when
    it created or updated the default workspace.
    """
    try:
        from aughor.db.registry import list_connections
        all_ids = [c.get("id", "") for c in list_connections() if c.get("id")]
    except Exception:
        all_ids = []

    existing = get_workspace(DEFAULT_WORKSPACE_ID)
    if existing is None:
        create_workspace(
            name="Default",
            connection_ids=all_ids,
            description="All connections",
            is_default=True,
            workspace_id=DEFAULT_WORKSPACE_ID,
        )
        return True

    # Keep the default workspace's membership in sync with the registry: add any
    # connection that isn't tracked by *any* workspace yet (newly registered).
    tracked: set[str] = set()
    for ws in list_workspaces():
        tracked.update(ws.connection_ids)
    untracked = [cid for cid in all_ids if cid not in tracked]
    if untracked:
        merged = list(dict.fromkeys([*existing.connection_ids, *untracked]))
        update_workspace(DEFAULT_WORKSPACE_ID, connection_ids=merged)
        return True
    return False
