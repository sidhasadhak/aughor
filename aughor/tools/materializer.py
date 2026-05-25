"""
Query result materializer — sidecar DuckDB cache for expensive queries.

Cache key:  {connection_id}:{md5(sql)[:16]}
TTL:        24 hours (soft — expired entries are evicted on next get())
Storage:    data/hermes_mat.duckdb  (separate from the fixture DB)

Usage:
    mat = QueryMaterializer()
    hit = mat.get(conn_id, sql, hypothesis_id)
    if hit is None:
        result = db.execute(hypothesis_id, sql)
        mat.put(conn_id, result)
    else:
        result = hit  # served from cache
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

import duckdb

from aughor.agent.state import QueryResult

_DB_PATH = Path("data/hermes_mat.duckdb")
_TTL_SECONDS = 86_400  # 24 hours

_INIT_DDL = """
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key    TEXT    PRIMARY KEY,
    connection_id TEXT   NOT NULL,
    sql          TEXT    NOT NULL,
    columns      TEXT    NOT NULL,
    rows         TEXT    NOT NULL,
    row_count    INTEGER NOT NULL,
    created_at   DOUBLE  NOT NULL
)
"""


class QueryMaterializer:
    """Thread-safe sidecar DuckDB cache for query results.

    Each instance owns a private DuckDB connection to hermes_mat.duckdb.
    Writes are fire-and-forget (errors are silently swallowed) — the cache
    is a performance optimisation, never a correctness dependency.
    """

    def __init__(self, db_path: str | Path = _DB_PATH) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._path))
        self._conn.execute(_INIT_DDL)

    # ── Cache key ─────────────────────────────────────────────────────────────

    @staticmethod
    def cache_key(connection_id: str, sql: str) -> str:
        digest = hashlib.md5(sql.strip().encode()).hexdigest()[:16]
        return f"{connection_id}:{digest}"

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, connection_id: str, sql: str, hypothesis_id: str) -> Optional[QueryResult]:
        """Return cached result or None if missing / TTL-expired."""
        from aughor.stats import stats
        key = self.cache_key(connection_id, sql)
        try:
            row = self._conn.execute(
                "SELECT columns, rows, row_count, created_at "
                "FROM query_cache WHERE cache_key = ?",
                [key],
            ).fetchone()
        except Exception:
            stats.inc("materializer_misses")
            return None

        if row is None:
            stats.inc("materializer_misses")
            return None

        columns_json, rows_json, row_count, created_at = row
        if time.time() - created_at > _TTL_SECONDS:
            self._evict(key)
            stats.inc("materializer_misses")
            return None

        stats.inc("materializer_hits")
        return QueryResult(
            hypothesis_id=hypothesis_id,
            sql=sql,
            columns=json.loads(columns_json),
            rows=json.loads(rows_json),
            row_count=row_count,
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def put(self, connection_id: str, result: QueryResult) -> None:
        """Upsert a QueryResult. Errors (empty results, failed queries) are not cached."""
        if result.error or not result.columns or result.sql is None:
            return
        key = self.cache_key(connection_id, result.sql)
        try:
            self._conn.execute(
                """
                INSERT INTO query_cache
                    (cache_key, connection_id, sql, columns, rows, row_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (cache_key) DO UPDATE SET
                    columns    = excluded.columns,
                    rows       = excluded.rows,
                    row_count  = excluded.row_count,
                    created_at = excluded.created_at
                """,
                [
                    key,
                    connection_id,
                    result.sql,
                    json.dumps(result.columns),
                    json.dumps(result.rows),
                    result.row_count,
                    time.time(),
                ],
            )
        except Exception:
            pass

    # ── Invalidation ──────────────────────────────────────────────────────────

    def invalidate_connection(self, connection_id: str) -> int:
        """Purge all cached entries for a connection. Returns the count deleted."""
        try:
            self._conn.execute(
                "DELETE FROM query_cache WHERE connection_id = ?",
                [connection_id],
            )
            row = self._conn.execute("SELECT changes()").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def invalidate_key(self, connection_id: str, sql: str) -> None:
        """Purge a single cache entry."""
        self._evict(self.cache_key(connection_id, sql))

    def purge_expired(self) -> int:
        """Delete all entries older than TTL. Returns count deleted."""
        cutoff = time.time() - _TTL_SECONDS
        try:
            self._conn.execute(
                "DELETE FROM query_cache WHERE created_at < ?",
                [cutoff],
            )
            row = self._conn.execute("SELECT changes()").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def _evict(self, key: str) -> None:
        try:
            self._conn.execute("DELETE FROM query_cache WHERE cache_key = ?", [key])
        except Exception:
            pass
