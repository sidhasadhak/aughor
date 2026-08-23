"""Wave A5 — adopt the two legacy schedulers onto the one engine.

The monitor scheduler and the brief scheduler are near-verbatim copies of each other, each a
per-object cron job driving exactly one hardcoded effect (append an alert / deliver a digest). Wave
A5 makes each legacy object *read as* an :class:`~aughor.automations.models.Automation` and run
through the A2 engine, so there is one loop, one run history, and one place a tick's reason is
recorded — while the legacy code stays present and authoritative until ``automations.adopt_legacy``
flips.

These automations are **virtual**: computed on the fly from the monitor/brief stores, never written
to the automations table. Their ids are stable (``monitor:<id>`` / ``brief:<id>``) so the engine's
``schedule`` condition can read ``last_run`` from the shared ``automation_runs`` table and fire the
cron once per due window — exactly the cadence the legacy per-object cron job had. (``append_run``'s
incidental ``UPDATE automations … WHERE id=?`` matches zero rows for a virtual id, which is a
harmless no-op.)

The translation is faithful by construction:
* a ``Monitor`` → ``schedule(check_cron)`` + a ``monitor`` effect that replays ``run_monitor`` with
  the anti-flap debounce intact (:func:`~aughor.automations.engine._dispatch_monitor`);
* a ``BriefSubscription`` → ``schedule(resolved_cron)`` + the existing ``brief`` effect
  (``deliver_subscription``).
So "engine output equals legacy output" is not a coincidence to test for — it is the same two
functions, called from a different loop.
"""
from __future__ import annotations

import logging

from aughor.automations.models import Automation, Condition, Effect

logger = logging.getLogger(__name__)

MONITOR_PREFIX = "monitor:"
BRIEF_PREFIX = "brief:"
AGENT_ALERT_PREFIX = "agent_alert:"


def monitor_as_automation(monitor) -> Automation:
    """A ``Monitor`` read as a virtual Automation: fire on its cron, run its check + append its alert.

    ``max_retries=0`` — the legacy monitor job never retried a failed tick (the next cron fire was
    the only retry), so a faithful replay must not add retries the operator never had."""
    return Automation(
        id=f"{MONITOR_PREFIX}{monitor.id}",
        conn_id=monitor.conn_id,
        name=monitor.name,
        description=f"adopted monitor {monitor.id}",
        conditions=[Condition(kind="schedule", config={"cron": monitor.check_cron})],
        effects=[Effect(kind="monitor", config={"monitor_id": monitor.id})],
        enabled=monitor.enabled,
        max_retries=0,
    )


def subscription_as_automation(sub) -> Automation:
    """A ``BriefSubscription`` read as a virtual Automation: fire on its cron, deliver the digest.

    ``max_retries=0`` for the same reason (the brief job's only retry was the next cron), and it
    matters more here: a brief delivery is an OUTWARD send, so a retry would risk a duplicate."""
    return Automation(
        id=f"{BRIEF_PREFIX}{sub.id}",
        conn_id=sub.conn_id,
        name=sub.name,
        description=f"adopted brief subscription {sub.id}",
        conditions=[Condition(kind="schedule", config={"cron": sub.resolved_cron()})],
        effects=[Effect(kind="brief", config={"subscription_id": sub.id})],
        enabled=sub.enabled,
        max_retries=0,
    )


def rule_as_automation(rule) -> Automation:
    """An ``AgentAlertRule`` read as a virtual Automation: fire on its cron, evaluate + deliver.

    VA-6 joins the heartbeat the way everything else does. There is one loop in this platform —
    the per-monitor and per-brief schedulers were deleted in Wave 4 precisely so a second one
    could not come back — so an alert plane that arrived with its own timer would be the thing
    that deletion was for.

    ``conn_id=""`` because a rule has no connection: it watches the fleet, scoped by agent or
    charter, and the metrics come from the ledger rather than from a warehouse. ``max_retries=0``
    for the same reason the adopted monitor uses it — the next cron fire is the only retry an
    alert should ever get, and a retried alert is a second page about one condition.
    """
    return Automation(
        id=f"{AGENT_ALERT_PREFIX}{rule.id}",
        conn_id="",
        name=rule.name,
        description=f"adopted agent alert rule {rule.id}",
        conditions=[Condition(kind="schedule", config={"cron": rule.check_cron})],
        effects=[Effect(kind="agent_alert", config={"rule_id": rule.id})],
        enabled=rule.enabled,
        max_retries=0,
    )


def list_adopted_automations() -> list[Automation]:
    """Every enabled monitor and brief subscription, as virtual Automations — what the heartbeat
    runs when ``automations.adopt_legacy`` is on. Best-effort per store: a failure to read one
    store never suppresses the other."""
    out: list[Automation] = []
    try:
        from aughor.monitors.store import list_monitors
        out.extend(monitor_as_automation(m) for m in list_monitors() if m.enabled)
    except Exception as exc:
        logger.warning("adopt: could not read monitors: %s", exc)
    try:
        from aughor.briefing.store import list_subscriptions
        out.extend(subscription_as_automation(s) for s in list_subscriptions() if s.enabled)
    except Exception as exc:
        logger.warning("adopt: could not read brief subscriptions: %s", exc)
    try:
        from aughor.obs.agent_alert_store import list_rules
        out.extend(rule_as_automation(r) for r in list_rules(enabled_only=True))
    except Exception as exc:
        logger.warning("adopt: could not read agent alert rules: %s", exc)
    return out


def adoption_active() -> bool:
    """Always True — monitors and brief subscriptions run through the ENGINE.

    Flag endgame Wave 4 (2026-08-06, user-approved 2026-08-01): the
    `automations.adopt_legacy` flag turned ON and was deleted, and the legacy
    APScheduler loops were deleted WITH it in the same change — the win is one
    loop, not a flag. The L4 equivalence receipt (`65364174a172`, 9/9 stable ×3:
    alerts byte-for-byte, anti-flap and no-double-fire held) is what made the
    flip safe; the function survives as the single consult point so the callers
    that stand the legacy paths down keep one name while those paths are
    dismantled."""
    return True
