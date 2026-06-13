"""Scheduled Brief subscriptions — CRUD + test delivery.

A subscription pushes a connection's Intelligence Digest on a recurring schedule
through an existing Action Hub trigger. See aughor/briefs/.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate

router = APIRouter(tags=["briefs"])


class _SubscriptionBody(BaseModel):
    conn_id:    str
    name:       str
    trigger_id: str
    period:     str = "week"        # "week" | "day"
    send_cron:  str = ""            # optional explicit cron; derived from period if blank
    enabled:    bool = True


def _validate_period(period: str) -> None:
    if period not in ("week", "day"):
        raise HTTPException(status_code=422, detail="period must be 'week' or 'day'")


@router.get("/briefs/subscriptions")
def list_brief_subscriptions(conn_id: Optional[str] = None):
    from aughor.briefs.store import list_subscriptions
    return {"subscriptions": [s.to_dict() for s in list_subscriptions(conn_id)]}


@router.post("/briefs/subscriptions", status_code=201, dependencies=[gate(Capability.SCHEDULED_BRIEFS)])
def create_brief_subscription(body: _SubscriptionBody):
    from aughor.briefs.models    import BriefSubscription
    from aughor.briefs.store     import save_subscription
    from aughor.briefs.scheduler import reload_subscription
    from aughor.actions.store    import get_trigger

    _validate_period(body.period)
    if not get_trigger(body.trigger_id):
        raise HTTPException(status_code=400, detail="Delivery trigger not found — create an Action Hub trigger first")

    sub = BriefSubscription(
        conn_id=body.conn_id, name=body.name, trigger_id=body.trigger_id,
        period=body.period, send_cron=body.send_cron, enabled=body.enabled,
    )
    saved = save_subscription(sub)
    reload_subscription(saved)
    return saved.to_dict()


@router.put("/briefs/subscriptions/{sub_id}", dependencies=[gate(Capability.SCHEDULED_BRIEFS)])
def update_brief_subscription(sub_id: str, body: _SubscriptionBody):
    from aughor.briefs.store     import get_subscription, save_subscription
    from aughor.briefs.scheduler import reload_subscription

    _validate_period(body.period)
    existing = get_subscription(sub_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Subscription not found")

    existing.conn_id    = body.conn_id
    existing.name       = body.name
    existing.trigger_id = body.trigger_id
    existing.period     = body.period
    existing.send_cron  = body.send_cron
    existing.enabled    = body.enabled
    saved = save_subscription(existing)
    reload_subscription(saved)
    return saved.to_dict()


@router.delete("/briefs/subscriptions/{sub_id}", status_code=204)
def delete_brief_subscription(sub_id: str):
    from aughor.briefs.store     import delete_subscription
    from aughor.briefs.scheduler import remove_subscription
    if not delete_subscription(sub_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    remove_subscription(sub_id)


@router.post("/briefs/subscriptions/{sub_id}/test")
def test_brief_subscription(sub_id: str):
    """Deliver the brief immediately and return the outcome (status + preview)."""
    from aughor.briefs.scheduler import trigger_now
    result = trigger_now(sub_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return result
