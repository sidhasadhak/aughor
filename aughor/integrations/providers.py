"""VA-11 — the provider registry: adapters as DATA, not code.

The scope correction that keeps this wave a wave (ROADMAP §3.4): what a connector
vendor sells as "40 integrations" is, for the OAuth half, forty rows of this shape —
an authorize URL, a token URL, scopes, and quirks. Three providers cover the ask;
adding a fourth is an entry here plus nothing.

Two quirks are worth their fields:

* ``revoke_url`` is OPTIONAL because the world is: Google revokes by POST, Slack by
  an authed API call, and Microsoft has no token-revocation endpoint at all — a
  Microsoft "revoke" is deleting our copy, and the UI must SAY that rather than
  imply the provider was told.
* ``pkce`` is per-provider because providers disagree: Google and Microsoft accept
  S256 everywhere; Slack's v2 flow does not take PKCE and errors on unknown params.
  Sending it anyway "to be safe" is how a connect button breaks for exactly one
  provider in a way no hermetic test sees.
"""
from __future__ import annotations

from pydantic import BaseModel


class Product(BaseModel):
    """One product a provider's single app reaches, consented to on its own card.

    Google is one OAuth app and one grant per person, and a product is a SCOPE on it: the
    user, 2026-10-07, wanted Gmail, Sheets, Slides, Drive and Calendar as separate cards,
    each opening Google's consent for that product alone. Each card asks for its own scopes
    with `include_granted_scopes`, so the grant grows a product at a time and the token
    response says which products it now covers. Google revokes a grant whole, never one
    product of it — so disconnecting is the provider's, said on its card, not a product's.
    """

    id: str
    name: str
    blurb: str
    #: Space-separated scopes this product's card requests, beside the provider's own.
    scopes: str


class Provider(BaseModel):
    id: str
    name: str
    #: The catalog category — the grouping the user's own reference screenshots use.
    category: str
    blurb: str
    authorize_url: str
    token_url: str
    revoke_url: str = ""              # "" = the provider offers no revocation endpoint
    #: Space-separated scopes requested by default. What the user GRANTS is read back
    #: from the token response and stored on the Connection, never assumed from here.
    default_scopes: str = ""
    pkce: bool = True
    #: Where the org registers its OAuth client — surfaced beside the Set up form so
    #: the person doing it is never left to search for the right console.
    console_url: str = ""
    #: Extra query params some providers require on the authorize URL.
    authorize_extra: dict[str, str] = {}
    #: Whether this provider REFUSES an `http://` redirect URL, localhost included.
    #:
    #: Measured against the vendors' own docs, not assumed: Google and Microsoft both
    #: accept the loopback address, and Slack does not — "the `redirect_uri` must use
    #: HTTPS", with `http://` examples listed among the rejected ones. The wave that
    #: built this brokered on "localhost is a redirect URI every major provider
    #: accepts", which is true of two of the three shipped here. Carried as a field
    #: because it is the same kind of fact as `pkce` or `authorize_extra` — an
    #: adapter's data — and because the person pasting credentials needs to be told
    #: BEFORE they walk into the provider's own error page.
    https_only: bool = False
    #: A door this provider offers that needs NO public callback, when it has one.
    #:
    #: Slack's app+Socket-Mode path is the case: an outbound WebSocket from Aughor, no
    #: redirect URL, no HTTPS, no tunnel — which is the only Slack integration a laptop
    #: install can complete. It already exists here (RC-5's bot factory); what was
    #: missing is that the catalog pointed a fresh installer at OAuth, the one door
    #: their deployment cannot open. Empty = OAuth is the only way in.
    alt_door: str = ""
    #: The products this provider's one app reaches, each connected from its own card.
    #: Empty = the provider is connected as a whole, from its own card.
    products: list[Product] = []

    def product(self, product_id: str) -> "Product | None":
        return next((p for p in self.products if p.id == product_id), None)

    @property
    def requestable_scopes(self) -> set[str]:
        """Every scope this provider's cards may ask for — its own, and each product's."""
        return set(self.default_scopes.split()) | {s for p in self.products for s in p.scopes.split()}


_GOOGLE_AUTH = "https://www.googleapis.com/auth/"

PROVIDERS: dict[str, Provider] = {p.id: p for p in [
    Provider(
        id="google",
        name="Google",
        category="Productivity",
        blurb="The one Google app every Google card uses — set it up once, then connect each product.",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        revoke_url="https://oauth2.googleapis.com/revoke",
        # Who signed in, nothing more: each product's card asks for its own scope.
        default_scopes="openid email",
        pkce=True,
        console_url="https://console.cloud.google.com/apis/credentials",
        # Without the first two, Google omits the refresh token on every consent after the
        # first — a grant that silently cannot outlive its first hour. The third keeps every
        # product already granted when one more is added, so the token covers them all.
        authorize_extra={"access_type": "offline", "prompt": "consent",
                         "include_granted_scopes": "true"},
        # Read-only, each the narrowest scope its tools need — Drive lists files by their
        # metadata and never reads their contents.
        products=[
            Product(id="gmail", name="Gmail", blurb="Search and read your email.",
                    scopes=_GOOGLE_AUTH + "gmail.readonly"),
            Product(id="sheets", name="Google Sheets", blurb="Read the cells of a spreadsheet.",
                    scopes=_GOOGLE_AUTH + "spreadsheets.readonly"),
            Product(id="slides", name="Google Slides", blurb="Read the text of a presentation, slide by slide.",
                    scopes=_GOOGLE_AUTH + "presentations.readonly"),
            Product(id="drive", name="Google Drive", blurb="Find files by name, type or date — their names and links, not their contents.",
                    scopes=_GOOGLE_AUTH + "drive.metadata.readonly"),
            Product(id="calendar", name="Google Calendar", blurb="Read the events on your calendar.",
                    scopes=_GOOGLE_AUTH + "calendar.readonly"),
        ],
    ),
    Provider(
        id="slack",
        name="Slack",
        category="Communication",
        blurb="Post and read as a Slack app, workspace-scoped.",
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        revoke_url="https://slack.com/api/auth.revoke",
        default_scopes="chat:write channels:read",
        pkce=False,
        console_url="https://api.slack.com/apps",
        https_only=True,
        alt_door="slack_app",
    ),
    Provider(
        id="microsoft",
        name="Microsoft",
        category="Productivity",
        blurb="Outlook mail, OneDrive and Teams through Microsoft Graph.",
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        revoke_url="",  # Graph offers none; revoke is local + the account's own security page
        default_scopes="offline_access User.Read Mail.Read",
        pkce=True,
        console_url="https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
    ),
]}


def get_provider(provider_id: str) -> Provider | None:
    return PROVIDERS.get(provider_id)
