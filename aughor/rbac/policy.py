"""Declarative RBAC policy — the single, auditable map from endpoint → the
permission it requires (RBAC P4).

Rather than scatter ``gate_permission(...)`` across 150+ route decorators (which no
one can audit as a whole), the entire surface's authorization lives here as one
table, consulted per-request by the global ``deps.enforce_rbac`` dependency. This is
the "governance as an auditable primitive" the architecture review asked for.

The default is a least-astonishment floor:

  * **safe methods** (GET/HEAD/OPTIONS) require nothing beyond identity — a *viewer*
    reads everything.
  * **mutating methods** (POST/PUT/PATCH/DELETE) require ``resource.write`` — so a
    viewer can change nothing, *anywhere*, without every route having to opt in.

``POLICY`` then RAISES the bar for the endpoints that need a more specific
permission (admin/governance, connection lifecycle, analysis runs, exports), and can
LOWER it (a mutating endpoint that should stay open maps to ``None``). Keys are
``(METHOD, route-template)`` where the template is the FastAPI path with its params,
e.g. ``/connections/{conn_id}`` — matched exactly against the request's resolved
route, so there are no path-prefix collisions.
"""
from __future__ import annotations

from typing import Optional

from aughor.rbac.permissions import Permission as P

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_WRITE: P = P.RESOURCE_WRITE

# (METHOD, route-template) -> required Permission (or None to force-open a mutation).
POLICY: dict[tuple[str, str], Optional[P]] = {
    # ── Admin / governance (owner-only) ──
    ("GET", "/rbac/assignments"): P.ADMIN_MANAGE_ROLES,
    ("POST", "/rbac/assignments"): P.ADMIN_MANAGE_ROLES,
    ("DELETE", "/rbac/assignments"): P.ADMIN_MANAGE_ROLES,
    ("PUT", "/org-settings"): P.ADMIN_MANAGE_ORG,
    ("PATCH", "/agents/{agent_id}"): P.ADMIN_MANAGE_ORG,
    ("PUT", "/system/flags/{name}"): P.ADMIN_MANAGE_ORG,
    ("POST", "/metastore/workspaces/{workspace_id}/grants"): P.ADMIN_MANAGE_ORG,
    ("DELETE", "/metastore/workspaces/{workspace_id}/grants/{catalog_id}"): P.ADMIN_MANAGE_ORG,
    ("POST", "/llm/config"): P.ADMIN_MANAGE_BILLING,

    # ── Connection lifecycle ──
    ("POST", "/connections"): P.CONNECTION_CREATE,
    ("DELETE", "/connections/{conn_id}"): P.CONNECTION_DELETE,

    # ── Analysis runs (a viewer consumes existing answers; it doesn't run new ones) ──
    ("POST", "/chat"): P.ANALYSIS_RUN,
    ("POST", "/ask"): P.ANALYSIS_RUN,
    ("POST", "/investigate"): P.ANALYSIS_RUN,

    # ── Resource delete / export (more specific than the write floor) ──
    ("DELETE", "/investigations"): P.RESOURCE_DELETE,
    ("DELETE", "/investigations/{inv_id}"): P.RESOURCE_DELETE,
    ("GET", "/investigations/{inv_id}/export"): P.RESOURCE_EXPORT,
}


def required_permission(method: str, template: str) -> Optional[P]:
    """The permission an endpoint requires, or ``None`` when it's open to any
    identified caller (all reads, plus any mutation explicitly force-opened).

    An explicit ``POLICY`` entry always wins (including a ``None`` that opens a
    mutation); otherwise safe methods are open and every other method falls to the
    ``resource.write`` floor.
    """
    method = (method or "").upper()
    key = (method, template)
    if key in POLICY:
        return POLICY[key]
    if method in SAFE_METHODS:
        return None
    return DEFAULT_WRITE
