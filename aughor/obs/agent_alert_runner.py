"""Run an agent alert rule: read its window, evaluate it, record it, deliver it.

:mod:`aughor.obs.agent_alerts` is pure — a metric, a threshold, a verdict, no I/O. This
module is the half that was missing: where the rows come from, what gets written down, and
which channel hears about it. Nothing here re-implements a channel; delivery is the Action
Hub trigger the monitors plane already sends through.

Three decisions worth keeping:

**Runner jobs are excluded from the population.** The automation heartbeat outnumbers agent
work by roughly 45:1, so an error rate computed over every job in the window is an error
rate for the tick loop wearing the fleet's name. ``timeseries.job_rows`` already splits the
two reads for exactly this reason; alerting takes the agent side.

**The event row is written before delivery is attempted.** A rule that fires while Slack is
down must still leave something in Attention. The row is the alert; delivery is a
consequence of it, and ``mark_delivered`` records which happened.

**The debounce clock is stamped on NOTIFY, not on match.** ``evaluate`` already makes that
distinction; this module must not blur it by stamping every time the threshold is crossed,
or a persistently-bad condition would go quiet after one tick and never speak again.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from aughor.obs.agent_alerts import (
    AgentAlertEvent,
    AgentAlertRule,
    Verdict,
    evaluate,
    event_from_verdict,
)

logger = logging.getLogger(__name__)

#: Cap on the session-log read behind a `cost_usd` rule. A window is minutes wide, so this
#: is generous; it exists so a misconfigured 7-day window cannot pull the whole log into
#: memory on a heartbeat.
CALL_READ_LIMIT = 5000


def window_rows(rule: AgentAlertRule, *, now: Optional[datetime] = None
                ) -> tuple[list[dict], list[dict], list[dict], bool]:
    """``(agent jobs, priced model calls, guardrail verdicts, truncated)`` over the
    rule's look-back window.

    Model calls and guardrail verdicts are read only for the metrics that need them:
    every other metric answers from the job rows alone, and a session-log scan per rule
    per tick would make the heartbeat pay for facts nobody asked for.
    """
    from aughor.obs.timeseries import job_rows, resolve_window

    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=rule.window_minutes)
    window = resolve_window(since=start.isoformat(), until=now.isoformat())
    agents, _runners, truncated = job_rows(window)

    calls: list[dict] = []
    if rule.metric == "cost_usd":
        calls = priced_calls(window.since, window.until)
    guardrails: list[dict] = []
    if rule.metric in ("guardrail_blocks", "guardrail_block_rate"):
        guardrails = guardrail_verdicts(window.since, window.until)
    return agents, calls, guardrails, truncated


def guardrail_verdicts(since: str, until: str) -> list[dict]:
    """Every guardrail EVALUATION in the window, blocked or not.

    Both halves, because the metric is a rate: recording only the blocks would leave a
    numerator with no denominator, and an agent nothing ever checked would be
    indistinguishable from one that always passed.
    """
    from aughor.govern.guardrails import EVENT_KIND
    from aughor.kernel.ledger import Ledger

    rows = Ledger.default().session_events(kind=EVENT_KIND, since=since, until=until,
                                           limit=CALL_READ_LIMIT)
    out: list[dict] = []
    for r in rows:
        row = dict(r)
        payload = row.get("payload")
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        payload = payload if isinstance(payload, dict) else {}
        row["blocked"] = bool(payload.get("blocked"))
        row["guardrail"] = payload.get("guardrail") or row.get("name") or ""
        # The column wins over the payload copy: `session_event_insert` promotes the
        # ambient agent identity to a column, and a payload written by a caller that had
        # no agent in context would otherwise blank it.
        row["agent_id"] = row.get("agent_id") or payload.get("agent_id") or ""
        out.append(row)
    return out


def priced_calls(since: str, until: str) -> list[dict]:
    """Model calls in the window, each carrying ``cost_usd`` — or None where we cannot price it.

    ``None`` rather than 0.0 is the whole point: a backend that reports no usage, or a model
    with no price on file, is a call whose cost is UNKNOWN. ``measure`` counts those as
    coverage rather than folding them into the bill, and it can only do that if this
    function refuses to invent a number.
    """
    from aughor.kernel.ledger import Ledger
    from aughor.obs.session_log import LLM_CALL
    from aughor.obs.usage import price_for

    rows = Ledger.default().session_events(kind=LLM_CALL, since=since, until=until,
                                           limit=CALL_READ_LIMIT)
    out: list[dict] = []
    for r in rows:
        row = dict(r)
        price = price_for(str(row.get("provider") or ""), str(row.get("model") or ""))
        if price is None or row.get("total_tokens") is None:
            row["cost_usd"] = None
        else:
            pt = int(row.get("prompt_tokens") or 0)
            ct = int(row.get("completion_tokens") or 0)
            row["cost_usd"] = ((pt / 1_000_000.0) * price.input_per_1m
                               + (ct / 1_000_000.0) * price.output_per_1m)
        out.append(row)
    return out


def deliver(event: AgentAlertEvent, rule: AgentAlertRule) -> tuple[bool, str]:
    """Send a fired alert through the rule's channel. Returns ``(delivered, detail)``.

    Never raises. The event row is already committed when this runs, and a delivery
    problem must not read as a rule that failed to fire — the same fail-open contract
    ``monitors.notify.dispatch_alert`` keeps, for the same reason.
    """
    channel = (rule.channel or "").strip()
    if not channel:
        return False, "in-app only (no channel configured)"
    try:
        from aughor.notifications.executor import fire_action
        from aughor.notifications.models import ActionPayload
        from aughor.notifications.store import get_trigger

        trigger = get_trigger(channel)
        if trigger is None:
            # A rule pointing at a deleted trigger is a configuration error, and a silent
            # one is indistinguishable from a channel that works.
            logger.warning("agent alert rule %s (%s) notifies via trigger %r, which does "
                           "not exist — alert %s was recorded but not delivered",
                           rule.id, rule.name, channel, event.id)
            return False, f"unknown trigger: {channel}"

        log = fire_action(trigger, ActionPayload(
            investigation_id=f"agent_alert:{rule.id}",
            rec_index=0,
            recommendation=f"{rule.name} [{event.severity}]: {event.reason}",
            metric_name=event.metric,
            headline=rule.name,
            trigger_id=trigger.id,
            triggered_at=event.fired_at,
            # The event id, never a fresh timestamp: the HTTP layer retries, and a slow
            # receiver has to be able to tell that retry from a genuinely new alert.
            delivery_key=f"agent-alert:{event.id}",
            context=alert_context(event, rule),
        ))
        status = str(getattr(log, "status", ""))
        if status == "timeout":
            # It may have arrived. Reporting failure would license a retry, and a retried
            # maybe-delivered webhook is the duplicate this layer exists to prevent.
            return False, "delivery timed out — it may already have been delivered"
        if status != "ok":
            return False, f"{status}: {getattr(log, 'error', '') or ''}"[:500]
        return True, f"delivered via {trigger.name}"
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent alert delivery is fail-open; the event row is already "
                      "committed and remains the source of truth",
                 counter="obs.agent_alerts.deliver")
        return False, f"{type(exc).__name__}: {exc}"[:500]


def alert_context(event: AgentAlertEvent, rule: AgentAlertRule) -> dict:
    """The alert's facts as structured context, beside the prose.

    Separate from ``recommendation`` so a receiver can ROUTE on it — an IF node reads
    ``context.severity``; it cannot parse a sentence. ``population`` travels with it
    because an alert that cannot state its denominator is a number nobody can check.
    """
    return {
        "kind": "agent_alert",
        "event_id": event.id,
        "rule_id": rule.id,
        "rule_name": rule.name,
        "severity": event.severity,
        "metric": event.metric,
        "value": event.value,
        "threshold": event.threshold,
        "comparator": rule.comparator,
        "population": event.population,
        "window_minutes": event.window_minutes,
        "agent_id": rule.agent_id,
        "charter_id": rule.charter_id,
        "observed": event.observed,
        "fired_at": event.fired_at,
        "message": event.reason,
    }


def run_rule(rule: AgentAlertRule, *, now: Optional[datetime] = None,
             suppress: bool = True) -> tuple[Verdict, Optional[AgentAlertEvent]]:
    """Evaluate one rule and, when it should notify, record and deliver the alert.

    ``suppress=True`` honours the rule's quiet period — what the heartbeat wants.
    ``suppress=False`` is the operator's "test this rule now" button: it still records
    nothing unless the threshold is genuinely crossed, but it ignores the debounce so a
    condition that is currently muted can still be shown working. That is the same split
    ``monitors.scheduler.trigger_now`` makes.

    **The quiet period is stamped whenever an alert is RECORDED, on either path.** The clock
    means "when did we last reach out", and a Test click reaches out — it delivers through
    the real channel, exactly as the adopted monitor's Test does. Stamping only the
    heartbeat path would leave Test as a debounce-free button that pages a human as fast as
    it can be clicked. An in-app rule counts too: an alert appearing in Attention is the
    notification, and a flood of those is still a flood.
    """
    from aughor.obs import agent_alert_store as store

    now = now or datetime.now(timezone.utc)
    jobs, calls, guardrails, truncated = window_rows(rule, now=now)
    verdict = evaluate(rule, jobs, calls=calls, guardrails=guardrails, now=now)

    if truncated:
        # A capped read makes the population a floor, not a total. Say so on the verdict
        # rather than letting a threshold be crossed by an artefact of the cap.
        verdict.reason += " (window read hit its cap — population is a floor)"

    should_record = verdict.should_notify or (verdict.matched and not suppress)
    if not should_record:
        return verdict, None

    event = event_from_verdict(rule, verdict, fired_at=now.isoformat())
    event = event.model_copy(update={"org_id": _current_org()})
    event = store.append_event(event)

    store.mark_notified(rule.id, now.isoformat())

    delivered, detail = deliver(event, rule)
    store.mark_delivered(event.id, delivered=delivered, detail=detail)
    return verdict, event.model_copy(update={"delivered": delivered,
                                             "delivery_detail": detail})


def run_rule_by_id(rule_id: str, *, now: Optional[datetime] = None,
                   suppress: bool = True) -> tuple[Optional[Verdict], Optional[AgentAlertEvent]]:
    """``run_rule`` for a stored id. ``(None, None)`` when the rule is gone or disabled."""
    from aughor.obs import agent_alert_store as store

    rule = store.get_rule(rule_id)
    if rule is None or not rule.enabled:
        return None, None
    return run_rule(rule, now=now, suppress=suppress)


def _current_org() -> str:
    try:
        from aughor.org.context import current_org_id
        return str(current_org_id() or "")
    except Exception:
        logger.debug("agent alerts: no ambient org", exc_info=True)
        return ""
