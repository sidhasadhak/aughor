"""Wave K2 — the HTTP surface for executing declared KineticActions.

POST-only and governed: the route resolves the declared action from the connection's ontology,
then runs it through the single executor (`kinetic.executor.execute_kinetic_action`). RBAC is
enforced by the app-wide `enforce_rbac` dependency (a POST resolves to the `resource.write` floor
in `rbac/policy.py`); the executor owns submission criteria + graduated approval + audit. The
kinetic plane is always on — the `kinetic.actions` flag was DELETED (hardwired 2026-08-02); do
not reintroduce a gate on that name: `flag_enabled` answers False for unregistered names, which
would tell every deployment its actions are off.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aughor.db.registry import BUILTIN_ID
from aughor.security.authz import caller, connection_owner_guard

logger = logging.getLogger(__name__)

#: DATA-06 — every connection a door of this router names belongs to the caller's org (identity on).
# The prefix is spelled ONCE — every route below lives under it, and the wire paths
# are byte-identical to the eleven that used to spell it per-decorator.
router = APIRouter(prefix="/kinetic-actions", tags=["kinetic"],
                   dependencies=[Depends(connection_owner_guard)])


class ExecuteRequest(BaseModel):
    params: dict = Field(default_factory=dict)
    actor: str = ""                         # ignored: the person signed in is who acts (`authz.caller`)
    #: Arc OC-4 — when running it needs approval, stage it in the Actions inbox for a person instead of answering 428:
    #: what a cockpit's action button does. Read only while `ontology.cockpit_pieces` is on.
    propose_if_gated: bool = False
    #: Where the person was when they asked — shown on the approval card beside the params.
    reasoning: str = ""
    #: Arc OC-6 — the version of each property this action sets, as the person read it (0: they saw none set). A run
    #: made against a version since changed is refused (409) and writes nothing.
    expected: dict[str, int] = Field(default_factory=dict)


class ProposeRequest(BaseModel):
    context: str                            # a finding / question the proposal is grounded in
    actor: str = "agent"                    # ignored: the agent proposes; no client names the proposer


class AnnotateRequest(BaseModel):
    table: str
    body: str                               # the annotation text / corrected value
    column: str = ""                        # '' ⇒ whole-table
    key_column: str = ""                    # column whose value identifies the row
    row_key: str = ""                       # '' ⇒ whole-column
    kind: str = "annotation"                # annotation | correction


class AcceptRequest(BaseModel):
    actor: str = ""                         # ignored: the person signed in is who accepts
    mint_grant: bool = False                # also mint a target-bound standing grant on accept
    #: SP-9 — the approver's answers to a draft's OPEN choices, from the card's own
    #: fields: {"<action number>.<key>": value}. Only an open choice may be filled;
    #: the inbox refuses anything else whole.
    fills: dict[str, str] = {}


class RejectRequest(BaseModel):
    actor: str = ""                         # ignored: the person signed in is who rejects


class SupersedeRequest(BaseModel):
    actor: str = ""                         # ignored: the person signed in is who supersedes
    #: What replaced the draft — shown as the resolved row's message.
    note: str = ""


def _resolve_graph(connection_id: str, schema_name: Optional[str]):
    from aughor.ontology.store import load_latest_ontology
    graph = load_latest_ontology(connection_id, schema_name or None)
    if graph is None and schema_name:
        graph = load_latest_ontology(connection_id, None)
    return graph


@router.post("/{action_id}/execute")
def execute_action(
    action_id: str,
    body: ExecuteRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Run one declared action. A criterion failure returns 422 with the authored message; a
    high-risk action needing approval returns 428 (approve via POST /approvals/allow, then retry) —
    or, asked with ``propose_if_gated`` while `ontology.cockpit_pieces` is on, is staged for a person
    and returns 200 with ``status: proposed`` and the proposal's id (Arc OC-4); success returns 200
    with the dispatch outcome, what its verification found, and its Action ledger entry — the answer had dropped the
    last two, so a press read "done" whatever its check said."""
    # The public store loader already overlays human overrides (so kinetic_actions are applied);
    # a declared action implies the ontology is cached, so the fast path is sufficient here.
    graph = _resolve_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    action = graph.kinetic_actions.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No declared action '{action_id}'")

    from aughor.actions.executor import execute_kinetic_action
    # scope = the connection id — the grain the approval allowlist is keyed on.
    result = execute_kinetic_action(action, body.params, actor=caller(), scope=connection_id,
                                    schema_name=schema_name or "", expected_versions=body.expected or None)
    if result.ok:
        # granted_by (A4) cites the standing grant that auto-allowed an unattended run ('' otherwise),
        # so the citation reaches the caller/receipt, not only the audit ledger.
        return {"status": result.status, "action_id": result.action_id,
                "outcome": result.outcome, "granted_by": result.granted_by,
                "verification": result.verification, "action_entry": result.action_entry}
    if result.status == "approval_required" and body.propose_if_gated:
        staged = _propose_gated(action, body, connection_id, schema_name)
        if staged is not None:
            return staged
    # Every non-OK outcome maps to an HTTP status carrying the authored message VERBATIM.
    raise HTTPException(
        status_code=result.http_status(),
        detail={"status": result.status, "action_id": result.action_id,
                "message": result.message, **result.detail},
    )


