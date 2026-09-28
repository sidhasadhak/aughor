"""Where a cockpit lives: a person's, on one connection (Arc CT, CT-7; ROADMAP §3.50).

The first home was a Data Canvas. The user moved it (§6 item 36(c), superseded): the Briefing
is the connection's, and a cockpit is a person's own — their dashboard, and a Briefing tailored
to the areas they look into. So a cockpit is now three things: the connection
it reads, the person it belongs to, and that person's own name for it — "Returns", "Pricing".
A person keeps as many as they like.

**A person** is who the request says, as the Briefing's arrangement has always named them
(``routers/dashboard._layout_user_id``): the identified user, or ``default`` where identity is
off and one operator uses every device. It is never a value the page or a model supplies.

**Its cards** are the cards the connection shares — the ones pinned for everyone, as the
Briefing's cockpit has always read them — and the person's own. A card a person's cockpit
creates is theirs (the card store's ``user`` scope), so a limit set on it is theirs too.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Optional

#: Where identity is off, the one operator's name — the same as the Briefing's arrangement.
NOBODY_IN_PARTICULAR = "default"

#: A person's first cockpit, started from the cards pinned before cockpits had names.
FIRST = "my-cockpit"

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_NOT_ID = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Home:
    """One person's cockpit on one connection."""
    connection_id: str
    owner: str
    cockpit_id: str

    @property
    def key(self) -> str:
        """The Ledger's natural key. A canvas cockpit was ``cockpit:<canvas>``; a person's
        says whose it is in the key itself, so a list of a person's cockpits is a prefix."""
        return f"{prefix(self.connection_id, self.owner)}{self.cockpit_id}"

    def as_params(self) -> dict:
        return {"connection_id": self.connection_id, "owner": self.owner, "cockpit_id": self.cockpit_id}

    @classmethod
    def of(cls, params: dict) -> Optional["Home"]:
        """The home a proposal's params name, or None when they name none."""
        if not isinstance(params, dict):
            return None
        conn, owner, cid = (str(params.get(k) or "") for k in ("connection_id", "owner", "cockpit_id"))
        return cls(conn, owner, cid) if conn and owner and valid_id(cid) else None


def prefix(connection_id: str, owner: str) -> str:
    return f"cockpit:person:{connection_id}:{owner}:"


def valid_id(cockpit_id: str) -> bool:
    return bool(_ID.match(cockpit_id or ""))


def new_id(name: str) -> str:
    """A cockpit id from the name a person gave it: readable, and never one they already
    have — the suffix is random, not counted, so two tabs starting one at once do not meet."""
    slug = _NOT_ID.sub("-", (name or "").lower()).strip("-")[:32] or "cockpit"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def person_of(request) -> str:
    """Who is asking, as the Briefing's arrangement names them."""
    try:
        from aughor.security.authz import get_principal
        p = get_principal(request)
        return p.user_id if p and p.user_id else NOBODY_IN_PARTICULAR
    except Exception:
        return NOBODY_IN_PARTICULAR


def approver(owner: str) -> str:
    """How an approval by this person is written on a version and on a proposal."""
    return f"user:{owner}" if owner and owner != NOBODY_IN_PARTICULAR else "person"
