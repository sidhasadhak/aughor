"""Background schema exploration — connection and canvas scoped."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.db.connection import open_connection_for
from aughor.explorer.models import ExplorationPhase, elapsed_seconds
from aughor.routers._shared import (
    explorers as _explorers,
    explorer_tasks as _explorer_tasks,
    canvas_explorers as _canvas_explorers,
    canvas_explorer_tasks as _canvas_explorer_tasks,
    kickoff_exploration,
    spawn_explorer,
)

logger = logging.getLogger(__name__)
import re as _re

_SQL_TABLE_RE = _re.compile(
    r"(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO|DELETE\s+FROM)\s+(?:\"?\w+\"?\.)?\"?(\w+)\"?(?:\s+(?:AS\s+)?\w+)?(?=\s|$|[,;])",
    _re.IGNORECASE,
)


def _tables_from_sql(sql: str) -> set[str]:
    return {m.group(1) for m in _SQL_TABLE_RE.finditer(sql) if m.group(1)}


def _schema_table_set(conn_id: str, schema: str | None) -> set[str] | None:
    """The bare, lowercased table names in ``schema`` for ``conn_id`` — or None when it
    can't be determined (the caller then skips filtering: over-inclusion is safe, wrong
    exclusion is not)."""
    if not schema:
        return None
    try:
        db = open_connection_for(conn_id)
    except Exception:
        return None
    try:
        safe_schema = schema.replace("'", "''")
        # information_schema.tables is standard SQL — same query for every dialect.
        res = db.execute(
            "__schema_filter__",
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = '{safe_schema}' AND table_type = 'BASE TABLE'",
        )
        return {str(r[0]).lower() for r in res.rows}
    except Exception:
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _insight_refs(ins: dict) -> set[str]:
    """Lowercased table names an insight references — SQL tables plus declared entities
    (also snake-cased, so CamelCase entity names match snake_case tables)."""
    sql_tables = {t.lower() for t in _tables_from_sql(ins.get("sql", ""))}
    entities = {e.lower() for e in ins.get("entities_involved", [])}
    snake = {_re.sub(r'(?<!^)(?=[A-Z])', '_', e).lower() for e in entities}
    return sql_tables | entities | snake


def _filter_by_schema(domain_data: dict, conn_id: str, schema: str | None) -> dict:
    """Filter domain insights to only those referencing tables in the given schema."""
    tables_in_schema = _schema_table_set(conn_id, schema)
    if tables_in_schema is None:
        return domain_data
    filtered = {}
    for domain, data in domain_data.items():
        insights = data if isinstance(data, list) else data.get("insights", [])
        kept = [ins for ins in insights if _insight_refs(ins) & tables_in_schema]
        if kept:
            filtered[domain] = kept if isinstance(data, list) else {**data, "insights": kept}
    return filtered


def _filter_findings_by_schema(findings: dict, conn_id: str, schema: str | None) -> dict:
    """Scope an exploration-findings payload to one schema's tables so the Domains layer
    follows the shared schema selector. Sections are keyed by table (``lifecycle_maps``)
    or ``"table:column"`` (``null_meanings``, ``distributions``); insights reference
    tables via their SQL/entities. Returns ``findings`` unchanged when the schema's table
    set can't be determined (over-inclusion beats wrong exclusion)."""
    tset = _schema_table_set(conn_id, schema)
    if tset is None:
        return findings

    def _tbl(key: str) -> str:
        return key.split(":", 1)[0].split(".")[-1].lower()

    out = dict(findings)
    out["null_meanings"] = {k: v for k, v in (findings.get("null_meanings") or {}).items() if _tbl(k) in tset}
    out["distributions"] = {k: v for k, v in (findings.get("distributions") or {}).items() if _tbl(k) in tset}
    out["lifecycle_maps"] = {k: v for k, v in (findings.get("lifecycle_maps") or {}).items() if k.split(".")[-1].lower() in tset}
    out["insights"] = [i for i in (findings.get("insights") or []) if _insight_refs(i) & tset]
    return out

from aughor.licensing import Capability, gate

router = APIRouter(tags=["exploration"])


class RetryQueryRequest(BaseModel):
    sql: str
    error: str
    hint: str = ""
    domain: str = ""


