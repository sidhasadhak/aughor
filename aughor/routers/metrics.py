"""Metrics catalog, health scorecard, and playbook endpoints."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate

from aughor.semantic.metrics import (
    MetricDefinition,
    delete_metric,
    get_metric,
    list_metrics,
    save_metric,
    validate_metric,
    check_freshness,
)

router = APIRouter(tags=["metrics"])


class MetricRequest(BaseModel):
    name: str
    label: str
    sql: str
    tables: list[str] = []
    dimensions: list[str] = []
    filters: list[str] = []
    unit: Optional[str] = None
    caveats: Optional[str] = None
    target_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    target_period: Optional[str] = None
    benchmark_source: Optional[str] = None
    # Governance fields (M21)
    owner: Optional[str] = None
    freshness_sla: Optional[str] = None
    freshness_check_sql: Optional[str] = None
    quality_tests: list[str] = []
    lineage: list[str] = []
    wrong_usage_examples: list[str] = []
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None


@router.get("/metrics")
def get_metrics():
    return [m.model_dump() for m in list_metrics()]


@router.post("/metrics", status_code=201, dependencies=[gate(Capability.METRICS_DEFINE)])
def create_metric(req: MetricRequest):
    if get_metric(req.name):
        raise HTTPException(status_code=409, detail=f"Metric '{req.name}' already exists. Use PUT to update.")
    m = MetricDefinition(**req.model_dump())
    save_metric(m)
    return m.model_dump()


@router.put("/metrics/{name}", dependencies=[gate(Capability.METRICS_DEFINE)])
def update_metric(name: str, req: MetricRequest):
    existing = get_metric(name)
    data = {**req.model_dump(), "name": name}
    audit = None
    if existing is not None:
        # Governance state is owned by the transition workflow (B-8), not by edits —
        # carry status/version/stamps forward. But changing the FORMULA of an approved
        # metric un-approves it: it returns to 'proposed' for re-review, and that's audited.
        data["status"] = existing.status
        data["version"] = existing.version
        data["proposed_by"], data["proposed_at"] = existing.proposed_by, existing.proposed_at
        data["approved_by"], data["approved_at"] = existing.approved_by, existing.approved_at
        if existing.status == "approved" and (req.sql or "").strip() != (existing.sql or "").strip():
            from datetime import datetime, timezone
            data["status"] = "proposed"
            data["approved_by"] = data["approved_at"] = None
            audit = {"metric": name, "action": "edit_reproposed",
                     "actor": existing.owner or "editor", "from": "approved", "to": "proposed",
                     "version": existing.version, "at": datetime.now(timezone.utc).isoformat()}
    m = MetricDefinition(**data)
    save_metric(m)
    if audit:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("metric.governance", audit)
    return m.model_dump()


class TransitionRequest(BaseModel):
    action: str   # propose | approve | reject | deprecate
    actor: str    # who is performing it (person/team)


@router.post("/metrics/{name}/transition", dependencies=[gate(Capability.METRICS_DEFINE)])
def transition_metric(name: str, req: TransitionRequest):
    """B-8 — drive a metric through its governance lifecycle (propose → approve →
    deprecate …). Validates the transition, persists the new state, and journals an
    audit event so the trail is queryable."""
    from datetime import datetime, timezone
    from aughor.semantic.governance import apply_transition
    from aughor.kernel.ledger import Ledger

    m = get_metric(name)
    if not m:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    now = datetime.now(timezone.utc).isoformat()
    try:
        updated, audit = apply_transition(m.model_dump(), req.action, req.actor, now)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    save_metric(MetricDefinition(**updated))
    Ledger.default().emit("metric.governance", audit)
    return {"metric": updated, "audit": audit}


@router.get("/metrics/{name}/audit")
def metric_audit(name: str, limit: int = 50):
    """The governance audit trail for a metric — every transition, newest first."""
    from aughor.kernel.ledger import Ledger
    events = Ledger.default().events(kind="metric.governance", limit=1000)
    trail = [e["payload"] for e in events
             if e.get("payload") and e["payload"].get("metric") == name]
    return {"metric": name, "audit": trail[:limit]}


@router.delete("/metrics/{name}")
def remove_metric(name: str, sql: Optional[str] = None):
    # `sql` (optional) targets a single grain when a name has several governed
    # definitions; omitted → remove every entry sharing the name.
    if not delete_metric(name, sql=sql):
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    return {"ok": True, "name": name}


@router.post("/metrics/{name}/validate")
async def run_metric_validation(name: str, conn_id: str):
    """Run all quality_tests for a metric against the given connection."""
    from aughor.db.connection import open_connection_for

    metric = get_metric(name)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    loop = asyncio.get_running_loop()
    def _work():
        try:
            return validate_metric(metric, db)
        finally:
            try:
                db.close()
            except Exception:
                pass

    try:
        result = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result.model_dump()


@router.get("/metrics/{name}/freshness")
async def get_metric_freshness(name: str, conn_id: str):
    """Check the freshness of a metric's underlying data against its SLA."""
    from aughor.db.connection import open_connection_for

    metric = get_metric(name)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    loop = asyncio.get_running_loop()
    def _work():
        try:
            return check_freshness(metric, db)
        finally:
            try:
                db.close()
            except Exception:
                pass

    try:
        result = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result.model_dump()


