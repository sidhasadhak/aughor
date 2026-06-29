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

from cryptography.fernet import Fernet

from aughor.org.context import DEFAULT_ORG_ID, current_org_id

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
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS connections (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            conn_type  TEXT NOT NULL,
            dsn_enc    TEXT NOT NULL,
            meta       TEXT DEFAULT '{{}}',
            org_id     TEXT NOT NULL DEFAULT '{DEFAULT_ORG_ID}'
        )
    """)
    # Migration (2026-06-22): tenant key on existing single-org registries.
    # Idempotent — add only if an older DB predates the column.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(connections)").fetchall()}
    if "org_id" not in cols:
        conn.execute(f"ALTER TABLE connections ADD COLUMN org_id TEXT NOT NULL DEFAULT '{DEFAULT_ORG_ID}'")
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


def _encrypt_meta(conn_type: str, meta: dict | None) -> dict:
    """Encrypt secret connector fields that live in meta (API tokens, SA-JSON path,
    …) — the DSN is encrypted separately. Non-secret keys pass through untouched."""
    from aughor.connectors.registry import secret_field_keys
    from aughor.secretvault import encrypt_secret
    keys = secret_field_keys(conn_type)
    return {k: (encrypt_secret(v) if k in keys and isinstance(v, str) else v)
            for k, v in (meta or {}).items()}


def _decrypt_meta(meta: dict | None) -> dict:
    """Decrypt any encrypted values in meta. Legacy plaintext (and non-secret) values
    round-trip unchanged, so this is safe on every read with no migration."""
    from aughor.secretvault import decrypt_secret, is_encrypted
    return {k: (decrypt_secret(v) if is_encrypted(v) else v) for k, v in (meta or {}).items()}


def add_connection(name: str, conn_type: str, dsn: str, meta: dict | None = None) -> str:
    conn_id = str(uuid.uuid4())[:8]
    with _db() as conn:
        conn.execute(
            "INSERT INTO connections (id, name, conn_type, dsn_enc, meta, org_id) VALUES (?, ?, ?, ?, ?, ?)",
            [conn_id, name, conn_type, _encrypt(dsn), json.dumps(_encrypt_meta(conn_type, meta)), current_org_id()],
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
    return _decrypt_meta(json.loads(row["meta"] or "{}"))


_SETTINGS_PATH = Path(__file__).parent.parent.parent / "data" / "connection_settings.json"


def _load_settings() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            return json.loads(_SETTINGS_PATH.read_text())
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection-settings read is best-effort; empty defaults used",
                 counter="registry.settings.read")
    return {}


def _save_settings(s: dict) -> None:
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "connection-settings write is non-fatal; retried on next update",
                 counter="registry.settings.write")


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
    # Settings can change schema/DSN behaviour — drop pooled connections.
    try:
        from aughor.db.pool import evict_conn
        evict_conn(conn_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "pool eviction after settings change is best-effort; stale conn self-heals",
                 counter="registry.pool.evict")
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


def delete_connection(conn_id: str) -> bool:
    """Delete a connection, or *hide* a builtin (which is restorable). Returns True
    when the row was genuinely removed — the caller's signal that the connection's
    derived intelligence should be purged (a hidden builtin keeps its artifacts)."""
    if conn_id == SAMPLES_ID:
        raise ValueError("The Sample Catalog cannot be deleted.")
    if conn_id == WORKSPACE_ID:
        raise ValueError("The Workspace cannot be deleted.")
    deleted = conn_id not in (BUILTIN_ID, POSTGRES_BUILTIN_ID)
    if not deleted:
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
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "profile-cache invalidation on delete is best-effort; stale entries expire",
                 counter="registry.profile_cache.invalidate")
    # Drop materialized-cache rows for this connection — they can never be served
    # again once the connection is gone, and would otherwise linger until TTL.
    try:
        from aughor.db.matcache import invalidate as _matcache_invalidate
        _matcache_invalidate(conn_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "matcache invalidation on delete is best-effort; rows expire on schedule",
                 counter="registry.matcache.invalidate")
    # Evict pooled physical connections — the connection no longer exists.
    try:
        from aughor.db.pool import evict_conn
        evict_conn(conn_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "pool eviction on delete is best-effort; the connection no longer exists",
                 counter="registry.pool.evict")
    return deleted


def _dsn_preview(conn_type: str) -> str:
    from aughor.connectors.registry import DSN_PREVIEWS
    return DSN_PREVIEWS.get(conn_type, conn_type)
