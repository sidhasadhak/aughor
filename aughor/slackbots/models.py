"""RC-5 — a Slack bot as a platform record.

RC-1 put `@aughor` in a Slack thread and RC-2 gave its answers charts and cards, but
both ran against ONE bot whose credentials lived in a `.env.local` on a laptop. Nothing
about that is a platform object, so nothing about it is user-creatable — and the ask was
for users to make as many bots as they want, from inside Aughor.

The whole feature is this tuple::

    {bot_token, app_token, signing_secret}  →  {agent_id, connection_id}

and the two halves of that arrow are the design:

* **The right half is a REFERENCE, never a copy.** A bot points at a `UserAgent`, which
  already owns instructions, purpose, bound documents, packs, connection and its eval
  chip. Copying any of that here would fork the governing configuration and silently
  invalidate `config_rev` — the fingerprint the pass chip uses to say whether a
  measurement is still about this agent. A bot is a DOOR onto an agent, not an agent.
* **The left half is three credentials, and they are the credential.** Anyone holding a
  bot token can post as that app, exactly as a Slack webhook URL *is* the credential
  (`notifications/executor.py`). All three are encrypted at rest and masked on read.

`agent_view` is here rather than inferred because it must match the Slack app's own
manifest: the adapter's `agentView` requires an app in `agent_view` mode, and turning it
on against an `assistant_view` app makes `stopStream` send a parameter that app cannot
accept — which costs the final message of every answer. The manifest and the record are
written in the same act, so the flag belongs with the record that act produces.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from aughor.secretvault import decrypt_secret, encrypt_secret, mask_secret
from aughor.util.time import now_iso_z

NAME_MAX = 80

#: The three Slack secrets. Named once so the encrypt / decrypt / mask paths cannot
#: drift apart — a field added to one and missed by another is how a token leaks.
SECRET_FIELDS = ("bot_token", "app_token", "signing_secret")


class SlackBot(BaseModel):
    """One Slack app bound to one Aughor agent."""
    id: str = ""
    name: str = ""
    enabled: bool = True

    # ── the binding ──
    agent_id: str = ""          # the UserAgent whose instructions/docs/packs answer
    connection_id: str = ""     # the warehouse it answers over ("" = the ask's own)

    # ── the credentials (encrypted at rest, masked on read) ──
    bot_token: str = ""         # xoxb-…  posts as the bot
    app_token: str = ""         # xapp-…  opens the Socket Mode connection
    signing_secret: str = ""

    # ── what Slack told us at install time ──
    team_id: str = ""
    slack_app_id: str = ""
    bot_user_id: str = ""       # the bot's own Slack user id, from auth.test
    #: Must match the app's manifest mode. See the module docstring.
    agent_view: bool = False

    created_at: str = Field(default_factory=now_iso_z)
    updated_at: str = Field(default_factory=now_iso_z)

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_safe_dict(self) -> dict:
        """The API-facing form — every secret masked, so a raw token never leaves the
        server. The client renders the mask and sends it back unchanged on save; the
        update path detects that and keeps the stored value (see `merge_secrets`)."""
        d = self.to_dict()
        for f in SECRET_FIELDS:
            d[f] = mask_secret(d.get(f) or "")
        return d


def encrypt_secrets(bot: SlackBot) -> SlackBot:
    """Encrypt every secret field. Idempotent — `encrypt_secret` returns an already
    encrypted value unchanged, so re-saving never double-encrypts."""
    return bot.model_copy(update={f: encrypt_secret(getattr(bot, f) or "") or ""
                                  for f in SECRET_FIELDS})


def decrypt_secrets(bot: SlackBot) -> SlackBot:
    """Plaintext secrets, for the supervisor that must actually open a socket."""
    return bot.model_copy(update={f: decrypt_secret(getattr(bot, f) or "") or ""
                                  for f in SECRET_FIELDS})


def is_masked(value: str, stored: str) -> bool:
    """Whether `value` is the mask the API handed out for `stored`, rather than a new
    secret. Compared against the mask of the STORED value, not against a bullet-pattern:
    a shape test would treat any bullet-containing string as "unchanged", and a caller
    that genuinely wants to set a bullet-containing secret would be silently ignored."""
    return bool(value) and bool(stored) and value == mask_secret(stored)


def merge_secrets(incoming: SlackBot, stored: Optional[SlackBot]) -> SlackBot:
    """Carry stored secrets through an update that echoed the mask back.

    Three cases, and the middle one is the whole reason this exists:
      * a new non-empty value  → take it (the caller is rotating the token)
      * the mask we handed out → keep what is stored (an ordinary save of an edit form)
      * empty                  → keep what is stored (the field was not in the payload)
    """
    if stored is None:
        return incoming
    updates = {}
    for f in SECRET_FIELDS:
        new, old = getattr(incoming, f) or "", getattr(stored, f) or ""
        updates[f] = old if (not new or is_masked(new, old)) else new
    return incoming.model_copy(update=updates)
