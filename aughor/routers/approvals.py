"""Approval + audit endpoints (P4, AI-FDE Pillar B).

The user-facing surface for the action gate: approve (allowlist) a high-risk action
for a scope, revoke it, list the allowlist, and read the audit trail. A high-risk
mutation blocked by :func:`aughor.govern.guard` returns 428; the client approves
here and retries.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from aughor import govern

router = APIRouter(tags=["approvals"])


class AllowRequest(BaseModel):
    action: str
    scope: str = ""


@router.post("/approvals/allow")
def approve_action(req: AllowRequest):
    """Allowlist a high-risk action for a scope so future attempts proceed."""
    rec = govern.allow(req.action, req.scope)
    return {"allowed": True, "entry": rec, "risk": govern.classify(req.action).value}


@router.post("/approvals/revoke")
def revoke_action(req: AllowRequest):
    """Remove an allowlist entry — the action is gated again."""
    return {"revoked": govern.revoke(req.action, req.scope)}


@router.get("/approvals/allowlist")
def get_allowlist():
    """Current per-scope allowlist entries for this org."""
    return govern.list_allowlist()


@router.get("/approvals/audit")
def get_audit(limit: int = 100):
    """Recent action-approval audit events (newest-first) for this org — the trail an
    enterprise review reads to confirm every high-risk mutation was gated + attributed."""
    return govern.recent_audit(limit)
