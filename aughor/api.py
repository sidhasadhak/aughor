"""FastAPI backend — application entrypoint, middleware, startup events, router registration."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env from the project root (no-op if python-dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from aughor.db.connection import open_connection_for
from aughor.db.registry import list_connections, get_connection_settings

# Shared mutable state — imported here so startup events can populate the dicts
from aughor.routers._shared import (
    explorers as _explorers,
    explorer_tasks as _explorer_tasks,
    canvas_explorers as _canvas_explorers,
    canvas_explorer_tasks as _canvas_explorer_tasks,
    get_schema_cached as _get_schema_cached,
    invalidate_schema_cache as _invalidate_schema_cache,
)

# Without an explicit config, app loggers fall back to logging's lastResort
# handler which drops everything below WARNING — every INFO-level
# instrumentation line in the codebase was invisible. Configure once at the
# entrypoint; respect a host process that already installed handlers.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=os.environ.get("AUGHOR_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )

logger = logging.getLogger(__name__)

# The context-propagating default executor (installed at startup, torn down at
# shutdown) — see _install_context_executor.
_CTX_EXECUTOR = None


@asynccontextmanager
async def _lifespan(app: "FastAPI"):
    """Application lifespan — replaces the deprecated @app.on_event('startup')
    handlers. The startup steps run in the SAME order they were previously
    registered (FastAPI ran on_event handlers sequentially in registration
    order); each step is individually fault-isolated inside its own helper, so
    one failing step never aborts boot. Forward-references the step helpers
    defined below — they are resolved at call time (startup), not import time.
    """
    # ── Startup ────────────────────────────────────────────────────────────────
    # First: make contextvars (current job id + per-run metering) cross the
    # run_in_executor boundary, before any startup step dispatches into a thread.
    _install_context_executor()
    await _kernel_journal_boot()
    await _setup_samples()
    # Orphaned investigations are recovered (salvaged, not blanket-failed) inside
    # _kernel_boot_recovery — AFTER kernel boot_recovery sweeps the job table, so
    # the salvage jobs we submit aren't themselves caught by that sweep.
    await _purge_legacy_canvases()
    await _ensure_default_org()
    await _ensure_default_workspace()
    await _validate_connections()
    await _start_explorers()
    await _start_ontology_refresh_loop()
    await _seed_playbook()
    await _start_monitor_scheduler()
    await _start_brief_scheduler()
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────────
    # Background loops (supervisor, ontology refresh) are cancelled by event-loop
    # teardown, and the kernel's boot_recovery fails any job orphaned by the stop
    # on the next start. The one explicit teardown is the context executor.
    global _CTX_EXECUTOR
    if _CTX_EXECUTOR is not None:
        try:
            _CTX_EXECUTOR.shutdown(wait=False)
        except Exception as exc:
            logger.warning("context executor shutdown failed (non-fatal): %s", exc)
        _CTX_EXECUTOR = None


app = FastAPI(title="Aughor API", lifespan=_lifespan)

# ── CORS ──────────────────────────────────────────────────────────────────────
_cors_raw = os.environ.get("AUGHOR_CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")
_cors_origins: list[str] = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────────
_API_KEY = os.environ.get("AUGHOR_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def _require_auth(key: str | None = Security(_api_key_header)) -> None:
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── Startup steps (run by _lifespan above, in this order) ──────────────────────

def _install_context_executor() -> None:
    """Make ``loop.run_in_executor(None, …)`` propagate contextvars into worker
    threads, by installing a :class:`ContextThreadPoolExecutor` as the loop's
    default executor. The stdlib default does not copy context, so the current
    job id and the per-run metering accumulator would otherwise be invisible to
    the LLM/SQL calls (which all run in the executor). Strict more-correct; the
    only observable change is that executor-run work now sees the right context."""
    global _CTX_EXECUTOR
    try:
        from aughor.kernel.concurrency import ContextThreadPoolExecutor
        _CTX_EXECUTOR = ContextThreadPoolExecutor(thread_name_prefix="aughor-exec")
        asyncio.get_event_loop().set_default_executor(_CTX_EXECUTOR)
    except Exception as exc:
        logger.warning("context executor install failed (non-fatal): %s", exc)


async def _kernel_journal_boot() -> None:
    # The boot event anchors the journal's timeline: restarts become visible,
    # and "jobs running before this seq with no later transition" is exactly
    # the orphan set K1's supervisor will resume.
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("api.started")
    except Exception as exc:
        logger.warning("Kernel ledger unavailable at boot: %s", exc)


async def _setup_samples() -> None:
    # Run synchronous DB seeding off the event loop so startup returns instantly.
    loop = asyncio.get_event_loop()
    try:
        from aughor.samples.setup import ensure_samples_db

        def _seed_and_validate() -> None:
            path = ensure_samples_db()
            # Validate the seed actually holds tables — a half-written/corrupt seed
            # is the root of the "sample data missing" class and must be loud.
            import duckdb
            conn = duckdb.connect(str(path), read_only=True)
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM duckdb_tables() WHERE internal = false"
                ).fetchone()[0]
            finally:
                conn.close()
            if n == 0:
                logger.error("Samples DB validation FAILED: %s exists but has 0 tables", path)
            else:
                logger.info("Samples DB validated: %d tables at %s", n, path)

        await loop.run_in_executor(None, _seed_and_validate)
    except Exception as exc:
        logger.warning("Samples DB setup failed (non-fatal): %s", exc)


async def _purge_legacy_canvases() -> None:
    # Auto-generated per-connection Canvases are no longer created. Purge any
    # left over from older installs so only user-created Canvases remain.
    try:
        from aughor.canvas.store import delete_legacy_canvases
        removed = delete_legacy_canvases()
        if removed:
            logger.info("Canvas cleanup: removed %d auto-generated Canvas(es)", removed)
    except Exception as exc:
        logger.warning("Canvas cleanup failed (non-fatal): %s", exc)


async def _ensure_default_org() -> None:
    try:
        from aughor.org import ensure_default_org
        ensure_default_org()
    except Exception as exc:
        logger.warning("Org bootstrap failed (non-fatal): %s", exc)


async def _ensure_default_workspace() -> None:
    try:
        from aughor.workspace.store import ensure_default_workspace
        ensure_default_workspace()
    except Exception as exc:
        logger.warning("Workspace migration failed (non-fatal): %s", exc)


async def _validate_connections() -> None:
    from aughor.db.registry import _db, _decrypt
    try:
        with _db() as conn:
            rows = conn.execute("SELECT id, name, dsn_enc FROM connections").fetchall()
        bad = []
        for row in rows:
            try:
                _decrypt(row["dsn_enc"])
            except Exception:
                bad.append(f"{row['name']} (id={row['id']})")
        if bad:
            logger.error(
                "⚠️  CONNECTION KEY MISMATCH — %d connection(s) cannot be decrypted: %s",
                len(bad), ", ".join(bad),
            )
        else:
            logger.info("Connection key check passed — %d connection(s) OK", len(rows))
    except Exception as exc:
        logger.warning("Could not run connection key check: %s", exc)


async def _boot_canvas_explorers() -> None:
    """Background task: resume canvas explorers from saved state (via the ONE
    kernel-supervised spawn path)."""
    from aughor.canvas.store import get_canvas
    from aughor.explorer.store import canvas_has_state
    from aughor.routers._shared import spawn_explorer

    canvas_states = [
        p.stem.replace("exploration_canvas_", "")
        for p in Path("data").glob("exploration_canvas_*.json")
        if p.exists()
    ]
    for canvas_id in canvas_states:
        if not canvas_has_state(canvas_id):
            continue
        try:
            canvas = get_canvas(canvas_id)
            if not canvas or not canvas.scopes:
                continue
            res = await spawn_explorer(
                canvas.scopes[0].connection_id,
                canvas_id=canvas_id,
                tables_filter=canvas.scopes[0].tables or None,
            )
            if res["ok"]:
                logger.info("Canvas explorer resumed for canvas %s (job %s)", canvas_id, res["job_id"])
            else:
                logger.info("Canvas explorer skipped for %s — %s", canvas_id, res["reason"])
        except Exception as exc:
            logger.warning("Could not resume canvas explorer for %s: %s", canvas_id, exc)


async def _kernel_boot_recovery() -> None:
    """K1: fail every job orphaned by the previous process, then resume the
    explorations whose checkpoints show unfinished work — the restart-amnesia
    fix (an exploration at phase 5 no longer dies silently with the server)."""
    from aughor.kernel.jobs import kernel
    from aughor.routers._shared import spawn_explorer

    try:
        resumable = kernel().boot_recovery()
    except Exception as exc:
        logger.warning("Kernel boot recovery failed: %s", exc)
        return
    for job in resumable:
        conn_id, canvas_id = job.get("conn_id"), job.get("canvas_id")
        if not conn_id:
            continue
        try:
            if canvas_id:
                # Canvas explorers are also resumed by _boot_canvas_explorers;
                # the spawn guard + idempotency key make double-resume a no-op.
                from aughor.explorer.store import canvas_has_state
                if not canvas_has_state(canvas_id):
                    continue
                tables = (job.get("payload") or {}).get("tables_filter")
                res = await spawn_explorer(conn_id, canvas_id=canvas_id, tables_filter=tables)
            else:
                from aughor.explorer import store as _expl_store
                phase = (_expl_store.load(conn_id) or {}).get("phase", "pending")
                if phase in ("complete", "failed"):
                    continue
                res = await spawn_explorer(
                    conn_id,
                    domain_intel_only=bool((job.get("payload") or {}).get("domain_intel_only")),
                )
            logger.info(
                "Boot recovery: exploration %s for %s — %s",
                "resumed" if res["ok"] else "NOT resumed",
                canvas_id or conn_id,
                res["job_id"] or res["reason"],
            )
        except Exception as exc:
            logger.warning("Boot recovery: could not resume %s: %s", canvas_id or conn_id, exc)

    # Investigations: recover orphaned 'running' rows AFTER the job sweep above, so
    # the salvage jobs we submit here aren't swept as orphans themselves.
    await _recover_orphaned_investigations()


async def _recover_orphaned_investigations() -> None:
    """Crash recovery for investigations. A 'running' row at boot was orphaned by
    the previous process; instead of blanket-failing it, submit a supervised salvage
    job that reads its LangGraph checkpoint and recovers a partial report from the
    evidence gathered before the crash — completing it where possible, failing it
    only when there is nothing to salvage. The 60-min supervisor sweep backstops any
    that don't get a job."""
    try:
        from aughor.db.history import list_orphaned_running_investigations
        from aughor.routers.investigations import salvage_orphaned_investigation
        from aughor.kernel.jobs import kernel
        orphans = list_orphaned_running_investigations()
        for inv in orphans:
            await kernel().submit(
                "investigation_salvage",
                (lambda inv=inv: salvage_orphaned_investigation(
                    inv["id"], inv["connection_id"], inv.get("canvas_id"), inv["question"])),
                conn_id=inv["connection_id"], canvas_id=inv.get("canvas_id"),
            )
        if orphans:
            logger.info("Boot recovery: submitted salvage jobs for %d orphaned investigation(s)", len(orphans))
    except Exception as exc:
        logger.warning("Orphaned-investigation recovery failed (non-fatal): %s", exc)


