"""RBAC persistence models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleAssignment:
    """A user holding a role within an org. The store's unit of record.

    ``(org_id, user_id, role)`` is unique — a user can hold several roles, and the
    same role in two orgs is two distinct assignments (org-scoping, DATA-06).
    """
    org_id: str
    user_id: str
    role: str
    created_at: str
    updated_at: str
