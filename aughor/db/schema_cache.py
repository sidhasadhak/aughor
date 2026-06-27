"""
Schema fingerprint cache.

Stores MD5 fingerprints of database schemas that have been fully auto-seeded.
On reconnect to an unchanged database, autoseed skips all LLM calls instantly.

Fingerprint = MD5(sorted_table_names + column_counts_per_table).
Cache is a simple JSON file capped at MAX_ENTRIES (LRU eviction).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "schema_cache.json"
_MAX_ENTRIES = 50


def compute_fingerprint(table_blocks: dict[str, str]) -> str:
    """
    Stable fingerprint of a schema based on table names and approximate
    column counts (number of lines in each table block).
    Cheap to compute — no LLM, no DB calls.
    """
    parts = sorted(f"{t}:{blk.count(chr(10))}" for t, blk in table_blocks.items())
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


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
