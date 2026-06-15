"""System endpoints — health, dev stats, suggestions, connector types."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.db.registry import BUILTIN_ID

router = APIRouter(tags=["system"])


@router.post("/eval/run")
async def run_eval_endpoint(
    dataset: str = "evals/golden_sql_expanded.jsonl",
    connection: str = "samples",
    limit: int | None = None,
    by_category: bool = True,
):
    """Run the golden dataset SQL accuracy evaluator (reference replay mode)."""
    import asyncio
    import json
    from pathlib import Path

    from aughor.db.connection import open_connection_for

    # The golden-SQL eval harness is an optional dev/CI component. Degrade
    # gracefully when it (or its dataset) isn't present, so a minimal deployment
    # gets a clear 503/404 instead of an ImportError/FileNotFoundError 500.
    try:
        from evals.run_golden import run_eval
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Evaluation harness not available: {exc}",
        )

    dataset_path = Path(dataset)
    if not dataset_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Eval dataset not found: {dataset}",
        )

    records = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
    if limit:
        records = records[:limit]

    db = open_connection_for(connection)
    schema = ""
    try:
        schema = db.get_schema()
    except Exception:
        pass

    loop = asyncio.get_event_loop()
    def _work():
        results = []
        for rec in records:
            results.append(run_eval(rec, db, live=False, schema=schema))
        return results

    try:
        results = await loop.run_in_executor(None, _work)
    finally:
        try:
            db.close()
        except Exception:
            pass

    total = len(results)
    perfect = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.99)
    passed_80 = sum(1 for r in results if r["scores"].get("overall", 0) >= 0.80)
    errors = sum(1 for r in results if r["scores"].get("error"))

    by_diff = {}
    for r in results:
        d = r["difficulty"]
        by_diff.setdefault(d, {"total": 0, "perfect": 0, "passed_80": 0, "errors": 0})
        by_diff[d]["total"] += 1
        if r["scores"].get("overall", 0) >= 0.99:
            by_diff[d]["perfect"] += 1
        if r["scores"].get("overall", 0) >= 0.80:
            by_diff[d]["passed_80"] += 1
        if r["scores"].get("error"):
            by_diff[d]["errors"] += 1

    summary = {
        "total": total,
        "perfect": perfect,
        "passed_80": passed_80,
        "errors": errors,
        "by_difficulty": by_diff,
    }

    return {"results": results, "summary": summary}



@router.get("/health")
def health():
    fixture = Path(__file__).parent.parent.parent / "data" / "aughor.duckdb"
    return {"status": "ok", "fixture_db": fixture.exists()}


@router.get("/capabilities")
def get_capabilities(connection_id: str | None = None):
    """The active tier + the capabilities it grants, for the frontend to show/lock/upsell UI.
    Defaults to the `enterprise` tier (everything on) until a lower tier is assigned."""
    from aughor.licensing import resolve_tier, capabilities_for
    tier = resolve_tier(connection_id)
    return {
        "tier": tier.value,
        "capabilities": sorted(c.value for c in capabilities_for(tier)),
    }


@router.get("/dev/stats")
def get_dev_stats():
    """Return in-process stats counters."""
    from aughor.stats import stats
    return stats.snapshot()


@router.post("/dev/stats/reset")
def reset_dev_stats():
    """Reset all counters to zero."""
    from aughor.stats import stats
    stats.reset()
    return {"ok": True}


class _Suggestion(BaseModel):
    text: str
    mode: str   # "ask" | "investigate"


class _Suggestions(BaseModel):
    suggestions: list[_Suggestion]


@router.get("/suggestions")
async def get_suggestions(connection_id: str = BUILTIN_ID):
    """Return 6 starter questions tailored to the schema of the given connection."""
    from aughor.semantic.suggestions_cache import (
        schema_fingerprint, get_cached, store as cache_store,
    )
    from aughor.db.connection import open_connection_for

    loop = asyncio.get_event_loop()

    try:
        db = open_connection_for(connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        schema_summary: str = await loop.run_in_executor(None, db.get_schema)
        db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    fingerprint = schema_fingerprint(schema_summary)

    try:
        cached = get_cached(connection_id, fingerprint)
        if cached:
            return {"suggestions": cached, "cached": True}
    except Exception:
        pass

    enrichment = ""
    try:
        from aughor.explorer.store import render_exploration_annotations
        _ea = render_exploration_annotations(connection_id)
        if _ea:
            enrichment += f"\n\nEXPLORATION FINDINGS (interesting patterns already discovered):\n{_ea}"
    except Exception:
        pass
    try:
        from aughor.semantic.metrics import build_metrics_block
        _mb = build_metrics_block()
        if _mb:
            enrichment += f"\n\n{_mb}"
    except Exception:
        pass

    _system = (
        "You are a data analyst assistant. Given a database schema and any domain intelligence, "
        "produce exactly 6 starter questions a business user might ask. "
        "Mix question types: 4 should be simple analytical questions (mode='ask') and "
        "2 should be deeper diagnostic questions (mode='investigate'). "
        "Make every question specific to the actual table and column names provided — "
        "no generic placeholders. Keep each question concise (under 12 words)."
    )
    _user = f"Database schema:\n{schema_summary}{enrichment}\n\nReturn 6 starter questions."

    def _llm_work():
        from aughor.llm.provider import get_provider
        result: _Suggestions = get_provider("coder").complete(
            system=_system,
            user=_user,
            response_model=_Suggestions,
            temperature=0.4,
        )
        return [s.model_dump() for s in result.suggestions]

    try:
        suggestions = await loop.run_in_executor(None, _llm_work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        cache_store(connection_id, fingerprint, suggestions)
    except Exception:
        pass

    return {"suggestions": suggestions, "cached": False}


@router.get("/connectors/types")
def list_connector_types():
    """Return all registered connector types with form field descriptors."""
    from aughor.connectors.registry import REGISTRY, FORM_FIELDS, DSN_PREVIEWS
    types = []
    for conn_type in ["duckdb", "postgres"] + REGISTRY.supported_types():
        types.append({
            "type":        conn_type,
            "dsn_preview": DSN_PREVIEWS.get(conn_type, conn_type),
            "fields":      FORM_FIELDS.get(conn_type, []),
            "category":    (
                "file"       if conn_type in ("local_upload", "s3", "sqlite") else
                "warehouse"  if conn_type in ("bigquery", "snowflake", "mysql", "motherduck", "exasol") else
                "api"        if conn_type in ("stripe", "hubspot", "salesforce", "gsheets") else
                "federation" if conn_type == "federated" else
                "built-in"
            ),
        })
    return {"types": types}
