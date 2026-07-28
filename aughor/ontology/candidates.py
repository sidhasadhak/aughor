"""Wave O4 — mine typed candidates, bind them before offering, apply none of them.

The compounding-accuracy loop: what the platform already learned becomes a *proposal* a
human accepts or rejects, and accepting it makes the next answer better. Snowflake's
capture → verify → generalize → suggest, with Aughor's binding rigor bolted on.

**Three rules, and the wave stands or falls on them.**

1. **Nothing auto-applies.** A candidate is a suggestion, and it reaches the A4
   resolve-once inbox — J10, ONE queue. A second suggestion store is the bug the
   five-eval-surfaces lesson already paid for.
2. **Every candidate EXPLAIN-binds before it is offered.** Unbound SQL is never even
   shown. A suggestion that cannot execute wastes the reviewer's attention *and* teaches
   them the queue is noise, which is how a review surface dies.
3. **Provenance and rank travel with the candidate.** A mined join and a human-declared
   one are not the same claim; the source rank (O1's ladder) rides along so nothing
   downstream can confuse "we noticed this" with "somebody decided this". J4 unchanged —
   a candidate proposes, it never writes an edge.

**Where candidates come from.** Accepted verdicts, trusted queries, and — at onboarding —
the source's own saved / dbt / query-log SQL. All three are records of a human having
already run or approved something, which is what makes mining them defensible: the loop
generalizes decisions that were made, rather than inventing decisions nobody took (the N1
line, one layer over).

Deterministic mining; the binder is injected so this module needs no warehouse to test and
the dialect-specific EXPLAIN lives with the connector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: What a candidate can propose. Typed rather than free-form because the reviewer's
#: question differs per kind — a join asks "is this key right", a synonym asks "do people
#: really say that" — and an untyped suggestion queue cannot ask either.
CANDIDATE_KINDS: tuple[str, ...] = ("join", "measure", "filter", "synonym", "object_set")

#: Where a candidate was mined from. Each is a record of a human having run or approved
#: something, which is what makes generalizing it defensible.
ORIGINS: tuple[str, ...] = ("verdict", "trusted_query", "saved_sql", "dbt", "query_log")


class CandidateError(ValueError):
    """A malformed candidate. Raised at construction rather than filtered at review —
    junk that reaches the queue teaches the reviewer to skim it."""


@dataclass
class Candidate:
    """One typed proposal, with where it came from and how strong the claim is."""

    connection_id: str
    kind: str
    subject: str                     # the table / metric / term it is about
    proposal: str                    # the join predicate, formula, filter or synonym
    origin: str
    source_rank: str = "mined"       # O1's ladder: human > mined > llm_candidate
    evidence: str = ""               # what was observed, for the reviewer
    bound: Optional[bool] = None     # None = not yet checked
    bind_error: str = ""

    def validate(self) -> None:
        if self.kind not in CANDIDATE_KINDS:
            raise CandidateError(
                f"unknown candidate kind {self.kind!r} — known: {list(CANDIDATE_KINDS)}")
        if self.origin not in ORIGINS:
            raise CandidateError(
                f"unknown candidate origin {self.origin!r} — known: {list(ORIGINS)}")
        if not str(self.subject).strip() or not str(self.proposal).strip():
            raise CandidateError("a candidate needs a subject and a proposal")

    @property
    def offerable(self) -> bool:
        """Whether this may be shown to a reviewer. Unbound SQL never is."""
        return self.bound is True

    def to_dict(self) -> dict:
        return {"connection_id": self.connection_id, "kind": self.kind,
                "subject": self.subject, "proposal": self.proposal,
                "origin": self.origin, "source_rank": self.source_rank,
                "evidence": self.evidence, "bound": self.bound,
                "bind_error": self.bind_error, "offerable": self.offerable}


#: A binder returns (ok, error). Injected so the dialect-specific EXPLAIN lives with the
#: connector and this module is testable without a warehouse.
Binder = Callable[[Candidate], tuple[bool, str]]


def bind(candidate: Candidate, binder: Binder) -> Candidate:
    """EXPLAIN-bind one candidate. A binder that RAISES marks it unbound, never bound.

    Failing closed is the only safe direction: an exception means we do not know whether
    the proposal executes, and offering it anyway is exactly the noise rule 2 forbids.
    """
    candidate.validate()
    try:
        ok, err = binder(candidate)
    except Exception as exc:
        candidate.bound = False
        candidate.bind_error = f"{type(exc).__name__}: {exc}"
        return candidate
    candidate.bound = bool(ok)
    candidate.bind_error = "" if ok else (err or "did not bind")
    return candidate


def offerable(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Only the candidates a reviewer should ever see."""
    return [c for c in candidates if c.offerable]


