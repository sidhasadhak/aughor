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
    r"(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO|DELETE\s+FROM)\s+(?:\"?(\w+)\"?\.)?\"?(\w+)\"?(?:\s+(?:AS\s+)?\w+)?(?=\s|$|[,;])",
    _re.IGNORECASE,
)


def _tables_from_sql(sql: str) -> set[str]:
    """Lowercased table refs in a query — BOTH the bare name and, when the query qualifies
    it, the ``schema.table`` form. The qualified form is what lets schema isolation tell
    ``ecommerce.orders`` from ``missimi.orders`` (both schemas have an ``orders`` table)."""
    out: set[str] = set()
    for m in _SQL_TABLE_RE.finditer(sql):
        sch, tbl = m.group(1), m.group(2)
        if not tbl:
            continue
        out.add(tbl.lower())
        if sch:
            out.add(f"{sch.lower()}.{tbl.lower()}")
    return out


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


def _qualified_set(schema: str, bare: set[str]) -> set[str]:
    return {f"{schema.lower()}.{t}" for t in bare}


def _refs_in_schema(refs: set[str], bare: set[str], qual: set[str]) -> bool:
    """True if an insight's table refs belong to the schema. When the refs are SCHEMA-
    QUALIFIED (e.g. 'ecommerce.orders'), match the QUALIFIED set — so 'missimi.orders' is
    NOT mistaken for 'ecommerce.orders' (both schemas have an 'orders' table). Only when an
    insight is fully unqualified (single-schema connections) do we fall back to bare names."""
    quals = {r for r in refs if "." in r}
    if quals:
        return bool(quals & qual)
    return bool(refs & bare)


def _filter_by_schema(domain_data: dict, conn_id: str, schema: str | None) -> dict:
    """Filter domain insights to only those referencing tables in the given schema."""
    tables_in_schema = _schema_table_set(conn_id, schema)
    if tables_in_schema is None:
        return domain_data
    qual = _qualified_set(schema, tables_in_schema)
    filtered = {}
    for domain, data in domain_data.items():
        insights = data if isinstance(data, list) else data.get("insights", [])
        kept = [ins for ins in insights if _refs_in_schema(_insight_refs(ins), tables_in_schema, qual)]
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
    qual = _qualified_set(schema, tset)

    def _key_in_schema(key: str) -> bool:
        # keys are 'schema.table:col', 'schema.table', or bare 'table[:col]'. Match the
        # QUALIFIED form when present (so ecommerce.orders ≠ missimi.orders), else bare.
        kt = key.split(":", 1)[0].lower()
        return (kt in qual) if "." in kt else (kt in tset)

    out = dict(findings)
    out["null_meanings"] = {k: v for k, v in (findings.get("null_meanings") or {}).items() if _key_in_schema(k)}
    out["distributions"] = {k: v for k, v in (findings.get("distributions") or {}).items() if _key_in_schema(k)}
    out["lifecycle_maps"] = {k: v for k, v in (findings.get("lifecycle_maps") or {}).items() if _key_in_schema(k)}
    out["insights"] = [i for i in (findings.get("insights") or []) if _refs_in_schema(_insight_refs(i), tset, qual)]
    return out


def _store_key(conn_id: str, schema: str | None) -> str:
    """Resolve the exploration store key for a (connection, schema). When a per-schema run
    exists (its own state file), read THAT — it's natively isolated to the schema. Otherwise
    fall back to the connection-level state (the single-run case, then schema-FILTERED by the
    callers). Lets the same endpoints serve per-schema runs and the legacy connection run."""
    if schema:
        from pathlib import Path
        if (Path("data") / f"exploration_{conn_id}__{schema}.json").exists():
            return f"{conn_id}__{schema}"
    return conn_id


def _explorer_for(conn_id: str, schema: str | None):
    """The in-memory explorer for a (connection, schema) — per-schema run if present."""
    if schema and f"{conn_id}__{schema}" in _explorers:
        return _explorers.get(f"{conn_id}__{schema}")
    return _explorers.get(conn_id)


