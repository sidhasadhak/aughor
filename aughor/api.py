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

from fastapi import Depends, FastAPI, HTTPException, Request, Security

from aughor.db.paths import state_dir
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from aughor.db.connection import open_connection_for
from aughor.db.registry import list_connections, get_connection_settings

# Shared mutable state — imported here so startup events can populate the dicts

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
    # First of all: plug the Agent into the Platform's registries (purge hooks,
    # schema annotators, …) so the platform's seams carry the agent's intelligence
    # on the live path. Must precede any request handling. Idempotent + fault-isolated.
    await _register_agent_plugins()
    # Then: make contextvars (current job id + per-run metering) cross the
    # run_in_executor boundary, before any startup step dispatches into a thread.
    _install_context_executor()
    await _kernel_journal_boot()
    await _setup_samples()
    # Orphaned investigations are recovered (salvaged, not blanket-failed) inside
    # _kernel_boot_recovery — AFTER kernel boot_recovery sweeps the job table, so
    # the salvage jobs we submit aren't themselves caught by that sweep.
    await _purge_legacy_canvases()
    await _ensure_default_org()
    await _migrate_upload_storage()
    await _ensure_default_workspace()
    await _sync_metastore()
    await _validate_connections()
    await _start_explorers()
    await _start_ontology_refresh_loop()
    await _start_continuous_exploration_loop()
    await _seed_playbook()
    await _start_monitor_scheduler()
    await _start_brief_scheduler()
    await _start_automation_heartbeat()
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


# ── Auth ──────────────────────────────────────────────────────────────────────
# Optional shared-secret gate. OFF by default (AUGHOR_API_KEY unset) so the local
# single-user tool needs no token. When the env var is set, every request must
# carry it as `X-Api-Key` (the MCP client already sends it that way) — the in-app
# authorization model is capability-gating (aughor.licensing.gate); this is the
# coarse front-door lock for when the server is exposed beyond localhost.
_API_KEY = os.environ.get("AUGHOR_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)
# Liveness + API docs stay open so health probes and the schema browser work
# even when the key is set.
_AUTH_EXEMPT = ("/health", "/docs", "/redoc", "/openapi.json")


def _require_auth(request: Request, key: str | None = Security(_api_key_header)) -> None:
    """App-wide request gate: the shared-key front door PLUS (flag-gated) identity.

    Resolves the principal onto ``request.state`` (which reliably reaches handlers)
    and 401s when identity is required but absent. The org *contextvar* binding is
    done by ``_OrgContextMiddleware`` below — a dependency's ``set_org_id`` runs in a
    throwaway worker context and does NOT reach the handler, so ``current_org_id()``
    would stay DEFAULT (verified). With ``AUGHOR_REQUIRE_IDENTITY`` unset (default)
    this is behaviourally identical to the old key-only check.
    """
    exempt = any(request.url.path.startswith(p) for p in _AUTH_EXEMPT)
    # 1. Shared-secret front door (unchanged): coarse lock when exposed beyond localhost.
    if _API_KEY and not exempt and key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # 2. Identity (SEC-01). Off by default; exempt paths (health/docs) never require it.
    from aughor.security.authz import require_identity_enabled, resolve_principal
    if exempt or not require_identity_enabled():
        return
    principal = resolve_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="identity required (missing X-Aughor-Org)")
    request.state.principal = principal


