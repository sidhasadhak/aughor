"""
ConnectionRegistry — persists named DB connections to SQLite.

Credentials (DSN strings) are encrypted at rest with Fernet symmetric
encryption. The key is derived from a secret stored in .aughor_key next
to the database, or from AUGHOR_SECRET_KEY env var.
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
KEY_FILE    = Path(__file__).parent.parent.parent / "data" / ".aughor_key"

BUILTIN_ID = "fixture"
POSTGRES_BUILTIN_ID = "mydb"
SAMPLES_ID = "samples"
WORKSPACE_ID = "workspace"  # default DuckDB-backed scratch space for file uploads


def _postgres_builtin_dsn() -> str:
    """Read at call time so .env loaded by the API startup is picked up."""
    return os.getenv("AUGHOR_DEFAULT_POSTGRES_DSN", "")


def _get_fernet() -> Fernet:
    key_env = os.getenv("AUGHOR_SECRET_KEY")
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

def _hidden_builtins() -> set:
    return set(_load_settings().get("hidden_builtins", []))


def list_connections() -> list[dict]:
    """Return all saved connections (DSN redacted)."""
    hidden = _hidden_builtins()
    rows = []

    # Always include the Workspace — a DuckDB-backed catalog that folds in the
    # sample (ecommerce) demo tables read-only AND lets users upload their own
    # files (CSV/Parquet/Excel/JSON) as new tables/schemas. This replaces the
    # former separate "Sample Catalog" built-in.
    if WORKSPACE_ID not in hidden:
        rows.append({
            "id": WORKSPACE_ID,
            "name": "Workspace",
            "conn_type": "local_upload",
            "dsn_preview": "local://workspace/",
            "schema_name": None,
            "meta": {"builtin_workspace": True},
            "builtin": True,
        })

    # Include built-in fixture unless user has removed it
    if BUILTIN_ID not in hidden:
        fixture_path = Path(__file__).parent.parent.parent / "data" / "aughor.duckdb"
        rows.append({
            "id": BUILTIN_ID,
            "name": "Fixture DB (demo)",
            "conn_type": "duckdb",
            "dsn_preview": str(fixture_path),
            "meta": {},
            "builtin": False,
        })

    # Include default Postgres if configured and not removed
    if POSTGRES_BUILTIN_ID not in hidden and _postgres_builtin_dsn():
        rows.append({
            "id": POSTGRES_BUILTIN_ID,
            "name": "mydb (default)",
            "conn_type": "postgres",
            "dsn_preview": "postgresql://***",
            "meta": {},
            "builtin": False,
        })

    with _db() as conn:
        for row in conn.execute("SELECT id, name, conn_type, meta FROM connections ORDER BY rowid"):
            meta = json.loads(row["meta"] or "{}")
            rows.append({
                "id": row["id"],
                "name": row["name"],
                "conn_type": row["conn_type"],
                "dsn_preview": _dsn_preview(row["conn_type"]),
                "schema_name": meta.get("schema_name") or None,
                "meta": meta,
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


def get_meta(conn_id: str) -> dict:
    """Return the metadata dict stored for a connection (e.g. schema_name)."""
    if conn_id == SAMPLES_ID:
        return {"builtin_samples": True, "schema_name": "ecommerce"}
    if conn_id == WORKSPACE_ID:
        samples_path = Path(__file__).parent.parent.parent / "data" / "samples.duckdb"
        meta = {"builtin_workspace": True}
        if samples_path.exists():
            # Fold the sample ecommerce tables into the Workspace (read-only).
            meta["seed_duckdb"] = str(samples_path)
        return meta
    if conn_id in (BUILTIN_ID, POSTGRES_BUILTIN_ID):
        # Builtins store settings in the settings file
        return _load_settings().get(conn_id, {})
    with _db() as conn:
        row = conn.execute(
            "SELECT meta FROM connections WHERE id = ?", [conn_id]
        ).fetchone()
    if not row:
        return {}
    return json.loads(row["meta"] or "{}")


_SETTINGS_PATH = Path(__file__).parent.parent.parent / "data" / "connection_settings.json"


def _load_settings() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            return json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        pass
    return {}


def _save_settings(s: dict) -> None:
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    except Exception:
        pass


def get_connection_settings(conn_id: str) -> dict:
    """Return per-connection settings (refresh schedule, etc.)."""
    return _load_settings().get(conn_id, {})


def update_connection_settings(conn_id: str, updates: dict) -> dict:
    """Merge updates into per-connection settings and persist."""
    settings = _load_settings()
    existing = settings.get(conn_id, {})
    existing.update(updates)
    settings[conn_id] = existing
    _save_settings(settings)
    return existing


def get_dsn(conn_id: str) -> tuple[str, str]:
    """Return (conn_type, plain_dsn) for the given connection ID."""
    if conn_id == SAMPLES_ID:
        samples_path = Path(__file__).parent.parent.parent / "data" / "samples.duckdb"
        return "duckdb", str(samples_path)
    if conn_id == WORKSPACE_ID:
        return "local_upload", "local://"
    if conn_id == BUILTIN_ID:
        fixture_path = Path(__file__).parent.parent.parent / "data" / "aughor.duckdb"
        return "duckdb", str(fixture_path)
    if conn_id == POSTGRES_BUILTIN_ID:
        if not _postgres_builtin_dsn():
            raise KeyError("Default Postgres connection is not configured (set AUGHOR_DEFAULT_POSTGRES_DSN)")
        return "postgres", _postgres_builtin_dsn()
    with _db() as conn:
        row = conn.execute(
            "SELECT conn_type, dsn_enc FROM connections WHERE id = ?", [conn_id]
        ).fetchone()
    if not row:
        raise KeyError(f"Connection {conn_id!r} not found")
    return row["conn_type"], _decrypt(row["dsn_enc"])


def delete_connection(conn_id: str) -> None:
    if conn_id == SAMPLES_ID:
        raise ValueError("The Sample Catalog cannot be deleted.")
    if conn_id == WORKSPACE_ID:
        raise ValueError("The Workspace cannot be deleted.")
    if conn_id in (BUILTIN_ID, POSTGRES_BUILTIN_ID):
        # Hide the builtin so it won't reappear on restart
        settings = _load_settings()
        hidden = set(settings.get("hidden_builtins", []))
        hidden.add(conn_id)
        settings["hidden_builtins"] = list(hidden)
        _save_settings(settings)
    else:
        with _db() as conn:
            conn.execute("DELETE FROM connections WHERE id = ?", [conn_id])
            conn.commit()
    # Evict any cached profiles for this connection
    try:
        from aughor.tools.profile_cache import invalidate
        invalidate(conn_id)
    except Exception:
        pass


def _dsn_preview(conn_type: str) -> str:
    from aughor.connectors.registry import DSN_PREVIEWS
    return DSN_PREVIEWS.get(conn_type, conn_type)
