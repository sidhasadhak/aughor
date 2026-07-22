"""
Schema fingerprint cache.

Stores MD5 fingerprints of database schemas that have been fully auto-seeded.
On reconnect to an unchanged database, autoseed skips all LLM calls instantly.

Fingerprint = MD5(scope + sorted_table_names + column_counts_per_table), where scope is the
owning connection + schema — structure alone does not identify a schema, and two copies of
the same DDL used to share one "seeded" marker.
Cache is a simple JSON file capped at MAX_ENTRIES (LRU eviction).
"""
from __future__ import annotations

import hashlib
import json

from aughor.db.paths import state_dir

# Generated per-connection state, so it belongs to the AUGHOR_STATE_DIR family. It was a
# repo-absolute `Path(__file__).parent…/data/` — an override-free hole the 2026-07-21 canary
# caught only because it diffed the WHOLE directory rather than the stores we knew about.
_CACHE_PATH = state_dir() / "schema_cache.json"
_MAX_ENTRIES = 50


def compute_fingerprint(table_blocks: dict[str, str], scope: str = "") -> str:
    """
    Stable fingerprint of a schema based on table names and approximate
    column counts (number of lines in each table block).
    Cheap to compute — no LLM, no DB calls.

    ``scope`` identifies WHOSE schema this is (connection + schema name). Without it the
    fingerprint described only *structure*, so two schemas built from the same DDL — a dev
    and a prod copy, two tenants, two schemas in one workspace — hashed identically and the
    second inherited the first's "fully seeded" marker without ever being seeded. Structure
    alone cannot identify a schema; only structure plus owner can.

    Omitted → the legacy structure-only hash, so a caller that genuinely has no scope
    (and any stored fingerprint it wrote) keeps working unchanged.
    """
    parts = sorted(f"{t}:{blk.count(chr(10))}" for t, blk in table_blocks.items())
    raw = "|".join(parts)
    if scope:
        # NUL-separated: no schema or connection id can contain it, so no scope+structure
        # pair can be confused with a different pair that happens to concatenate the same.
        raw = f"{scope}\x00{raw}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def scope_key(connection_id: str | None, schema: str | None) -> str:
    """The ``scope`` for :func:`compute_fingerprint` — ``""`` when neither is known."""
    conn = (connection_id or "").strip()
    sch = (schema or "").strip()
    return f"{conn}\x00{sch}" if (conn or sch) else ""


def is_complete(fingerprint: str) -> bool:
    """Return True if this fingerprint was previously fully seeded."""
    return fingerprint in _load()


def mark_complete(fingerprint: str) -> None:
    """Record that this schema fingerprint is fully seeded."""
    cache = _load()
    # Move to end (most-recently-used)
    cache.pop(fingerprint, None)
    cache[fingerprint] = True
    # Evict oldest if over cap
    while len(cache) > _MAX_ENTRIES:
        oldest = next(iter(cache))
        del cache[oldest]
    _save(cache)


def _load() -> dict[str, bool]:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text())
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "schema-fingerprint cache read is best-effort; treated as empty (re-seeds)",
                 counter="schema_cache.read")
    return {}


def _save(cache: dict[str, bool]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "schema-fingerprint cache write is non-fatal; schema re-seeds next time",
                 counter="schema_cache.write")
