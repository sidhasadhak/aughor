"""The seam between the sync answer core and the SSE wrapper.

`_stream_chat` used to BE the pipeline. Now it runs `_answer_core` on a worker thread and
relays what the core emits over an `asyncio.Queue`, which makes the queue a real piece of
concurrency design rather than plumbing — so it gets its own net, separate from the frame
transcript.

Four properties, each one a way the bridge could be wrong while every existing test stayed
green:

  * ORDER AND COMPLETENESS. The core writes from a thread; the consumer reads on the loop.
    If a single frame is dropped or reordered by the hop, the transcript test would only
    notice on the handful of frames it names.
  * RAISED IS NOT FINISHED. The sentinel terminates the STREAM; it carries no outcome. The
    wrapper learns the outcome by awaiting the future, which is what keeps the old
    `except Exception -> error` frame working from a thread it no longer runs on.
  * A `BaseException` STILL CROSSES. `BudgetExceeded` unwinds past the answer path's
    fail-open handlers by not being an `Exception`. It now also has to survive a thread
    boundary and stay uncaught by the wrapper, or the budget stops being enforceable.
  * THE CORE IS ACTUALLY SYNC. The point of the split is that a plain function call can
    reach the answer path — no loop, no bridge, no `asyncio.run`. Asserted by calling it.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from aughor.routers import investigations as inv


def _frames(chunks: list[str]) -> list[tuple[str, dict]]:
    out = []
    for c in chunks:
        for line in c.splitlines():
            if line.startswith("data:"):
                p = json.loads(line[5:].strip())
                out.append((p.pop("type"), p))
    return out


async def _drain(**kw) -> list[str]:
    return [c async for c in inv._stream_chat("q", "fixture", [], **kw)]


def _fake_core(monkeypatch, fn):
    """Swap the core for a scripted one. The wrapper is what is under test here."""
    monkeypatch.setattr(inv, "_answer_core", fn)


@pytest.mark.anyio
async def test_a_thousand_frames_arrive_in_order_and_none_are_lost(monkeypatch):
    """E2 — the sentinel/ordering property, at a volume where a race would show.

    One producer thread and `call_soon_threadsafe` callbacks running FIFO on the loop is
    what makes emission order survive; a `queue.SimpleQueue` drained through an executor
    hop per frame would too, at the cost this design exists to avoid. Either way the
    guarantee has to be checked, not assumed.
    """
    def core(*a, emit, **kw):
        for i in range(1000):
            emit("headline_delta", {"headline": str(i)})
        return inv._AnswerCoreResult(outcome="answered")

    _fake_core(monkeypatch, core)
    frames = _frames(await _drain())

    assert [t for t, _ in frames] == ["headline_delta"] * 1000
    assert [p["headline"] for _, p in frames] == [str(i) for i in range(1000)]


@pytest.mark.anyio
async def test_a_core_that_raises_still_delivers_what_it_already_said(monkeypatch):
    """The frames emitted before the raise are the user's evidence of how far it got.

    They are already on the queue when the exception unwinds, so the consumer must drain
    them BEFORE the future is awaited — the error frame comes last, exactly where the
    `yield` used to put it.
    """
    def core(*a, emit, **kw):
        emit("sql", {"sql": "SELECT 1"})
        emit("columns", {"columns": ["x"]})
        raise RuntimeError("the coder fell over")

    _fake_core(monkeypatch, core)
    frames = _frames(await _drain())

    assert [t for t, _ in frames] == ["sql", "columns", "error"]
    assert "the coder fell over" in frames[-1][1]["message"]


@pytest.mark.anyio
async def test_a_base_exception_is_not_swallowed_by_the_wrapper(monkeypatch):
    """E5 — `BudgetExceeded` is a `BaseException` on purpose.

    The wrapper catches `Exception`, so a budget stop must pass straight through it to
    `_metered_stream`, which is the only place that knows how to phrase it. If the thread
    boundary or the `except` clause ate it, the budget would silently stop being enforced
    and the turn would end on a generic red line instead.
    """
    from aughor.kernel import metering

    def core(*a, emit, **kw):
        emit("sql", {"sql": "SELECT 1"})
        raise metering.BudgetExceeded("token budget")

    _fake_core(monkeypatch, core)
    with pytest.raises(metering.BudgetExceeded):
        await _drain()

    # And the composed stream still turns it into the typed frame it always did.
    _fake_core(monkeypatch, core)
    chunks = [c async for c in inv._metered_stream(
        inv._stream_chat("q", "fixture", []), budget=None)]
    frames = _frames(chunks)
    assert [t for t, _ in frames] == ["sql", "error"]
    assert frames[-1][1]["reason"] == "budget_exceeded"


@pytest.mark.anyio
async def test_a_client_that_leaves_stops_the_core_at_its_next_checkpoint(monkeypatch):
    """Cancellation is cooperative and this is its granularity.

    Nothing interrupts a blocking call mid-flight — there is no cancel primitive on any of
    these connections — so the honest guarantee is: once the consumer goes away, the next
    `emit` raises and the core unwinds through its own `finally`. This asserts the loop
    that used to run forever now stops, and that it stops by raising rather than by being
    politely asked.
    """
    emitted = threading.Event()
    stopped: dict = {}

    def core(*a, emit, **kw):
        try:
            for i in range(100_000):
                emit("headline_delta", {"headline": str(i)})
                emitted.set()
        except inv._CoreCancelled:
            stopped["at"] = i
            raise
        finally:
            stopped["unwound"] = True

    _fake_core(monkeypatch, core)
    gen = inv._stream_chat("q", "fixture", [])
    await gen.__anext__()
    await gen.aclose()

    assert emitted.wait(5), "the core never started emitting"
    for _ in range(500):                       # the core is on another thread
        if stopped.get("unwound"):
            break
        await asyncio.sleep(0.01)

    assert stopped.get("unwound"), "the core ran on after the client left"
    assert "at" in stopped, "the core stopped, but not by raising _CoreCancelled"
    assert stopped["at"] < 100_000 - 1, "it only stopped because it ran out of work"


def test_the_core_answers_with_no_event_loop_anywhere(monkeypatch, builtin_conn_id):
    """The reason the split exists, asserted as a plain function call.

    Not `async def`, no bridge, no `asyncio.run` — a sync caller (the converse
    `answer_question` tool is the one this is for) reaches the real answer path and gets
    the terminal state back, including the guard receipts that a no-op `emit` would
    otherwise throw away. Its sibling tool `run_sql` returns those; without them in the
    RETURN the richer tool would be the weaker one.
    """
    from tests.integration.test_stream_chat_transcript import _stub_providers
    _stub_providers(monkeypatch)

    seen: list[str] = []
    result = inv._answer_core("How many rows are there?", builtin_conn_id, [],
                              emit=lambda t, p: seen.append(t))

    assert result.outcome == "answered", result.error
    assert result.sql and result.columns and result.headline
    # The emission log and the returned receipts describe the same turn.
    assert len(result.guard_receipts) == seen.count("guard_receipt")
    assert set(result.receipt) >= {"compiled", "defan", "grounded", "lint", "assumed"}
