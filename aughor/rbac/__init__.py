"""Role-based access control (RBAC P1).

The second authorization axis, orthogonal to licensing capabilities: a licensing
capability says what the org's *plan* unlocks; an RBAC permission says what *this
user* may do. A request is authorized when both hold.

**Enforcement is live** (P4): ``policy.py`` maps every ``(method, route)`` to the
permission it requires, and ``deps.enforce_rbac`` is an app-wide dependency wired at
``aughor/api.py``. It stays a no-op in two situations by design — identity off /
localhost (the caller resolves to owner) and an org tier without
``Capability.RBAC_SSO`` — so a deployment that has not opted into RBAC is unaffected.

This docstring said the opposite until 2026-07-28, describing a P1 in which "no
enforcement is wired into any route yet". It had been wrong since P3 landed, and the
cost was not cosmetic: the Wave G program was scoped around "clearances **before**
roles, roles come later" on the strength of it. Prose drifts; the route table and
``api.py`` are the authority.

Wave G2 adds a THIRD axis beside these two — ``aughor/govern/tags.py`` — for what the
*data* requires of whoever reads it, which neither a plan nor a role can express.
"""
from __future__ import annotations

from aughor.rbac.capabilities import (
    ceiling_for_roles,
    effective_capabilities,
    role_ceiling,
    role_has_capability,
)
from aughor.rbac.deps import enforce_rbac, gate_permission, require_permission
from aughor.rbac.permissions import ALL_PERMISSIONS, Permission
from aughor.rbac.policy import required_permission
from aughor.rbac.resolver import (
    default_role,
    has_permission,
    maybe_bootstrap_owner,
    permissions_for,
    resolve_roles,
)
from aughor.rbac.roles import (
    ANALYST,
    BUILTIN_ROLES,
    OWNER,
    VIEWER,
    Role,
    get_role,
    is_builtin_role,
    role_permissions,
)

__all__ = [
    "Permission",
    "ALL_PERMISSIONS",
    "Role",
    "BUILTIN_ROLES",
    "OWNER",
    "ANALYST",
    "VIEWER",
    "get_role",
    "is_builtin_role",
    "role_permissions",
    "resolve_roles",
    "permissions_for",
    "has_permission",
    "maybe_bootstrap_owner",
    "default_role",
    "require_permission",
    "gate_permission",
    "enforce_rbac",
    "required_permission",
    "effective_capabilities",
    "role_has_capability",
    "role_ceiling",
    "ceiling_for_roles",
]
