"""Role-aware capability resolution (RBAC P2).

Two orthogonal axes decide what a caller can do with a *feature*:

  * the **tier** (``licensing``) — what the org's PLAN unlocks, and
  * the caller's **role** (this package) — a *ceiling* on which of those unlocked
    capabilities the role may actually exercise.

The effective capability set is their intersection: ``tier_caps ∩ role_ceiling``.
So on an enterprise plan a *viewer* still only sees the read/consume features, while
an *owner* sees everything the plan grants. This is surfaced through
``GET /capabilities`` (which the frontend reads to show/lock/upsell UI), so the UI
reflects the caller's role — not just the org's plan.

Layering: ``rbac`` depends on ``licensing`` (never the reverse), so the tier gate
(``require_capability`` → 402) stays plan-only; role restriction lives here and is
applied at the capability-*resolution* seam. Enforcement of the endpoint surface by
role is the RBAC policy table's job (``policy.py`` → 403).

The ceilings are defined by EXCLUSION so a newly-added capability has a safe default:
it flows to analyst + owner automatically, and is withheld from viewer unless
explicitly listed — a new feature is never silently exposed to read-only users.
"""
from __future__ import annotations

from typing import Optional

from aughor.licensing.capabilities import Capability, capabilities_for
from aughor.licensing.resolver import resolve_tier
from aughor.rbac.roles import ANALYST, OWNER, VIEWER
from aughor.rbac.resolver import resolve_roles
from aughor.security.authz import Principal

_ALL_CAPS: frozenset[Capability] = frozenset(Capability)

# Governance / audit capabilities only an owner may exercise (withheld from analyst).
_OWNER_ONLY_CAPS: frozenset[Capability] = frozenset({
    Capability.SECURITY_SUITE,
    Capability.RBAC_SSO,
    Capability.AUDIT_EXPORT,
    Capability.EVAL_SUITE,
})

# The read/consume capabilities a viewer may exercise (explicit allowlist).
_VIEWER_CAPS: frozenset[Capability] = frozenset({
    Capability.CONNECT,
    Capability.SCHEMA_PROFILE,
    Capability.CATALOG,
    Capability.ONTOLOGY_VIEW,
    Capability.BRIEFING_SAMPLE,
    Capability.BRIEFING_LIVE,
    Capability.INTELLIGENCE_HUB,
    Capability.DOMAIN_INTEL,
    Capability.EVIDENCE_LEDGER,
})


def role_ceiling(role_name: str) -> frozenset[Capability]:
    """The capabilities a single role may exercise (before intersecting with the tier).

    owner → all · analyst → all minus governance/audit · viewer → the read set ·
    unknown role → empty (fail-closed)."""
    name = (role_name or "").strip().lower()
    if name == OWNER:
        return _ALL_CAPS
    if name == ANALYST:
        return _ALL_CAPS - _OWNER_ONLY_CAPS
    if name == VIEWER:
        return _VIEWER_CAPS
    return frozenset()


def ceiling_for_roles(role_names) -> frozenset[Capability]:
    """The union of the ceilings of every role a caller holds."""
    ceiling: set[Capability] = set()
    for name in role_names:
        ceiling |= role_ceiling(name)
    return frozenset(ceiling)


def effective_capabilities(
    principal: Optional[Principal],
    conn_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> frozenset[Capability]:
    """The capabilities a caller can actually exercise: ``tier_caps ∩ role_ceiling``.

    No-op (returns the full tier set) when identity is off (``principal is None``) or
    the tier doesn't include ``RBAC_SSO`` — so localhost and non-RBAC plans are
    unchanged, and the role ceiling only bites where RBAC is actually active.
    """
    tier_caps = frozenset(capabilities_for(resolve_tier(conn_id, workspace_id)))
    if principal is None:
        return tier_caps
    if Capability.RBAC_SSO not in tier_caps:
        return tier_caps
    return tier_caps & ceiling_for_roles(resolve_roles(principal))


def role_has_capability(
    principal: Optional[Principal],
    cap: Capability,
    conn_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> bool:
    """True when the caller's tier AND role both grant ``cap``."""
    return cap in effective_capabilities(principal, conn_id, workspace_id)