def _load_state(conn_id: str, schema: str | None) -> dict:
    """Exploration state for a (connection, schema): the per-schema run for a specific
    schema; the merged 'All schemas' aggregate when none is selected and the connection ran
    per-schema; else the connection-level state."""
    from aughor.explorer import store as _s
    if schema:
        return _s.load(_store_key(conn_id, schema))
    if _s.schema_run_keys(conn_id):
        return _s.load_aggregate(conn_id)
    return _s.load(conn_id)


def _domain_insights_for(conn_id: str, schema: str | None) -> dict:
    """by_domain insights for a (connection, schema) — per-schema, aggregate, or conn-level."""
    from aughor.explorer import store as _s
    if schema:
        return _s.get_domain_insights(_store_key(conn_id, schema))
    if _s.schema_run_keys(conn_id):
        return _s.get_aggregate_domain_insights(conn_id)
    return _s.get_domain_insights(conn_id)


def _needs_filter(conn_id: str, schema: str | None) -> bool:
    """A specific-schema view needs the qualified post-filter ONLY when it falls back to the
    connection-level state (the legacy single-run case). A per-schema run is already isolated;
    the aggregate is intentionally the union — neither is filtered."""
    return bool(schema) and _store_key(conn_id, schema) == conn_id

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
def get_exploration_status(conn_id: str, schema: str | None = None):
    from aughor.explorer import store as _expl_store
    explorer = _explorer_for(conn_id, schema)
    if explorer:
        return explorer._status.to_dict()
    state = _load_state(conn_id, schema)
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
        # {schema: phase} for the 'All schemas' aggregate — lets the UI show per-schema progress.
        "per_schema": state.get("per_schema"),
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
    state = _load_state(conn_id, schema)
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
    if _needs_filter(conn_id, schema):
        result = _filter_findings_by_schema(result, conn_id, schema)
    return result


def _annotate_insights_triage(by_domain: dict, profile) -> None:
    """Stamp each insight with `impact` (the briefing's ranking score) and `plausibility`
    (None | 'implausible' | 'confound'), reusing knowledge.triage so the insight CARDS rank
    and filter by the SAME authority as the brief — instead of re-implementing it in the
    frontend. Mutates in place; fail-open (a triage bug must not blank the cards)."""
    try:
        from aughor.knowledge.triage import impact_score, plausibility, north_star_tokens
        names = [getattr(m, "name", "") for m in (getattr(profile, "north_star_metrics", None) or [])]
        ns = north_star_tokens(names)
        for payload in by_domain.values():
            for ins in payload.get("insights", []):
                finding = ins.get("finding", "")
                ins["impact"] = round(
                    impact_score(finding, ins.get("novelty", 0), ins.get("confidence", 0), ns), 4)
                v = plausibility(finding, ins.get("sql", ""))
                ins["plausibility"] = None if v.ok else v.severity
    except Exception as _e:
        from aughor.kernel.errors import tolerate
        tolerate(_e, "domains: insight triage annotation", counter="domains.triage_annotation_failed")


@router.get("/exploration/{conn_id}/domains")
def get_domain_insights(conn_id: str, schema: str | None = None):
    from aughor.explorer import store as _expl_store
    state = _load_state(conn_id, schema)
    budgets  = state.get("domain_budgets", {})
    coverage = state.get("domain_coverage", {})
    by_domain = _domain_insights_for(conn_id, schema)
    if _needs_filter(conn_id, schema):
        by_domain = _filter_by_schema(by_domain, conn_id, schema)
    result = {}
    for domain, insights in by_domain.items():
        result[domain] = {
            "insights": insights,
            "queries_used": budgets.get(domain, 0),
            "budget_cap": budgets.get(f"{domain}__cap", 15),
            "angles_covered": coverage.get(domain, []),
        }
    # Impact-rank + plausibility for the cards (same authority as the brief).
    _annotate_insights_triage(result, _load_business_profile(conn_id, schema))
    return result


@router.get("/exploration/{conn_id}/patterns")
def get_connection_patterns(conn_id: str, refresh: bool = False, schema: str | None = None):
    """Return extracted patterns from domain intelligence for this connection."""
    from aughor.explorer import store as _expl_store
    from aughor.knowledge.patterns import get_patterns
    by_domain = _domain_insights_for(conn_id, schema)
    if _needs_filter(conn_id, schema):
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


