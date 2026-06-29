"""Cross-finding synthesis — the explorer's "build on what it knows" pillar.

Coverage (Layer 1) finds the right *raw* findings. Synthesis manufactures *novel
views* from findings already held, with **zero new data scans for discovery**: two
individually-flat findings whose *combination* is novel ("18% of customers are
repeat buyers" + "repeat AOV is 2.3× first-time" → "repeats drive ~40% of
revenue").

The insight lives in the **relationship between knowns**, so the structure is a
*findings graph*: nodes are findings, edges are shared join keys (a common table /
dimension / measure). This module is the PURE, deterministic half — it builds
claims, finds combinable pairs, and tags each pair with the composition operators
it is structurally eligible for. The agent's ``_phase9_synthesis`` does the
LLM articulation and — crucially — re-derives every emergent number with ONE
confirming query that passes the same guards a normal finding does. Composition is
a hypothesis; the confirming query is the proof.

Five composition operators (v1):

- ``share``         a magnitude + a rate on the same entity → contribution/importance
- ``tension``       two findings opposing on one entity → a trade-off / problem
- ``concentration`` a total + a subset's large share → fragility / leverage
- ``confound``      an aggregate + a reversing split → the headline is misleading
- ``chain``         two metrics linked via a shared segment → a causal narrative
"""
from __future__ import annotations

import re
from dataclasses import dataclass

OPERATORS = ("share", "tension", "concentration", "confound", "chain")

_TEMPORAL_DIM = re.compile(r"(date|day|week|month|quarter|year|period|time|cohort)", re.I)


@dataclass(frozen=True)
class Claim:
    """A finding reduced to the coordinates synthesis reasons over."""
    id: str
    domain: str
    finding: str
    sql: str
    tables: frozenset
    dimensions: frozenset
    measures: frozenset
    novelty: int = 3

    @property
    def is_headline(self) -> bool:
        return not self.dimensions

    @property
    def has_temporal_dim(self) -> bool:
        return any(_TEMPORAL_DIM.search(d or "") for d in self.dimensions)


@dataclass
class SynthCandidate:
    """A combinable pair of findings + the operators it is structurally eligible for."""
    a: Claim
    b: Claim
    operators: list[str]
    shared_tables: list[str]
    shared_dimensions: list[str]
    shared_measures: list[str]

    @property
    def parent_ids(self) -> tuple[str, str]:
        return (self.a.id, self.b.id)

    @property
    def score(self) -> int:
        # rank by combined novelty + operator breadth: a pair eligible for several
        # composition types, on two genuinely-novel parents, is the richest soil.
        return self.a.novelty + self.b.novelty + len(self.operators)


def to_claim(insight: dict) -> Claim:
    """Reduce a stored insight dict to a Claim, reading the `signature` block the
    explorer now stamps on each finding (falling back to top-level dimensions/measures)."""
    sig = insight.get("signature") or {}
    tables = sig.get("tables") or []
    dims = sig.get("dimensions") or insight.get("dimensions") or []
    meas = sig.get("measures") or insight.get("measures") or []
    try:
        nov = int(insight.get("novelty", 3))
    except (TypeError, ValueError):
        nov = 3
    return Claim(
        id=str(insight.get("id", "")),
        domain=str(insight.get("domain", "")),
        finding=str(insight.get("finding", "")),
        sql=str(insight.get("sql", "")),
        tables=frozenset(t.lower() for t in tables),
        dimensions=frozenset(dims),
        measures=frozenset(meas),
        novelty=nov,
    )


def _eligible_operators(a: Claim, b: Claim, shared_tables, shared_dims, shared_meas) -> list[str]:
    """Which composition operators this pair is *structurally* eligible for. The LLM
    later judges whether the operator actually produces a novel emergent claim; this
    is the cheap pre-filter that keeps us from asking the LLM about unrelated pairs."""
    ops: list[str] = []
    diff_measures = bool(a.measures and b.measures and a.measures != b.measures)
    same_measure = bool(shared_meas)

    # share: a magnitude and a (different) measure on the same entity → contribution.
    if shared_tables and diff_measures:
        ops.append("share")
    # tension: opposing measures cut by the SAME dimension on the same entity.
    if shared_dims and diff_measures:
        ops.append("tension")
    # chain: two metrics linked through a shared segment (possibly across tables).
    if shared_dims and diff_measures:
        ops.append("chain")
    # concentration: a headline total + the SAME measure broken out by a dimension.
    if same_measure and (a.is_headline ^ b.is_headline):
        ops.append("concentration")
    # confound: same measure, an aggregate/trend vs a reversing split. Eligible when
    # one side is a headline or temporal trend and the other splits the same measure.
    if same_measure and (
        (a.is_headline ^ b.is_headline)
        or (a.has_temporal_dim ^ b.has_temporal_dim)
        or (a.dimensions and b.dimensions and a.dimensions != b.dimensions)
    ):
        ops.append("confound")
    return list(dict.fromkeys(ops))


def candidate_pairs(insights, *, max_pairs: int = 24) -> list[SynthCandidate]:
    """All combinable finding-pairs, ranked, capped. Two findings are combinable when
    they share a table OR a dimension (a join key); unrelated findings are skipped.
    Self-pairs and exact-duplicate signatures are excluded."""
    claims = [to_claim(i) for i in (insights or []) if i.get("sql")]
    out: list[SynthCandidate] = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a, b = claims[i], claims[j]
            if a.id == b.id:
                continue
            shared_tables = sorted(a.tables & b.tables)
            shared_dims = sorted(a.dimensions & b.dimensions)
            shared_meas = sorted(a.measures & b.measures)
            if not (shared_tables or shared_dims):
                continue                              # no join key → not combinable
            # Skip identical-signature pairs (the dedup gate already collapses those).
            if a.tables == b.tables and a.dimensions == b.dimensions and a.measures == b.measures:
                continue
            ops = _eligible_operators(a, b, shared_tables, shared_dims, shared_meas)
            if not ops:
                continue
            key = tuple(sorted((a.id, b.id)))
            if key in seen:
                continue
            seen.add(key)
            out.append(SynthCandidate(a, b, ops, shared_tables, shared_dims, shared_meas))
    out.sort(key=lambda c: (-c.score, c.a.id, c.b.id))
    return out[:max_pairs]


def render_pair_prompt(c: SynthCandidate) -> str:
    """The articulation prompt body for one candidate pair: the two parent findings,
    their shared join keys, and the eligible operators to choose from."""
    return (
        f"FINDING A: {c.a.finding}\n"
        f"  (measures: {', '.join(sorted(c.a.measures)) or '—'}; "
        f"dimensions: {', '.join(sorted(c.a.dimensions)) or 'headline'})\n\n"
        f"FINDING B: {c.b.finding}\n"
        f"  (measures: {', '.join(sorted(c.b.measures)) or '—'}; "
        f"dimensions: {', '.join(sorted(c.b.dimensions)) or 'headline'})\n\n"
        f"SHARED JOIN KEYS — tables: {', '.join(c.shared_tables) or '—'}; "
        f"dimensions: {', '.join(c.shared_dimensions) or '—'}; "
        f"measures: {', '.join(c.shared_measures) or '—'}\n"
        f"CANDIDATE COMPOSITION TYPES: {', '.join(c.operators)}\n"
    )
