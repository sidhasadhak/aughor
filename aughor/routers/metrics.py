"""Metrics catalog, health scorecard, and playbook endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.semantic.metrics import MetricDefinition, delete_metric, get_metric, list_metrics, save_metric

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


@router.get("/metrics")
def get_metrics():
    return [m.model_dump() for m in list_metrics()]


@router.post("/metrics", status_code=201)
def create_metric(req: MetricRequest):
    if get_metric(req.name):
        raise HTTPException(status_code=409, detail=f"Metric '{req.name}' already exists. Use PUT to update.")
    m = MetricDefinition(**req.model_dump())
    save_metric(m)
    return m.model_dump()


@router.put("/metrics/{name}")
def update_metric(name: str, req: MetricRequest):
    m = MetricDefinition(**{**req.model_dump(), "name": name})
    save_metric(m)
    return m.model_dump()


@router.delete("/metrics/{name}")
def remove_metric(name: str):
    if not delete_metric(name):
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    return {"ok": True, "name": name}


@router.get("/connections/{conn_id}/health-scorecard")
def get_health_scorecard(conn_id: str):
    """Execute each targeted metric's SQL and return health status."""
    from aughor.db.connection import open_connection_for

    targeted = [m for m in list_metrics() if m.target_value is not None]
    if not targeted:
        return []

    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    results = []
    for metric in targeted:
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


@router.post("/playbook", status_code=201)
def create_playbook_entry(req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import save_entry
    import uuid
    entry = PlaybookEntry(id=f"user_{uuid.uuid4().hex[:12]}", **req.model_dump())
    save_entry(entry)
    return entry.model_dump()


@router.put("/playbook/{entry_id}")
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
