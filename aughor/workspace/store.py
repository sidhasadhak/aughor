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
from pathlib import Path
from typing import Any, Dict, List, Optional

from aughor.org.context import DEFAULT_ORG_ID, current_org_id
from aughor.workspace.models import Workspace
from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path("AUGHOR_WORKSPACES_DB", Path(__file__).parent.parent.parent / "data" / "workspaces.db")
DEFAULT_WORKSPACE_ID = "default"

# Schema evolution (DATA-05). The `workspaces` base table is v1; changes are Migration(v>=2).
_MIGRATIONS = [
    Migration(2, "per-workspace org-settings overrides",
              lambda c: add_column_if_missing(c, "workspaces", "settings_override_json", "TEXT DEFAULT '{}'")),
    Migration(3, "tenant key: org_id on workspaces",
              lambda c: add_column_if_missing(c, "workspaces", "org_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_ORG_ID}'")),
]


from aughor.util.time import now_iso as _now


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
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
    run_migrations(c, _MIGRATIONS, store="workspace")
    c.commit()


def _row_to_workspace(row: sqlite3.Row) -> Workspace:
    try:
        override = (
            json.loads(row["settings_override_json"])
            if "settings_override_json" in row.keys() and row["settings_override_json"]
            else {}
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "workspace settings_override_json invalid — treating as empty",
                 counter="workspace.override_parse_failed")
        override = {}
    return Workspace(
        id=row["id"],
        org_id=(row["org_id"] if "org_id" in row.keys() and row["org_id"] else DEFAULT_ORG_ID),
        name=row["name"],
        description=row["description"] or "",
        connection_ids=json.loads(row["connection_ids_json"] or "[]"),
        is_default=bool(row["is_default"]),
        settings_override=override,
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
    settings_override: Optional[Dict[str, Any]] = None,
) -> Workspace:
    wid = workspace_id or uuid.uuid4().hex[:8]
    org_id = current_org_id()
    now = _now()
    ids_json = json.dumps(connection_ids or [])
    override_json = json.dumps(settings_override or {})
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO workspaces (id, org_id, name, description, connection_ids_json, is_default, settings_override_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (wid, org_id, name, description, ids_json, int(is_default), override_json, now, now),
    )
    c.commit()
    return Workspace(
        id=wid, org_id=org_id, name=name, description=description,
        connection_ids=connection_ids or [], is_default=is_default,
        settings_override=settings_override or {},
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
    settings_override: Optional[Dict[str, Any]] = None,
) -> Optional[Workspace]:
    existing = get_workspace(workspace_id)
    if not existing:
        return None
    now = _now()
    new_name = name if name is not None else existing.name
    new_desc = description if description is not None else existing.description
    new_ids = connection_ids if connection_ids is not None else existing.connection_ids
    new_override = settings_override if settings_override is not None else existing.settings_override
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "UPDATE workspaces SET name=?, description=?, connection_ids_json=?, settings_override_json=?, updated_at=? WHERE id=?",
        (new_name, new_desc, json.dumps(new_ids), json.dumps(new_override or {}), now, workspace_id),
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


# ── Workspace scope (data-path tenancy) ───────────────────────────────────────

def workspace_connection_ids(workspace_id: Optional[str]) -> Optional[set]:
    """The set of connection ids visible in a workspace — the data-path tenancy gate.

    Returns:
      • ``None``  when no workspace is given (blank/omitted) → caller stays UNSCOPED,
        preserving the global behaviour for management flows that need all data.
      • the workspace's ``connection_ids`` for a known workspace.
      • an EMPTY set for an *unknown* workspace id → fail-closed (an unrecognised
        workspace must not leak another's data).
    """
    if not workspace_id:
        return None
    ws = get_workspace(workspace_id)
    return set(ws.connection_ids) if ws else set()


def workspace_for_connection(conn_id: Optional[str]) -> Optional[str]:
    """The *specific* (non-default) workspace that owns a connection, for resolving
    per-workspace agent governance. Returns ``None`` when the connection lives only
    in the catch-all Default workspace (or nowhere) — i.e. it falls back to the
    Org-wide (app) scope. Best-effort; never raises into a caller."""
    if not conn_id:
        return None
    try:
        for ws in list_workspaces():
            if not ws.is_default and conn_id in (ws.connection_ids or []):
                return ws.id
    except Exception:
        return None
    return None


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
