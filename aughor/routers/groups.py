"""HB-1 — groups, level grants, and the two receipt doors (explain + route).

The routing half's surface (§3.18). The built-in groups are synthesized from the
roles (never stored — see ``rbac/groups.py``); function groups, their members and
their level grants are the org's own rows. The two GET receipts are the wave's
point: ``/access/explain`` answers "may this principal do this, and which grant
says so", ``/access/route`` answers "where does a departure about this thing go" —
both before anything sends, so the map can be wrong out loud (the falsifier) rather
than wrong in a channel.

Org-scoped like ``roles.py``: every read and write is against the caller's own org.
Mutations and the people-naming reads sit at ``admin.manage_roles`` in the policy
table; identity-off deployments feel no gate, as everywhere.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aughor.metastore.models import group_principal, principal_kind
from aughor.org.context import current_org_id
from aughor.rbac.access import may
from aughor.rbac.groups import (
    BUILTIN,
    add_member,
    delete_group,
    get_group,
    list_groups,
    list_members,
    remove_member,
    upsert_group,
    valid_group_id,
)
from aughor.rbac.levels import LADDER, ROLE_DEFAULT_LEVELS, is_level, normalize_level
from aughor.rbac.roles import BUILTIN_ROLES
from aughor.rbac.routing import route

router = APIRouter(tags=["groups"])


# ── Requests ─────────────────────────────────────────────────────────────────

class GroupRequest(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    channel_trigger_id: str = ""


class MemberRequest(BaseModel):
    principal: str  # user:... | agent:...


class GrantRequest(BaseModel):
    principal: str  # user:... | group:... | agent:...
    securable: str  # metric:x | promise:y | domain:z | ...
    level: str      # view | subscribe | edit | manage | own


def _group_dict(g) -> dict:
    return {"id": g.id, "name": g.name, "kind": g.kind, "description": g.description,
            "channel_trigger_id": g.channel_trigger_id,
            "created_at": g.created_at, "updated_at": g.updated_at}


# ── Groups ───────────────────────────────────────────────────────────────────

@router.get("/groups")
def get_groups():
    """The built-in groups (platform-shipped, a level per securable kind) + the org's function
    groups. The ladder rides along as reference data so a client never hardcodes it."""
    builtin = [
        {"id": r.name, "name": r.label, "kind": BUILTIN,
         "description": r.description, "channel_trigger_id": "",
         "levels": ROLE_DEFAULT_LEVELS.get(r.name, {})}
        for r in BUILTIN_ROLES.values()
    ]
    return {
        "ladder": list(LADDER),
        "builtin_groups": builtin,
        "groups": [_group_dict(g) for g in list_groups(current_org_id())],
    }


@router.post("/groups", status_code=201)
def create_group(req: GroupRequest):
    """Create or update a function group (idempotent on its id)."""
    if not valid_group_id(req.id):
        raise HTTPException(status_code=400,
                            detail=f"not a valid group id: {req.id!r} (lowercase slug)")
    g = upsert_group(current_org_id(), req.id, req.name or req.id,
                     req.description, req.channel_trigger_id)
    return _group_dict(g)


@router.delete("/groups/{group_id}")
def remove_group(group_id: str):
    """Delete a function group, its memberships and its level grants — a grant
    naming a gone group routes nobody, but leaving rows behind is how a re-created
    group would silently inherit its predecessor's reach."""
    org = current_org_id()
    from aughor.metastore.store import list_grants, revoke_grant
    gp = group_principal(group_id)
    for grant in list_grants(org_id=org, principal=gp):
        revoke_grant(gp, grant.securable, grant.privilege, org_id=org)
    removed = delete_group(org, group_id)
    return {"removed": removed}


# ── Members ──────────────────────────────────────────────────────────────────

@router.get("/groups/{group_id}/members")
def get_members(group_id: str):
    org = current_org_id()
    if get_group(org, group_id) is None:
        raise HTTPException(status_code=404, detail=f"no such group: {group_id!r}")
    return {"members": list_members(org, group_id)}


@router.post("/groups/{group_id}/members", status_code=201)
def create_member(group_id: str, req: MemberRequest):
    """Add a person or an agent (a member is a principal string, one rule for both)."""
    try:
        add_member(current_org_id(), group_id, req.principal.strip())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"members": list_members(current_org_id(), group_id)}


@router.delete("/groups/{group_id}/members")
def delete_member(group_id: str, principal: str = Query(...)):
    removed = remove_member(current_org_id(), group_id, principal.strip())
    return {"removed": removed}


# ── Level grants ─────────────────────────────────────────────────────────────

@router.get("/access/grants")
def get_level_grants(securable: str | None = None, principal: str | None = None):
    """The org's LEVEL grants (the ladder's rows; USAGE stays the catalog plane's)."""
    from aughor.metastore.store import list_grants
    grants = [g for g in list_grants(org_id=current_org_id(),
                                     principal=principal, securable=securable)
              if is_level(g.privilege)]
    return [{"principal": g.principal, "securable": g.securable,
             "level": normalize_level(g.privilege), "created_at": g.created_at}
            for g in grants]


@router.post("/access/grants", status_code=201)
def create_level_grant(req: GrantRequest):
    lvl = normalize_level(req.level)
    if not is_level(lvl):
        raise HTTPException(status_code=400,
                            detail=f"unknown level {req.level!r} (one of {list(LADDER)})")
    if principal_kind(req.principal.strip()) not in ("user", "group", "agent"):
        raise HTTPException(status_code=400,
                            detail=f"not a grantable principal: {req.principal!r}")
    if ":" not in (req.securable or ""):
        raise HTTPException(status_code=400,
                            detail=f"not a securable string: {req.securable!r}")
    from aughor.metastore.store import add_grant
    g = add_grant(req.principal.strip(), req.securable.strip(), lvl,
                  org_id=current_org_id())
    return {"principal": g.principal, "securable": g.securable,
            "level": normalize_level(g.privilege), "created_at": g.created_at}


@router.delete("/access/grants")
def delete_level_grant(principal: str = Query(...), securable: str = Query(...),
                       level: str = Query(...)):
    from aughor.metastore.store import revoke_grant
    removed = revoke_grant(principal.strip(), securable.strip(),
                           normalize_level(level), org_id=current_org_id())
    return {"removed": removed}


# ── The receipts ─────────────────────────────────────────────────────────────

def _parents_list(parents: str | None) -> list[str]:
    return [p.strip() for p in (parents or "").split(",") if p.strip()]


@router.get("/access/explain")
def explain_access(principal: str, level: str, securable: str,
                   parents: str | None = None, domain: str | None = None):
    """May ``principal`` act at ``level`` on ``securable`` — and which grant says so.
    ``parents`` is the meaning chain upward (comma-separated securables); ``domain``
    is the object's grant-bearing tag value, if tagged."""
    tags = {"domain": domain} if domain else None
    d = may(principal.strip(), level, securable.strip(),
            org_id=current_org_id(), parents=_parents_list(parents), tags=tags)
    return d.to_dict()


@router.get("/access/route")
def route_departure(securable: str, owner: str | None = None,
                    parents: str | None = None, domain: str | None = None):
    """Where a departure about ``securable`` lands: its owner (when the owner field
    names a principal) and every Subscribe-or-higher holder, each group through its
    channel — resolved and explained BEFORE anything sends."""
    tags = {"domain": domain} if domain else None
    dests = route(securable.strip(), org_id=current_org_id(), owner=owner or "",
                  parents=_parents_list(parents), tags=tags)
    return {"securable": securable.strip(),
            "destinations": [d.to_dict() for d in dests]}
