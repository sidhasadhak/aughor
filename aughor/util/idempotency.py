"""Idempotency-Key support for create endpoints (API-03).

A client retry — a dropped response, a double-click, a proxy replay — must not
create a duplicate connection / canvas / action-trigger. When the caller sends an
``Idempotency-Key`` header, we remember ``key -> created resource id`` (scoped to
the endpoint *and* the org) and replay the same id on repeat instead of creating
a second row.

Best-effort and self-pruning: entries older than ``TTL_SECONDS`` are swept on
each write so the table can't grow unbounded (the failure-mode note on REC-10).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from aughor.db.sqlite_util import resolve_db_path, tune
from aughor.org.context import current_org_id

_DB_PATH = resolve_db_path(
    "AUGHOR_IDEMPOTENCY_DB", Path(__file__).parent.parent.parent / "data" / "idempotency.db"
)
TTL_SECONDS = 24 * 3600


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.execute(
        """CREATE TABLE IF NOT EXISTS idempotency (
            scope       TEXT NOT NULL,
            key         TEXT NOT NULL,
            org_id      TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            created_at  REAL NOT NULL,
            PRIMARY KEY (scope, key, org_id)
        )"""
    )
    return c


def lookup(scope: str, key: Optional[str]) -> Optional[str]:
    """The resource id previously created for ``(scope, key, current org)``, or
    None if there is no live (un-expired) entry."""
    if not key:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT resource_id, created_at FROM idempotency WHERE scope=? AND key=? AND org_id=?",
            (scope, key, current_org_id()),
        ).fetchone()
    if not row:
        return None
    resource_id, created_at = row
    if time.time() - created_at > TTL_SECONDS:
        return None
    return resource_id


def remember(scope: str, key: Optional[str], resource_id: str) -> None:
    """Record that ``(scope, key, current org)`` produced ``resource_id``. No-op when
    the caller sent no key. Prunes expired rows so the store stays bounded."""
    if not key:
        return
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO idempotency (scope, key, org_id, resource_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (scope, key, current_org_id(), resource_id, now),
        )
        c.execute("DELETE FROM idempotency WHERE created_at < ?", (now - TTL_SECONDS,))
        c.commit()
