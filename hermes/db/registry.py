"""
ConnectionRegistry — persists named DB connections to SQLite.

Credentials (DSN strings) are encrypted at rest with Fernet symmetric
encryption. The key is derived from a secret stored in .hermes_key next
to the database, or from HERMES_SECRET_KEY env var.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

REGISTRY_DB = Path(__file__).parent.parent.parent / "data" / "connections.db"
KEY_FILE    = Path(__file__).parent.parent.parent / "data" / ".hermes_key"

BUILTIN_ID = "fixture"
POSTGRES_BUILTIN_ID = "mydb"


def _postgres_builtin_dsn() -> str:
    """Read at call time so .env loaded by the API startup is picked up."""
    return os.getenv("HERMES_DEFAULT_POSTGRES_DSN", "")


def _get_fernet() -> Fernet:
    key_env = os.getenv("HERMES_SECRET_KEY")
    if key_env:
        return Fernet(key_env.encode())
    if KEY_FILE.exists():
        return Fernet(KEY_FILE.read_bytes().strip())
    # Generate and persist a new key
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    KEY_FILE.chmod(0o600)
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


def _db() -> sqlite3.Connection:
    REGISTRY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(REGISTRY_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            conn_type  TEXT NOT NULL,
            dsn_enc    TEXT NOT NULL,
            meta       TEXT DEFAULT '{}'
        )
    """)
    conn.commit()
    return conn


# ── Public API ────────────────────────────────────────────────────────────────

def list_connections() -> list[dict]:
    """Return all saved connections (DSN redacted)."""
    rows = []

    # Always include the built-in fixture
    fixture_path = Path(__file__).parent.parent.parent / "data" / "hermes.duckdb"
    rows.append({
        "id": BUILTIN_ID,
        "name": "Fixture DB (demo)",
        "conn_type": "duckdb",
        "dsn_preview": str(fixture_path),
        "meta": {},
        "builtin": True,
    })

    # Include default Postgres if configured
    if _postgres_builtin_dsn():
        rows.append({
            "id": POSTGRES_BUILTIN_ID,
            "name": "mydb (default)",
            "conn_type": "postgres",
            "dsn_preview": "postgresql://***",
            "meta": {},
            "builtin": True,
        })

    with _db() as conn:
        for row in conn.execute("SELECT id, name, conn_type, meta FROM connections ORDER BY rowid"):
            rows.append({
                "id": row["id"],
                "name": row["name"],
                "conn_type": row["conn_type"],
                "dsn_preview": _dsn_preview(row["conn_type"]),
                "meta": json.loads(row["meta"] or "{}"),
                "builtin": False,
            })
    return rows


def add_connection(name: str, conn_type: str, dsn: str, meta: dict | None = None) -> str:
    conn_id = str(uuid.uuid4())[:8]
    with _db() as conn:
        conn.execute(
            "INSERT INTO connections (id, name, conn_type, dsn_enc, meta) VALUES (?, ?, ?, ?, ?)",
            [conn_id, name, conn_type, _encrypt(dsn), json.dumps(meta or {})],
        )
        conn.commit()
    return conn_id


def get_dsn(conn_id: str) -> tuple[str, str]:
    """Return (conn_type, plain_dsn) for the given connection ID."""
    if conn_id == BUILTIN_ID:
        fixture_path = Path(__file__).parent.parent.parent / "data" / "hermes.duckdb"
        return "duckdb", str(fixture_path)
    if conn_id == POSTGRES_BUILTIN_ID:
        if not _postgres_builtin_dsn():
            raise KeyError("Default Postgres connection is not configured (set HERMES_DEFAULT_POSTGRES_DSN)")
        return "postgres", _postgres_builtin_dsn()
    with _db() as conn:
        row = conn.execute(
            "SELECT conn_type, dsn_enc FROM connections WHERE id = ?", [conn_id]
        ).fetchone()
    if not row:
        raise KeyError(f"Connection {conn_id!r} not found")
    return row["conn_type"], _decrypt(row["dsn_enc"])


def delete_connection(conn_id: str) -> None:
    if conn_id in (BUILTIN_ID, POSTGRES_BUILTIN_ID):
        raise ValueError("Cannot delete a built-in connection")
    with _db() as conn:
        conn.execute("DELETE FROM connections WHERE id = ?", [conn_id])
        conn.commit()


def _dsn_preview(conn_type: str) -> str:
    previews = {
        "postgres": "postgresql://***",
        "duckdb":   "*.duckdb",
    }
    return previews.get(conn_type, conn_type)
