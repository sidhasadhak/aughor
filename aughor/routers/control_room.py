"""Wave CR3/CR4 — the fleet overview and the needs-a-human list.

Both endpoints are VIEWS (J10/J12): every number is folded at read time from a
store that already exists — jobs, charters+governance, personas, the session
log's usage rollup, the kinetic inbox, investigation history and automation
runs. Nothing here writes, and there is no control-room store to drift.

Honesty rules the fleet table is built on (each earned by a measurement):

- **Charter ≠ persona.** One table, but every row is labelled with its kind —
  the collision was dodged twice in Wave H and stays dodged.
- **Two spend sources, never one measurement.** Charter spend rides job-row
  metering (`jobs.metrics`, works with the session log off); persona spend
  rides H2's `agent_id` axis over the session log. They are reported under
  different keys with different caveats.
- **NULL metrics is not zero spend.** ~44% of live job rows carry no metrics
  (orphaned restarts never reach the metering flush) — those are counted as
  `unmetered_runs`, never as 0 tokens.
- **An orphaned restart is not an agent error.** The error-rate tile excludes
  interrupted runs (`JobState.INTERRUPTED`) and reports them separately. That used
  to be an error-string match, which silently never fired for jobs — the string it
  compared against is the investigations wording.
- **Concurrency is what the kernel actually has**: one global cap plus an
  exemption set (`concurrency_policy()`), not per-agent knobs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter

# The error string boot recovery writes on rows a process restart orphaned —
# imported from the producer so the exact-equality match below can never drift blind.
from aughor.db.history import ORPHAN_REASON as _ORPHAN_ERROR
from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter(tags=["control-room"])

_ACTIVE_STATES = ["PENDING", "RUNNING", "PAUSED"]


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _pct(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * q))], 1)


#: A runner named for what it IS, rather than for the fact that no charter claimed it.
#: "Unassigned kinds" described the lookup that produced the row; a reader wants to know
#: it is the automations engine.
_RUNNER_NAMES = {
    "automation": "Automations",
    "eval_experiment": "Evals",
}


def _runner_role(kinds: list[str], fold: dict) -> str:
    """One line saying what this runner does and how much of it is nothing.

    The automation engine records a job PER TICK, including the overwhelming majority
    that evaluate and fire nothing — so "1,291 runs" is a heartbeat, not work, and the
    row has to say so or it reads as the busiest agent on the fleet.
    """
    if kinds == ["automation"]:
        runs = int(fold.get("runs") or 0)
        return (f"scheduled · one evaluation tick per minute · {runs:,} ticks in window, "
                f"no model calls")
    if kinds == ["eval_experiment"]:
        return "eval experiments · run on demand"
    return "job kinds with no charter: " + (", ".join(kinds) or "none")


def _window_cost(win) -> dict:
    """What the window's model calls cost, with the share nothing could price.

    Priced from the provider's own published catalogue (never a hardcoded rate), and a
    figure that cannot be completed says so: `unpriced_calls` is the number that stops a
    small total reading as a cheap day.
    """
    from aughor.obs.usage import price_for
    try:
        rows = Ledger.default().session_events(
            kind="llm_call", since=win.since, until=win.until, limit=20000)
    except Exception:
        logger.warning("fleet: window cost scan failed", exc_info=True)
        return {"usd": None, "unpriced_calls": None, "is_complete": False, "calls": 0}
    usd, unpriced = 0.0, 0
    for e in rows:
        price = price_for(str(e.get("provider") or ""), str(e.get("model") or ""))
        if price is None:
            unpriced += 1
            continue
        usd += (int(e.get("prompt_tokens") or 0) / 1e6) * price.input_per_1m
        usd += (int(e.get("completion_tokens") or 0) / 1e6) * price.output_per_1m
    return {"usd": round(usd, 4), "unpriced_calls": unpriced,
            "is_complete": unpriced == 0, "calls": len(rows)}


# ── CR3: the fleet overview ──────────────────────────────────────────────────────

@router.get("/control-room/fleet")
def fleet_overview(window_minutes: int = 60, spark_hours: int = 24,
                   range: str = "", since: str = "", until: str = "",
                   include_runners: bool = False):
    """KPI tiles + the fleet table, over ONE window shared with every other panel.

    `range` (or explicit `since`/`until`) is the shared time axis; `window_minutes` /
    `spark_hours` remain for callers that predate it. The tiles and the row sparklines
    now bucket through the SAME window — they used to disagree by construction, the
    tiles counting a 60-minute window while the sparks drew 24 hourly buckets.

    **Runners are not agents.** Job kinds no charter claims — the automation engine's
    every-minute evaluation tick, eval experiments — come back in `runners`, never in
    `rows`, and never inside the tile counts unless `include_runners` is set. Measured
    2026-08-17 that tick was 1,291 of 1,316 jobs in twenty-four hours, so folding it in
    turns every agent metric into a rounding error on a cron and makes runs/min a
    heartbeat reading.

    Cost IS here now (roadmap decision 2, 2026-08-17), priced from the provider's own
    catalogue and always carrying its unpriced share; `GET /usage` keeps the full ledger
    behind billing RBAC.
    """
    from aughor.kernel.agents import is_enabled as charter_enabled
    from aughor.kernel.agents import charter_for_kind, list_charters
    from aughor.kernel.jobs import concurrency_policy
    from aughor.obs.timeseries import (JOB_READ_LIMIT, bucket_edges, job_rows,
                                       resolve_window)
    from aughor.obs.usage import usage_report
    from aughor.custom_agents.store import list_agents as list_personas

    ledger = Ledger.default()
    now = datetime.now(timezone.utc)
    if range or since or until:
        win = resolve_window(range, since=since, until=until)
    else:
        win = resolve_window(since=(now - timedelta(minutes=max(1, int(window_minutes))))
                             .isoformat(), until=now.isoformat())
    window_start = win.since_dt
    window_minutes = max(1, int((win.until_dt - win.since_dt).total_seconds() // 60))
    spark_start = window_start

    # ONE bounded read, shared with the chart, split BY KIND in the query. `active` is
    # deliberately unbounded by time — a job running since yesterday is running NOW.
    #
    # This used to be a single capped read that was classified afterwards, and the cap
    # was the bug: the tick outnumbers agent work ~45:1, so the newest 5,000 rows were
    # almost all tick and the agent runs fell off the end. Measured on a real store over
    # seven days it reported 143 agent runs where there were 250 — a 43% undercount, with
    # the chart beside it drawing the true number, because it read with a larger cap.
    # `job_rows` now issues one read per side, so neither can starve the other, and says
    # when a cap was actually reached.
    agent_rows, runner_rows, truncated = job_rows(win, limit=JOB_READ_LIMIT)
    active = ledger.jobs_where(states=_ACTIVE_STATES, limit=500)

    # ── tiles, from the jobs table ────────────────────────────────────────────
    # Every job carries its charter from the read, so "is this an agent or a runner" is
    # decided in ONE place and the tiles, the sparks and the table cannot disagree.
    jobs = agent_rows + runner_rows
    for j in jobs:
        j["_charter"] = j.get("charter_id") or charter_for_kind(j.get("kind")).id
    runner_jobs = runner_rows
    agent_jobs = jobs if include_runners else agent_rows

    in_window: list[dict] = []
    durations_ms: list[float] = []
    failed = orphaned = succeeded = 0
    tokens = 0
    metered = unmetered = 0
    for j in agent_jobs:
        created = _parse_ts(j.get("created_at"))
        if created is None or created < window_start:
            continue
        in_window.append(j)
        started, finished = _parse_ts(j.get("started_at")), _parse_ts(j.get("finished_at"))
        if started and finished:
            durations_ms.append((finished - started).total_seconds() * 1000)
        state = j.get("state")
        if state == "INTERRUPTED":
            orphaned += 1
        elif state == "FAILED":
            # The legacy string match stays for rows written before INTERRUPTED
            # existed. It never matched a JOB even then — `_ORPHAN_ERROR` is the
            # *investigations* wording, while an orphaned job says "lease lapsed
            # (orphaned)" — so every restart-killed job has been counted as an agent
            # error, which is exactly what this split exists to prevent. The status
            # is now the authority; a key that must equal a sentence is how a guard
            # goes blind.
            if (j.get("error") or "") == _ORPHAN_ERROR:
                orphaned += 1
            else:
                failed += 1
        elif state == "SUCCEEDED":
            succeeded += 1
        metrics = j.get("metrics") or {}
        if isinstance(metrics, dict) and metrics.get("total_tokens") is not None:
            metered += 1
            tokens += int(metrics.get("total_tokens") or 0)
        elif state not in _ACTIVE_STATES:
            unmetered += 1

    finished_in_window = failed + orphaned + succeeded
    tiles = {
        "active_jobs": len(active),
        "window_minutes": int(window_minutes),
        "runs_started": len(in_window),
        "runs_per_min": round(len(in_window) / max(1, int(window_minutes)), 2),
        "p95_duration_ms": _pct(durations_ms, 0.95),
        "p50_duration_ms": _pct(durations_ms, 0.50),
        # Agent errors only; an orphaned restart is an infrastructure fact.
        "error_rate": (round(failed / finished_in_window, 3)
                       if finished_in_window else None),
        "failed_runs": failed,
        "orphaned_runs": orphaned,
        "tokens": {"total": tokens, "metered_runs": metered,
                   "unmetered_runs": unmetered,
                   "per_hour": round(tokens / max(int(window_minutes) / 60, 1e-9))
                   if metered else None},
        "concurrency": concurrency_policy(),
        # What was left OUT of every number above, stated rather than implied. A reader
        # who sees "24 runs" while the machine did 1,315 things is owed the difference.
        "runner_runs": len(runner_jobs),
        "include_runners": bool(include_runners),
        # True when a read filled its cap: every count here is then a floor, not a total.
        "truncated": bool(truncated),
        "window": win.as_dict(),
    }
    tiles["cost"] = _window_cost(win)

    # ── charter rows, from job metering ──────────────────────────────────────
    # Sparks bucket through the SHARED window, so a row's bars and the tiles above it
    # describe the same span. They used to be independent (60-minute tiles, 24 hourly
    # bars) — two time bases in one table, which is a chart that cannot be read.
    spark_buckets = win.bucket_count
    bucket_seconds = win.bucket_seconds
    by_charter: dict[str, dict] = {}
    for j in jobs:
        charter = charter_for_kind(j.get("kind"))
        row = by_charter.setdefault(charter.id, {
            "runs": 0, "failed": 0, "orphaned": 0, "tokens": 0, "queries": 0,
            "metered_runs": 0, "unmetered_runs": 0, "last_run_at": None,
            "spark": [0] * spark_buckets, "kinds": set(),
        })
        row["runs"] += 1
        row["kinds"].add(j.get("kind") or "")
        if j.get("state") == "INTERRUPTED":
            row["orphaned"] += 1
        elif j.get("state") == "FAILED":
            row["orphaned" if (j.get("error") or "") == _ORPHAN_ERROR else "failed"] += 1
        metrics = j.get("metrics") or {}
        if isinstance(metrics, dict) and metrics.get("total_tokens") is not None:
            row["metered_runs"] += 1
            row["tokens"] += int(metrics.get("total_tokens") or 0)
            row["queries"] += int(metrics.get("query_count") or 0)
        elif j.get("state") not in _ACTIVE_STATES:
            row["unmetered_runs"] += 1
        created = _parse_ts(j.get("created_at"))
        if created:
            if row["last_run_at"] is None or str(j["created_at"]) > row["last_run_at"]:
                row["last_run_at"] = str(j["created_at"])
            if created >= spark_start:
                bucket = min(spark_buckets - 1,
                             int((created - spark_start).total_seconds() // bucket_seconds))
                row["spark"][bucket] += 1

    rows: list[dict] = []
    for charter in list_charters():
        fold = by_charter.pop(charter.id, None) or {
            "runs": 0, "failed": 0, "orphaned": 0, "tokens": 0, "queries": 0,
            "metered_runs": 0, "unmetered_runs": 0, "last_run_at": None,
            "spark": [0] * spark_buckets, "kinds": set()}
        rows.append({
            "kind": "charter", "id": charter.id, "name": charter.name,
            "role": charter.role, "icon": charter.icon, "lane": charter.lane,
            "enabled": charter_enabled(charter.id),
            "job_kinds": list(charter.job_kinds),
            "spend_source": "job_metering",
            **{k: v for k, v in fold.items() if k != "kinds"},
        })
    # Job kinds no charter claims are RUNNERS, not agents — the automation engine's
    # every-minute evaluation tick, eval experiments. They used to fold into one row
    # called "Unassigned kinds" sitting in the agent table, where the tick's 1,291 runs
    # per day dwarfed every real agent and set the shape of every sparkline on the page.
    # They come back in their own list now: still counted, still visible (spend nobody
    # can see is the reason the row was invented), never mixed into the agents.
    runners: list[dict] = []
    for worker_id, fold in by_charter.items():
        kinds = sorted(k for k in fold["kinds"] if k)
        runners.append({
            "kind": "runner", "id": worker_id,
            "name": _RUNNER_NAMES.get(kinds[0] if len(kinds) == 1 else "", "Background runners"),
            "role": _runner_role(kinds, fold),
            "icon": "gear", "lane": "background", "enabled": True,
            "job_kinds": kinds, "spend_source": "job_metering",
            **{k: v for k, v in fold.items() if k != "kinds"},
        })

    # ── persona rows, from H2's agent axis over the session log ──────────────
    # Personas are a permanent surface (flag endgame Wave 2, 2026-08-06) — the
    # fleet table always lists user-defined agents; an empty roster is honest.
    personas_on = True
    persona_usage: dict[str, Any] = {}
    if personas_on:
        try:
            report = usage_report(axes=("agent_id",))
            persona_usage = {r.key.get("agent_id"): r for r in report.rows}
        except Exception:
            logger.warning("fleet: custom-agent usage rollup failed", exc_info=True)
    # A custom agent's work is CALLS in the session log, not jobs in the kernel — it
    # answers inside a request rather than submitting a run. Folding those calls into
    # the same columns the charters use (runs, spark, tokens, last run) is what lets one
    # table hold both without half its cells reading "—", and the `spend_source` on every
    # row keeps the two populations legible rather than silently summed.
    events_by_agent: dict[str, list[dict]] = {}
    try:
        for e in ledger.session_events(kind="llm_call", since=win.since, until=win.until,
                                       limit=20000):
            if e.get("agent_id"):
                events_by_agent.setdefault(e["agent_id"], []).append(e)
    except Exception:
        logger.warning("fleet: custom-agent event scan failed", exc_info=True)
    for persona in (list_personas() if personas_on else []):
        usage_row = persona_usage.get(persona.id)
        if usage_row is None:
            spend = {"measured": True, "calls": 0, "total_tokens": 0,
                     "failure_rate": None}
        else:
            spend = {"measured": True, "calls": usage_row.calls,
                     "total_tokens": usage_row.total_tokens,
                     "failure_rate": (round(usage_row.failures / usage_row.calls, 3)
                                      if usage_row.calls else None)}
        mine = events_by_agent.get(persona.id, [])
        spark = [0] * spark_buckets
        for e in mine:
            idx = win.index_of(e.get("at") or "")
            if idx is not None:
                spark[idx] += 1
        rows.append({
            "kind": "persona", "id": persona.id, "name": persona.name,
            "enabled": persona.enabled, "connection_id": persona.connection_id,
            "last_eval": persona.last_eval, "eval_basis": persona.eval_basis,
            "spend_source": "session_log",
            "spend": spend,
            # The shared columns, from the agent's own calls.
            "runs": len({e.get("trace_id") for e in mine if e.get("trace_id")}),
            "failed": sum(1 for e in mine if e.get("ok") is False),
            "orphaned": 0,
            "tokens": sum(int(e.get("total_tokens") or 0) for e in mine),
            "metered_runs": sum(1 for e in mine if e.get("total_tokens") is not None),
            "unmetered_runs": sum(1 for e in mine if e.get("total_tokens") is None),
            "queries": 0,
            "spark": spark,
            "last_run_at": max((str(e.get("at") or "") for e in mine), default=None),
        })

    return {"tiles": tiles, "rows": rows, "runners": runners,
            "window": win.as_dict(), "edges": bucket_edges(win),
            "session_log_recording": True}


# ── CR4: needs a human ───────────────────────────────────────────────────────────

@router.get("/control-room/needs-human")
def needs_human(limit: int = 100):
    """One derived list over the three real sources — a VIEW, never a queue.

    Each row deep-links to its native resolve surface, so resolving anywhere
    removes it everywhere by construction (one store per source, no copies).
    `count` equals the sum of the per-source counts at read time — that
    equality is the CR4 gate.
    """
    from aughor.automations.store import get_runs
    from aughor.db.history import list_investigations
    from aughor.actions.inbox import list_proposals

    now = datetime.now(timezone.utc)
    rows: list[dict] = []

    def _waiting_ms(since: Any) -> Optional[int]:
        ts = _parse_ts(since)
        return int((now - ts).total_seconds() * 1000) if ts else None

    # Source A — kinetic inbox proposals awaiting accept/reject.
    inbox_count = 0
    try:
        for p in list_proposals(status="pending", limit=limit):
            inbox_count += 1
            rows.append({
                "source": "kinetic_inbox", "id": p.id,
                "title": f"{p.action_id}: {p.reasoning[:140]}" if p.reasoning
                else p.action_id,
                "connection_id": p.connection_id,
                "since": p.created_at, "waiting_ms": _waiting_ms(p.created_at),
                "resolve": {"surface": "inbox",
                            "accept": f"/kinetic-actions/inbox/{p.id}/accept",
                            "reject": f"/kinetic-actions/inbox/{p.id}/reject"},
            })
    except Exception:
        logger.warning("needs-human: inbox read failed", exc_info=True)

    # Source B — deep runs paused at a gate, resumable via feedback.
    # `investigations` has no paused_at column; the honest timestamp is the
    # `investigation.paused` lifecycle event on the kernel journal. When the
    # journal has aged it out, fall back to started_at and SAY SO via `basis`.
    paused_count = 0
    try:
        paused_at: dict[str, str] = {}
        for ev in Ledger.default().events(kind="investigation.paused", limit=500):
            inv = (ev.get("payload") or {}).get("investigation_id")
            if inv and inv not in paused_at:
                paused_at[inv] = ev["at"]
        for inv in list_investigations(limit=200):
            if inv.get("status") != "paused":
                continue
            paused_count += 1
            since = paused_at.get(inv["id"])
            rows.append({
                "source": "paused_run", "id": inv["id"],
                "title": inv.get("question") or inv["id"],
                "connection_id": inv.get("connection_id"),
                "since": since or inv.get("started_at"),
                "since_basis": "paused_event" if since else "started_at",
                "waiting_ms": _waiting_ms(since or inv.get("started_at")),
                "resolve": {"surface": "investigation",
                            "feedback": f"/investigations/{inv['id']}/feedback"},
            })
    except Exception:
        logger.warning("needs-human: paused-run read failed", exc_info=True)

    # Source C — automation effects that stopped at approval_required.
    approval_count = 0
    try:
        for run in get_runs(limit=200):
            for idx, effect in enumerate(run.effects):
                if effect.status != "approval_required":
                    continue
                approval_count += 1
                rows.append({
                    "source": "automation_approval",
                    "id": f"{run.id}:{idx}",
                    "title": f"{run.automation_name or run.automation_id} — "
                             f"{effect.kind}: {effect.message[:140]}",
                    "connection_id": run.conn_id,
                    "since": run.started_at, "waiting_ms": _waiting_ms(run.started_at),
                    "resolve": {"surface": "automation",
                                "automation_id": run.automation_id,
                                "run_id": run.id},
                })
    except Exception:
        logger.warning("needs-human: automation-run read failed", exc_info=True)

    rows.sort(key=lambda r: r.get("waiting_ms") or 0, reverse=True)
    return {
        "count": inbox_count + paused_count + approval_count,
        "sources": {"kinetic_inbox": inbox_count, "paused_runs": paused_count,
                    "automation_approvals": approval_count},
        "rows": rows[: max(1, int(limit))],
    }
