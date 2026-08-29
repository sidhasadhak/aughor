"""The external-identity link table (RC-4).

One ``identity_links`` row per ``(org_id, provider, external_id)`` naming the platform
user that external principal IS. Org-scoped, so one tenant's Slack workspace never
resolves into another's roster.

Mirrors ``rbac/store.py`` exactly — an ``AUGHOR_IDENTITY_DB`` override via
``sqlite_util.resolve_db_path`` keeps it hermetic under test, ``connect_store`` +
``ensure_once`` apply the shared pooling/WAL idiom. Base-only (no migrations): the
schema is a single additive table, and it adopts ``run_migrations`` the first time it
grows a column, like the other stores.

No policy lives here. This is a pure record of who-is-who, read by ``resolver.py``;
whether an unlinked identity may DO anything is RBAC's question, not this table's.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from aughor.db.backend import connect_store
from aughor.db.sqlite_util import resolve_db_path
from aughor.db.store_pool import ensure_once
from aughor.org.context import current_org_id
from aughor.util.time import now_iso_z

_DB_PATH = resolve_db_path(
    "AUGHOR_IDENTITY_DB",
    Path(__file__).parent.parent.parent / "data" / "identity_links.db",
)


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS identity_links (
            org_id       TEXT NOT NULL DEFAULT 'default',
            provider     TEXT NOT NULL,
            external_id  TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            display      TEXT NOT NULL DEFAULT '',
            linked_by    TEXT NOT NULL DEFAULT '',
            linked_at    TEXT NOT NULL,
            PRIMARY KEY (org_id, provider, external_id)
        )
    """)
    # The reverse lookup: "which external identities is this person?" — the query the
    # Slack↔web continuity check asks, and the one an unlink flow needs.
    c.execute("CREATE INDEX IF NOT EXISTS ix_identity_user ON identity_links (org_id, user_id)")
    c.commit()


def _conn() -> sqlite3.Connection:
    c = connect_store(_DB_PATH)
    c.row_factory = sqlite3.Row
    ensure_once(c, _ensure_schema)
    return c


def get_link(provider: str, external_id: str) -> Optional[str]:
    """The platform user id this external principal is linked to, or None."""
    c = _conn()
    try:
        r = c.execute(
            "SELECT user_id FROM identity_links WHERE org_id=? AND provider=? AND external_id=?",
            (current_org_id(), provider, external_id)).fetchone()
        return r["user_id"] if r else None
    finally:
        c.close()


def put_link(provider: str, external_id: str, user_id: str, *,
             display: str = "", linked_by: str = "") -> None:
    """Link (or re-link) an external principal to a platform user. Idempotent."""
    c = _conn()
    try:
        c.execute("""
            INSERT INTO identity_links (org_id, provider, external_id, user_id, display,
                                        linked_by, linked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (org_id, provider, external_id) DO UPDATE SET
                user_id=excluded.user_id, display=excluded.display,
                linked_by=excluded.linked_by, linked_at=excluded.linked_at
        """, (current_org_id(), provider, external_id, user_id, display, linked_by, now_iso_z()))
        c.commit()
    finally:
        c.close()


def delete_link(provider: str, external_id: str) -> bool:
    """Unlink. Returns True iff a row was removed."""
    c = _conn()
    try:
        cur = c.execute(
            "DELETE FROM identity_links WHERE org_id=? AND provider=? AND external_id=?",
            (current_org_id(), provider, external_id))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def links_for_user(user_id: str) -> list[dict]:
    """Every external identity linked to one platform user, for this org."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT provider, external_id, display, linked_at FROM identity_links "
            "WHERE org_id=? AND user_id=? ORDER BY provider, external_id",
            (current_org_id(), user_id)).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()
