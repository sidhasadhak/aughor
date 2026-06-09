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
    kickoff_exploration,
)

logger = logging.getLogger(__name__)
import re as _re

_SQL_TABLE_RE = _re.compile(
    r"(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO|DELETE\s+FROM)\s+(?:\"?\w+\"?\.)?\"?(\w+)\"?(?:\s+(?:AS\s+)?\w+)?(?=\s|$|[,;])",
    _re.IGNORECASE,
)


def _tables_from_sql(sql: str) -> set[str]:
    return {m.group(1) for m in _SQL_TABLE_RE.finditer(sql) if m.group(1)}


def _filter_by_schema(domain_data: dict, conn_id: str, schema: str | None) -> dict:
    """Filter domain insights to only those referencing tables in the given schema."""
    if not schema:
        return domain_data
    try:
        db = open_connection_for(conn_id)
    except Exception:
        return domain_data
    try:
        safe_schema = schema.replace("'", "''")
        # information_schema.tables is standard SQL — same query for every dialect.
        res = db.execute(
            "__schema_filter__",
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{safe_schema}' AND table_type = 'BASE TABLE'",
        )
        tables_in_schema = {str(r[0]) for r in res.rows}
    except Exception:
        db.close()
        return domain_data
    finally:
        try:
            db.close()
        except Exception:
            pass

    filtered = {}
    for domain, data in domain_data.items():
        insights = data if isinstance(data, list) else data.get("insights", [])
        filtered_insights = []
        for ins in insights:
            sql_tables = _tables_from_sql(ins.get("sql", ""))
            entities = {e.lower() for e in ins.get("entities_involved", [])}
            # snake_case entities for broader matching
            snake_entities = {_re.sub(r'(?<!^)(?=[A-Z])', '_', e).lower() for e in entities}
            all_refs = sql_tables | snake_entities | entities
            if all_refs & tables_in_schema:
                filtered_insights.append(ins)
        if filtered_insights:
            if isinstance(data, list):
                filtered[domain] = filtered_insights
            else:
                filtered[domain] = {**data, "insights": filtered_insights}
    return filtered

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
    # Restore counters persisted at completion time (survive server restarts)
    return {
        "connection_id": conn_id,
        "phase": state.get("phase", "pending"),
        "paused": False,
        "tables_total":   state.get("tables_total", 0),
        "columns_total":  state.get("columns_total", 0),
        "joins_total":    len(state.get("join_verifications", [])),
        "null_meanings_resolved":  len(state.get("null_meanings", {})),
        "joins_verified":          sum(1 for j in state.get("join_verifications", []) if j.get("verified")),
        "lifecycles_mapped":       len(state.get("lifecycle_maps", {})),
        "distributions_profiled":  len(state.get("distributions", {})),
        "insights_found":          len(state.get("insights", [])),
        "queries_executed": state.get("queries_executed", 0),
        "facts_discovered": len(state.get("insights", [])) + len(state.get("lifecycle_maps", {})),
        "started_at":   state.get("started_at"),
        "completed_at": state.get("completed_at"),
        "error": None,
        "domain_intel_skipped": state.get("domain_intel_skipped", False),
        "domain_intel_note": state.get("domain_intel_note"),
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
def get_domain_insights(conn_id: str, schema: str | None = None):
    from aughor.explorer import store as _expl_store
    state = _expl_store.load(conn_id)
    budgets  = state.get("domain_budgets", {})
    coverage = state.get("domain_coverage", {})
    by_domain = _expl_store.get_domain_insights(conn_id)
    if schema:
        by_domain = _filter_by_schema(by_domain, conn_id, schema)
    result = {}
    for domain, insights in by_domain.items():
        result[domain] = {
            "insights": insights,
            "queries_used": budgets.get(domain, 0),
            "budget_cap": budgets.get(f"{domain}__cap", 15),
            "angles_covered": coverage.get(domain, []),
        }
    return result


@router.get("/exploration/{conn_id}/patterns")
def get_connection_patterns(conn_id: str, refresh: bool = False, schema: str | None = None):
    """Return extracted patterns from domain intelligence for this connection."""
    from aughor.explorer import store as _expl_store
    from aughor.knowledge.patterns import get_patterns
    by_domain = _expl_store.get_domain_insights(conn_id)
    if schema:
        by_domain = _filter_by_schema(by_domain, conn_id, schema)
    patterns = get_patterns(conn_id, by_domain, force_refresh=refresh)
    return {"patterns": patterns, "count": len(patterns)}


@router.get("/exploration/canvas/{canvas_id}/patterns")
def get_canvas_patterns(canvas_id: str, refresh: bool = False):
    """Return patterns extracted from a Canvas's curated-table domain intelligence —
    canvas-scoped counterpart to the connection patterns endpoint (Hub scope consistency)."""
    from aughor.explorer import store as _expl_store
    from aughor.knowledge.patterns import get_patterns
    from aughor.canvas.store import get_canvas

    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    by_domain = _expl_store.get_domain_insights_canvas(canvas_id)
    conn_id = canvas.primary_connection_id or ""
    patterns = get_patterns(conn_id, by_domain, force_refresh=refresh)
    return {"patterns": patterns, "count": len(patterns)}


@router.post("/exploration/{conn_id}/briefing")
def generate_briefing(conn_id: str, refresh: bool = False, schema: str | None = None):
    """Generate (or return cached) an LLM synthesis narrative for the connection."""
    from aughor.explorer import store as _expl_store
    from aughor.knowledge.patterns import get_patterns
    from aughor.knowledge.briefing import get_briefing

    by_domain = _expl_store.get_domain_insights(conn_id)
    if schema:
        by_domain = _filter_by_schema(by_domain, conn_id, schema)
    if not by_domain:
        return {
            "narrative": "",
            "headline_theme": "",
            "citations": [],
            "generated_at": None,
            "available": False,
        }

    patterns = get_patterns(conn_id, by_domain, force_refresh=False)
    macro = _expl_store.load(conn_id).get("macro_context")
    result = get_briefing(
        connection_id=conn_id,
        domain_data=by_domain,
        patterns=patterns,
        force_refresh=refresh,
        macro_context=macro,
    )
    return {**result, "macro_context": macro, "available": bool(result.get("narrative"))}


@router.post("/exploration/canvas/{canvas_id}/briefing")
def generate_canvas_briefing(canvas_id: str, refresh: bool = False):
    """Generate (or return cached) a briefing scoped to a Canvas's curated tables — so the
    brief reflects only the canvas's tables, not the whole connection (scope consistency:
    Domains is already canvas-scoped; this brings Briefing in line)."""
    from aughor.explorer import store as _expl_store
    from aughor.knowledge.patterns import get_patterns
    from aughor.knowledge.briefing import get_briefing
    from aughor.canvas.store import get_canvas

    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    by_domain = _expl_store.get_domain_insights_canvas(canvas_id)
    if not by_domain:
        return {
            "narrative": "",
            "headline_theme": "",
            "citations": [],
            "generated_at": None,
            "available": False,
        }

    conn_id = canvas.primary_connection_id or ""
    patterns = get_patterns(conn_id, by_domain, force_refresh=False)
    macro = _expl_store.load_canvas(canvas_id).get("macro_context")
    result = get_briefing(
        connection_id=conn_id,
        domain_data=by_domain,
        patterns=patterns,
        force_refresh=refresh,
        scope_key=f"canvas:{canvas_id}",
        macro_context=macro,
    )
    return {**result, "macro_context": macro, "available": bool(result.get("narrative"))}


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
            _t = asyncio.create_task(
                explorer.explore(domain_intel_only=True), name=f"explorer-{conn_id}-extend"
            )
            _t.add_done_callback(lambda _, k=conn_id: _explorer_tasks.pop(k, None))
            _explorer_tasks[conn_id] = _t
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

    async def _do_resume() -> None:
        loop = asyncio.get_running_loop()
        try:
            def _open_and_test():
                db = open_connection_for(conn_id)
                ok, msg = db.test()
                if not ok:
                    db.close()
                    return None, False, msg
                return db, True, msg

            db, ok, msg = await loop.run_in_executor(None, _open_and_test)
            if not ok or db is None:
                logger.warning("Resume: connection %s not ready — %s", conn_id, msg)
                return
            from aughor.explorer.agent import SchemaExplorer
            explorer = SchemaExplorer(conn_id, db)
            _explorers[conn_id] = explorer
            _t = asyncio.create_task(
                explorer.explore(), name=f"explorer-{conn_id}-resume"
            )
            _t.add_done_callback(lambda _, k=conn_id: _explorer_tasks.pop(k, None))
            _explorer_tasks[conn_id] = _t
            logger.info("Resume: explorer started for %s", conn_id)
        except Exception as exc:
            logger.warning("Resume: failed for %s — %s", conn_id, exc)

    asyncio.create_task(_do_resume(), name=f"resume-{conn_id}")
    return {"ok": True}


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
    # Also bust the profile cache so the profiler re-classifies all columns
    # with the latest semantic-type heuristics (e.g. geo/zip → key, not measure)
    try:
        from aughor.tools.profile_cache import invalidate as invalidate_profiles
        invalidate_profiles(conn_id)
    except Exception as _exc:
        logger.warning("Could not invalidate profile cache for %s: %s", conn_id, _exc)
    try:
        from aughor.explorer.agent import SchemaExplorer
        db = open_connection_for(conn_id)
        new_explorer = SchemaExplorer(conn_id, db)
        _explorers[conn_id] = new_explorer
        _t = asyncio.create_task(new_explorer.explore(), name=f"explorer-{conn_id}-restart")
        _t.add_done_callback(lambda _, k=conn_id: _explorer_tasks.pop(k, None))
        _explorer_tasks[conn_id] = _t
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


# ── Explorer control ─────────────────────────────────────────────────────────

@router.post("/exploration/{conn_id}/start")
async def start_exploration(conn_id: str):
    """Start a fresh explorer run if none is active."""
    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "already running", "phase": existing.status.phase.value}

    # Same background open+test+explore path used by connection auto-onboarding.
    started = kickoff_exploration(conn_id)
    return {"ok": started}


