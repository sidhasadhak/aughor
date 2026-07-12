"""Per-run compute metering — what an answer actually *cost* to produce.

A single accumulator lives in a contextvar; the LLM funnel
(:func:`aughor.llm.provider.LLMProvider._complete_on`) and the warehouse execute
chokepoint (:func:`aughor.db.connection.security_post`) add to it; it is flushed
onto the job row (:mod:`aughor.kernel.jobs`) and stamped into the answer artifact
so it surfaces in the Trust Receipt and the Fleet view.

Design contract:
- **No-op when no run is active.** ``record_*`` return immediately if nothing
  called :func:`start` / :func:`metered` in the current context, so ordinary
  (un-metered) code paths are completely unaffected.
- **Fail-open, always.** Metering must never break an answer; failures route
  through :func:`aughor.kernel.errors.tolerate` (the sanctioned swallow — no new
  silent-swallow ratchet debt).
- **Honest compute, not money.** We meter tokens · calls · queries · rows · time —
  signals that are always available and true. A dollar figure would require a
  per-model price table (local models are ~free, prices drift) and is deliberately
  left to a later step.

Crossing threads: ``record_*`` run in worker threads (LLM/SQL go through
``run_in_executor`` / ad-hoc pools). :class:`aughor.kernel.concurrency.ContextThreadPoolExecutor`
propagates this contextvar into those threads.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Iterator, Optional


@dataclass
class LearningSignals:
    """Closed-loop learning events attributed to one run — the per-run Learning Receipt (Wave 1 · E4).

    These are RUNTIME events that occur within the answering run (a resolution settled on a clarify
    resume, a trusted plan replayed); the receipt combines them with receipt-time read-backs (readings
    reused / corrections) — see ``aughor/agent/learning_receipt.py``. (Clarifications-asked is deliberately
    NOT here: the asking turn pauses without a receipt and resumes as a fresh run, so it needs cross-turn
    state to surface honestly — a follow-up.)"""

    resolutions_crystallized: int = 0     # a resolution settled by the user/a reviewer this run
    trusted_program_replayed: int = 0     # a verified plan-as-program replayed deterministically


@dataclass
class RunMetrics:
    """Accumulated compute for one run (one investigation / exploration / answer)."""

    org_id: str = ""  # tenant this run is billed to; stamped at register_job
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    query_count: int = 0
    rows_returned: int = 0
    llm_ms: float = 0.0
    query_ms: float = 0.0
    learning: LearningSignals = field(default_factory=LearningSignals)
    activations: list = field(default_factory=list)   # self-gating guards that fired this run (E3)

    def to_dict(self) -> dict:
        # The COST view — learning signals and capability activations ride the same run accumulator but
        # are separate surfaces (the Learning / Activation Receipts), so the cost blob stamped on the
        # Trust Receipt stays byte-identical.
        d = asdict(self)
        d.pop("learning", None)
        d.pop("activations", None)
        return d


_current: contextvars.ContextVar[Optional[RunMetrics]] = contextvars.ContextVar(
    "aughor_run_metrics", default=None
)
# record_* run from parallel worker threads sharing one RunMetrics object; guard
# the read-modify-write so a rare interleave can't drop an increment.
_lock = threading.Lock()


def start() -> "contextvars.Token[Optional[RunMetrics]]":
    """Begin a metered run in the current context; returns a token for :func:`reset`."""
    return _current.set(RunMetrics())


def reset(token: "contextvars.Token[Optional[RunMetrics]]") -> None:
    try:
        _current.reset(token)
    except Exception as exc:  # reset across contexts is best-effort
        from aughor.kernel.errors import tolerate
        tolerate(exc, "metering reset", counter="metering")


def current() -> Optional[RunMetrics]:
    return _current.get()


def snapshot() -> Optional[dict]:
    """The current run's metrics as a plain dict, or ``None`` if no run is active."""
    m = _current.get()
    return m.to_dict() if m is not None else None


def record_llm(prompt_tokens: int = 0, completion_tokens: int = 0, ms: float = 0.0) -> None:
    """Attribute one LLM completion (tokens + wall-time) to the active run. No-op if none."""
    m = _current.get()
    if m is None:
        return
    try:
        with _lock:
            m.llm_calls += 1
            m.prompt_tokens += int(prompt_tokens or 0)
            m.completion_tokens += int(completion_tokens or 0)
            m.total_tokens = m.prompt_tokens + m.completion_tokens
            m.llm_ms += float(ms or 0.0)
    except Exception as exc:  # never let metering break a completion
        from aughor.kernel.errors import tolerate
        tolerate(exc, "llm metering", counter="metering")


def record_query(rows: int = 0, ms: float = 0.0) -> None:
    """Attribute one warehouse query (rows returned + wall-time) to the active run. No-op if none."""
    m = _current.get()
    if m is None:
        return
    try:
        with _lock:
            m.query_count += 1
            m.rows_returned += int(rows or 0)
            m.query_ms += float(ms or 0.0)
    except Exception as exc:  # never let metering break a query
        from aughor.kernel.errors import tolerate
        tolerate(exc, "query metering", counter="metering")


