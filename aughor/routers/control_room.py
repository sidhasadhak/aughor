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
  `server restart (orphaned)` failures and reports them separately.
- **Concurrency is what the kernel actually has**: one global cap plus an
  exemption set (`concurrency_policy()`), not per-agent knobs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter

from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter(tags=["control-room"])

#: The error string boot_recovery writes on rows a process restart orphaned.
_ORPHAN_ERROR = "server restart (orphaned)"

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


# ── CR3: the fleet overview ──────────────────────────────────────────────────────

@router.get("/control-room/fleet")
def fleet_overview(window_minutes: int = 60, spark_hours: int = 24):
    """KPI tiles + one labelled fleet table (charters and personas).

    Dollar cost is deliberately NOT here — it stays on `GET /usage`, which
    carries its own RBAC (billing) and its own `cost_is_complete` caveat.
    """
    from aughor.kernel.agents import is_enabled as charter_enabled
    from aughor.kernel.agents import charter_for_kind, list_charters
    from aughor.kernel.jobs import concurrency_policy
    from aughor.obs.usage import usage_report
    from aughor.custom_agents.store import list_agents as list_personas

    ledger = Ledger.default()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=max(1, int(window_minutes)))
    spark_start = now - timedelta(hours=max(1, int(spark_hours)))

    jobs = ledger.jobs_where(limit=2000)
    active = ledger.jobs_where(states=_ACTIVE_STATES, limit=500)

    # ── tiles, from the jobs table ────────────────────────────────────────────
    in_window: list[dict] = []
    durations_ms: list[float] = []
    failed = orphaned = succeeded = 0
    tokens = 0
    metered = unmetered = 0
    for j in jobs:
        created = _parse_ts(j.get("created_at"))
        if created is None or created < window_start:
            continue
        in_window.append(j)
        started, finished = _parse_ts(j.get("started_at")), _parse_ts(j.get("finished_at"))
        if started and finished:
            durations_ms.append((finished - started).total_seconds() * 1000)
        state = j.get("state")
        if state == "FAILED":
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
    }

    # ── charter rows, from job metering ──────────────────────────────────────
    spark_buckets = max(1, int(spark_hours))
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
        if j.get("state") == "FAILED":
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
                             int((created - spark_start).total_seconds() // 3600))
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
    # Job kinds no charter claims (e.g. `automation`, `eval_experiment`) would
    # otherwise vanish from the table — spend nobody can see. One labelled row.
    for worker_id, fold in by_charter.items():
        rows.append({
            "kind": "charter", "id": worker_id, "name": "Unassigned kinds",
            "role": f"job kinds with no charter: {', '.join(sorted(fold['kinds']))}",
            "icon": "gear", "lane": "background", "enabled": True,
            "job_kinds": sorted(fold["kinds"]), "spend_source": "job_metering",
            **{k: v for k, v in fold.items() if k != "kinds"},
        })

    # ── persona rows, from H2's agent axis over the session log ──────────────
    # Personas exist as a surface only while `agents.user_defined` is on — with
    # it off their CRUD routes 404, and a fleet table advertising rows nobody
    # can open would be two views disagreeing about what exists.
    from aughor.kernel.flags import flag_enabled
    personas_on = flag_enabled("agents.user_defined")
    persona_usage: dict[str, Any] = {}
    if personas_on:
        try:
            report = usage_report(axes=("agent_id",))
            persona_usage = {r.key.get("agent_id"): r for r in report.rows}
        except Exception:
            logger.warning("fleet: persona usage rollup failed", exc_info=True)
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
        rows.append({
            "kind": "persona", "id": persona.id, "name": persona.name,
            "enabled": persona.enabled, "connection_id": persona.connection_id,
            "last_eval": persona.last_eval, "eval_basis": persona.eval_basis,
            "spend_source": "session_log",
            "spend": spend,
        })

    return {"tiles": tiles, "rows": rows, "session_log_recording": True}


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