class FixEpisodeRequest(BaseModel):
    """One errored episode to repair-and-save."""
    sql: str
    error: str
    think: str = ""
    phase: str = "domain_intel"
    hint: str = ""
    canvas_id: str = ""


class FixAllRequest(BaseModel):
    """A batch of errored episodes to repair — the client passes exactly the episodes
    currently VISIBLE under its filter, so the server only fixes those and stops. It
    never generates new questions or starts the explorer."""
    episodes: list[FixEpisodeRequest]
    hint: str = ""
    canvas_id: str = ""


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
        "first_insight_at": state.get("first_insight_at"),
        "first_insight_seconds": elapsed_seconds(state.get("started_at"), state.get("first_insight_at")),
        "completed_at": state.get("completed_at"),
        "error": None,
        "domain_intel_skipped": state.get("domain_intel_skipped", False),
        "domain_intel_note": state.get("domain_intel_note"),
    }


@router.get("/exploration/kpi/time-to-first-insight")
def time_to_first_insight_kpi(limit: int = 200):
    """B-6 product KPI: the connect→first-insight funnel, measured.

    Reads the `exploration.first_insight` milestone events the explorer stamps
    (one per run, on the first insight from any phase) and reports the
    distribution of elapsed seconds — so "how fast does a fresh connection
    deliver its first finding" is a query, not a vibe. Mirrors
    /metrics/enforcement-rate: a measured rate the product is held to."""
    from aughor.kernel.ledger import Ledger
    events = Ledger.default().events(kind="exploration.first_insight", limit=min(int(limit), 500))
    samples = [
        {
            "conn_id": e.get("conn_id"),
            "at": e.get("at"),
            "elapsed_seconds": (e.get("payload") or {}).get("elapsed_seconds"),
            "phase": (e.get("payload") or {}).get("phase"),
        }
        for e in events
    ]
    durations = sorted(s["elapsed_seconds"] for s in samples if isinstance(s["elapsed_seconds"], (int, float)))

    def _pct(p: float) -> float | None:
        if not durations:
            return None
        idx = min(len(durations) - 1, int(round(p * (len(durations) - 1))))
        return round(durations[idx], 1)

    return {
        "count": len(durations),
        "p50_seconds": _pct(0.5),
        "p90_seconds": _pct(0.9),
        "min_seconds": durations[0] if durations else None,
        "max_seconds": durations[-1] if durations else None,
        "samples": samples[:50],   # newest-first, for inspection
    }


@router.get("/exploration/{conn_id}/findings")
def get_exploration_findings(conn_id: str, schema: str | None = None):
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

    result = {
        "connection_id": conn_id,
        "phase": state.get("phase", "pending"),
        "null_meanings": state.get("null_meanings", {}),
        "join_verifications": state.get("join_verifications", []),
        "lifecycle_maps": state.get("lifecycle_maps", {}),
        "distributions": distributions,
        "insights": state.get("insights", []),
    }
    # Scope to the shared schema selector (Domains layer) when one is supplied.
    if schema:
        result = _filter_findings_by_schema(result, conn_id, schema)
    return result


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
    # Scope the cache key per schema so a schema-filtered briefing never returns the
    # connection-wide (or another schema's) cached narrative — the AI Synthesis card
    # was staying stale on schema change because every schema shared one cache key.
    result = get_briefing(
        connection_id=conn_id,
        domain_data=by_domain,
        patterns=patterns,
        force_refresh=refresh,
        scope_key=f"{conn_id}:{schema}" if schema else conn_id,
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


@router.post("/exploration/{conn_id}/domains/{domain}/extend", dependencies=[gate(Capability.AUTO_EXPLORATION)])
async def extend_domain_budget(conn_id: str, domain: str):
    from aughor.explorer import store as _expl_store
    new_cap = _expl_store.extend_domain_budget(conn_id, domain, extra=5)
    existing = _explorers.get(conn_id)
    if existing is not None and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        existing._state.setdefault("domain_budgets", {})[f"{domain}__cap"] = new_cap
    else:
        res = await spawn_explorer(conn_id, domain_intel_only=True)
        if not res["ok"]:
            logger.warning("Could not restart explorer for %s after extend: %s", conn_id, res["reason"])
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


@router.post("/exploration/{conn_id}/resume", dependencies=[gate(Capability.AUTO_EXPLORATION)])
async def resume_exploration(conn_id: str):
    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "already running"}

    res = await spawn_explorer(conn_id)
    if not res["ok"]:
        logger.warning("Resume: failed for %s — %s", conn_id, res["reason"])
    return {"ok": res["ok"], **({"reason": res["reason"]} if res["reason"] else {})}


