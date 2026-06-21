"""Per-run compute metering — what an answer actually *cost* to produce.

A single accumulator lives in a contextvar; the LLM funnel
(:func:`aughor.llm.provider.LLMProvider._complete_on`) and the warehouse execute
chokepoint (:func:`aughor.db.connection._security_post`) add to it; it is flushed
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
from dataclasses import asdict, dataclass
from typing import Iterator, Optional


@dataclass
class RunMetrics:
    """Accumulated compute for one run (one investigation / exploration / answer)."""

    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    query_count: int = 0
    rows_returned: int = 0
    llm_ms: float = 0.0
    query_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


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


# A run's live metrics, also reachable by job_id — so the kernel heartbeat (a
# separate task, which can't see the job task's contextvar) can enforce budgets.
_by_job: dict[str, RunMetrics] = {}


def register_job(job_id: str) -> None:
    """Expose the current run's metrics under `job_id` for cross-task budget reads."""
    m = _current.get()
    if m is not None:
        with _lock:
            _by_job[job_id] = m


def unregister_job(job_id: str) -> None:
    with _lock:
        _by_job.pop(job_id, None)


def metrics_for_job(job_id: str) -> Optional[RunMetrics]:
    return _by_job.get(job_id)


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
