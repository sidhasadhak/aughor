"""HB-4 — the provenance envelope: every piece of context says where it came from,
who said so, how far it reaches, and how much to trust it (§3.18).

Not a ninth store. Each piece stays where it already belongs — the glossary, the
metrics catalog, the stamped ontology, notes, the claims ledger, the manifest — and
this module is the ENVELOPE those stores' adapters wrap a piece in on the way to a
reader: source kind · author (person, model, system) · scope (object → connection →
domain → organisation → industry) · observed-at with a validity window · verification
tier · blast radius. It completes PX-5's substrate (source asset, author, verification
outranks authority) with the two facts PX-5 did not carry: scope and decay.

The AUTHORITY ladder is the metric-precedence catalog generalised, and it is a CLOSED
vocabulary — an unknown word ranks lowest rather than guessing upward, the same
fail-closed stance as the grant ladder's:

    measured against the data
  > approved by its owner
  > declared by a person
  > mined from a document and reviewed
  > said in a conversation
  > a model's inference

Every block a reader sees carries its stamp — ``[measured 2018-09-11, this connection]``,
``[said by Ana in #ops, 3 days ago, unverified]`` — so trust is legible at the point of
reading, never an implementation detail.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

#: Highest first. Position IS the rank; an unknown authority ranks below the last.
AUTHORITY_LADDER: tuple[str, ...] = (
    "measured",     # executed against the data; the number is the data's own
    "approved",     # a definition its owner approved (Finance's revenue)
    "declared",     # a person declared it (a process, a promise, a rule, a note they wrote)
    "mined",        # extracted from a document and human-reviewed (KI's lane)
    "said",         # said in a conversation; nobody has verified it
    "inferred",     # a model's inference, unconfirmed
)

#: Nearest first. A piece about THIS object outranks one about the industry at large.
SCOPE_LADDER: tuple[str, ...] = (
    "object", "connection", "domain", "organisation", "industry",
)

#: How long a conversational/observational piece stays alive without re-affirmation.
#: Definitions and measurements do NOT decay by this clock — a definition's current
#: approved version wins regardless of age, and a measurement carries the data's own
#: as-of. Only the "somebody said" kinds rot.
OBSERVATION_TTL_DAYS = 30


def authority_rank(authority: str) -> int:
    """0 is highest. Unknown words rank below every known one — fail-closed."""
    a = (authority or "").strip().lower()
    return AUTHORITY_LADDER.index(a) if a in AUTHORITY_LADDER else len(AUTHORITY_LADDER)


def scope_rank(scope_kind: str) -> int:
    s = (scope_kind or "").strip().lower()
    return SCOPE_LADDER.index(s) if s in SCOPE_LADDER else len(SCOPE_LADDER)


@dataclass(frozen=True)
class Provenance:
    """The envelope. ``source_kind`` names the family a harness arm gates by
    (measurement · definition · declaration · document · conversation · inference);
    ``authority`` is the ladder word; ``scope_kind``/``scope_key`` say how far the
    piece reaches; ``observed_at`` is ISO; ``valid_until`` marks explicit expiry
    (conversation pieces default to OBSERVATION_TTL_DAYS past observed_at when
    empty); ``verification`` is the tier word shown in the stamp."""
    source_kind: str
    authority: str
    author: str = ""                 # "Ana" · "user:ana" · a model name · "system"
    author_kind: str = "system"      # person | model | system
    scope_kind: str = "connection"
    scope_key: str = ""
    observed_at: str = ""
    valid_until: str = ""
    verification: str = ""           # verified | approved | reviewed | unverified
    blast_radius: str = ""           # what applying this piece could touch
    where: str = ""                  # "#ops" · "the metrics catalog" — for the stamp

    def expired(self, now: Optional[datetime] = None) -> bool:
        """True when a decaying piece has outlived its window unre-affirmed. Only
        conversation/inference pieces decay by default; anything with an explicit
        ``valid_until`` honours it regardless of kind."""
        now = now or datetime.now(timezone.utc)
        limit = self.valid_until
        if not limit and self.source_kind in ("conversation", "inference") and self.observed_at:
            base = _parse(self.observed_at)
            if base is not None:
                limit_dt = base + timedelta(days=OBSERVATION_TTL_DAYS)
                return now > limit_dt
            return False
        if limit:
            limit_dt = _parse(limit)
            return limit_dt is not None and now > limit_dt
        return False

    def stamp(self, now: Optional[datetime] = None) -> str:
        """The reader-facing provenance mark, the roadmap's exact shapes:
        ``[measured 2018-09-11, this connection]`` ·
        ``[said by Ana in #ops, 3 days ago, unverified]``."""
        parts: list[str] = []
        if self.authority == "said":
            head = "said"
            if self.author:
                head += f" by {self.author}"
            if self.where:
                head += f" in {self.where}"
            parts.append(head)
            age = _age_phrase(self.observed_at, now)
            if age:
                parts.append(age)
        else:
            head = self.authority or self.source_kind
            if self.observed_at:
                head += f" {self.observed_at[:10]}"
            parts.append(head)
            if self.scope_kind == "object" and self.scope_key:
                parts.append(self.scope_key)
            elif self.scope_kind == "connection":
                parts.append("this connection")
            elif self.scope_kind in ("domain", "organisation", "industry"):
                parts.append(f"the {self.scope_kind}"
                             + (f" {self.scope_key}" if self.scope_key and
                                self.scope_kind != "organisation" else ""))
        if self.verification and self.verification not in ("verified", "approved"):
            parts.append(self.verification)
        return "[" + ", ".join(p for p in parts if p) + "]"


@dataclass
class ContextPiece:
    """One candidate block for a reader or a prompt: the text plus its envelope, and
    ``subject`` — what the piece is ABOUT (two pieces sharing a subject can conflict)."""
    text: str
    provenance: Provenance
    subject: str = ""
    piece_id: str = ""
    #: definitions carry their approved version; the current one wins regardless of age.
    version: int = 0
    fields: dict = field(default_factory=dict)

    def block(self, now: Optional[datetime] = None) -> str:
        return f"{self.text} {self.provenance.stamp(now)}"


def _parse(iso: str) -> Optional[datetime]:
    try:
        s = iso.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_phrase(observed_at: str, now: Optional[datetime]) -> str:
    dt = _parse(observed_at or "")
    if dt is None:
        return ""
    now = now or datetime.now(timezone.utc)
    days = max(0, (now - dt).days)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"
