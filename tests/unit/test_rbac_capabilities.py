"""RBAC P2 — role-aware capability resolution (tier ∩ role ceiling)."""
from __future__ import annotations

from aughor.licensing.capabilities import Capability, capabilities_for
from aughor.licensing.capabilities import Tier
from aughor.rbac import (
    ANALYST,
    OWNER,
    VIEWER,
    ceiling_for_roles,
    effective_capabilities,
    role_ceiling,
    role_has_capability,
)
from aughor.security.authz import Principal


def test_owner_ceiling_is_everything():
    assert role_ceiling(OWNER) == frozenset(Capability)


def test_analyst_ceiling_excludes_governance():
    ceil = role_ceiling(ANALYST)
    assert Capability.SECURITY_SUITE not in ceil
    assert Capability.RBAC_SSO not in ceil
    assert Capability.AUDIT_EXPORT not in ceil
    # …but keeps the product/feature capabilities
    assert Capability.MONITORS in ceil
    assert Capability.DEEP_ANALYSIS in ceil
    assert Capability.METRICS_DEFINE in ceil


def test_viewer_ceiling_is_read_only():
    ceil = role_ceiling(VIEWER)
    assert Capability.CATALOG in ceil
    assert Capability.INTELLIGENCE_HUB in ceil
    assert Capability.MONITORS not in ceil          # can't create monitors
    assert Capability.METRICS_DEFINE not in ceil    # can't define metrics
    assert Capability.NL2SQL_CHAT not in ceil       # can't run chat


def test_unknown_role_ceiling_is_empty():
    assert role_ceiling("superuser") == frozenset()


def test_ceiling_union_across_roles():
    assert ceiling_for_roles([VIEWER, ANALYST]) == role_ceiling(ANALYST)


def test_effective_caps_localhost_is_the_full_tier():
    # principal None (identity off) → unchanged tier set
    assert effective_capabilities(None) == frozenset(capabilities_for(Tier.ENTERPRISE))


def test_effective_caps_intersect_tier_and_role(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "enterprise")  # RBAC_SSO present → ceiling applies
    p = Principal(user_id="v", org_id="caps-org-1")   # unassigned → default viewer
    caps = effective_capabilities(p)
    assert Capability.CATALOG in caps
    assert Capability.MONITORS not in caps            # tier grants it, role doesn't
    assert not role_has_capability(p, Capability.METRICS_DEFINE)
    assert role_has_capability(p, Capability.CATALOG)


def test_no_ceiling_when_tier_lacks_rbac_sso(monkeypatch):
    monkeypatch.setenv("AUGHOR_TIER", "free")         # free lacks RBAC_SSO → no role gate
    p = Principal(user_id="v", org_id="caps-org-2")    # would be a viewer under enterprise
    # the ceiling doesn't bite: the caller gets the full (free) tier set
    assert effective_capabilities(p) == frozenset(capabilities_for(Tier.FREE))
