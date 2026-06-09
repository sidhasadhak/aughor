"""Capability catalogue + the additive tier → capabilities map.

Tiers are additive: Pro = Free + Pro caps, Enterprise = Pro + Enterprise caps. Adding a
new feature means adding a `Capability` and placing it in exactly one tier set.
"""
from __future__ import annotations

from enum import Enum


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Capability(str, Enum):
    # ── Free — connect, understand the data, a taste of intelligence ──
    CONNECT             = "connect"
    SCHEMA_PROFILE      = "schema.profile"
    CATALOG             = "catalog"
    NL2SQL_CHAT         = "nl2sql.chat"
    QUERY_BUILDER       = "query.builder"
    ONTOLOGY_VIEW       = "ontology.view"
    BRIEFING_SAMPLE     = "briefing.sample"
    # ── Pro — the autonomous intelligence + actionability ──
    DEEP_ANALYSIS       = "analysis.deep"
    AUTO_EXPLORATION    = "exploration.auto"
    DOMAIN_INTEL        = "intel.domain"
    BRIEFING_LIVE       = "briefing.live"
    INTELLIGENCE_HUB    = "intel.hub"
    EVIDENCE_LEDGER     = "evidence.ledger"
    MONITORS            = "monitors"
    SCHEDULED_BRIEFS    = "briefs.scheduled"
    ACTION_HUB          = "actions.hub"
    METRICS_DEFINE      = "metrics.define"
    PLAYBOOK            = "playbook"
    SEMANTIC_EDIT       = "semantic.edit"
    ONTOLOGY_EDIT       = "ontology.edit"
    CANVAS_MULTI        = "canvas.multi"
    TEMPORAL_TIER12     = "temporal.tier12"
    FEDERATION          = "federation"
    FIX_SAVE            = "fix.save"          # save a repaired Activity query as a finding
    # ── Enterprise — scale, governance, trust, determinism ──
    TEMPORAL_TIER3      = "temporal.tier3"    # query cost governor
    SEMANTIC_COMPILER   = "semantic.compiler"  # deterministic SQL
    SECURITY_SUITE      = "security.suite"    # audit / PII / budgets / sandbox
    EVAL_SUITE          = "eval.suite"
    RBAC_SSO            = "rbac.sso"
    AUDIT_EXPORT        = "audit.export"
    QUERY_CANCEL        = "query.cancel"


_FREE: set[Capability] = {
    Capability.CONNECT, Capability.SCHEMA_PROFILE, Capability.CATALOG,
    Capability.NL2SQL_CHAT, Capability.QUERY_BUILDER, Capability.ONTOLOGY_VIEW,
    Capability.BRIEFING_SAMPLE,
}

_PRO: set[Capability] = _FREE | {
    Capability.DEEP_ANALYSIS, Capability.AUTO_EXPLORATION, Capability.DOMAIN_INTEL,
    Capability.BRIEFING_LIVE, Capability.INTELLIGENCE_HUB, Capability.EVIDENCE_LEDGER,
    Capability.MONITORS, Capability.SCHEDULED_BRIEFS, Capability.ACTION_HUB,
    Capability.METRICS_DEFINE, Capability.PLAYBOOK, Capability.SEMANTIC_EDIT,
    Capability.ONTOLOGY_EDIT, Capability.CANVAS_MULTI, Capability.TEMPORAL_TIER12,
    Capability.FEDERATION, Capability.FIX_SAVE,
}

_ENTERPRISE: set[Capability] = _PRO | {
    Capability.TEMPORAL_TIER3, Capability.SEMANTIC_COMPILER, Capability.SECURITY_SUITE,
    Capability.EVAL_SUITE, Capability.RBAC_SSO, Capability.AUDIT_EXPORT,
    Capability.QUERY_CANCEL,
}

TIER_CAPABILITIES: dict[Tier, set[Capability]] = {
    Tier.FREE: _FREE,
    Tier.PRO: _PRO,
    Tier.ENTERPRISE: _ENTERPRISE,
}


def capabilities_for(tier: Tier) -> set[Capability]:
    """The full capability set granted by a tier (additive)."""
    return TIER_CAPABILITIES.get(tier, _ENTERPRISE)
