"""APScheduler wrapper for scheduled brief delivery.

Mirrors aughor.monitors.scheduler. Public helpers:
    reload_subscription(sub) — add/replace a subscription's cron job
    remove_subscription(id)  — remove a job when a sub is deleted/disabled
    trigger_now(id)          — deliver a brief immediately (for the test endpoint)
    start() / stop()         — lifecycle (called from api.py startup)
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from aughor.briefs.models import BriefSubscription

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"misfire_grace_time": 3600})
_started = False


def _make_job_fn(sub_id: str):
    def _job():
        try:
            from aughor.briefs.store    import get_subscription
            from aughor.briefs.delivery import deliver_subscription
            from aughor.db.registry     import get_connection_org
            from aughor.org.context     import using_org
            sub = get_subscription(sub_id)
            if sub is None or not sub.enabled:
                return
            # DATA-06: a background delivery has no request context — bind the
            # subscription's tenant (its connection's org) so the digest is built and
            # any persisted trace stamps the right org (mirrors the monitor scheduler).
            org = get_connection_org(sub.conn_id) or ""

            def _work():
                with using_org(org):
                    result = deliver_subscription(sub)
                logger.info("Brief '%s' delivered [%s]", sub.name, result.get("status"))

            # WP-7: under `ops.metered_monitors`, deliver as a supervised Briefer job so the
            # brief's synthesis LLM calls + warehouse SQL are metered + budget-enforced.
            from aughor.kernel.flags import flag_enabled
            if flag_enabled("ops.metered_monitors"):
                from aughor.kernel.jobs import submit_background_tick
                job_id = submit_background_tick(
                    "brief", _work, conn_id=sub.conn_id, org_id=org,
                    idempotency_key=f"brief:{sub_id}")
                if job_id is not None:
                    return   # routed through the kernel
            _work()          # legacy / no-loop fallback
        except Exception as exc:
            logger.error("Brief job %s crashed: %s", sub_id, exc)

    _job.__name__ = f"brief_job_{sub_id}"
    return _job


def reload_subscription(sub: BriefSubscription) -> None:
    """Add or replace the cron job for *sub*."""
    job_id = f"brief_{sub.id}"
    try:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
        if sub.enabled:
            _scheduler.add_job(
                _make_job_fn(sub.id),
                trigger=CronTrigger.from_crontab(sub.resolved_cron(), timezone="UTC"),
                id=job_id,
                name=sub.name,
                replace_existing=True,
            )
            logger.debug("Scheduled brief '%s' (%s)", sub.name, sub.resolved_cron())
    except Exception as exc:
        logger.warning("Failed to schedule brief '%s': %s", sub.name, exc)


def remove_subscription(sub_id: str) -> None:
    job_id = f"brief_{sub_id}"
    try:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
    except Exception as exc:
        logger.warning("Failed to remove brief job %s: %s", sub_id, exc)


def trigger_now(sub_id: str) -> Optional[dict]:
    """Deliver a brief immediately (synchronous, for the API test endpoint)."""
    try:
        from aughor.briefs.store    import get_subscription
        from aughor.briefs.delivery import deliver_subscription
        from aughor.db.registry     import get_connection_org
        from aughor.org.context     import using_org
        sub = get_subscription(sub_id)
        if not sub:
            return None
        with using_org(get_connection_org(sub.conn_id) or ""):  # DATA-06: bind the sub's tenant
            return deliver_subscription(sub)
    except Exception as exc:
        logger.error("trigger_now failed for brief %s: %s", sub_id, exc)
        return None


def start() -> None:
    """Load all enabled subscriptions and start the background scheduler."""
    global _started
    if _started:
        return
    try:
        from aughor.briefs.store import list_subscriptions
        subs = list_subscriptions()
        enabled = [s for s in subs if s.enabled]
        for sub in enabled:
            reload_subscription(sub)
        _scheduler.start()
        _started = True
        logger.info("Brief scheduler started — %d/%d subscription(s) scheduled",
                    len(enabled), len(subs))
    except Exception as exc:
        logger.warning("Brief scheduler failed to start (non-fatal): %s", exc)


def stop() -> None:
    global _started
    if _started:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "scheduler shutdown is best-effort; the process is stopping anyway",
                     counter="briefs.scheduler.stop")
        _started = False


brief_scheduler = _scheduler
