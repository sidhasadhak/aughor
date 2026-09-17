"""Brief delivery — build a connection's digest and push it through an Action Hub
trigger (Slack / webhook / Jira), then record the outcome on the subscription.

Reuses aughor.notifications.executor.fire_action so delivery retry/logging is shared
with recommendation execution and finding-sharing.
"""
from __future__ import annotations

import logging

from aughor.briefing.models import BriefSubscription

logger = logging.getLogger(__name__)

_HEADLINE_CAP = 1500   # keep delivery payloads channel-friendly


from aughor.util.time import now_iso_z as _now


def build_brief_payload(sub: BriefSubscription):
    """Build (summary, markdown, brief) for a subscription's connection.

    summary  — one-line headline suitable for a Slack message / webhook field
    markdown — the full rendered briefing (truncated for the delivery field)
    brief    — the AlertSummary (for callers that want structured access)
    """
    from aughor.monitors.alert_summary import build_alert_summary
    brief = build_alert_summary(conn_id=sub.conn_id, period=sub.period)
    return brief_summary(sub, brief), brief.to_markdown(), brief


def brief_summary(sub: BriefSubscription, brief) -> str:
    """The one-line headline, counted off the briefing as it will actually leave."""
    period_label = f"{sub.period.capitalize()}ly"
    bits = []
    if brief.alert_count:
        bits.append(f"{brief.alert_count} alert(s)")
    if brief.critical_count:
        bits.append(f"{brief.critical_count} critical")
    populated = [s for s in brief.sections if s.items and getattr(s, "kind", "") != "held"]
    if populated:
        bits.append(f"{len(populated)} section(s)")
    tail = " · ".join(bits) if bits else "no significant activity"
    return f"{period_label} Intelligence Brief — {tail}"


#: Causal relationships from the causal graph carry a strength, never a falsifier's verdict.
CAUSAL_HOLD = ("a causal relationship departs only on a falsifier's verdict, and the causal "
               "graph records none")


def hold_lines(brief, conn_id: str) -> tuple:
    """HB-2 — cut the lines of a briefing that fail a departure law on their own, and say so
    in the briefing. Returns ``(brief without them, the reasons)``.

    Judged by what each section's lines claim: monitor alerts are dated records a person
    declared; findings and recommendations answer to trust, definition and claim type; the
    causal graph's relationships cannot depart at all; a review count is a count. The
    briefing ends by naming how many lines it did not send."""
    from aughor.govern.departure import line_holds
    from aughor.monitors.alert_summary import AlertSummarySection

    kept_sections = []
    reasons: list[str] = []
    cut = 0
    for section in brief.sections:
        kind = getattr(section, "kind", "")
        if kind == "causal_links":
            for line in section.items:
                cut += 1
                reasons.append(f"“{line[:80]}”: {CAUSAL_HOLD}")
            continue
        if kind in ("monitor_alerts", "findings", "recommendations"):
            kept = []
            for line in section.items:
                why = line_holds(line, conn_id=conn_id, declared=kind == "monitor_alerts")
                if why:
                    cut += 1
                    reasons.append(f"“{line[:80]}”: {why[0]}")
                else:
                    kept.append(line)
            if len(kept) != len(section.items):
                section = section.model_copy(update={"items": kept})
        kept_sections.append(section)
    if not cut:
        return brief, reasons
    kept_sections.append(AlertSummarySection(
        title="Held at departure", kind="held",
        items=[f"{cut} line{'s' if cut != 1 else ''} of this briefing did not leave the "
               f"platform — the departures screen records why"]))
    return brief.model_copy(update={"sections": kept_sections}), reasons


def deliver_subscription(sub: BriefSubscription, *, persist: bool = True) -> dict:
    """Build + send the brief for *sub*. Records last_sent_at/status when persist.

    Returns {status, http_status, error, summary, markdown}. Never raises — a
    delivery failure is captured in the returned dict and on the subscription.
    """
    import datetime as _dt
    from aughor.notifications.store    import get_trigger
    from aughor.notifications.models   import ActionPayload
    from aughor.notifications.executor import fire_action
    from aughor.briefing.store     import save_subscription

    result = {"status": "failed", "http_status": None, "error": None,
              "summary": None, "markdown": None}

    trigger = get_trigger(sub.trigger_id)
    if trigger is None:
        result["error"] = "Delivery trigger not found"
    else:
        try:
            from aughor.govern.departure import gate_departure
            from aughor.org.context import current_org_id

            _summary, _md, brief = build_brief_payload(sub)
            # HB-2 — the departure gate, line by line and then whole. A briefing is many
            # claims; the lines that fail a law on their own are cut (causal relationships
            # with no falsifier's verdict, a KPI with no approved definition, a forecast),
            # the rest depart, and the record says what was cut and why.
            brief, held_lines = hold_lines(brief, sub.conn_id)
            summary, md = brief_summary(sub, brief), brief.to_markdown()
            result["summary"] = summary
            result["markdown"] = md
            verdict = gate_departure(
                kind="briefing", org_id=current_org_id(), conn_id=sub.conn_id, text=md,
                target=sub.trigger_id, actor=f"briefing:{sub.id}", source_kind="briefing",
                source_id=sub.id, source_name=sub.name, dated_records=True,
                declared_definition="dated monitor alerts and explorer findings",
                held_lines=held_lines)
            result["departure_id"] = verdict.record_id
            if verdict.held:
                result["status"] = "held"
                result["error"] = f"held at departure — {verdict.reason_sentence()}"
            else:
                payload = ActionPayload(
                    investigation_id=f"brief:{sub.id}", rec_index=0,
                    recommendation=summary,
                    metric_name=sub.conn_id,
                    headline=md[:_HEADLINE_CAP],
                    trigger_id=sub.trigger_id,
                    triggered_at=_dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    context={"receipt": verdict.receipt, "receipt_line": verdict.receipt_line()},
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
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "persisting last_sent/last_status is best-effort; the delivery already happened and is retried next cycle",
                     counter="briefs.delivery.persist", conn_id=sub.conn_id)

    # T3 kernel-leverage: a delivered brief lands on the event spine so the
    # scheduled-subsystem activity is observable (status incl. failures) instead
    # of living only in the subscription's last_status.
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(
            "brief.delivered",
            {"subscription_id": sub.id, "name": sub.name, "period": sub.period,
             "status": result["status"], "error": result["error"]},
            conn_id=sub.conn_id,
        )
    except Exception:
        logger.debug("brief.delivered emit failed", exc_info=True)

    return result
