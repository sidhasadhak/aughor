"""Best-effort per-dimension progress sink for Deep-Analysis scans (P2, `ada.progress_events`).

A long-running scan node (`ada_cross_section` / `ada_decompose`) runs its per-dimension queries
inside a `ContextThreadPoolExecutor`; between `phase_complete` events the user otherwise sees a
multi-minute silent spinner (there is no mid-node → SSE channel by default). When the SSE stream
provisions a sink, each completed dimension query pushes a lightweight progress marker to it, which
the stream interleaves into the response as a `phase_progress` event.

Design:
  • The sink is `(event_loop, asyncio.Queue)`, held in a ContextVar. The stream sets it inside the
    `Context` that each graph node's `next()` runs in; `ContextThreadPoolExecutor` copies that
    context per submit, so the sink propagates into the scan's worker threads with no extra plumbing.
  • Emitting is FAIL-SAFE: no sink, a full queue, or a torn-down loop all silently no-op. A progress
    emit must NEVER perturb the investigation — it is pure telemetry.
  • Gated by the caller: the sink is only set under `ada.progress_events`, so with the flag off
    `emit_phase_progress` is a single ContextVar read returning None (the default path is unchanged).
"""
from __future__ import annotations

import contextvars
from typing import Optional

# (event_loop, asyncio.Queue) or None. Read on the scan's node/worker threads; set by the SSE stream.
_PROGRESS_SINK: contextvars.ContextVar[Optional[tuple]] = contextvars.ContextVar(
    "ada_progress_sink", default=None)


def set_progress_sink(loop, queue) -> "contextvars.Token":
    """Bind the active progress sink in the current context. The SSE stream calls this inside the
    `Context` it runs the graph in, so the sink reaches the scan's threads via context copy."""
    return _PROGRESS_SINK.set((loop, queue))


def clear_progress_sink(token) -> None:
    try:
        _PROGRESS_SINK.reset(token)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "clearing the progress sink is best-effort teardown; a stale token is harmless",
                 counter="ada.progress_clear")


def emit_phase_progress(phase_id: str, done: int, total: int, current: str = "") -> None:
    """Push one progress marker to the active sink, if any. Best-effort; never raises. ``done``/``total``
    are the completed/total per-dimension queries of the phase; ``current`` is the dimension just
    finished (a human label the UI shows as 'scanning {current} ({done}/{total})…')."""
    sink = _PROGRESS_SINK.get()
    if sink is None:
        return
    loop, queue = sink
    payload = {"phase_id": phase_id, "done": int(done), "total": int(total), "current": current or ""}
    try:
        loop.call_soon_threadsafe(queue.put_nowait, payload)
    except Exception as exc:
        # Loop closed, queue full, or any teardown race — progress is disposable telemetry.
        from aughor.kernel.errors import tolerate
        tolerate(exc, "progress emit is disposable telemetry; a closed loop / full queue is fine",
                 counter="ada.progress_emit")
