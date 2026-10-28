"""Grep-the-graph-first — read the connection knowledge graph back into the planner.

This is the mechanic Wave C exists for: before generating SQL, match the committed
per-connection graph against the question, pull the 1-hop subgraph, and inject it as a
plan-time prior. The subgraph now includes the two node types that were *write-only*
before — ``finding`` (dossiers/exploration insights) and the ``resolves`` readings —
so a question about a table Aughor already investigated finally inherits what it
learned. Every line is cited by its node/edge id, so the block the context receipt
shows names exactly what grounded the plan.

Gated behind ``graph.readback`` (default off): off ⇒ empty string, zero prompt cost,
byte-identical. The last run's cited node ids ride a contextvar so a receipt can
attribute them without threading a return value through the string-only inject sites.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

from aughor.kernel.errors import tolerate
from aughor.org.context import current_org_id

# The nodes that grounded the most recent read-back — read by the trust/context
# receipt. Defaults empty; set on every build_graph_prior call (including to empty).
_last_cited: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "aughor_graph_cited_nodes", default=[]
)

_MAX_FINDINGS = 5
_MAX_JOINS = 6
_MAX_TERMS = 5
_MAX_DECLARATIONS = 5
_TEXT_CAP = 240        # per-line text truncation
_SECTION_CAP = 2600    # whole-block char budget (token-proportional; C3 refines)


@dataclass
class GraphPrior:
    section: str = ""
    cited_node_ids: list[str] = field(default_factory=list)

    @property
    def fired(self) -> bool:
        return bool(self.section)


def last_cited_nodes() -> list[str]:
    """The graph node ids that grounded the most recent read-back (for the receipt)."""
    return list(_last_cited.get())


def publish_cited_nodes(node_ids: list[str]) -> None:
    """Republish citations produced in ANOTHER context onto this one.

    A ``ContextVar.set`` inside ``contextvars.copy_context().run(...)`` — which is exactly
    what ``ContextThreadPoolExecutor.submit`` does — never propagates back to the
    submitter. The deep-analysis path builds its priors in that pool, so the citations it
    produced were invisible to the receipt writer on the request context: the read-back
    fired, the receipt recorded nothing, and the failure was silent because an empty list
    is also what "the flag is off" looks like.

    A worker reads :func:`last_cited_nodes` inside its own context and hands the ids back
    through its return value; the submitter calls this. Explicit and one-directional —
    nothing here reaches across a context boundary by itself.
    """
    if node_ids:
        _last_cited.set(list(node_ids))


def _clip(text: str, cap: int = _TEXT_CAP) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= cap else t[: cap - 1] + "…"


def build_graph_prior(
    question: str, connection_id: str, *, org_id: str = "", top_k: int = 6,
    max_chars: int = _SECTION_CAP,
) -> GraphPrior:
    """Assemble the CONNECTION GRAPH prior for a question. Always on (flag endgame
    Wave 5, 2026-08-06 — `graph.readback` hardwired: we finally USE what we know;
    prompt-only cost, post-validated by its budgeted grid). Empty (no section, no
    citations) when no graph is built for the connection or nothing matches — so a
    caller can inject it unconditionally at zero cost. ``max_chars`` is the
    token-proportional budget the injected slice must respect (C3)."""
    _last_cited.set([])
    try:
        return _build(question, connection_id, org_id or current_org_id(), top_k, max_chars)
    except Exception as exc:
        tolerate(exc, "context-graph read-back is best-effort; the plan proceeds "
                      "without it rather than failing",
                 counter="context_graph.readback")
        return GraphPrior()


def _build(question: str, connection_id: str, org_id: str, top_k: int,
           max_chars: int = _SECTION_CAP) -> GraphPrior:
    from aughor.ontology.context_graph_search import merge_graphs, one_hop, search_graph
    from aughor.ontology.context_graph_store import graphs_for_connection
    from aughor.ontology.graph_warrant import warrant_of_edge, warrant_of_node

    cg = merge_graphs(graphs_for_connection(org_id, connection_id))   # rebuilt on demand (C3)
    if cg is None or not cg.nodes:
        return GraphPrior()

    seeds = search_graph(cg, question, top_k=top_k)
    if not seeds:
        return GraphPrior()

    nodes, edges = one_hop(cg, [n.id for n, _ in seeds])
    # G5: trim by clearance HERE, at retrieval — a blocked fact must never reach the
    # prompt. Once it is in the context window the model may repeat it, and a redaction
    # applied to the output is a redaction applied after the leak.
    nodes, edges, governance_notice = trim_graph_by_clearance(
        nodes, edges, connection_id=connection_id,
        schema_name=getattr(cg, "schema_name", "") or "", graph=cg)
    by_id = {n.id: n for n in nodes}
    cited: list[str] = []

    tables = [n for n in nodes if n.kind == "table"]
    findings = [n for n in nodes if n.kind == "finding"]
    terms = [n for n in nodes if n.kind == "glossary_term"]
    declarations = [n for n in nodes if n.kind == "declaration"]     # FA-1
    joins = [e for e in edges if e.kind == "joins_on"]
    resolves = [e for e in edges if e.kind == "resolves"]

    lines: list[str] = [
        "CONNECTION GRAPH — facts this database has already established about the "
        "entities in your question (treat as ground truth; each is auditable by its "
        "[id]):",
    ]

    if tables:
        names = ", ".join(t.label for t in tables[:8])
        lines.append(f"\nRelevant entities: {names}")
        cited += [t.id for t in tables[:8]]

    if joins:
        lines.append("\nJoins between these entities — each states the evidence behind it, "
                     "so a measured join and a name match are not read as equal claims:")
        for e in joins[:_MAX_JOINS]:
            frm = by_id.get(e.from_id)
            to = by_id.get(e.to_id)
            if not (frm and to):
                continue
            v = warrant_of_edge(e)
            lines.append(f"  • {frm.label} → {to.label}  "
                         f"[{v.warrant}: {v.detail}]  [{e.id}]")
            cited.append(e.id)

    if findings:
        lines.append("\nFindings already established on these entities (from prior "
                     "investigations — do NOT re-derive; build on them):")
        for f in findings[:_MAX_FINDINGS]:
            v = warrant_of_node(f)
            lines.append(f'  • "{_clip(f.summary or f.label)}"  [{f.id}] '
                         f"({v.warrant}: {v.detail})")
            cited.append(f.id)

    if terms or resolves:
        lines.append("\nResolved meanings on this connection (settled earlier — use "
                     "these exact readings):")
        seen: set[str] = set()
        for e in resolves[:_MAX_TERMS]:
            src = by_id.get(e.from_id)
            if src and src.id not in seen:
                seen.add(src.id)
                lines.append(f'  • "{src.label}" = {_clip(src.summary or "(resolved)")}  '
                             f"[{src.id}]")
                cited.append(src.id)
        for t in terms[:_MAX_TERMS]:
            if t.id in seen or not t.summary:
                continue
            lines.append(f'  • "{t.label}" = {_clip(t.summary)}  [{t.id}]')
            cited.append(t.id)

    if declarations:
        lines.append("\nDeclared on these entities (published — read them by these names):")
        for d in declarations[:_MAX_DECLARATIONS]:
            what = str(d.data.get("decl_kind") or "").replace("_", " ")
            about = ", ".join(d.data.get("entities") or [])
            said = _clip(d.summary or d.data.get("detail") or "", _TEXT_CAP // 2)
            lines.append(f'  • {what} "{d.label}" on {about}' + (f" — {said}" if said else "") + f"  [{d.id}]")
            cited.append(d.id)
        if len(declarations) > _MAX_DECLARATIONS:
            lines.append(f"  … and {len(declarations) - _MAX_DECLARATIONS} more declared here")

    # A block with only the header (no tables/joins/findings/terms matched the seeds)
    # is not worth injecting — UNLESS governance withheld everything, in which case the
    # empty slice is exactly the thing that must not pass silently: an answer that comes
    # back thin because it was trimmed reads identically to one that found nothing, and
    # that is the anti-pattern this wave exists to refuse.
    if len(lines) <= 1:
        if governance_notice:
            return GraphPrior(section=governance_notice + "\n")
        return GraphPrior()

    if governance_notice:
        lines.append("\n" + governance_notice)

    section = "\n".join(lines)
    if len(section) > max_chars:
        section = section[:max_chars].rstrip() + "\n  … (graph slice truncated to budget)"
    section += "\n"

    # de-dup citations preserving order
    cited = list(dict.fromkeys(cited))
    _last_cited.set(cited)
    return GraphPrior(section=section, cited_node_ids=cited)


def build_graph_prior_section(question: str, connection_id: str, **kw) -> str:
    """Convenience: just the prompt text (empty when nothing applies)."""
    return build_graph_prior(question, connection_id, **kw).section


#: The edges along which one node rests on another: a metric's formula reads a table, a finding's SQL reads one, a
#: brief cites a finding, a settled reading resolves a term. Walked outward when deciding which tables a node is about.
#: A table beside a table (`joins_on`) and a glossary term whose name equals a metric's (`defines`) are not walked: a
#: join is decided by each of its ends, and a name match is a coincidence about two different tables.
_RESTS_ON = frozenset({"derived_from", "grounded_in", "resolves"})
_WALK_DEPTH = 3


def _field(obj, name: str):
    """A field of a graph node or edge, whether it is the model or the plain dict a door hands out."""
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


class _TablesBehind:
    """Which physical tables each node of one graph is about — the index one trim reads, built once per call."""

    def __init__(self, graph=None):
        nodes = _field(graph, "nodes") if graph is not None else None
        self.nodes: dict = dict(nodes) if isinstance(nodes, dict) else {
            _field(n, "id"): n for n in (nodes or [])}
        edges = _field(graph, "edges") if graph is not None else None
        self.out: dict[str, list[str]] = {}
        for e in (edges.values() if isinstance(edges, dict) else (edges or [])):
            if _field(e, "kind") in _RESTS_ON:
                self.out.setdefault(_field(e, "from_id"), []).append(_field(e, "to_id"))

    def own(self, node) -> list[str]:
        """The tables a node names itself. A table node's are its BACKING tables, not its label: the label is the
        entity's display name ("Return") and the securable names the physical table ("returns") — resolving from the
        label matched nothing, and the trim never fired on a real graph."""
        kind, data = _field(node, "kind"), _field(node, "data") or {}
        if kind in ("table", "declaration"):
            return list(data.get("source_tables") or [])
        if kind in ("metric", "finding"):
            return list(data.get("tables") or [])
        if kind == "glossary_term":
            return [data["table"]] if data.get("table") else []
        if kind == "domain":
            return [t for m in (data.get("members") or []) if m in self.nodes
                    for t in ((_field(self.nodes[m], "data") or {}).get("source_tables") or [])]
        return []

    def of(self, node) -> list[str]:
        """The tables a node is about: its own, and those of every node it rests on, a few edges out."""
        tables = self.own(node)
        seen, frontier = {_field(node, "id")}, [_field(node, "id")]
        for _ in range(_WALK_DEPTH):
            frontier = [t for f in frontier for t in self.out.get(f, []) if t not in seen and t in self.nodes]
            seen.update(frontier)
            for nid in frontier:
                tables += self.own(self.nodes[nid])
        return list(dict.fromkeys(str(t) for t in tables if t))


def trim_graph_by_clearance(nodes, edges=(), *, connection_id: str, schema_name: str, graph=None):
    """Wave G5 — drop the nodes the caller lacks clearance for, plus every edge touching them.

    Returns ``(nodes, edges, notice)``. The notice is empty when nothing was withheld, and is a one-line, out-of-band
    sentence otherwise — never a silent thinning.

    A node is withheld when ANY table it is about is: a table node on its backing tables (an entity can have several,
    and showing one whose backing table is restricted shows the restricted thing), a metric, finding, term or
    declaration on the tables it names, and with ``graph`` every node on what it rests on — a brief on the findings it
    cites. Sweeping the edges alone left such a node standing with its text intact. Nodes are the graph's models or
    the plain dicts a door hands out. An untagged securable is always allowed, so a deployment that tags nothing sees
    no trimming.
    """
    from aughor.govern.retrieval_trim import (
        caller_clearances,
        partition,
        securable_for_table,
        sweep_edges,
    )
    from aughor.govern.tags import check as tag_check

    behind = _TablesBehind(graph)
    decided: dict = {}

    def _check(securable, held):
        if securable not in decided:            # one table under many nodes is looked up once a call
            decided[securable] = tag_check(securable, held)
        return decided[securable]

    def _securables(node):
        return [securable_for_table(connection_id, schema_name, t) for t in behind.of(node)] or None

    result = partition(list(nodes), _securables, caller_clearances(), check=_check)
    if not result.trimmed:
        return nodes, edges, ""

    kept_ids = {_field(n, "id") for n in result.kept}
    return result.kept, sweep_edges(list(edges), kept_ids), result.notice()
