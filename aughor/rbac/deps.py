"""FastAPI dependency to gate a route behind an RBAC permission (P3 enforcement).

Mirrors ``licensing/deps.require_capability`` but on the *user* axis: it returns
**HTTP 403 Forbidden** (distinct from 402 capability-locked / 401 unauthenticated)
when the caller's roles don't grant the permission.

Usage (opt-in, per route — no handler-body change):

    from aughor.rbac import Permission
    from aughor.rbac.deps import gate_permission

    @router.delete("/connections/{conn_id}",
                   dependencies=[gate_permission(Permission.CONNECTION_DELETE)])
    def remove_connection(...): ...

Two conditions make the gate a NO-OP, so adding it is safe everywhere and does
nothing until a deployment opts into RBAC:

  1. **identity off / localhost** — no principal is bound, the resolver treats the
     caller as owner, so every permission is granted (byte-identical to today).
  2. **the org's tier lacks ``Capability.RBAC_SSO``** — RBAC is an enterprise
     capability; a plan without it keeps the REC-05 identity + owner-checks but no
     per-permission enforcement.

When both the identity flag and the RBAC_SSO capability are present, the gate
resolves the caller's roles (bootstrapping the org's first user as owner) and 403s
a caller whose roles don't grant ``perm``.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from aughor.rbac.permissions import Permission


def require_permission(perm: Permission):
    """Build a dependency that 403s when the caller's roles don't grant ``perm``."""
    def _dep(request: Request) -> None:
        from aughor.security.authz import get_principal
        principal = get_principal(request)
        if principal is None:
            return  # identity off / localhost — unchanged behaviour

        from aughor.licensing import Capability, has_capability
        if not has_capability(Capability.RBAC_SSO):
            return  # RBAC is an enterprise capability; not enforced without it

        from aughor.rbac.resolver import has_permission, maybe_bootstrap_owner
        maybe_bootstrap_owner(principal)  # the org's first identified user becomes owner
        if not has_permission(principal, perm):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "permission_denied",
                    "permission": perm.value,
                    "hint": f"your role does not grant '{perm.value}'.",
                },
            )
    return _dep


def gate_permission(perm: Permission) -> Depends:
    """Sugar for route decorators: ``dependencies=[gate_permission(Permission.X)]``."""
    return Depends(require_permission(perm))
