"""Ingestion / event sink registry — invert "platform produces, agent consumes".

The platform produces data and lifecycle events the AGENT wants to react to — a
knowledge connector's documents (Confluence/Notion → embed + vector upsert), a
completed investigation (→ RAG index), a deleted connection (→ evict the profile
cache). The platform must not import the agent, so it emits via ``ingest(kind, **payload)``
and the agent registers the sink for each ``kind`` at startup
(``agent.bootstrap.register_agent_plugins``).

With no sink registered the emit is a guarded no-op: the platform still does its own
work (fetch the documents, store the investigation, delete the connection), but the
agent-side *reaction* (indexing, RAG, cache eviction) is a capability that may simply
be absent — exactly the plug-and-play property the boundary guarantees.
"""
from __future__ import annotations

from typing import Callable

from aughor.kernel.errors import tolerate

_SINKS: dict[str, Callable] = {}


def register_ingest_sink(kind: str, fn: Callable) -> None:
    """Register the consumer for an ingestion ``kind`` (e.g. ``"knowledge"``)."""
    _SINKS[kind] = fn


def clear() -> None:
    """Drop every registered sink (idempotent re-registration / test isolation)."""
    _SINKS.clear()


def ingest(kind: str, **doc) -> dict:
    """Emit one document to the registered sink for ``kind``. Returns the sink's
    result (e.g. the indexer registry entry), or ``{}`` when no sink is registered
    or the sink fails (best-effort, never raises into the connector)."""
    fn = _SINKS.get(kind)
    if fn is None:
        return {}
    try:
        return fn(**doc) or {}
    except Exception as e:
        tolerate(e, f"ingest sink {kind!r}", counter=f"ingest.{kind}")
        return {}