async def _start_explorers() -> None:
    """Kernel-supervised background work boot:
    1. fail jobs orphaned by the previous process + resume unfinished explorations,
    2. resume canvas explorers from saved state,
    3. start the supervisor (stale-job sweep, paused-explorer backstop,
       periodic stale-investigation sweep — replaces the old boot-only sweep).
    Fresh connection explorations still start manually (POST /exploration/{id}/start).
    """
    from aughor.kernel.jobs import kernel

    async def _boot() -> None:
        await _kernel_boot_recovery()
        await _boot_canvas_explorers()

    asyncio.create_task(_boot(), name="kernel-boot")
    asyncio.create_task(kernel().supervise_forever(), name="kernel-supervisor")


async def _ontology_refresh_loop() -> None:
    from datetime import datetime, timezone
    from aughor.ontology.store import load_latest_ontology, invalidate as invalidate_ontology

    while True:
        await asyncio.sleep(3600)
        try:
            for conn_info in list_connections():
                conn_id = conn_info["id"]
                settings = get_connection_settings(conn_id)
                refresh_hours = settings.get("ontology_refresh_hours")
                if not refresh_hours:
                    continue
                try:
                    graph = load_latest_ontology(conn_id)
                    if graph is not None:
                        generated_at = datetime.fromisoformat(graph.generated_at)
                        age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
                        if age_hours < refresh_hours:
                            continue
                    invalidate_ontology(conn_id)
                    db = open_connection_for(conn_id)
                    db.get_schema()
                    db.close()
                    logger.info("Ontology refreshed for connection %s", conn_id)
                except Exception as exc:
                    logger.warning("Ontology refresh failed for %s: %s", conn_id, exc)
        except Exception as exc:
            logger.warning("Ontology refresh loop error: %s", exc)


