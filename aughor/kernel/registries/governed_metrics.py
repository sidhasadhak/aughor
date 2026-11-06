"""Which governed metrics a connection has — the platform's seam (2026-11-06).

A chart names its axis by the governed metric a query computes (`answer/series_names.py`): the metric's
own label when the query is that metric, filter and all. The metrics live in the semantic layer, on the
agent side of the boundary, so the agent registers its reader here at bootstrap and the platform reads
through the seam, never importing it.

With no reader registered (a bare platform, a harness outside the app) a connection has no governed
metrics, and an axis is named by its column — never a metric's name it did not earn.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# fn(connection_id) -> the connection's metric definitions (each with `label`, `sql`, `filters`, `status`)
Reader = Callable[[str], list[Any]]

_reader: Optional[Reader] = None


def register_metric_reader(reader: Reader) -> None:
    """Install (or replace) the reader. The agent registers the real one at bootstrap; tests may register fakes."""
    global _reader
    _reader = reader


def clear() -> None:
    """Drop the reader (test isolation)."""
    global _reader
    _reader = None


def metrics_for(connection_id: str) -> list[Any]:
    """The connection's governed metrics — empty when none is registered, or the reader failed (counted)."""
    if _reader is None or not connection_id:
        return []
    try:
        return list(_reader(connection_id) or [])
    except Exception as exc:  # noqa: BLE001 — a name is cosmetic; the chart still draws
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the governed-metric reader failed; axes are named by their columns",
                 counter="governed_metrics.read_failed", conn_id=connection_id or None)
        return []
