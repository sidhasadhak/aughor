"""R6 — the deep investigation streams its report prose (ada_synthesize's
executive_summary) to the client token-by-token, instead of going silent between
phase_complete markers and dropping the whole report at once.

The mechanism reuses the existing progress sink: ada_synthesize captures a
report-delta emitter (in the node body, where the ContextVar sink is visible),
passes it to provider.complete_streaming as on_text, and the emitter forwards the
growing prose to the sink queue. The interleaver passes the self-tagged delta
through verbatim; the router maps it to a `report_delta` SSE event. Gated on the
sink being bound (ada.progress_events) — off → blocking .complete(), unchanged.
"""
from __future__ import annotations

import asyncio
import contextvars
import time

from aughor.agent import progress
from aughor.routers.investigations import _aiter_sync_with_progress


def test_emitter_is_none_without_a_bound_sink():
    # Default context: no sink → no streaming → caller falls back to .complete().
    assert progress.report_delta_emitter() is None


def test_emitter_pushes_throttled_deltas_from_a_worker_thread():
    async def run():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        ctx = contextvars.copy_context()
        ctx.run(progress.set_progress_sink, loop, q)
        emit = ctx.run(progress.report_delta_emitter)
        assert emit is not None

        # complete_streaming runs in a plain executor thread; the captured closure
        # must still reach the loop's queue from there.
        def worker():
            emit("x" * 30)   # first partial, +30 ≥ 24 → emitted
            emit("x" * 40)   # +10 < 24 → throttled (dropped)
            emit("x" * 60)   # +30 ≥ 24 → emitted

        await loop.run_in_executor(None, worker)
        await asyncio.sleep(0.05)   # let call_soon_threadsafe callbacks land
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    items = asyncio.run(run())
    assert items == [{"__report_delta__": "x" * 30}, {"__report_delta__": "x" * 60}]


def test_interleaver_passes_report_delta_verbatim_and_wraps_progress():
    """A report-delta payload flows through untouched; a phase-progress payload is
    wrapped as __ada_progress__ (so the router maps each to the right SSE type)."""
    async def run():
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait({"__report_delta__": "partial prose so far"})
        q.put_nowait({"phase_id": "baseline", "done": 1, "total": 3, "current": "region"})
        ctx = contextvars.copy_context()

        def gen():
            # Sleep so the two already-queued progress items drain first (deterministic).
            time.sleep(0.15)
            yield {"ada_synthesize": {"answer_report": {"headline": "done"}}}

        out = []
        async for ev in _aiter_sync_with_progress(gen(), q, ctx):
            out.append(ev)
        return out

    events = asyncio.run(run())
    # report-delta passed through verbatim (NOT wrapped under __ada_progress__)
    assert {"__report_delta__": "partial prose so far"} in events
    # phase-progress wrapped
    assert {"__ada_progress__": {"phase_id": "baseline", "done": 1, "total": 3,
                                 "current": "region"}} in events
    # the graph event still passes through
    assert {"ada_synthesize": {"answer_report": {"headline": "done"}}} in events
