"""P2 — live per-dimension Deep-Analysis progress (`ada.progress_events`).

The audit's silent ~5-min spinner: `ada_cross_section` runs its whole scan as ONE graph node, and the
explore-wave "progress" template is a post-node drain — it can't fill the gap. P2 adds a real mid-node
channel: each completed per-dimension query pushes a marker to a best-effort sink, which the SSE stream
interleaves as a `phase_progress` event. These tests pin the three moving parts hermetically (no graph,
no LLM): the fail-safe sink, the emit from `_parallel_execute_safe`, and the interleaving iterator.
"""
from __future__ import annotations

import asyncio
import contextvars
import types

import aughor.agent.investigate as I
from aughor.agent import progress
from aughor.routers import investigations as R


def _run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [x async for x in agen]


# ── The sink: fail-safe, and delivers when bound ──────────────────────────────────

def test_emit_is_a_noop_without_a_sink():
    # No sink bound → a single ContextVar read returning None; must never raise (the default path).
    assert progress._PROGRESS_SINK.get() is None
    progress.emit_phase_progress("cross_section", 1, 6, "brand")   # no exception = pass


def test_emit_delivers_payload_to_the_bound_queue():
    async def _c():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        token = progress.set_progress_sink(loop, q)
        try:
            progress.emit_phase_progress("cross_section", 3, 6, "brand")
            await asyncio.sleep(0)     # let call_soon_threadsafe run
            return q.get_nowait()
        finally:
            progress.clear_progress_sink(token)
    assert _run(_c()) == {"phase_id": "cross_section", "done": 3, "total": 6, "current": "brand"}


def test_emit_swallows_a_broken_loop():
    class _BadLoop:
        def call_soon_threadsafe(self, *a, **k):
            raise RuntimeError("loop closed")
    token = progress.set_progress_sink(_BadLoop(), asyncio.Queue())
    try:
        progress.emit_phase_progress("x", 1, 1, "y")   # must be swallowed
    finally:
        progress.clear_progress_sink(token)


# ── The emit seam: _parallel_execute_safe reports one marker per completed query ───

class _StubResult:
    def __init__(self):
        self.error = None
        self.hypothesis_id = ""


class _StubConn:
    def make_reader(self):
        return self


def _query(title: str):
    return types.SimpleNamespace(title=title, sql=f"SELECT 1 -- {title}")


def test_parallel_execute_emits_progress_per_dimension(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(I, "emit_phase_progress",
                        lambda pid, done, total, current: seen.append((pid, done, total, current)))
    monkeypatch.setattr(I, "_execute_safe", lambda conn, pid, sql, schema=None: _StubResult())

    queries = [_query("by brand"), _query("by category"), _query("by channel")]
    I._parallel_execute_safe(_StubConn(), "cross_section", queries, cap=8)

    assert len(seen) == 3
    assert {s[0] for s in seen} == {"cross_section"}
    assert sorted(s[1] for s in seen) == [1, 2, 3]        # done counts 1..3 (completion order varies)
    assert all(s[2] == 3 for s in seen)                   # total is 3 throughout
    assert {s[3] for s in seen} == {"by brand", "by category", "by channel"}


def test_parallel_execute_serial_fallback_still_emits(monkeypatch):
    # When the threadpool path raises, the serial fallback must still report progress in order.
    seen: list[tuple] = []
    monkeypatch.setattr(I, "emit_phase_progress",
                        lambda pid, done, total, current: seen.append((pid, done, total, current)))
    monkeypatch.setattr(I, "_execute_safe", lambda conn, pid, sql, schema=None: _StubResult())

    class _BoomPool:
        def __init__(self, *a, **k): pass
        def __enter__(self): raise RuntimeError("pool down")
        def __exit__(self, *a): return False
    monkeypatch.setattr(I, "ContextThreadPoolExecutor", _BoomPool, raising=False)
    # ContextThreadPoolExecutor is imported inside the function; patch at its source too.
    monkeypatch.setattr("aughor.kernel.concurrency.ContextThreadPoolExecutor", _BoomPool)

    queries = [_query("by brand"), _query("by category")]
    I._parallel_execute_safe(_StubConn(), "decompose", queries, cap=8)
    assert [(s[1], s[3]) for s in seen] == [(1, "by brand"), (2, "by category")]


# ── The interleaving iterator: progress markers mixed into graph events ────────────

def test_progress_iterator_interleaves_markers_and_graph_events():
    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait({"phase_id": "cross_section", "done": 1, "total": 2, "current": "brand"})
    ctx = contextvars.copy_context()
    graph_events = [{"ada_intake": {}}, {"ada_cross_section": {}}]

    out = _run(_collect(R._aiter_sync_with_progress(iter(graph_events), q, ctx)))

    # Every graph event is delivered, in order, and the queued progress marker is surfaced too.
    graph = [e for e in out if "__ada_progress__" not in e]
    prog = [e for e in out if "__ada_progress__" in e]
    assert graph == graph_events
    assert prog and prog[0]["__ada_progress__"]["current"] == "brand"


def test_progress_iterator_completes_when_graph_exhausts_with_pending_progress():
    # A progress item that arrives late (after the graph is done) is discarded, not hung on.
    q: asyncio.Queue = asyncio.Queue()
    ctx = contextvars.copy_context()
    out = _run(_collect(R._aiter_sync_with_progress(iter([{"n": 1}]), q, ctx)))
    assert out == [{"n": 1}]


# ── Flag gate: off → plain _aiter_sync (byte-identical stream) ─────────────────────

def test_investigation_stream_is_plain_when_flag_off(monkeypatch):
    # ada.progress_events graduated to default-ON (CK-0.4, 2026-07-13); off = explicit "0"
    monkeypatch.setenv("AUGHOR_ADA_PROGRESS_EVENTS", "0")
    out = _run(_collect(R._investigation_stream(iter([{"a": 1}, {"b": 2}]))))
    assert out == [{"a": 1}, {"b": 2}]        # no progress markers, no wrapping


def test_investigation_stream_interleaves_when_flag_on(monkeypatch):
    # With the flag on, the stream binds a sink so an emit during a node surfaces as a marker.
    monkeypatch.setenv("AUGHOR_ADA_PROGRESS_EVENTS", "1")

    def _graph():
        # A one-node "graph" that emits progress while running, then yields its node event.
        progress.emit_phase_progress("cross_section", 1, 1, "brand")
        yield {"ada_cross_section": {}}

    async def _c():
        return await _collect(R._investigation_stream(_graph()))
    out = _run(_c())
    assert {"ada_cross_section": {}} in out
    markers = [e for e in out if "__ada_progress__" in e]
    assert markers and markers[0]["__ada_progress__"]["current"] == "brand"
