"""Graduated per-action approval + audit (P4, AI-FDE Pillar B).

AI FDE's governance is a runtime autonomy dial, not a license tier: read-only
actions run automatically, low-risk actions run on a safe scope, and high-risk
mutations require explicit approval — and every action is written to the audit
ledger attributed to the tenant, exactly as a manual action would be. This module
is that gate for Aughor's mutating endpoints:

- ``classify`` maps an action to a risk (an unregistered mutation is HIGH by
  default — fail-safe, so a new destructive endpoint is gated until someone lowers
  it deliberately).
- an **allowlist** (ledger KV, scoped by org+action+scope) lets the user pre-approve
  a tool for a connection — AI FDE's "approve for the session, scoped to a project".
- ``audit`` records every decision to the ledger (``action.approval`` events).
- ``guard`` enforces it: a high-risk action that isn't allowlisted is blocked with a
  428 the client turns into an approval prompt; everything else proceeds and is audited.

Opt-in via ``AUGHOR_ACTION_APPROVAL``. When off, ``guard`` is a no-op so existing
flows are byte-for-byte unchanged.
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Optional

from fastapi import HTTPException

from aughor.kernel.ledger import Ledger
from aughor.org.context import current_org_id
from aughor.util.time import now_iso as _now

_ALLOW_STORE = "action_allowlist"
_AUDIT_KIND = "action.approval"


class ActionRisk(str, Enum):
    READ_ONLY = "read_only"   # never gated; auto + audited
    LOW = "low"               # reversible / additive; auto + audited
    HIGH = "high"             # destructive or governance-changing; approval required


# Known mutating actions and their risk. Unregistered → HIGH (fail-safe).
_RISK: dict[str, ActionRisk] = {
    # Destructive — take data / whole intelligence footprint with them
    "connection.delete": ActionRisk.HIGH,
    "connection.schema.delete": ActionRisk.HIGH,
    "connection.table.delete": ActionRisk.HIGH,
    # Semantic-layer / governance changes
    "ontology.override": ActionRisk.HIGH,
    "ontology.delete_override": ActionRisk.HIGH,
    "ontology.import": ActionRisk.HIGH,
    "metric.approve": ActionRisk.HIGH,
    # Reversible / additive
    "skill.save": ActionRisk.LOW,
    "metric.define": ActionRisk.LOW,
    "metric.propose": ActionRisk.LOW,
    "pack.bind": ActionRisk.LOW,
}


def classify(action: str) -> ActionRisk:
    return _RISK.get(action, ActionRisk.HIGH)


def approval_enabled() -> bool:
    return os.getenv("AUGHOR_ACTION_APPROVAL", "").strip().lower() in ("1", "true", "yes", "on")


def _key(action: str, scope: str) -> str:
    # Org-scoped so the allowlist is per-tenant, matching the rest of the platform.
    return f"{current_org_id()}:{action}:{scope or '*'}"


def is_allowed(action: str, scope: str = "") -> bool:
    rec = Ledger.default().kv_get(_ALLOW_STORE, _key(action, scope), None)
    return bool(rec and (rec.get("allowed") if isinstance(rec, dict) else rec))


def allow(action: str, scope: str = "", *, actor: str = "") -> dict:
    """Add a per-scope allowlist entry so future high-risk `action`s on `scope` proceed."""
    rec = {"allowed": True, "action": action, "scope": scope or "*",
           "by": actor or current_org_id(), "at": _now()}
    Ledger.default().kv_put(_ALLOW_STORE, _key(action, scope), rec)
    audit(action, scope, "allowlisted", actor=actor)
    return rec


def revoke(action: str, scope: str = "") -> bool:
    ok = Ledger.default().kv_delete(_ALLOW_STORE, _key(action, scope))
    if ok:
        audit(action, scope, "revoked")
    return ok


def list_allowlist() -> list[dict]:
    org = current_org_id()
    raw = Ledger.default().kv_load_all(_ALLOW_STORE) or {}
    out = []
    for k, v in raw.items():
        if k.startswith(f"{org}:") and isinstance(v, dict):
            out.append(v)
    return out


def audit(action: str, scope: str, decision: str, *, actor: str = "", detail: str = "",
          risk: Optional[ActionRisk] = None) -> None:
    """Record one action decision to the audit ledger (attributed to the tenant).

    ``risk`` overrides the static ``classify`` lookup — needed for DYNAMIC actions (Wave K
    declared actions) whose risk is carried on the action itself, not in the static registry.
    Existing callers pass nothing and keep classifying as before."""
    Ledger.default().emit(_AUDIT_KIND, {
        "action": action, "risk": (risk or classify(action)).value, "decision": decision,
        "scope": scope or "", "actor": actor or current_org_id(),
        "org_id": current_org_id(), "detail": detail,
    }, conn_id=(scope or None))


def recent_audit(limit: int = 100) -> list[dict]:
    """Recent action-approval audit events for the current org, newest-first."""
    org = current_org_id()
    evs = Ledger.default().events(kind=_AUDIT_KIND, limit=max(1, min(int(limit) * 3, 2000)))
    out = []
    for e in evs:
        p = e.get("payload") or {}
        if p.get("org_id") == org:
            out.append({"seq": e.get("seq"), "at": e.get("at"), **p})
        if len(out) >= limit:
            break
    return out


def guard(action: str, scope: str = "", *, actor: str = "", risk: Optional[ActionRisk] = None) -> None:
    """Enforce the gate for a mutating action, then return (so the caller proceeds).

    No-op when approval is disabled. Otherwise: a HIGH-risk action that is not
    allowlisted for this scope is audited as ``blocked`` and raises HTTP 428
    ``approval_required``; every other case is audited (``auto`` / ``approved``)
    and allowed through.

    ``risk`` overrides the static ``classify`` lookup for DYNAMIC actions (Wave K declared
    actions carry their own risk tier). Omitted for the static endpoints, which classify as
    before — so this is byte-for-byte unchanged for the three existing call sites."""
    if not approval_enabled():
        return
    risk = risk or classify(action)
    if risk == ActionRisk.HIGH and not is_allowed(action, scope):
        audit(action, scope, "blocked", actor=actor, risk=risk)
        raise HTTPException(status_code=428, detail={
            "error": "approval_required",
            "action": action,
            "scope": scope,
            "risk": risk.value,
            "hint": (f"High-risk action '{action}' requires approval. "
                     f"POST /approvals/allow with this action + scope to approve it, then retry."),
        })
    audit(action, scope, "approved" if risk == ActionRisk.HIGH else "auto", actor=actor, risk=risk)
