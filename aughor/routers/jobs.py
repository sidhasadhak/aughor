"""K1 — the Fleet surface: a read view over the kernel's job table + journal, plus
cancellation. Mirrors MotherDuck's Flights tool shape (list / get / logs / cancel)
so the autonomy we already run is legible as a fleet of named agents — and so the
same surface can be exposed as MCP tools later.

See docs/AGENTIC_ARCHITECTURE.md §6-7 and docs/MOTHERDUCK_LEARNINGS.md R2/R5.

Read endpoints are ungated (like /events): they expose nothing a user can't
already read off the journal. Cancel mirrors the existing investigation-cancel.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from aughor.kernel.agents import agent_for
from aughor.kernel.jobs import JobState, kernel
from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter()


def _duration_ms(job: dict) -> Optional[float]:
    s, f = job.get("started_at"), job.get("finished_at")
    if not (s and f):
        return None
    try:
        return (datetime.fromisoformat(f) - datetime.fromisoformat(s)).total_seconds() * 1000.0
    except Exception:
        return None


def _title(job: dict) -> str:
    """A human label for a run — the question for an investigation, the scope for
    an exploration, else the kind."""
    payload = job.get("payload")
    if isinstance(payload, dict) and payload.get("question"):
        return str(payload["question"])
    if job.get("kind") == "exploration":
        return f"Exploring {job.get('canvas_id') or job.get('conn_id') or 'data'}"
    return job.get("kind") or "job"


def _view(job: dict) -> dict:
    """A job row as the Fleet view wants it: agent identity + the compute it spent."""
    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "state": job.get("state"),
        "conn_id": job.get("conn_id"),
        "canvas_id": job.get("canvas_id"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
        "agent": agent_for(job.get("kind")),
        "title": _title(job),
        "cost": job.get("metrics"),        # parsed dict (tokens/queries/rows/time) or None
        "duration_ms": _duration_ms(job),
    }


@router.get("/jobs")
def list_jobs(state: Optional[str] = None, conn_id: Optional[str] = None,
              kind: Optional[str] = None, limit: int = 100):
    """The fleet: recent jobs (newest first), each tagged with its agent + the
    compute it spent. ``state=active`` returns only in-flight jobs."""
    if state == "active":
        states: Optional[list[str]] = list(JobState.ACTIVE)
    elif state:
        states = [state]
    else:
        states = None
    jobs = Ledger.default().jobs_where(states=states, conn_id=conn_id, limit=min(int(limit), 500))
    if kind:
        jobs = [j for j in jobs if j.get("kind") == kind]
    return [_view(j) for j in jobs]


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = Ledger.default().job_get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return _view(job)


@router.get("/jobs/{job_id}/logs")
def job_logs(job_id: str, limit: int = 200):
    """The run's journal slice — its lifecycle + phase events, newest first."""
    if Ledger.default().job_get(job_id) is None:
        raise HTTPException(status_code=404, detail="No such job")
    return Ledger.default().events(job_id=job_id, limit=min(int(limit), 500))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel an in-flight job — the supervised task's CancelledError unwinds it
    and the kernel records it CANCELLED."""
    if Ledger.default().job_get(job_id) is None:
        raise HTTPException(status_code=404, detail="No such job")
    return {"job_id": job_id, "cancelled": kernel().cancel(job_id)}
