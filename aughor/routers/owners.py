"""CB-3 — owners the platform can reach: the inventory and the link doors (§3.21).

``GET /owners`` lists every owner text the organisation's declarations carry — metrics, processes,
business rules, glossary — with where each is used and whether it resolves to a principal, the
unresolved first. ``PUT /owners/links`` is a person linking one text to one principal, once;
``DELETE`` takes it back. Org-scoped like groups.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from aughor.org.context import current_org_id
from aughor.rbac.owners import link_owner, list_owner_links, owner_inventory, unlink_owner

router = APIRouter(tags=["owners"])


class OwnerLinkRequest(BaseModel):
    owner_text: str
    principal: str


def _linked_by(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    for attr in ("user_id", "email", "id"):
        v = getattr(principal, attr, "") if principal is not None else ""
        if v:
            return str(v)
    return ""


@router.get("/owners")
def list_owners(connection_id: Optional[str] = Query(default=None)):
    """Every owner in use, resolved or not, with its uses. ``connection_id`` narrows the ontology
    read to one connection (the catalog and the glossary are org-wide either way)."""
    org = current_org_id()
    ids = [connection_id] if connection_id else None
    return {"owners": owner_inventory(org, connection_ids=ids),
            "links": [link.to_dict() for link in list_owner_links(org)]}


@router.put("/owners/links")
def put_owner_link(req: OwnerLinkRequest, request: Request):
    try:
        link = link_owner(current_org_id(), req.owner_text, req.principal, linked_by=_linked_by(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return link.to_dict()


@router.delete("/owners/links")
def delete_owner_link(owner_text: str = Query(...)):
    if not unlink_owner(current_org_id(), owner_text):
        raise HTTPException(status_code=404, detail="no link for that owner")
    return {"ok": True}
