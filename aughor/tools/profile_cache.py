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
from pathlib import Path
from typing import Optional

from aughor.tools.profiler import ColumnProfile, TableProfile
from aughor.util.json_store import KeyedJsonStore

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "schema_profiles.json"
_MAX_ENTRIES = 20
_store = KeyedJsonStore(_CACHE_PATH, max_entries=_MAX_ENTRIES)


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
    # Version prefix — bump when the profile schema changes so stale caches that
    # lack new stats (distributions, period density) are rebuilt.
    # v4: adds high-cardinality entity value_sample (R5) — a rebuild populates it.
    raw = "v4-valsample|" + "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _cache_key(connection_id: str, fingerprint: str) -> str:
    return f"{connection_id}:{fingerprint}"


# ── Load / save ───────────────────────────────────────────────────────────────

def _load() -> dict:
    return _store.load()


def _save(cache: dict) -> None:
    _store.save(cache)


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


def load_value_samples(connection_id: str) -> dict[tuple[str, str], list[str]]:
    """Every persisted high-cardinality entity value sample for a connection, keyed
    (table, column), merged across all cached schema fingerprints. Read-only — never
    builds or writes. Returns {} when nothing is cached.

    Feeds offline entity binding (answer_resolution): a value already in the warmed
    sample resolves without a live warehouse probe (Databricks Genie warms the same
    thing at composer-open)."""
    out: dict[tuple[str, str], list[str]] = {}
    try:
        cache = _load()
    except Exception:
        return out
    prefix = f"{connection_id}:"
    for k, entry in cache.items():
        if not k.startswith(prefix):
            continue
        for d in (entry.get("columns") or {}).values():
            vs = d.get("value_sample")
            tbl, col = d.get("table"), d.get("column")
            if vs and tbl and col:
                out.setdefault((tbl, col), vs)
    return out


def save_profiles(
    connection_id: str,
    fingerprint: str,
    table_profiles: dict[str, TableProfile],
    column_profiles: dict[str, ColumnProfile],
) -> None:
    """Persist profiles to the cache. Evicts oldest entry when cap is reached."""
    _store.put(_cache_key(connection_id, fingerprint), {
        "tables": {t: tp.to_dict() for t, tp in table_profiles.items()},
        "columns": {k: cp.to_dict() for k, cp in column_profiles.items()},
    })


def invalidate(connection_id: str) -> None:
    """Remove all cached profiles for a connection (called on delete or DSN change)."""
    _store.invalidate_prefix(f"{connection_id}:")


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
                sql = f'SELECT COUNT(*) FROM (DESCRIBE {table})'
            else:
                schema_name = getattr(conn, "_schema_name", "public")
                sql = (f"SELECT COUNT(*) FROM information_schema.columns "
                       f"WHERE table_name = '{table}' AND table_schema = '{schema_name}'")
            col_counts[table] = conn.scalar(sql, label="__profiler__", cast=int) or 0
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
