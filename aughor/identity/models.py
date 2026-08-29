"""RC-4 — a principal reference that is honest about where it came from.

The plane this fixes was not missing; it was *lying*. Every governed decision already
records an ``actor``, and `govern.actions.audit` filled an absent one with
``current_org_id()`` — so on the live ledger 34 of 67 governed decisions are attributed
to ``default``, which is the TENANT, not a person. An audit trail that answers "who
approved this refund?" with the org name reads as attributed and is not, and that is
strictly worse than an obvious blank: a blank prompts the question, a plausible value
closes it.

The model here is deliberately small, and its shape is the argument:

* **A reference carries its provider.** ``slack:U08N9EQ80UT`` is a real, stable,
  externally-meaningful identity even when nobody has linked it to a platform account.
  Recording it beats recording ``default`` on every axis — it is per-person, it is
  stable across turns, and it says which door it came through.
* **Linking is an upgrade, never a precondition.** An unlinked identity still attributes;
  it just does not yet join to a platform user. This is what lets a Slack door attribute
  from day one and Slack↔web continuity arrive later without a second scheme.
* **The absent case is NAMED, never borrowed.** When nothing is known the answer is
  :data:`UNATTRIBUTED` — never the org, never an empty string that a downstream
  ``or`` can quietly replace with something else.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

#: What an unknown actor is called. A value, not a blank: an empty string invites the
#: exact `actor or <something ambient>` fallback that produced the defect.
UNATTRIBUTED = "unattributed"

#: A provider token: lowercase, short, no separator that would make `ref` ambiguous.
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class Identity(BaseModel):
    """One principal, as a door reported it — plus the platform user it links to, if any."""
    provider: str            # "slack" | "web" | "api" | "automation" | "system"
    external_id: str         # stable id WITHIN that provider (a Slack user id, an email)
    user_id: str = ""        # the linked platform user; "" = not linked (still attributable)
    display: str = ""        # a human label when the door knows one; never used as a key

    @property
    def ref(self) -> str:
        """The canonical ``provider:external_id`` string. Stable, and safe to store."""
        return f"{self.provider}:{self.external_id}"

    @property
    def linked(self) -> bool:
        return bool(self.user_id)

    @property
    def attribution_key(self) -> str:
        """What to record as the actor.

        The linked platform user when there is one — that is what makes the same person
        the same subject across doors — else the provider-qualified ref, which is still a
        real identity. Never the org, never empty.
        """
        return self.user_id or self.ref


def parse_ref(raw: str) -> Optional[Identity]:
    """Parse ``provider:external_id`` into an :class:`Identity`, or None if it is not one.

    None is returned for the values that look like identities but are not — ``"human"``,
    ``"agent-ops"``, ``"me"``, all of which appear in the live ledger today. They are
    labels someone typed, and promoting a label to an identity is how a trail acquires
    confident nonsense. The caller decides what an un-parseable actor means; this refuses
    to guess.

    Only the FIRST colon splits, so an external id may contain colons (a Slack thread ref,
    a composite key) without needing an escape.
    """
    if not raw or ":" not in raw:
        return None
    provider, _, external = raw.partition(":")
    provider, external = provider.strip().lower(), external.strip()
    if not _PROVIDER_RE.match(provider) or not external:
        return None
    return Identity(provider=provider, external_id=external)
