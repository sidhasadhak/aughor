"""The review question DELIVERED (the 2027 study §K and §W phase 3): to the resolved owner, where
they already are, through the departure gate — where before this it was written to a log.

The owner is a principal (`playbook/outcomes.resolve_asked_to`); the place is the channel their
group binds (`rbac/routing.route`). A person with no channel bound is not reached by this module,
and the record says so rather than nothing: the question waits on the departures screen and the
Now page. A delivered question passes the gate like every message that leaves — its two numbers
are the measurement it departs on — and the departure row is cited on the review.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def deliver_review_question(o, *, now: Optional[datetime] = None) -> dict:
    """``{"door", "status", "note", "departure_id", "target"}`` — what became of the question."""
    now = now or datetime.now(timezone.utc)
    principal = str(getattr(o, "review_asked_to", "") or "")
    question = str(getattr(o, "review_question", "") or "")
    if not principal:
        return {"door": "none", "status": "nobody", "note": "no principal to ask; the question waits on the departures screen"}
    if not question:
        return {"door": "none", "status": "nothing", "note": "the review wrote no question"}
    from aughor.org.context import current_org_id
    from aughor.rbac.routing import route
    label = (o.spec or {}).get("metric_label") or o.metric_name or "the metric"
    org = current_org_id()
    destinations = route(f"metric:{label}", org_id=org, owner=principal)
    channel = next((d for d in destinations if d.channel_trigger_id), None)
    if channel is None:
        return {"door": "none", "status": "not_sent",
                "note": f"{principal} has no channel bound; the question waits on the departures screen and the Now page"}
    from aughor.notifications.store import get_trigger
    trigger = get_trigger(channel.channel_trigger_id)
    if trigger is None:
        return {"door": "channel", "status": "not_sent", "target": channel.channel_trigger_id,
                "note": f"the channel {channel.channel_trigger_id!r} bound to {principal} no longer exists"}
    from aughor.govern.departure import Measurement, gate_departure
    from aughor.notifications.executor import fire_action
    from aughor.notifications.models import ActionPayload
    values = [float(v) for v in (o.baseline_value, o.review_value) if v is not None]
    verdict = gate_departure(
        kind="review_question", org_id=org, conn_id=o.connection_id or "", text=question,
        target=trigger.id, actor=f"review:{o.id}", investigation_id=o.inv_id,
        source_kind="review", source_id=o.id, source_name=f"review of {o.rec_text[:60]}",
        about=f"metric:{label}",
        measurement=Measurement(source=f"the review of “{o.rec_text[:60]}”", values=values,
                                measured_at=now.isoformat(), definition=label),
        declared_definition=label)
    if verdict.held:
        return {"door": "channel", "status": "held", "target": trigger.id, "departure_id": verdict.record_id,
                "note": verdict.reason_sentence()}
    log = fire_action(trigger, ActionPayload(
        investigation_id=o.inv_id, rec_index=o.rec_index, recommendation=question, metric_name=label,
        headline=f"Review of “{o.rec_text[:80]}”", trigger_id=trigger.id, triggered_at=now.isoformat(),
        delivery_key=f"review:{o.id}:{str(o.reviewed_at or now.isoformat())[:19]}",
        context={"review_of": o.id, "asked_to": principal, "receipt": verdict.receipt,
                 "receipt_line": verdict.receipt_line()}))
    status = getattr(log, "status", "") or "unknown"
    return {"door": "channel", "status": "sent" if status == "ok" else status, "target": trigger.id,
            "departure_id": verdict.record_id, "to": principal,
            "note": "" if status == "ok" else str(getattr(log, "error", "") or "")}
