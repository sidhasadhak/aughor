"""Scheduled briefing subscriptions — CRUD + test delivery.

A subscription pushes a connection's briefing on a recurring schedule through an
existing notification trigger. See aughor/briefing/.

The canonical paths are ``/briefing/subscriptions*``. The older ``/briefs/*`` paths stay
registered as thin ``deprecated=True`` aliases that delegate to the handlers below, so a
client pinned to them keeps working for one release.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from aughor.licensing import Capability, gate


def _brief_owner_guard(request: Request) -> None:
    """Object-level authz (SEC-05 / DATA-06): a by-id subscription route is reachable
    only by the org that owns the underlying connection. No-op on the list/create
    routes (no ``sub_id``) and in localhost mode."""
    from aughor.security.authz import check_owner, get_principal
    if (sid := request.path_params.get("sub_id")):
        check_owner("brief", sid, get_principal(request))


router = APIRouter(tags=["briefing"], dependencies=[Depends(_brief_owner_guard)])


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


@router.get("/briefing/subscriptions")
def list_briefing_subscriptions(conn_id: Optional[str] = None):
    from aughor.briefing.store import list_subscriptions
    from aughor.security.authz import org_visible_conn_ids
    org_conns = org_visible_conn_ids()  # DATA-06: only this org's subscriptions
    subs = [
        s for s in list_subscriptions(conn_id)
        if org_conns is None or s.conn_id in org_conns
    ]
    return {"subscriptions": [s.to_dict() for s in subs]}


@router.get("/briefs/subscriptions", deprecated=True)
def list_brief_subscriptions(conn_id: Optional[str] = None):
    """DEPRECATED alias of ``GET /briefing/subscriptions``.

    Identical payload — it delegates to the handler above. Use ``/briefing/subscriptions``.
    """
    return list_briefing_subscriptions(conn_id)


@router.post("/briefing/subscriptions", status_code=201, dependencies=[gate(Capability.SCHEDULED_BRIEFS)])
def create_briefing_subscription(body: _SubscriptionBody, request: Request):
    from aughor.briefing.models    import BriefSubscription
    from aughor.briefing.store     import save_subscription
    from aughor.briefing.scheduler import reload_subscription
    from aughor.notifications.store    import get_trigger
    from aughor.security.authz   import check_owner, get_principal

    check_owner("connection", body.conn_id, get_principal(request))  # DATA-06: no cross-org subscribe
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


@router.post(
    "/briefs/subscriptions",
    status_code=201,
    dependencies=[gate(Capability.SCHEDULED_BRIEFS)],
    deprecated=True,
)
def create_brief_subscription(body: _SubscriptionBody, request: Request):
    """DEPRECATED alias of ``POST /briefing/subscriptions``.

    Same body, same payload, same persisted subscription — it delegates to the handler
    above. Use ``/briefing/subscriptions``.
    """
    return create_briefing_subscription(body, request)


@router.put("/briefing/subscriptions/{sub_id}", dependencies=[gate(Capability.SCHEDULED_BRIEFS)])
def update_briefing_subscription(sub_id: str, body: _SubscriptionBody):
    from aughor.briefing.store     import get_subscription, save_subscription
    from aughor.briefing.scheduler import reload_subscription

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


@router.put(
    "/briefs/subscriptions/{sub_id}",
    dependencies=[gate(Capability.SCHEDULED_BRIEFS)],
    deprecated=True,
)
def update_brief_subscription(sub_id: str, body: _SubscriptionBody):
    """DEPRECATED alias of ``PUT /briefing/subscriptions/{sub_id}``.

    Same body, same payload — it delegates to the handler above. Use ``/briefing/…``.
    """
    return update_briefing_subscription(sub_id, body)


@router.delete("/briefing/subscriptions/{sub_id}", status_code=204)
def delete_briefing_subscription(sub_id: str):
    from aughor.briefing.store     import delete_subscription
    from aughor.briefing.scheduler import remove_subscription
    if not delete_subscription(sub_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    remove_subscription(sub_id)


@router.delete("/briefs/subscriptions/{sub_id}", status_code=204, deprecated=True)
def delete_brief_subscription(sub_id: str):
    """DEPRECATED alias of ``DELETE /briefing/subscriptions/{sub_id}``. Use ``/briefing/…``."""
    delete_briefing_subscription(sub_id)


@router.post("/briefing/subscriptions/{sub_id}/test")
def test_briefing_subscription(sub_id: str):
    """Deliver the briefing immediately and return the outcome (status + preview)."""
    from aughor.briefing.scheduler import trigger_now
    result = trigger_now(sub_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return result


@router.post("/briefs/subscriptions/{sub_id}/test", deprecated=True)
def test_brief_subscription(sub_id: str):
    """DEPRECATED alias of ``POST /briefing/subscriptions/{sub_id}/test``.

    Identical payload — it delegates to the handler above. Use ``/briefing/…``.
    """
    return test_briefing_subscription(sub_id)
