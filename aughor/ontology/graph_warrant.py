"""The warrant class — what kind of evidence stands behind a node or edge (Wave P2).

Every node and edge in the connection graph already carries :class:`Provenance` (J4).
What it does *not* carry is a comparable answer to the question a reader actually asks:
**how do you know that?** ``source="join_guard"`` and ``source="glossary"`` are origins,
not strengths, and a reader cannot rank them without knowing the codebase.

This module derives five ordered warrant classes from the provenance that is already
there:

    measured  — a number was read off the data (a probed value-domain overlap, a
                containment fraction, an ambiguity resolved by probing the warehouse)
    human     — a person asserted it (a reviewer verdict, a user's resolution)
    declared  — a definitional store or the source system states it (schema, a governed
                metric's formula, a written glossary definition, a declared foreign key)
    derived   — the platform computed it from executed SQL (findings, dossiers, evidence
                claims, briefs)
    inferred  — a name or shape coincidence with nothing probed behind it (an unprobed
                name-matched join, a glossary term whose name equals a metric's, an
                enricher's domain grouping, an auto-seeded description)

**It is derived, never stored.** The verdict is computed from fields the artifact
already holds, so it applies to graphs committed long before this module existed and can
never drift from the provenance it describes — the same discipline as the reflection
sidecar in the Graphify study (`docs/GRAPHIFY_STUDY_2026-08-04.md`): experiential and
derived layers are merged at read time, never stamped into the structural truth.

The two rules that carry the weight, and why they are worth the extra code:

1. **A measurement is decided by the NUMBER, not the source name.** A ``join_guard``
   edge with ``measured=None`` is an *unprobed* join — the guard named it, nothing
   measured it. Reading the source name alone would promote it to ``measured`` and
   report a guess as a probe. (This is the proxy-for-the-real-measure trap, which this
   codebase has now caught four times.)
2. **An ambiguity resolution's tier is part of its evidence.** ``resolution_source=probe``
   means the warehouse was queried; ``user`` and ``verdict`` mean a person decided. Those
   are different warrants and collapsing them loses the distinction the ledger paid to
   record.

Both facts live in ``Provenance.note`` as ``key=value`` pairs written by the projection.
Parsing our own structured emission is a guard whose key can stop matching, so
``tests/unit/test_graph_warrant.py`` pins each one by running the REAL projection and
asserting the field is still found — a rot guard, in the same family as the contract
scanner's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

Warrant = Literal["measured", "human", "declared", "derived", "inferred"]

# Strongest → weakest. The order is the product claim: a measured edge outranks a
# declared one, which outranks a name coincidence.
WARRANT_ORDER: tuple[Warrant, ...] = (
    "measured", "human", "declared", "derived", "inferred",
)

WARRANT_LABEL: dict[Warrant, str] = {
    "measured": "Measured",
    "human": "Human",
    "declared": "Declared",
    "derived": "Derived",
    "inferred": "Inferred",
}

# One line each, written for a reader who has never seen the codebase — the tooltip text.
WARRANT_MEANING: dict[Warrant, str] = {
    "measured": "A number read off your data.",
    "human": "A person asserted this.",
    "declared": "Your schema, dbt, or a written definition states this.",
    "derived": "Computed by Aughor from SQL it ran.",
    "inferred": "A name or shape match — nothing probed it.",
}

# The default class per provenance source. Sources whose warrant depends on the
# EVIDENCE rather than the origin (join_guard, ambiguity_ledger, glossary) are resolved
# by the rules below and deliberately absent from this table.
_BY_SOURCE: dict[str, Warrant] = {
    "ontology.entity": "declared",     # the warehouse's own schema
    "ontology.metric": "declared",     # a governed formula, declared by its owner
    "ontology.domain": "inferred",     # an enricher's grouping — no measurement
    "metrics_catalog": "declared",
    "dossier": "derived",              # a finding's captured derivation
    "exploration": "derived",
    "evidence_ledger": "derived",      # the CLAIM is derived; its self-confidence is banned (J4)
    "briefing": "derived",
}

# Edge kinds whose construction rule fixes the warrant regardless of source. `defines`
# is emitted on exact case-folded name equality between a glossary column and a metric
# (`context_graph._project_glossary_terms`) — a coincidence until someone confirms it.
_BY_EDGE_KIND: dict[str, Warrant] = {
    "defines": "inferred",
}

_NOTE_FIELD = re.compile(r"(?:^|\s)(?P<key>[a-z_]+)=(?P<value>[^\s]+)")


def note_field(note: str, key: str) -> Optional[str]:
    """Read a ``key=value`` field out of a provenance note. ``None`` when absent.

    The projection writes notes like ``value_overlap=0.983 join_confidence=verified``
    and ``resolution_source=probe``. Pinned by the rot-guard tests: if a projection ever
    stops emitting the field, those fail rather than this silently returning ``None`` and
    downgrading every edge to the weakest class.
    """
    for m in _NOTE_FIELD.finditer(note or ""):
        if m.group("key") == key:
            return m.group("value")
    return None


@dataclass(frozen=True)
class WarrantVerdict:
    """The warrant class plus the specific evidence phrase behind it."""

    warrant: Warrant
    detail: str = ""

    def to_dict(self) -> dict:
        return {"warrant": self.warrant, "detail": self.detail,
                "label": WARRANT_LABEL[self.warrant]}


def warrant_for(provenance, *, edge_kind: str = "", node_data: Optional[dict] = None
                ) -> WarrantVerdict:
    """The warrant class for one node or edge. Never raises; unknown ⇒ ``inferred``.

    ``edge_kind`` fixes the class for edges whose construction rule is itself the
    evidence (see :data:`_BY_EDGE_KIND`). ``node_data`` lets a glossary term declare
    itself auto-seeded.
    """
    source = str(getattr(provenance, "source", "") or "")
    note = str(getattr(provenance, "note", "") or "")
    measured = getattr(provenance, "measured", None)

    # 1. A real number outranks everything — but ONLY when it is actually a number.
    #    A non-numeric `measured` (a string, a bool, a sentinel) is NOT a measurement, and
    #    an except-branch that returned "measured" anyway would be this module's own rule 1
    #    broken in the one place it is enforced. `bool` is excluded explicitly because it
    #    is an int subclass: `measured=True` would otherwise render as "100% overlap".
    if measured is not None and not isinstance(measured, bool):
        pct = None
        try:
            pct = f"{float(measured):.0%}"
        except (TypeError, ValueError):
            pct = None
        if pct is not None:
            if source == "join_guard":
                return WarrantVerdict("measured", f"{pct} of key values overlap")
            return WarrantVerdict("measured", pct)
        # Fall through: a non-numeric value is classified by its SOURCE below, exactly as
        # if no measurement had been recorded — which is the truth of the matter.

    # 2. An ambiguity resolution's tier IS its warrant.
    if source == "ambiguity_ledger":
        tier = (note_field(note, "resolution_source") or "").strip().lower()
        if tier == "probe":
            return WarrantVerdict("measured", "settled by probing the data")
        if tier == "verdict":
            return WarrantVerdict("human", "settled by a reviewer's verdict")
        if tier == "user":
            return WarrantVerdict("human", "settled by a person")
        # An absent or unrecognised tier is NOT a probe. The ledger's rows are written by
        # several paths and one of them can leave the column empty; defaulting an unknown
        # origin to the strongest class would publish a measurement nobody took.
        return WarrantVerdict("inferred", "resolved, origin not recorded")

    # 3. An unprobed join: the declaration tier decides. A declared foreign key is a real
    #    statement by the source system; a name match is a coincidence.
    if source == "join_guard":
        tier = (note_field(note, "join_confidence") or "").lower()
        if tier == "exact":
            return WarrantVerdict("declared", "declared foreign key — not yet probed")
        if tier == "verified":
            # Verified upstream but the overlap did not survive into this graph: report
            # what is here, not what the tier name promises.
            return WarrantVerdict("declared", "verified upstream — no overlap recorded here")
        return WarrantVerdict("inferred", "name match — not probed")

    # 4. Edge kinds whose construction rule is the evidence.
    if edge_kind and edge_kind in _BY_EDGE_KIND:
        return WarrantVerdict(_BY_EDGE_KIND[edge_kind], "term name equals the metric name")

    # 5. A glossary definition someone wrote vs one the autodoc seeded.
    if source == "glossary":
        if (node_data or {}).get("auto_generated"):
            return WarrantVerdict("inferred", "auto-generated description")
        return WarrantVerdict("declared", "written definition")

    known = _BY_SOURCE.get(source)
    if known:
        return WarrantVerdict(known, _SOURCE_DETAIL.get(source, ""))
    return WarrantVerdict("inferred", f"origin: {source}" if source else "")


_SOURCE_DETAIL: dict[str, str] = {
    "ontology.entity": "from the warehouse schema",
    "ontology.metric": "declared by the metric's formula",
    "ontology.domain": "grouped by the enricher",
    "metrics_catalog": "a governed metric definition",
    "dossier": "from a captured derivation",
    "exploration": "from an exploration run",
    "evidence_ledger": "from an investigation's SQL",
    "briefing": "synthesized from cited findings",
}


def warrant_of_node(node) -> WarrantVerdict:
    return warrant_for(node.provenance, node_data=getattr(node, "data", None))


def warrant_of_edge(edge) -> WarrantVerdict:
    return warrant_for(edge.provenance, edge_kind=getattr(edge, "kind", ""))


def audit(graph) -> dict:
    """The graph's honesty scorecard: how many nodes and edges stand on each warrant.

    This is the number a governance reader asks for first — not "how big is the graph"
    but "how much of it is measured, and how much is a name match". Weakest classes are
    reported alongside the strongest deliberately: a scorecard that only showed the good
    news would be the thing this wave exists to refuse.
    """
    nodes: dict[str, int] = {w: 0 for w in WARRANT_ORDER}
    edges: dict[str, int] = {w: 0 for w in WARRANT_ORDER}
    by_edge_kind: dict[str, dict[str, int]] = {}

    for n in (getattr(graph, "nodes", {}) or {}).values():
        nodes[warrant_of_node(n).warrant] += 1
    for e in (getattr(graph, "edges", {}) or {}).values():
        v = warrant_of_edge(e).warrant
        edges[v] += 1
        by_edge_kind.setdefault(e.kind, {w: 0 for w in WARRANT_ORDER})[v] += 1

    n_total, e_total = sum(nodes.values()), sum(edges.values())
    return {
        "order": list(WARRANT_ORDER),
        "labels": dict(WARRANT_LABEL),
        "meanings": dict(WARRANT_MEANING),
        "nodes": nodes,
        "edges": edges,
        "edges_by_kind": by_edge_kind,
        "totals": {"nodes": n_total, "edges": e_total},
        # The single number the panel leads with: the share of EDGES (the claims that
        # connect things, where a wrong warrant does the most damage) that were measured
        # or asserted by a person. Nodes are mostly definitional by nature, so mixing
        # them in would flatter the score.
        "edge_grounded_share": (
            round((edges["measured"] + edges["human"]) / e_total, 4) if e_total else 0.0
        ),
    }