@router.get("/metrics/{name}/value")
async def get_metric_value(name: str, conn_id: str):
    """Compute a governed metric's CURRENT value by running its registered SQL
    against a connection — the exact governed number, not an LLM re-derivation.
    This is what the MCP `get_metric` tool returns so an external agent binds to
    the same definition the rest of Aughor enforces (vs improvising a formula)."""
    from aughor.db.connection import open_connection_for

    metric = get_metric(name)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Build the GOVERNED value query from the metric's parts: the aggregate expression
    # over its table, with its declared filters applied (e.g. revenue = SUM(total_amount)
    # WHERE status <> 'cancelled' — net-of-cancelled, the governed definition). A metric
    # whose sql is already a full SELECT is run verbatim.
    expr = (metric.sql or "").strip()
    if expr.lower().startswith("select"):
        query = expr
    else:
        query = f"SELECT ({expr}) AS _v"
        if metric.tables:
            query += f" FROM {metric.tables[0]}"
            if metric.filters:
                query += " WHERE " + " AND ".join(metric.filters)

    def _work():
        try:
            qr = db.execute(query)
            rows = qr.rows if qr else []
            if rows and rows[0] is not None:
                raw = rows[0][0] if isinstance(rows[0], (list, tuple)) else list(rows[0].values())[0]
                try:
                    return float(raw), None
                except (TypeError, ValueError):
                    return None, None
            return None, None
        except Exception as exc:
            # A bare-aggregate metric on an ambiguous (e.g. multi-schema) connection can't
            # be auto-computed — report that honestly rather than 500-ing.
            return None, str(exc)
        finally:
            try:
                db.close()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "metric-value connection close is best-effort",
                         counter="metrics.value.close")

    loop = asyncio.get_running_loop()
    value, err = await loop.run_in_executor(None, _work)
    out = {
        "name": metric.name,
        "label": metric.label,
        "value": value,
        "unit": metric.unit,
        "sql": query,
        "filters": metric.filters,
        "caveats": metric.caveats,
    }
    if err:
        out["note"] = f"Could not compute against '{conn_id}': {err}"
    return out


@router.get("/connections/{conn_id}/health-scorecard")
async def get_health_scorecard(conn_id: str):
    """Execute each targeted metric's SQL and return health status."""
    from aughor.db.connection import open_connection_for

    targeted = [m for m in list_metrics() if m.target_value is not None]
    if not targeted:
        return []

    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    _targeted = targeted

    def _work():
        results = []
        for metric in _targeted:
            try:
                qr = db.execute(f"SELECT ({metric.sql}) AS _v")
                rows = qr.rows if qr else []
                current: Optional[float] = None
                if rows and rows[0]:
                    raw = rows[0][0] if isinstance(rows[0], (list, tuple)) else list(rows[0].values())[0]
                    try:
                        current = float(raw)
                    except (TypeError, ValueError):
                        current = None

                if current is None:
                    status = "unknown"
                    variance = None
                else:
                    variance = (current - metric.target_value) / metric.target_value if metric.target_value else None
                    if metric.critical_threshold is not None and abs(current - metric.target_value) >= metric.critical_threshold:
                        status = "red"
                    elif metric.warning_threshold is not None and abs(current - metric.target_value) >= metric.warning_threshold:
                        status = "yellow"
                    else:
                        status = "green"

                results.append({
                    "name": metric.name, "label": metric.label, "current": current,
                    "target": metric.target_value, "variance": variance, "status": status,
                    "unit": metric.unit, "target_period": metric.target_period,
                    "benchmark_source": metric.benchmark_source,
                })
            except Exception:
                results.append({
                    "name": metric.name, "label": metric.label, "current": None,
                    "target": metric.target_value, "variance": None, "status": "unknown",
                    "unit": metric.unit, "target_period": metric.target_period,
                    "benchmark_source": metric.benchmark_source,
                })
        try:
            db.close()
        except Exception:
            pass
        return results

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Playbook ──────────────────────────────────────────────────────────────────

