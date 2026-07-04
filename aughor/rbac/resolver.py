"""Resolve a principal → roles → permissions (RBAC P1).

This is the seam every later phase consumes:

  - **P2** replaces the flat licensing ``resolve_tier`` decision with a role-aware
    one (a role can gate a capability).
  - **P3** wires ``has_permission`` into route dependencies (behind
    ``Capability.RBAC_SSO``) and adds the admin roster endpoints.

P1 delivers only the pure resolution — no route touches it yet, so blast radius is
zero. Two fallbacks preserve today's behaviour and keep an identity-on deployment
usable:

  - **localhost / identity-off** (``principal is None``) → the **owner** role, i.e.
    every permission. So ``has_permission`` is always True and behaviour is
    byte-identical to before RBAC existed.
  - **an identified user with no explicit assignment** → the configured default role
    (``AUGHOR_RBAC_DEFAULT_ROLE``, default **viewer** = least privilege), so flipping
    identity on never silently grants a stranger more than read.

A store error resolves to the default role too (fail-closed to least privilege),
never to owner — an outage must not escalate.
"""
from __future__ import annotations

import os
from typing import List, Optional

from aughor.rbac.permissions import Permission
from aughor.rbac.roles import OWNER, VIEWER, get_role, role_permissions
from aughor.security.authz import Principal


def default_role() -> str:
    """The role an identified-but-unassigned user gets. Least privilege by default;
    an unknown configured value falls back to viewer (never silently to owner)."""
    name = (os.getenv("AUGHOR_RBAC_DEFAULT_ROLE", VIEWER) or VIEWER).strip().lower()
    return name if get_role(name) else VIEWER


def resolve_roles(principal: Optional[Principal]) -> List[str]:
    """The role names in effect for a principal.

    ``None`` (identity off / localhost) → ``[owner]`` (full access, unchanged
    behaviour). An identified user gets their assigned roles, or the default role
    when they have none. Fail-closed to the default role on a store error.
    """
    if principal is None:
        return [OWNER]
    try:
        from aughor.rbac.store import roles_for_user
        roles = roles_for_user(principal.org_id, principal.user_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "RBAC role lookup failed — falling back to the default role "
                      "(least privilege, never owner)", counter="rbac.role_lookup")
        return [default_role()]
    return roles if roles else [default_role()]


def permissions_for(principal: Optional[Principal]) -> frozenset[Permission]:
    """The union of permissions granted by a principal's effective roles."""
    perms: set[Permission] = set()
    for name in resolve_roles(principal):
        perms |= role_permissions(name)
    return frozenset(perms)


def has_permission(principal: Optional[Principal], perm: Permission) -> bool:
    """True when the principal's roles grant ``perm``. The check P3 enforces."""
    return perm in permissions_for(principal)
