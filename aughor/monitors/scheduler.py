"""APScheduler wrapper for monitor execution.

Usage (from api.py startup):

    from aughor.monitors.scheduler import monitor_scheduler
    monitor_scheduler.start()          # load all enabled monitors + schedule jobs

Public helpers:
    reload_monitor(monitor)  — add/replace a single monitor's cron job
    remove_monitor(id)       — remove a job when a monitor is deleted/disabled
    trigger_now(id)          — fire a monitor immediately (for testing)
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from aughor.monitors.models import Monitor, MonitorAlert

logger = logging.getLogger(__name__)

# Module-level singleton
_scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"misfire_grace_time": 300})
_started = False


# ── Job factory ───────────────────────────────────────────────────────────────

def _make_job_fn(monitor_id: str):
    """Return a zero-arg callable that runs the monitor and persists any alert."""

    def _job():
        try:
            from aughor.monitors.store import get_monitor, append_alert
            from aughor.monitors.runner import run_monitor
            from aughor.db.connection import open_connection_for

            monitor = get_monitor(monitor_id)
            if monitor is None or not monitor.enabled:
                return

            db = open_connection_for(monitor.conn_id)
            try:
                alert = run_monitor(monitor, db)
            finally:
                try:
                    db.close()
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "closing the per-tick db handle is best-effort; the monitor result is already computed",
                             counter="monitors.scheduler.tick.db_close")

            if alert is not None:
                append_alert(alert)
                logger.info(
                    "Monitor '%s' fired [%s]: %s",
                    monitor.name, alert.severity, alert.message[:120],
                )
        except Exception as exc:
            logger.error("Monitor job %s crashed: %s", monitor_id, exc)

    _job.__name__ = f"monitor_job_{monitor_id}"
    return _job


# ── Housekeeping ───────────────────────────────────────────────────────────────

def _evict_matcache() -> None:
    """Hourly: drop expired materialized-cache rows so mat_cache.duckdb can't grow
    unbounded (the cache is TTL-on-read; unread entries never expire on their own)."""
    try:
        from aughor.db.matcache import evict_expired
        n = evict_expired()
        if n:
            logger.info("matcache housekeeping evicted %d expired row(s)", n)
    except Exception as exc:
        logger.warning("matcache housekeeping failed (non-fatal): %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def reload_monitor(monitor: Monitor) -> None:
    """Add or replace the cron job for *monitor*."""
    job_id = f"monitor_{monitor.id}"
    try:
        existing = _scheduler.get_job(job_id)
        if existing:
            _scheduler.remove_job(job_id)
        if monitor.enabled:
            _scheduler.add_job(
                _make_job_fn(monitor.id),
                trigger=CronTrigger.from_crontab(monitor.check_cron, timezone="UTC"),
                id=job_id,
                name=monitor.name,
                replace_existing=True,
            )
            logger.debug("Scheduled monitor '%s' (%s)", monitor.name, monitor.check_cron)
    except Exception as exc:
        logger.warning("Failed to schedule monitor '%s': %s", monitor.name, exc)


def remove_monitor(monitor_id: str) -> None:
    """Remove the cron job for a deleted/disabled monitor."""
    job_id = f"monitor_{monitor_id}"
    try:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
    except Exception as exc:
        logger.warning("Failed to remove monitor job %s: %s", monitor_id, exc)


def trigger_now(monitor_id: str) -> Optional[MonitorAlert]:
    """Run a monitor immediately (synchronous, for the API test endpoint)."""
    try:
        from aughor.monitors.store import get_monitor, append_alert
        from aughor.monitors.runner import run_monitor
        from aughor.db.connection import open_connection_for

        monitor = get_monitor(monitor_id)
        if not monitor:
            return None
        db = open_connection_for(monitor.conn_id)
        try:
            # Manual test endpoint — bypass the anti-flap debounce so the user
            # always sees the raw verdict, even within a grace window.
            alert = run_monitor(monitor, db, suppress=False)
        finally:
            try:
                db.close()
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "closing the test-trigger db handle is best-effort; the monitor result is already computed",
                         counter="monitors.scheduler.trigger_now.db_close")
        if alert is not None:
            append_alert(alert)
        return alert
    except Exception as exc:
        logger.error("trigger_now failed for monitor %s: %s", monitor_id, exc)
        return None


def start() -> None:
    """Load all enabled monitors and start the APScheduler background thread."""
    global _started
    if _started:
        return

    try:
        from aughor.monitors.store import list_monitors
        monitors = list_monitors()
        enabled = [m for m in monitors if m.enabled]
        for monitor in enabled:
            reload_monitor(monitor)
        # Background housekeeping that needs a heartbeat but isn't a monitor.
        _scheduler.add_job(
            _evict_matcache,
            trigger=IntervalTrigger(hours=1),
            id="matcache_evict",
            name="matcache eviction",
            replace_existing=True,
        )
        _scheduler.start()
        _started = True
        logger.info(
            "Monitor scheduler started — %d/%d monitor(s) scheduled",
            len(enabled), len(monitors),
        )
    except Exception as exc:
        logger.warning("Monitor scheduler failed to start (non-fatal): %s", exc)


def stop() -> None:
    global _started
    if _started:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "scheduler shutdown is best-effort; the process is stopping anyway",
                     counter="monitors.scheduler.stop")
        _started = False


# Expose the underlying scheduler for inspection
monitor_scheduler = _scheduler
