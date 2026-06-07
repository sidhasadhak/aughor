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
    # A schema change (file add/delete, type override, manual refresh) means any
    # pooled physical connection is stale — evict so the next open re-reads.
    try:
        from aughor.db.pool import evict_conn
        evict_conn(conn_id)
    except Exception:
        pass


# ── Background explorer registry ──────────────────────────────────────────────
explorers: dict = {}              # conn_id → SchemaExplorer
explorer_tasks: dict = {}         # conn_id → asyncio.Task
canvas_explorers: dict = {}       # canvas_id → SchemaExplorer
canvas_explorer_tasks: dict = {}  # canvas_id → asyncio.Task


def kickoff_exploration(conn_id: str) -> bool:
    """Schedule a background schema-exploration run for a connection, unless one
    is already active. Returns True if a run was scheduled, False if skipped.

    Shared by the explicit ``POST /exploration/{id}/start`` endpoint and by
    connection creation (auto-onboarding). The heavy open+test+explore work runs
    as a background task — this never blocks the caller. The run is visible via
    ``GET /exploration/{id}/status`` and cancellable via ``POST /exploration/{id}/stop``.

    Must be called from within a running event loop (i.e. an async request
    handler), since it uses ``asyncio.create_task``.
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    from aughor.explorer.models import ExplorationPhase

    existing = explorers.get(conn_id)
    if existing is not None:
        phase = getattr(getattr(existing, "status", None), "phase", None)
        if phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED, None):
            return False  # already running — don't double-start

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        try:
            from aughor.db.connection import open_connection_for

            def _open_and_test():
                db = open_connection_for(conn_id)
                ok, msg = db.test()
                if not ok:
                    db.close()
                    return None, False, msg
                return db, True, msg

            db, ok, msg = await loop.run_in_executor(None, _open_and_test)
            if not ok or db is None:
                logger.warning("kickoff_exploration: %s not ready — %s", conn_id, msg)
                return
            from aughor.explorer.agent import SchemaExplorer
            explorer = SchemaExplorer(conn_id, db)
            explorers[conn_id] = explorer
            t = asyncio.create_task(explorer.explore(), name=f"explorer-{conn_id}")
            t.add_done_callback(lambda _, k=conn_id: explorer_tasks.pop(k, None))
            explorer_tasks[conn_id] = t
            logger.info("kickoff_exploration: started for %s", conn_id)
        except Exception as exc:
            logger.warning("kickoff_exploration: failed for %s — %s", conn_id, exc)

    asyncio.create_task(_run(), name=f"kickoff-{conn_id}")
    return True
