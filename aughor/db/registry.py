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

from aughor.db.migrations import Migration, add_column_if_missing, run_migrations
from aughor.db.sqlite_util import tune
from aughor.org.context import DEFAULT_ORG_ID, current_org_id

# AUGHOR_REGISTRY_DB overrides the connections registry path (mirrors the ledger's
# AUGHOR_SYSTEM_DB). Tests point it at a temp path so the suite can NEVER mutate the real
# data/connections.db — the harness gap that let a full-suite run empty live connections.
REGISTRY_DB = Path(os.environ.get("AUGHOR_REGISTRY_DB")
                   or (Path(__file__).parent.parent.parent / "data" / "connections.db"))
KEY_FILE    = Path(__file__).parent.parent.parent / "data" / ".aughor_key"

BUILTIN_ID = "fixture"
POSTGRES_BUILTIN_ID = "mydb"
SAMPLES_ID = "samples"
WORKSPACE_ID = "workspace"  # default DuckDB-backed scratch space for file uploads
AUGHOR_OPS_ID = "aughor_ops"  # Aughor-on-Aughor: the platform's own task_history/jobs/events


def _aughor_ops_available() -> bool:
    """The self-investigation connection exists only when the span table is being
    written (flag ``obs.task_table``) — no point pointing an investigator at an
    always-empty table. Reads through the runtime flag so an operator toggle
    surfaces/hides it live."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("obs.task_table")
    except Exception:
        return False


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


# Schema evolution runs through the versioned migration framework (DATA-05). The
# base table below is v1; each later change is a Migration(version>=2). Migrations
# must stay ADDITIVE (see aughor/db/migrations.py) so a code rollback is always safe.
_MIGRATIONS = [
    Migration(2, "tenant key: org_id on connections",
              lambda c: add_column_if_missing(
                  c, "connections", "org_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_ORG_ID}'")),
]


def _db() -> sqlite3.Connection:
    REGISTRY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = tune(sqlite3.connect(str(REGISTRY_DB)))
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
    run_migrations(conn, _MIGRATIONS, store="registry")
    return conn


# ── Public API ────────────────────────────────────────────────────────────────

def _hidden_builtins() -> set:
    return set(_load_settings().get("hidden_builtins", []))


def list_connections(org_id: str | None = None) -> list[dict]:
    """Return all saved connections (DSN redacted).

    When identity is enforced (DATA-06), the DB-stored connections are scoped to a
    single org: pass ``org_id`` explicitly (the caller-facing endpoint reads it from
    the authenticated principal, which is reliable across the sync-endpoint boundary
    where the ``current_org_id()`` contextvar is not); direct/internal callers fall
    back to the contextvar. Shared builtins are always included."""
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
        from aughor.samples.setup import fixture_db_path
        fixture_path = fixture_db_path()
        rows.append({
            "id": BUILTIN_ID,
            "name": "Fixture DB (demo)",
            "conn_type": "duckdb",
            "dsn_preview": str(fixture_path),
            "meta": {},
            "builtin": False,
        })

    # Aughor-on-Aughor — the platform's own operational tables as a queryable
    # connection, present only while spans are being recorded (flag obs.task_table).
    if AUGHOR_OPS_ID not in hidden and _aughor_ops_available():
        rows.append({
            "id": AUGHOR_OPS_ID,
            "name": "Aughor Ops (self-investigation)",
            "conn_type": "aughor_ops",
            "dsn_preview": "aughor://ops/task_history",
            "schema_name": "aughor_ops",
            "meta": {"builtin_aughor_ops": True, "schema_name": "aughor_ops"},
            "builtin": True,
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

    # Tenant scoping (DATA-06): when identity is enforced, a caller sees only their
    # own org's saved connections. The shared builtins above stay visible to all.
    # OFF by default → current_org_id() is 'default' and every row is 'default', so
    # the filter is a no-op and behaviour is unchanged.
    from aughor.security.authz import require_identity_enabled
    if require_identity_enabled():
        _scope_org = org_id if org_id is not None else current_org_id()
        _where, _params = "WHERE org_id = ?", [_scope_org]
    else:
        _where, _params = "", []
    with _db() as conn:
        for row in conn.execute(
            f"SELECT id, name, conn_type, meta FROM connections {_where} ORDER BY rowid", _params
        ):
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
    if conn_id == AUGHOR_OPS_ID:
        return {"builtin_aughor_ops": True, "schema_name": "aughor_ops"}
    if conn_id == WORKSPACE_ID:
        from aughor.samples.setup import samples_db_path
        samples_path = samples_db_path()
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


def get_connection_org(conn_id: str) -> str | None:
    """The org that owns a connection, or None when unknown (builtins / missing id).

    Ownership of derived resources (investigations, canvases) resolves THROUGH the
    connection's org — the investigations table itself carries no org_id (DATA-06).
    Returns None for the shared builtins (fixture/samples/workspace), which are not
    org-scoped, so an owner-check over them is a no-op.
    """
    if not conn_id:
        return None
    with _db() as conn:
        row = conn.execute(
            "SELECT org_id FROM connections WHERE id = ?", [conn_id]
        ).fetchone()
    return row["org_id"] if row else None


_SETTINGS_PATH = Path(os.environ.get("AUGHOR_CONNECTION_SETTINGS")
                      or (Path(__file__).parent.parent.parent / "data" / "connection_settings.json"))


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
        from aughor.samples.setup import samples_db_path
        return "duckdb", str(samples_db_path())
    if conn_id == WORKSPACE_ID:
        return "local_upload", "local://"
    if conn_id == AUGHOR_OPS_ID:
        if not _aughor_ops_available():
            raise KeyError("aughor_ops is available only when obs.task_table is enabled")
        from aughor.kernel.ledger import Ledger
        return "aughor_ops", str(Ledger.default().path)
    if conn_id == BUILTIN_ID:
        from aughor.samples.setup import fixture_db_path
        return "duckdb", str(fixture_db_path())
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
    # Evict any cached profiles for this connection. Emitted via the platform
    # ingestion/event seam so this module (platform db) never imports the agent;
    # the agent registers the "connection_invalidated" sink (profile-cache evict).
    try:
        from aughor.kernel.registries.ingestion import ingest
        ingest("connection_invalidated", conn_id=conn_id)
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