def _propose_gated(action, body: ExecuteRequest, connection_id: str, schema_name: Optional[str]) -> Optional[dict]:
    """Arc OC-4 — the action a person asked to run, which needs approval, staged for a person to accept: no model is
    called and nothing runs; accepting it runs it through the governed pipeline as any accepted proposal does. None
    while `ontology.cockpit_pieces` is off, so the door answers 428 exactly as before."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("ontology.cockpit_pieces"):
        return None
    import uuid as _uuid

    from aughor.actions.executor import coerce_params
    from aughor.actions.inbox import StagedProposal, stage_proposal
    staged = stage_proposal(StagedProposal(
        connection_id=connection_id, schema_name=schema_name or "", action_id=action.id,
        params=coerce_params(action, body.params), reasoning=body.reasoning.strip()[:500], proposer=caller(),
        source="cockpit", run_id=_uuid.uuid4().hex, call_id="0"))
    return {"status": "proposed", "action_id": action.id, "inbox_id": staged.id}


@router.post("/propose")
def propose_actions_route(
    body: ProposeRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave K4: the agent proposes declared actions for a context. Returns STAGED, dry-run-validated
    proposals — nothing is executed (a human accepts, then POSTs to .../execute). Always on
    (flag endgame Wave 5, 2026-08-06): data-gated — no declared actions ⇒ nothing to propose,
    and every proposal still passes a human. The proposer LLM call runs on the `fast` role binding."""
    graph = _resolve_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")

    from aughor.actions.propose import propose_actions
    proposals = propose_actions(graph, body.context, scope=connection_id, schema_name=schema_name or "")

    # A4: persist each VALID proposal so a human can accept it later (durable,
    # resolve-once). A single run_id groups this propose call; call_id = index makes a
    # replay idempotent.
    inbox_ids: dict[int, str] = {}
    import uuid as _uuid
    from aughor.actions.inbox import StagedProposal, stage_proposal
    run_id = _uuid.uuid4().hex
    for i, p in enumerate(proposals):
        if not p.ok:
            continue
        staged = stage_proposal(StagedProposal(
            connection_id=connection_id, schema_name=schema_name or "",
            action_id=p.action_id, params=p.params, reasoning=p.reasoning,
            proposer="agent", source="agent",
            run_id=run_id, call_id=str(i)))
        inbox_ids[i] = staged.id

    return {"proposals": [
        {"action_id": p.action_id, "status": p.status, "ok": p.ok, "params": p.params,
         "reasoning": p.reasoning, "message": p.message,
         **({"inbox_id": inbox_ids[i]} if i in inbox_ids else {})}
        for i, p in enumerate(proposals)]}


# ── A4: the resolve-once proposal inbox + standing grants ─────────────────────────

