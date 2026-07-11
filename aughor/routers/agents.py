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


# ── User-defined agents (flag `agents.user_defined`) ──────────────────────────
# Dynamic, user-created personas (aughor/user_agents/) — distinct from the
# static built-in fleet charters above. Routes 404 when the flag is off.

def _require_user_agents() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("agents.user_defined"):
        raise HTTPException(status_code=404,
                            detail="user-defined agents are disabled (flag agents.user_defined)")


def _validate_agent_fields(name: Optional[str] = None, instructions: Optional[str] = None,
                           connection_id: Optional[str] = None,
                           doc_ids: Optional[list] = None) -> None:
    from aughor.user_agents.models import INSTRUCTIONS_MAX, NAME_MAX
    if name is not None and not (0 < len(name.strip()) <= NAME_MAX):
        raise HTTPException(status_code=422, detail=f"name must be 1..{NAME_MAX} chars")
    if instructions is not None and len(instructions) > INSTRUCTIONS_MAX:
        raise HTTPException(status_code=422,
                            detail=f"instructions exceed {INSTRUCTIONS_MAX} chars")
    if connection_id:
        from aughor.db.registry import BUILTIN_ID, list_connections
        known = {c.get("id") for c in list_connections()} | {BUILTIN_ID}
        if connection_id not in known:
            raise HTTPException(status_code=422,
                                detail=f"unknown connection '{connection_id}'")
    if doc_ids:
        from aughor.knowledge.indexer import get_document
        missing = [d for d in doc_ids if get_document(d) is None]
        if missing:
            raise HTTPException(status_code=422,
                                detail=f"unknown document id(s): {', '.join(missing)}")


def _validate_agent_packs(pack_ids: Optional[list]) -> None:
    if not pack_ids:
        return
    try:
        from aughor.packs.intake import active_packs
        known = {p.id for p in active_packs()}
    except Exception:
        known = set()
    missing = [p for p in pack_ids if p not in known]
    if missing:
        raise HTTPException(status_code=422,
                            detail=f"unknown/inactive pack id(s): {', '.join(missing)}")


class UserAgentCreate(BaseModel):
    name: str
    instructions: str = ""
    connection_id: str = ""
    schema_scope: str = ""
    doc_ids: list[str] = []
    pack_ids: list[str] = []


class UserAgentPatch(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None
    connection_id: Optional[str] = None
    schema_scope: Optional[str] = None
    doc_ids: Optional[list[str]] = None
    pack_ids: Optional[list[str]] = None
    enabled: Optional[bool] = None


@router.get("/agents/custom")
def list_user_agents():
    """All user-defined agents (the persona roster, newest first)."""
    _require_user_agents()
    from aughor.user_agents import list_agents
    return [a.model_dump() for a in list_agents()]


@router.post("/agents/custom", status_code=201)
def create_user_agent(body: UserAgentCreate):
    _require_user_agents()
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    _validate_agent_packs(body.pack_ids)
    from aughor.org.context import current_org_id
    from aughor.user_agents import create_agent
    agent = create_agent(body.name, instructions=body.instructions,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         owner=current_org_id() or "")
    return agent.model_dump()


@router.get("/agents/custom/{agent_id}")
def get_user_agent(agent_id: str):
    _require_user_agents()
    from aughor.user_agents import get_agent
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return agent.model_dump()


@router.patch("/agents/custom/{agent_id}")
def patch_user_agent(agent_id: str, body: UserAgentPatch):
    _require_user_agents()
    _validate_agent_fields(body.name, body.instructions, body.connection_id, body.doc_ids)
    _validate_agent_packs(body.pack_ids)
    from aughor.user_agents import update_agent
    agent = update_agent(agent_id, name=body.name, instructions=body.instructions,
                         connection_id=body.connection_id, schema_scope=body.schema_scope,
                         doc_ids=body.doc_ids, pack_ids=body.pack_ids,
                         enabled=body.enabled)
    if agent is None:
        raise HTTPException(status_code=404, detail="No such agent")
    return agent.model_dump()


@router.delete("/agents/custom/{agent_id}")
def delete_user_agent(agent_id: str):
    _require_user_agents()
    from aughor.user_agents import delete_agent
    if not delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="No such agent")
    return {"deleted": agent_id}
