"""Slice 2 of the MLflow-underneath Agent Workspace: the request-scoped session
contextvar + the /ask stream wrapper that pins it.

The session id rides the request body, so — unlike org/user (middleware-set) — it
is pinned by the ask stream itself and read ambiently by the telemetry seam for
MLflow trace attribution (the Sessions view). These tests pin the contextvar
round-trip and that the wrapper sets it for the whole stream, then restores it.
"""
from __future__ import annotations

import asyncio

from aughor.org.context import (current_session_id, reset_session_id,
                                set_session_id)


def test_session_contextvar_roundtrip_and_default():
    assert current_session_id() == ""          # default: no session
    tok = set_session_id("sess-1")
    try:
        assert current_session_id() == "sess-1"
    finally:
        reset_session_id(tok)
    assert current_session_id() == ""          # restored


def test_set_session_id_none_falls_back_to_empty():
    tok = set_session_id(None)  # type: ignore[arg-type]
    try:
        assert current_session_id() == ""      # never blank/None
    finally:
        reset_session_id(tok)


def test_stream_with_session_pins_for_the_whole_stream_then_resets():
    from aughor.routers.investigations import _stream_with_session

    seen: list[str] = []

    async def _inner():
        seen.append(current_session_id())
        yield "e1"
        seen.append(current_session_id())
        yield "e2"

    async def _run():
        out = []
        async for ev in _stream_with_session("sess-77", _inner()):
            out.append(ev)
        return out

    events = asyncio.run(_run())
    assert events == ["e1", "e2"]
    assert seen == ["sess-77", "sess-77"]       # active for every yielded event
    assert current_session_id() == ""           # reset once the stream closes


def test_stream_with_session_empty_is_a_noop():
    from aughor.routers.investigations import _stream_with_session

    seen: list[str] = []

    async def _inner():
        seen.append(current_session_id())
        yield "x"

    async def _run():
        async for _ in _stream_with_session("", _inner()):
            pass

    asyncio.run(_run())
    assert seen == [""]
    assert current_session_id() == ""
