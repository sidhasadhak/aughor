"""The permission taxonomy — the action verbs a role can grant.

RBAC P1 (the follow-on to REC-05's identity + owner-checks) introduces a *second*
authorization axis, orthogonal to licensing:

  - **licensing capability** (``aughor/licensing``) = what the *org's plan* unlocks.
  - **RBAC permission** (this module)              = what *this user* may do.

Wave G2 adds a third: a **clearance** (``aughor/govern/tags.py``) = what this *data*
requires of whoever reads it. All three compose with AND.

This module defines just the permission vocabulary; ``roles.py`` groups permissions
into roles and ``resolver.py`` resolves a principal → roles → permissions.
Enforcement is live and app-wide via ``policy.py`` + ``deps.enforce_rbac`` — this
paragraph claimed it was "deliberately NOT in P1, lands in P3" until 2026-07-28, long
after P3 and P4 had shipped.

Adding a permission means adding a member here and placing it in the built-in roles
that should grant it (``roles.py``). Keep the set small and coherent: these are
coarse *action* verbs, not per-endpoint flags.
"""
from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    # ── Object-level verbs (the actions the SEC-05 owner-checks already gate on) ──
    RESOURCE_READ    = "resource.read"      # view an investigation / canvas / answer
    RESOURCE_WRITE   = "resource.write"     # create / update a resource
    RESOURCE_DELETE  = "resource.delete"    # delete a resource
    RESOURCE_EXPORT  = "resource.export"    # export / download a resource

    # ── Connection lifecycle ──
    CONNECTION_CREATE = "connection.create"
    CONNECTION_DELETE = "connection.delete"

    # ── Analysis actions (the interactive + autonomous agent paths) ──
    ANALYSIS_RUN      = "analysis.run"      # run chat / deep analysis / exploration

    # ── Governance / administration ──
    ADMIN_MANAGE_ROLES   = "admin.manage_roles"    # assign / revoke roles in the org
    ADMIN_MANAGE_ORG     = "admin.manage_org"      # org settings, agent governance
    ADMIN_MANAGE_BILLING = "admin.manage_billing"  # plan / tier / billing


# The complete set — the OWNER role grants exactly this.
ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)
