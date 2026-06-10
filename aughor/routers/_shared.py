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


def explorers_for_connection(connection_id: str, *, include_paused: bool = False) -> list:
    """Every live explorer bound to a connection — the connection explorer plus any canvas
    explorers running on the same connection. Used to pause ALL background exploration
    during a user investigation so it doesn't contend with the investigation's queries. By
    default skips already-paused explorers (so the caller only resumes what it paused)."""
    out = []
    e = explorers.get(connection_id)
    if e is not None:
        out.append(e)
    for cx in list(canvas_explorers.values()):
        if getattr(cx, "connection_id", None) == connection_id:
            out.append(cx)
    if not include_paused:
        out = [x for x in out if not getattr(getattr(x, "_status", None), "paused", False)]
    return out


async def spawn_explorer(
    conn_id: str,
    *,
    canvas_id: str | None = None,
    tables_filter: list | None = None,
    domain_intel_only: bool = False,
) -> dict:
    """THE explorer spawn path — every surface (start, resume, restart, extend,
    trigger-intel, canvas start/restart, boot recovery) goes through here, so an
    exploration is always a supervised kernel job: persisted state machine,
    heartbeats, crash-resume at boot, cancellation on owner deletion. Replaces
    the eight hand-rolled SchemaExplorer + create_task dances.

    Returns ``{"ok": bool, "reason": str | None, "job_id": str | None}``.
    Must be awaited from a running event loop.
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    from aughor.explorer.models import ExplorationPhase

    registry = canvas_explorers if canvas_id else explorers
    tasks_registry = canvas_explorer_tasks if canvas_id else explorer_tasks
    key = canvas_id or conn_id

    existing = registry.get(key)
    if existing is not None:
        phase = getattr(getattr(existing, "status", None), "phase", None)
        if phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED, None):
            return {"ok": False, "reason": "already running", "job_id": None}

    loop = asyncio.get_running_loop()
    from aughor.db.connection import open_connection_for

    def _open_and_test():
        db = open_connection_for(conn_id)
        ok, msg = db.test()
        if not ok:
            db.close()
            return None, False, msg
        return db, True, msg

    try:
        db, ok, msg = await loop.run_in_executor(None, _open_and_test)
    except Exception as exc:
        db, ok, msg = None, False, str(exc)
    if not ok or db is None:
        logger.warning("spawn_explorer: %s not ready — %s", conn_id, msg)
        return {"ok": False, "reason": f"connection not ready: {msg}", "job_id": None}

    from aughor.explorer.agent import SchemaExplorer
    explorer = SchemaExplorer(conn_id, db, canvas_id=canvas_id, tables_filter=tables_filter)
    registry[key] = explorer

    def _cleanup(_job_id: str, _final: str) -> None:
        tasks_registry.pop(key, None)

    from aughor.kernel.jobs import kernel
    job_id = await kernel().submit(
        "exploration",
        lambda: explorer.explore(domain_intel_only=domain_intel_only),
        conn_id=conn_id,
        canvas_id=canvas_id,
        idempotency_key=f"explore:{'canvas:' + canvas_id if canvas_id else conn_id}",
        payload={"domain_intel_only": domain_intel_only,
                 "tables_filter": tables_filter or None},
        on_finish=_cleanup,
    )
    # The kernel task is the cancellation handle — stop endpoints keep working.
    _t = kernel()._tasks.get(job_id)
    if _t is not None:
        tasks_registry[key] = _t
    logger.info("spawn_explorer: %s started for %s (job %s)",
                "canvas " + canvas_id if canvas_id else "connection", conn_id, job_id)
    return {"ok": True, "reason": None, "job_id": job_id}


def kickoff_exploration(conn_id: str) -> bool:
    """Schedule a background schema-exploration run for a connection, unless one
    is already active. Returns True if a run was scheduled, False if skipped.

    Thin sync wrapper over ``spawn_explorer`` (the guard runs here so the caller
    gets an honest bool; the open+test+explore work runs as a kernel job).
    Must be called from within a running event loop.
    """
    import asyncio

    from aughor.explorer.models import ExplorationPhase

    existing = explorers.get(conn_id)
    if existing is not None:
        phase = getattr(getattr(existing, "status", None), "phase", None)
        if phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED, None):
            return False  # already running — don't double-start

    asyncio.create_task(spawn_explorer(conn_id), name=f"kickoff-{conn_id}")
    return True
