"""Wave O3 — order retrieval candidates by usage, never by edge evidence.

**The pre-check ran first, and it moved the scope.** Measured on the reference connection
before any code (the L3 lesson, and a gate in this wave's scoping doc):

    table hints    5 terms,  0% with more than one candidate  → ranking is INERT
    column hints   5 terms, 100% with more than one candidate (4–5 each)
    metric names   2 metrics, 0 name collisions               → nothing to resolve yet
    questions      179 of 795 real questions (23%) touch an ambiguous term
                   — `aov`, `average`, `order`, `revenue`, `value`

So ranking is reachable and worth building, but **only where ambiguity exists**, which
today is column candidates. Ranking table candidates would have been machinery over a set
of size one. That is the sort of finding that is free before the code and expensive after,
and it is why :func:`rank` states plainly that it is a no-op on a single candidate rather
than quietly returning the same list.

**What ranks, in order of authority:**

1. **Declared source rank** (O1's synonym store: human > mined > llm_candidate). A human
   statement outranks every popularity signal — the governance story Genie does not have.
2. **Usage** — ledger hits, drill records, trusted-query usage. Popularity, honestly
   labelled as popularity.
3. **Freshness** — V's vocabulary; a `stale` candidate sinks below a `fresh` one.

**What never ranks: edge evidence.** J4 and J14 both say it and it is worth restating,
because the temptation is real and the code would look reasonable: a join's measured
overlap is evidence that a join is SAFE, not that a table is what the user MEANT.
Popularity is not evidence, and ordering retrieval must never become weighting the graph.
This module reads no edges and exposes no way to.

**Ordering, not filtering.** Nothing here drops a candidate. A ranker that filtered would
silently hide the right answer when its signals were wrong, and the failure would look
exactly like the entity not existing — the same confusion G5's notice exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

#: Source ranks, mirrored from O1's vocabulary so the two cannot disagree about which
#: source outranks which.
from aughor.ontology.vocabulary import SOURCE_RANKS  # noqa: E402

#: Freshness states that sink a candidate, in V's vocabulary (never a sixth dialect).
_STALE_STATES = frozenset({"stale", "dirty"})


@dataclass
class Signals:
    """What is known about one candidate. Every field is optional and absent means
    "unknown", which ranks neutrally — an unmeasured candidate must not be punished as if
    it had been measured and found unused."""

    source: Optional[str] = None       # one of SOURCE_RANKS
    hits: int = 0                      # ledger record_hit / drill records
    trusted_uses: int = 0              # times a trusted query used it
    freshness: Optional[str] = None    # V vocabulary: fresh | dirty | stale | unknown

    def to_dict(self) -> dict:
        return {"source": self.source, "hits": self.hits,
                "trusted_uses": self.trusted_uses, "freshness": self.freshness}


@dataclass
class RankedCandidate:
    """One candidate with the score that placed it, and why."""

    candidate: str
    score: tuple
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"candidate": self.candidate, "reasons": list(self.reasons)}


def _source_index(source: Optional[str]) -> int:
    if source is None:
        return len(SOURCE_RANKS)          # unknown ranks below every declared source
    try:
        return SOURCE_RANKS.index(source)
    except ValueError:
        return len(SOURCE_RANKS)


def score(candidate: str, signals: Signals) -> tuple:
    """The sort key. Lower is better, so a plain ``sorted`` puts the winner first.

    A TUPLE rather than a weighted sum, deliberately: a sum invites tuning constants
    nobody can justify, and makes "why did this win" unanswerable. A lexicographic tuple
    says the priority order out loud — a human declaration beats any amount of popularity,
    and the tie-break chain is readable in one line.
    """
    stale = 1 if (signals.freshness or "").lower() in _STALE_STATES else 0
    return (
        _source_index(signals.source),      # 1. declared authority
        stale,                              # 2. stale sinks
        -int(signals.trusted_uses or 0),    # 3. verified reuse
        -int(signals.hits or 0),            # 4. raw popularity
        candidate,                          # 5. alphabetical — deterministic ties
    )


def _reasons(signals: Signals) -> list[str]:
    out: list[str] = []
    if signals.source:
        out.append(f"declared by {signals.source}")
    if signals.trusted_uses:
        out.append(f"used by {signals.trusted_uses} trusted quer"
                   f"{'y' if signals.trusted_uses == 1 else 'ies'}")
    if signals.hits:
        out.append(f"{signals.hits} recorded hit(s)")
    if (signals.freshness or "").lower() in _STALE_STATES:
        out.append(f"ranked down: {signals.freshness}")
    return out


def rank(
    candidates: Sequence[str],
    signals_for: Callable[[str], Signals] | dict[str, Signals],
) -> list[RankedCandidate]:
    """Order candidates best-first. **A no-op on a list of one**, and that is stated
    rather than implied: the pre-check found table candidates are unambiguous today, so a
    caller must be able to tell "ranking did nothing" from "ranking chose this".

    Never filters — see the module docstring.
    """
    lookup = ((lambda c: signals_for.get(c, Signals()))
              if isinstance(signals_for, dict) else signals_for)
    ranked = [RankedCandidate(candidate=c, score=score(c, s), reasons=_reasons(s))
              for c, s in ((c, lookup(c)) for c in candidates)]
    return sorted(ranked, key=lambda r: r.score)


def rank_terms(
    hints: dict[str, list[str]],
    signals_for: Callable[[str], Signals] | dict[str, Signals],
) -> dict[str, list[str]]:
    """Re-order a linker hint map in place-safe fashion, returning a new map.

    Terms with a single candidate pass through untouched — measured as 100% of table
    hints on the reference connection, so this path is the common one and must be free.
    """
    out: dict[str, list[str]] = {}
    for term, cands in (hints or {}).items():
        if len(cands) < 2:
            out[term] = list(cands)
            continue
        out[term] = [r.candidate for r in rank(cands, signals_for)]
    return out


def ambiguity(hints: dict[str, list[str]]) -> dict:
    """How much of a hint map ranking can actually affect.

    Exposed because it is the number that scoped this item, and because a future
    connection may be far more ambiguous than the one measured — a caller deciding whether
    ranking is worth its cost should read the number rather than inherit the finding.
    """
    total = len(hints or {})
    multi = sum(1 for v in (hints or {}).values() if len(v) > 1)
    return {"terms": total, "ambiguous": multi,
            "share": round(multi / total, 3) if total else 0.0}


def signals_from_stores(connection_id: str) -> dict[str, Signals]:
    """Best-effort signal lookup for a connection.

    Reads O1's declared synonyms for source rank and the graph's freshness state. Returns
    ``{}`` rather than raising — an unavailable signal store must degrade ranking to the
    deterministic alphabetical tie-break, never fail a question.
    """
    out: dict[str, Signals] = {}
    try:
        from aughor.ontology.vocabulary import synonyms_for

        for syn in synonyms_for(connection_id):
            existing = out.get(syn.subject_id)
            if existing is None or _source_index(syn.source) < _source_index(existing.source):
                out[syn.subject_id] = Signals(source=syn.source)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "ranking signals are best-effort; ordering degrades to the "
                      "deterministic tie-break",
                 counter="ontology.ranking_signals")
    return out


def has_edge_signal(_: Iterable) -> bool:
    """Always ``False`` — this module reads no edges, by design (J4/J14).

    Present so the rule is testable rather than merely documented: a join's measured
    overlap is evidence that a join is SAFE, not that a table is what the user MEANT, and
    ordering retrieval must never become weighting the graph.
    """
    return False
