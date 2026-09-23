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
    from aughor.monitors.alert_summary import period_adjective
    period_label = period_adjective(sub.period)
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


# ── idea 3: a subscription that sends the Briefing written for its period ───────────────────

_SHEET_TITLES = {"measured": "Headline metrics", "unmeasured": "Not measured",
                 "alerts": "Alerts in this {period}", "records": "Recorded in this {period}",
                 "narrative": "The briefing"}


def render_period_markdown(block: dict, sections: list, cut: int) -> str:
    """A period briefing as it leaves: what it covers and against what, why it ends where it
    does, then each surviving section. Same shape as the alert summary's markdown."""
    period = block.get("period", "period")
    lines = [f"# {block.get('label', '')} Briefing — {block.get('covers', '')}",
             f"*Compared with {block.get('compared_with', '')}. All dates UTC.*"]
    lag = int(block.get("lag_days") or 1)
    if lag > 1:
        lines.append(f"*This {period} ends {lag} days before today: newer days are still "
                     "settling as late rows arrive"
                     + (", a lag the platform measured" if block.get("lag_source") == "learned"
                        else "") + ".*")
    lines.append("")
    for kind, items in sections:
        lines.append(f"## {_SHEET_TITLES.get(kind, kind).format(period=period)}")
        if kind == "narrative":
            lines.extend(p + "\n" for p in items)
        else:
            lines.extend(f"- {item}" for item in items)
            lines.append("")
    if not sections:
        lines.append(f"*Nothing was measured or recorded for this {period}.*")
    if cut:
        lines.append(f"*{cut} line{'s' if cut != 1 else ''} of this briefing did not leave the "
                     "platform — the departures screen records why.*")
    return "\n".join(lines).rstrip() + "\n"


def build_period_departure(sub: BriefSubscription, *, runner=None) -> dict:
    """The period briefing for *sub*, judged line by line before it leaves: the headline
    metrics and the narrative against the period queries RE-RUN now (law 1), alerts as a
    monitor's declared readings, every line for trust, definition and claim type. Returns
    ``{"brief", "summary", "markdown", "held_lines"}``."""
    from aughor.govern.departure import line_holds
    from aughor.knowledge import period_brief

    domain_data, profile = period_brief.connection_inputs(sub.conn_id)
    brief = period_brief.build_period_briefing(
        sub.conn_id, sub.period, scope_key=sub.conn_id, domain_data=domain_data,
        profile=profile, workspace_id=sub.workspace_id or None, runner=runner)
    block = brief.get("period") or {}
    measurement = period_brief.fresh_measurement(sub.conn_id, brief, runner=runner)
    kept: list = []
    held: list[str] = []
    for kind, lines in period_brief.sheet_lines(brief):
        passing = []
        for line in lines:
            why = line_holds(line, conn_id=sub.conn_id, declared=kind == "alerts",
                             measurement=measurement if kind in ("measured", "narrative") else None)
            if why:
                held.append(f"“{line[:80]}”: {why[0]}")
            else:
                passing.append(line)
        if passing:
            kept.append((kind, passing))
    measured = next((len(items) for kind, items in kept if kind == "measured"), 0)
    tail = " · ".join(bit for bit in (
        f"{measured} headline metric{'s' if measured != 1 else ''} measured" if measured else "",
        f"{len(held)} held at departure" if held else "") if bit) or "nothing measured"
    return {"brief": brief, "held_lines": held,
            "summary": f"{block.get('label', '')} Briefing — {block.get('covers', '')} — {tail}",
            "markdown": render_period_markdown(block, kept, len(held))}


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
    elif sub.content == "briefing":
        _deliver_period(sub, trigger, result)
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


def _deliver_period(sub: BriefSubscription, trigger, result: dict) -> None:
    """Send the Briefing written for *sub*'s period through the same departure gate and
    trigger as the alert summary. Refused — and said — while the flag is off: a subscription saved
    as "briefing" never silently degrades into the alert summary. Fills *result* in place."""
    import datetime as _dt
    from aughor.govern.departure import gate_departure
    from aughor.knowledge import period_brief
    from aughor.notifications.executor import fire_action
    from aughor.notifications.models import ActionPayload
    from aughor.org.context import current_org_id

    why = period_brief.refusal(sub.period)
    if why:
        result["error"] = f"not sent — {why}"
        return
    try:
        built = build_period_departure(sub)
        result["summary"], result["markdown"] = built["summary"], built["markdown"]
        verdict = gate_departure(
            kind="briefing", org_id=current_org_id(), conn_id=sub.conn_id,
            text=built["markdown"], target=sub.trigger_id, actor=f"briefing:{sub.id}",
            source_kind="briefing", source_id=sub.id, source_name=sub.name,
            # law 1 ran per line on the measured lines and the narrative (above); the rest are
            # dated records, as in the alert summary
            dated_records=True,
            declared_definition=("each headline metric's own trend query cut to the period; "
                                 "dated monitor alerts and recorded findings"),
            held_lines=built["held_lines"])
        result["departure_id"] = verdict.record_id
        if verdict.held:
            result["status"] = "held"
            result["error"] = f"held at departure — {verdict.reason_sentence()}"
            return
        log = fire_action(trigger, ActionPayload(
            investigation_id=f"brief:{sub.id}", rec_index=0, recommendation=built["summary"],
            metric_name=sub.conn_id, headline=built["markdown"][:_HEADLINE_CAP],
            trigger_id=sub.trigger_id,
            triggered_at=_dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            context={"receipt": verdict.receipt, "receipt_line": verdict.receipt_line()}))
        result["status"], result["http_status"], result["error"] = log.status, log.http_status, log.error
    except Exception as exc:  # the period build / delivery crash — non-fatal, as the alert summary's
        logger.error("Period briefing delivery for sub %s crashed: %s", sub.id, exc)
        result["error"] = str(exc)
