"""Wave K2 — the HTTP surface for executing declared KineticActions.

POST-only and governed: the route resolves the declared action from the connection's ontology,
then runs it through the single executor (`kinetic.executor.execute_kinetic_action`). RBAC is
enforced by the app-wide `enforce_rbac` dependency (a POST resolves to the `resource.write` floor
in `rbac/policy.py`); the executor owns submission criteria + graduated approval + audit. Flag-gated
on `kinetic.actions` so the route 404s when the kinetic plane is off.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from aughor.db.registry import BUILTIN_ID

router = APIRouter(tags=["kinetic"])


class ExecuteRequest(BaseModel):
    params: dict = Field(default_factory=dict)
    actor: str = ""


class ProposeRequest(BaseModel):
    context: str                            # a finding / question the proposal is grounded in
    actor: str = "agent"


def _resolve_graph(connection_id: str, schema_name: Optional[str]):
    from aughor.ontology.store import load_latest_ontology
    graph = load_latest_ontology(connection_id, schema_name or None)
    if graph is None and schema_name:
        graph = load_latest_ontology(connection_id, None)
    return graph


@router.post("/kinetic-actions/{action_id}/execute")
def execute_action(
    action_id: str,
    body: ExecuteRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Run one declared action. A criterion failure returns 422 with the authored message; a
    high-risk action needing approval returns 428 (approve via POST /approvals/allow, then retry);
    success returns 200 with the dispatch outcome."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("kinetic.actions"):
        raise HTTPException(status_code=404, detail="Kinetic actions are not enabled")

    # The public store loader already overlays human overrides (so kinetic_actions are applied);
    # a declared action implies the ontology is cached, so the fast path is sufficient here.
    graph = _resolve_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    action = graph.kinetic_actions.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No declared action '{action_id}'")

    from aughor.kinetic.executor import execute_kinetic_action
    # scope = the connection id — the grain the approval allowlist is keyed on.
    result = execute_kinetic_action(action, body.params, actor=body.actor, scope=connection_id)
    if result.ok:
        return {"status": result.status, "action_id": result.action_id, "outcome": result.outcome}
    # Every non-OK outcome maps to an HTTP status carrying the authored message VERBATIM.
    raise HTTPException(
        status_code=result.http_status(),
        detail={"status": result.status, "action_id": result.action_id,
                "message": result.message, **result.detail},
    )


@router.post("/kinetic-actions/propose")
def propose_actions_route(
    body: ProposeRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave K4: the agent proposes declared actions for a context. Returns STAGED, dry-run-validated
    proposals — nothing is executed (a human accepts, then POSTs to .../execute). Flag-gated on
    `kinetic.agent_actions` → 404 when off. The proposer LLM call runs on the `fast` role binding."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("kinetic.agent_actions"):
        raise HTTPException(status_code=404, detail="Agent action proposals are not enabled")
    graph = _resolve_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")

    from aughor.kinetic.propose import propose_actions
    proposals = propose_actions(graph, body.context, scope=connection_id)
    return {"proposals": [
        {"action_id": p.action_id, "status": p.status, "ok": p.ok, "params": p.params,
         "reasoning": p.reasoning, "message": p.message}
        for p in proposals]}
