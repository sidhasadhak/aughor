"""SQLite-backed metastore store — catalogs + grants, org-scoped.

Persistence only (mirrors the `org/` + `workspace/` store conventions: idempotent
`_ensure_schema` with the PRAGMA-guarded ALTER idiom, `_row_to_*` marshallers, CRUD).
Deriving catalogs/grants from the connection registry + workspace membership, and the
grant resolver, live in `sync.py` (which is allowed to import the registry); this
module stays dependency-light.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from aughor.org.context import current_org_id
from aughor.metastore.models import (
    USAGE,
    Catalog,
    Grant,
    catalog_securable,
    workspace_principal,
)
from aughor.util.time import now_iso as _now

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "metastore.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS catalogs (
            id          TEXT NOT NULL,
            org_id      TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL DEFAULT '',
            conn_id     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (org_id, id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS grants (
            id          TEXT PRIMARY KEY,
            org_id      TEXT NOT NULL DEFAULT 'default',
            principal   TEXT NOT NULL,
            securable   TEXT NOT NULL,
            privilege   TEXT NOT NULL DEFAULT 'USAGE',
            created_at  TEXT NOT NULL,
            UNIQUE (org_id, principal, securable, privilege)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS grants_principal ON grants(org_id, principal)")
    c.commit()


def _row_to_catalog(row: sqlite3.Row) -> Catalog:
    return Catalog(
        id=row["id"], org_id=row["org_id"], name=row["name"],
        conn_id=row["conn_id"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_grant(row: sqlite3.Row) -> Grant:
    return Grant(
        id=row["id"], org_id=row["org_id"], principal=row["principal"],
        securable=row["securable"], privilege=row["privilege"], created_at=row["created_at"],
    )


# ── catalogs ──────────────────────────────────────────────────────────────────

def upsert_catalog(catalog_id: str, name: str = "", conn_id: str = "",
                   org_id: Optional[str] = None) -> Catalog:
    """Insert or update a catalog (keyed by org_id + id). Idempotent."""
    oid = org_id or current_org_id()
    now = _now()
    c = _conn()
    c.execute(
        "INSERT INTO catalogs (id, org_id, name, conn_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(org_id, id) DO UPDATE SET name=excluded.name, "
        "conn_id=excluded.conn_id, updated_at=excluded.updated_at",
        (catalog_id, oid, name, conn_id or catalog_id, now, now),
    )
    c.commit()
    c.close()
    return get_catalog(catalog_id, org_id=oid)  # type: ignore[return-value]


def get_catalog(catalog_id: str, org_id: Optional[str] = None) -> Optional[Catalog]:
    oid = org_id or current_org_id()
    c = _conn()
    row = c.execute("SELECT * FROM catalogs WHERE org_id=? AND id=?", (oid, catalog_id)).fetchone()
    c.close()
    return _row_to_catalog(row) if row else None


def list_catalogs(org_id: Optional[str] = None) -> List[Catalog]:
    oid = org_id or current_org_id()
    c = _conn()
    rows = c.execute("SELECT * FROM catalogs WHERE org_id=? ORDER BY name, id", (oid,)).fetchall()
    c.close()
    return [_row_to_catalog(r) for r in rows]


def delete_catalog(catalog_id: str, org_id: Optional[str] = None) -> bool:
    oid = org_id or current_org_id()
    c = _conn()
    n = c.execute("DELETE FROM catalogs WHERE org_id=? AND id=?", (oid, catalog_id)).rowcount
    c.commit()
    c.close()
    return n > 0


# ── grants ────────────────────────────────────────────────────────────────────

def add_grant(principal: str, securable: str, privilege: str = USAGE,
              org_id: Optional[str] = None) -> Grant:
    """Grant a privilege (idempotent on org_id+principal+securable+privilege)."""
    oid = org_id or current_org_id()
    now = _now()
    c = _conn()
    c.execute(
        "INSERT OR IGNORE INTO grants (id, org_id, principal, securable, privilege, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex[:12], oid, principal, securable, privilege, now),
    )
    c.commit()
    row = c.execute(
        "SELECT * FROM grants WHERE org_id=? AND principal=? AND securable=? AND privilege=?",
        (oid, principal, securable, privilege),
    ).fetchone()
    c.close()
    return _row_to_grant(row)


def revoke_grant(principal: str, securable: str, privilege: str = USAGE,
                 org_id: Optional[str] = None) -> bool:
    oid = org_id or current_org_id()
    c = _conn()
    n = c.execute(
        "DELETE FROM grants WHERE org_id=? AND principal=? AND securable=? AND privilege=?",
        (oid, principal, securable, privilege),
    ).rowcount
    c.commit()
    c.close()
    return n > 0


def list_grants(org_id: Optional[str] = None, principal: Optional[str] = None,
                securable: Optional[str] = None) -> List[Grant]:
    oid = org_id or current_org_id()
    clauses = ["org_id=?"]
    params: list = [oid]
    if principal is not None:
        clauses.append("principal=?")
        params.append(principal)
    if securable is not None:
        clauses.append("securable=?")
        params.append(securable)
    c = _conn()
    rows = c.execute(
        f"SELECT * FROM grants WHERE {' AND '.join(clauses)} ORDER BY principal, securable", params
    ).fetchall()
    c.close()
    return [_row_to_grant(r) for r in rows]


def grants_for_workspace(workspace_id: str, org_id: Optional[str] = None) -> List[Grant]:
    """All grants held by a workspace principal."""
    return list_grants(org_id=org_id, principal=workspace_principal(workspace_id))
