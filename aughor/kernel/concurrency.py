"""A ThreadPoolExecutor that propagates the caller's context into worker threads.

The stdlib executor does **not** copy ``contextvars`` across the thread boundary,
so any contextvar set on the event loop — the current job id
(:func:`aughor.kernel.jobs.current_job_id`) and the per-run metering accumulator
(:mod:`aughor.kernel.metering`) — is invisible to code dispatched via
``loop.run_in_executor`` / ``pool.submit``. Installing this as the loop's default
executor (and using it for the ad-hoc pools) makes that context cross the
boundary.

This is a strict *more-correct* change: executor-run code now sees the context it
would have seen had it run inline (e.g. journal events emitted from inside a query
get tagged with the right ``job_id`` instead of ``None``).
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    """``ThreadPoolExecutor`` whose submitted callables run inside a *copy* of the
    submitting context, so ``contextvars`` propagate into the worker thread.

    A fresh ``copy_context()`` per ``submit`` keeps parallel calls isolated (a
    single ``Context`` cannot be entered from two threads at once) while still
    sharing references to mutable objects held in contextvars — which is exactly
    what lets the metering accumulator add up across parallel leaf calls.
    """

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[override]
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)


# ── background tasks that outlive the request that started them ───────────────────────
#
# `asyncio.create_task` returns the ONLY strong reference to its task. The stdlib docs say
# it plainly: save a reference, or the task can be garbage-collected mid-execution and
# vanish without finishing and without raising. Every fire-and-forget kick in the routers
# discarded that reference — a schema exploration or a knowledge sync could stop halfway
# for no reason anyone could reproduce.
#
# Holding the references buys a second thing the suite needs: somewhere to cancel from.
# A kick started inside one test kept running after it, and its doc-tree write landed in a
# LATER test's fake store — a stranger's point arriving in a capture that had every reason
# to believe it was its own. Tests can now end what they started.

import asyncio as _asyncio
import logging as _logging
from typing import Any, Coroutine, Optional, Set

_LOG = _logging.getLogger(__name__)

#: Live background tasks. Entries remove themselves on completion, so this is what is
#: still running rather than everything ever started.
_BACKGROUND: "Set[_asyncio.Task]" = set()


def spawn(coro: "Coroutine[Any, Any, Any]", *, name: Optional[str] = None) -> "_asyncio.Task":
    """`asyncio.create_task`, with the reference kept for as long as the task runs."""
    task = _asyncio.create_task(coro, name=name)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return task


def pending_background() -> list:
    """The background tasks still running, newest state first read at call time."""
    return [t for t in _BACKGROUND if not t.done()]


def cancel_background() -> int:
    """Cancel every running background task; returns how many were asked to stop.

    Each task is cancelled **on its own loop** via `call_soon_threadsafe`, because the
    caller is usually not on it — a test finishing on the main thread, ending work that a
    TestClient's portal thread is still running. A closed loop is skipped rather than
    raising: its tasks died with it.

    ⚠️ **Cancelling a task does not stop the thread behind it.** These kicks do their real
    work in an executor, and cancelling the awaiting task abandons that future while the
    worker thread runs on. So this narrows the window in which a leaked write can land; it
    does not close it. A test that must not see a stranger's write should also capture only
    its own — a property no cancellation can give it.
    """
    asked = 0
    for task in list(_BACKGROUND):
        if task.done():
            continue
        try:
            loop = task.get_loop()
            if loop.is_closed():
                continue
            loop.call_soon_threadsafe(task.cancel)
            asked += 1
        except Exception:  # pragma: no cover - a loop torn down mid-iteration
            _LOG.debug("background task could not be cancelled", exc_info=True)
    return asked
