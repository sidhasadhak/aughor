"""FastAPI dependency to gate a route behind a capability.

Usage (opt-in, per route — no handler-body changes):

    @router.post("/monitors", dependencies=[Depends(require_capability(Capability.MONITORS))])
    def create_monitor(...): ...

Returns **HTTP 402 Payment Required** (distinct from 401 auth / 403 forbidden) with an
`upgrade_hint`, so the frontend can show an upsell rather than an error. With the default
`enterprise` tier every capability is granted, so adding the dependency is a no-op until a
lower tier is assigned.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Query

from aughor.licensing.capabilities import Capability
from aughor.licensing.resolver import has_capability, resolve_tier


def require_capability(cap: Capability):
    """Build a dependency that 402s when the resolved tier lacks `cap`."""
    def _dep(connection_id: Optional[str] = Query(default=None)) -> None:
        if not has_capability(cap, conn_id=connection_id):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "capability_locked",
                    "capability": cap.value,
                    "current_tier": resolve_tier(connection_id).value,
                    "upgrade_hint": f"'{cap.value}' requires a higher plan.",
                },
            )
    return _dep
