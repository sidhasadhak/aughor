"""
Materialization Cache — M3c

Caches expensive query results as rows in a DuckDB file
(data/mat_cache.duckdb), keyed by (conn_id, [tenancy], sha256(sql)).
TTL defaults to 1 hour.

Usage::

    from aughor.db.matcache import get_cached, put_cache, invalidate

    result = get_cached(conn_id, sql)           # None on miss / expiry
    if result is None:
        result = db.execute(hyp_id, sql)
        put_cache(conn_id, sql, result)         # store for next time

**Tenancy (RBAC row policy).** These rows are POST-execution — i.e. post-RLS when
``rbac.row_policy`` is active — but the cache is consulted *before* the connection layer
injects a principal's row filters. Keyed on ``(conn_id, sql)`` alone, one principal's filtered
rows would be served to another under the same key. Callers on a per-principal result path must
therefore pass ``tenancy=result_cache_tenancy()`` (``aughor/db/connection.py``) to both
``get_cached`` and ``put_cache``: it folds ``(org, roles, resolved row filters)`` into the key
when the policy gate is live, and is ``None`` (→ the legacy key, byte-identical) when it is inert.
Do NOT pass a tenancy for permission-independent results (schema/metadata) — a raw shared key is
correct there (the schema is identical for every principal on a connection).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

import duckdb

from aughor.db.sqlite_util import resolve_db_path
from aughor.platform.contracts.execution import QueryResult

# WP-4 — env override (AUGHOR_MATCACHE_DB) so the test suite can point this at a temp
# file; it was hardcoded to the live data/ dir with no override (a non-hermetic hole).
_CACHE_PATH = resolve_db_path("AUGHOR_MATCACHE_DB", Path("data") / "mat_cache.duckdb")
DEFAULT_TTL: float = 3_600.0   # 1 hour

# Module-level connection — opened lazily once, reused.
_conn: duckdb.DuckDBPyConnection | None = None

_DDL = """
CREATE TABLE IF NOT EXISTS mat_cache (
    cache_key    TEXT PRIMARY KEY,
    conn_id      TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    rows_json    TEXT NOT NULL,
    row_count    INTEGER NOT NULL,
    stored_at    DOUBLE NOT NULL
)
"""


def _db() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(str(_CACHE_PATH))
        _conn.execute(_DDL)
    return _conn


def _cache_key(conn_id: str, sql: str, tenancy: str | None = None) -> str:
    # tenancy=None reproduces the historical key EXACTLY (byte-identical), so entries written before
    # this parameter existed — and every current default-off deployment — keep resolving. A non-None
    # tenancy partitions the key per principal/policy (see the module docstring).
    raw = f"{conn_id}::{sql.strip()}" if tenancy is None else f"{conn_id}::{tenancy}::{sql.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Public API ────────────────────────────────────────────────────────────────

def get_cached(
    conn_id: str,
    sql: str,
    ttl: float = DEFAULT_TTL,
    *,
    tenancy: str | None = None,
) -> Optional[QueryResult]:
    """Return a cached QueryResult if one exists and is still fresh, else None.

    ``tenancy`` partitions the entry per principal/policy under the RBAC row policy — pass
    ``result_cache_tenancy()`` on a per-principal result path; leave it ``None`` (the default,
    byte-identical legacy key) for permission-independent results. See the module docstring."""
    try:
        c = _db()
        key = _cache_key(conn_id, sql, tenancy)
        row = c.execute(
            "SELECT columns_json, rows_json, row_count, stored_at "
            "FROM mat_cache WHERE cache_key = ?",
            [key],
        ).fetchone()
        if row is None:
            return None
        columns_json, rows_json, row_count, stored_at = row
        if time.time() - stored_at > ttl:
            c.execute("DELETE FROM mat_cache WHERE cache_key = ?", [key])
            return None
        return QueryResult(
            hypothesis_id="__cache__",
            sql=sql,
            columns=json.loads(columns_json),
            rows=json.loads(rows_json),
            row_count=row_count,
        )
    except Exception:
        return None


def put_cache(conn_id: str, sql: str, result: QueryResult, *, tenancy: str | None = None) -> None:
    """Store a QueryResult in the cache (upsert by cache_key).

    ``tenancy`` MUST match the value used for the paired ``get_cached`` so a principal reads back
    exactly what it wrote. See the module docstring."""
    try:
        c = _db()
        key = _cache_key(conn_id, sql, tenancy)
        c.execute(
            """
            INSERT OR REPLACE INTO mat_cache
                (cache_key, conn_id, columns_json, rows_json, row_count, stored_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                key,
                conn_id,
                json.dumps(result.columns),
                json.dumps(result.rows),
                result.row_count,
                time.time(),
            ],
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "materialized-cache write is non-fatal; the query just recomputes next time",
                 counter="matcache.write")


def invalidate(conn_id: str) -> int:
    """Delete all cache entries for a connection. Returns number of rows deleted."""
    try:
        c = _db()
        c.execute("DELETE FROM mat_cache WHERE conn_id = ?", [conn_id])
        # DuckDB cursor doesn't expose rowcount reliably; return 0 as sentinel
        return 0
    except Exception:
        return 0


def evict_expired(ttl: float = DEFAULT_TTL) -> int:
    """Remove all entries older than *ttl* seconds. Returns count evicted.

    The cache is TTL-on-read, so an entry that is never read again lives forever
    until this runs — call it on a schedule (see monitors.scheduler) so the file
    can't grow unbounded on a long-running server."""
    try:
        c = _db()
        cutoff = time.time() - ttl
        n = c.execute(
            "SELECT COUNT(*) FROM mat_cache WHERE stored_at < ?", [cutoff]
        ).fetchone()
        evicted = int(n[0]) if n and n[0] is not None else 0
        c.execute("DELETE FROM mat_cache WHERE stored_at < ?", [cutoff])
        return evicted
    except Exception:
        return 0


def cache_stats() -> dict:
    """Return aggregate stats about the cache."""
    try:
        c = _db()
        row = c.execute(
            "SELECT COUNT(*), MIN(stored_at), MAX(stored_at) FROM mat_cache"
        ).fetchone()
        return {
            "entries": row[0],
            "oldest_at": row[1],
            "newest_at": row[2],
            "ttl_default_s": DEFAULT_TTL,
        }
    except Exception:
        return {"entries": 0, "oldest_at": None, "newest_at": None}
