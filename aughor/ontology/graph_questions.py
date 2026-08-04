"""The graph's own review queue — what it knows it cannot vouch for (Wave P5).

Every other surface in this wave answers a question the user asked. This one is the
proactive half: **before any question is asked, which nodes are worth checking?** A graph
that can report its own weak points is auditable in a way one that only answers queries is
not — the user does not have to know which of 200 tables to be suspicious of.

Every item is derived from graph structure and the warrant classes (Wave P2), with no LLM
and no scoring model. The five checks, and the reason each is worth a human's minute:

1. **Unprobed joins** — a join asserted on a name match that nothing measured. This is the
   single highest-value item in the queue, because a wrong join does not error: it
   fabricates rows, and every number computed across it is wrong in a way that looks
   plausible. It is also the cheapest to settle — the value-overlap probe already exists,
   so the item carries a one-click check that turns the doubt into a measurement.
2. **Isolated tables** — a table nothing joins to. Either dead, or joined by a key nobody
   declared; both are worth knowing, and neither is visible from a table list.
3. **Contested findings** — Wave N3 marks a subject whose findings disagree on the NUMBERS
   and carries the alternatives rather than picking a winner by recency. That decision was
   deliberately left to a human; this is where the human finds it.
4. **Ungrounded findings** — a finding whose table has since vanished from the ontology
   (N3's reachability staleness). It may still be quoted by the read-back, so it needs
   retiring or re-deriving.
5. **Undocumented hubs** — a table many things join to, with no glossary definition. Its
   meaning is load-bearing for everything downstream and nobody has written it down.

**Ranking is by measurable consequence, never by a confidence number.** The rank of an
item is how many other nodes depend on the thing in doubt — a degree count, computed from
the edges. There is deliberately no severity model: a made-up 0–1 score over deterministic
facts is the self-reported confidence J4 bans, wearing a different badge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# The check a user can run to settle an item. `kind` is a stable token the UI maps to an
# action; nothing here executes anything.
CHECK_PROBE_JOIN = "probe_join"     # measure the value overlap of this join
CHECK_ASK = "ask"                   # ask the question against the connection
CHECK_REVIEW_FINDING = "review_finding"   # open the contested finding to settle it
CHECK_DEFINE = "define"             # write a glossary definition for this table
CHECK_REBUILD = "rebuild"           # the graph itself is behind

_DEFAULT_LIMIT = 50


@dataclass
class ReviewItem:
    id: str
    type: str
    question: str          # what a human is being asked to settle, in their words
    why: str               # why it matters — the consequence, not the mechanism
    subject_id: str        # the node or edge in doubt
    subject_label: str
    check: str             # one of the CHECK_* tokens
    # How many other nodes hang off the thing in doubt. The ranking key, and shown to the
    # user so they can see WHY an item is near the top.
    depends: int = 0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "question": self.question, "why": self.why,
            "subject_id": self.subject_id, "subject_label": self.subject_label,
            "check": self.check, "depends": self.depends, "detail": self.detail,
        }


def _degree(graph) -> dict[str, int]:
    deg: dict[str, int] = {}
    for e in graph.edges.values():
        deg[e.from_id] = deg.get(e.from_id, 0) + 1
        deg[e.to_id] = deg.get(e.to_id, 0) + 1
    return deg


def review_queue(graph, *, drift: Optional[dict] = None, limit: int = _DEFAULT_LIMIT) -> list[ReviewItem]:
    """The deterministic review queue for one graph. Stable order, no LLM.

    ``drift`` is the content-drift dict (`graph_freshness.content_drift`) when the caller
    has it: a graph missing what the platform has already learned is itself the first thing
    to fix, and an item about a stale graph outranks items derived FROM that stale graph.
    """
    from aughor.ontology.graph_warrant import warrant_of_edge

    items: list[ReviewItem] = []
    deg = _degree(graph)
    label = {nid: n.label for nid, n in graph.nodes.items()}

    # 0. The graph itself is behind — reported first, because every other item below was
    #    computed FROM this graph and inherits its shortfall.
    if drift and drift.get("drifted"):
        missing = drift.get("missing") or {}
        items.append(ReviewItem(
            id="graph:drift", type="graph_behind",
            question="Rebuild the knowledge graph?",
            why=drift.get("reason")
                or "The graph is missing findings or terms the platform has already learned, "
                   "so every check below is computed from an incomplete picture.",
            subject_id="", subject_label="This connection's graph",
            check=CHECK_REBUILD, depends=sum(int(v) for v in missing.values() if isinstance(v, (int, float))),
            detail={"missing": missing},
        ))

    # 1. Unprobed joins — the highest-consequence, cheapest-to-settle item.
    for e in graph.edges.values():
        if e.kind != "joins_on":
            continue
        v = warrant_of_edge(e)
        if v.warrant == "measured":
            continue
        a, b = label.get(e.from_id, e.from_id), label.get(e.to_id, e.to_id)
        declared = v.warrant == "declared"
        items.append(ReviewItem(
            id=f"join:{e.id}", type="unprobed_join",
            question=f"Do {a} and {b} really join on these keys?",
            why=("This join is declared by the schema but nothing has measured whether the "
                 "key values actually overlap." if declared else
                 "This join was matched by column NAME and nothing probed it. A wrong join "
                 "does not fail — it invents rows, and every total across it is wrong."),
            subject_id=e.id, subject_label=f"{a} → {b}",
            check=CHECK_PROBE_JOIN,
            depends=max(deg.get(e.from_id, 0), deg.get(e.to_id, 0)),
            detail={"warrant": v.warrant, "note": e.provenance.note,
                    "from_id": e.from_id, "to_id": e.to_id},
        ))

    # 2. Isolated tables.
    joined: set[str] = set()
    for e in graph.edges.values():
        if e.kind == "joins_on":
            joined.update((e.from_id, e.to_id))
    for n in graph.nodes.values():
        if n.kind != "table" or n.id in joined:
            continue
        items.append(ReviewItem(
            id=f"isolated:{n.id}", type="isolated_table",
            question=f"How does {n.label} connect to the rest of the warehouse?",
            why="Nothing joins to this table. It is either unused, or joined by a key that "
                "was never declared — and an undeclared join is one no answer can use.",
            subject_id=n.id, subject_label=n.label, check=CHECK_ASK, depends=0,
            detail={"source_tables": list((n.data or {}).get("source_tables") or [])},
        ))

    # 3 + 4. Findings that need a human: contested (N3 refused to pick a winner) and
    #        ungrounded (the table they stand on is gone).
    for n in graph.nodes.values():
        if n.kind != "finding":
            continue
        data = n.data or {}
        if data.get("contested"):
            variants = list(data.get("contested_variants") or [])
            items.append(ReviewItem(
                id=f"contested:{n.id}", type="contested_finding",
                question=f"Which reading is right: “{(n.summary or n.label)[:120]}”?",
                why=f"Two analyses of the same subject reported different numbers "
                    f"({len(variants) + 1} readings). Aughor refuses to settle that by "
                    f"recency — whether, say, a cancelled order counts as revenue is a "
                    f"business decision, not a timestamp.",
                subject_id=n.id, subject_label=(n.summary or n.label)[:80],
                check=CHECK_REVIEW_FINDING, depends=len(variants) + 1,
                detail={"variants": variants[:5]},
            ))
        if data.get("stale"):
            items.append(ReviewItem(
                id=f"stale:{n.id}", type="ungrounded_finding",
                question=f"Retire or re-derive “{(n.summary or n.label)[:120]}”?",
                why=data.get("stale_reason")
                    or "The table this finding was derived from is no longer in the "
                       "ontology, so nothing can re-check it — but it can still be quoted.",
                subject_id=n.id, subject_label=(n.summary or n.label)[:80],
                check=CHECK_REVIEW_FINDING, depends=0,
                detail={"tables": list(data.get("tables") or [])},
            ))

    # 5. Undocumented hubs — many things depend on it, nobody wrote down what it means.
    documented: set[str] = set()
    by_table_name: dict[str, str] = {}
    for n in graph.nodes.values():
        if n.kind == "table":
            for src in ((n.data or {}).get("source_tables") or []):
                by_table_name[str(src).rsplit(".", 1)[-1].strip().lower()] = n.id
    for n in graph.nodes.values():
        if n.kind == "glossary_term":
            owner = by_table_name.get(str((n.data or {}).get("table") or "").lower())
            if owner:
                documented.add(owner)
    for n in graph.nodes.values():
        if n.kind != "table" or n.id in documented or n.summary:
            continue
        d = deg.get(n.id, 0)
        if d < 2:      # a hub, not every undocumented table — the queue must stay actionable
            continue
        items.append(ReviewItem(
            id=f"undocumented:{n.id}", type="undocumented_hub",
            question=f"What does {n.label} mean, in business terms?",
            why=f"{d} other things in the graph depend on this table and nothing defines "
                f"it, so every answer that crosses it is interpreting a name.",
            subject_id=n.id, subject_label=n.label, check=CHECK_DEFINE, depends=d,
            detail={},
        ))

    # Rank by consequence, then by a stable id so the queue never reshuffles between two
    # reads of the same graph (a queue that reorders itself cannot be worked through).
    order = {"graph_behind": 0, "unprobed_join": 1, "contested_finding": 2,
             "ungrounded_finding": 3, "undocumented_hub": 4, "isolated_table": 5}
    items.sort(key=lambda i: (order.get(i.type, 9), -i.depends, i.id))
    # Coerced rather than trusted: this is a public function, and its HTTP caller's
    # default arrives as a FastAPI `Query` object whenever the handler is invoked
    # directly (as the route tests do), which sliced with a TypeError.
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = _DEFAULT_LIMIT
    return items[:max(1, n)]


def review_queue_with_total(graph, *, drift: Optional[dict] = None,
                            limit: int = _DEFAULT_LIMIT) -> tuple[list[ReviewItem], int]:
    """The queue plus how many items existed before the limit — so a caller can say so."""
    everything = review_queue(graph, drift=drift, limit=10_000_000)
    try:
        n = max(1, int(limit))
    except (TypeError, ValueError):
        n = _DEFAULT_LIMIT
    return everything[:n], len(everything)


def queue_summary(items: list[ReviewItem], *, total_found: Optional[int] = None) -> dict:
    """Counts per type — the one line a panel header shows.

    ``total_found`` is the count BEFORE the limit was applied. A queue that renders "50
    things this graph cannot vouch for" over a warehouse with 300 is under-reporting the
    very thing it exists to report, so truncation is declared rather than inferred — the
    same rule `LineageReport.summary` follows when it says "At least".
    """
    by_type: dict[str, int] = {}
    for i in items:
        by_type[i.type] = by_type.get(i.type, 0) + 1
    shown = len(items)
    found = shown if total_found is None else int(total_found)
    return {"total": shown, "total_found": found, "truncated": found > shown,
            "by_type": by_type}
