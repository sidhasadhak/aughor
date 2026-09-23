"""Idea 2 · the Watcher's alert proposals, on demand.

The heartbeat's version runs after an exploration; this door runs the same deterministic
work now — read every metric's daily series, learn its distribution, stage the watch in the
inbox for a person — and reports what was staged, what already was, and why the rest were
skipped. No model call, warehouse reads only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from aughor.security.authz import connection_owner_guard, get_principal

# DATA-06 — a door that names a connection asks whose it is, on every route.
router = APIRouter(tags=["alerts"], dependencies=[Depends(connection_owner_guard)])


@router.post("/alerts/propose/{connection_id}")
def propose_alerts_now(connection_id: str, principal=Depends(get_principal)) -> dict:
    """Stage an anomaly watch for every metric on this connection that has a daily series
    and enough settled history; each lands in the inbox with its evidence, unarmed."""
    from aughor.monitors.sentinel import propose_for_connection
    return propose_for_connection(connection_id)
