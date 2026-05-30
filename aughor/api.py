"""FastAPI backend — application entrypoint, middleware, startup events, router registration."""
from __future__ import annotations

import asyncio
import logging
import os
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

logger = logging.getLogger(__name__)

app = FastAPI(title="Aughor API")

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


# ── Startup events ────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _setup_samples() -> None:
    try:
        from aughor.samples.setup import ensure_samples_db
        ensure_samples_db()
    except Exception as exc:
        logger.warning("Samples DB setup failed (non-fatal): %s", exc)


@app.on_event("startup")
async def _migrate_canvases() -> None:
    try:
        from aughor.canvas.store import migrate_connections_to_legacy_canvases
        created = migrate_connections_to_legacy_canvases()
        if created:
            logger.info("Canvas migration: created %d legacy Canvas(es)", created)
    except Exception as exc:
        logger.warning("Canvas migration failed (non-fatal): %s", exc)


@app.on_event("startup")
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


@app.on_event("startup")
async def _start_explorers() -> None:
    from aughor.explorer.agent import SchemaExplorer
    from pathlib import Path as _Path

    def _store_path(conn_id: str) -> _Path:
        return _Path("data") / f"exploration_{conn_id}.json"

    for conn_info in list_connections():
        conn_id = conn_info["id"]
        if not _store_path(conn_id).exists():
            continue
        try:
            db = open_connection_for(conn_id)
            ok, msg = db.test()
            if not ok:
                db.close()
                continue
            explorer = SchemaExplorer(conn_id, db)
            _explorers[conn_id] = explorer
            task = asyncio.create_task(explorer.explore(), name=f"explorer-{conn_id}")
            _explorer_tasks[conn_id] = task
            logger.info("Explorer resumed for connection %s", conn_id)
        except Exception as exc:
            logger.warning("Could not resume explorer for %s: %s", conn_id, exc)

    from aughor.canvas.store import get_canvas
    from aughor.explorer.store import canvas_has_state
    from pathlib import Path as _Path2
    canvas_states = [
        p.stem.replace("exploration_canvas_", "")
        for p in _Path2("data").glob("exploration_canvas_*.json")
        if p.exists()
    ]
    for canvas_id in canvas_states:
        if not canvas_has_state(canvas_id):
            continue
        try:
            canvas = get_canvas(canvas_id)
            if not canvas or not canvas.scopes:
                continue
            conn_id = canvas.scopes[0].connection_id
            tables = canvas.scopes[0].tables
            db = open_connection_for(conn_id)
            ok, msg = db.test()
            if not ok:
                db.close()
                continue
            explorer = SchemaExplorer(conn_id, db, canvas_id=canvas_id, tables_filter=tables or None)
            _canvas_explorers[canvas_id] = explorer
            task = asyncio.create_task(explorer.explore(), name=f"canvas-explorer-{canvas_id}")
            _canvas_explorer_tasks[canvas_id] = task
            logger.info("Canvas explorer resumed for canvas %s", canvas_id)
        except Exception as exc:
            logger.warning("Could not resume canvas explorer for %s: %s", canvas_id, exc)


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


@app.on_event("startup")
async def _start_ontology_refresh_loop() -> None:
    asyncio.create_task(_ontology_refresh_loop(), name="ontology-refresh")


@app.on_event("startup")
async def _seed_playbook() -> None:
    try:
        from aughor.playbook.builder import seed_from_kb
        n = seed_from_kb()
        if n:
            logger.info("Playbook seeded with %d entries from KB.", n)
    except Exception:
        pass


@app.on_event("startup")
async def _start_monitor_scheduler() -> None:
    """Load enabled monitors and start the APScheduler background thread."""
    try:
        from aughor.monitors.scheduler import start as _start_monitors
        _start_monitors()
    except Exception as exc:
        logger.warning("Monitor scheduler startup failed (non-fatal): %s", exc)


# ── Router registration ───────────────────────────────────────────────────────

from aughor.routers import (  # noqa: E402
    system,
    investigations,
    canvas,
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
)

app.include_router(system.router)
app.include_router(investigations.router)
app.include_router(canvas.router)
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
