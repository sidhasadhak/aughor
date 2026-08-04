"""The answer trace — every answer as a walkable subgraph (Wave P1).

The question this closes: *how was this answer generated, and can I check each piece?*
Aughor already recorded the parts — the SQL it ran, the tables that SQL read, the governed
metrics it used, the readings it applied, and (when the read-back fires) the graph nodes it
was shown. What it never did was **name them together as nodes of the graph the user can
open**, so a receipt listed bare table strings while a rich, provenance-carrying node for
each of those tables sat one lookup away.

Two design choices carry this module:

**1. It resolves at READ time, from the answer's own lineage.** Nothing new has to be
captured for a trace to exist, which means every receipt ever written already has one —
including the ones from before this wave. It also means a node that has since vanished from
the graph is reported as vanished (``present=False``) rather than silently dropped: a
finding grounded in a table that no longer exists is exactly the thing a reader must see,
the same reachability rule Wave N3 shipped for stale findings.

**2. It does not depend on the read-back flag.** ``graph.readback`` is an off-by-default
experiment, so a trace built only from ``last_cited_nodes()`` would be empty on every
production answer — both ends of a feature existing while the feature does not. The tables
the SQL actually read and the metrics it actually used are recorded on every answer and
resolve to real graph nodes, so the walk has content in the default configuration and gains
the cited nodes on top when the experiment is on.

The trace is a projection, never an authorship: every entry is derived from lineage the
answer path already wrote, and every node carries the warrant class it has in the graph
(Wave P2). No LLM writes any part of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aughor.kernel.errors import tolerate

# Why a node is in the trace — the sentence the UI shows under it. Keyed so the reason is
# a stable token, not prose a caller re-invents.
REASON_TEXT: dict[str, str] = {
    "read": "The SQL this answer ran read this table.",
    "metric": "The answer used this governed metric.",
    "cited": "The planner was shown this before writing the SQL.",
    "finding": "This answer was recorded here.",
}

# The order the UI lists reasons in — what the answer stood ON first, what it produced last.
_REASON_ORDER = ("cited", "read", "metric", "finding")


def _bare(name: str) -> str:
    return str(name).rsplit(".", 1)[-1].strip().strip('"').lower()


@dataclass
class TracedNode:
    """One graph node this answer stands on."""

    id: str
    reason: str                       # a key of REASON_TEXT
    present: bool = True              # False ⇒ named by the answer, absent from the graph now
    kind: str = ""
    label: str = ""
    summary: str = ""
    warrant: Optional[dict] = None    # P2's {warrant, detail, label}

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "label": self.label,
            "summary": self.summary, "reason": self.reason,
            "why": REASON_TEXT.get(self.reason, ""),
            "present": self.present, "warrant": self.warrant,
        }


@dataclass
class AnswerTrace:
    """The subgraph behind one answer: the nodes it stands on and how they connect."""

    connection_id: str
    nodes: list[TracedNode] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    graph_version: int = 0
    # True when the answer named things the graph does not (or no longer) contains.
    has_unresolved: bool = False

    @property
    def empty(self) -> bool:
        return not self.nodes

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "graph_version": self.graph_version,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": self.edges,
            "counts": {"nodes": len(self.nodes), "edges": len(self.edges),
                       "unresolved": sum(1 for n in self.nodes if not n.present)},
            "has_unresolved": self.has_unresolved,
        }


def build_answer_trace(
    connection_id: str,
    *,
    tables: Optional[list] = None,
    metrics: Optional[list] = None,
    cited_node_ids: Optional[list] = None,
    finding_id: str = "",
    org_id: str = "",
) -> Optional[AnswerTrace]:
    """Resolve one answer's lineage into the graph subgraph behind it.

    ``None`` when the connection has no graph at all (nothing to walk — the honest answer,
    not an empty walk that reads as "nothing grounded this"). Never raises: a trace is an
    explanation of an answer already given, so a failure here must not surface as an error
    on the answer itself.
    """
    try:
        return _build(connection_id, tables or [], metrics or [], cited_node_ids or [],
                      finding_id, org_id)
    except Exception as exc:
        tolerate(exc, "answer trace is a read-time projection; the receipt renders without it",
                 counter="answer_trace.build")
        return None


def _build(connection_id: str, tables: list, metrics: list, cited: list,
           finding_id: str, org_id: str) -> Optional[AnswerTrace]:
    from aughor.ontology.context_graph_search import merge_graphs
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    from aughor.ontology.graph_warrant import warrant_of_edge, warrant_of_node
    from aughor.org.context import current_org_id

    cg = merge_graphs(load_graphs_for_connection(org_id or current_org_id(), connection_id))
    if cg is None or not cg.nodes:
        return None

    trace = AnswerTrace(connection_id=connection_id, graph_version=getattr(cg, "version", 0))

    # Table name → the entity node that materialises it. TWO maps, because
    # `merge_graphs` unions one graph per SCHEMA: `sales.orders` and `staging.orders` both
    # reduce to the bare key `orders`, and a single flat map would silently render one
    # schema's node for the other's table — wrong label, wrong summary, wrong edges.
    #
    # `by_qualified` holds the full `schema.table` key and always wins. `by_bare` holds the
    # unqualified key and is set to None the moment a second, DIFFERENT node claims it, so
    # an ambiguous bare name resolves to nothing rather than to whichever node was
    # iterated first.
    by_qualified: dict[str, str] = {}
    by_bare: dict[str, Optional[str]] = {}

    def _claim(key: str, node_id: str) -> None:
        if not key:
            return
        if key in by_bare and by_bare[key] != node_id:
            by_bare[key] = None          # ambiguous — refuse to guess
        else:
            by_bare.setdefault(key, node_id)

    for n in cg.nodes.values():
        if n.kind != "table":
            continue
        for src in (n.data.get("source_tables") or []):
            full = str(src).strip().strip('"').lower()
            if "." in full:
                by_qualified.setdefault(full, n.id)
            _claim(_bare(src), n.id)
        _claim(_bare(n.id.split(":", 1)[-1]), n.id)
        _claim(_bare(n.label), n.id)

    def _resolve_table(name: str) -> Optional[str]:
        full = str(name).strip().strip('"').lower()
        return by_qualified.get(full) or by_bare.get(_bare(name))

    by_metric: dict[str, str] = {}
    for n in cg.nodes.values():
        if n.kind == "metric":
            by_metric.setdefault(n.label.strip().lower(), n.id)
            by_metric.setdefault(n.id.split(":", 1)[-1].strip().lower(), n.id)

    # Resolution order matters: `cited` first, so a node that was BOTH shown to the planner
    # and read by the SQL is attributed to the stronger fact (the planner saw it), and the
    # later passes do not overwrite that.
    seen: dict[str, TracedNode] = {}

    def _add(node_id: str, reason: str, *, present: bool = True, label: str = "") -> None:
        if node_id in seen:
            return
        node = cg.nodes.get(node_id)
        if node is None:
            trace.has_unresolved = True
            seen[node_id] = TracedNode(id=node_id, reason=reason, present=False,
                                       label=label or node_id)
            return
        seen[node_id] = TracedNode(
            id=node.id, reason=reason, present=present, kind=node.kind,
            label=node.label, summary=node.summary,
            warrant=warrant_of_node(node).to_dict(),
        )

    for nid in cited:
        # Edge ids also ride the citation list (the read-back cites joins by edge id); an
        # edge is not a node, and the edge sweep below picks it up on its own.
        if nid in cg.nodes:
            _add(nid, "cited")

    for t in tables:
        nid = _resolve_table(t)
        if nid:
            _add(nid, "read")
        else:
            # A table the SQL read that the graph does not model. Named honestly rather
            # than dropped — "the graph does not cover this" is a real answer to "can I
            # check every node", and silently showing 3 of 4 tables is not.
            _add(f"table:{_bare(t)}", "read", present=False, label=str(t))

    for m in metrics:
        nid = by_metric.get(str(m).strip().lower())
        if nid:
            _add(nid, "metric")

    if finding_id:
        fid = finding_id if finding_id.startswith("finding:") else f"finding:{finding_id}"
        if fid in cg.nodes:
            _add(fid, "finding")

    order = {r: i for i, r in enumerate(_REASON_ORDER)}
    trace.nodes = sorted(seen.values(),
                         key=lambda n: (order.get(n.reason, 99), not n.present, n.label))

    # The edges AMONG the traced nodes — the walk. A join between two tables this answer
    # read is the single most checkable thing on the receipt: it is where a wrong answer
    # comes from, and it now arrives with the warrant that stands behind it.
    ids = {n.id for n in trace.nodes if n.present}
    for e in cg.edges.values():
        if e.from_id in ids and e.to_id in ids:
            trace.edges.append({
                "id": e.id, "kind": e.kind, "from_id": e.from_id, "to_id": e.to_id,
                "label": e.label, "warrant": warrant_of_edge(e).to_dict(),
            })
    trace.edges.sort(key=lambda e: e["id"])
    return trace


def trace_from_receipt(receipt: dict, *, org_id: str = "") -> Optional[dict]:
    """The trace for a PUBLIC receipt dict — the one call a route needs.

    Reads the receipt's own fields (`input_tables`, the metrics it used, the graph nodes it
    cited, its own id) so the trace is an explanation of that exact answer rather than a
    fresh lookup that might resolve differently.
    """
    if not receipt:
        return None
    conn = (receipt.get("connection") or {}).get("id") or ""
    if not conn:
        return None
    # `metrics.used` is a list of NAMES, while its sibling `drifted` is a list of
    # {metric, detail} dicts (`trust.receipt._metrics_from_lineage`). Both shapes are read
    # here rather than assuming one: assuming dicts raised on every real receipt while the
    # unit test — which happened to pass an empty list — stayed green.
    metrics_used = [
        m.get("metric") if isinstance(m, dict) else m
        for m in ((receipt.get("metrics") or {}).get("used") or [])
    ]
    metrics_used = [m for m in metrics_used if m]
    trace = build_answer_trace(
        conn,
        tables=list(receipt.get("input_tables") or []),
        metrics=metrics_used,
        cited_node_ids=list(receipt.get("grounded_in_graph") or []),
        finding_id=receipt.get("id") or "",
        org_id=org_id,
    )
    return trace.to_dict() if trace and not trace.empty else None
