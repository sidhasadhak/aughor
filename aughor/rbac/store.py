"""Org-scoped role-assignment store (RBAC P1).

One ``role_assignments`` table keyed on ``(org_id, user_id, role)`` — a user may
hold multiple roles, and assignments are tenant-scoped so org A never sees org B's
grants (DATA-06). Mirrors ``org/store.py``: an ``AUGHOR_RBAC_DB`` override
(``sqlite_util.resolve_db_path``) keeps it hermetic under test, and ``tune`` applies
WAL + busy_timeout at every connect (REC-03).

Base-only store for now (no migrations) — the schema is a single additive table.
When it grows a column it adopts the ``run_migrations`` framework, like the other
migrating stores. No enforcement lives here; the store is a pure record of who holds
what, read by ``resolver.py``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.rbac.models import RoleAssignment
from aughor.util.time import now_iso as _now

_DB_PATH = resolve_db_path(
    "AUGHOR_RBAC_DB", Path(__file__).parent.parent.parent / "data" / "rbac.db"
)


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS role_assignments (
            org_id      TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            role        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (org_id, user_id, role)
        )
        """
    )
    # Reverse-lookup index for the roster admin view (list every assignment in an org).
    c.execute("CREATE INDEX IF NOT EXISTS idx_role_assignments_org ON role_assignments(org_id)")
    c.commit()


def _row_to_assignment(row: sqlite3.Row) -> RoleAssignment:
    return RoleAssignment(
        org_id=row["org_id"],
        user_id=row["user_id"],
        role=row["role"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Mutations ────────────────────────────────────────────────────────────────

def assign_role(org_id: str, user_id: str, role: str) -> RoleAssignment:
    """Grant ``role`` to ``user_id`` in ``org_id``. Idempotent — re-granting an
    existing assignment just refreshes ``updated_at`` (never a duplicate row)."""
    role = (role or "").strip().lower()
    now = _now()
    c = _conn()
    _ensure_schema(c)
    c.execute(
        """
        INSERT INTO role_assignments (org_id, user_id, role, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(org_id, user_id, role)
            DO UPDATE SET updated_at = excluded.updated_at
        """,
        (org_id, user_id, role, now, now),
    )
    c.commit()
    row = c.execute(
        "SELECT * FROM role_assignments WHERE org_id = ? AND user_id = ? AND role = ?",
        (org_id, user_id, role),
    ).fetchone()
    return _row_to_assignment(row)


def revoke_role(org_id: str, user_id: str, role: str) -> bool:
    """Remove a role grant. Returns True when a row was actually removed."""
    role = (role or "").strip().lower()
    c = _conn()
    _ensure_schema(c)
    cur = c.execute(
        "DELETE FROM role_assignments WHERE org_id = ? AND user_id = ? AND role = ?",
        (org_id, user_id, role),
    )
    c.commit()
    return cur.rowcount > 0


# ── Reads ────────────────────────────────────────────────────────────────────

def roles_for_user(org_id: str, user_id: str) -> List[str]:
    """The role names held by ``user_id`` in ``org_id`` (deterministic order)."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT role FROM role_assignments WHERE org_id = ? AND user_id = ? ORDER BY role ASC",
        (org_id, user_id),
    ).fetchall()
    return [r["role"] for r in rows]


def list_assignments(org_id: str) -> List[RoleAssignment]:
    """Every assignment in an org — the roster admin view (P3)."""
    c = _conn()
    _ensure_schema(c)
    rows = c.execute(
        "SELECT * FROM role_assignments WHERE org_id = ? ORDER BY user_id ASC, role ASC",
        (org_id,),
    ).fetchall()
    return [_row_to_assignment(r) for r in rows]


def count_assignments(org_id: str) -> int:
    """How many role grants exist in an org — 0 means "un-bootstrapped" (P3 uses
    this to make the org's first identified user its owner)."""
    c = _conn()
    _ensure_schema(c)
    return c.execute(
        "SELECT COUNT(*) FROM role_assignments WHERE org_id = ?", (org_id,)
    ).fetchone()[0]
