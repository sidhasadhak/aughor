"""HB-4 — the one ranker: deterministic on three axes, shown in the receipt, and no
model decides which context outranks which (§3.18).

The axes, in order:

1. **authority** — the envelope's ladder (measured > approved > declared > mined >
   said > inferred);
2. **scope** — this object > this connection > this domain > the organisation > the
   industry pack;
3. **recency PER KIND, never one global score** — a definition's current approved
   version wins regardless of age; an observation decays and EXPIRES unless
   re-affirmed (dropped, reason recorded); a measurement carries the data's own
   as-of and the freshest wins.

Conflicts (two pieces about one subject): different tiers — the higher wins and the
lower is dropped WITH A FLAG in the receipt; same tier — both survive ranking and the
conflict is surfaced for a person (the ambiguity ledger's "ask once, remember" is the
caller's hook — this module only refuses to guess).

The ranker fills a character budget and SAYS WHAT IT DROPPED — a receipt where an
omission is as legible as an inclusion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from aughor.hub.provenance import ContextPiece, authority_rank, scope_rank


@dataclass
class Dropped:
    piece_id: str
    subject: str
    reason: str


@dataclass
class Conflict:
    subject: str
    piece_ids: list[str]
    tier: str


@dataclass
class RankedContext:
    """What survived, in rank order, with the full account of what did not."""
    kept: list[ContextPiece] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    def rendered(self, now: Optional[datetime] = None) -> str:
        """The prompt/reader block: each kept piece with its stamp, one per line."""
        return "\n".join(p.block(now) for p in self.kept)

    def receipt(self) -> dict:
        return {
            "kept": [p.piece_id or p.subject for p in self.kept],
            "dropped": [{"piece": d.piece_id, "subject": d.subject, "reason": d.reason}
                        for d in self.dropped],
            "conflicts": [{"subject": c.subject, "pieces": c.piece_ids, "tier": c.tier}
                          for c in self.conflicts],
        }


def _recency_key(p: ContextPiece) -> tuple:
    """Per-kind recency, as a sort key WITHIN an (authority, scope) band.

    definitions: higher approved version first, age irrelevant;
    measurements: the data's own as-of, freshest first;
    everything else: observed_at, freshest first."""
    kind = p.provenance.source_kind
    if kind == "definition":
        return (-int(p.version or 0),)
    return (p.provenance.observed_at and
            "".join(ch for ch in p.provenance.observed_at if ch.isdigit()) or "0",)


def _sort_key(p: ContextPiece) -> tuple:
    key = _recency_key(p)
    # freshest-first for date-shaped keys: invert lexicographically via negation trick —
    # dates are zero-padded digit strings, so sorting DESCENDING needs a reversed key.
    rec = key[0]
    rec_desc = tuple(-ord(c) for c in rec) if isinstance(rec, str) else rec
    return (authority_rank(p.provenance.authority),
            scope_rank(p.provenance.scope_kind),
            rec_desc)


def rank(pieces: list[ContextPiece], *, budget_chars: int = 4000,
         now: Optional[datetime] = None) -> RankedContext:
    """Deterministic ranking + budget fill. Never raises; an empty input is an empty
    receipt, not an error."""
    now = now or datetime.now(timezone.utc)
    out = RankedContext()

    # 1 — expiry: an observation past its window is dropped BEFORE it can compete.
    alive: list[ContextPiece] = []
    for p in pieces or []:
        if p.provenance.expired(now):
            out.dropped.append(Dropped(p.piece_id, p.subject,
                                       "expired — unre-affirmed past its validity window"))
        else:
            alive.append(p)

    # 2 — conflicts by subject: a higher tier wins; the loser is dropped with the flag.
    #     Same-tier disagreement survives ranking and is surfaced — this module never
    #     guesses between two equally-placed claims.
    by_subject: dict[str, list[ContextPiece]] = {}
    for p in alive:
        if p.subject:
            by_subject.setdefault(p.subject, []).append(p)
    survivors: list[ContextPiece] = [p for p in alive if not p.subject]
    for subject, group in by_subject.items():
        if len(group) == 1:
            survivors.extend(group)
            continue
        best = min(authority_rank(p.provenance.authority) for p in group)
        top = [p for p in group if authority_rank(p.provenance.authority) == best]
        for p in group:
            if p not in top:
                out.dropped.append(Dropped(
                    p.piece_id, subject,
                    f"outranked on {subject}: {p.provenance.authority} loses to "
                    f"{top[0].provenance.authority} — kept as this flag, not in the block"))
        if len(top) > 1:
            out.conflicts.append(Conflict(
                subject, [p.piece_id for p in top],
                tier=top[0].provenance.authority))
        survivors.extend(top)

    # 3 — the three axes, then the budget. Dropping for budget is recorded like any
    #     other omission: a reader can see what the block would have said next.
    survivors.sort(key=_sort_key)
    used = 0
    for p in survivors:
        cost = len(p.block(now)) + 1
        if used + cost > budget_chars and out.kept:
            out.dropped.append(Dropped(p.piece_id, p.subject,
                                       f"over the context budget ({budget_chars} chars)"))
            continue
        out.kept.append(p)
        used += cost
    return out
