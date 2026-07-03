"""SQLite-backed Org store.

Schema: one `orgs` table. `ensure_default_org()` runs idempotently on startup and
creates the single bootstrap "Default" Org, so the app has a valid tenant scope from
the first launch and every persisted `org_id` resolves to a real row. Mirrors the
shape of `workspace/store.py`, including the PRAGMA-guarded additive-migration idiom.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

from aughor.org.context import DEFAULT_ORG_ID
from aughor.org.models import Org
from aughor.util.time import now_iso as _now
from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path("AUGHOR_ORGS_DB", Path(__file__).parent.parent.parent / "data" / "orgs.db")


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS orgs (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            region      TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    c.commit()


def _row_to_org(row: sqlite3.Row) -> Org:
    return Org(
        id=row["id"],
        name=row["name"],
        region=row["region"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_org(
    name: str,
    org_id: Optional[str] = None,
    region: str = "",
) -> Org:
    oid = org_id or DEFAULT_ORG_ID
    now = _now()
    c = _conn()
    _ensure_schema(c)
    c.execute(
        "INSERT INTO orgs (id, name, region, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (oid, name, region, now, now),
    )
    c.commit()
    return Org(id=oid, name=name, region=region, created_at=now, updated_at=now)


def get_org(org_id: str) -> Optional[Org]:
    c = _conn()
    _ensure_schema(c)
    row = c.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
    return _row_to_org(row) if row else None


def list_orgs() -> List[Org]:
    c = _conn()
    _ensure_schema(c)
    rows = c.execute("SELECT * FROM orgs ORDER BY created_at ASC").fetchall()
    return [_row_to_org(r) for r in rows]


# ── Default-org migration ─────────────────────────────────────────────────────

def ensure_default_org() -> bool:
    """Create the bootstrap "Default" Org if it doesn't exist yet.

    Idempotent — safe to call on every startup. Returns True when it created the
    default org. This guarantees the `org_id='default'` that every store stamps
    always points at a real tenant row.
    """
    if get_org(DEFAULT_ORG_ID) is not None:
        return False
    create_org(name="Default", org_id=DEFAULT_ORG_ID)
    return True
