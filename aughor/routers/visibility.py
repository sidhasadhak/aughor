"""CB-5 — how much of the business the platform can see (§3.21).

``GET /visibility`` is the number and the gap for one connection: the share of tables the ontology
maps (the profiler's universe as the denominator, declared exclusions out of it), the share of joins
that were measured rather than name-matched, and the held sends grouped by the definition that would
clear them — the top one is "approve this and N unblock". ``PUT``/``DELETE /visibility/exclusions``
are a person declaring a table out of scope, with one of the honest reasons.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from aughor.ontology.declarations import EXCLUSION_REASONS
from aughor.ontology.visibility import declare_exclusion, visibility, withdraw_exclusion
from aughor.security.authz import connection_owner_guard

# DATA-06: every door here names a connection, so the owner guard sits on the router.
router = APIRouter(tags=["visibility"], dependencies=[Depends(connection_owner_guard)])
BUILTIN_ID = "builtin"


class ExclusionRequest(BaseModel):
    table: str
    reason: str
    note: str = ""


def _by(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    for attr in ("user_id", "email", "id"):
        v = getattr(principal, attr, "") if principal is not None else ""
        if v:
            return str(v)
    return ""


@router.get("/visibility")
def get_visibility(connection_id: str = BUILTIN_ID, schema_name: Optional[str] = Query(default=None)):
    from aughor.agent.framing import served_graph
    graph = served_graph(connection_id, schema_name)       # a read; never builds
    context_graph = None
    try:
        from aughor.ontology.context_graph_store import load_graph
        from aughor.org.context import current_org_id
        context_graph = load_graph(current_org_id(), connection_id, schema_name or (getattr(graph, "schema_name", "") or ""))
    except Exception as exc:  # noqa: BLE001 — the joins line is additive
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the context graph could not be read for the joins line", counter="visibility.context_graph")
    schema = schema_name or (getattr(graph, "schema_name", "") or "default")
    out = visibility(connection_id, schema, graph, context_graph=context_graph)
    out["exclusion_reasons"] = list(EXCLUSION_REASONS)
    return out


@router.put("/visibility/exclusions")
def put_exclusion(req: ExclusionRequest, request: Request, connection_id: str = BUILTIN_ID,
                  schema_name: Optional[str] = Query(default=None)):
    try:
        e = declare_exclusion(connection_id, schema_name or "default", req.table, req.reason, note=req.note, declared_by=_by(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return e.to_dict()


@router.delete("/visibility/exclusions")
def delete_exclusion(table: str = Query(...), connection_id: str = BUILTIN_ID,
                     schema_name: Optional[str] = Query(default=None)):
    if not withdraw_exclusion(connection_id, schema_name or "default", table):
        raise HTTPException(status_code=404, detail="no exclusion for that table")
    return {"ok": True}
