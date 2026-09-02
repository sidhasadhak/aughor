"""DS-17 — the credential behind a chain's webhook door.

A `webhook` trigger is the only trigger kind whose firing is caused from OUTSIDE this
deployment, so it is the only one that needs a credential. Everything else here follows
from that single sentence.

**Why a separate store rather than a column on the automation.** The token is the one
piece of an automation that is a secret, and `GET /automations` returns the record whole
to every caller that can read the list. A column would have put a bearer token into the
body of a route whose whole job is to be read — and `Condition.config` is worse still,
because that dict is echoed by the palette, the graph, the dry run and the DS-14 tool
description. Keeping it out of the record means no surface has to remember to mask it.
It also means **no migration**, which keeps this wave clear of the numbering trap
(`PRAGMA user_version` has to be read off the LIVE db and no hermetic test can catch a
wrong number) — the same reasoning `slackbots/store.py` states for its own rows.

**The shape is `issue_supervisor_key`'s, deliberately.** Mint 32 random bytes, store the
ciphertext, return the plaintext exactly once; every later read is a COMPARISON, never a
disclosure. So the door can tell you *when* a URL was issued and never what it is, and a
rotation is the same gesture as a first issue. That is `credentials.py`'s rule for
anything a reader could use, and a webhook token is the most usable thing in this repo:
it fires a chain with no session at all.

**Revocation is deletion, not a flag.** A revoked token that still exists is a row
somebody can un-revoke; a deleted one cannot come back, and the door reads `closed`
because the absence IS the state. The automation keeps its `webhook` trigger — design
and deployment are different questions, which is the whole of DS-17.
"""
from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from aughor.db.sqlite_util import resolve_db_path
from aughor.secretvault import decrypt_secret, encrypt_secret
from aughor.util.json_store import LedgerListStore
from aughor.util.time import now_iso_z

#: Same store family as the rest of the automations plane. `LedgerListStore` (not the file
#: version) because a token minted on one serverless instance must be verifiable by the
#: next: the file store writes under `data/`, which a read-only bundle ships empty and
#: refuses to write, so a URL issued in the browser would stop working on the next request.
_DIR = resolve_db_path("AUGHOR_AUTOMATIONS_DIR", Path("data"))
_STORE = LedgerListStore(_DIR / "automation_webhooks.json")

#: How many bytes of entropy behind the door. 32 urlsafe bytes is what the supervisor key
#: uses; the threat is online guessing against a route that answers 401, not offline
#: cracking, and this is far past either.
_TOKEN_BYTES = 32


def issue_webhook_token(automation_id: str) -> str:
    """Mint this chain's webhook token, store it encrypted, and return it ONCE.

    Issuing replaces: one automation, one token, and a rotation is the same gesture as a
    first issue — which is also what makes rotation something an operator will actually do.
    """
    raw = secrets.token_urlsafe(_TOKEN_BYTES)
    _STORE.upsert({
        "id": str(automation_id),
        "token": encrypt_secret(raw),
        "created_at": now_iso_z(),
    })
    return raw


def webhook_issued_at(automation_id: str) -> str:
    """When this chain's token was minted, or ``""`` when none exists. Never the token."""
    row = _row(automation_id)
    return str(row.get("created_at", "")) if row else ""


def webhook_token_matches(automation_id: str, candidate: str) -> bool:
    """Constant-time comparison against the stored token. False when none is issued.

    False on *every* failure path — no token, no candidate, a vault that cannot decrypt.
    A verifier that raised would answer 500 to a wrong token and 401 to a missing one,
    which tells an unauthenticated caller which automations exist.
    """
    row = _row(automation_id)
    if not row or not candidate:
        return False
    try:
        stored = decrypt_secret(str(row.get("token", "")) or "") or ""
    except Exception:
        return False
    return bool(stored) and hmac.compare_digest(stored, candidate)


def revoke_webhook_token(automation_id: str) -> bool:
    """Delete this chain's token. True when one was there to delete."""
    return bool(_STORE.delete(str(automation_id)))


def _row(automation_id: str) -> dict:
    return _STORE.get(str(automation_id)) or {}
