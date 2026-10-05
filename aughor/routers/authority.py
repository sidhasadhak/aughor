"""The authority door (the 2027 study §M; phase 4) — the L0–L5 table for a connection's declared
actions, each level with its record, its receipt and its blockers; the graduation a person books
on an earned record; the demotion a person or a failed verification books; the executions.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from aughor.actions import authority as A
from aughor.db.registry import BUILTIN_ID
from aughor.security.authz import connection_owner_guard, get_principal

router = APIRouter(prefix="/authority", tags=["authority"], dependencies=[Depends(connection_owner_guard)])


def _actions(connection_id: str, schema_name: Optional[str]) -> dict:
    from aughor.ontology.store import load_latest_ontology
    graph = load_latest_ontology(connection_id, schema_name or None)
    if graph is None and schema_name:
        graph = load_latest_ontology(connection_id, None)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {a.id: a for a in graph.declared_actions()}


def _who(principal) -> str:
    for attr in ("user_id", "email", "id", "sub", "name"):
        v = getattr(principal, attr, "") if principal is not None else ""
        if v:
            return f"user:{v}"
    return ""


@router.get("")
def authority_table(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)) -> dict:
    """Every declared action's level on this connection, with the record it is computed from, the
    receipt that granted it, the demotion that took it, and what L4 would still need."""
    actions = _actions(connection_id, schema_name)
    return {"connection_id": connection_id, "levels": A.LEVELS, "graduation_n": A.GRADUATION_N,
            "actions": A.table(list(actions.values()), connection_id),
            "note": "L5 is unreachable until missions exist (phase 5); an irreversible action never passes L3"}


@router.get("/{action_id}/record")
def authority_record(action_id: str, connection_id: str = BUILTIN_ID,
                     schema_name: Optional[str] = Query(default=None), limit: int = 100) -> dict:
    actions = _actions(connection_id, schema_name)
    action = actions.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No declared action '{action_id}'")
    return {**A.level_for(action, connection_id), "graduation_check": A.evaluate_graduation(action, connection_id),
            "executions": A.executions(action_id, connection_id, limit=max(1, min(int(limit), 500)))}


class GraduateBody(BaseModel):
    connection_id: str = BUILTIN_ID
    schema_name: Optional[str] = None


@router.post("/{action_id}/graduate", status_code=201)
def authority_graduate(action_id: str, body: GraduateBody, principal=Depends(get_principal)) -> dict:
    """A person books the graduation receipt — the record decides whether it is earned."""
    actions = _actions(body.connection_id, body.schema_name)
    action = actions.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"No declared action '{action_id}'")
    try:
        return A.graduate(action, body.connection_id, by=_who(principal) or "unidentified")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class DemoteBody(BaseModel):
    connection_id: str = BUILTIN_ID
    why: str


@router.post("/{action_id}/demote", status_code=201)
def authority_demote(action_id: str, body: DemoteBody, principal=Depends(get_principal)) -> dict:
    """A person takes authority away — the same entry a failed verification books — and the
    standing grants of (action, scope) are withdrawn with it."""
    if not (body.why or "").strip():
        raise HTTPException(status_code=422, detail="a demotion says why")
    entry = A.demote(action_id, body.connection_id, why=body.why, by=_who(principal) or "unidentified")
    return {"entry": entry, "action_id": action_id, "scope": body.connection_id, "to_level": 3}
