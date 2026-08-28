"""FL-2 — the provider chain's stream-event side channel, platform-safe.

`emit_chain_state` began life next to the other sink emitters in
``aughor/agent/progress.py`` — but its CALLER is the transport layer
(``aughor/llm/provider.py``), and the platform must not import the agent
(``tests/unit/test_platform_agent_boundary.py``; invert via a contract, per
docs/PLATFORM_ARCHITECTURE.md). So the chain-state sink lives here, in neutral
territory, with the agent sink's exact shape: the SSE stream (the routers
layer, which may import both sides) binds ``(event_loop, queue)`` around a run;
the provider emits; no sink bound means a single ContextVar read and out.
It shares the progress sink's QUEUE, not its ContextVar — payloads are
self-tagged (``__chain_state__``), so the consumer cannot confuse them.
"""
from __future__ import annotations

import contextvars
from typing import Optional

_CHAIN_SINK: contextvars.ContextVar[Optional[tuple]] = contextvars.ContextVar(
    "llm_chain_sink", default=None)


def set_chain_sink(loop, queue) -> "contextvars.Token":
    """Bind the chain-state sink in the current context (returns a reset token)."""
    return _CHAIN_SINK.set((loop, queue))


def clear_chain_sink(token) -> None:
    try:
        _CHAIN_SINK.reset(token)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "clearing the chain sink is best-effort teardown; a stale token is harmless",
                 counter="llm.chain_sink_clear")


def emit_chain_state(event: str, from_backend: str, to_backend: str,
                     model: str = "", role: str = "", detail: str = "") -> None:
    """Push one provider-chain transition to the active sink, if any.

    The failover chain's whole failure mode is that it WORKS: the primary dies,
    a fallback answers, and the only witness is a log line — the user watches a
    silent spinner and then an answer that never says which backend wrote it.
    This makes the transition a stream event ({event: fallback|link_failed,
    from, to, model, role, detail}) the SSE layer forwards as ``chain_state``.
    Exactly as disposable as phase progress: emitting must never perturb the
    call it narrates."""
    sink = _CHAIN_SINK.get()
    if sink is None:
        return
    loop, queue = sink
    payload = {"event": event, "from": from_backend, "to": to_backend,
               "model": model or "", "role": role or "", "detail": (detail or "")[:200]}
    try:
        loop.call_soon_threadsafe(queue.put_nowait, {"__chain_state__": payload})
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "chain-state emit is disposable telemetry; a closed loop / full queue is fine",
                 counter="llm.chain_state_emit")
