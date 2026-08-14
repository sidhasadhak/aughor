"""Alert delivery — OA·N8-0.

``Monitor.notification_channel`` has existed since monitors shipped, with its own
field docstring conceding the gap: *"only in_app wired currently"*. A monitor could
be configured to notify Slack; nothing read the field. This module is the read.

**Why an Action Hub trigger id and not a channel name.** The field used to be
described as ``'in_app' | 'slack' | 'email'``, which names a *kind* of destination
but never a destination: "slack" does not say which workspace, which webhook, or with
what credential. Aughor already models configured destinations — ``ActionTrigger``,
with a URL, encrypted at rest, an SSRF guard at send time, retry, an audit log, and
delivery-key idempotency. So the channel holds a trigger id, and delivery is
``fire_action``. Nothing here re-implements dispatch.

That choice also settles OA·N8-1 in advance: an n8n Webhook node is reachable as a
plain ``webhook`` trigger, so "alert → n8n" needs no aughor code at all — only a
trigger pointing at the user's own instance. Which is the arm's-length posture n8n's
licence requires of us anyway (study §7.2).

Delivery is FAIL-OPEN in one direction only: a failed send never costs the alert. The
alert row is the source of truth and is already committed before this runs.

⚠️ **Tenancy.** Action Hub triggers are not org-scoped — a flat JSON store with no
tenant column, and no org predicate on `/actions/*` or in `get_trigger`. This module
resolves a trigger id exactly as `automations/engine.py:_dispatch_notify` already
does, so it adds a consumer of that gap rather than widening it; scoping the Action
Hub belongs with SE-0's cross-tenant item, which covers the same class platform-wide.
Stated here because an unremarked reuse is how a known gap becomes an assumed
guarantee.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:                                  # pragma: no cover
    from aughor.monitors.models import Monitor, MonitorAlert
    from aughor.notifications.models import ActionLog

logger = logging.getLogger(__name__)

#: The default, and the historical behaviour: persist + emit on the event spine, and
#: send nothing outward. Any other value names an Action Hub trigger.
IN_APP = "in_app"


def _deep_link(alert: "MonitorAlert") -> str:
    """A link back to the monitor that fired, or "" when we cannot know one.

    The API does not otherwise know its own public web origin, so this is opt-in via
    ``AUGHOR_WEB_URL``. Empty beats guessed: a Slack message carrying a link to
    ``localhost`` is worse than one carrying no link."""
    base = os.environ.get("AUGHOR_WEB_URL", "").strip().rstrip("/")
    if not base:
        return ""
    from urllib.parse import urlencode
    q = {"tab": "monitors"}
    if alert.conn_id:
        q["conn"] = alert.conn_id
    return f"{base}/?{urlencode(q)}"


def _threshold_phrase(alert: "MonitorAlert") -> str:
    """"12.4 vs threshold 10.0" — the comparison, not just the number. A receiver
    routing on magnitude needs both sides, and a human reading the Slack line needs
    to know whether 12.4 is bad."""
    cur = alert.current_value
    if cur is None:
        return alert.message
    parts = [f"{cur:g}"]
    if alert.threshold is not None:
        parts.append(f"vs threshold {alert.threshold:g}")
    if alert.previous_value is not None:
        parts.append(f"(previous {alert.previous_value:g})")
    return " ".join(parts)


def alert_context(alert: "MonitorAlert") -> dict:
    """The alert's facts as the webhook body's ``context`` — severity, the value
    against its threshold, the connection, and a deep link. Kept separate from the
    prose ``recommendation`` so a receiver can ROUTE on it (n8n's IF node reads
    ``context.severity``; it cannot parse a sentence)."""
    return {
        "kind":           "monitor_alert",
        "alert_id":       alert.id,
        "monitor_id":     alert.monitor_id,
        "monitor_name":   alert.monitor_name,
        "severity":       alert.severity,
        "alert_on":       alert.alert_on,
        "metric_name":    alert.metric_name,
        "current_value":  alert.current_value,
        "previous_value": alert.previous_value,
        "threshold":      alert.threshold,
        "conn_id":        alert.conn_id,
        "triggered_at":   alert.triggered_at,
        "message":        alert.message,
        "caveat":         getattr(alert, "caveat", None),
        "deep_link":      _deep_link(alert),
    }


def dispatch_alert(alert: "MonitorAlert", monitor: Optional["Monitor"] = None) -> Optional["ActionLog"]:
    """Deliver a fired alert through its monitor's configured channel.

    Returns the ``ActionLog`` when a send was attempted, else None (in-app monitors,
    an unresolvable monitor, an unknown trigger). Never raises: this runs immediately
    after the alert is committed, and a delivery problem must not look like a monitor
    that failed to fire.
    """
    try:
        if monitor is None:
            from aughor.monitors.store import get_monitor
            monitor = get_monitor(alert.monitor_id)
        if monitor is None:
            return None

        channel = (monitor.notification_channel or IN_APP).strip()
        if not channel or channel == IN_APP:
            return None

        from aughor.notifications.store import get_trigger
        trigger = get_trigger(channel)
        if trigger is None:
            # A monitor pointing at a deleted trigger is a configuration error, and a
            # silent one is how this field spent its whole life. Say so once per fire.
            logger.warning(
                "monitor %s (%s) notifies via trigger %r, which does not exist — "
                "alert %s was persisted but not delivered",
                monitor.id, monitor.name, channel, alert.id)
            return None

        from aughor.notifications.executor import fire_action
        from aughor.notifications.models import ActionPayload

        log = fire_action(trigger, ActionPayload(
            investigation_id=f"monitor:{alert.monitor_id}",
            rec_index=0,
            recommendation=(f"{alert.monitor_name or 'Monitor'} "
                            f"[{alert.severity}]: {_threshold_phrase(alert)}"),
            metric_name=alert.metric_name or "",
            headline=alert.message,
            trigger_id=trigger.id,
            triggered_at=alert.triggered_at,
            # The alert id, not a fresh timestamp: `_post` retries twice on a 15s
            # timeout, and a slow-but-successful receiver must be able to tell that
            # retry from a genuinely new alert. One alert, one delivery key, forever.
            delivery_key=f"monitor-alert:{alert.id}",
            context=alert_context(alert),
        ))
        if getattr(log, "status", "") != "ok":
            logger.warning("monitor alert %s delivery to %r ended %s: %s",
                           alert.id, trigger.name, log.status, log.error or "")
        return log
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "monitor alert delivery is fail-open; the alert row is already "
                      "committed and remains the source of truth",
                 counter="monitors.notify")
        return None
