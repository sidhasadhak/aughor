"""VA-11 — the credential as a governed object.

Two records, because there are two credentials and they rot differently:

* :class:`ProviderApp` — the ORG's OAuth client registration with one provider
  (client id + secret, from the provider's developer console). One per provider.
  Without it a provider shows **Set up**; with it, **Connect**.
* :class:`Connection` — one USER's grant against that app: the tokens, the scopes
  they actually consented to, and when the access token dies. This is the record
  ``govern.audit`` attributes against, and the record warehouse connections adopt
  later — the decision behind it (ROADMAP §6.1) is that **Aughor owns the vault**:
  the token may never live with a third-party custodian, so it lives here, Fernet
  under ``AUGHOR_SECRET_KEY`` like every other secret this platform holds.

The encryption pattern is lifted from ``slackbots/models.py`` because that pattern is
already proven in production: named ``SECRET_FIELDS``, encrypted on the way into the
store, decrypted only for the caller that must present the token, and **masked for
every reader** — ``security/credentials.py``'s rule that a credential "is an access
token that reading grants" applies to no field more literally than these.
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from aughor.secretvault import decrypt_secret, encrypt_secret, mask_secret
from aughor.util.time import now_iso_z


def _new_id() -> str:
    return f"ic_{uuid.uuid4().hex[:12]}"


# ── the org's app registration ───────────────────────────────────────────────────

APP_SECRET_FIELDS = ("client_secret",)


class ProviderApp(BaseModel):
    """The org's OAuth client for one provider. ``id`` IS the provider id — there is
    exactly one registration per provider, so a synthetic key would only invite two."""
    id: str = ""                      # provider id: "google" | "slack" | "microsoft"
    client_id: str = ""
    client_secret: str = ""           # encrypted at rest
    #: An explicit callback address, when the derived one is not the one registered.
    #:
    #: The callback is normally read off the request (`_callback_uri`), which is right
    #: for a deployment reached at its own address. It is WRONG the moment the API is
    #: registered under an address it is not currently being reached at — the case every
    #: local Slack setup lands in, because Slack refuses `http://` and the developer is
    #: browsing over `http://localhost` while the provider must call back to a tunnel.
    #: Empty = derive it, which is every deployment that never needed to think about it.
    redirect_uri: str = ""
    created_at: str = Field(default_factory=now_iso_z)
    updated_at: str = Field(default_factory=now_iso_z)

    def to_safe_dict(self) -> dict:
        d = self.model_dump()
        for f in APP_SECRET_FIELDS:
            d[f] = mask_secret(d.get(f) or "")
        return d


# ── the user's grant ─────────────────────────────────────────────────────────────

CONNECTION_SECRET_FIELDS = ("access_token", "refresh_token")


class Connection(BaseModel):
    """One user's grant against one provider app.

    ``status`` is a verdict, not a health check:

    * ``active`` — tokens held, refresh believed to work.
    * ``needs_reconnect`` — the provider refused a refresh (``invalid_grant``): the
      grant is dead upstream and only the user consenting again can revive it. Kept
      rather than deleted so the catalog can SAY so instead of silently showing
      "not connected", which reads as "never was".
    * ``revoked`` — revoked from our side. Tokens are cleared but the row stays,
      because "who held access, and until when" is an audit answer this record exists
      to give.
    """
    id: str = Field(default_factory=_new_id)
    provider: str = ""
    #: RC-4's identity plane: the platform user this grant belongs to. "" is a real
    #: value on a single-user install and is stored as itself, never invented into
    #: an actor (the `default`-actor lesson).
    user_id: str = ""
    #: What the PROVIDER says was granted — read back from the token response, not
    #: echoed from what we asked for. A scope the user declined must not be listed.
    scopes: str = ""
    #: The provider's name for the account (an email, a workspace) so a user with two
    #: Google accounts can tell their grants apart.
    account: str = ""
    access_token: str = ""            # encrypted at rest
    refresh_token: str = ""           # encrypted at rest
    token_type: str = "Bearer"
    #: ISO-8601 UTC when the access token dies. The broker refreshes BEFORE this.
    expires_at: Optional[str] = None
    status: str = "active"            # active | needs_reconnect | revoked
    created_at: str = Field(default_factory=now_iso_z)
    updated_at: str = Field(default_factory=now_iso_z)

    def to_safe_dict(self) -> dict:
        """The API-facing form. Token fields are DROPPED, not masked: a mask still
        confirms a token's length-class and invites the client to store the field.
        Nothing above the store has any use for even the shape of these."""
        d = self.model_dump()
        for f in CONNECTION_SECRET_FIELDS:
            d.pop(f, None)
        return d


def encrypt_connection(conn: Connection) -> Connection:
    return conn.model_copy(update={
        f: encrypt_secret(getattr(conn, f) or "") or "" for f in CONNECTION_SECRET_FIELDS})


def decrypt_connection(conn: Connection) -> Connection:
    return conn.model_copy(update={
        f: decrypt_secret(getattr(conn, f) or "") or "" for f in CONNECTION_SECRET_FIELDS})


def encrypt_app(app: ProviderApp) -> ProviderApp:
    return app.model_copy(update={
        f: encrypt_secret(getattr(app, f) or "") or "" for f in APP_SECRET_FIELDS})


def decrypt_app(app: ProviderApp) -> ProviderApp:
    return app.model_copy(update={
        f: decrypt_secret(getattr(app, f) or "") or "" for f in APP_SECRET_FIELDS})
