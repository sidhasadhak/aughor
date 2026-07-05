"""Monitors API — CRUD for monitors, alert queries, trigger-now, digest."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from aughor.licensing import Capability, gate

from aughor.monitors.models import Monitor
from aughor.monitors.store import (
    list_monitors,
    get_monitor,
    upsert_monitor,
    delete_monitor,
    set_monitor_enabled,
    get_alerts,
    acknowledge_alert,
)


def _monitor_owner_guard(request: Request) -> None:
    """Object-level authz (SEC-05 / DATA-06): a by-id monitor or alert route is
    reachable only by the org that owns the underlying connection. No-op on routes
    without a ``monitor_id``/``alert_id`` (list/create) and in localhost mode."""
    from aughor.security.authz import check_owner, get_principal
    principal = get_principal(request)
    if (mid := request.path_params.get("monitor_id")):
        check_owner("monitor", mid, principal)
    if (aid := request.path_params.get("alert_id")):
        check_owner("alert", aid, principal)


router = APIRouter(tags=["monitors"], dependencies=[Depends(_monitor_owner_guard)])


# ── Request bodies ─────────────────────────────────────────────────────────────

class CreateMonitorRequest(BaseModel):
    conn_id: str
    name: str
    metric_name: Optional[str] = None
    custom_sql: Optional[str] = None
    reanchor_window: bool = False
    check_cron: str = "0 * * * *"
    alert_on: str = "threshold_cross"
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    threshold_direction: str = "below"
    sigma_threshold: float = 2.5
    history_days: int = 30
    dimension_column: Optional[str] = None
    drift_p_threshold: float = 0.05
    freshness_table: Optional[str] = None
    freshness_column: str = "updated_at"
    freshness_sla_hours: float = 24.0
    notification_channel: str = "in_app"
    enabled: bool = True


class UpdateMonitorRequest(BaseModel):
    """Partial update — only provided fields are changed."""
    name: Optional[str] = None
    check_cron: Optional[str] = None
    alert_on: Optional[str] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    threshold_direction: Optional[str] = None
    sigma_threshold: Optional[float] = None
    history_days: Optional[int] = None
    dimension_column: Optional[str] = None
    drift_p_threshold: Optional[float] = None
    freshness_table: Optional[str] = None
    freshness_column: Optional[str] = None
    freshness_sla_hours: Optional[float] = None
    notification_channel: Optional[str] = None
    enabled: Optional[bool] = None
    custom_sql: Optional[str] = None
    metric_name: Optional[str] = None


# ── Monitor CRUD ───────────────────────────────────────────────────────────────

@router.get("/monitors")
def list_monitors_route(
    conn_id: Optional[str] = None, workspace_id: Optional[str] = None
) -> list[dict]:
    # Fail-closed workspace tenancy gate: None => unscoped (management/default view),
    # a set => only those connections, empty-set => an unknown workspace surfaces nothing.
    from aughor.metastore import accessible_catalog_ids
    from aughor.security.authz import org_visible_conn_ids

    allowed = accessible_catalog_ids(workspace_id)
    org_conns = org_visible_conn_ids()  # DATA-06: None in localhost, else this org's connections
    return [
        m.model_dump()
        for m in list_monitors(conn_id=conn_id)
        if (allowed is None or m.conn_id in allowed)
        and (org_conns is None or m.conn_id in org_conns)
    ]


@router.get("/monitors/{monitor_id}")
def get_monitor_route(monitor_id: str) -> dict:
    m = get_monitor(monitor_id)
    if not m:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return m.model_dump()


@router.post("/monitors", status_code=201, dependencies=[gate(Capability.MONITORS)])
def create_monitor(req: CreateMonitorRequest, request: Request) -> dict:
    # DATA-06: can't attach a monitor to a connection your org can't see.
    from aughor.security.authz import check_owner, get_principal
    check_owner("connection", req.conn_id, get_principal(request))
    # CreateMonitorRequest is permissive (str fields); Monitor enforces strict
    # Literals (alert_on, threshold_direction, …). Translate a domain-model
    # validation failure into a clean 422 instead of leaking a 500.
    try:
        monitor = Monitor(**req.model_dump())
    except ValidationError as e:
        detail = "; ".join(f"{er['loc'][-1]}: {er['msg']}" for er in e.errors())
        raise HTTPException(status_code=422, detail=f"Invalid monitor configuration — {detail}")
    saved = upsert_monitor(monitor)
    # Schedule it
    try:
        from aughor.monitors.scheduler import reload_monitor
        reload_monitor(saved)
    except Exception:
        pass
    return saved.model_dump()


@router.put("/monitors/{monitor_id}", dependencies=[gate(Capability.MONITORS)])
def update_monitor(monitor_id: str, req: UpdateMonitorRequest) -> dict:
    existing = get_monitor(monitor_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Monitor not found")
    # Merge non-None fields
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = existing.model_copy(update=updates)
    saved = upsert_monitor(updated)
    try:
        from aughor.monitors.scheduler import reload_monitor, remove_monitor
        if saved.enabled:
            reload_monitor(saved)
        else:
            remove_monitor(monitor_id)
    except Exception:
        pass
    return saved.model_dump()


@router.delete("/monitors/{monitor_id}", status_code=204)
def delete_monitor_route(monitor_id: str) -> None:
    if not delete_monitor(monitor_id):
        raise HTTPException(status_code=404, detail="Monitor not found")
    try:
        from aughor.monitors.scheduler import remove_monitor
        remove_monitor(monitor_id)
    except Exception:
        pass


# ── Enable / disable ───────────────────────────────────────────────────────────

@router.post("/monitors/{monitor_id}/enable")
def enable_monitor(monitor_id: str) -> dict:
    m = set_monitor_enabled(monitor_id, True)
    if not m:
        raise HTTPException(status_code=404, detail="Monitor not found")
    try:
        from aughor.monitors.scheduler import reload_monitor
        reload_monitor(m)
    except Exception:
        pass
    return m.model_dump()


@router.post("/monitors/{monitor_id}/disable")
def disable_monitor(monitor_id: str) -> dict:
    m = set_monitor_enabled(monitor_id, False)
    if not m:
        raise HTTPException(status_code=404, detail="Monitor not found")
    try:
        from aughor.monitors.scheduler import remove_monitor
        remove_monitor(monitor_id)
    except Exception:
        pass
    return m.model_dump()


# ── Trigger now (test run) ─────────────────────────────────────────────────────

@router.post("/monitors/{monitor_id}/trigger", dependencies=[gate(Capability.MONITORS)])
def trigger_monitor(monitor_id: str) -> dict:
    """Run a monitor immediately and return the alert (or null if no condition met)."""
    if not get_monitor(monitor_id):
        raise HTTPException(status_code=404, detail="Monitor not found")
    try:
        from aughor.monitors.scheduler import trigger_now
        alert = trigger_now(monitor_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return alert.model_dump() if alert else {"fired": False}


# ── Alerts ─────────────────────────────────────────────────────────────────────

@router.get("/monitors/{monitor_id}/alerts")
def get_monitor_alerts(
    monitor_id: str,
    limit: int = 50,
    unacknowledged_only: bool = False,
) -> list[dict]:
    if not get_monitor(monitor_id):
        raise HTTPException(status_code=404, detail="Monitor not found")
    return [a.model_dump() for a in get_alerts(
        monitor_id=monitor_id, limit=limit, unacknowledged_only=unacknowledged_only
    )]


@router.get("/alerts")
def get_all_alerts(
    conn_id: Optional[str] = None,
    limit: int = 100,
    unacknowledged_only: bool = False,
    workspace_id: Optional[str] = None,
) -> list[dict]:
    """All recent alerts across all monitors, optionally filtered by connection
    and/or scoped to the active workspace (fail-closed: an unknown workspace
    surfaces nothing)."""
    from aughor.metastore import accessible_catalog_ids
    from aughor.security.authz import org_visible_conn_ids

    allowed = accessible_catalog_ids(workspace_id)
    org_conns = org_visible_conn_ids()  # DATA-06: cross-org alerts never leak into the feed
    return [
        a.model_dump()
        for a in get_alerts(
            conn_id=conn_id, limit=limit, unacknowledged_only=unacknowledged_only
        )
        if (allowed is None or a.conn_id in allowed)
        and (org_conns is None or a.conn_id in org_conns)
    ]


@router.post("/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: str) -> dict:
    a = acknowledge_alert(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    return a.model_dump()


# ── Digest ─────────────────────────────────────────────────────────────────────

@router.get("/monitors/digest")
def get_digest(conn_id: str, request: Request, period: str = "week") -> dict:
    """Build and return the intelligence digest for a connection."""
    from aughor.security.authz import check_owner, get_principal
    check_owner("connection", conn_id, get_principal(request))  # DATA-06: no cross-org digest
    if period not in ("week", "day"):
        raise HTTPException(status_code=422, detail="period must be 'week' or 'day'")
    try:
        from aughor.monitors.digest import build_digest
        result = build_digest(conn_id=conn_id, period=period)
        return {**result.model_dump(), "markdown": result.to_markdown()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
