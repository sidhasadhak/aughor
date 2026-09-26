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
from aughor.security.authz import connection_owner_guard


def _brief_owner_guard(request: Request) -> None:
    """Object-level authz (SEC-05 / DATA-06): a by-id subscription route is reachable
    only by the org that owns the underlying connection. No-op on the list/create
    routes (no ``sub_id``) and in localhost mode."""
    from aughor.security.authz import check_owner, get_principal
    if (sid := request.path_params.get("sub_id")):
        check_owner("brief", sid, get_principal(request))


#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["briefing"], dependencies=[Depends(_brief_owner_guard), Depends(connection_owner_guard)])


class _SubscriptionBody(BaseModel):
    conn_id:    str
    name:       str
    trigger_id: str = ""
    # Arc BR-5 — a Slack bot and channel instead of a trigger; the Briefing's scope; the
    # automation it replaces. Sent only by a client that knows them.
    bot_id:     str = ""
    channel:    str = ""
    schema_name: str = ""
    supersedes: str = ""
    period:     str = "week"        # "week" | "day" (+ "month" | "year" with briefing.by_period)
    send_cron:  str = ""            # optional explicit cron; derived from period if blank
    enabled:    bool = True
    content:    str = "alert_summary"      # "alert_summary" | "briefing" (briefing.by_period)


def _validate_destination(body: "_SubscriptionBody") -> None:
    """A subscription delivers through an Action Hub trigger or a Slack bot and channel, and
    replaces only an automation of its own connection. Refused with the reason."""
    from aughor.notifications.store import get_trigger
    if body.bot_id:
        from aughor.slackbots.store import get_bot
        if get_bot(body.bot_id) is None:
            raise HTTPException(status_code=400, detail="Slack bot not found")
        if not body.channel.strip():
            raise HTTPException(status_code=422, detail="a Slack bot needs a channel to post in")
    elif not get_trigger(body.trigger_id):
        raise HTTPException(status_code=400, detail="Delivery trigger not found — create an Action Hub trigger first")
    if body.supersedes:
        from aughor.automations.store import get_automation
        replaced = get_automation(body.supersedes)
        if replaced is None or replaced.conn_id != body.conn_id:
            raise HTTPException(status_code=422, detail="the automation it replaces is not one of this connection's")


def _validate_period(period: str, content: str = "alert_summary") -> None:
    if content == "alert_summary" and period in ("week", "day"):
        return
    from aughor.briefing.models import CONTENTS
    from aughor.knowledge import period_brief
    if not period_brief.enabled():
        if content == "alert_summary":
            # Unchanged while the flag is off: the same refusal a client has always received.
            raise HTTPException(status_code=422, detail="period must be 'week' or 'day'")
        raise HTTPException(status_code=422, detail=(
            "briefings by period are off on this install — a subscription that sends the "
            f"Briefing needs the '{period_brief.FLAG}' flag"))
    if period not in period_brief.PERIODS:
        raise HTTPException(status_code=422, detail=period_brief.refusal(period))
    if content not in CONTENTS:
        raise HTTPException(status_code=422, detail="content must be 'alert_summary' or 'briefing'")
    if content == "alert_summary":
        raise HTTPException(status_code=422, detail=(
            f"there is no {period}ly alert summary — only daily and weekly ones; a {period} "
            "subscription sends the Briefing written for its period (content 'briefing')"))


@router.get("/briefing/subscriptions")
def list_briefing_subscriptions(conn_id: Optional[str] = None):
    from aughor.briefing.store import list_subscriptions
    from aughor.security.authz import org_visible_conn_ids
    org_conns = org_visible_conn_ids()  # DATA-06: only this org's subscriptions
    from aughor.metastore import scoped_to_workspace
    subs = [
        s for s in list_subscriptions(conn_id)
        if org_conns is None or s.conn_id in org_conns
    ]
    subs = scoped_to_workspace(subs, key="conn_id")  # …then to the active workspace
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
    from aughor.security.authz   import check_owner, get_principal

    check_owner("connection", body.conn_id, get_principal(request))  # DATA-06: no cross-org subscribe
    _validate_period(body.period, body.content)
    _validate_destination(body)
    sub = BriefSubscription(
        conn_id=body.conn_id, name=body.name, trigger_id=body.trigger_id,
        period=body.period, send_cron=body.send_cron, enabled=body.enabled,
        content=body.content, bot_id=body.bot_id, channel=body.channel.strip(),
        schema_name=body.schema_name, supersedes=body.supersedes,
    )
    saved = save_subscription(sub)
    # No scheduler sync: the automation heartbeat reads the subscription store live
    # each tick (virtual adoption), so a saved row is already scheduled.
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

    existing = get_subscription(sub_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if (body.period, body.content) != (existing.period, existing.content):
        # validated only when it CHANGES: a briefing subscription saved while the flag was on can
        # still be paused or renamed after it is turned off (branch review, 2026-09-24)
        _validate_period(body.period, body.content)

    existing.conn_id    = body.conn_id
    existing.name       = body.name
    existing.trigger_id = body.trigger_id
    existing.period     = body.period
    existing.send_cron  = body.send_cron
    existing.enabled    = body.enabled
    existing.content    = body.content
    # Arc BR-5 fields change only when SENT: an editor that does not know them keeps them
    for k in ("bot_id", "channel", "schema_name", "supersedes"):
        if k in body.model_fields_set:
            setattr(existing, k, getattr(body, k))
    if {"bot_id", "channel", "trigger_id", "supersedes"} & body.model_fields_set:
        _validate_destination(_SubscriptionBody(**existing.model_dump(include=set(_SubscriptionBody.model_fields))))
    saved = save_subscription(existing)
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
    if not delete_subscription(sub_id):
        raise HTTPException(status_code=404, detail="Subscription not found")


@router.delete("/briefs/subscriptions/{sub_id}", status_code=204, deprecated=True)
def delete_brief_subscription(sub_id: str):
    """DEPRECATED alias of ``DELETE /briefing/subscriptions/{sub_id}``. Use ``/briefing/…``."""
    delete_briefing_subscription(sub_id)


@router.post("/briefing/subscriptions/{sub_id}/test")
def test_briefing_subscription(sub_id: str, dry_run: bool = False):
    """Deliver the briefing immediately and return the outcome (status + preview). With
    ``dry_run`` (Arc BR-5) it is built and judged at the departure gate exactly as a send
    would be, and NOT sent: the preview and the verdict, nothing leaves."""
    if dry_run:
        from aughor.briefing.delivery import preview_subscription
        from aughor.briefing.store import get_subscription
        sub = get_subscription(sub_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return preview_subscription(sub)
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