def _resume_parked_run(proposal_id: str) -> None:
    """DS-8 — if this proposal was an automation's, let its parked run continue.

    Here at the ROUTER, not inside the inbox, and the reason is structural: A already depends
    on K (an automation's governed-write step runs through K's executor), so K reaching back
    for A's engine would close the cycle H5 exists to keep open — there is a ratchet on it.
    The application layer may import both planes, which is exactly where this codebase already
    puts the other cascade between them (`DELETE /automations/{id}` purges the proposals an
    automation staged).

    Called unconditionally after a resolve, including on `already_resolved`: that status is
    the losing half of a race, and the winner may have died between resolving the proposal and
    resuming the run. `resume_run` is a no-op on a run that is not paused, so a redundant call
    costs a row read and the recovery is worth more.

    Best-effort. The governed write has already happened by the time this runs; raising here
    would report a completed write as a failed one and invite the caller to retry it. A run
    that fails to wake stays `paused` and the heartbeat's sweep picks it up within the minute.
    """
    try:
        from aughor.actions.inbox import get_proposal
        p = get_proposal(proposal_id)
        if p is None or not p.run_id or not p.source.startswith("automation:"):
            return
        from aughor.automations.engine import resume_run
        resume_run(p.run_id)
    except Exception:
        logger.warning("resuming the run parked on proposal %s failed", proposal_id,
                       exc_info=True)


def _finish_accepted_send(proposal_id: str, result) -> str:
    """An accepted Slack send ends as an unattended one does: its chart in the thread the
    post opened, and the thread filed on what the send is about, so a reply there reaches
    that object (`engine.finish_accepted_slack_post`). Here at the ROUTER for
    `_resume_parked_run`'s reason — the inbox may not import the engine — and before the
    resume, so a later step that replies into the thread finds the chart already there.

    Only an executed Slack send reaches the engine; best-effort, because the post has
    already happened. Returns the filed link id, or "".
    """
    if not result.ok or not (result.outcome or {}).get("ts"):
        return ""
    try:
        from aughor.actions.inbox import get_proposal
        p = get_proposal(proposal_id)
        if p is None or p.kind != "outbound_send" or (p.params or {}).get("trigger_id"):
            return ""
        from aughor.automations.engine import finish_accepted_slack_post
        return finish_accepted_slack_post(p.params or {}, result.outcome or {},
                                          proposer=p.proposer)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "an accepted send's chart and filing are best-effort — the post stands",
                 counter="inbox.accepted_send")
        return ""


@router.get("/inbox")
def list_inbox(connection_id: str = BUILTIN_ID, status: Optional[str] = Query(default=None)):
    """The staged proposals for a connection (optionally filtered by status) — the review queue."""
    from aughor.actions.inbox import list_proposals
    return {"proposals": [p.model_dump() for p in list_proposals(connection_id, status)]}


@router.get("/inbox/{proposal_id}")
def get_inbox_proposal(proposal_id: str):
    """ONE staged proposal, by id — the approval card's read (SP-9). Chat learns a
    proposal's id from the turn that staged it and renders the RECORD, not the prose;
    Attention holds ids from the needs-human strip. Same shape as one list row."""
    from aughor.actions.inbox import get_proposal
    p = get_proposal(proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="No such proposal")
    return {"proposal": p.model_dump()}


@router.post("/inbox/{proposal_id}/accept")
def accept_inbox(proposal_id: str, body: AcceptRequest):
    """Accept a staged proposal and execute it — exactly once. The accept is the approval, so the
    executor bypasses the approval gate (never the criteria). A criterion failure returns 422 with
    the authored message; a re-accept of an already-resolved proposal returns 409."""
    from aughor.actions.inbox import accept_proposal
    result, grant_id = accept_proposal(proposal_id, actor=caller(), mint_grant=body.mint_grant,
                                       fills=body.fills or None)
    link_id = _finish_accepted_send(proposal_id, result)
    _resume_parked_run(proposal_id)
    if result.status == "not_found":
        raise HTTPException(status_code=404, detail="No such proposal")
    if result.status == "already_resolved":
        raise HTTPException(status_code=409, detail={"status": result.status, "message": result.message})
    if result.ok:
        return {"status": result.status, "action_id": result.action_id,
                "outcome": {**(result.outcome or {}), **({"link_id": link_id} if link_id else {})},
                "granted_by": result.granted_by, "minted_grant": grant_id}
    raise HTTPException(status_code=result.http_status(),
                        detail={"status": result.status, "action_id": result.action_id,
                                "message": result.message, **result.detail})


@router.post("/inbox/{proposal_id}/supersede")
def supersede_inbox(proposal_id: str, body: SupersedeRequest):
    """Resolve a pending draft as REPLACED (SP-11) — a person finished the same ask in
    the real editor, so the staged draft must not sit beside the saved record looking
    like separate work. No side effect, first-responder-wins; a re-supersede is a
    no-op, and an already-accepted draft stays what it is."""
    from aughor.actions.inbox import supersede_proposal
    return {"superseded": supersede_proposal(proposal_id, actor=caller(),
                                             note=body.note)}