class _OrgContextMiddleware:
    """Bind ``current_org_id()`` for the whole request (SEC-01 / DATA-06).

    A pure-ASGI middleware sets the contextvar in the REQUEST's context, which
    ``run_in_threadpool`` copies into sync-handler workers — so ``current_org_id()``
    is correct in every handler (sync or async). A generator *dependency* can't do
    this (its context is discarded before the handler runs). No-op when identity is
    off or no principal is presented (``_require_auth`` still 401s a missing one)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from aughor.security.authz import require_identity_enabled, resolve_principal
        if not require_identity_enabled():
            return await self.app(scope, receive, send)
        from starlette.requests import Request as _Req
        principal = resolve_principal(_Req(scope))
        if principal is None:
            return await self.app(scope, receive, send)
        from aughor.org.context import reset_org_id, reset_user_id, set_org_id, set_user_id
        token = set_org_id(principal.org_id)
        user_token = set_user_id(principal.user_id)   # for the RBAC row-policy injector (Rec 7)
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                reset_user_id(user_token)
                reset_org_id(token)
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "org contextvar reset (best-effort)", counter="org.reset")


from aughor.rbac.deps import enforce_rbac  # noqa: E402

app = FastAPI(title="Aughor API", lifespan=_lifespan,
              dependencies=[Depends(_require_auth), Depends(enforce_rbac)])
app.add_middleware(_OrgContextMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Defaults cover the dev web UI (:3000/:3001) and the prod-preview server (:3210);
# AUGHOR_CORS_ORIGINS overrides the whole list.
_cors_raw = os.environ.get(
    "AUGHOR_CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:3210",
)
_cors_origins: list[str] = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler (SEC-06) ───────────────────────────────────────────
# ~50 endpoints did `raise HTTPException(500, detail=str(e))`, leaking internal
# exception text (and there was no catch-all). This handler catches only genuinely
# UNHANDLED exceptions — Starlette routes HTTPException/validation errors to their
# own handlers first, so intended 4xx/5xx responses are untouched. Clients get a
# stable `{error, request_id}`; the traceback stays server-side, correlatable by id.
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: "Request", exc: Exception):
    import uuid as _uuid

    from fastapi.responses import JSONResponse
    request_id = str(_uuid.uuid4())
    logger.exception("Unhandled error [%s] on %s %s", request_id, request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error", "request_id": request_id})



# ── Startup steps (run by _lifespan above, in this order) ──────────────────────

async def _register_agent_plugins() -> None:
    """Register the Agent's contributions into the Platform's extension registries
    (purge hooks, schema annotators, …). The platform never imports the agent; this
    is the one explicit wiring call that plugs the agent in. Non-fatal: if it fails,
    the platform degrades to its raw, agent-free behaviour rather than failing boot."""
    try:
        from aughor.agent.bootstrap import register_agent_plugins
        register_agent_plugins()
    except Exception as exc:
        logger.warning("Agent plugin registration failed (non-fatal): %s", exc)


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
        loop = asyncio.get_running_loop()
        loop.set_default_executor(_CTX_EXECUTOR)
        # WP-7: record the loop so scheduler threads (monitor/brief cron) can bridge a
        # supervised kernel job onto it via run_coroutine_threadsafe.
        from aughor.kernel.jobs import set_main_loop
        set_main_loop(loop)
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
    loop = asyncio.get_running_loop()
    try:
        from aughor.samples.setup import ensure_fixture_db, ensure_samples_db

        def _seed_and_validate() -> None:
            # Guarantee the 'fixture' builtin connection has an openable DB — it's
            # gitignored and otherwise never created (a fresh install had a broken
            # "Fixture DB (demo)" connection).
            ensure_fixture_db()
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


async def _migrate_upload_storage() -> None:
    # Tenant-path the on-disk uploads ({conn}/ → {org}/{conn}/) before any connector
    # is constructed. One-time, idempotent, crash-safe. Must run AFTER the default
    # org exists and BEFORE connections are validated / explorers start.
    try:
        from aughor.platform import migrate_uploads_to_org_layout
        migrate_uploads_to_org_layout()
    except Exception as exc:
        logger.warning("Upload storage migration failed (non-fatal): %s", exc)


async def _ensure_default_workspace() -> None:
    try:
        from aughor.workspace.store import ensure_default_workspace
        ensure_default_workspace()
    except Exception as exc:
        logger.warning("Workspace migration failed (non-fatal): %s", exc)


async def _sync_metastore() -> None:
    # Derive catalogs (← connections) + grants (← workspace membership). Must run
    # AFTER the default workspace exists so memberships are present. Non-fatal; the
    # metastore isn't on the live data path yet (the gate still uses connection_ids).
    try:
        from aughor.metastore import sync_metastore_from_registry
        sync_metastore_from_registry()
    except Exception as exc:
        logger.warning("Metastore sync failed (non-fatal): %s", exc)


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
        for p in state_dir().glob("exploration_canvas_*.json")
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
                # Aggregate phase — the bare state reads 'pending' forever on a
                # multi-schema connection, so recovery kept re-spawning explorers
                # for explorations that had already completed per schema.
                phase = (_expl_store.load_aggregate(conn_id) or {}).get("phase", "pending")
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


async def _continuous_exploration_loop() -> None:
    """WP-6 — periodically re-arm the Scout so exploration doesn't die after the first
    pass. Gated by the `explorer.continuous` flag (default off = a pure sleep, byte-
    identical). The per-connection decision + governance/licensing gates live in
    `explorer.continuous.run_continuous_tick`; this is just the heartbeat.
    """
    from aughor.explorer.continuous import _TICK_SECONDS, run_continuous_tick
    from aughor.kernel.flags import flag_enabled

    while True:
        await asyncio.sleep(_TICK_SECONDS)
        if not flag_enabled("explorer.continuous"):
            continue
        try:
            # run_continuous_tick does its blocking decision off the loop internally, then
            # schedules spawns on it — so it's awaited here, not executor-wrapped.
            n = await run_continuous_tick()
            if n:
                logger.info("Continuous exploration re-armed %d connection(s)", n)
        except Exception as exc:
            logger.warning("Continuous exploration tick error: %s", exc)


async def _start_continuous_exploration_loop() -> None:
    asyncio.create_task(_continuous_exploration_loop(), name="continuous-exploration")


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


async def _start_automation_heartbeat() -> None:
    """Start the Wave-A condition→effect heartbeat. Self-gates on `automations.engine`:
    with the flag off it returns without scheduling anything."""
    try:
        from aughor.automations.scheduler import start as _start_automations
        _start_automations()
    except Exception as exc:
        logger.warning("Automation heartbeat startup failed (non-fatal): %s", exc)


# ── Router registration ───────────────────────────────────────────────────────

from aughor.routers import (
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
    metastore,
    volumes,
    verify,
    approvals,
    learning,
    roles as roles_router,
    packs as packs_router,
    receipt as receipt_router,
    agui,
    dashboard,
    evals,
    kinetic,
    automations,
)

app.include_router(system.router)
app.include_router(investigations.router)
app.include_router(canvas.router)
app.include_router(workspace.router)
app.include_router(connections.router)
app.include_router(exploration.router)
app.include_router(catalog.router)
app.include_router(ontology.router)
app.include_router(kinetic.router)
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
app.include_router(metastore.router)
app.include_router(approvals.router)
app.include_router(metastore.grants_router)
app.include_router(volumes.router)
app.include_router(profile.router)
app.include_router(orgsettings.router)
app.include_router(verify.router)
app.include_router(learning.router)
app.include_router(packs_router.router)
app.include_router(roles_router.router)
app.include_router(receipt_router.router)
app.include_router(agui.router)  # AG-UI protocol seam (CK-1); endpoint self-gates on flag `agui.endpoint`
app.include_router(dashboard.router)  # briefing-cockpit — user-authored dashboard cards (Slice 0)
app.include_router(evals.router)  # Wave E3 — eval suites/runs (gated on eval.suite)
app.include_router(automations.router)  # Wave A — condition→effect (self-gates on automations.engine)
