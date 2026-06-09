"""Brief delivery — build a connection's digest and push it through an Action Hub
trigger (Slack / webhook / Jira), then record the outcome on the subscription.

Reuses aughor.actions.executor.fire_action so delivery retry/logging is shared
with recommendation execution and finding-sharing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aughor.briefs.models import BriefSubscription

logger = logging.getLogger(__name__)

_HEADLINE_CAP = 1500   # keep delivery payloads channel-friendly


from aughor.util.time import now_iso_z as _now


def build_brief_payload(sub: BriefSubscription):
    """Build (summary, markdown, digest) for a subscription's connection.

    summary  — one-line headline suitable for a Slack message / webhook field
    markdown — the full rendered digest (truncated for the delivery field)
    digest   — the DigestResult (for callers that want structured access)
    """
    from aughor.monitors.digest import build_digest
    digest = build_digest(conn_id=sub.conn_id, period=sub.period)
    md = digest.to_markdown()
    period_label = f"{sub.period.capitalize()}ly"
    bits = []
    if digest.alert_count:
        bits.append(f"{digest.alert_count} alert(s)")
    if digest.critical_count:
        bits.append(f"{digest.critical_count} critical")
    populated = [s for s in digest.sections if s.items]
    if populated:
        bits.append(f"{len(populated)} section(s)")
    tail = " · ".join(bits) if bits else "no significant activity"
    summary = f"{period_label} Intelligence Brief — {tail}"
    return summary, md, digest


def deliver_subscription(sub: BriefSubscription, *, persist: bool = True) -> dict:
    """Build + send the brief for *sub*. Records last_sent_at/status when persist.

    Returns {status, http_status, error, summary, markdown}. Never raises — a
    delivery failure is captured in the returned dict and on the subscription.
    """
    import datetime as _dt
    from aughor.actions.store    import get_trigger
    from aughor.actions.models   import ActionPayload
    from aughor.actions.executor import fire_action
    from aughor.briefs.store     import save_subscription

    result = {"status": "failed", "http_status": None, "error": None,
              "summary": None, "markdown": None}

    trigger = get_trigger(sub.trigger_id)
    if trigger is None:
        result["error"] = "Delivery trigger not found"
    else:
        try:
            summary, md, _digest = build_brief_payload(sub)
            result["summary"] = summary
            result["markdown"] = md
            payload = ActionPayload(
                investigation_id=f"brief:{sub.id}", rec_index=0,
                recommendation=summary,
                metric_name=sub.conn_id,
                headline=md[:_HEADLINE_CAP],
                trigger_id=sub.trigger_id,
                triggered_at=_dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            )
            log = fire_action(trigger, payload)
            result["status"] = log.status
            result["http_status"] = log.http_status
            result["error"] = log.error
        except Exception as exc:  # digest build / delivery crash — non-fatal
            logger.error("Brief delivery for sub %s crashed: %s", sub.id, exc)
            result["error"] = str(exc)

    if persist:
        sub.last_sent_at = _now()
        sub.last_status = result["status"]
        sub.last_error = result["error"]
        try:
            save_subscription(sub)
        except Exception:
            pass

    return result
