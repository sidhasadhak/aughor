"""WP-6 — continuous exploration: re-arm the Scout when the schema changes or a run
goes stale, so "never stops learning" is true rather than aspirational.

A finished exploration used to be a dead end. A schema change (new tables/columns) or
the simple passage of time never re-triggered the Scout — only a manual POST did
(`api.py`: "Fresh connection explorations still start manually"). New tables and data
went undiscovered until someone restarted exploration by hand.

This adds a periodic tick that, per connection, re-arms exploration when:
  • the connection's live schema fingerprint no longer matches the one the last run
    recorded (a table/column was added or removed), OR
  • the last completed run is older than the staleness window (a light periodic refresh).

Re-runs are INCREMENTAL by construction: the coverage frontier (covered measure×dimension
cuts) is recomputed from persisted insights, so a re-explore only spends budget on what is
genuinely new. Every re-kick still flows through `kickoff_exploration(auto=True)`, so the
Scout-governance and `AUTO_EXPLORATION` licensing gates are unchanged, and a run always
executes as a budget-supervised kernel job.

Always on for an always-on process since flag endgame Wave 4 (2026-08-06; the
`explorer.continuous` flag turned ON and was deleted) — the spend controls are the
per-connection gates above, not a process-wide boolean. The heartbeat is not started
under VERCEL (api.py): a warm serverless instance is not a clock.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_TICK_SECONDS = 3600.0            # how often the loop wakes; the work is gated below
_DEFAULT_REFRESH_DAYS = 7.0      # a completed run older than this is refreshed

# Decisions (also the ledger-event reasons):
SCHEMA_CHANGED = "schema_changed"
STALE = "stale"
STOPPED_ON_BUDGET = "stopped_on_budget"
SKIP = "skip"

#: A run stopped by its own time or token budget is continued this long after it stopped —
#: the user's call, 2026-09-26 (ROADMAP §6 item 34(f)): theLook's run stopped on its 600 s
#: budget and nothing ever continued it. It resumes from its saved progress, under the same
#: per-connection gates as a stale run. A person's stop is never continued.
STOPPED_RERUN_SECONDS = 86_400.0
#: The one sentence the budget path writes (``explorer/agent.py``); a run recorded before the
#: ``stopped_on_budget_at`` stamp existed is recognised by it. A user's stop or a kernel
#: cancel ends "… or stopped) — progress saved" and never matches.
_BUDGET_STOP_TAIL = "exceeded) — progress saved"


def refresh_seconds() -> float:
    """Staleness window in seconds (env AUGHOR_EXPLORER_REFRESH_DAYS, default 7 days).
    A value of 0 disables the time-based refresh (schema-change re-arm still applies)."""
    try:
        days = float(os.environ.get("AUGHOR_EXPLORER_REFRESH_DAYS", _DEFAULT_REFRESH_DAYS))
    except (TypeError, ValueError):
        days = _DEFAULT_REFRESH_DAYS
    return max(0.0, days) * 86_400.0


def stopped_on_budget_at(state: dict) -> Optional[datetime]:
    """When a run that its own budget stopped came to a halt, or None — a complete or running
    run, a failure with an error, and a person's stop are not budget stops."""
    from aughor.explorer.models import ExplorationPhase
    if state.get("phase") != ExplorationPhase.FAILED.value:
        return None
    stamp = state.get("stopped_on_budget_at")
    if not stamp:
        error = str(state.get("error") or "")
        if not (error.startswith("cancelled (") and error.endswith(_BUDGET_STOP_TAIL)):
            return None
        # recorded before the stamp: the run stopped within its budget of starting
        stamp = state.get("started_at")
    try:
        at = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None   # an unreadable stamp is not a reason to spend
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def continues_at(state: dict) -> Optional[str]:
    """When the continuous loop will continue a budget-stopped run, for the Briefing to say."""
    at = stopped_on_budget_at(state)
    return (at + timedelta(seconds=STOPPED_RERUN_SECONDS)).isoformat() if at else None


