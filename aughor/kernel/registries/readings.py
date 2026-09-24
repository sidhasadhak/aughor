"""Declared-readings loader registry — the platform's SQL checks read the ontology's readings at a moment WITHOUT
importing the agent (the registry inversion, docs/PLATFORM_ARCHITECTURE.md).

PENDING item 27: a person declares on the ontology (agent side) that a property is a reading at a moment — a stock
level, a balance, a headcount — taken over a time property, and the platform's trust checks (``sql/trust_checks``)
flag a written SUM of one that spans more than one of its moments. A direct import would be a Platform→Agent edge, so
the agent registers its loader here at bootstrap and the platform reads through the seam. With no loader registered
(a bare platform, an eval harness outside the app) nothing is declared and the check is silent.
"""
from __future__ import annotations

from typing import Callable, Optional

# fn(connection_id) -> {table: {column: {"over": str, "note": str}}}, every name lower-cased
ReadingsLoader = Callable[[str], dict]

_loader: Optional[ReadingsLoader] = None


def register_readings_loader(fn: ReadingsLoader) -> None:
    """Install (or replace) the loader. The agent registers the real one at bootstrap; tests register fakes."""
    global _loader
    _loader = fn


def clear() -> None:
    """Drop the loader (test isolation)."""
    global _loader
    _loader = None


def declared_readings_for(connection_id: str) -> dict:
    """The platform-side read: ``{table: {column: {"over", "note"}}}``, {} when no loader is registered, the
    connection declares none, or the loader fails — the statement is then checked for nothing more."""
    if _loader is None or not connection_id:
        return {}
    try:
        return _loader(connection_id) or {}
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the declared-readings loader is best-effort; the SUM check is skipped",
                 counter="readings.loader", conn_id=connection_id or None)
        return {}
