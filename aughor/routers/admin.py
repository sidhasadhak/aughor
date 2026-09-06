"""Admin — the cross-user view (VA-10's second half, buildable once identity landed).

§3.5's table called this row "genuinely missing — no admin routes exist", and §6.4's
decided asymmetry IS the design here: counts, costs, error rates and role assignments
are admin-visible without ceremony, because metadata answers "is this deployment
healthy". Reading a prompt or a response body stays a BREAK-GLASS behind the existing
audited doors (the prompt-capture window, ``trace.payload_access``) — this router
deliberately adds no payload read of any kind.

Authorization rides the declarative table in ``aughor/rbac/policy.py`` like the rest
of the governance surface. Attribution honesty rides the usage report's own contract:
``user_id`` coverage is served beside the rows, so a deployment where identity is off
reads as "0% attributed", never as one busy user named "".
"""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["admin"])


@router.get("/admin/users")
def list_users(scan: int = Query(default=5000, ge=1, le=100_000)):
    """Every user this org's ledger or role table knows, with their usage.

    The union matters: a user with a role and no calls yet is real (they were
    granted something), and a user with calls and no role is real (the ledger saw
    them) — a view built from either side alone would silently drop the other.
    """
    from aughor.obs.usage import usage_report
    from aughor.org.context import current_org_id
    from aughor.rbac.store import list_assignments
    from aughor.security import oidc
    from aughor.security.authz import require_identity_enabled

    org = current_org_id() or "default"
    report = usage_report(axes=("user_id",), scan=scan)

    users: dict[str, dict] = {}
    for row in report.rows:
        d = row.to_dict()
        uid = str(d.pop("user_id", "") or "")
        if not uid:
            continue  # counted in unattributed below, never shown as a blank cohort
        users[uid] = {"user_id": uid, "roles": [], **d}

    for assignment in list_assignments(org):
        entry = users.setdefault(
            assignment.user_id,
            {"user_id": assignment.user_id, "roles": [], "calls": 0, "failures": 0,
             "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "calls_without_usage": 0, "unpriced_calls": 0, "cost_usd": 0.0,
             "cost_is_complete": True, "mean_ms": 0.0, "failure_rate": 0.0})
        entry["roles"].append(assignment.role)

    unattributed = report.unattributed.get("user_id", 0)
    return {
        "org_id": org,
        "users": sorted(users.values(), key=lambda u: (-u["calls"], u["user_id"])),
        "total_calls": report.total_calls,
        "unattributed_calls": unattributed,
        "coverage": (round(1 - unattributed / report.total_calls, 3)
                     if report.total_calls else 0.0),
        # Why attribution might be empty, stated rather than inferred by the reader.
        "identity_required": require_identity_enabled(),
        "oidc_configured": oidc.configured(),
    }
