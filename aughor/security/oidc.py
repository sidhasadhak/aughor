"""OIDC bearer verification — the production half of the identity seam (VA-10).

``security/authz.resolve_principal`` has carried its own warrant since SEC-01: *"a
production deployment MUST derive the org from an authenticated identity (JWT / OIDC /
mTLS) so the caller cannot simply claim an org."* This module is that derivation,
decided 2026-09-06 (§6 item 11, the user's call: OIDC).

**No IdP is hardcoded** — the same law as model ids. The issuer is configuration, and
everything provider-specific is read from the issuer's own discovery document
(``/.well-known/openid-configuration`` → ``jwks_uri``), so Google Workspace, Azure AD,
Okta, Auth0 and Keycloak are all the same deployment with different env values:

    AUGHOR_OIDC_ISSUER      the token issuer, e.g. https://accounts.google.com
    AUGHOR_OIDC_AUDIENCE    the client id tokens must be minted for (REQUIRED with
                            the issuer — verification without an audience check would
                            accept any token the IdP ever minted for anything)
    AUGHOR_OIDC_ORG_CLAIM   optional: a claim carrying the tenant. Unset → every
                            verified user lands in AUGHOR_OIDC_DEFAULT_ORG
                            (default "default") — the single-org deployment shape.

Laws:

- **Fail closed.** A malformed, expired, unsigned, wrong-audience or wrong-issuer
  token verifies as NOTHING — never as a downgraded identity. And while an issuer is
  configured, the transitional ``X-Aughor-*`` header seam stops resolving identity
  under ``AUGHOR_REQUIRE_IDENTITY`` — the spoofable path and the verified path must
  not coexist (the ``mallory`` demonstration of 2026-09-04 is the argument).
- **Config is read per call**, never at import — the third import-time-freeze
  (``vocabulary._ROOT``) bought this rule. The JWKS client cache is keyed by the
  issuer VALUE, so a changed env takes effect on the next request.
- **The user id is the stable subject**, ``sub``, with ``email`` preferred when the
  IdP provides it (analytics group by this string; an email reads, a sub does not).

Env reads ride ``os.environ`` directly like ``require_identity_enabled`` does, and for
the same stated reason: an auth switch should require a restart, not a runtime toggle.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from aughor.security.authz import Principal

_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384")

#: JWKS clients per issuer VALUE (not per env read) — a changed issuer gets a fresh
#: client, an unchanged one keeps its key cache across requests.
_JWKS_CLIENTS: dict[str, Any] = {}


class OidcError(Exception):
    """A bearer token this deployment must not accept, with the reason."""


def issuer() -> str:
    return (os.environ.get("AUGHOR_OIDC_ISSUER") or "").strip().rstrip("/")


def audience() -> str:
    return (os.environ.get("AUGHOR_OIDC_AUDIENCE") or "").strip()


def configured() -> bool:
    """Whether OIDC verification is in force for this process."""
    return bool(issuer())


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    """The JWT carried by an ``Authorization`` header, or None.

    Only a JWT-SHAPED bearer (three dot-separated segments) counts: other bearers on
    this API are real and must pass through untouched — ``/cron/tick`` authenticates
    with ``Bearer $CRON_SECRET`` and the webhook door with its per-chain token.
    """
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = value.strip()
    return token if token.count(".") == 2 and all(token.split(".")) else None


def _discovery_jwks_uri(iss: str) -> str:
    import requests

    resp = requests.get(f"{iss}/.well-known/openid-configuration", timeout=10)
    resp.raise_for_status()
    jwks_uri = (resp.json() or {}).get("jwks_uri") or ""
    if not jwks_uri:
        raise OidcError(f"issuer {iss} publishes no jwks_uri in its discovery document")
    return jwks_uri


def _signing_key(token: str) -> Any:
    """The public key that signed ``token``, resolved through the issuer's JWKS.

    Split out as the one seam the tests replace: everything above it (discovery,
    key cache, HTTP) needs a live IdP, everything below it (signature, exp, aud,
    iss, claims) is the part whose failure modes matter and runs for real.
    """
    import jwt as _pyjwt

    iss = issuer()
    client = _JWKS_CLIENTS.get(iss)
    if client is None:
        client = _pyjwt.PyJWKClient(_discovery_jwks_uri(iss), cache_keys=True)
        _JWKS_CLIENTS[iss] = client
    return client.get_signing_key_from_jwt(token).key


def verify(token: str) -> dict:
    """Verified claims of ``token``, or :class:`OidcError`. Never a partial answer."""
    import jwt as _pyjwt

    if not audience():
        # Without an audience pin, any token the IdP minted for any application would
        # verify here. Refusing to run half-configured IS the fail-closed posture.
        raise OidcError("AUGHOR_OIDC_ISSUER is set but AUGHOR_OIDC_AUDIENCE is not")
    try:
        key = _signing_key(token)
        return _pyjwt.decode(
            token, key=key, algorithms=list(_ALGORITHMS),
            audience=audience(), issuer=issuer(),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except OidcError:
        raise
    except _pyjwt.PyJWTError as exc:
        raise OidcError(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # discovery/JWKS transport failures fail closed too
        raise OidcError(f"key resolution failed: {type(exc).__name__}: {exc}")


def principal_of(claims: dict) -> Principal:
    """The platform principal a verified claim set names.

    The org comes from ``AUGHOR_OIDC_ORG_CLAIM`` when configured AND present — a
    configured claim that is absent from the token refuses rather than defaulting,
    because a token silently landing in the default org is a tenant-boundary bug
    wearing a convenience.
    """
    user = str(claims.get("email") or claims.get("sub") or "").strip()
    org_claim = (os.environ.get("AUGHOR_OIDC_ORG_CLAIM") or "").strip()
    if org_claim:
        org = str(claims.get(org_claim) or "").strip()
        if not org:
            raise OidcError(f"token carries no {org_claim!r} claim (AUGHOR_OIDC_ORG_CLAIM)")
    else:
        org = (os.environ.get("AUGHOR_OIDC_DEFAULT_ORG") or "default").strip()
    return Principal(user_id=user, org_id=org)


def resolve_verified(authorization: Optional[str]) -> Optional[Principal]:
    """The full path: header → JWT-shaped bearer → verified claims → principal.

    ``None`` when no JWT-shaped bearer is presented. A presented-but-invalid token
    raises — the caller decides how that surfaces (401), but it must never resolve.
    """
    token = bearer_token(authorization)
    if token is None:
        return None
    return principal_of(verify(token))
