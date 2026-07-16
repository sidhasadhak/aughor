"""Shared mutable state and helpers used across multiple routers.

These objects are module-level singletons — Python's import system guarantees
all routers importing from this module share the same dict instances.
"""
from __future__ import annotations

import time as _time

# ── Schema cache ──────────────────────────────────────────────────────────────
_schema_cache: dict[str, tuple[float, str]] = {}
_SCHEMA_CACHE_TTL = 300.0  # seconds


def _schema_cache_key(conn_id: str, db) -> str:
    # Keyed on (conn_id, schema-SCOPE). Permission-independent still holds — the RBAC row policy
    # filters ROWS not schema, and there is no column-level security — so this stays a raw shared
    # key (unlike matcache, which caches post-RLS rows and folds in tenancy). But a schema-SCOPED
    # connection (open_connection_for_with_schema pins ._schema_name) returns a NARROWER
    # get_schema() than the full connection, so the scope IS part of the cached value's identity.
    # Keying on conn_id alone let a single-schema op (e.g. a canvas scoped to `main`) poison the
    # cache with a one-schema view that a later full-connection consumer (the overview tour)
    # inherited — silently dropping every other schema on a multi-schema connection.
    scope = getattr(db, "_schema_name", None) or getattr(db, "schema_name", None) or ""
    return f"{conn_id}\x00{scope}"


def get_schema_cached(conn_id: str, db) -> str:
    key = _schema_cache_key(conn_id, db)
    cached = _schema_cache.get(key)
    if cached and (_time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL:
        return cached[1]
    schema = db.get_schema()
    _schema_cache[key] = (_time.monotonic(), schema)
    return schema


def invalidate_schema_cache(conn_id: str) -> None:
    # Drop every schema-scope variant cached for this connection (keys are "conn_id\x00scope").
    prefix = f"{conn_id}\x00"
    for k in [k for k in _schema_cache if k.startswith(prefix)]:
        _schema_cache.pop(k, None)
    # A schema change (file add/delete, type override, manual refresh) means any
    # pooled physical connection is stale — evict so the next open re-reads.
    try:
        from aughor.db.pool import evict_conn
        evict_conn(conn_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "pool eviction is best-effort; a stale pooled conn self-heals on next open",
                 counter="pool.evict", conn_id=conn_id)


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
    schema_name: str | None = None,
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

    # Canonical key: a single-schema connection always uses the bare key, so an explicit
    # ?schema= can't split state between {conn} and {conn}__{the_only_schema} (canvas runs
    # key by canvas_id and are unaffected).
    if not canvas_id:
        schema_name = canonical_schema(conn_id, schema_name)

    registry = canvas_explorers if canvas_id else explorers
    tasks_registry = canvas_explorer_tasks if canvas_id else explorer_tasks
    # A per-schema run gets its OWN registry/state/idempotency key so several schemas of
    # one connection can explore independently (and concurrently, under the cap).
    key = canvas_id or (f"{conn_id}__{schema_name}" if schema_name else conn_id)

    existing = registry.get(key)
    if existing is not None:
        phase = getattr(getattr(existing, "status", None), "phase", None)
        if phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED, None):
            return {"ok": False, "reason": "already running", "job_id": None}

    loop = asyncio.get_running_loop()
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema

    def _open_and_test():
        # Schema-scoped open so a per-schema run resolves ONLY that schema's tables.
        db = (open_connection_for_with_schema(conn_id, schema_name)
              if schema_name else open_connection_for(conn_id))
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
    explorer = SchemaExplorer(conn_id, db, canvas_id=canvas_id, tables_filter=tables_filter,
                              schema_name=schema_name)
    registry[key] = explorer

    def _cleanup(_job_id: str, _final: str) -> None:
        # On ANY terminal job state (succeeded/failed/cancelled), drop the explorer from the
        # registry too — not just the task. The registry holds *active* explorers; leaving a
        # finished one (especially a budget-cancelled run stuck mid-phase) makes the next
        # start/spawn refuse "already running". Status falls back to the persisted disk state.
        tasks_registry.pop(key, None)
        registry.pop(key, None)

    from aughor.kernel.jobs import kernel
    job_id = await kernel().submit(
        "exploration",
        lambda: explorer.explore(domain_intel_only=domain_intel_only),
        conn_id=conn_id,
        canvas_id=canvas_id,
        idempotency_key=f"explore:{'canvas:' + canvas_id if canvas_id else key}",
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


async def run_birth(
    conn_id: str,
    *,
    schema_name: str | None = None,
    canvas_id: str | None = None,
    tables_filter: list | None = None,
) -> dict:
    """R12 — the "understand this data" job body (the knowledge/start-mining analog).

    Step 1 ``intelligence`` builds the durable understanding EAGERLY — profiles →
    ontology (enrich + validate) → R8 doc tree → R11 column config, everything the
    heavy annotator chain produces — instead of lazily on the first question.
    Step 2 hands off to exploration, which stays its own supervised kernel job
    (chained, independently observable). Every step emits a ``birth.step`` event
    on the K2 spine and the terminal ``birth.done`` carries the summary, so the
    rite is legible in Fleet / events / (flag ``obs.task_table``) task_history.

    Resilient by design: an intelligence failure still lets exploration run (its
    own ontology gate can retry the build); the job fails only when NOTHING was
    accomplished.
    """
    import asyncio
    import logging

    from aughor.kernel.jobs import current_job_id
    from aughor.kernel.ledger import Ledger

    logger = logging.getLogger(__name__)
    steps: list[dict] = []

    def _emit(step: str, status: str, **detail) -> None:
        rec = {"step": step, "status": status,
               **{k: v for k, v in detail.items() if v not in (None, "")}}
        steps.append(rec)
        try:
            Ledger.default().emit(
                "birth.step", {"connection_id": conn_id, "schema": schema_name, **rec},
                conn_id=conn_id, canvas_id=canvas_id, job_id=current_job_id())
        except Exception:
            logger.debug("birth.step emit failed", exc_info=True)

    loop = asyncio.get_running_loop()
    from aughor.db.connection import open_connection_for, open_connection_for_with_schema

    _emit("intelligence", "started")
    intelligence_ok = False

    def _build():
        db = (open_connection_for_with_schema(conn_id, schema_name)
              if schema_name else open_connection_for(conn_id))
        try:
            from aughor import telemetry
            with telemetry.span(f"birth:{conn_id}", "birth.intelligence",
                                {"connection_id": conn_id, "schema": schema_name or ""}):
                db.build_intelligence()
            return getattr(db, "last_build", None)
        finally:
            try:
                db.close()
            except Exception:
                logger.debug("birth: connection close failed", exc_info=True)

    try:
        last_build = await loop.run_in_executor(None, _build)
        lb = last_build if isinstance(last_build, dict) else {}
        intelligence_ok = bool(lb.get("ok", True))
        _emit("intelligence", "done" if intelligence_ok else "failed",
              stage=lb.get("stage"), error=lb.get("error"))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "birth intelligence step failed; exploration still runs",
                 counter="birth.job", conn_id=conn_id)
        _emit("intelligence", "failed", error=str(exc)[:300])

    _emit("exploration", "started")
    exploration_ok = False
    try:
        res = await spawn_explorer(conn_id, canvas_id=canvas_id,
                                   tables_filter=tables_filter, schema_name=schema_name)
        exploration_ok = bool(res.get("ok"))
        # "already running" / "connection not ready" are handoff declines, not crashes.
        _emit("exploration", "done" if exploration_ok else "skipped",
              job_id=res.get("job_id"), reason=res.get("reason"))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "birth exploration handoff failed", counter="birth.job", conn_id=conn_id)
        _emit("exploration", "failed", error=str(exc)[:300])

    summary = {"connection_id": conn_id, "schema": schema_name,
               "canvas_id": canvas_id, "steps": steps}
    try:
        Ledger.default().emit("birth.done", summary, conn_id=conn_id,
                              canvas_id=canvas_id, job_id=current_job_id())
    except Exception:
        logger.debug("birth.done emit failed", exc_info=True)

    if not intelligence_ok and not exploration_ok:
        raise RuntimeError("birth accomplished nothing — intelligence and exploration both failed")
    return summary


