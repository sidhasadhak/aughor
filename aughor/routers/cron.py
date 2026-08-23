"""The scheduler's serverless face — one cron-driven tick of the one loop.

On an always-on process, APScheduler owns the clock (the automation heartbeat —
which carries monitors and briefs as virtual automations — plus hourly matcache
eviction). A serverless instance has no standing clock, so an EXTERNAL one calls
this endpoint and one tick runs — the same `tick_once` the heartbeat calls, so
behaviour is identical; only who-holds-the-clock changes. The clock is tiered
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

Due-ness lives in the engine (`_schedule_fired`: did the cron match since the
object's LAST RUN), so a missed external tick is caught up on the next one and
``window_s`` matters only to the hourly-housekeeping gate. The tick is IDEMPOTENT:
monitors debounce their alerts, brief delivery de-duplicates per period, the
automation engine re-checks conditions — so a double-fired minute is safe, matching
the at-least-once posture everything else in Phase 2 adopted.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from aughor.kernel.errors import tolerate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cron"])


# GET only, deliberately: both real callers (Vercel Cron, the Actions curl) GET,
# and a two-method api_route makes FastAPI emit colliding operationIds — the
# generated TS client carried `cron_tick_cron_tick_get` TWICE, failing typecheck,
# the web build, and the drift check nondeterministically.
@router.get("/cron/tick")
def cron_tick(request: Request, window_s: int = 60) -> dict:
    """Run one engine tick (automations + adopted monitors/briefs). Returns counts.

    ``window_s`` is the caller's own tick interval; due-ness is the engine's
    since-last-run check, so the window only gates the hourly housekeeping."""
    secret = os.environ.get("CRON_SECRET", "")
    if secret:
        if request.headers.get("authorization", "") != f"Bearer {secret}":
            raise HTTPException(status_code=401, detail="bad cron credential")
    elif os.environ.get("VERCEL"):
        raise HTTPException(status_code=403, detail="CRON_SECRET is not configured")

    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    # ONE tick of the ONE loop: the automation heartbeat evaluates every enabled
    # automation AND every enabled monitor and brief subscription (virtual adoption —
    # the legacy per-object families this endpoint used to drive separately were
    # deleted with their schedulers, flag endgame Wave 4 2026-08-06; driving them
    # here as well double-delivered a brief that the engine tick also delivered).
    # Due-ness is the engine's own `_schedule_fired` — "did the cron match since the
    # LAST RUN", tracked per object in automation_runs — which out-windows any
    # caller-declared lookback: a missed external tick is caught up on the next one
    # regardless of window_s.
    try:
        from aughor.automations.scheduler import tick_once
        evaluated = tick_once()
        counts["automations_tick"] = 1
        counts["monitors_evaluated"] = evaluated.get("monitors", 0)
        counts["briefs_evaluated"] = evaluated.get("briefs", 0)
        counts["agent_alerts_evaluated"] = evaluated.get("agent_alerts", 0)
    except Exception as exc:
        tolerate(exc, "automation tick is fault-isolated within the cron tick",
                 counter="cron.automations")

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
