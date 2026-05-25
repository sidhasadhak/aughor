"""
Profile cache — persists TableProfile and ColumnProfile objects between runs.

Cache key: "{connection_id}:{schema_fingerprint}"
  - connection_id: the UUID-style ID from the registry (or "fixture" / "mydb")
  - schema_fingerprint: MD5 of sorted table names + column counts (from schema_cache.py)

Per-table granularity: when a schema changes (new table, column added), only the
affected tables are re-profiled. Tables whose fingerprint hasn't changed are loaded
from cache without touching the database.

File: data/schema_profiles.json
  Max entries: 20 (connection × fingerprint combos)
  Eviction: LRU — oldest entry removed when cap exceeded
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from aughor.tools.profiler import ColumnProfile, TableProfile

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "schema_profiles.json"
_MAX_ENTRIES = 20


# ── Fingerprint helpers ───────────────────────────────────────────────────────

def compute_schema_fingerprint(table_col_counts: dict[str, int]) -> str:
    """
    Stable fingerprint of a schema.
    table_col_counts: {table_name: column_count}
    Changing a column name (not just count) won't invalidate this — that's
    acceptable; profile staleness is harmless (old interpretation stays until
    the next explicit re-profile). Adding/removing tables will invalidate.
    """
    parts = sorted(f"{t}:{n}" for t, n in table_col_counts.items())
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _cache_key(connection_id: str, fingerprint: str) -> str:
    return f"{connection_id}:{fingerprint}"


# ── Load / save ───────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text())
    except Exception:
        pass
    return {}


def _save(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def load_profiles(
    connection_id: str,
    fingerprint: str,
) -> Optional[tuple[dict[str, TableProfile], dict[str, ColumnProfile]]]:
    """
    Load cached profiles for this (connection_id, fingerprint) pair.
    Returns (table_profiles, column_profiles) or None if not cached.
    """
    cache = _load()
    key = _cache_key(connection_id, fingerprint)
    entry = cache.get(key)
    if not entry:
        return None

    try:
        table_profiles = {
            t: TableProfile.from_dict(d)
            for t, d in entry.get("tables", {}).items()
        }
        column_profiles = {
            k: ColumnProfile.from_dict(d)
            for k, d in entry.get("columns", {}).items()
        }
        return table_profiles, column_profiles
    except Exception:
        return None


def save_profiles(
    connection_id: str,
    fingerprint: str,
    table_profiles: dict[str, TableProfile],
    column_profiles: dict[str, ColumnProfile],
) -> None:
    """Persist profiles to the cache. Evicts oldest entry when cap is reached."""
    cache = _load()
    key = _cache_key(connection_id, fingerprint)

    # Move to end (most-recently-used)
    cache.pop(key, None)
    cache[key] = {
        "tables": {t: tp.to_dict() for t, tp in table_profiles.items()},
        "columns": {k: cp.to_dict() for k, cp in column_profiles.items()},
    }

    # LRU eviction
    while len(cache) > _MAX_ENTRIES:
        oldest = next(iter(cache))
        del cache[oldest]

    _save(cache)


def invalidate(connection_id: str) -> None:
    """Remove all cached profiles for a connection (called on delete or DSN change)."""
    cache = _load()
    prefix = f"{connection_id}:"
    evict = [k for k in cache if k.startswith(prefix)]
    for k in evict:
        del cache[k]
    if evict:
        _save(cache)


def get_or_build_profiles(
    conn,  # DatabaseConnection
    connection_id: str,
    tables: list[str],
    fk_hints: dict[str, set[str]],
) -> tuple[dict[str, TableProfile], dict[str, ColumnProfile]]:
    """
    Main entry point called at schema-load time.

    Computes the schema fingerprint from table names + column counts (cheap),
    then either returns the cached profiles or runs the profiler and caches the result.

    `fk_hints` is {table: {fk_col, ...}} derived from the join-inference step.
    """
    from aughor.tools.profiler import profile_connection

    # Compute fingerprint from column counts per table
    col_counts: dict[str, int] = {}
    for table in tables:
        try:
            if conn.dialect == "duckdb":
                # SELECT-wrapped DESCRIBE passes the SELECT-only validator
                r = conn.execute(
                    "__profiler__",
                    f'SELECT COUNT(*) FROM (DESCRIBE "{table}")',
                )
                col_counts[table] = int(r.rows[0][0]) if not r.error and r.rows else 0
            else:
                schema_name = getattr(conn, "_schema_name", "public")
                r = conn.execute(
                    "__profiler__",
                    f"SELECT COUNT(*) FROM information_schema.columns "
                    f"WHERE table_name = '{table}' AND table_schema = '{schema_name}'",
                )
                col_counts[table] = int(r.rows[0][0]) if not r.error and r.rows else 0
        except Exception:
            col_counts[table] = 0

    fingerprint = compute_schema_fingerprint(col_counts)

    # Cache hit
    cached = load_profiles(connection_id, fingerprint)
    if cached is not None:
        return cached

    # Cache miss — run profiler and persist
    table_profiles, column_profiles = profile_connection(conn, tables, fk_hints)
    save_profiles(connection_id, fingerprint, table_profiles, column_profiles)
    return table_profiles, column_profiles
