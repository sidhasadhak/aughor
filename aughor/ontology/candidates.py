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

**Where candidates come from.** Accepted verdicts, trusted queries, and — Arc NV-3,
2026-11-04 — the warehouse's OWN query history (`mine_from_query_log`: the SQL people ran
there, read by the connector's `query_history` when the organisation allows it, parsed by
`aughor.sql.query_log_miner`). All three are records of a human having already run or
approved something, which is what makes mining them defensible: the loop generalizes
decisions that were made, rather than inventing decisions nobody took (the N1 line, one
layer over). `saved_sql` and `dbt` were listed as origins for two years and never written
by anything; they are gone, so a reader is not told a source exists that does not.

Deterministic mining; the binder is injected so this module needs no warehouse to test and
the dialect-specific EXPLAIN lives with the connector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: What a candidate can propose. Typed rather than free-form because the reviewer's
#: question differs per kind — a join asks "is this key right", a synonym asks "do people
#: really say that" — and an untyped suggestion queue cannot ask either.
#: `"object_set"` is FROZEN even though the thing it proposes is now a Segment:
#: `to_inbox_items` writes it into the A4 inbox as `"ontology.object_set"`, so the
#: string is a persisted record value. Map it to "segment" for display, never here.
CANDIDATE_KINDS: tuple[str, ...] = ("join", "measure", "filter", "synonym", "object_set")

#: Where a candidate was mined from. Each is a record of a human having run or approved
#: something, which is what makes generalizing it defensible. Every name here has a miner.
ORIGINS: tuple[str, ...] = ("verdict", "trusted_query", "query_log")


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


def _edge_key(edge: str) -> str:
    """`orders.customer_id = customers.id`, either way round, lower-cased → one key."""
    sides = [s.strip().lower() for s in edge.split("=")]
    return " = ".join(sorted(sides))


def known_join_edges(join_map: dict) -> set[str]:
    """The join map's edges (`compute_join_map`'s `joins`) as the miner spells them, so a mined edge the map already
    holds is not proposed again."""
    out: set[str] = set()
    for j in (join_map or {}).get("joins", []) or []:
        if isinstance(j, dict) and all(j.get(k) for k in ("t1", "c1", "t2", "c2")):
            out.add(_edge_key(f"{j['t1']}.{j['c1']} = {j['t2']}.{j['c2']}"))
    return out


#: A query-history fact must recur to be proposed: one person's one-off join is not how the warehouse is queried.
QUERY_LOG_MIN_SUPPORT = 2


def mine_from_query_log(connection_id: str, sqls: Iterable[str], *, dialect: str = "duckdb",
                        known_joins: Iterable[str] = (), min_support: int = QUERY_LOG_MIN_SUPPORT,
                        max_per_kind: int = 25) -> list[Candidate]:
    """The warehouse's own query history → join, filter and measure candidates (Arc NV-3).

    Deterministic: `aughor.sql.query_log_miner` parses every statement with sqlglot and counts what recurs. A join
    edge the name-based join map already holds is skipped — the point is the edges the map LACKS (the AT&T
    measurement: ~25% more join constraints in the log than in the declared keys). Each candidate's evidence says
    how often it was seen, so the reviewer judges a frequency, not a claim. Nothing here binds: `mine` does.
    """
    from aughor.sql.query_log_miner import mine_query_log
    sqls = [s for s in sqls if s and str(s).strip()]
    if not sqls:
        return []
    facts = mine_query_log(list(sqls), dialect=dialect)
    known = {_edge_key(e) for e in known_joins}
    out: list[Candidate] = []
    joins = [(e, n) for e, n in facts.join_edges.most_common() if n >= min_support and _edge_key(e) not in known]
    for edge, n in joins[:max_per_kind]:
        left = edge.split("=")[0].strip()
        out.append(Candidate(
            connection_id=connection_id, kind="join", subject=left.split(".")[0], proposal=edge,
            origin="query_log", source_rank="mined",
            evidence=f"joined this way in {n} of {facts.n_parsed} runs in the warehouse's query history; "
                     "not in the join map"))
    filters = sorted(((qc, c) for qc, c in facts.filter_values.items() if sum(c.values()) >= min_support),
                     key=lambda kv: sum(kv[1].values()), reverse=True)
    for qc, counter in filters[:max_per_kind]:
        vals = [v for v, _ in counter.most_common(8)]
        col = qc.split(".")[-1]
        proposal = f"{col} IN ({', '.join(repr(v) for v in vals)})"
        out.append(Candidate(
            connection_id=connection_id, kind="filter", subject=qc, proposal=proposal,
            origin="query_log", source_rank="mined",
            evidence=f"filtered on these values in {sum(counter.values())} runs in the query history"))
    # A formula the platform itself named (`_n`, `_first`, `_v`: the Briefing's checks and the metric probes) is how
    # Aughor queries, not how the business does; a reviewer gains nothing from being offered it back.
    formulas = [(k, n) for k, n in facts.named_formulas.most_common()
                if n >= min_support and not str(k[0]).startswith("_")]
    for (name, expr), n in formulas[:max_per_kind]:
        tables = sorted(facts.formula_tables.get((name, expr), set()))
        out.append(Candidate(
            connection_id=connection_id, kind="measure", subject=", ".join(tables) or name, proposal=expr,
            origin="query_log", source_rank="mined",
            evidence=f"computed as `{name}`" + (f" over {', '.join(tables)}" if tables else "")
                     + f" in {n} of {facts.n_parsed} runs in the query history"))
    return out