class PlaybookEntryRequest(BaseModel):
    trigger_metric: str
    trigger_condition: str
    trigger_operator: str = "any"
    trigger_value: float = 0.0
    recommendation: str
    expected_impact: str = ""
    typical_timeline: str = ""
    owner_role: str = ""
    tags: list[str] = []
    status: str = "draft"
    source_kb_id: Optional[str] = None


@router.get("/playbook")
def get_playbook():
    from aughor.playbook.store import list_entries
    return [e.model_dump() for e in list_entries()]


@router.get("/playbook/{entry_id}")
def get_playbook_entry(entry_id: str):
    from aughor.playbook.store import get_entry
    e = get_entry(entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Entry not found")
    return e.model_dump()


@router.get("/playbook/{entry_id}/versions")
def get_playbook_versions(entry_id: str):
    """The immutable Governed-Dive history of a play — every frozen version (with its receipt),
    oldest → newest. A finding that cited an older version can be resolved against the exact
    content it relied on."""
    from aughor.playbook.store import get_entry, list_versions
    if not get_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return list_versions(entry_id)


@router.post("/playbook", status_code=201, dependencies=[gate(Capability.PLAYBOOK)])
def create_playbook_entry(req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import save_entry
    import uuid
    entry = PlaybookEntry(id=f"user_{uuid.uuid4().hex[:12]}", **req.model_dump())
    save_entry(entry)
    return entry.model_dump()


@router.put("/playbook/{entry_id}", dependencies=[gate(Capability.PLAYBOOK)])
def update_playbook_entry(entry_id: str, req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import get_entry, save_entry
    existing = get_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Entry not found")
    updated = PlaybookEntry(
        id=entry_id,
        evidence_sources=existing.evidence_sources,
        historical_success_rate=existing.historical_success_rate,
        **req.model_dump(),
    )
    save_entry(updated)
    return updated.model_dump()


@router.delete("/playbook/{entry_id}")
def delete_playbook_entry(entry_id: str):
    from aughor.playbook.store import delete_entry
    if not delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True, "id": entry_id}


@router.post("/playbook/seed")
def reseed_playbook():
    """Force re-seed of playbook from KB."""
    from aughor.playbook.builder import seed_from_kb
    n = seed_from_kb(force=True)
    return {"seeded": n}


@router.get("/metrics/enforcement-rate")
def metric_enforcement_rate(connection_id: str = "", limit: int = 500):
    """B-7 — the measured enforcement rate: of the answers that TARGETED a
    governed metric, what fraction USED the governed formula (vs improvised).
    Aggregated from the metric.enforcement journal events. The honest
    denominator is metric-bearing answers only — questions with no governed
    metric don't count for or against."""
    from aughor.kernel.ledger import Ledger
    evs = Ledger.default().events(
        kind="metric.enforcement",
        conn_id=connection_id or None, limit=int(limit),
    )
    total = len(evs)
    enforced = sum(1 for e in evs if (e.get("payload") or {}).get("enforced"))
    drift_metrics: dict[str, int] = {}
    for e in evs:
        for m in (e.get("payload") or {}).get("drift", []) or []:
            drift_metrics[m] = drift_metrics.get(m, 0) + 1
    return {
        "connection_id": connection_id or "all",
        "metric_bearing_answers": total,
        "enforced": enforced,
        "enforcement_rate": round(enforced / total, 3) if total else None,
        "drift_by_metric": drift_metrics,
    }
