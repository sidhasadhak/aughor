"""FastAPI dependency to gate a route behind an RBAC permission (P3 enforcement).

Mirrors ``licensing/deps.require_capability`` but on the *user* axis: it returns
**HTTP 403 Forbidden** (distinct from 402 capability-locked / 401 unauthenticated)
when the caller's roles don't grant the permission.

Usage (opt-in, per route — no handler-body change):

    from aughor.rbac import Permission
    from aughor.rbac.deps import gate_permission

    @router.delete("/connections/{conn_id}",
                   dependencies=[gate_permission(Permission.CONNECTION_DELETE)])
    def remove_connection(...): ...

One condition makes the gate a NO-OP, so adding it is safe everywhere:

  **identity off / localhost** — no principal is bound, the resolver treats the
  caller as owner, so every permission is granted (byte-identical to today).

There was a second — the org's tier lacking ``Capability.RBAC_SSO`` — and it went on
2026-11-05 (the 10× program, Track A3): whether a permission is EVALUATED is not a
thing a plan may switch off. The tier is an unsigned environment variable that defaults
to enterprise, so the skip was latent; had anyone set a lower tier, every identified
caller would have passed every gate. A capability may still gate an administration
SURFACE (SCIM, a roster); it never gates the decision itself.

With a principal bound, the gate resolves the caller's roles (bootstrapping the org's
first user as owner) and 403s a caller whose roles don't grant ``perm``.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from aughor.rbac.permissions import Permission


def require_permission(perm: Permission):
    """Build a dependency that 403s when the caller's roles don't grant ``perm``."""
    def _dep(request: Request) -> None:
        from aughor.security.authz import get_principal
        principal = get_principal(request)
        if principal is None:
            return  # identity off / localhost — unchanged behaviour

        from aughor.rbac.resolver import has_permission, maybe_bootstrap_owner
        maybe_bootstrap_owner(principal)  # the org's first identified user becomes owner
        if not has_permission(principal, perm):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "permission_denied",
                    "permission": perm.value,
                    "hint": f"your role does not grant '{perm.value}'.",
                },
            )
    return _dep


def gate_permission(perm: Permission) -> Depends:
    """Sugar for a one-off route gate: ``dependencies=[gate_permission(Permission.X)]``.

    For the standard surface, enforcement is centralized in ``policy.py`` +
    ``enforce_rbac`` (below) — this remains for the occasional route that needs a
    bespoke gate outside the policy table."""
    return Depends(require_permission(perm))


# Never gated — health probes and the schema/docs browser must answer regardless.
_ENFORCE_EXEMPT = ("/health", "/docs", "/redoc", "/openapi.json")


def enforce_rbac(request: Request) -> None:
    """App-wide RBAC enforcement (the P4 broad gate).

    A global dependency that resolves the permission each endpoint requires from the
    declarative ``policy.py`` table and 403s a caller whose roles don't grant it. Like
    the per-route gate it is inert while identity is off, so localhost is unchanged;
    the tier plays no part (Track A3). The org's first identified caller is bootstrapped as owner.

    Self-contained (resolves its own principal) so it's order-independent w.r.t.
    ``api._require_auth``; when identity is required but absent, ``_require_auth``
    still issues the 401 and this simply no-ops.
    """
    path = request.url.path
    if any(path.startswith(p) for p in _ENFORCE_EXEMPT):
        return

    from aughor.security.authz import require_identity_enabled, resolve_principal
    if not require_identity_enabled():
        return
    principal = resolve_principal(request)
    if principal is None:
        return  # _require_auth issues the 401 for a missing identity

    from aughor.rbac.resolver import has_permission, maybe_bootstrap_owner
    maybe_bootstrap_owner(principal)  # first identified caller of the org → owner

    from aughor.rbac.policy import required_permission
    route = request.scope.get("route")
    template = getattr(route, "path", None) or path
    perm = required_permission(request.method, template)
    if perm is None:
        return
    if not has_permission(principal, perm):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "permission": perm.value,
                "hint": f"your role does not grant '{perm.value}'.",
            },
        )