def _load_business_profile(conn_id: str, schema: str | None):
    """The persisted BusinessProfile for (conn, schema), or None. Read-only (no infer) —
    the brief must not block on profile inference; without one it still gates + ranks, just
    without north-star weighting or currency correction. Fail-open."""
    try:
        from aughor.profile import store as _pstore
        return _pstore.load(conn_id, schema)
    except Exception:
        return None


def _metric_moves_provider(conn_id: str, profile):
    """A zero-arg callable that runs each north-star metric's chart_sql and returns the
    material time-trend MOVES as synthetic findings (the biggest KPI swings — margin
    47→34, AOV, repeat-rate — that no explorer finding carries). Returns None when there
    is no profile to draw metrics from. The callable opens ONE connection, is matcache-
    first, and fails open per metric — and get_briefing only invokes it on a cache miss."""
    if profile is None:
        return None
    metrics = getattr(profile, "north_star_metrics", None) or []
    if not metrics:
        return None
    from aughor.orgsettings import resolve_currency
    # Override-wins: an explicitly-set org currency is authoritative over the
    # per-connection inferred currency_code (else the inferred value, else USD).
    currency = resolve_currency(getattr(profile, "currency_code", None) or "")

    def _provider():
        from aughor.knowledge.metric_moves import compute_metric_moves
        from aughor.db.connection import open_connection_for
        from aughor.db.matcache import get_cached, put_cache
        try:
            db = open_connection_for(conn_id)
        except Exception:
            return []
        try:
            def run_sql(sql: str):
                cached = get_cached(conn_id, sql)
                if cached is not None:
                    return cached.columns, cached.rows, None
                res = db.execute("__brief_metric_move__", sql)
                err = getattr(res, "error", None)
                if not err:
                    try:
                        put_cache(conn_id, sql, res)
                    except Exception as _e:
                        from aughor.kernel.errors import tolerate
                        tolerate(_e, "metric-move: matcache put", counter="brief.metric_move.cache_put_failed")
                return res.columns, res.rows, err
            return compute_metric_moves(metrics, run_sql, currency)
        finally:
            try:
                db.close()
            except Exception as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, "metric-move: best-effort connection close", counter="brief.metric_move.close_failed")

    return _provider


@router.post("/exploration/{conn_id}/briefing")
def generate_briefing(conn_id: str, refresh: bool = False, schema: str | None = None,
                      workspace_id: str | None = None):
    """Generate (or return cached) an LLM synthesis narrative for the connection."""
    from aughor.explorer import store as _expl_store
    from aughor.knowledge.patterns import get_patterns
    from aughor.knowledge.briefing import get_briefing

    # RC5b — re-validate the findings that can headline this brief against LIVE data before
    # synthesizing. Re-runs the top-N by novelty and re-applies the same gate (verify_insight
    # + grounding); anything that no longer reproduces / is degenerate / implausible is
    # flagged invalid (reversible) so it's dropped from BOTH the headline and the synthesis.
    # Bounded + cached + fail-open. Skipped for a cached narrative (only matters when building).
    if refresh:
        try:
            from aughor.explorer.revalidate_live import revalidate_for_briefing
            revalidate_for_briefing(conn_id, schema)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "pre-brief re-validation is best-effort; the brief still builds from "
                     "stored findings", counter="briefing.revalidate")

    by_domain = _domain_insights_for(conn_id, schema)
    if _needs_filter(conn_id, schema):
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
    macro = _load_state(conn_id, schema).get("macro_context")
    # The BusinessProfile drives the brief's impact ranking (its north-star metrics) and
    # currency-correct figures (its currency_code) — load it for THIS schema.
    profile = _load_business_profile(conn_id, schema)
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
        profile=profile,
        metric_moves=_metric_moves_provider(conn_id, profile),
        workspace_id=workspace_id,
    )
    return {**result, "macro_context": macro, "available": bool(result.get("narrative"))}