@dataclass
class MiningReport:
    """What mining produced, including what it refused to offer."""

    candidates: list[Candidate] = field(default_factory=list)

    @property
    def offered(self) -> list[Candidate]:
        return offerable(self.candidates)

    @property
    def refused(self) -> list[Candidate]:
        return [c for c in self.candidates if c.bound is False]

    def summary(self) -> str:
        # The refused count is always stated. A miner that reported only its successes
        # would look like it was finding less than it was, and hide a broken binder.
        return (f"{len(self.candidates)} candidate(s) mined, {len(self.offered)} bound "
                f"and offerable, {len(self.refused)} refused for not binding.")

    def to_dict(self) -> dict:
        return {"summary": self.summary(),
                "offered": [c.to_dict() for c in self.offered],
                "refused": [c.to_dict() for c in self.refused]}


def mine_from_trusted_queries(connection_id: str, rows: Iterable[dict]) -> list[Candidate]:
    """Trusted queries → filter and join candidates.

    A trusted query is SQL a human approved, so generalizing its filters is generalizing a
    decision that was taken. Deliberately shallow: it proposes what the query literally
    contains, and never infers intent from it.
    """
    out: list[Candidate] = []
    for row in rows:
        sql = str(row.get("sql") or "")
        question = str(row.get("question") or "")
        for table in (row.get("tables") or []):
            if " join " in sql.lower():
                out.append(Candidate(
                    connection_id=connection_id, kind="join", subject=str(table),
                    proposal=sql, origin="trusted_query", source_rank="mined",
                    evidence=f"used by the trusted query for {question!r}"))
                break
    return out


def mine_from_verdicts(connection_id: str, rows: Iterable[dict]) -> list[Candidate]:
    """Accepted verdicts → synonym and measure candidates.

    Only ACCEPTED verdicts are mined. A rejected correction is evidence about what is
    wrong, not a proposal to generalize, and mining it would propose the mistake.
    """
    out: list[Candidate] = []
    for row in rows:
        if str(row.get("verdict") or "").lower() not in ("accepted", "correct", "approved"):
            continue
        subject = str(row.get("subject") or "").strip()
        proposal = str(row.get("correction") or "").strip()
        if not subject or not proposal:
            continue
        out.append(Candidate(
            connection_id=connection_id, kind=str(row.get("kind") or "synonym"),
            subject=subject, proposal=proposal, origin="verdict", source_rank="mined",
            evidence=f"accepted correction on {row.get('question', 'a past answer')!r}"))
    return out


def mine(connection_id: str, *, trusted_queries: Iterable[dict] = (),
         verdicts: Iterable[dict] = (), binder: Optional[Binder] = None) -> MiningReport:
    """Mine every source, bind everything, and report what was refused.

    With no binder nothing is offerable — `bound` stays ``None``. That is the correct
    default rather than an inconvenience: a deployment that has not wired a binder must
    not start showing unverified SQL to reviewers.
    """
    found = (list(mine_from_trusted_queries(connection_id, trusted_queries))
             + list(mine_from_verdicts(connection_id, verdicts)))
    for c in found:
        c.validate()
    if binder is not None:
        found = [bind(c, binder) for c in found]
    return MiningReport(candidates=found)


def to_inbox_items(candidates: Iterable[Candidate]) -> list[dict]:
    """Shape offerable candidates for the A4 resolve-once inbox.

    J10: ONE queue. This returns inbox ITEMS rather than writing them, so the inbox stays
    the single writer and O4 does not become a second suggestion store — the bug the
    five-eval-surfaces lesson already paid for once.
    """
    return [{"kind": f"ontology.{c.kind}", "subject": c.subject,
             "proposal": c.proposal, "evidence": c.evidence,
             "source_rank": c.source_rank, "origin": c.origin,
             "connection_id": c.connection_id}
            for c in offerable(candidates)]