@router.post("/exploration/{conn_id}/restart", dependencies=[gate(Capability.AUTO_EXPLORATION)])
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
    # Drop the stopped explorer or spawn_explorer's already-running guard refuses.
    _explorers.pop(conn_id, None)
    _explorer_tasks.pop(conn_id, None)
    res = await spawn_explorer(conn_id)
    if not res["ok"]:
        raise HTTPException(status_code=500, detail=res["reason"] or "could not start explorer")
    return {"ok": True}


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


@router.post("/exploration/{conn_id}/fix-episode", dependencies=[gate(Capability.FIX_SAVE)])
def fix_episode(conn_id: str, body: FixEpisodeRequest):
    """Repair an errored episode and, on a successful run, SAVE it: heal the episode and
    (for domain-intelligence queries) store a finding through the same Phase-8 guards.
    Unlike /retry-query this persists; it never generates new questions."""
    from aughor.explorer.fix_persist import persist_fixed_finding
    try:
        return persist_fixed_finding(
            conn_id, original_sql=body.sql, error=body.error,
            think=body.think, phase=body.phase, hint=body.hint,
            canvas_id=body.canvas_id or None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fix-and-save failed: {e}")


@router.post("/exploration/{conn_id}/fix-all", dependencies=[gate(Capability.FIX_SAVE)])
def fix_all(conn_id: str, body: FixAllRequest):
    """Repair-and-save every episode in the provided list — and ONLY those. The client
    sends exactly the errored episodes visible under its current filter, so a date filter
    (e.g. 'yesterday') naturally scopes the batch. This never starts the explorer or
    generates fresh questions; it repairs the given errors and stops."""
    from aughor.explorer.fix_persist import persist_fixed_finding
    results = []
    for ep in body.episodes[:200]:   # hard cap — a repair batch, not a crawl
        try:
            r = persist_fixed_finding(
                conn_id, original_sql=ep.sql, error=ep.error,
                think=ep.think, phase=ep.phase, hint=body.hint or ep.hint,
                canvas_id=body.canvas_id or None,
            )
        except Exception as e:
            r = {"ok": False, "stored": False, "error": str(e)}
        results.append({"sql": ep.sql[:100], **r})
    summary = {
        "total":   len(results),
        "fixed":   sum(1 for r in results if r.get("ok")),
        "saved":   sum(1 for r in results if r.get("stored")),
        "flagged": sum(1 for r in results if r.get("stored") and (r.get("insight") or {}).get("unverified")),
        "failed":  sum(1 for r in results if not r.get("ok")),
    }
    return {"summary": summary, "results": results}


# ── Explorer control ─────────────────────────────────────────────────────────

@router.post("/exploration/{conn_id}/start", dependencies=[gate(Capability.AUTO_EXPLORATION)])
async def start_exploration(conn_id: str):
    """Start a fresh explorer run if none is active."""
    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "already running", "phase": existing.status.phase.value}

    # Same background open+test+explore path used by connection auto-onboarding.
    started = kickoff_exploration(conn_id)
    return {"ok": started}


@router.post("/exploration/{conn_id}/trigger-intel", dependencies=[gate(Capability.DOMAIN_INTEL)])
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

    res = await spawn_explorer(conn_id, domain_intel_only=True)
    if not res["ok"]:
        logger.warning("Trigger-intel: failed for %s — %s", conn_id, res["reason"])
    return {"ok": res["ok"], **({"reason": res["reason"]} if res["reason"] else {})}


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


@router.post("/exploration/canvas/{canvas_id}/resume", dependencies=[gate(Capability.AUTO_EXPLORATION)])
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
    _canvas_explorers.pop(canvas_id, None)   # stopped husk would trip the spawn guard
    res = await spawn_explorer(conn_id, canvas_id=canvas_id, tables_filter=tables)
    if not res["ok"]:
        raise HTTPException(status_code=500, detail=res["reason"] or "could not start canvas explorer")
    return {"status": "started"}