@router.post("/exploration/canvas/{canvas_id}/briefing")
def generate_canvas_briefing(canvas_id: str, refresh: bool = False, workspace_id: str | None = None):
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
    profile = _load_business_profile(conn_id, getattr(canvas, "schema_name", None))
    result = get_briefing(
        connection_id=conn_id,
        domain_data=by_domain,
        patterns=patterns,
        force_refresh=refresh,
        scope_key=f"canvas:{canvas_id}",
        macro_context=macro,
        profile=profile,
        metric_moves=_metric_moves_provider(conn_id, profile),
        workspace_id=workspace_id,
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
    # Stop EVERY explorer bound to this connection — the connection-level run AND each per-schema
    # run ({conn}__{schema}) — so /stop works regardless of which key the run was spawned under
    # (trigger-intel/kickoff use the bare key for a single-schema connection; an explicit
    # ?schema= uses the per-schema key). Mirrors _purge_exploration_state's key resolution.
    keys = [k for k in list(_explorers.keys()) if k == conn_id or k.startswith(f"{conn_id}__")]
    stopped = 0
    for key in keys:
        e = _explorers.get(key)
        if e is not None:
            e.stop()
            e._status.paused = True
            stopped += 1
        t = _explorer_tasks.get(key)
        if t is not None and not t.done():
            t.cancel()
    return {"ok": True, "stopped": stopped > 0, "count": stopped}


@router.post("/exploration/{conn_id}/resume", dependencies=[gate(Capability.AUTO_EXPLORATION)])
async def resume_exploration(conn_id: str):
    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "already running"}

    res = await spawn_explorer(conn_id)
    if not res["ok"]:
        logger.warning("Resume: failed for %s — %s", conn_id, res["reason"])
    return {"ok": res["ok"], **({"reason": res["reason"]} if res["reason"] else {})}


def _purge_exploration_state(conn_id: str) -> list[str]:
    """Stop EVERY explorer bound to this connection — the connection-level run AND each
    per-schema run (``{conn}__{schema}``) — and delete ALL their state + episode files.
    `restart`/`reset` previously cleared only the connection-level files, so a multi-schema
    connection's stale per-schema findings (where the garbage lived) survived a 'restart'.
    Returns the deleted filenames. Also busts the profile cache so columns re-classify."""
    from aughor.kernel.errors import tolerate
    keys = [k for k in list(_explorers.keys()) if k == conn_id or k.startswith(f"{conn_id}__")]
    for key in keys:
        e = _explorers.get(key)
        if e is not None:
            try:
                e.stop()
            except Exception as exc:
                tolerate(exc, "explorer stop is best-effort during purge", counter="explorer.purge_stop")
        t = _explorer_tasks.get(key)
        if t is not None and not t.done():
            t.cancel()
        _explorers.pop(key, None)
        _explorer_tasks.pop(key, None)

    deleted: list[str] = []
    data = Path("data")
    for fname in (f"exploration_{conn_id}.json", f"episodes_{conn_id}.jsonl"):
        p = data / fname
        if p.exists():
            try:
                p.unlink()
                deleted.append(fname)
            except Exception as exc:
                tolerate(exc, f"could not delete {fname} during purge", counter="explorer.purge_unlink")
    for pat in (f"exploration_{conn_id}__*.json", f"episodes_{conn_id}__*.jsonl"):
        for p in data.glob(pat):
            try:
                p.unlink()
                deleted.append(p.name)
            except Exception as exc:
                tolerate(exc, f"could not delete {p.name} during purge", counter="explorer.purge_unlink")
    try:
        from aughor.tools.profile_cache import invalidate as invalidate_profiles
        invalidate_profiles(conn_id)
    except Exception as _exc:
        logger.warning("Could not invalidate profile cache for %s: %s", conn_id, _exc)
    return deleted


