"""Arc OC-8 — the versioned doors an outside program uses: read the contract, list objects, PROPOSE an action.

`/ontology/v1` serves the published ontology as a contract (`aughor/ontology/builder_doors.py`): JSON Schemas of each
entity's objects and each declared action's parameters, and the same as TypeScript declarations, stamped with the
release they came from. `/objects/v1` lists objects and proposes declared actions. A proposal is staged in the Actions
inbox for a person and never runs from here — the doors read and propose; approving stays a person's (decision (d)).
Behind `ontology.builder_doors` (off): with it off every door says so (404), and nothing else changes.

The shapes here are the version: a field is added, never renamed or removed, while the prefix is `v1`.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from aughor.db.registry import BUILTIN_ID
from aughor.security.authz import caller, connection_owner_guard
from aughor.semantic.object_query import ObjectListing

#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
router = APIRouter(tags=["builders"], dependencies=[Depends(connection_owner_guard)])

FLAG = "ontology.builder_doors"


def _on() -> None:
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled(FLAG):
        raise HTTPException(status_code=404, detail=(
            "The doors for builders are off — an administrator turns them on in Settings → System → Feature flags "
            f"({FLAG})."))


def _scope(connection_id: str, schema_name: Optional[str]):
    """The published graph a scope serves and the release it is — the contract is always the published one."""
    from aughor.ontology.release import current_id
    from aughor.routers.ontology import served_ontology_graph
    graph = served_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="No ontology is built for this scope — it has no contract yet.")
    return graph, current_id(connection_id, graph.schema_name or "default")


@router.get("/ontology/v1/contract")
def get_ontology_contract(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)):
    """The published ontology as a contract: a JSON Schema per entity (its properties, key and the segments a listing
    may name) and per declared action (what a proposal carries), stamped with the release they came from."""
    _on()
    from aughor.ontology.builder_doors import ontology_contract
    graph, release = _scope(connection_id, schema_name)
    return ontology_contract(graph, release)


@router.get("/ontology/v1/types.d.ts", response_class=PlainTextResponse)
def get_ontology_typescript(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)):
    """The same contract as TypeScript declarations — an interface per entity, a union of its segments, a params
    interface per declared action and the release. Declarations only: nothing in them runs."""
    _on()
    from aughor.ontology.builder_doors import ontology_contract, typescript
    graph, release = _scope(connection_id, schema_name)
    return PlainTextResponse(typescript(ontology_contract(graph, release)),
                             media_type="application/typescript; charset=utf-8")


@router.get("/ontology/v1/actions/{action_id}/schema")
def get_action_schema(action_id: str, connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)):
    """One declared action's proposal schema."""
    _on()
    from aughor.ontology.builder_doors import action_schema
    graph, release = _scope(connection_id, schema_name)
    action = next((a for a in graph.declared_actions() if a.id == action_id), None)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No declared action '{action_id}' in this scope")
    return action_schema(action, release)


@router.post("/objects/v1/list")
def post_objects_v1_list(listing: ObjectListing, connection_id: str = BUILTIN_ID,
                         schema_name: Optional[str] = Query(default=None)):
    """One page of objects — the cockpit's listing door, with the release it was read under. An entity, or a segment
    of it (late, overdue, a rule's objects), the columns asked for, at most 200 a page."""
    _on()
    from aughor.routers.objects import post_object_listing
    _graph, release = _scope(connection_id, schema_name)
    page = post_object_listing(listing, connection_id=connection_id, schema_name=schema_name, execute=True)
    return {**page, "release": release} if isinstance(page, dict) else page


class ProposalBody(BaseModel):
    params: dict = Field(default_factory=dict)
    #: Why the program proposes it — shown to the person who decides.
    reasoning: str = ""
    #: The release the program read its contract under. Given and moved on, the proposal is refused: the action may
    #: no longer take what the program sends.
    release: str = ""


@router.post("/objects/v1/actions/{action_id}/propose")
def propose_declared_action(action_id: str, body: ProposalBody, connection_id: str = BUILTIN_ID,
                            schema_name: Optional[str] = Query(default=None)):
    """Propose a declared action: checked against its schema and its own criteria, then staged in the Actions inbox
    for a person, with the action's version pinned (Arc OC-6). Never runs here — `status` is `awaiting_approval`."""
    _on()
    from aughor.ontology.builder_doors import action_schema, validate_params
    graph, release = _scope(connection_id, schema_name)
    if body.release and release and body.release != release:
        raise HTTPException(status_code=409, detail=(
            f"The contract moved: the program read {body.release}, this scope serves {release}. Read "
            "GET /ontology/v1/contract again before proposing."))
    action = next((a for a in graph.declared_actions() if a.id == action_id), None)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No declared action '{action_id}' in this scope")
    problem = validate_params(action_schema(action, release), dict(body.params))
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    from aughor.actions.propose import ProposedAction, validate_proposals
    schema = graph.schema_name or ""
    [checked] = validate_proposals(graph, [ProposedAction(action_id=action_id, params=dict(body.params),
                                                           reasoning=body.reasoning)],
                                   scope=connection_id, schema_name=schema) or [None]
    if checked is None or not checked.ok:
        raise HTTPException(status_code=422, detail=(checked.message if checked is not None
                                                     else "The proposal did not validate."))
    from aughor.actions.inbox import StagedProposal, stage_proposal
    who = caller()
    staged = stage_proposal(StagedProposal(
        connection_id=connection_id, schema_name=schema, action_id=checked.action_id, params=checked.params,
        reasoning=body.reasoning or f"proposed by {who} through /objects/v1", proposer=who, source="builder",
        # one key per call: two proposals of one action are two decisions a person sees separately
        run_id=uuid.uuid4().hex, call_id=checked.action_id))
    return {"status": "awaiting_approval", "proposal_id": staged.id, "action_id": checked.action_id,
            "params": checked.params, "release": release, "expires_at": staged.expires_at,
            "action_pin": (staged.detail or {}).get("action_pin"),
            "message": "Proposed — a person approves it in the Actions inbox; nothing has run."}
