"""SQLite-backed Volume store — volumes + their object metadata catalog, org-scoped.

Persistence only (mirrors the metastore/org store conventions). The bytes are not
here — they live at the tenant-pathed storage location vended by the control plane;
this store holds the queryable metadata catalog (`volume_objects`).
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now
from aughor.volumes.models import Volume, VolumeObject
from aughor.db.sqlite_util import resolve_db_path, tune

_DB_PATH = resolve_db_path("AUGHOR_VOLUMES_DB", Path(__file__).parent.parent.parent / "data" / "volumes.db")


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = tune(sqlite3.connect(str(_DB_PATH)))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS volumes (
            id          TEXT NOT NULL,
            org_id      TEXT NOT NULL DEFAULT 'default',
            catalog_id  TEXT NOT NULL,
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (org_id, id),
            UNIQUE (org_id, catalog_id, name)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS volume_objects (
            id              TEXT NOT NULL,
            org_id          TEXT NOT NULL DEFAULT 'default',
            volume_id       TEXT NOT NULL,
            path            TEXT NOT NULL,
            name            TEXT NOT NULL,
            mime_type       TEXT NOT NULL DEFAULT '',
            size_bytes      INTEGER NOT NULL DEFAULT 0,
            extracted_text  TEXT,
            created_at      TEXT NOT NULL,
            PRIMARY KEY (org_id, id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS volobj_volume ON volume_objects(org_id, volume_id)")
    c.commit()


def _row_to_volume(r: sqlite3.Row) -> Volume:
    return Volume(id=r["id"], org_id=r["org_id"], catalog_id=r["catalog_id"],
                  name=r["name"], created_at=r["created_at"], updated_at=r["updated_at"])


def _row_to_object(r: sqlite3.Row) -> VolumeObject:
    return VolumeObject(
        id=r["id"], org_id=r["org_id"], volume_id=r["volume_id"], path=r["path"],
        name=r["name"], mime_type=r["mime_type"], size_bytes=r["size_bytes"],
        extracted_text=r["extracted_text"], created_at=r["created_at"],
    )


# ── volumes ───────────────────────────────────────────────────────────────────

def create_volume(catalog_id: str, name: str, org_id: Optional[str] = None) -> Volume:
    """Create a volume (idempotent on org_id+catalog_id+name)."""
    oid = org_id or current_org_id()
    existing = get_volume_by_name(catalog_id, name, org_id=oid)
    if existing:
        return existing
    vid = uuid.uuid4().hex[:12]
    now = _now()
    c = _conn()
    c.execute(
        "INSERT INTO volumes (id, org_id, catalog_id, name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (vid, oid, catalog_id, name, now, now),
    )
    c.commit()
    c.close()
    return Volume(id=vid, org_id=oid, catalog_id=catalog_id, name=name,
                  created_at=now, updated_at=now)


def get_volume(volume_id: str, org_id: Optional[str] = None) -> Optional[Volume]:
    oid = org_id or current_org_id()
    c = _conn()
    r = c.execute("SELECT * FROM volumes WHERE org_id=? AND id=?", (oid, volume_id)).fetchone()
    c.close()
    return _row_to_volume(r) if r else None


def get_volume_by_name(catalog_id: str, name: str, org_id: Optional[str] = None) -> Optional[Volume]:
    oid = org_id or current_org_id()
    c = _conn()
    r = c.execute("SELECT * FROM volumes WHERE org_id=? AND catalog_id=? AND name=?",
                  (oid, catalog_id, name)).fetchone()
    c.close()
    return _row_to_volume(r) if r else None


def list_volumes(catalog_id: str, org_id: Optional[str] = None) -> List[Volume]:
    oid = org_id or current_org_id()
    c = _conn()
    rows = c.execute("SELECT * FROM volumes WHERE org_id=? AND catalog_id=? ORDER BY name",
                     (oid, catalog_id)).fetchall()
    c.close()
    return [_row_to_volume(r) for r in rows]


# ── objects (the queryable metadata catalog) ──────────────────────────────────

def add_object(volume_id: str, path: str, name: str, mime_type: str = "",
               size_bytes: int = 0, extracted_text: Optional[str] = None,
               org_id: Optional[str] = None) -> VolumeObject:
    oid = org_id or current_org_id()
    obj_id = uuid.uuid4().hex[:12]
    now = _now()
    c = _conn()
    c.execute(
        "INSERT INTO volume_objects (id, org_id, volume_id, path, name, mime_type, "
        "size_bytes, extracted_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (obj_id, oid, volume_id, path, name, mime_type, size_bytes, extracted_text, now),
    )
    c.commit()
    c.close()
    return VolumeObject(id=obj_id, org_id=oid, volume_id=volume_id, path=path, name=name,
                        mime_type=mime_type, size_bytes=size_bytes,
                        extracted_text=extracted_text, created_at=now)


def get_object(object_id: str, org_id: Optional[str] = None) -> Optional[VolumeObject]:
    oid = org_id or current_org_id()
    c = _conn()
    r = c.execute("SELECT * FROM volume_objects WHERE org_id=? AND id=?", (oid, object_id)).fetchone()
    c.close()
    return _row_to_object(r) if r else None


def list_objects(volume_id: str, org_id: Optional[str] = None) -> List[VolumeObject]:
    oid = org_id or current_org_id()
    c = _conn()
    rows = c.execute("SELECT * FROM volume_objects WHERE org_id=? AND volume_id=? ORDER BY name",
                     (oid, volume_id)).fetchall()
    c.close()
    return [_row_to_object(r) for r in rows]


def delete_object(object_id: str, org_id: Optional[str] = None) -> bool:
    oid = org_id or current_org_id()
    c = _conn()
    n = c.execute("DELETE FROM volume_objects WHERE org_id=? AND id=?", (oid, object_id)).rowcount
    c.commit()
    c.close()
    return n > 0
