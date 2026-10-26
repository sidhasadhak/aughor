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
    trigger_now(id)  — check a monitor immediately (the API test endpoint); bypasses
                       the debounce so the operator always sees the raw verdict, and
                       files nothing: the scheduled check owns the record and the send.
    evict_matcache_once() — hourly housekeeping; needs a clock, is not a monitor.
    backup_state_once() — Arc SV-2's hourly backup of the platform's own state, a job here
                       only while `state.backups` is on (`db/backups.py`). Never on
                       serverless: a warm instance is not a clock, and its disk is not
                       the state's.
    start() / stop() — the APScheduler thread now carries ONLY the housekeeping jobs
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


#: The backup job's id — present on the clock only while `state.backups` is on.
BACKUPS_JOB_ID = "state_backups"


def backup_state_once() -> None:
    """Hourly, behind `state.backups`: back up the state directory if anything changed (Arc SV-2). Re-reads the flag,
    so turning it off stops the next run without a restart."""
    try:
        from aughor.db.backups import run_scheduled
        run_scheduled()
    except Exception as exc:
        logger.warning("state backup failed (non-fatal): %s", exc)


def _sync_backups_job() -> None:
    """Put the backup job on the clock while the flag is on, and take it off when it is not. Run at start and on every
    hourly tick, so a flag turned on in Settings takes effect within the hour, and off it leaves nothing scheduled."""
    try:
        from datetime import datetime, timezone

        from aughor.db.backups import EVERY, FIRST_RUN_AFTER, FLAG
        from aughor.kernel.flags import flag_enabled
        job = _scheduler.get_job(BACKUPS_JOB_ID)
        if flag_enabled(FLAG):
            if job is None:
                _scheduler.add_job(
                    backup_state_once,
                    trigger=IntervalTrigger(seconds=EVERY.total_seconds()),
                    id=BACKUPS_JOB_ID,
                    name="state backups",
                    # Minutes after boot, not an hour: an API restarted more often than hourly would otherwise never
                    # back anything up. `run_scheduled` skips a run within the hour of the last check.
                    next_run_time=datetime.now(timezone.utc) + FIRST_RUN_AFTER,
                    max_instances=1,
                    coalesce=True,
                    replace_existing=True,
                )
        elif job is not None:
            _scheduler.remove_job(BACKUPS_JOB_ID)
    except Exception as exc:
        logger.warning("state backup scheduling failed (non-fatal): %s", exc)


def _hourly_housekeeping() -> None:
    evict_matcache_once()
    _sync_backups_job()


# ── Public API ────────────────────────────────────────────────────────────────

def trigger_now(monitor_id: str) -> Optional[MonitorAlert]:
    """Run a monitor immediately (synchronous, for the API test endpoint)."""
    return trigger_now_read(monitor_id)[0]


def trigger_now_read(monitor_id: str) -> tuple[Optional[MonitorAlert], str]:
    """Run a monitor immediately; the alert it raised (or None) and what it READ, in words — "read 848,860.1 (warning
    below 900,000)" — so "no condition met" is never said without the value it was judged on (the Olist study, Gap 36)."""
    said = ""
    try:
        from aughor.monitors.store import get_monitor
        from aughor.monitors.runner import check_monitor, failure_alert
        from aughor.db.connection import open_connection_for
        from aughor.db.registry import get_connection_org
        from aughor.org.context import using_org

        monitor = get_monitor(monitor_id)
        if not monitor:
            return None, ""
        # DATA-06: bind the monitor's tenant for the run (the caller's request org and
        # the connection's org agree once the owner-check passes; binding the
        # connection's org is authoritative and matches the background engine path).
        with using_org(get_connection_org(monitor.conn_id) or ""):
            db = open_connection_for(monitor.conn_id)
            try:
                # Manual test endpoint — bypass the anti-flap debounce so the user
                # always sees the raw verdict, even within a grace window.
                run = check_monitor(monitor, db, suppress=False)
            finally:
                try:
                    db.close()
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "closing the test-trigger db handle is best-effort; the monitor result is already computed",
                             counter="monitors.scheduler.trigger_now.db_close")
            if run.failed:
                # GM-4 — the test run says its query could not run, rather than "no condition met". Shown,
                # not stored: the scheduled run owns the record and the one alert a failure sends.
                return failure_alert(monitor, run.failed), ""
            from aughor.monitors.runner import reading_words
            said = reading_words(monitor, run)
            # Shown, not filed, as a failure is and a drill is. Filing it sent a real alert past the debounce and made
            # it the "last alert" every later any-change, trend and debounce check compares against.
            return run.alert, said
    except Exception as exc:
        logger.error("trigger_now failed for monitor %s: %s", monitor_id, exc)
        return None, said


def start() -> None:
    """Start the housekeeping scheduler (matcache eviction; state backups while `state.backups` is on)."""
    global _started
    if _started:
        return

    try:
        _scheduler.add_job(
            _hourly_housekeeping,
            trigger=IntervalTrigger(hours=1),
            id="matcache_evict",
            name="matcache eviction",
            replace_existing=True,
        )
        _sync_backups_job()
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
