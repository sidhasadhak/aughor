"""Purge-hook registries — invert the catalog/connection delete cascade.

The platform owns the delete-cascade ORCHESTRATION (``db/purge.py``) but must not
import the agent stores it cascades into. Instead each agent store registers a hook
here at startup (``agent.bootstrap.register_agent_plugins``); the orchestrator runs
the registered hooks. Three keying schemes mirror how derived artifacts are
addressed:

  • **connection-keyed**    — ``fn(conn_id, org_id) -> {label: count}``
  • **schema-keyed**        — ``fn(conn_id, schema) -> {label: count}``
  • **investigation-keyed** — ``fn(inv_ids) -> {label: count}``

Every hook runs under :func:`aughor.kernel.errors.tolerate`, so one failing store
never blocks the rest — the same best-effort / observable contract ``db/purge.py``
had when it imported the stores directly. Counts merge by summation; each store owns
distinct labels, so the merged dict matches the legacy single-pass summary.
"""
from __future__ import annotations

from typing import Callable, Optional

from aughor.kernel.errors import tolerate

ConnHook = Callable[[str, Optional[str]], dict]
SchemaHook = Callable[[str, str], dict]
InvHook = Callable[[list], dict]

_CONN: list[tuple[str, ConnHook]] = []
_SCHEMA: list[tuple[str, SchemaHook]] = []
_INV: list[tuple[str, InvHook]] = []


def register_purge_hook(name: str, fn: ConnHook) -> None:
    """Register a connection-keyed purge hook: ``fn(conn_id, org_id) -> counts``."""
    _CONN.append((name, fn))


def register_schema_purge_hook(name: str, fn: SchemaHook) -> None:
    """Register a schema-keyed purge hook: ``fn(conn_id, schema) -> counts``."""
    _SCHEMA.append((name, fn))


def register_investigations_purge_hook(name: str, fn: InvHook) -> None:
    """Register an investigation-keyed purge hook: ``fn(inv_ids) -> counts``."""
    _INV.append((name, fn))


def clear() -> None:
    """Drop every registered hook (idempotent re-registration / test isolation)."""
    _CONN.clear()
    _SCHEMA.clear()
    _INV.clear()


def _merge(counts: dict, name: str, fn, *args) -> None:
    try:
        out = fn(*args) or {}
        for k, v in out.items():
            counts[k] = counts.get(k, 0) + (v or 0)
    except Exception as e:  # one failing store never blocks the rest
        tolerate(e, f"purge hook {name!r}", counter=f"purge.hook.{name}")


def run_purge_hooks(conn_id: str, org_id: Optional[str]) -> dict:
    counts: dict[str, int] = {}
    for name, fn in list(_CONN):
        _merge(counts, name, fn, conn_id, org_id)
    return counts


def run_schema_purge_hooks(conn_id: str, schema: str) -> dict:
    counts: dict[str, int] = {}
    for name, fn in list(_SCHEMA):
        _merge(counts, name, fn, conn_id, schema)
    return counts


def run_investigations_purge_hooks(inv_ids: list) -> dict:
    counts: dict[str, int] = {}
    for name, fn in list(_INV):
        _merge(counts, name, fn, inv_ids)
    return counts