def reexplore_decision(state: dict, current_fp: Optional[str], *,
                       now: datetime, refresh_secs: float) -> str:
    """Pure decision: should an exploration be re-armed? Returns a reason or SKIP.

    Re-arms a COMPLETE run on a schema change or staleness, and a run its own budget stopped
    once ``STOPPED_RERUN_SECONDS`` have passed (it resumes from its saved progress). A
    running/paused run, a failure with an error, and a person's stop are never touched (a
    still-running run must not be double-spawned; pause intent belongs to the person).
    A schema-change re-arm requires BOTH fingerprints to be known:
    a run that predates fingerprint-stamping has `None` stored, and `None != current` must
    NOT be read as "changed" (that would re-explore every connection once on first enable).
    """
    from aughor.explorer.models import ExplorationPhase
    stopped = stopped_on_budget_at(state)
    if stopped is not None:
        return STOPPED_ON_BUDGET if (now - stopped).total_seconds() >= STOPPED_RERUN_SECONDS else SKIP
    if state.get("phase") != ExplorationPhase.COMPLETE.value:
        return SKIP
    stored_fp = state.get("schema_fingerprint")
    if current_fp and stored_fp and stored_fp != current_fp:
        return SCHEMA_CHANGED
    if refresh_secs > 0:
        completed_at = state.get("completed_at")
        if completed_at:
            try:
                done = datetime.fromisoformat(str(completed_at))
                if done.tzinfo is None:
                    done = done.replace(tzinfo=timezone.utc)
                if (now - done).total_seconds() > refresh_secs:
                    return STALE
            except (TypeError, ValueError):
                return SKIP   # unparseable timestamp → don't re-arm on staleness (a handled path, not a swallow)
    return SKIP


def connection_schema_fingerprint(connection_id: str) -> Optional[str]:
    """The connection's current schema fingerprint (all schemas), computed the SAME way the
    profile cache does — so it is directly comparable to the value a run stamps at completion.
    Best-effort: None on any failure (the tick then falls back to the staleness path only)."""
    try:
        from aughor.db.connection import open_connection_for
        from aughor.tools.schema import parse_schema_tables
        from aughor.tools.profile_cache import compute_schema_fingerprint
        db = open_connection_for(connection_id)
        try:
            schema_str = db.get_schema()
        finally:
            db.close()
        table_cols = parse_schema_tables(schema_str)
        return compute_schema_fingerprint({t: len(cols) for t, cols in table_cols.items()})
    except Exception as exc:
        logger.debug("continuous: fingerprint failed for %s: %s", connection_id, exc)
        return None


def _emit(kind: str, payload: dict, conn_id: str) -> None:
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(kind, payload, conn_id=conn_id)
    except Exception:
        logger.debug("continuous: ledger emit %s failed", kind, exc_info=True)


def plan_reexplorations() -> list[tuple[str, str]]:
    """Sync, executor-safe: decide which connections to re-arm. Reads state + computes the
    live schema fingerprint (blocking I/O), but has NO side effects — no spawn (which needs
    the event loop), no ledger emit. Returns ``[(conn_id, reason), …]``. Never raises."""
    from aughor.db.registry import list_connections
    from aughor.explorer import store as expl_store

    now = datetime.now(timezone.utc)
    secs = refresh_seconds()
    out: list[tuple[str, str]] = []
    for conn in list_connections():
        conn_id = conn.get("id")
        if not conn_id:
            continue
        try:
            # A multi-schema connection keeps one state per schema, but every run of the
            # connection stamps the SAME connection-level fingerprint, so any per-schema
            # state answers the decision. Fall back to the bare state for single-schema.
            keys = expl_store.schema_run_keys(conn_id) or [conn_id]
            state = expl_store.load(keys[0])
            current_fp = connection_schema_fingerprint(conn_id)
            decision = reexplore_decision(state, current_fp, now=now, refresh_secs=secs)
            if decision != SKIP:
                out.append((conn_id, decision))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "continuous-exploration planning is best-effort per connection",
                     counter="explorer.continuous_plan", conn_id=conn_id)
    return out


async def run_continuous_tick() -> int:
    """One pass of the continuous-exploration loop. The blocking decision runs off the event
    loop; the spawn (which needs the loop) runs on it. Governance/licensing is delegated to
    `kickoff_exploration(auto=True)` — it runs only when Scout is enabled, and surfaces an
    `exploration.skipped` ledger event when it declines (so a connection that silently never
    re-explores is visible). Returns the number of connections re-armed. Never raises."""
    import asyncio
    from aughor.routers._shared import kickoff_exploration

    loop = asyncio.get_running_loop()
    plans = await loop.run_in_executor(None, plan_reexplorations)
    rearmed = 0
    for conn_id, reason in plans:
        try:
            if kickoff_exploration(conn_id, auto=True):   # on the loop — schedules the spawn
                rearmed += 1
                _emit("exploration.rearmed", {"reason": reason, "connection_id": conn_id}, conn_id)
                logger.info("continuous: re-armed exploration for %s (%s)", conn_id, reason)
            else:
                logger.info("continuous: wanted to re-arm %s (%s) but the auto run was declined",
                            conn_id, reason)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "continuous-exploration re-arm is best-effort per connection",
                     counter="explorer.continuous_rearm", conn_id=conn_id)
    return rearmed
