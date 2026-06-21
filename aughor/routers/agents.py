"""The /agents surface — manage the fleet (Phase 0).

The roster of agent charters + each one's effective governance (enabled, budget)
+ recent spend (aggregated from the metered job rows), and a PATCH to enable/disable
or re-budget an agent. v1 operates the app scope (the Org's fleet config); pass
`workspace_id` to read/write a workspace override (resolver is ready for it).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.kernel.agents import (
    charter_for_kind,
    effective_governance,
    get_charter,
    list_charters,
    set_governance,
)
from aughor.kernel.ledger import Ledger

logger = logging.getLogger(__name__)
router = APIRouter()


def _spend_by_agent(limit: int = 500) -> dict[str, dict]:
    """Aggregate recent metered runs per agent (by the charter owning each job kind)."""
    out: dict[str, dict] = {}
    for job in Ledger.default().jobs_where(limit=limit):
        c = charter_for_kind(job.get("kind"))
        agg = out.setdefault(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0})
        agg["runs"] += 1
        m = job.get("metrics")
        if isinstance(m, dict):
            agg["total_tokens"] += int(m.get("total_tokens") or 0)
            agg["query_count"] += int(m.get("query_count") or 0)
    return out


@router.get("/agents")
def list_agents(workspace_id: Optional[str] = None):
    """The fleet roster: each agent's charter + effective governance + recent spend."""
    spend = _spend_by_agent()
    return [
        {
            **c.to_dict(),
            "governance": effective_governance(c.id, workspace_id).to_dict(),
            "spend": spend.get(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0}),
        }
        for c in list_charters()
    ]


class AgentGovernancePatch(BaseModel):
    enabled: Optional[bool] = None
    token_budget: Optional[int] = None
    time_budget_s: Optional[int] = None
    workspace_id: Optional[str] = None   # None → app scope (the Org default)


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, body: AgentGovernancePatch):
    """Enable/disable or re-budget an agent. Only the provided fields change."""
    if get_charter(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    gov = set_governance(
        agent_id,
        scope=body.workspace_id,
        enabled=body.enabled,
        token_budget=body.token_budget,
        time_budget_s=body.time_budget_s,
    )
    return {"agent_id": agent_id, "governance": gov.to_dict()}
