"""Value-sample loader registry — platform reads the agent's warmed samples
WITHOUT importing the agent (the registry inversion, docs/PLATFORM_ARCHITECTURE.md).

The profiler (agent side) persists per-column entity-value samples (R5); the
platform's filter guard (``sql/join_guard``) wants to fuzzy-bind absent literals
from them offline before scanning the warehouse. A direct import would be a
Platform→Agent edge, so the agent registers its loader here at bootstrap and
the platform reads through the seam. With no loader registered (a bare-platform
deployment, an eval harness outside the app) the guard simply falls back to its
live-domain sample — the plug-and-play property the boundary guarantees.
"""
from __future__ import annotations

from typing import Callable, Optional

# fn(connection_id) -> {(table, column): [values]}
ValueSampleLoader = Callable[[str], dict]

_loader: Optional[ValueSampleLoader] = None


def register_value_sample_loader(fn: ValueSampleLoader) -> None:
    """Install (or replace) the loader. The agent registers the real one at
    bootstrap; tests register fakes."""
    global _loader
    _loader = fn


def clear() -> None:
    """Drop the loader (test isolation)."""
    global _loader
    _loader = None


def load_value_samples_for(connection_id: str) -> dict:
    """The platform-side read: {(table, column): [values]}, {} when no loader is
    registered or the loader fails — callers always have a live fallback."""
    if _loader is None or not connection_id:
        return {}
    try:
        return _loader(connection_id) or {}
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "value-sample loader is best-effort; guard falls back to the live domain",
                 counter="value_samples.loader", conn_id=connection_id or None)
        return {}
