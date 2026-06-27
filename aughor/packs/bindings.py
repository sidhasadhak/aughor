"""Persisted entity bindings (P1 — the 'pin' step of the resolver).

After the resolver proposes a role→table/column mapping and the deployer confirms it, the
binding is stored as a first-class, org-scoped, versioned record so a re-deploy is
reproducible and auditable (DOMAIN_EXPERTISE_PACKS.md §5.4). A pack is "bound" on a
connection iff a binding row exists. Mirrors the SQLite idiom of aughor/verify/verdicts.py.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "pack_bindings.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    _ensure_schema(c)
    return c


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS pack_bindings (
            org_id        TEXT NOT NULL,
            pack_id       TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            version       INTEGER NOT NULL DEFAULT 1,
            bindings_json TEXT NOT NULL,
            verified      INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (org_id, pack_id, connection_id)
        )
    """)
    c.commit()


def save_binding(
    pack_id: str,
    connection_id: str,
    bindings: dict,
    version: int = 1,
    verified: bool = False,
) -> dict:
    """Pin (or replace) the resolved binding for (org, pack, connection). `bindings` is a
    role→{table,column,value,confidence,evidence} map. `verified` flags that every recipe
    dry-ran successfully against it (set by the deploy verify step)."""
    org = current_org_id()
    now = _now()
    payload = json.dumps(bindings)
    c = _conn()
    try:
        c.execute(
            "INSERT INTO pack_bindings (org_id, pack_id, connection_id, version, bindings_json, verified, updated_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(org_id, pack_id, connection_id) DO UPDATE SET "
            "version=excluded.version, bindings_json=excluded.bindings_json, "
            "verified=excluded.verified, updated_at=excluded.updated_at",
            (org, pack_id, connection_id, version, payload, 1 if verified else 0, now),
        )
        c.commit()
    finally:
        c.close()
    return {"org_id": org, "pack_id": pack_id, "connection_id": connection_id,
            "version": version, "bindings": bindings, "verified": verified, "updated_at": now}


def load_binding(pack_id: str, connection_id: str) -> Optional[dict]:
    """The pinned binding for (current org, pack, connection), or None if unbound."""
    org = current_org_id()
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM pack_bindings WHERE org_id=? AND pack_id=? AND connection_id=?",
            (org, pack_id, connection_id),
        ).fetchone()
    finally:
        c.close()
    if not row:
        return None
    return {
        "org_id": row["org_id"], "pack_id": row["pack_id"], "connection_id": row["connection_id"],
        "version": row["version"], "bindings": json.loads(row["bindings_json"]),
        "verified": bool(row["verified"]), "updated_at": row["updated_at"],
    }


def is_bound(pack_id: str, connection_id: str, *, require_verified: bool = False) -> bool:
    """Is the pack bound on this connection? `require_verified` additionally insists the
    recipes dry-ran (the gate a pack must pass before it can answer)."""
    b = load_binding(pack_id, connection_id)
    if not b:
        return False
    return bool(b["verified"]) if require_verified else True
