"""Roles — named bundles of permissions, and the built-in role catalogue.

A ``Role`` groups ``Permission``s. P1 ships three built-in, org-independent roles
(the classic least-privilege ladder); a deployment assigns them to users via the
org-scoped store (``store.py``). Custom per-org roles are a later phase — the model
here is deliberately closed for P1 (only the built-ins exist) so the permission
surface stays auditable.

The ladder (each a strict superset of the one below):

  - **viewer**  — read-only. See answers, investigations, canvases; nothing else.
  - **analyst** — the working data analyst: read + write + delete + export own work,
                  run analysis, and create/delete connections. No governance.
  - **owner**   — everything, including role administration and billing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aughor.rbac.permissions import ALL_PERMISSIONS, Permission

# ── Built-in role names (the assignment store stores these strings) ──
OWNER = "owner"
ANALYST = "analyst"
VIEWER = "viewer"


@dataclass(frozen=True)
class Role:
    """A named permission bundle. Frozen — the built-ins are immutable singletons."""
    name: str
    permissions: frozenset[Permission]
    description: str = ""

    def grants(self, perm: Permission) -> bool:
        return perm in self.permissions


_VIEWER_PERMS: frozenset[Permission] = frozenset({
    Permission.RESOURCE_READ,
})

# analyst = viewer + the full working-analyst action set (no governance verbs).
_ANALYST_PERMS: frozenset[Permission] = _VIEWER_PERMS | {
    Permission.RESOURCE_WRITE,
    Permission.RESOURCE_DELETE,
    Permission.RESOURCE_EXPORT,
    Permission.ANALYSIS_RUN,
    Permission.CONNECTION_CREATE,
    Permission.CONNECTION_DELETE,
}

# owner = every permission (the admin/governance verbs are owner-only).
_OWNER_PERMS: frozenset[Permission] = ALL_PERMISSIONS


BUILTIN_ROLES: dict[str, Role] = {
    VIEWER: Role(VIEWER, _VIEWER_PERMS, "Read-only access to answers and analyses."),
    ANALYST: Role(ANALYST, _ANALYST_PERMS, "Run analyses and manage connections and one's own work."),
    OWNER: Role(OWNER, _OWNER_PERMS, "Full control, including role administration and billing."),
}


def get_role(name: str) -> Optional[Role]:
    """The built-in role by name, or None for an unknown name."""
    return BUILTIN_ROLES.get((name or "").strip().lower())


def is_builtin_role(name: str) -> bool:
    return (name or "").strip().lower() in BUILTIN_ROLES


def role_permissions(name: str) -> frozenset[Permission]:
    """The permissions a role grants — empty for an unknown role (fail-closed)."""
    role = get_role(name)
    return role.permissions if role else frozenset()