def record_learning(**deltas: int) -> None:
    """Attribute closed-loop learning events to the active run (fields of ``LearningSignals``:
    ``resolutions_crystallized`` / ``trusted_program_replayed``). No-op when no run is active
    (background/seed calls) or a delta names an unknown field — cheap and fail-safe, so touchpoints call
    it unconditionally."""
    m = _current.get()
    if m is None:
        return
    try:
        with _lock:
            for k, v in deltas.items():
                if hasattr(m.learning, k):
                    setattr(m.learning, k, getattr(m.learning, k) + int(v or 0))
    except Exception as exc:  # never let a learning-signal count break the answer path
        from aughor.kernel.errors import tolerate
        tolerate(exc, "learning-signal metering", counter="metering.learning")


def learning_snapshot() -> Optional[dict]:
    """The active run's learning signals as a plain dict, or ``None`` if no run is active."""
    m = _current.get()
    return asdict(m.learning) if m is not None else None


def record_activation(capability: str) -> None:
    """Note that a self-gating capability FIRED on the active run (its deterministic trigger held) — the
    per-run Activation Receipt (Wave 1 · E3). No-op when no run is active. The human 'why' is looked up
    from ``kernel/flags.CAPABILITY_TRIGGER`` at receipt-build time, so touchpoints pass only the name."""
    m = _current.get()
    if m is None or not capability:
        return
    try:
        with _lock:
            m.activations.append(capability)
    except Exception as exc:  # never let a receipt count break a guard
        from aughor.kernel.errors import tolerate
        tolerate(exc, "activation metering", counter="metering.activation")


def activations_snapshot() -> Optional[list]:
    """The active run's capability activations (a list of names, one per firing), or ``None`` if no run."""
    m = _current.get()
    return list(m.activations) if m is not None else None


# A run's live metrics, also reachable by job_id — so the kernel heartbeat (a
# separate task, which can't see the job task's contextvar) can enforce budgets.
_by_job: dict[str, RunMetrics] = {}


def register_job(job_id: str) -> None:
    """Expose the current run's metrics under `job_id` for cross-task budget reads.
    Stamps the run's tenant from the current Org context so per-run compute is
    tenant-keyed alongside the job/receipt rows."""
    m = _current.get()
    if m is not None:
        from aughor.org.context import current_org_id
        if not m.org_id:
            m.org_id = current_org_id()
        with _lock:
            _by_job[job_id] = m


def unregister_job(job_id: str) -> None:
    with _lock:
        _by_job.pop(job_id, None)


def metrics_for_job(job_id: str) -> Optional[RunMetrics]:
    return _by_job.get(job_id)


# ── In-context budget enforcement (the synchronous path) ─────────────────────
# Kernel jobs enforce budgets from the heartbeat (kernel/jobs.py). The synchronous
# chat/insight path has no heartbeat, so it arms a budget in-context and checks it
# at the LLM funnel. BudgetExceeded is a BaseException so it unwinds past the
# answer path's fail-open `except Exception` (the same reliability trick that makes
# the kernel's cancel work) — the stream wrapper catches it and ends cleanly.

class BudgetExceeded(BaseException):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class _BudgetCtx:
    token_budget: Optional[int]
    time_budget_s: Optional[int]
    t0: float


_budget: contextvars.ContextVar[Optional[_BudgetCtx]] = contextvars.ContextVar(
    "aughor_run_budget", default=None
)


def set_budget(token_budget: Optional[int], time_budget_s: Optional[int]) -> "contextvars.Token":
    """Arm an in-context budget for the current run; returns a token for clear_budget."""
    import time as _time
    return _budget.set(_BudgetCtx(token_budget, time_budget_s, _time.monotonic()))


def clear_budget(token: "contextvars.Token") -> None:
    try:
        _budget.reset(token)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "metering budget clear", counter="metering")


def check_budget() -> None:
    """Raise BudgetExceeded if the active run is over its in-context budget. No-op
    when no budget is armed (job paths enforce via the kernel heartbeat instead)."""
    b = _budget.get()
    if b is None:
        return
    m = _current.get()
    if b.token_budget and m is not None and m.total_tokens > b.token_budget:
        raise BudgetExceeded(f"token budget ({b.token_budget:,} tokens)")
    if b.time_budget_s:
        import time as _time
        if (_time.monotonic() - b.t0) > b.time_budget_s:
            raise BudgetExceeded(f"time budget ({b.time_budget_s}s)")


@contextmanager
def metered() -> Iterator[Optional[RunMetrics]]:
    """Set a fresh accumulator for the duration of the block.

    Used by the synchronous chat/insight answer path, which is *not* a kernel job
    (kernel jobs already set the accumulator in ``JobKernel._run``)."""
    token = start()
    try:
        yield _current.get()
    finally:
        reset(token)
