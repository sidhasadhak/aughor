"""The scheduler's serverless face — one cron-driven tick over every job family.

On an always-on process, APScheduler owns the clock (monitor crons, brief crons,
the automation heartbeat, hourly matcache eviction). A serverless instance has no
standing clock, so an EXTERNAL one calls this endpoint and ONE tick of each
family runs — the same underlying job functions the in-process schedulers call,
so behaviour is identical; only who-holds-the-clock changes. The clock is tiered
to the plan: Vercel Cron provides the guaranteed daily floor (Hobby allows no
finer), and a GitHub Actions schedule (.github/workflows/cron-tick.yml) drives
~10-minute ticks, each passing its interval as ``window_s``. The in-process
schedulers are gated OFF under ``VERCEL`` (api.py lifespan), because a warm
instance running both would double-tick.

Auth: Vercel sends ``Authorization: Bearer $CRON_SECRET`` when that env var exists
on the project. A deployment without the secret refuses to serve the endpoint at
all rather than running unauthenticated — a public URL that triggers LLM-spending
deliveries is not a degradation, it is an open faucet. Locally (no VERCEL, no
secret) the endpoint stays callable for tests and manual ticks.

Due-ness for cron-scheduled families is computed with APScheduler's own
``CronTrigger`` (already a dependency): an entry is due when its next fire time
falls inside the caller's lookback window. The tick is IDEMPOTENT per family: monitors
window their alerts, brief delivery de-duplicates per period, the automation tick
re-checks conditions — so a double-fired minute is safe, matching the at-least-once
posture everything else in Phase 2 adopted.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cron"])


def _due_in_window(cron_expr: str, now: datetime, window_s: int) -> bool:
    """Whether a crontab expression fired inside the LOOKBACK window ending now.

    The window, not the minute, because who holds the clock varies by tier: a
    minute-grained scheduler passes 60; the Hobby-tier reality is a GitHub Actions
    schedule every ~10 minutes plus Vercel's daily floor, each passing its own
    interval — an entry due anywhere in the gap fires on the next tick
    (at-least-once, matching the platform's delivery posture)."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        end = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        start = end - timedelta(seconds=max(60, window_s) + 60)
        trigger = CronTrigger.from_crontab(cron_expr, timezone="UTC")
        nxt = trigger.get_next_fire_time(None, start)
        return nxt is not None and nxt < end
    except Exception as exc:
        tolerate(exc, "an unparseable cron expression is skipped, not fatal to the tick",
                 counter="cron.bad_expr")
        return False


# GET only, deliberately: both real callers (Vercel Cron, the Actions curl) GET,
# and a two-method api_route makes FastAPI emit colliding operationIds — the
# generated TS client carried `cron_tick_cron_tick_get` TWICE, failing typecheck,
# the web build, and the drift check nondeterministically.
@router.get("/cron/tick")
def cron_tick(request: Request, window_s: int = 60) -> dict:
    """Run one tick of every scheduled family. Returns per-family counts.

    ``window_s`` is the caller's own tick interval — entries whose cron fired
    within that lookback are due now."""
    secret = os.environ.get("CRON_SECRET", "")
    if secret:
        if request.headers.get("authorization", "") != f"Bearer {secret}":
            raise HTTPException(status_code=401, detail="bad cron credential")
    elif os.environ.get("VERCEL"):
        raise HTTPException(status_code=403, detail="CRON_SECRET is not configured")

    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    # Automations — the heartbeat's own tick scans due automations itself.
    try:
        from aughor.automations.scheduler import tick_once
        tick_once()
        counts["automations_tick"] = 1
    except Exception as exc:
        tolerate(exc, "automation tick is fault-isolated within the cron tick",
                 counter="cron.automations")

    # Monitors — each enabled monitor whose cron fired in the window.
    try:
        from aughor.monitors.scheduler import run_monitor_job
        from aughor.monitors.store import list_monitors
        n = 0
        for m in list_monitors():
            if getattr(m, "enabled", True) and _due_in_window(m.check_cron, now, window_s):
                run_monitor_job(m.id)
                n += 1
        counts["monitors_run"] = n
    except Exception as exc:
        tolerate(exc, "monitor ticks are fault-isolated within the cron tick",
                 counter="cron.monitors")

    # Briefs — each enabled subscription whose cron fired in the window.
    try:
        from aughor.briefing.scheduler import trigger_now
        from aughor.briefing.store import list_subscriptions
        n = 0
        for sub in list_subscriptions():
            if getattr(sub, "enabled", True) and _due_in_window(sub.resolved_cron(), now, window_s):
                trigger_now(sub.id)
                n += 1
        counts["briefs_delivered"] = n
    except Exception as exc:
        tolerate(exc, "brief deliveries are fault-isolated within the cron tick",
                 counter="cron.briefs")

    # Kernel supervisor — cheap and idempotent; a lapsed lease is an orphan
    # wherever it ran, and no always-on process sweeps for us here.
    try:
        from aughor.kernel.jobs import kernel
        counts["stale_jobs_swept"] = kernel().sweep_stale()
    except Exception as exc:
        tolerate(exc, "the stale sweep is fault-isolated within the cron tick",
                 counter="cron.sweep")

    # Matcache eviction — hourly housekeeping; fires when a tick window crosses
    # the top of an hour (the daily floor tick always qualifies).
    if now.minute * 60 < max(60, window_s) or now.minute == 0:
        try:
            from aughor.monitors.scheduler import evict_matcache_once
            evict_matcache_once()
            counts["matcache_evicted"] = 1
        except Exception as exc:
            tolerate(exc, "matcache eviction is fault-isolated within the cron tick",
                     counter="cron.matcache")

    logger.info("cron tick: %s", counts)
    return {"ok": True, "at": now.isoformat(), "counts": counts}
