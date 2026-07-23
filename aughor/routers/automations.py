"""Automations API (Wave A) — CRUD, run-now, and the tick history.

Every route self-gates on the ``automations.engine`` flag, so with it off the whole surface 404s
and nothing here is reachable — the same shape ``routers/kinetic.py`` uses.

``GET /automations/{id}/runs`` is the endpoint the subsystem exists for: it answers "did it run,
and why did nothing happen?", which the monitor API cannot answer because ``monitor_alerts`` stores
only the ticks that fired.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from aughor.automations.models import Automation, Condition, Effect
from aughor.automations.store import (
    delete_automation,
    get_automation,
    get_runs,
    list_automations,
    pause_automation,
    set_automation_enabled,
    upsert_automation,
)

router = APIRouter(tags=["automations"])


def _require_flag() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("automations.engine"):
        raise HTTPException(status_code=404, detail="Automations are not enabled")


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreateAutomationRequest(BaseModel):
    conn_id: str
    name: str
    description: str = ""
    conditions: list[Condition] = Field(min_length=1)
    condition_logic: str = "all"
    effects: list[Effect] = Field(min_length=1)
    fallback_effect: Optional[Effect] = None
    enabled: bool = True
    paused_until: Optional[str] = None
    expires_at: Optional[str] = None
    max_retries: int = 1
    retry_backoff_seconds: float = 30.0


class PauseRequest(BaseModel):
    until: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC to mute until, or null to clear the mute.",
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/automations")
def list_all(conn_id: Optional[str] = None, enabled_only: bool = False):
    _require_flag()
    return {"automations": [a.model_dump() for a in list_automations(conn_id, enabled_only)]}


@router.get("/automations/{automation_id}")
def get_one(automation_id: str):
    _require_flag()
    a = get_automation(automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.post("/automations")
def create(body: CreateAutomationRequest):
    """Create an automation. A malformed condition or effect is rejected HERE, at construction —
    it never reaches the store, so a broken automation cannot sit in the DB looking schedulable."""
    _require_flag()
    try:
        automation = Automation(**body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return upsert_automation(automation).model_dump()


@router.put("/automations/{automation_id}")
def update(automation_id: str, body: CreateAutomationRequest):
    _require_flag()
    existing = get_automation(automation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    try:
        automation = Automation(**body.model_dump(), id=automation_id,
                                created_at=existing.created_at)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return upsert_automation(automation).model_dump()


@router.delete("/automations/{automation_id}")
def remove(automation_id: str):
    _require_flag()
    if not delete_automation(automation_id):
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"deleted": automation_id}


@router.post("/automations/{automation_id}/enabled")
def set_enabled(automation_id: str, enabled: bool = True):
    _require_flag()
    a = set_automation_enabled(automation_id, enabled)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.post("/automations/{automation_id}/pause")
def pause(automation_id: str, body: PauseRequest):
    """Mute until a timestamp (or clear it). Distinct from disabling: a pause has an end, and the
    run history keeps recording *why* nothing fired while it holds."""
    _require_flag()
    a = pause_automation(automation_id, body.until)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a.model_dump()


@router.post("/automations/{automation_id}/run")
def run_now(automation_id: str):
    """Run one automation immediately, through the same gates the heartbeat uses — so a gated
    automation returns the REASON it is gated rather than silently doing nothing."""
    _require_flag()
    from aughor.automations.scheduler import trigger_now
    run = trigger_now(automation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return run.model_dump()


@router.get("/automations/{automation_id}/runs")
def runs(automation_id: str, limit: int = 50):
    _require_flag()
    return {"runs": [r.model_dump() for r in get_runs(automation_id=automation_id, limit=limit)]}
