"""Role-based access control (RBAC P1).

The second authorization axis, orthogonal to licensing capabilities: a licensing
capability says what the org's *plan* unlocks; an RBAC permission says what *this
user* may do. A request is authorized when both hold.

P1 (this package) ships the model + org-scoped assignment store + the pure
resolver seam — no enforcement is wired into any route yet. See the module
docstrings for the phased plan (P2 role→capability, P3 enforcement + admin roster
behind ``Capability.RBAC_SSO``).
"""
from __future__ import annotations

from aughor.rbac.permissions import ALL_PERMISSIONS, Permission
from aughor.rbac.resolver import (
    default_role,
    has_permission,
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
    "default_role",
]
