"""FL-1b — the resume seam: a job-streamed run mirrors into the frame hub.

THE test this wave owes the codebase: the hub (FL-1a) is importable on its own,
so a test that only exercises it can stay green while nothing consumes it — the
built-but-not-wired failure mode this repo keeps rediscovering. These tests
drive the REAL `_investigation_job_streamed` bridge (with a faked inner
investigation stream) and assert the hub saw the frames — they fail the moment
the mirror is unplugged.

Hermetic: the kernel ledger is the per-session temp system.db from conftest; the
inner `_stream_investigation` is monkeypatched; no LLM, no connection, no HTTP.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.kernel.flags import flag_overrides
from aughor.util.frame_hub import hub

FRAMES = [
    'data: {"type": "start", "investigation_id": "inv-1"}\n\n',
    'data: {"type": "headline", "headline": "x"}\n\n',
    'data: {"type": "done"}\n\n',
]


def _fake_stream(*_a, **_k):
    async def _gen():
        for f in FRAMES:
            yield f
    return _gen()


@pytest.mark.anyio
async def test_job_stream_mirrors_into_hub(monkeypatch):
    from aughor.routers import investigations as inv

    monkeypatch.setattr(inv, "_stream_investigation", _fake_stream)
    with flag_overrides({"ask.resume_stream": True}):
        out = [s async for s in inv._investigation_job_streamed(
            "q", "conn-x", None, session_id="sess-seam-1")]

    assert out == FRAMES  # the request-side bridge is unchanged by the mirror
    c = hub().attach("ask:sess-seam-1")
    assert c.snapshot == FRAMES  # THE seam: an unplugged mirror fails here
    assert c.closed and c.error is None


@pytest.mark.anyio
async def test_flag_off_leaves_no_hub_run(monkeypatch):
    from aughor.routers import investigations as inv

    monkeypatch.setattr(inv, "_stream_investigation", _fake_stream)
    out = [s async for s in inv._investigation_job_streamed(
        "q", "conn-x", None, session_id="sess-seam-off")]
    assert out == FRAMES
    assert hub().status("ask:sess-seam-off") is None


@pytest.mark.anyio
async def test_reattach_mid_run_gets_snapshot_then_tail(monkeypatch):
    from aughor.routers import investigations as inv

    gate = asyncio.Event()

    def fake(*_a, **_k):
        async def _gen():
            yield FRAMES[0]
            await gate.wait()
            yield FRAMES[1]
            yield FRAMES[2]
        return _gen()

    monkeypatch.setattr(inv, "_stream_investigation", fake)
    with flag_overrides({"ask.resume_stream": True}):
        agen = inv._investigation_job_streamed("q", "conn-x", None,
                                               session_id="sess-seam-mid")
        assert await agen.__anext__() == FRAMES[0]

        # A reloaded tab reattaches while the run is live: snapshot, then tail.
        c = hub().attach("ask:sess-seam-mid")
        assert c.snapshot == [FRAMES[0]]
        gate.set()
        rest = [s async for s in agen]
        tail = [f async for f in c.tail()]

    assert rest == FRAMES[1:]
    assert tail == FRAMES[1:]


@pytest.mark.anyio
async def test_superseding_turn_closes_the_stale_run(monkeypatch):
    from aughor.routers import investigations as inv

    monkeypatch.setattr(inv, "_stream_investigation", _fake_stream)
    with flag_overrides({"ask.resume_stream": True}):
        stale = hub().open_run("ask:sess-seam-super")  # a prior turn never closed
        stale.publish("data: old\n\n")
        out = [s async for s in inv._investigation_job_streamed(
            "q", "conn-x", None, session_id="sess-seam-super")]

    assert out == FRAMES
    c = hub().attach("ask:sess-seam-super")
    assert c.snapshot == FRAMES  # the new turn's frames, not the stale run's


@pytest.mark.anyio
async def test_bridge_carries_a_prebuilt_body_too():
    # The analyst branch hands the bridge an ALREADY-CONSTRUCTED generator via a
    # lambda (its origin resolution awaits happen request-side) — the bridge must
    # not care which shape it gets.
    from aughor.routers.investigations import _job_streamed_body

    async def _body():
        for f in FRAMES:
            yield f

    prebuilt = _body()
    with flag_overrides({"ask.resume_stream": True}):
        out = [s async for s in _job_streamed_body(
            lambda: prebuilt, session_id="sess-seam-analyst")]

    assert out == FRAMES
    assert hub().attach("ask:sess-seam-analyst").snapshot == FRAMES


@pytest.mark.anyio
async def test_resume_endpoint_semantics():
    from aughor.routers.investigations import ask_resume_stream

    r = await ask_resume_stream("anything")  # flag off → nothing to resume
    assert r.status_code == 204

    with flag_overrides({"ask.resume_stream": True}):
        r = await ask_resume_stream("sess-ep-none")  # no run for this conversation
        assert r.status_code == 204

        done = hub().open_run("ask:sess-ep-closed")
        done.publish("data: a\n\n")
        done.close()
        r = await ask_resume_stream("sess-ep-closed")  # finished → history owns it
        assert r.status_code == 204

        live = hub().open_run("ask:sess-ep-live")
        live.publish("data: x\n\n")
        resp = await ask_resume_stream("sess-ep-live")
        agen = resp.body_iterator
        assert await agen.__anext__() == "data: x\n\n"  # snapshot replays first
        live.publish("data: y\n\n")                     # ...then the live tail
        assert await agen.__anext__() == "data: y\n\n"
        live.close()
        assert [f async for f in agen] == []
