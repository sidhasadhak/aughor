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


class AnnotateRequest(BaseModel):
    table: str
    body: str                               # the annotation text / corrected value
    column: str = ""                        # '' ⇒ whole-table
    key_column: str = ""                    # column whose value identifies the row
    row_key: str = ""                       # '' ⇒ whole-column
    kind: str = "annotation"                # annotation | correction


class AcceptRequest(BaseModel):
    actor: str = ""
    mint_grant: bool = False                # also mint a target-bound standing grant on accept


class RejectRequest(BaseModel):
    actor: str = ""


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
        # granted_by (A4) cites the standing grant that auto-allowed an unattended run ('' otherwise),
        # so the citation reaches the caller/receipt, not only the audit ledger.
        return {"status": result.status, "action_id": result.action_id,
                "outcome": result.outcome, "granted_by": result.granted_by}
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

    # A4: when the inbox is on, persist each VALID proposal so a human can accept it later (durable,
    # resolve-once). A single run_id groups this propose call; call_id = index makes a replay
    # idempotent. Off ⇒ the response is byte-identical to K4 (live proposals, no inbox_id).
    inbox_ids: dict[int, str] = {}
    if flag_enabled("automations.proposals"):
        import uuid as _uuid
        from aughor.kinetic.inbox import StagedProposal, stage_proposal
        run_id = _uuid.uuid4().hex
        for i, p in enumerate(proposals):
            if not p.ok:
                continue
            staged = stage_proposal(StagedProposal(
                connection_id=connection_id, schema_name=schema_name or "",
                action_id=p.action_id, params=p.params, reasoning=p.reasoning,
                proposer=body.actor or "agent", source="agent",
                run_id=run_id, call_id=str(i)))
            inbox_ids[i] = staged.id

    return {"proposals": [
        {"action_id": p.action_id, "status": p.status, "ok": p.ok, "params": p.params,
         "reasoning": p.reasoning, "message": p.message,
         **({"inbox_id": inbox_ids[i]} if i in inbox_ids else {})}
        for i, p in enumerate(proposals)]}


# ── A4: the resolve-once proposal inbox + standing grants ─────────────────────────

def _require_proposals() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("automations.proposals"):
        raise HTTPException(status_code=404, detail="Proposal inbox is not enabled")


@router.get("/kinetic-actions/inbox")
def list_inbox(connection_id: str = BUILTIN_ID, status: Optional[str] = Query(default=None)):
    """The staged proposals for a connection (optionally filtered by status) — the review queue."""
    _require_proposals()
    from aughor.kinetic.inbox import list_proposals
    return {"proposals": [p.model_dump() for p in list_proposals(connection_id, status)]}


@router.post("/kinetic-actions/inbox/{proposal_id}/accept")
def accept_inbox(proposal_id: str, body: AcceptRequest):
    """Accept a staged proposal and execute it — exactly once. The accept is the approval, so the
    executor bypasses the approval gate (never the criteria). A criterion failure returns 422 with
    the authored message; a re-accept of an already-resolved proposal returns 409."""
    _require_proposals()
    from aughor.kinetic.inbox import accept_proposal
    result, grant_id = accept_proposal(proposal_id, actor=body.actor, mint_grant=body.mint_grant)
    if result.status == "not_found":
        raise HTTPException(status_code=404, detail="No such proposal")
    if result.status == "already_resolved":
        raise HTTPException(status_code=409, detail={"status": result.status, "message": result.message})
    if result.ok:
        return {"status": result.status, "action_id": result.action_id,
                "outcome": result.outcome, "granted_by": result.granted_by,
                "minted_grant": grant_id}
    raise HTTPException(status_code=result.http_status(),
                        detail={"status": result.status, "action_id": result.action_id,
                                "message": result.message, **result.detail})


@router.post("/kinetic-actions/inbox/{proposal_id}/reject")
def reject_inbox(proposal_id: str, body: RejectRequest):
    """Reject a staged proposal — resolved with the actor, no side effect. A re-reject is a no-op."""
    _require_proposals()
    from aughor.kinetic.inbox import reject_proposal
    return {"rejected": reject_proposal(proposal_id, actor=body.actor)}


@router.get("/kinetic-actions/grants")
def list_grants_route(connection_id: str = BUILTIN_ID):
    """The target-bound standing grants on a connection — the pre-authorizations, for review/revoke."""
    _require_proposals()
    from aughor.kinetic.grants import list_grants
    return {"grants": [g.model_dump() for g in list_grants(connection_id)]}


@router.post("/kinetic-actions/grants/{grant_id}/revoke")
def revoke_grant_route(grant_id: str):
    """Revoke a standing grant — future unattended runs of that target hit the approval gate again."""
    _require_proposals()
    from aughor.kinetic.grants import revoke_grant
    if not revoke_grant(grant_id):
        raise HTTPException(status_code=404, detail="No such grant")
    return {"revoked": grant_id}


@router.post("/kinetic-actions/annotate")
def annotate(body: AnnotateRequest, connection_id: str = BUILTIN_ID):
    """Wave K5 — write a human overlay annotation/correction directly (the 'annotate this cell'
    affordance). Merged onto reads by K3 when `kinetic.overlay` is on; never mutates source. Flag-gated
    on `kinetic.overlay` → 404 when off."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("kinetic.overlay"):
        raise HTTPException(status_code=404, detail="Overlay edits are not enabled")
    if not body.table or not body.body:
        raise HTTPException(status_code=400, detail="table and body are required")
    from aughor.kinetic.overlay import OverlayEdit, save_edit
    edit = save_edit(OverlayEdit(
        connection_id=connection_id, table=body.table, column=body.column,
        key_column=body.key_column, row_key=body.row_key, kind=body.kind, body=body.body,
        source="user"))
    return {"id": edit.id, "target": edit.target()}


@router.get("/kinetic-actions/annotations")
def list_annotations(connection_id: str = BUILTIN_ID):
    """Wave K5 — the human overlay edits on a connection, for the review UI."""
    from aughor.kinetic.overlay import edits_for_connection
    return {"edits": [e.model_dump() for e in edits_for_connection(connection_id)]}
