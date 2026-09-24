"""PENDING.md item 9 — the company-brain map door. One read: every store behind the "brain" as a
box with a live count and the door that serves it, and the measured edges between them
(`aughor/hub/brain_map.py`) — a read, never a build."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from aughor.security.authz import connection_owner_guard

#: DATA-06 — the connection this door is asked about must belong to the caller's org.
router = APIRouter(tags=["hub"], dependencies=[Depends(connection_owner_guard)])


@router.get("/brain/map")
def get_brain_map(connection_id: str, workspace_id: str = ""):
    """The map for one connection. A box whose store cannot be read carries ``count: null`` and
    the reason in ``line`` — never a zero that means "could not read"."""
    from aughor.hub.brain_map import brain_map
    return brain_map(connection_id, workspace_id=workspace_id or None)
