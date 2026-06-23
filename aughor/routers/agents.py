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
from aughor.org.context import current_org_id
from aughor.platform import budget as budget_gov

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
    """The fleet roster: each agent's charter + effective governance + recent spend
    + its cumulative budget status (the scoped spend cap, derived on read)."""
    spend = _spend_by_agent()
    return [
        {
            **c.to_dict(),
            "governance": effective_governance(c.id, workspace_id).to_dict(),
            "spend": spend.get(c.id, {"runs": 0, "total_tokens": 0, "query_count": 0}),
            "budget": budget_gov.status("agent", c.id).to_dict(),
        }
        for c in list_charters()
    ]


@router.get("/agents/budget")
def get_budgets():
    """The fleet's cumulative spend governance: the Org cap + every agent's cap, each
    with derived status (unbounded · ok · warning · hard_stop). The same derivation the
    submit-time gate enforces, so the dashboard never disagrees with the enforcement."""
    return {
        "org": budget_gov.status("org", current_org_id()).to_dict(),
        "agents": {c.id: budget_gov.status("agent", c.id).to_dict() for c in list_charters()},
    }


class BudgetPolicyPatch(BaseModel):
    scope_type: str                      # "org" | "agent"
    scope_id: str                        # org id, or charter id for an agent
    limit_tokens: int
    window: str = "calendar_month"       # | "lifetime"
    warn_percent: int = 80
    hard_stop: bool = True
    active: bool = True


@router.put("/agents/budget")
def put_budget(body: BudgetPolicyPatch):
    """Set (or update) a cumulative budget policy for a scope. Raising the limit above
    current spend clears a breach automatically — status is derived, not stored."""
    if body.scope_type not in ("org", "agent"):
        raise HTTPException(status_code=422, detail="scope_type must be 'org' or 'agent'")
    if body.scope_type == "agent" and get_charter(body.scope_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    budget_gov.set_policy(
        body.scope_type, body.scope_id,
        limit_tokens=body.limit_tokens, window=body.window,
        warn_percent=body.warn_percent, hard_stop=body.hard_stop, active=body.active,
    )
    return budget_gov.status(body.scope_type, body.scope_id).to_dict()


class AgentGovernancePatch(BaseModel):
    enabled: Optional[bool] = None
    token_budget: Optional[int] = None
    time_budget_s: Optional[int] = None
    model: Optional[str] = None          # per-agent LLM model; "" clears back to the role default
    workspace_id: Optional[str] = None   # None → app scope (the Org default)


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, body: AgentGovernancePatch):
    """Enable/disable, re-budget, or pin the model for an agent. Only the provided fields change."""
    if get_charter(agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    gov = set_governance(
        agent_id,
        scope=body.workspace_id,
        enabled=body.enabled,
        token_budget=body.token_budget,
        time_budget_s=body.time_budget_s,
        model=body.model,
    )
    return {"agent_id": agent_id, "governance": gov.to_dict()}
