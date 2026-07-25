"""The connection tour — Wave C5.

A *curriculum*, not a listicle. The order is computed from graph TOPOLOGY, then (optionally)
narrated by the LLM — the pedagogy is grounded in structure, not prose vibes:

  1. **Entry point** — the highest-join-degree table (the fact/hub every other table reaches).
  2. **BFS reading order** — breadth-first from the entry, so each table is introduced right
     after a table it joins to; every step after the first names the prior step it connects to.
  3. **Standalone tables** — tables with no joins come after the connected core.
  4. **Metrics = capstone** — the governed metrics come last, each tied to the table it derives
     from: understanding the tables is the prerequisite for understanding what's measured on them.

Deterministic and LLM-free to BUILD (ties are broken by label so the order is stable). The
`narration` field is the only LLM-emitted part, filled by :func:`narrate_tour` as a narrow
emission over the already-fixed order — the model writes the connective tissue, never the sequence.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from aughor.ontology.context_graph import ContextGraph, GraphNode

_MAX_STEPS = 15


class TourStep(BaseModel):
    order: int                       # 0-based position in the reading order
    node_id: str
    kind: str                        # "table" | "metric"
    label: str
    connects_to: str | None = None   # the node_id of the PRIOR step this one builds on
    connects_to_label: str = ""
    connection: str = ""             # deterministic reason ("joins on the verified key", …)
    why: str = ""                    # deterministic one-line significance
    narration: str = ""              # LLM connective narration (empty until narrate_tour)


class Tour(BaseModel):
    connection_id: str
    schema_name: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    narrated: bool = False
    steps: list[TourStep] = Field(default_factory=list)


def _join_adjacency(cg: ContextGraph) -> dict[str, set[str]]:
    """Undirected join adjacency over table nodes (a join is a reading link either way)."""
    adj: dict[str, set[str]] = {n.id: set() for n in cg.nodes.values() if n.kind == "table"}
    for e in cg.edges.values():
        if e.kind == "joins_on" and e.from_id in adj and e.to_id in adj:
            adj[e.from_id].add(e.to_id)
            adj[e.to_id].add(e.from_id)
    return adj


def _metric_table(cg: ContextGraph, metric_id: str) -> GraphNode | None:
    """The first table a metric derives from (via a derived_from edge), by stable order."""
    targets = sorted(e.to_id for e in cg.edges.values()
                     if e.kind == "derived_from" and e.from_id == metric_id)
    for tid in targets:
        n = cg.nodes.get(tid)
        if n and n.kind == "table":
            return n
    return None


def build_tour(cg: ContextGraph, *, max_steps: int = _MAX_STEPS) -> Tour:
    """Compute the deterministic reading order. Pure topology — no LLM, ties broken by label.

    Assembly = [connected core (BFS)] + [standalone appendix] + [metrics capstone], but room
    for ALL metrics is reserved BEFORE filling table slots, so a connection with many
    standalone tables (which are the least pedagogically valuable — no joins) can never crowd
    the capstone out of a capped tour."""
    tables = sorted((n for n in cg.nodes.values() if n.kind == "table"), key=lambda n: n.label)
    core_steps: list[TourStep] = []
    standalone_steps: list[TourStep] = []
    adj = _join_adjacency(cg)
    entry_id: str | None = None

    if tables:
        # Entry = the hub: most joins, ties broken toward the alphabetically-first label (stable).
        entry = max(tables, key=lambda t: (len(adj.get(t.id, ())), _neg_label(t.label)))
        entry_id = entry.id
        # BFS from the entry; each node records the prior node that introduced it.
        parent: dict[str, str | None] = {entry.id: None}
        core_ids: list[str] = []
        q: deque[str] = deque([entry.id])
        seen = {entry.id}
        while q:
            nid = q.popleft()
            core_ids.append(nid)
            for nb in sorted(adj.get(nid, ()), key=lambda x: cg.nodes[x].label if x in cg.nodes else x):
                if nb not in seen:
                    seen.add(nb)
                    parent[nb] = nid
                    q.append(nb)
        for nid in core_ids:
            n = cg.nodes[nid]
            p = parent.get(nid)
            pnode = cg.nodes.get(p) if p else None
            deg = len(adj.get(nid, ()))
            if p is None:
                why = f"The hub of this connection — {deg} table(s) join to it. Start here."
                connection = ""
            else:
                why = f"Reached from {pnode.label if pnode else '?'} — one join out."
                connection = f"joins {pnode.label if pnode else '?'}"
            core_steps.append(TourStep(
                order=0, node_id=nid, kind="table", label=n.label,
                connects_to=p, connects_to_label=(pnode.label if pnode else ""),
                connection=connection, why=why))
        # Standalone tables (no join reached them) — the appendix, tied to the hub.
        for t in tables:
            if t.id not in seen:
                standalone_steps.append(TourStep(
                    order=0, node_id=t.id, kind="table", label=t.label,
                    connects_to=entry_id, connects_to_label=entry.label,
                    connection=f"same connection as {entry.label}",
                    why="A standalone table — no joins into the core."))

    metric_steps: list[TourStep] = []
    for m in sorted((n for n in cg.nodes.values() if n.kind == "metric"), key=lambda n: n.label):
        mt = _metric_table(cg, m.id)
        target = mt.id if mt else entry_id
        target_label = mt.label if mt else (core_steps[0].label if core_steps else "")
        metric_steps.append(TourStep(
            order=0, node_id=m.id, kind="metric", label=m.label,
            connects_to=target, connects_to_label=target_label,
            connection=f"measured on {target_label}" if target_label else "",
            why=f"The «{m.label}» metric — what this data is measured by. Derived from {target_label}."
                if target_label else f"The «{m.label}» metric."))

    # Reserve room for the whole capstone first; the core outranks the standalone appendix.
    table_budget = max(0, max_steps - len(metric_steps))
    steps = (core_steps + standalone_steps)[:table_budget] + metric_steps
    steps = steps[:max_steps]
    for i, s in enumerate(steps):
        s.order = i
    return Tour(connection_id=cg.connection_id, schema_name=cg.schema_name, steps=steps)


def _neg_label(label: str) -> tuple:
    """A sort key that makes label ASCENDING win a max() tie (so ties are broken toward the
    alphabetically-FIRST label deterministically)."""
    return tuple(-ord(c) for c in label)


# ── LLM narration (the only non-deterministic part; optional) ─────────────────

class _StepNarration(BaseModel):
    order: int
    narration: str


class _TourNarration(BaseModel):
    steps: list[_StepNarration]


def narrate_tour(tour: Tour) -> Tour:
    """Fill each step's ``narration`` with a one-sentence connective note, in a single narrow
    LLM emission over the ALREADY-FIXED order. Best-effort: on any failure the tour is returned
    unchanged (still a readable curriculum via the deterministic ``why`` lines)."""
    if not tour.steps:
        return tour
    try:
        from aughor.llm.provider import get_provider
        outline = "\n".join(
            f"{s.order}. {s.label} ({s.kind})"
            + (f" — connects to {s.connects_to_label} [{s.connection}]" if s.connects_to_label else "")
            for s in tour.steps
        )
        sys = ("You narrate a guided tour of a database, in reading order. For EACH numbered step "
               "write ONE sentence that connects it to the step before it — what it adds to the "
               "picture. Never re-order; never invent tables. Keep each sentence under 25 words.")
        resp = get_provider("narrator").complete(
            system=sys, user=f"Steps (in order):\n{outline}", response_model=_TourNarration,
            temperature=0.2)
        by_order = {s.order: s.narration for s in resp.steps}
        for s in tour.steps:
            s.narration = (by_order.get(s.order) or "").strip()
        tour.narrated = any(s.narration for s in tour.steps)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "tour narration is best-effort; the deterministic curriculum stands without it",
                 counter="context_graph.tour_narrate")
    return tour