@router.post("/exploration/{conn_id}/restart", dependencies=[gate(Capability.AUTO_EXPLORATION)])
async def restart_exploration(conn_id: str):
    """Wipe ALL exploration state for the connection (connection-level + every per-schema run)
    and start fresh — fanning out one run PER schema for a multi-schema connection."""
    deleted = _purge_exploration_state(conn_id)
    started = kickoff_exploration(conn_id)   # fans out per schema (or connection-level if single)
    if not started:
        raise HTTPException(status_code=500, detail="could not start explorer after reset")
    return {"ok": True, "purged": deleted}


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
async def start_exploration(conn_id: str, schema: str | None = None):
    """Start a fresh explorer run if none is active. With ?schema=, explores just that
    schema; without it, a multi-schema connection fans out into one run per schema."""
    key = f"{conn_id}__{schema}" if schema else conn_id
    existing = _explorers.get(key)
    if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
        return {"ok": False, "reason": "already running", "phase": existing.status.phase.value}

    # Same background open+test+explore path used by connection auto-onboarding.
    started = kickoff_exploration(conn_id, schema)
    return {"ok": started}


@router.post("/exploration/{conn_id}/trigger-intel", dependencies=[gate(Capability.DOMAIN_INTEL)])
async def trigger_domain_intelligence(conn_id: str, schema: str | None = None):
    """Run only Phase 8 (domain intelligence) where phases 3-7 are already complete.

    A multi-schema connection's runs live under per-schema keys (``{conn}__{schema}``), so
    resolve the same schema targets ``start``/``kickoff`` use — reading the per-schema state,
    not the (empty) bare-connection state. ``?schema=`` targets one schema (Tier-0 #2)."""
    from aughor.explorer import store as _expl_store
    from aughor.routers._shared import schemas_of_connection

    if schema:
        targets: list[str | None] = [schema]
    else:
        _schemas = schemas_of_connection(conn_id)
        targets = list(_schemas) if len(_schemas) >= 2 else [None]

    results: list[dict] = []
    for sch in targets:
        key = f"{conn_id}__{sch}" if sch else conn_id
        state = _expl_store.load(key)
        phase = state.get("phase", "pending")
        # Foundation (phases 3-7) is done once a run reaches domain_intel — accept that as well as
        # 'complete', so an incremental Phase-8 run works after a budget-cancel left it at
        # domain_intel rather than 'complete' (the run still has its cached foundation).
        _foundation_done = (ExplorationPhase.DOMAIN_INTEL.value, ExplorationPhase.COMPLETE.value)
        if phase not in _foundation_done:
            results.append({"schema": sch, "ok": False,
                            "reason": f"phases 3-7 not complete (current: {phase}) — run /start or /restart first"})
            continue
        existing = _explorers.get(key)
        if existing and existing.status.phase not in (ExplorationPhase.COMPLETE, ExplorationPhase.FAILED):
            results.append({"schema": sch, "ok": False, "reason": "explorer already running"})
            continue
        res = await spawn_explorer(conn_id, schema_name=sch, domain_intel_only=True)
        if not res["ok"]:
            logger.warning("Trigger-intel: failed for %s (schema=%s) — %s", conn_id, sch, res["reason"])
        results.append({"schema": sch, **res})

    return {"ok": any(r.get("ok") for r in results), "results": results}


@router.post("/exploration/{conn_id}/reset")
def reset_exploration(conn_id: str):
    """Clear ALL exploration state (connection-level + every per-schema run) without
    restarting. Use /restart to reset+start."""
    deleted = _purge_exploration_state(conn_id)
    return {"ok": True, "reset": True, "purged": deleted}


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


class GroundRequest(BaseModel):
    """Resolve + re-run a cited finding's query to back a specific number ("show the
    receipt"). `text` is the exact token clicked in the brief (e.g. "2.49M"). A
    synthesized narrative number may have come from any of the cited insights, not just
    the nearest — so `insight_ids` lets the caller pass every citation and we ground the
    number against whichever insight actually produced it. `insight_id` is the primary
    (tried first); when empty the whole finding is grounded."""
    insight_id: str = ""
    insight_ids: list[str] = []
    schema: str | None = None
    text: str = ""


