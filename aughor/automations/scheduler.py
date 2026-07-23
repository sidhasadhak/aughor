"""Wave A2 — the automation heartbeat.

Deliberately **one interval job, not one cron job per automation** — the opposite of what
:mod:`aughor.monitors.scheduler` and :mod:`aughor.briefs.scheduler` do, and the reason those two
could never merge. A per-automation cron job can only ever encode a *time* condition, so an
automation whose trigger is "revenue dropped" or "new rows landed" has nothing to register. A single
heartbeat that asks each enabled automation "are your conditions true?" handles time and non-time
conditions with one mechanism, and a ``schedule`` condition stays exact because
:func:`~aughor.automations.engine._schedule_fired` asks whether the cron matched *since the last
run*, not whether this instant is the cron minute.

The whole subsystem is gated on ``automations.engine``: off ⇒ the heartbeat never starts and this
module is inert.
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


def _tick() -> None:
    """Evaluate every enabled automation once. One automation's failure never stops the rest."""
    try:
        from aughor.automations.store import list_automations
        automations = list_automations(enabled_only=True)
    except Exception as exc:
        logger.warning("automation heartbeat could not load automations: %s", exc)
        return

    for automation in automations:
        try:
            _run_one(automation)
        except Exception as exc:
            logger.error("automation %s (%s) crashed the tick: %s",
                         automation.id, automation.name, exc)


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

    from aughor.kernel.flags import flag_enabled
    if flag_enabled("ops.metered_monitors"):
        from aughor.kernel.jobs import submit_background_tick
        job_id = submit_background_tick(
            "automation", _work, conn_id=automation.conn_id, org_id=org,
            idempotency_key=f"automation:{automation.id}")
        if job_id is not None:
            return       # routed through the kernel
    _work()              # legacy / no-loop fallback


def trigger_now(automation_id: str) -> Optional[AutomationRun]:
    """Run one automation immediately (synchronous, for the API test endpoint).

    Unlike the heartbeat this does NOT skip a disabled or paused automation — it runs it through
    the same gates and hands back the resulting run, so an operator asking "why isn't this firing?"
    gets the reason rather than silence.
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
            return run_automation(automation)
    except Exception as exc:
        logger.error("trigger_now failed for automation %s: %s", automation_id, exc)
        return None


def start() -> None:
    """Start the heartbeat, if the flag is on."""
    global _started
    if _started:
        return
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("automations.engine"):
        logger.debug("automation engine disabled — heartbeat not started")
        return
    try:
        _scheduler.add_job(
            _tick,
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
