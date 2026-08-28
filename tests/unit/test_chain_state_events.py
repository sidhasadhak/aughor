"""FL-2 — chain-state narration: the failover chain's hops reach the SSE sink.

The chain's failure mode is that it WORKS silently (the provider-failover
lesson: a failing model can LOOK fine because another backend answered).
These tests pin the seam: the emitter is a no-op without a sink, delivers a
self-tagged payload with one, and the provider-side shim can never break a
call — narration is disposable, the failover is not.

Hermetic: no LLM client is constructed and no network is touched; the provider
module is imported only for its module-level `_emit_chain_state` shim.
"""
from __future__ import annotations

import asyncio

import pytest

from aughor.util.stream_events import clear_chain_sink, emit_chain_state, set_chain_sink


@pytest.mark.anyio
async def test_no_sink_is_a_noop():
    emit_chain_state("fallback", "gemini", "groq", model="m", role="analyst",
                     detail="x")  # must not raise; there is nothing else to observe


@pytest.mark.anyio
async def test_sink_receives_tagged_payload():
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    token = set_chain_sink(loop, q)
    try:
        emit_chain_state("fallback", "gemini", "groq", model="llama-3.3-70b",
                         role="analyst", detail="429 quota")
        await asyncio.sleep(0)  # let call_soon_threadsafe land
        payload = q.get_nowait()
    finally:
        clear_chain_sink(token)
    assert payload == {"__chain_state__": {
        "event": "fallback", "from": "gemini", "to": "groq",
        "model": "llama-3.3-70b", "role": "analyst", "detail": "429 quota"}}


@pytest.mark.anyio
async def test_detail_is_truncated_and_defaults_are_strings():
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    token = set_chain_sink(loop, q)
    try:
        emit_chain_state("link_failed", "gemini", "together", detail="x" * 999)
        await asyncio.sleep(0)
        inner = q.get_nowait()["__chain_state__"]
    finally:
        clear_chain_sink(token)
    assert len(inner["detail"]) == 200
    assert inner["model"] == "" and inner["role"] == ""


@pytest.mark.anyio
async def test_provider_shim_forwards(monkeypatch):
    from aughor.llm import provider as provider_mod

    seen: list = []
    monkeypatch.setattr("aughor.util.stream_events.emit_chain_state",
                        lambda *a, **k: seen.append((a, k)))
    provider_mod._emit_chain_state("fallback", "gemini", "groq",
                                   model="m", role="coder", detail="d")
    assert seen == [(("fallback", "gemini", "groq"),
                     {"model": "m", "role": "coder", "detail": "d"})]


@pytest.mark.anyio
async def test_provider_shim_never_breaks_the_call(monkeypatch):
    from aughor.llm import provider as provider_mod

    def _boom(*_a, **_k):
        raise RuntimeError("sink exploded")

    monkeypatch.setattr("aughor.util.stream_events.emit_chain_state", _boom)
    provider_mod._emit_chain_state("fallback", "gemini", "groq")  # must not raise
