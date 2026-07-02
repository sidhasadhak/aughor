"""Governance — graduated per-action approval + audit (AI-FDE Pillar B, P4).

The autonomy dial for Aughor's *mutating* operations: read-only actions run
automatically, low-risk ones run on a safe scope, high-risk mutations require
explicit approval — and every action, whichever way it resolves, is recorded to
the audit ledger attributed to the tenant. Opt-in via ``AUGHOR_ACTION_APPROVAL``.
"""
from aughor.govern.actions import (
    ActionRisk,
    approval_enabled,
    classify,
    guard,
    allow,
    revoke,
    is_allowed,
    list_allowlist,
    audit,
    recent_audit,
)

__all__ = [
    "ActionRisk", "approval_enabled", "classify", "guard",
    "allow", "revoke", "is_allowed", "list_allowlist", "audit", "recent_audit",
]