@router.post("/exploration/{conn_id}/trigger-intel")
async def trigger_domain_intelligence(conn_id: str):
    """Run only Phase 8 (domain intelligence) if phases 3-7 are already complete."""
    from aughor.explorer import store as _expl_store
    state = _expl_store.load(conn_id)
    phase = state.get("phase", "pending")
    if phase not in ("complete", ExplorationPhase.COMPLETE.value):
        return {"ok": False, "reason": f"phases 3-7 not complete (current: {phase}) — run /start or /restart first"}

    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "explorer already running", "phase": existing.status.phase.value}

    async def _do_intel() -> None:
        loop = asyncio.get_running_loop()
        try:
            def _open_and_test():
                db = open_connection_for(conn_id)
                ok, msg = db.test()
                if not ok:
                    db.close()
                    return None, False, msg
                return db, True, msg

            db, ok, msg = await loop.run_in_executor(None, _open_and_test)
            if not ok or db is None:
                logger.warning("Trigger-intel: connection %s not ready — %s", conn_id, msg)
                return
            from aughor.explorer.agent import SchemaExplorer
            explorer = SchemaExplorer(conn_id, db)
            _explorers[conn_id] = explorer
            _t = asyncio.create_task(
                explorer.explore(domain_intel_only=True), name=f"explorer-{conn_id}-intel"
            )
            _t.add_done_callback(lambda _, k=conn_id: _explorer_tasks.pop(k, None))
            _explorer_tasks[conn_id] = _t
            logger.info("Trigger-intel: domain intelligence started for %s", conn_id)
        except Exception as exc:
            logger.warning("Trigger-intel: failed for %s — %s", conn_id, exc)

    asyncio.create_task(_do_intel(), name=f"intel-{conn_id}")
    return {"ok": True}


