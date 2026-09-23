"""Idea 4 · the settling store's door — what the platform has learned about when each
table's numbers stop changing, and a way to take today's reading on demand.

Every store has a door and a count (Arc CB's rule for the map): here the tables sampled,
their evidence, each verdict with its reason, and the connection's learned lag. The POST
takes the reading the heartbeat would take at its next tick — a count per table, no model —
for an operator who wants the evidence to start today rather than tomorrow.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from aughor.security.authz import get_principal

router = APIRouter(tags=["settling"])


@router.get("/settling/{connection_id}")
def settling_summary(connection_id: str, principal=Depends(get_principal)) -> dict:
    """Each sampled table with its observations, its verdict (the lag, or why there is
    none yet) and the connection's learned lag — ``null`` until a table has earned one."""
    from aughor.settling import summary
    return summary(connection_id)


@router.post("/settling/{connection_id}/sample")
def settling_sample_now(connection_id: str, principal=Depends(get_principal)) -> dict:
    """Take today's reading now: count each recent day on every profiled time table and
    file the counts. Idempotent within a day — a second reading replaces the first."""
    from aughor.db.measure import run_sql_for
    from aughor.settling.sampler import sample_connection
    return sample_connection(connection_id, run_sql_for(connection_id))