@router.post("/inbox/{proposal_id}/reject")
def reject_inbox(proposal_id: str, body: RejectRequest):
    """Reject a staged proposal — resolved with the actor, no side effect. A re-reject is a no-op."""
    from aughor.actions.inbox import reject_proposal
    rejected = reject_proposal(proposal_id, actor=caller())
    if rejected:
        _resume_parked_run(proposal_id)
    return {"rejected": rejected}


@router.get("/grants")
def list_grants_route(connection_id: str = BUILTIN_ID):
    """The target-bound standing grants on a connection — the pre-authorizations, for review/revoke."""
    from aughor.actions.grants import list_grants
    return {"grants": [g.model_dump() for g in list_grants(connection_id)]}


@router.post("/grants/{grant_id}/revoke")
def revoke_grant_route(grant_id: str):
    """Revoke a standing grant — future unattended runs of that target hit the approval gate again."""
    from aughor.actions.grants import revoke_grant
    if not revoke_grant(grant_id):
        raise HTTPException(status_code=404, detail="No such grant")
    return {"revoked": grant_id}


@router.post("/annotate")
def annotate(body: AnnotateRequest, connection_id: str = BUILTIN_ID):
    """Wave K5 — write a human overlay annotation/correction directly (the 'annotate this cell'
    affordance). Merged onto reads by K3; never mutates source."""
    if not body.table or not body.body:
        raise HTTPException(status_code=400, detail="table and body are required")
    from aughor.actions.overlay import OverlayEdit, save_edit
    edit = save_edit(OverlayEdit(
        connection_id=connection_id, table=body.table, column=body.column,
        key_column=body.key_column, row_key=body.row_key, kind=body.kind, body=body.body,
        source="user"))
    return {"id": edit.id, "target": edit.target()}


@router.get("/annotations")
def list_annotations(connection_id: str = BUILTIN_ID):
    """Wave K5 — the human overlay edits on a connection, for the review UI.

    Scoped to the current org, the way every read of this ledger is (`accepted_object_edits`): listing an
    edit a withdrawal could not then find is a worse answer than not listing it."""
    from aughor.actions.overlay import edits_for_connection
    from aughor.org.context import current_org_id
    return {"edits": [e.model_dump() for e in edits_for_connection(connection_id, current_org_id() or "")]}


@router.get("/edits/history")
def get_edit_history(connection_id: str = BUILTIN_ID, object_type: str = "", row_key: str = "", column: str = ""):
    """Arc OC-6 — every version of the edits on this connection's objects, newest first: who set what, the value it
    replaced, who withdrew it. Narrowed to one object type, one object (`row_key`) and one property."""
    from aughor.actions.overlay import edit_history
    from aughor.org.context import current_org_id
    return {"history": edit_history(connection_id, object_type=object_type, row_key=row_key, column=column,
                                    org_id=current_org_id() or None)}


@router.delete("/annotations/{edit_id}")
def withdraw_annotation(edit_id: str, connection_id: str = BUILTIN_ID):
    """ON-4 — withdraw ONE overlay edit: an annotation on a row, or a property an accepted action set on
    an object. The next read stops merging it and the object reads as the warehouse holds it — nothing is
    restored, because the source was never written. 404 when this connection and org hold no such edit."""
    from aughor.actions.overlay import withdraw_edit
    from aughor.org.context import current_org_id
    if connection_id.startswith("domain:"):
        # PENDING item 25 — the page of an organisation's ontology sent its own token here, and every withdrawal
        # answered "no such edit": an edit lives on the connection its object's rows live on, and says so.
        raise HTTPException(status_code=400, detail=(
            "An edit is withdrawn on the connection its object lives on, not on an organisation's ontology — "
            "send that connection's id"))
    gone = withdraw_edit(edit_id, connection_id, current_org_id() or None, actor=caller())
    if gone is None:
        raise HTTPException(status_code=404,
                            detail=f"No overlay edit '{edit_id}' on this connection — it may already be withdrawn")
    return {"withdrawn": gone.id, "target": gone.target(), "kind": gone.kind,
            "object_type": gone.object_type, "property": gone.column}
