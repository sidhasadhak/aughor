"""Shared mutable state and helpers used across multiple routers.

These objects are module-level singletons — Python's import system guarantees
all routers importing from this module share the same dict instances.
"""
from __future__ import annotations

import time as _time

# ── Schema cache ──────────────────────────────────────────────────────────────
_schema_cache: dict[str, tuple[float, str]] = {}
_SCHEMA_CACHE_TTL = 300.0  # seconds


def get_schema_cached(conn_id: str, db) -> str:
    cached = _schema_cache.get(conn_id)
    if cached and (_time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL:
        return cached[1]
    schema = db.get_schema()
    _schema_cache[conn_id] = (_time.monotonic(), schema)
    return schema


def invalidate_schema_cache(conn_id: str) -> None:
    _schema_cache.pop(conn_id, None)


# ── Background explorer registry ──────────────────────────────────────────────
explorers: dict = {}              # conn_id → SchemaExplorer
explorer_tasks: dict = {}         # conn_id → asyncio.Task
canvas_explorers: dict = {}       # canvas_id → SchemaExplorer
canvas_explorer_tasks: dict = {}  # canvas_id → asyncio.Task
