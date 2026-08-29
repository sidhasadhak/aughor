"""Door-supplied principal → the key a governed record should carry (RC-4).

Two entry points, and the split matters:

``resolve`` returns the full :class:`~aughor.identity.models.Identity` — provider, external
id, and the platform user it links to when a link exists. Callers that need to KNOW whether
a principal is linked (a continuity check, an admin screen) use this.

``attribution_key`` returns the one string a ledger row should store. It is total: every
input produces a usable key, and the unknown case is the named
:data:`~aughor.identity.models.UNATTRIBUTED` rather than anything ambient. That totality is
the point — the defect this wave fixes came from an ``or`` reaching for whatever value
happened to be in scope when the real one was missing.

Resolution is deliberately read-only and never auto-creates a link. An unlinked Slack user
attributes as ``slack:U…`` forever until a human links it; inferring a link from a matching
display name is how one person's actions get filed under another's.
"""
from __future__ import annotations

from typing import Optional

from aughor.identity.models import UNATTRIBUTED, Identity, parse_ref


def resolve(raw: str) -> Optional[Identity]:
    """Parse `raw` and attach its platform user if one is linked. None if not a ref.

    A store failure resolves to the UNLINKED identity rather than raising: attribution
    must not be the reason a governed action fails, and `slack:U…` is still an honest
    answer when the link table cannot be read.
    """
    ident = parse_ref(raw)
    if ident is None:
        return None
    try:
        from aughor.identity import store
        user_id = store.get_link(ident.provider, ident.external_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "identity link lookup is best-effort — the unlinked ref still attributes",
                 counter="identity.link_read")
        user_id = None
    return ident.model_copy(update={"user_id": user_id or ""})


def attribution_key(raw: str) -> str:
    """The actor string to record for `raw`. Never empty, never the org.

    Order of preference, each a strictly better answer than the next:
      1. the linked platform user   — the same subject across every door
      2. the provider-qualified ref — a real identity, just not linked yet
      3. the raw value as given     — a label someone chose (``automation:<id>``, ``agent-ops``);
         weak, but it is what the caller meant and discarding it would lose information
      4. :data:`UNATTRIBUTED`       — nothing was supplied
    """
    if not raw or not raw.strip():
        return UNATTRIBUTED
    ident = resolve(raw)
    return ident.attribution_key if ident else raw.strip()