async def spawn_birth(
    conn_id: str,
    *,
    schema_name: str | None = None,
    canvas_id: str | None = None,
    tables_filter: list | None = None,
) -> dict:
    """R12 — submit the birth rite as ONE supervised kernel job (kind ``profile``,
    the Curator charter): persisted state machine, heartbeats, budget governance,
    Fleet visibility, cancellation on owner deletion. The idempotency key debounces
    bursts — an upload storm or a create/upload race can't stack birth jobs for the
    same connection/schema/canvas. Must be awaited from a running event loop."""
    if not canvas_id:
        schema_name = canonical_schema(conn_id, schema_name)
    key = (f"canvas:{canvas_id}" if canvas_id
           else (f"{conn_id}__{schema_name}" if schema_name else conn_id))
    from aughor.kernel.jobs import kernel
    job_id = await kernel().submit(
        "profile",
        lambda: run_birth(conn_id, schema_name=schema_name, canvas_id=canvas_id,
                          tables_filter=tables_filter),
        conn_id=conn_id,
        canvas_id=canvas_id,
        idempotency_key=f"birth:{key}",
        payload={"schema_name": schema_name, "canvas_id": canvas_id,
                 "tables_filter": tables_filter or None},
    )
    return {"ok": True, "job_id": job_id}