@router.post("/exploration/{conn_id}/reset")
def reset_exploration(conn_id: str):
    """Clear exploration state without restarting. Use /restart to reset+start."""
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
        from aughor.tools.profile_cache import invalidate as invalidate_profiles
        invalidate_profiles(conn_id)
    except Exception:
        pass
    return {"ok": True, "reset": True}


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
        "domain_intel_skipped": state.get("domain_intel_skipped", False),
        "domain_intel_note": state.get("domain_intel_note"),
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
        _ct = asyncio.create_task(explorer.explore(), name=f"canvas-explorer-{canvas_id}")
        _ct.add_done_callback(lambda _, k=canvas_id: _canvas_explorer_tasks.pop(k, None))
        _canvas_explorer_tasks[canvas_id] = _ct
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
        _ct = asyncio.create_task(explorer.explore(), name=f"canvas-explorer-{canvas_id}")
        _ct.add_done_callback(lambda _, k=canvas_id: _canvas_explorer_tasks.pop(k, None))
        _canvas_explorer_tasks[canvas_id] = _ct
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
    from aughor.explorer.store import promote_insight, load_canvas
    if not promote_insight(canvas_id, insight_id):
        raise HTTPException(status_code=404, detail="Insight not found")

    # Push the full insight text into the org_intelligence Qdrant collection
    try:
        state = load_canvas(canvas_id)
        insight = next(
            (i for i in state.get("insights", []) if i.get("id") == insight_id),
            None,
        )
        if insight:
            from aughor.knowledge.org_intelligence import promote_to_org
            promote_to_org(
                insight_id=insight_id,
                text=insight.get("finding", ""),
                domain=insight.get("domain", ""),
                novelty=insight.get("novelty", 3),
                canvas_id=canvas_id,
                angle=insight.get("angle", ""),
            )
    except Exception:
        pass  # Qdrant unavailable — metadata flag is already set; non-critical

    return {"insight_id": insight_id, "promoted": True}


@router.post("/exploration/{connection_id}/insights/{insight_id}/promote")
def promote_connection_insight(connection_id: str, insight_id: str):
    """Promote a connection-scoped Briefing/Hub finding to org-wide intelligence.

    Counterpart to the canvas promote endpoint — connection-level findings (the
    default Briefing scope) had no promotion path until now.
    """
    from aughor.explorer.store import promote_insight_conn
    insight = promote_insight_conn(connection_id, insight_id)
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found")

    # Push the full insight text into the org_intelligence Qdrant collection.
    try:
        from aughor.knowledge.org_intelligence import promote_to_org
        promote_to_org(
            insight_id=insight_id,
            text=insight.get("finding", ""),
            domain=insight.get("domain", ""),
            novelty=insight.get("novelty", 3),
            canvas_id=f"conn:{connection_id}",
            angle=insight.get("angle", ""),
        )
    except Exception:
        pass  # Qdrant unavailable — metadata flag is already set; non-critical

    return {"insight_id": insight_id, "promoted": True}