@router.post("/exploration/canvas/{canvas_id}/stop")
def stop_canvas_exploration(canvas_id: str):
    explorer = _canvas_explorers.get(canvas_id)
    if not explorer:
        raise HTTPException(status_code=404, detail="No canvas explorer running")
    explorer.pause()
    return {"status": "paused"}


@router.post("/exploration/canvas/{canvas_id}/restart", dependencies=[gate(Capability.AUTO_EXPLORATION)])
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
    res = await spawn_explorer(conn_id, canvas_id=canvas_id, tables_filter=tables)
    if not res["ok"]:
        raise HTTPException(status_code=500, detail=res["reason"] or "could not restart canvas explorer")
    return {"status": "restarted"}


@router.post("/exploration/canvas/{canvas_id}/trigger-intel", dependencies=[gate(Capability.DOMAIN_INTEL)])
async def trigger_canvas_domain_intelligence(canvas_id: str):
    """Run only Phase 8 (domain intelligence) for a Canvas if phases 3-7 are already
    complete — the canvas-scoped counterpart to the connection `trigger-intel`. Drives
    the *canvas* explorer (scoped to the canvas's curated tables), not the connection.
    spawn_explorer guards the already-running case."""
    from aughor.explorer import store as _expl_store
    from aughor.canvas.store import get_canvas
    canvas = get_canvas(canvas_id)
    if not canvas or not canvas.scopes:
        raise HTTPException(status_code=404, detail="Canvas not found")
    state = _expl_store.load_canvas(canvas_id)
    phase = state.get("phase", "pending")
    if phase not in ("complete", ExplorationPhase.COMPLETE.value):
        return {"ok": False, "reason": f"phases 3-7 not complete (current: {phase}) — run /resume or /restart first"}

    conn_id = canvas.scopes[0].connection_id
    tables  = canvas.scopes[0].tables or None
    res = await spawn_explorer(conn_id, canvas_id=canvas_id, tables_filter=tables, domain_intel_only=True)
    if not res["ok"]:
        logger.warning("Canvas trigger-intel: failed for %s — %s", canvas_id, res["reason"])
    return {"ok": res["ok"], **({"reason": res["reason"]} if res["reason"] else {})}


@router.post("/exploration/canvas/{canvas_id}/domains/{domain}/extend", dependencies=[gate(Capability.AUTO_EXPLORATION)])
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


class DismissRequest(BaseModel):
    reason: str = ""


@router.post("/exploration/{connection_id}/insights/{insight_id}/dismiss")
def dismiss_connection_insight(connection_id: str, insight_id: str, req: DismissRequest):
    """Dismiss a connection-scoped finding with a reason. Flags it invalid (hidden
    from intel, kept in the store, reversible) and logs the reason for the guard
    backlog — wrong/stale findings shouldn't need a hand-edited JSON file."""
    from aughor.explorer.store import dismiss_insight_conn
    insight = dismiss_insight_conn(connection_id, insight_id, req.reason)
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"insight_id": insight_id, "dismissed": True}


@router.get("/exploration/{connection_id}/insights/{insight_id}/receipt")
def get_insight_receipt(connection_id: str, insight_id: str):
    """K3 Trust Receipt — the versioned finding artifact + its provenance edges
    (source SQL, input tables, guards) + the kernel job that computed it. One
    query over the ledger answers 'why should I trust this number'. Findings
    persisted before K3 have no artifact yet — they gain one on the next
    explore/refresh (404 until then, by design)."""
    from aughor.kernel.ledger import Ledger
    rec = Ledger.default().receipt(f"insight:{connection_id}:{insight_id}")
    if rec is None:
        raise HTTPException(status_code=404, detail="No receipt — finding predates provenance tracking; re-explore to generate one")
    return rec


@router.post("/exploration/canvas/{canvas_id}/insights/{insight_id}/dismiss")
def dismiss_canvas_insight(canvas_id: str, insight_id: str, req: DismissRequest):
    from aughor.canvas.store import get_canvas
    if not get_canvas(canvas_id):
        raise HTTPException(status_code=404, detail="Canvas not found")
    from aughor.explorer.store import dismiss_insight_canvas
    insight = dismiss_insight_canvas(canvas_id, insight_id, req.reason)
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"insight_id": insight_id, "dismissed": True}