def schemas_of_connection(conn_id: str) -> list[str]:
    """The non-system schemas a connection exposes. Used to fan exploration out per schema
    so a multi-schema connection (e.g. a workspace folding ecommerce + missimi + …) gives
    EACH schema its own intelligence instead of one run that starves the smaller schemas.
    Best-effort: returns [] on any failure (caller falls back to a connection-level run).

    ``main`` counts as a REAL schema whenever it holds tables. It used to be excluded
    wholesale (treating it as DuckDB's default namespace), which made a connection with
    data in BOTH main and other schemas look single-schema: canonical_schema() collapsed
    an explicit "explore schema main" to the bare key, silently resuming whatever old
    run lived there and never exploring the main-schema data at all. A DB whose only
    schema is main still resolves to the bare key via the callers' len<=1 rule."""
    try:
        from aughor.db.connection import open_connection_for
        db = open_connection_for(conn_id)
        res = db.execute(
            "__schemas__",
            "SELECT DISTINCT table_schema FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' AND table_schema NOT IN "
            "('information_schema', 'pg_catalog', 'temp') ORDER BY 1",
        )
        return [str(r[0]) for r in (getattr(res, "rows", None) or []) if r and r[0]]
    except Exception:
        return []


def canonical_schema(conn_id: str, schema: str | None) -> str | None:
    """Normalise a requested schema to the canonical key dimension. A single-schema connection
    has exactly one user schema == the connection itself, so it must ALWAYS use the bare key
    (schema=None) — otherwise state splits between `{conn}` and `{conn}__{the_only_schema}`
    depending on whether a caller passed `?schema=`. Returns None for the bare key, else the
    schema unchanged. Best-effort: on any lookup failure, leave the schema as given."""
    if not schema:
        return None
    try:
        schemas = schemas_of_connection(conn_id)
    except Exception:
        return schema
    return None if len(schemas) <= 1 else schema


def kickoff_exploration(conn_id: str, schema_name: str | None = None, *, auto: bool = False) -> bool:
    """Schedule background schema-exploration, unless already active. Returns True if any run
    was scheduled. An explicit schema_name explores just that schema; otherwise a MULTI-schema
    connection fans out into one run PER schema (the 'every schema gets understood' guarantee),
    and a single-schema connection runs connection-level (unchanged).

    ``auto=True`` marks a background kick (on-connect / startup): it runs only when the Org
    has the **Scout** agent enabled. An explicit user 'Start' (``auto=False``) always runs.

    Thin sync wrapper over ``spawn_explorer``. Must be called from within a running event loop.
    """
    import asyncio
    from aughor.explorer.models import ExplorationPhase

    if auto:
        from aughor.kernel.agents import is_enabled
        from aughor.workspace.store import workspace_for_connection
        if not is_enabled("scout", workspace_for_connection(conn_id)):
            import logging
            logging.getLogger(__name__).info(
                "kickoff_exploration: Scout disabled by governance — skipping auto run for %s", conn_id)
            # WP-6/6c — surface the silent skip: an auto run (on-connect or the continuous
            # tick) that never happens because Scout is disabled was previously log-only, so
            # a connection that never explores was invisible. Emit a ledger event the event
            # spine carries to the UI (Inbox / the EXPLORER status chip).
            try:
                from aughor.kernel.ledger import Ledger
                Ledger.default().emit(
                    "exploration.skipped",
                    {"reason": "scout_disabled", "connection_id": conn_id}, conn_id=conn_id)
            except Exception:
                logging.getLogger(__name__).debug("exploration.skipped emit failed", exc_info=True)
            return False

    if schema_name:
        targets: list[str | None] = [schema_name]
    else:
        _schemas = schemas_of_connection(conn_id)
        targets = list(_schemas) if len(_schemas) >= 2 else [None]

    # R12 — when the birth job is on (and the Curator agent is enabled for this
    # workspace), a kick elevates to the full birth rite: eager intelligence first,
    # then the exploration handoff, one supervised kernel job per target schema.
    # Off → exploration alone, exactly as before.
    birth = False
    from aughor.kernel.flags import flag_enabled
    if flag_enabled("birth.job"):
        try:
            from aughor.kernel.agents import is_enabled
            from aughor.workspace.store import workspace_for_connection
            birth = is_enabled("curator", workspace_for_connection(conn_id))
        except Exception:
            birth = True   # governance lookup hiccup → the flag still decides

    started = False
    for sch in targets:
        key = f"{conn_id}__{sch}" if sch else conn_id
        existing = explorers.get(key)
        if existing is not None:
            phase = getattr(getattr(existing, "status", None), "phase", None)
            if phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED, None):
                continue  # this schema's run is already active
        if birth:
            asyncio.create_task(spawn_birth(conn_id, schema_name=sch), name=f"birth-{key}")
        else:
            asyncio.create_task(spawn_explorer(conn_id, schema_name=sch), name=f"kickoff-{key}")
        started = True
    return started
