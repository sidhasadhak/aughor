"""The served auth config — what a browser needs to START authenticating (VA-10).

One route, deliberately public (it joins ``_AUTH_EXEMPT`` in ``api.py``): a client that
does not yet hold a token has to be able to learn HOW to get one, or requiring identity
would brick every UI. It serves only what is public by nature — the issuer and the
OAuth client id (the audience) — never a secret; verification uses none.

Served, never mirrored: the frontend renders its sign-in from this payload, so the
client id lives in exactly one place (``AUGHOR_OIDC_AUDIENCE``) and a rotated client
needs no frontend change.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["auth"])

_GOOGLE_ISSUER = "https://accounts.google.com"


@router.get("/auth/config")
def auth_config():
    """How this deployment authenticates. ``provider`` is a RENDERING hint — the
    verification path is issuer-generic; only the sign-in widget is provider-shaped,
    and today the one widget shipped is Google Identity Services."""
    from aughor.security import oidc
    from aughor.security.authz import require_identity_enabled

    if not oidc.configured():
        return {"oidc_configured": False,
                "identity_required": require_identity_enabled()}
    issuer = oidc.issuer()
    return {
        "oidc_configured": True,
        "identity_required": require_identity_enabled(),
        "issuer": issuer,
        "client_id": oidc.audience(),
        "provider": "google" if issuer == _GOOGLE_ISSUER else "generic",
    }