def mine(connection_id: str, *, trusted_queries: Iterable[dict] = (),
         verdicts: Iterable[dict] = (), query_log: Iterable[str] = (), dialect: str = "duckdb",
         known_joins: Iterable[str] = (), binder: Optional[Binder] = None) -> MiningReport:
    """Mine every source, bind everything, and report what was refused.

    With no binder nothing is offerable — `bound` stays ``None``. That is the correct
    default rather than an inconvenience: a deployment that has not wired a binder must
    not start showing unverified SQL to reviewers.
    """
    found = (list(mine_from_trusted_queries(connection_id, trusted_queries))
             + list(mine_from_verdicts(connection_id, verdicts))
             + list(mine_from_query_log(connection_id, query_log, dialect=dialect, known_joins=known_joins)))
    for c in found:
        c.validate()
    if binder is not None:
        found = [bind(c, binder) for c in found]
    return MiningReport(candidates=found)


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_").lower()
    return s[:48] or "candidate"


def proposal_detail(c: Candidate, table_to_entity: dict[str, str]) -> tuple[Optional[dict], str]:
    """Arc NV-4 — what ACCEPTING this candidate declares, resolved against the served graph, or why it cannot be
    staged. A join becomes a link spec for the link door (`from_entity`, `to_entity`, the two columns, a name); a
    measure over ONE entity a computed property on it; a filter a segment on its entity. A candidate whose tables
    the graph does not know, or a formula over several entities, is not staged — said, with why — because the
    inbox offers Accept, and an accept that could not declare anything is a lie in a button."""
    def entity_of(table: str) -> str:
        t = (table or "").strip()
        return table_to_entity.get(t) or table_to_entity.get(t.split(".")[-1]) or ""

    if c.kind == "join":
        try:
            left, right = [side.strip() for side in c.proposal.split("=", 1)]
            lt, lc = left.rsplit(".", 1)
            rt, rc = right.rsplit(".", 1)
        except ValueError:
            return None, "the join edge is not `table.column = table.column`"
        fe, te = entity_of(lt), entity_of(rt)
        if not fe or not te:
            return None, f"no entity backs {lt if not fe else rt} in the served graph"
        if fe == te:
            return None, "both sides are the same entity"
        return {"declares": "link", "from_entity": fe, "to_entity": te, "from_column": lc, "to_column": rc,
                "name": f"{_slug(fe)}_to_{_slug(te)}_from_history"}, ""
    if c.kind == "measure":
        tables = [t.strip() for t in c.subject.split(",") if t.strip()]
        entities = sorted({entity_of(t) for t in tables if entity_of(t)})
        if len(tables) != 1 or len(entities) != 1:
            return None, ("the formula reads several tables; a computed property lives on one entity — declare it by hand"
                          if len(tables) > 1 else f"no entity backs {c.subject or 'the formula'} in the served graph")
        name = c.evidence.split("`")[1] if c.evidence.count("`") >= 2 else _slug(c.proposal)
        return {"declares": "computed_property", "entity_id": entities[0], "prop_id": _slug(name), "label": name,
                "formula_sql": c.proposal}, ""
    if c.kind == "filter":
        table = c.subject.rsplit(".", 1)[0] if "." in c.subject else c.subject
        col = c.subject.rsplit(".", 1)[-1]
        e = entity_of(table)
        if not e:
            return None, f"no entity backs {table} in the served graph"
        return {"declares": "segment", "entity_id": e, "segment_id": _slug(f"{col}_from_history"),
                "display_name": f"{col} as queried", "filter_sql": c.proposal,
                "description": "the values this column is filtered on in the warehouse's query history"}, ""
    return None, f"a {c.kind} candidate has no declaration to make"


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
