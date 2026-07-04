"""RBAC administration — the role catalogue, the caller's effective grants, and the
org role roster (P3).

The roster read/write endpoints are org-scoped: they operate on the caller's *own*
org (``current_org_id()``, bound per-request by ``_OrgContextMiddleware``) — an admin
can never manage another tenant's roles. They are gated on ``admin.manage_roles``,
so only an owner may assign/revoke (in localhost/identity-off mode the caller is
treated as owner, so local administration works unchanged).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from aughor.org.context import current_org_id
from aughor.rbac import (
    BUILTIN_ROLES,
    Permission,
    is_builtin_role,
    permissions_for,
    resolve_roles,
)
from aughor.rbac.deps import gate_permission
from aughor.rbac.store import assign_role, list_assignments, revoke_role
from aughor.security.authz import get_principal

router = APIRouter(tags=["rbac"])


class AssignRoleRequest(BaseModel):
    user_id: str
    role: str


def _sorted_perms(perms) -> list[str]:
    return sorted(p.value for p in perms)


@router.get("/rbac/roles")
def list_roles():
    """The built-in role catalogue + the permissions each grants (reference data)."""
    return [
        {"name": r.name, "description": r.description, "permissions": _sorted_perms(r.permissions)}
        for r in BUILTIN_ROLES.values()
    ]


@router.get("/rbac/me")
def my_access(request: Request):
    """The caller's effective identity, roles and permissions — so a client can
    show/hide admin surfaces. In localhost mode the caller resolves to owner."""
    principal = get_principal(request)
    return {
        "user_id": principal.user_id if principal else None,
        "org_id": principal.org_id if principal else current_org_id(),
        "roles": resolve_roles(principal),
        "permissions": _sorted_perms(permissions_for(principal)),
    }


@router.get("/rbac/assignments", dependencies=[gate_permission(Permission.ADMIN_MANAGE_ROLES)])
def get_assignments():
    """Every role grant in the caller's org (the admin roster)."""
    org = current_org_id()
    return [
        {"org_id": a.org_id, "user_id": a.user_id, "role": a.role,
         "created_at": a.created_at, "updated_at": a.updated_at}
        for a in list_assignments(org)
    ]


@router.post("/rbac/assignments", status_code=201,
             dependencies=[gate_permission(Permission.ADMIN_MANAGE_ROLES)])
def create_assignment(req: AssignRoleRequest):
    """Grant a built-in role to a user in the caller's org. Idempotent."""
    role = (req.role or "").strip().lower()
    if not is_builtin_role(role):
        raise HTTPException(status_code=400, detail=f"unknown role '{req.role}'")
    if not (req.user_id or "").strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    a = assign_role(current_org_id(), req.user_id.strip(), role)
    return {"org_id": a.org_id, "user_id": a.user_id, "role": a.role,
            "created_at": a.created_at, "updated_at": a.updated_at}


@router.delete("/rbac/assignments", dependencies=[gate_permission(Permission.ADMIN_MANAGE_ROLES)])
def delete_assignment(user_id: str = Query(...), role: str = Query(...)):
    """Revoke a role grant from a user in the caller's org."""
    removed = revoke_role(current_org_id(), user_id.strip(), (role or "").strip().lower())
    return {"removed": removed}
