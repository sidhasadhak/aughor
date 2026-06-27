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
    # schema_name is part of the key: a connection can expose several schemas (missimi,
    # swiss_air, …) and each needs its own binding — otherwise pinning one overwrites another.
    c.execute("""
        CREATE TABLE IF NOT EXISTS pack_bindings (
            org_id        TEXT NOT NULL,
            pack_id       TEXT NOT NULL,
            connection_id TEXT NOT NULL,
            schema_name   TEXT NOT NULL DEFAULT '',
            version       INTEGER NOT NULL DEFAULT 1,
            bindings_json TEXT NOT NULL,
            verified      INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (org_id, pack_id, connection_id, schema_name)
        )
    """)
    # Additive migration for a pre-existing 3-key table (best-effort).
    cols = {r[1] for r in c.execute("PRAGMA table_info(pack_bindings)").fetchall()}
    if "schema_name" not in cols:
        c.execute("ALTER TABLE pack_bindings ADD COLUMN schema_name TEXT NOT NULL DEFAULT ''")
    c.commit()


def save_binding(
    pack_id: str,
    connection_id: str,
    bindings: dict,
    version: int = 1,
    verified: bool = False,
    schema: str = "",
) -> dict:
    """Pin (or replace) the resolved binding for (org, pack, connection, schema). `bindings` is
    a role→{table,column,value,confidence,evidence} map. `verified` flags that every recipe
    dry-ran successfully. `schema` distinguishes datasets on a multi-schema connection."""
    org = current_org_id()
    now = _now()
    payload = json.dumps(bindings)
    c = _conn()
    try:
        c.execute(
            "INSERT INTO pack_bindings (org_id, pack_id, connection_id, schema_name, version, "
            "bindings_json, verified, updated_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(org_id, pack_id, connection_id, schema_name) DO UPDATE SET "
            "version=excluded.version, bindings_json=excluded.bindings_json, "
            "verified=excluded.verified, updated_at=excluded.updated_at",
            (org, pack_id, connection_id, schema or "", version, payload, 1 if verified else 0, now),
        )
        c.commit()
    finally:
        c.close()
    return {"org_id": org, "pack_id": pack_id, "connection_id": connection_id, "schema": schema or "",
            "version": version, "bindings": bindings, "verified": verified, "updated_at": now}


def load_binding(pack_id: str, connection_id: str, schema: str = "") -> Optional[dict]:
    """The pinned binding for (current org, pack, connection, schema), or None if unbound."""
    org = current_org_id()
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM pack_bindings WHERE org_id=? AND pack_id=? AND connection_id=? AND schema_name=?",
            (org, pack_id, connection_id, schema or ""),
        ).fetchone()
    finally:
        c.close()
    if not row:
        return None
    return {
        "org_id": row["org_id"], "pack_id": row["pack_id"], "connection_id": row["connection_id"],
        "schema": row["schema_name"], "version": row["version"], "bindings": json.loads(row["bindings_json"]),
        "verified": bool(row["verified"]), "updated_at": row["updated_at"],
    }


def is_bound(pack_id: str, connection_id: str, schema: str = "", *, require_verified: bool = False) -> bool:
    """Is the pack bound on this connection+schema? `require_verified` additionally insists the
    recipes dry-ran (the gate a pack must pass before it can answer)."""
    b = load_binding(pack_id, connection_id, schema)
    if not b:
        return False
    return bool(b["verified"]) if require_verified else True
