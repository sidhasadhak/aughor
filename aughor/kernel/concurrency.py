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