@router.post("/exploration/{conn_id}/briefing/ground")
def ground_briefing_number(conn_id: str, body: GroundRequest):
    """Show the receipt for a briefing number. Resolves the cited insight(s) from the
    SAME domain insights the brief is built from, RE-RUNS the recorded query live, and
    grounds the claimed numeral against the actual result cells via the same
    deterministic guard that gates findings (`ground_numerals`). When several citations
    are passed it tries each (primary first) and returns the one whose cells actually
    contain the number — so a synthesized figure is proven against its true source, not
    falsely flagged just because the *nearest* citation wasn't its origin."""
    by_domain = _domain_insights_for(conn_id, body.schema)
    index: dict[str, dict] = {}
    for items in by_domain.values():
        for i in (items or []):
            if i.get("id"):
                index.setdefault(i["id"], i)

    # Candidate insights, primary first, de-duped, dropping any without a query.
    ordered: list[str] = []
    for iid in ([body.insight_id] if body.insight_id else []) + list(body.insight_ids):
        if iid and iid not in ordered and index.get(iid) and (index[iid].get("sql") or "").strip():
            ordered.append(iid)
    if not ordered:
        raise HTTPException(status_code=404, detail="No cited insight with a query to ground against")

    use_schema = body.schema if (body.schema and _store_key(conn_id, body.schema) != conn_id) else None
    try:
        if use_schema:
            from aughor.db.connection import open_connection_for_with_schema
            db = open_connection_for_with_schema(conn_id, schema_name=use_schema)
        else:
            db = open_connection_for(conn_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")

    from aughor.explorer.grounding import ground_numerals

    def _receipt(iid: str, result, numerals) -> dict:
        ins = index[iid]
        return {
            "insight_id": iid,
            "finding": ins.get("finding", ""),
            "sql": (ins.get("sql") or "").strip(),
            "numerals": numerals,
            "columns": result.columns or [],
            "sample_rows": [[str(c) for c in r] for r in (result.rows or [])[:20]],
        }

    fallback: dict | None = None
    for iid in ordered[:6]:   # bounded: usually grounds on the first (the nearest citation)
        result = db.execute("__ground__", (index[iid].get("sql") or "").strip())
        if result.error:
            if fallback is None:
                fallback = {"insight_id": iid, "finding": index[iid].get("finding", ""),
                            "sql": (index[iid].get("sql") or "").strip(), "error": result.error,
                            "numerals": [], "columns": [], "sample_rows": []}
            continue
        text_to_ground = body.text.strip() or index[iid].get("finding", "")
        numerals = ground_numerals(text_to_ground, result.rows or [])
        receipt = _receipt(iid, result, numerals)
        if fallback is None or fallback.get("error"):
            fallback = receipt
        # Short-circuit: this insight's cells actually contain the clicked number.
        if body.text.strip() and numerals and numerals[0].get("enforce") and numerals[0].get("grounded"):
            return receipt
    return fallback or {"insight_id": ordered[0], "finding": "", "sql": "",
                        "numerals": [], "columns": [], "sample_rows": []}


@router.post("/exploration/{connection_id}/insights/{insight_id}/revalidate")
async def revalidate_insight(connection_id: str, insight_id: str):
    """Re-check a finding's dossier against LIVE data — re-run its stored SQL once
    (no LLM) and re-ground the claim. A living dossier: the snapshot is re-stamped
    `confirmed` (numbers still hold) or flagged `drifted` (a number moved), so we
    never silently serve a stale figure. Requires a dossier (404 otherwise)."""
    from datetime import datetime, timezone
    from aughor.kernel.ledger import Ledger
    from aughor.explorer.revalidate import revalidate_finding
    from aughor.explorer.dossier import update_dossier

    rec = Ledger.default().receipt(f"insight:{connection_id}:{insight_id}")
    dossier = ((rec or {}).get("artifact", {}).get("payload", {}) or {}).get("dossier") if rec else None
    if not dossier:
        raise HTTPException(status_code=404, detail="No dossier to re-validate — re-explore to generate one")
    try:
        db = open_connection_for(connection_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")

    result = await asyncio.to_thread(revalidate_finding, dossier, db)
    now = datetime.now(timezone.utc).isoformat()
    # Re-stamp the dossier so "as of" reflects the live check (supersede-not-delete).
    try:
        update_dossier(
            connection_id, insight_id,
            merge={"revalidated_at": now, "revalidation": result.get("status")},
            lineage_edge=("revalidated_by", "guard:live_recheck", result.get("status")),
        )
    except Exception:
        logger.debug("dossier re-stamp failed (non-fatal)", exc_info=True)
    return {**result, "revalidated_at": now}


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
