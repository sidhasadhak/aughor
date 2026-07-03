"""Request identity + object-level authorization (SEC-01 / SEC-05 / DATA-06).

Aughor grew up as a trusted-localhost tool: the only front door is an optional
shared API key, ``current_org_id()`` is never set per-request, and by-id
endpoints do no ownership check — any caller who knows a UUID can read/export/
delete any investigation or canvas.

This module adds the *seam* for real multi-tenant authorization, gated behind
``AUGHOR_REQUIRE_IDENTITY`` (default OFF → today's single-user behaviour is
byte-identical). It is deliberately NOT full RBAC — just:

  1. a ``Principal`` (who + which org),
  2. per-request identity → ``set_org_id(principal.org)`` binding (done in
     ``api._require_auth``), so the tenant key finally rides the request path,
  3. ``authorize_resource`` / ``check_owner`` ownership checks, resolved through
     resource → connection → ``connections.org_id``.

SEAM NOTE — where a real deployment plugs in identity: ``resolve_principal``
takes the org from the ``X-Aughor-Org`` request header. That is the transitional
self-host form; a production deployment MUST derive the org from an
*authenticated* identity (JWT / OIDC / mTLS) so the caller cannot simply claim an
org. Replace ``resolve_principal`` — every other piece (contextvar binding,
owner-checks) stays unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

IDENTITY_ORG_HEADER = "X-Aughor-Org"
IDENTITY_USER_HEADER = "X-Aughor-User"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller for a request: who they are and their tenant."""
    user_id: str
    org_id: str


def require_identity_enabled() -> bool:
    """Whether per-request identity is enforced. OFF by default (localhost mode).

    Read from the environment (not the runtime flag store) on purpose: an auth
    switch should require an explicit restart to flip, not a runtime toggle API.
    """
    return os.environ.get("AUGHOR_REQUIRE_IDENTITY", "") == "1"


def resolve_principal(request: Request) -> Optional[Principal]:
    """Resolve the calling principal from the request, or None if no identity is
    presented. SEAM: org comes from the ``X-Aughor-Org`` header today — swap this
    for authenticated-token extraction in production (see module docstring)."""
    org = (request.headers.get(IDENTITY_ORG_HEADER) or "").strip()
    if not org:
        return None
    user = (request.headers.get(IDENTITY_USER_HEADER) or "anonymous").strip()
    return Principal(user_id=user, org_id=org)


def get_principal(request: Request) -> Optional[Principal]:
    """FastAPI dependency: the principal bound to this request by ``_require_auth``
    (None in localhost / identity-off mode)."""
    return getattr(request.state, "principal", None)


# ── Ownership resolution: resource → connection → org ────────────────────────────

def _resource_org(kind: str, resource_id: str) -> Optional[str]:
    """The org that owns a resource, or None when it can't be determined (missing
    resource, or a shared builtin connection)."""
    from aughor.db.registry import get_connection_org
    if kind == "connection":
        return get_connection_org(resource_id)
    if kind == "canvas":
        from aughor.canvas.store import resolve_connection_id
        conn_id = resolve_connection_id(resource_id)
        return get_connection_org(conn_id) if conn_id else None
    if kind == "investigation":
        from aughor.db.history import get_investigation
        inv = get_investigation(resource_id)
        conn_id = (inv or {}).get("connection_id")
        return get_connection_org(conn_id) if conn_id else None
    return None


def authorize_resource(kind: str, resource_id: Optional[str], principal: Optional[Principal]) -> bool:
    """True if ``principal`` may act on the resource.

    No-op (True) in localhost mode: ``principal is None`` means identity isn't
    being enforced. A resource whose org can't be resolved (missing, or a shared
    builtin) is allowed here — the handler's own 404 covers a missing id, and we
    don't want to 403 the shared builtins.
    """
    if principal is None:
        return True
    owner_org = _resource_org(kind, resource_id) if resource_id else None
    if owner_org is None:
        return True
    return owner_org == principal.org_id


def check_owner(kind: str, resource_id: Optional[str], principal: Optional[Principal]) -> None:
    """Raise 403 when ``principal`` doesn't own the resource; no-op in localhost mode."""
    if not authorize_resource(kind, resource_id, principal):
        raise HTTPException(status_code=403, detail=f"forbidden: {kind} belongs to another org")
