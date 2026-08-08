"""Monitor execution helpers — the manual trigger, plus background housekeeping.

The legacy per-monitor APScheduler cron path was DELETED 2026-08-06 (flag endgame
Wave 4): every enabled monitor runs through the ONE automation engine as a virtual
automation (`aughor.automations.adopt.monitor_as_automation` — a `schedule` condition
on the monitor's own cron plus a `monitor` effect that replays `run_monitor` with the
anti-flap debounce intact). The heartbeat (`aughor.automations.scheduler`) is the only
loop; `/cron/tick` drives the same tick on serverless. The L4 equivalence receipt
(`65364174a172`) is what made the deletion safe — alerts byte-for-byte across loops,
anti-flap and no-double-fire held over 9/9 scenarios ×3.

What remains here, deliberately:
    trigger_now(id)  — fire a monitor immediately (the API test endpoint); bypasses
                       the debounce so the operator always sees the raw verdict.
    evict_matcache_once() — hourly housekeeping; needs a clock, is not a monitor.
    start() / stop() — the APScheduler thread now carries ONLY the housekeeping job
                       (api.py starts it on always-on processes; /cron/tick calls
                       evict_matcache_once directly on serverless).
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from aughor.monitors.models import MonitorAlert

logger = logging.getLogger(__name__)

# Module-level singleton
_scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"misfire_grace_time": 300})
_started = False


# ── Housekeeping ───────────────────────────────────────────────────────────────

def evict_matcache_once() -> None:
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

def trigger_now(monitor_id: str) -> Optional[MonitorAlert]:
    """Run a monitor immediately (synchronous, for the API test endpoint)."""
    try:
        from aughor.monitors.store import get_monitor, append_alert
        from aughor.monitors.runner import run_monitor
        from aughor.db.connection import open_connection_for
        from aughor.db.registry import get_connection_org
        from aughor.org.context import using_org

        monitor = get_monitor(monitor_id)
        if not monitor:
            return None
        # DATA-06: bind the monitor's tenant for the run (the caller's request org and
        # the connection's org agree once the owner-check passes; binding the
        # connection's org is authoritative and matches the background engine path).
        with using_org(get_connection_org(monitor.conn_id) or ""):
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
    """Start the housekeeping scheduler (matcache eviction only)."""
    global _started
    if _started:
        return

    try:
        _scheduler.add_job(
            evict_matcache_once,
            trigger=IntervalTrigger(hours=1),
            id="matcache_evict",
            name="matcache eviction",
            replace_existing=True,
        )
        _scheduler.start()
        _started = True
        logger.info("Housekeeping scheduler started (matcache eviction hourly)")
    except Exception as exc:
        logger.warning("Housekeeping scheduler failed to start (non-fatal): %s", exc)


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
