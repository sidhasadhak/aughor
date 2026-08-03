"""Wave G7 — what depends on this, answered from lineage rather than a maintained list.

**What V5 already solved, and what it did not.** The purge cascade is registry-driven:
stores register hooks in ``kernel/registries/purge_hooks`` and the orchestrator runs them,
so deleting a connection no longer depends on somebody remembering to extend a list. That
is the "not a hand-maintained list" half, and it is done.

What it does not answer is *lineage*: the hooks are keyed by connection, schema or
investigation, so they purge everything under a connection but cannot say **what
specifically was derived from one table**. Dropping a single table today removes the table
and leaves every finding, metric and brief that was derived from it in place, still
asserting numbers computed from data that no longer exists.

The graph already records this. ``grounded_in`` edges point finding → table, and
``derived_from`` edges point metric → table and brief → finding. That is a lineage
DAG nobody was querying. This module walks it.

**Reporting, not deleting.** :func:`dependents_of` answers the question; what to do about
the answer is the caller's decision, and for findings the answer is already settled —
C1's supersede-not-delete rule, and N3b marks a finding whose grounding vanished as stale
rather than removing it. A lineage walk that deleted would quietly become the most
destructive code path in the platform, reachable from a single table drop.

**Depth is bounded and declared.** Lineage is a DAG in principle and a graph in practice;
an unbounded walk over a cyclic edge set hangs a delete preview. The bound is stated, the
visited set is tracked, and truncation is REPORTED rather than silently returning a short
answer that reads as "nothing else depends on this".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Edge kinds that mean "the source is derived from the target". Walked in reverse: given
#: a table, find what points AT it.
LINEAGE_EDGES: frozenset[str] = frozenset({"grounded_in", "derived_from"})

#: How many hops a dependency walk follows. A brief derives from a finding which grounds
#: in a table — three levels — so 4 covers the shapes that exist with room to spare.
MAX_DEPTH = 4


@dataclass
class Dependent:
    """One node downstream of the thing being asked about.

    ``site`` is Wave P4's addition: not just *that* this finding depends on the table, but
    **the expression that would break** — the line of its SQL that names the table, or the
    metric formula that reads it. A dependency list without sites tells a reviewer which
    artifacts to open; a list with them tells them what to look at once they are open, and
    it is the difference between a report and a work item.
    """

    node_id: str
    kind: str
    label: str
    depth: int
    via: str            # the edge kind that connected it
    site: str = ""      # the expression in THIS node that references the target
    site_kind: str = ""  # sql | formula | citation — what kind of expression `site` is
    site_line: int = 0   # 1-based line within that expression, 0 when not applicable

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "kind": self.kind, "label": self.label,
                "depth": self.depth, "via": self.via, "site": self.site,
                "site_kind": self.site_kind, "site_line": self.site_line}


def _site_of(node, target_label: str, target_tables: list) -> tuple[str, str, int]:
    """The expression inside ``node`` that references the target — ``(site, kind, line)``.

    Deliberately literal: it reports the line of SQL that NAMES the table, found by
    scanning the text this node already carries. No parsing, no inference — a wrong guess
    about which expression breaks is worse than none, because a reviewer would check the
    wrong line and conclude the dependency was fine.
    """
    data = (getattr(node, "data", None) or {})
    names = {str(t).split(".")[-1].lower() for t in (target_tables or []) if t}
    if target_label:
        names.add(str(target_label).split(".")[-1].lower())
    names = {n for n in names if n}

    for key, kind in (("sql", "sql"), ("formula_sql", "formula")):
        text = str(data.get(key) or "")
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            if any(n in low for n in names):
                return line.strip()[:200], kind, i
        # Referenced by the edge but not visibly by name — report the expression itself
        # rather than claiming a line we did not find.
        return text.strip().splitlines()[0][:200] if text.strip() else "", kind, 0

    if getattr(node, "kind", "") == "brief":
        return "cites this finding", "citation", 0
    return "", "", 0


@dataclass
class LineageReport:
    """What depends on a node, and whether the walk saw all of it."""

    root: str
    dependents: list[Dependent] = field(default_factory=list)
    truncated: bool = False

    @property
    def counts_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.dependents:
            out[d.kind] = out.get(d.kind, 0) + 1
        return out

    def summary(self) -> str:
        """A sentence for a delete preview. Says 'at least' when the walk was truncated,
        because a bounded count presented as exact is how a preview under-reports what a
        deletion will orphan."""
        if not self.dependents:
            return f"Nothing in the graph is derived from {self.root}."
        parts = ", ".join(f"{n} {kind}" for kind, n in sorted(self.counts_by_kind.items()))
        prefix = "At least " if self.truncated else ""
        return (f"{prefix}{len(self.dependents)} artifact(s) derive from {self.root}: "
                f"{parts}. They are reported, not removed.")

    def to_dict(self) -> dict:
        return {"root": self.root, "truncated": self.truncated,
                "counts_by_kind": self.counts_by_kind,
                "summary": self.summary(),
                "dependents": [d.to_dict() for d in self.dependents]}


def dependents_of(graph, node_id: str, *, max_depth: int = MAX_DEPTH) -> LineageReport:
    """Everything downstream of ``node_id``, walking lineage edges in reverse.

    Pure over an already-loaded graph, so the walk is testable without a store.
    """
    report = LineageReport(root=node_id)
    if graph is None or not getattr(graph, "nodes", None):
        return report

    nodes = graph.nodes if isinstance(graph.nodes, dict) else {
        n.id: n for n in graph.nodes}
    edges = list(graph.edges.values() if isinstance(graph.edges, dict) else graph.edges)

    # Reverse index: target → [(source, kind)]. Built once; a per-hop scan over every edge
    # turns a delete preview on a large graph into a visible pause.
    incoming: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        if getattr(e, "kind", "") in LINEAGE_EDGES:
            incoming.setdefault(e.to_id, []).append((e.from_id, e.kind))

    seen: set[str] = {node_id}
    frontier = [node_id]
    for depth in range(1, max_depth + 1):
        nxt: list[str] = []
        for target in frontier:
            tnode = nodes.get(target)
            t_label = getattr(tnode, "label", "") if tnode is not None else ""
            t_tables = ((getattr(tnode, "data", None) or {}).get("source_tables") or []
                        if tnode is not None else [])
            for source, kind in incoming.get(target, []):
                if source in seen:
                    continue
                seen.add(source)
                node = nodes.get(source)
                if node is None:
                    continue
                site, site_kind, site_line = _site_of(node, t_label, t_tables)
                report.dependents.append(Dependent(
                    node_id=source, kind=getattr(node, "kind", ""),
                    label=getattr(node, "label", "") or source, depth=depth, via=kind,
                    site=site, site_kind=site_kind, site_line=site_line))
                nxt.append(source)
        frontier = nxt
        if not frontier:
            break
    else:
        # Loop completed without exhausting the frontier — there is more out there.
        report.truncated = bool(frontier)

    return report


def dependents_of_table(
    connection_id: str, table: str, *, org_id: str = "", schema_name: Optional[str] = None,
) -> LineageReport:
    """Store-backed: what the committed graph says depends on one table.

    Degrades to an empty report rather than raising — a delete preview that fails because
    lineage was unavailable is worse than one that says it found nothing, provided it is
    the caller's job to say which it was. :attr:`LineageReport.dependents` being empty on
    a missing graph is indistinguishable from genuinely nothing, so callers that need the
    distinction should check whether a graph exists first.
    """
    try:
        from aughor.ontology.context_graph_search import merge_graphs
        from aughor.ontology.context_graph_store import load_graphs_for_connection
        from aughor.org.context import current_org_id

        graph = merge_graphs(
            load_graphs_for_connection(org_id or current_org_id(), connection_id))
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "lineage lookup is best-effort; the caller proceeds without it",
                 counter="govern.lineage")
        return LineageReport(root=table)

    if graph is None:
        return LineageReport(root=table)

    bare = str(table or "").split(".")[-1].lower()
    root_id = None
    nodes = graph.nodes if isinstance(graph.nodes, dict) else {n.id: n for n in graph.nodes}
    for nid, node in nodes.items():
        if getattr(node, "kind", "") != "table":
            continue
        sources = (getattr(node, "data", None) or {}).get("source_tables") or []
        if bare in {str(s).split(".")[-1].lower() for s in sources}:
            root_id = nid
            break
    if root_id is None:
        return LineageReport(root=table)

    report = dependents_of(graph, root_id)
    report.root = table
    return report
