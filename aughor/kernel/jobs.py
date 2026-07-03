"""The Job Kernel (stage K1) — every long-running operation is a supervised job.

Before K1, long-running work was 17 raw ``asyncio.create_task`` sites with no
shared state model: explorations stuck "running" after a crash, never resumed
after a restart, leaked tasks on canvas/connection deletion, and pause states
that nothing was responsible for releasing. The kernel makes those properties
structural instead of per-call-site:

- **One state machine** (PENDING → RUNNING → SUCCEEDED | FAILED | CANCELLED,
  with PAUSED reserved) persisted in the ledger; every transition emits a
  ``job.state`` event to the journal.
- **Heartbeats** — a runner-side sidecar touches the job row while the task is
  alive. A heartbeat that stops without a terminal transition = an orphan.
  (Liveness of the event loop, not of the work itself — a hung-but-alive task
  is K1's known blind spot, taken deliberately to avoid threading heartbeat
  calls through every work loop.)
- **The Supervisor** — a periodic loop that fails stale orphans, absorbs the
  old one-shot ``sweep_stale_running`` (history.db, leveraged not duplicated),
  and resumes explorers left paused by a dead investigation.
- **Boot recovery** — at startup every non-terminal job row necessarily belongs
  to a dead process (single-process runtime): mark it FAILED("server restart")
  and hand resumable explorations back to the caller to respawn from their
  checkpoint files. The ``api.started`` journal event anchors the timeline.
- **Idempotency** — submitting with an idempotency key while a job with that
  key is active returns the existing job instead of double-spawning (the
  manual-rebuild-races-Phase-8 class).
- **Scope cancellation** — deleting a canvas/connection cancels its jobs.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from aughor.kernel import metering
from aughor.kernel.ledger import Ledger
from aughor.org.context import DEFAULT_ORG_ID, reset_org_id, set_org_id

logger = logging.getLogger(__name__)

# The job whose async context the current code runs under — artifact writes
# stamp `created_by_job` from this without threading ids through call chains.
_current_job: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "aughor_current_job", default=None
)


def current_job_id() -> Optional[str]:
    return _current_job.get()


class JobState:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    ACTIVE = (PENDING, RUNNING, PAUSED)
    TERMINAL = (SUCCEEDED, FAILED, CANCELLED)


_LEGAL = {
    JobState.PENDING: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.RUNNING: {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.PAUSED},
    JobState.PAUSED: {JobState.RUNNING, JobState.CANCELLED, JobState.FAILED},
    JobState.SUCCEEDED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}

_HEARTBEAT_SECONDS = 15
_STALE_SECONDS = 120

# Concurrency cap for user-initiated jobs. Without a bound, a client (or a script
# loop) hammering /investigate spawns unbounded supervised jobs + SSE streams +
# LLM calls and exhausts the single process. Background explorers are exempt:
# they are already bounded one-per-connection by idempotency key, and capping
# them here would let a few long-lived explorers starve user investigations.
_UNBOUNDED_KINDS = frozenset({"exploration"})


def _max_concurrent_jobs() -> int:
    import os
    try:
        return max(1, int(os.getenv("AUGHOR_MAX_CONCURRENT_JOBS", "8")))
    except ValueError:
        return 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobKernel:
    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger.default()
        self._tasks: dict[str, asyncio.Task] = {}
        # Lazily created on the running loop (a kernel built off-loop in a test
        # otherwise binds the semaphore to the wrong loop).
        self._job_sem: Optional[asyncio.Semaphore] = None

    def _slot_for(self, kind: str) -> Optional[asyncio.Semaphore]:
        """The concurrency semaphore a job of *kind* must hold to run, or None
        when the kind is exempt from the cap."""
        if kind in _UNBOUNDED_KINDS:
            return None
        if self._job_sem is None:
            self._job_sem = asyncio.Semaphore(_max_concurrent_jobs())
        return self._job_sem

    # ── state transitions (the ONLY writer of job.state) ─────────────────────

    def _transition(self, job_id: str, to: str, *, error: Optional[str] = None) -> bool:
        job = self.ledger.job_get(job_id)
        if job is None:
            return False
        frm = job["state"]
        if to not in _LEGAL.get(frm, set()):
            logger.warning("job %s: illegal transition %s → %s ignored", job_id, frm, to)
            return False
        fields: dict[str, Any] = {"state": to}
        if to == JobState.RUNNING and not job.get("started_at"):
            fields["started_at"] = _now()
            fields["heartbeat_at"] = _now()
        if to in JobState.TERMINAL:
            fields["finished_at"] = _now()
        if error is not None:
            fields["error"] = error[:2000]
        self.ledger.job_update(job_id, **fields)
        self.ledger.emit(
            "job.state",
            {"state": to, "kind": job["kind"], **({"error": error[:300]} if error else {})},
            conn_id=job.get("conn_id"), canvas_id=job.get("canvas_id"), job_id=job_id,
        )
        return True

    # ── submit / run ──────────────────────────────────────────────────────────

    async def submit(
        self,
        kind: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        conn_id: Optional[str] = None,
        canvas_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        payload: Any = None,
        on_finish: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """Create a supervised job and start it. Returns the job id.

        ``on_finish(job_id, final_state)`` runs after the terminal transition —
        callers use it for registry cleanup (the old add_done_callback role).
        """
        if idempotency_key:
            existing = self.ledger.jobs_where(
                states=list(JobState.ACTIVE), idempotency_key=idempotency_key, limit=1
            )
            if existing:
                return existing[0]["id"]

        job_id = uuid.uuid4().hex[:12]
        self.ledger.job_insert({
            "id": job_id, "kind": kind, "conn_id": conn_id, "canvas_id": canvas_id,
            "state": JobState.PENDING, "payload": payload,
            "idempotency_key": idempotency_key, "attempt": 1, "created_at": _now(),
        })
        self.ledger.emit("job.state", {"state": JobState.PENDING, "kind": kind},
                         conn_id=conn_id, canvas_id=canvas_id, job_id=job_id)

        sem = self._slot_for(kind)

        async def _gated() -> None:
            # Hold a concurrency slot for the whole run; the job sits PENDING
            # until a slot frees. Cancelling a still-queued job closes its row.
            if sem is not None:
                try:
                    await sem.acquire()
                except asyncio.CancelledError:
                    self._transition(job_id, JobState.CANCELLED)
                    self._tasks.pop(job_id, None)
                    raise
            try:
                await self._run(job_id, coro_factory, on_finish)
            finally:
                if sem is not None:
                    sem.release()

        task = asyncio.create_task(_gated(), name=f"job-{kind}-{job_id}")
        self._tasks[job_id] = task
        return job_id

    def _resolve_governance(self, job_id: str):
        """(governance, agent_id) for this job's agent, at its Org/workspace scope.
        Best-effort — any failure yields the charter defaults (never blocks a run)."""
        job = self.ledger.job_get(job_id) or {}
        from aughor.kernel.agents import charter_for_kind, effective_governance
        charter = charter_for_kind(job.get("kind"))
        ws = None
        try:
            from aughor.workspace.store import workspace_for_connection
            ws = workspace_for_connection(job.get("conn_id"))
        except Exception:
            ws = None
        return effective_governance(charter.id, ws), charter.id

    def _set_run_model(self, job_id: str):
        """Pin this run's LLM model to the agent's per-agent override (governance,
        override-wins: workspace > app > role default). Returns a reset token, or None when
        no override applies. Best-effort — a resolve error never blocks the run."""
        try:
            gov, _agent = self._resolve_governance(job_id)
            if getattr(gov, "model", None):
                from aughor.llm.provider import set_run_model
                return set_run_model(gov.model)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "per-agent model resolve", counter="agent_model")
        return None

    def _over_budget(self, job_id: str, gov, elapsed_s: float) -> Optional[str]:
        """The budget this run has blown, or None. Tokens come from the live
        metrics registry; time from the heartbeat's own clock."""
        from aughor.kernel import metering
        m = metering.metrics_for_job(job_id)
        if gov.token_budget and m and m.total_tokens > gov.token_budget:
            return f"token budget ({gov.token_budget:,} tokens)"
        if gov.time_budget_s and elapsed_s > gov.time_budget_s:
            return f"time budget ({gov.time_budget_s}s)"
        return None

    async def _heartbeat_loop(self, job_id: str) -> None:
        import time as _time
        gov, agent_id = self._resolve_governance(job_id)
        t0 = _time.monotonic()
        while True:
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            try:
                self.ledger.job_update(job_id, heartbeat_at=_now())
            except Exception:
                logger.debug("heartbeat write failed for job %s", job_id, exc_info=True)
            # Budget enforcement — the reliable kill: cancel raises CancelledError,
            # which (unlike a plain exception) unwinds past the agent's fail-open
            # try/excepts. We stamp the reason first; the CANCELLED transition keeps it.
            over = self._over_budget(job_id, gov, _time.monotonic() - t0)
            if over:
                logger.info("job %s exceeded %s — cancelling (agent %s)", job_id, over, agent_id)
                self.ledger.emit("budget.exceeded", {"agent": agent_id, "reason": over},
                                 job_id=job_id,
                                 conn_id=(self.ledger.job_get(job_id) or {}).get("conn_id"))
                self.ledger.job_update(job_id, error=f"budget exceeded: {over}")
                self.cancel(job_id)
                return

    async def _run(self, job_id: str, coro_factory, on_finish) -> None:
        self._transition(job_id, JobState.RUNNING)
        hb = asyncio.create_task(self._heartbeat_loop(job_id), name=f"hb-{job_id}")
        final = JobState.FAILED
        _token = _current_job.set(job_id)
        # Re-bind the job's tenant for the whole run (DATA-06 under identity). The org
        # was captured on the job row at submit; binding it HERE — not relying on the
        # implicit contextvar copy — means a job re-run by boot-recovery (no request
        # context) still operates in its own org, not 'default'.
        _org_token = set_org_id((self.ledger.job_get(job_id) or {}).get("org_id") or DEFAULT_ORG_ID)
        _m_token = metering.start()
        metering.register_job(job_id)   # so the heartbeat can enforce this run's budget
        _model_token = self._set_run_model(job_id)   # per-agent LLM model override (best-effort)
        try:
            await coro_factory()
            final = JobState.SUCCEEDED
            self._transition(job_id, JobState.SUCCEEDED)
        except asyncio.CancelledError:
            final = JobState.CANCELLED
            self._transition(job_id, JobState.CANCELLED)
            # Deliberately not re-raised: cancellation is an intended outcome,
            # and this task is the top of its own stack.
        except Exception as exc:
            final = JobState.FAILED
            self._transition(job_id, JobState.FAILED, error=str(exc))
            logger.error("job %s failed: %s", job_id, exc, exc_info=True)
        finally:
            # Flush the run's compute (tokens/queries/rows/time) onto the job row —
            # for the Fleet view + Trust Receipt. Runs for every terminal state so a
            # cancelled/failed run still records what it spent. Best-effort.
            try:
                _snap = metering.snapshot()
                if _snap is not None:
                    self.ledger.job_update(job_id, metrics=json.dumps(_snap, default=str))
            except Exception as _m_exc:
                from aughor.kernel.errors import tolerate
                tolerate(_m_exc, "job metrics flush", counter="metering")
            metering.unregister_job(job_id)
            metering.reset(_m_token)
            if _model_token is not None:
                from aughor.llm.provider import reset_run_model
                reset_run_model(_model_token)
            _current_job.reset(_token)
            reset_org_id(_org_token)
            hb.cancel()
            self._tasks.pop(job_id, None)
            if on_finish is not None:
                try:
                    on_finish(job_id, final)
                except Exception:
                    logger.warning("job %s on_finish hook failed", job_id, exc_info=True)

    # ── cancellation ──────────────────────────────────────────────────────────

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        # No live task (e.g. PENDING row from a dead process) — close the row.
        return self._transition(job_id, JobState.CANCELLED)

    def cancel_scope(self, *, conn_id: Optional[str] = None, canvas_id: Optional[str] = None) -> int:
        """Cancel every active job in a scope — wired into canvas/connection
        deletion so explorer tasks can't outlive their owner (the task-leak class)."""
        if conn_id is None and canvas_id is None:
            return 0
        n = 0
        for job in self.ledger.jobs_where(states=list(JobState.ACTIVE),
                                          conn_id=conn_id, canvas_id=canvas_id):
            if self.cancel(job["id"]):
                n += 1
        # A connection scope also owns canvas jobs running on that connection.
        if conn_id is not None and canvas_id is None:
            for job in self.ledger.jobs_where(states=list(JobState.ACTIVE)):
                if job.get("conn_id") == conn_id and job.get("canvas_id"):
                    if self.cancel(job["id"]):
                        n += 1
        return n

    # ── boot recovery (WCH-6) ─────────────────────────────────────────────────

    def boot_recovery(self) -> list[dict]:
        """At startup, every non-terminal job row belongs to a dead process —
        mark it FAILED and return the exploration jobs so the caller can respawn
        them from their checkpoints. Idempotent: a clean ledger returns []."""
        orphans = self.ledger.jobs_where(states=list(JobState.ACTIVE))
        resumable = []
        for job in orphans:
            self.ledger.emit("job.orphaned", {"kind": job["kind"]},
                             conn_id=job.get("conn_id"), canvas_id=job.get("canvas_id"),
                             job_id=job["id"])
            # PENDING/PAUSED → FAILED is legal; RUNNING → FAILED is legal.
            self._transition(job["id"], JobState.FAILED, error="server restart (orphaned)")
            if job["kind"] == "exploration":
                resumable.append(job)
        if orphans:
            logger.info("boot recovery: %d orphaned job(s) failed, %d exploration(s) resumable",
                        len(orphans), len(resumable))
        return resumable

    # ── the Supervisor ────────────────────────────────────────────────────────

    def sweep_stale(self, *, stale_after: int = _STALE_SECONDS) -> int:
        """Fail RUNNING jobs whose heartbeat went silent and whose task is gone —
        the in-process orphan case (task died without a terminal transition)."""
        n = 0
        cutoff = datetime.now(timezone.utc).timestamp() - stale_after
        for job in self.ledger.jobs_where(states=[JobState.RUNNING]):
            if job["id"] in self._tasks:
                continue
            hb = job.get("heartbeat_at") or job.get("started_at") or job.get("created_at")
            try:
                hb_ts = datetime.fromisoformat(hb).timestamp()
            except (ValueError, TypeError):
                hb_ts = 0
            if hb_ts < cutoff:
                if self._transition(job["id"], JobState.FAILED,
                                    error="orphaned (stale heartbeat, no live task)"):
                    n += 1
        return n

    def _resume_investigation_paused_explorers(self) -> int:
        """Backstop for the paused-explorer leak: an explorer paused BY AN
        INVESTIGATION (tagged ``_paused_by_investigation``) whose connection has
        no running investigation anymore gets resumed. User-paused explorers
        (stop endpoints) are never touched — pause intent belongs to the user."""
        try:
            from aughor.routers._shared import explorers, canvas_explorers
            from aughor.db.history import list_investigations
        except Exception:
            return 0
        candidates = [e for e in (*explorers.values(), *canvas_explorers.values())
                      if getattr(getattr(e, "_status", None), "paused", False)
                      and getattr(e, "_paused_by_investigation", False)]
        if not candidates:
            return 0
        running_conns = {
            r.get("connection_id") for r in list_investigations(limit=100)
            if r.get("status") == "running"
        }
        n = 0
        for e in candidates:
            if getattr(e, "connection_id", None) not in running_conns:
                try:
                    e.resume()
                    e._paused_by_investigation = False
                    self.ledger.emit("explorer.resumed",
                                     {"reason": "investigation gone (supervisor backstop)"},
                                     conn_id=getattr(e, "connection_id", None),
                                     canvas_id=getattr(e, "canvas_id", None))
                    n += 1
                except Exception:
                    logger.warning("supervisor: explorer resume failed", exc_info=True)
        return n

    async def supervise_forever(self, *, interval: int = 30) -> None:
        """The periodic supervisor — replaces the old boot-only stale sweep."""
        tick = 0
        while True:
            await asyncio.sleep(interval)
            tick += 1
            try:
                n = self.sweep_stale()
                if n:
                    logger.info("supervisor: failed %d stale orphaned job(s)", n)
            except Exception:
                logger.warning("supervisor: stale sweep failed", exc_info=True)
            try:
                self._resume_investigation_paused_explorers()
            except Exception:
                logger.warning("supervisor: paused-explorer backstop failed", exc_info=True)
            if tick % 10 == 0:  # ~every 5 min — absorb the old boot-only sweep
                try:
                    from aughor.db.history import sweep_stale_running
                    n = sweep_stale_running(max_age_minutes=60)
                    if n:
                        self.ledger.emit("investigations.swept", {"count": n})
                        logger.info("supervisor: swept %d stale investigation(s)", n)
                except Exception:
                    logger.warning("supervisor: investigation sweep failed", exc_info=True)


_kernel: Optional[JobKernel] = None


def kernel() -> JobKernel:
    """The process-wide job kernel (lazy — tests construct their own)."""
    global _kernel
    if _kernel is None:
        _kernel = JobKernel()
    return _kernel


def budget_fraction_used(job_id: Optional[str] = None) -> Optional[float]:
    """Fraction (0..1+) of the active job's token budget already consumed, or None
    when there is no job / no token budget. A long-running agent can use this to
    RESERVE headroom for a final, high-value phase instead of spending the whole
    budget on earlier work and being hard-cancelled before it runs. Best-effort —
    any resolution failure yields None (caller proceeds as if unbounded)."""
    job_id = job_id or current_job_id()
    if not job_id:
        return None
    try:
        gov, _ = kernel()._resolve_governance(job_id)
        budget = getattr(gov, "token_budget", None)
        if not budget:
            return None
        from aughor.kernel import metering
        m = metering.metrics_for_job(job_id)
        used = m.total_tokens if m else 0
        return used / budget
    except Exception:
        logger.debug("budget_fraction_used resolve failed for %s", job_id, exc_info=True)
        return None
