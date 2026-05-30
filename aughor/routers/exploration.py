"""Background schema exploration — connection and canvas scoped."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.db.connection import open_connection_for
from aughor.explorer.models import ExplorationPhase
from aughor.routers._shared import (
    explorers as _explorers,
    explorer_tasks as _explorer_tasks,
    canvas_explorers as _canvas_explorers,
    canvas_explorer_tasks as _canvas_explorer_tasks,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["exploration"])


class RetryQueryRequest(BaseModel):
    sql: str
    error: str
    hint: str = ""
    domain: str = ""


# ── Connection-scoped ─────────────────────────────────────────────────────────

@router.get("/exploration/{conn_id}/status")
def get_exploration_status(conn_id: str):
    from aughor.explorer import store as _expl_store
    explorer = _explorers.get(conn_id)
    if explorer:
        return explorer._status.to_dict()
    state = _expl_store.load(conn_id)
    return {
        "connection_id": conn_id,
        "phase": state.get("phase", "pending"),
        "paused": False,
        "tables_total": 0, "columns_total": 0, "joins_total": 0,
        "null_meanings_resolved": len(state.get("null_meanings", {})),
        "joins_verified": sum(1 for j in state.get("join_verifications", []) if j.get("verified")),
        "lifecycles_mapped": len(state.get("lifecycle_maps", {})),
        "distributions_profiled": len(state.get("distributions", {})),
        "insights_found": len(state.get("insights", [])),
        "queries_executed": 0, "facts_discovered": 0,
        "started_at": None, "completed_at": None, "error": None,
    }


@router.get("/exploration/{conn_id}/findings")
def get_exploration_findings(conn_id: str):
    from aughor.explorer import store as _expl_store
    state = _expl_store.load(conn_id)
    distributions = state.get("distributions", {})

    if distributions and any("col_type" not in v for v in distributions.values()):
        try:
            cache_path = Path(__file__).parent.parent.parent / "data" / "schema_profiles.json"
            if cache_path.exists():
                cache = json.loads(cache_path.read_text())
                col_dtype_map: dict[str, str] = {}
                for cache_key, entry in cache.items():
                    if cache_key.startswith(f"{conn_id}:"):
                        for flat_key, col_data in entry.get("columns", {}).items():
                            if isinstance(col_data, dict) and "dtype" in col_data:
                                col_dtype_map[flat_key] = col_data["dtype"]
                if col_dtype_map:
                    for key, dist in distributions.items():
                        if "col_type" not in dist:
                            table, col = key.split(":", 1)
                            dist["col_type"] = col_dtype_map.get(f"{table}.{col}")
        except Exception:
            pass

    return {
        "connection_id": conn_id,
        "phase": state.get("phase", "pending"),
        "null_meanings": state.get("null_meanings", {}),
        "join_verifications": state.get("join_verifications", []),
        "lifecycle_maps": state.get("lifecycle_maps", {}),
        "distributions": distributions,
        "insights": state.get("insights", []),
    }


@router.get("/exploration/{conn_id}/domains")
def get_domain_insights(conn_id: str):
    from aughor.explorer import store as _expl_store
    state = _expl_store.load(conn_id)
    budgets  = state.get("domain_budgets", {})
    coverage = state.get("domain_coverage", {})
    by_domain = _expl_store.get_domain_insights(conn_id)
    result = {}
    for domain, insights in by_domain.items():
        result[domain] = {
            "insights": insights,
            "queries_used": budgets.get(domain, 0),
            "budget_cap": budgets.get(f"{domain}__cap", 15),
            "angles_covered": coverage.get(domain, []),
        }
    return result


@router.post("/exploration/{conn_id}/domains/{domain}/extend")
async def extend_domain_budget(conn_id: str, domain: str):
    from aughor.explorer import store as _expl_store
    new_cap = _expl_store.extend_domain_budget(conn_id, domain, extra=5)
    existing = _explorers.get(conn_id)
    if existing is not None and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        existing._state.setdefault("domain_budgets", {})[f"{domain}__cap"] = new_cap
    else:
        try:
            from aughor.explorer.agent import SchemaExplorer
            db = open_connection_for(conn_id)
            explorer = SchemaExplorer(conn_id, db)
            _explorers[conn_id] = explorer
            _explorer_tasks[conn_id] = asyncio.create_task(
                explorer.explore(domain_intel_only=True), name=f"explorer-{conn_id}-extend"
            )
        except Exception as exc:
            logger.warning("Could not restart explorer for %s after extend: %s", conn_id, exc)
    return {"ok": True, "domain": domain, "extra": 5}


@router.get("/exploration/{conn_id}/episodes")
def get_exploration_episodes(conn_id: str, phase: str = "", limit: int = 300):
    p = Path("data") / f"episodes_{conn_id}.jsonl"
    if not p.exists():
        return []
    entries = []
    for line in p.read_text().strip().splitlines():
        try:
            e = json.loads(line)
            if not phase or e.get("phase") == phase:
                entries.append(e)
        except Exception:
            pass
    return entries[-limit:]


@router.post("/exploration/{conn_id}/stop")
def stop_exploration(conn_id: str):
    explorer = _explorers.get(conn_id)
    if explorer:
        explorer.stop()
        explorer._status.paused = True
    task = _explorer_tasks.get(conn_id)
    if task and not task.done():
        task.cancel()
    return {"ok": True, "stopped": explorer is not None}


@router.post("/exploration/{conn_id}/resume")
async def resume_exploration(conn_id: str):
    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "already running"}
    try:
        from aughor.explorer.agent import SchemaExplorer
        db = open_connection_for(conn_id)
        explorer = SchemaExplorer(conn_id, db)
        _explorers[conn_id] = explorer
        _explorer_tasks[conn_id] = asyncio.create_task(explorer.explore(), name=f"explorer-{conn_id}-resume")
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exploration/{conn_id}/restart")
async def restart_exploration(conn_id: str):
    explorer = _explorers.get(conn_id)
    if explorer:
        explorer.stop()
    task = _explorer_tasks.get(conn_id)
    if task and not task.done():
        task.cancel()
    for fname in (f"exploration_{conn_id}.json", f"episodes_{conn_id}.jsonl"):
        p = Path("data") / fname
        if p.exists():
            p.unlink()
    try:
        from aughor.explorer.agent import SchemaExplorer
        db = open_connection_for(conn_id)
        new_explorer = SchemaExplorer(conn_id, db)
        _explorers[conn_id] = new_explorer
        _explorer_tasks[conn_id] = asyncio.create_task(new_explorer.explore(), name=f"explorer-{conn_id}-restart")
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/exploration/{conn_id}/retry-query")
async def retry_query(conn_id: str, body: RetryQueryRequest):
    from aughor.sql.writer import SqlWriter
    try:
        db = open_connection_for(conn_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")
    writer = SqlWriter(db)
    fix = writer.fix(body.sql, body.error, hint=body.hint, max_retries=2)
    if not fix.ok:
        raise HTTPException(status_code=422, detail=f"LLM correction failed: {fix.final_error}")
    try:
        result = db.execute("__retry__", fix.sql)
        if result.error:
            return {"ok": False, "corrected_sql": fix.sql, "explanation": fix.explanation, "error": result.error, "rows": [], "columns": []}
        return {
            "ok": True, "corrected_sql": fix.sql, "explanation": fix.explanation,
            "rows": [[str(c) for c in r] for r in (result.rows or [])[:50]],
            "columns": result.columns or [], "row_count": result.row_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {e}")


# ── Canvas-scoped ─────────────────────────────────────────────────────────────

@router.get("/exploration/canvas/{canvas_id}/status")
def get_canvas_exploration_status(canvas_id: str):
    from aughor.explorer import store as _expl_store
    from aughor.canvas.store import get_canvas
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    explorer = _canvas_explorers.get(canvas_id)
    if explorer:
        return explorer._status.to_dict()
    state = _expl_store.load_canvas(canvas_id)
    conn_id = canvas.scopes[0].connection_id if canvas.scopes else ""
    return {
        "connection_id": conn_id, "canvas_id": canvas_id,
        "phase": state.get("phase", "pending"), "paused": False,
        "tables_total": 0, "columns_total": 0, "joins_total": 0,
        "null_meanings_resolved": len(state.get("null_meanings", {})),
        "joins_verified": sum(1 for j in state.get("join_verifications", []) if j.get("verified")),
        "lifecycles_mapped": len(state.get("lifecycle_maps", {})),
        "distributions_profiled": len(state.get("distributions", {})),
        "insights_found": len(state.get("insights", [])),
        "queries_executed": 0, "facts_discovered": 0,
        "started_at": None, "completed_at": None, "error": None,
    }


@router.get("/exploration/canvas/{canvas_id}/findings")
def get_canvas_exploration_findings(canvas_id: str):
    from aughor.explorer import store as _expl_store
    from aughor.canvas.store import get_canvas
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    state = _expl_store.load_canvas(canvas_id)
    return {
        "connection_id": canvas.scopes[0].connection_id if canvas.scopes else "",
        "canvas_id": canvas_id, "phase": state.get("phase", "pending"),
        "null_meanings": state.get("null_meanings", {}),
        "join_verifications": state.get("join_verifications", []),
        "lifecycle_maps": state.get("lifecycle_maps", {}),
        "distributions": state.get("distributions", {}),
        "insights": state.get("insights", []),
    }


@router.get("/exploration/canvas/{canvas_id}/domains")
def get_canvas_domain_insights(canvas_id: str):
    from aughor.explorer import store as _expl_store
    from aughor.canvas.store import get_canvas
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    state = _expl_store.load_canvas(canvas_id)
    budgets  = state.get("domain_budgets", {})
    coverage = state.get("domain_coverage", {})
    by_domain = _expl_store.get_domain_insights_canvas(canvas_id)
    return {
        domain: {
            "insights": insights,
            "queries_used": budgets.get(domain, 0),
            "budget_cap": budgets.get(f"{domain}__cap", 15),
            "angles_covered": coverage.get(domain, []),
        }
        for domain, insights in by_domain.items()
    }


@router.get("/exploration/canvas/{canvas_id}/episodes")
def get_canvas_exploration_episodes(canvas_id: str, phase: str = "", limit: int = 300):
    from aughor.canvas.store import get_canvas
    if not get_canvas(canvas_id):
        raise HTTPException(status_code=404, detail="Canvas not found")
    p = Path("data") / f"episodes_canvas_{canvas_id}.jsonl"
    if not p.exists():
        return []
    entries = []
    for line in p.read_text().strip().splitlines():
        try:
            e = json.loads(line)
            if not phase or e.get("phase") == phase:
                entries.append(e)
        except Exception:
            pass
    return entries[-limit:]


@router.post("/exploration/canvas/{canvas_id}/resume")
async def resume_canvas_exploration(canvas_id: str):
    from aughor.canvas.store import get_canvas
    from aughor.explorer.agent import SchemaExplorer
    canvas = get_canvas(canvas_id)
    if not canvas or not canvas.scopes:
        raise HTTPException(status_code=404, detail="Canvas not found")
    conn_id = canvas.scopes[0].connection_id
    tables  = canvas.scopes[0].tables or None
    existing = _canvas_explorers.get(canvas_id)
    if existing and not existing._stopped:
        existing.resume()
        return {"status": "resumed"}
    try:
        db = open_connection_for(conn_id)
        explorer = SchemaExplorer(conn_id, db, canvas_id=canvas_id, tables_filter=tables)
        _canvas_explorers[canvas_id] = explorer
        _canvas_explorer_tasks[canvas_id] = asyncio.create_task(explorer.explore(), name=f"canvas-explorer-{canvas_id}")
        return {"status": "started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/exploration/canvas/{canvas_id}/stop")
def stop_canvas_exploration(canvas_id: str):
    explorer = _canvas_explorers.get(canvas_id)
    if not explorer:
        raise HTTPException(status_code=404, detail="No canvas explorer running")
    explorer.pause()
    return {"status": "paused"}


@router.post("/exploration/canvas/{canvas_id}/restart")
async def restart_canvas_exploration(canvas_id: str):
    from aughor.canvas.store import get_canvas
    from aughor.explorer.agent import SchemaExplorer
    from aughor.explorer.store import save_canvas, _empty
    canvas = get_canvas(canvas_id)
    if not canvas or not canvas.scopes:
        raise HTTPException(status_code=404, detail="Canvas not found")
    conn_id = canvas.scopes[0].connection_id
    tables  = canvas.scopes[0].tables or None
    old = _canvas_explorers.pop(canvas_id, None)
    if old:
        old.stop()
    old_task = _canvas_explorer_tasks.pop(canvas_id, None)
    if old_task:
        old_task.cancel()
    save_canvas(canvas_id, _empty())
    ep_path = Path("data") / f"episodes_canvas_{canvas_id}.jsonl"
    if ep_path.exists():
        ep_path.unlink()
    try:
        db = open_connection_for(conn_id)
        explorer = SchemaExplorer(conn_id, db, canvas_id=canvas_id, tables_filter=tables)
        _canvas_explorers[canvas_id] = explorer
        _canvas_explorer_tasks[canvas_id] = asyncio.create_task(explorer.explore(), name=f"canvas-explorer-{canvas_id}")
        return {"status": "restarted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/exploration/canvas/{canvas_id}/domains/{domain}/extend")
def extend_canvas_domain_budget(canvas_id: str, domain: str, extra: int = 5):
    from aughor.canvas.store import get_canvas
    if not get_canvas(canvas_id):
        raise HTTPException(status_code=404, detail="Canvas not found")
    from aughor.explorer.store import extend_domain_budget_canvas
    new_cap = extend_domain_budget_canvas(canvas_id, domain, extra)
    explorer = _canvas_explorers.get(canvas_id)
    if explorer and hasattr(explorer, "_state"):
        explorer._state.setdefault("domain_budgets", {})[f"{domain}__cap"] = new_cap
    return {"domain": domain, "new_cap": new_cap}


@router.post("/exploration/canvas/{canvas_id}/insights/{insight_id}/promote")
def promote_canvas_insight(canvas_id: str, insight_id: str):
    from aughor.canvas.store import get_canvas
    if not get_canvas(canvas_id):
        raise HTTPException(status_code=404, detail="Canvas not found")
    from aughor.explorer.store import promote_insight
    if not promote_insight(canvas_id, insight_id):
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"insight_id": insight_id, "promoted": True}