async def _start_ontology_refresh_loop() -> None:
    asyncio.create_task(_ontology_refresh_loop(), name="ontology-refresh")


async def _seed_playbook() -> None:
    try:
        from aughor.playbook.builder import seed_from_kb, activate_seeded
        n = seed_from_kb()
        if n:
            logger.info("Playbook seeded with %d entries from KB.", n)
        # Activate the seed by default — promote KB-seeded drafts to 'active' so
        # they're live playbook items the user can keep / modify / remove, not
        # dormant drafts. Idempotent; never touches user-deprecated entries.
        promoted = activate_seeded()
        if promoted:
            logger.info("Activated %d seeded playbook entries.", promoted)
    except Exception as exc:
        # Non-fatal: a missing/empty KB just means no seeded playbook. Surface it
        # at warning level like every other startup step rather than swallowing.
        logger.warning("Playbook seeding failed (non-fatal): %s", exc)


async def _start_monitor_scheduler() -> None:
    """Load enabled monitors and start the APScheduler background thread."""
    try:
        from aughor.monitors.scheduler import start as _start_monitors
        _start_monitors()
    except Exception as exc:
        logger.warning("Monitor scheduler startup failed (non-fatal): %s", exc)


async def _start_brief_scheduler() -> None:
    """Load enabled brief subscriptions and start their delivery scheduler."""
    try:
        from aughor.briefs.scheduler import start as _start_briefs
        _start_briefs()
    except Exception as exc:
        logger.warning("Brief scheduler startup failed (non-fatal): %s", exc)


# ── Router registration ───────────────────────────────────────────────────────

from aughor.routers import (  # noqa: E402
    system,
    agents,
    investigations,
    canvas,
    workspace,
    connections,
    exploration,
    catalog,
    ontology,
    knowledge,
    metrics,
    actions,
    security,
    query,
    monitors,
    semantic,
    briefs,
    events,
    jobs,
    llm,
    profile,
    orgsettings,
)

app.include_router(system.router)
app.include_router(investigations.router)
app.include_router(canvas.router)
app.include_router(workspace.router)
app.include_router(connections.router)
app.include_router(exploration.router)
app.include_router(catalog.router)
app.include_router(ontology.router)
app.include_router(knowledge.router)
app.include_router(metrics.router)
app.include_router(actions.router)
app.include_router(security.router)
app.include_router(query.router)
app.include_router(monitors.router)
app.include_router(semantic.router)
app.include_router(briefs.router)
app.include_router(events.router)
app.include_router(jobs.router)
app.include_router(agents.router)
app.include_router(llm.router)
app.include_router(profile.router)
app.include_router(orgsettings.router)
