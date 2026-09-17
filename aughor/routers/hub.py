"""HB-6 — the hub-wide map door. One read: every automation on one screen, with the
seven columns the roadmap names (trigger, destinations, grant, owner, last run, cost,
probation state). Agent Ops' Map answers this per agent; this door answers it hub-wide,
assembled entirely from existing stores — a read, never a build."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from aughor.security.authz import connection_owner_guard

#: DATA-06 — a `conn_id` this door is asked to filter by must belong to the caller's org.
router = APIRouter(tags=["hub"], dependencies=[Depends(connection_owner_guard)])


@router.get("/hub/map")
def get_hub_map(conn_id: str = ""):
    """The map. Omit `conn_id` for the whole hub; pass it to narrow to one connection.

    `cost` on every row is a floor, not a total (`floor: true` says so in the payload):
    it folds the session log over the traces this automation's recent runs caused, and
    carries `unpriced_calls`/`calls_without_usage` so an unknown price never renders as
    free. `probation.precision` is null until anything is marked — "not measured", never
    0%."""
    from aughor.hub.map import hub_map
    return hub_map(conn_id=conn_id)
