"""The work-dispatch seam — in-process today, an external queue by env var.

Phase 2's durable execution needs work to be *dispatchable* without assuming an
always-on process, but §5.1 of docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md is firm
that the worker is a DEPLOYMENT choice, not an architecture choice. So dispatch
goes through this seam: :class:`InProcessQueue` — today's exact behaviour, a direct
kernel submit on the running event loop — is the default, and an external backend
(Upstash QStash, Inngest) becomes ``AUGHOR_WORK_QUEUE=…`` plus a class here, not a
rewrite of every dispatch site. No external backend ships until there is a real
queue to verify one against — the same discipline as the LLM coordinator seam.

What a backend must honour:
- **At-least-once is the contract**, so every dispatch carries an idempotency key;
  the kernel already collapses duplicate submissions on it (shared-DB safe).
- **Payloads are references, never state** — the durable-execution spike measured
  49 KB of state doubling the round-trip; slices exchange keys and read the family
  store directly.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Optional, Protocol, runtime_checkable

QUEUE_ENV = "AUGHOR_WORK_QUEUE"


@runtime_checkable
class WorkQueue(Protocol):
    """Dispatch one unit of work. Returns a dispatch id (the job id for the
    in-process backend), or None when dispatch was declined (no loop, duplicate)."""

    def dispatch(self, kind: str, payload: dict, *,
                 conn_id: Optional[str] = None,
                 idempotency_key: Optional[str] = None) -> Optional[str]:
        ...


class InProcessQueue:
    """Today's behaviour: hand the work to the running kernel on the main loop.

    Uses the same scheduler-thread-safe path background ticks already use
    (``kernel.jobs.submit_scheduled_tick``'s underpinnings): submit is awaited on
    the captured main loop, the work itself runs asynchronously, and the
    idempotency key stops a slow tick from piling up behind itself."""

    def dispatch(self, kind: str, payload: dict, *,
                 conn_id: Optional[str] = None,
                 idempotency_key: Optional[str] = None) -> Optional[str]:
        import asyncio

        from aughor.kernel.jobs import kernel, main_loop

        async def _coro() -> None:
            runner = _RUNNERS.get(kind)
            if runner is None:
                raise ValueError(f"no runner registered for work kind {kind!r}")
            await runner(payload)

        loop = main_loop()
        if loop is None or not loop.is_running():
            return None                      # caller falls back to inline execution
        fut = asyncio.run_coroutine_threadsafe(
            kernel().submit(kind, _coro, conn_id=conn_id, idempotency_key=idempotency_key),
            loop,
        )
        return fut.result(timeout=10)


# Work runners, registered by the owning module at import/startup — the queue
# dispatches by KIND so an external backend's webhook can resolve the same
# registry; payloads stay JSON-serializable references.
_RUNNERS: dict[str, Any] = {}


def register_runner(kind: str, runner) -> None:
    """Register ``async runner(payload)`` for a work kind. Last write wins —
    re-registration at reload is normal."""
    _RUNNERS[kind] = runner


_QUEUE: Optional[WorkQueue] = None
_LOCK = threading.Lock()
_BACKENDS: dict[str, type] = {"inprocess": InProcessQueue}


def default() -> WorkQueue:
    """The process's work queue, resolved once. An unknown name in
    AUGHOR_WORK_QUEUE degrades to in-process — dispatch that still runs beats
    dispatch that vanishes on a typo."""
    global _QUEUE
    if _QUEUE is None:
        with _LOCK:
            if _QUEUE is None:
                name = (os.getenv(QUEUE_ENV) or "inprocess").strip().lower()
                _QUEUE = _BACKENDS.get(name, InProcessQueue)()
    return _QUEUE


def set_default(queue: Optional[WorkQueue]) -> None:
    """Install a queue (or None to re-resolve from env) — the test hook and the
    entry point an external backend uses at startup."""
    global _QUEUE
    with _LOCK:
        _QUEUE = queue
