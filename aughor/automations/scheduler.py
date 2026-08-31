"""Wave A2 — the automation heartbeat.

Deliberately **one interval job, not one cron job per automation** — the opposite of what
the legacy monitor and brief schedulers did, and the reason those two could never merge.
A per-automation cron job can only ever encode a *time* condition, so an automation whose
trigger is "revenue dropped" or "new rows landed" has nothing to register. A single
heartbeat that asks each enabled automation "are your conditions true?" handles time and
non-time conditions with one mechanism, and a ``schedule`` condition stays exact because
:func:`~aughor.automations.engine._schedule_fired` asks whether the cron matched *since the
last run*, not whether this instant is the cron minute.

Since flag endgame Wave 4 (2026-08-06) this is the ONLY loop: monitors and brief
subscriptions ride every tick as virtual automations (:mod:`aughor.automations.adopt`),
their legacy per-object schedulers deleted.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from aughor.automations.models import AutomationRun

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"misfire_grace_time": 300})
_started = False

#: How often the heartbeat asks every automation whether it should fire. One minute is the finest
#: grain a cron expression can express, so a coarser tick would make ``schedule`` conditions late.
TICK_SECONDS = 60


def tick_once() -> dict[str, int]:
    """Evaluate every enabled automation once. One automation's failure never stops the rest.

    The same tick ALSO runs every enabled monitor and brief subscription as a virtual
    automation (adoption is permanent — flag endgame Wave 4, 2026-08-06; the legacy
    per-object schedulers were deleted, so this is the ONE loop). Returns per-family
    counts of what was evaluated — each object's own ``schedule`` condition decides
    whether it actually fires — so a caller holding an external clock (``/cron/tick``)
    can report a tick that did something distinguishable from one that found nothing."""
    from aughor.automations.adopt import (
        AGENT_ALERT_PREFIX,
        BRIEF_PREFIX,
        MONITOR_PREFIX,
        list_adopted_automations,
    )

    try:
        from aughor.automations.store import list_automations
        automations = list_automations(enabled_only=True)
    except Exception as exc:
        logger.warning("automation heartbeat could not load automations: %s", exc)
        automations = []

    try:
        automations = list(automations) + list_adopted_automations()
    except Exception as exc:
        logger.warning("automation heartbeat could not adopt legacy objects: %s", exc)

    # A family per adopted kind, not one bucket: "the tick evaluated 40 automations" is not
    # an answer to "is the alert plane running", and a caller holding an external clock has
    # nothing else to read.
    counts = {"automations": 0, "monitors": 0, "briefs": 0, "agent_alerts": 0}
    for automation in automations:
        aid = str(automation.id)
        if aid.startswith(MONITOR_PREFIX):
            counts["monitors"] += 1
        elif aid.startswith(BRIEF_PREFIX):
            counts["briefs"] += 1
        elif aid.startswith(AGENT_ALERT_PREFIX):
            counts["agent_alerts"] += 1
        else:
            counts["automations"] += 1
        try:
            _run_one(automation)
        except Exception as exc:
            logger.error("automation %s (%s) crashed the tick: %s",
                         automation.id, automation.name, exc)
    return counts


def _run_one(automation) -> None:
    """Run one automation with its tenant bound, metered as a supervised job when possible.

    DATA-06: a background tick carries no request context, so ``current_org_id()`` would default to
    'default' and mis-stamp the emitted ``automation.run`` event. Re-bind the automation's tenant
    (its connection's org) for the run — the same re-bind the monitor and brief schedulers do.
    """
    from aughor.automations.engine import run_automation
    from aughor.db.registry import get_connection_org
    from aughor.org.context import using_org

    org = get_connection_org(automation.conn_id) or ""

    def _work():
        with using_org(org):
            run_automation(automation)

    # Serverless: run the work INLINE, before the tick responds. The kernel path
    # only awaits the SUBMIT — the work itself becomes an asyncio task, and Vercel
    # freezes the instance the moment /cron/tick returns, so an enqueued delivery
    # may never start. Worse, its job row then sits PENDING under this
    # idempotency key and `submit` hands that same job back on every later tick:
    # one frozen instance wedged the automation permanently. Inline is the
    # no-loop fallback below, chosen deliberately — the cron route's maxDuration
    # is the budget, and the run's own automation_runs row stays the record.
    import os
    if os.environ.get("VERCEL"):
        _work()
        return
    # Metered execution is permanent (flag endgame Wave 2, 2026-08-06; receipt
    # b167bb891764) — the automation runs as a supervised job when the kernel
    # loop is up; _work() stays the no-loop fallback.
    from aughor.kernel.jobs import submit_background_tick
    job_id = submit_background_tick(
        "automation", _work, conn_id=automation.conn_id, org_id=org,
        idempotency_key=f"automation:{automation.id}")
    if job_id is not None:
        return       # routed through the kernel
    _work()              # no-loop fallback


def trigger_now(automation_id: str, run_id: Optional[str] = None) -> Optional[AutomationRun]:
    """Run one automation immediately (synchronous, for the API test endpoint).

    Unlike the heartbeat this does NOT skip a disabled or paused automation — it runs it through
    the same gates and hands back the resulting run, so an operator asking "why isn't this firing?"
    gets the reason rather than silence.

    ``manual=True``: the SCHEDULE is not consulted, because pressing this button is the
    answer to the question a schedule asks. Every other condition still is — a threshold
    or a source change describes the world, and nobody changed the world by clicking.
    The lifecycle gates above are untouched for the reason in the paragraph above: a
    disabled automation should say it is disabled, not run.
    """
    try:
        from aughor.automations.engine import run_automation
        from aughor.automations.store import get_automation
        from aughor.db.registry import get_connection_org
        from aughor.org.context import using_org

        automation = get_automation(automation_id)
        if automation is None:
            return None
        with using_org(get_connection_org(automation.conn_id) or ""):
            return run_automation(automation, manual=True, run_id=run_id)
    except Exception as exc:
        logger.error("trigger_now failed for automation %s: %s", automation_id, exc)
        return None


def start() -> None:
    """Start the heartbeat."""
    global _started
    if _started:
        return
    try:
        _scheduler.add_job(
            tick_once,
            trigger=IntervalTrigger(seconds=TICK_SECONDS),
            id="automation_heartbeat",
            name="automation heartbeat",
            replace_existing=True,
        )
        _scheduler.start()
        _started = True
        logger.info("Automation heartbeat started (every %ds)", TICK_SECONDS)
    except Exception as exc:
        logger.warning("Automation heartbeat failed to start (non-fatal): %s", exc)


def stop() -> None:
    global _started
    if _started:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "scheduler shutdown is best-effort; the process is stopping anyway",
                     counter="automations.scheduler.stop")
        _started = False


automation_scheduler = _scheduler
