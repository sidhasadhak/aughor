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
from aughor.kernel.flags import flag_enabled
from aughor.org.context import current_org_id

# The nodes that grounded the most recent read-back — read by the trust/context
# receipt. Defaults empty; set on every build_graph_prior call (including to empty).
_last_cited: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "aughor_graph_cited_nodes", default=[]
)

_MAX_FINDINGS = 5
_MAX_JOINS = 6
_MAX_TERMS = 5
_TEXT_CAP = 240        # per-line text truncation
_SECTION_CAP = 2600    # whole-block char budget (token-proportional; C3 refines)


@dataclass
class GraphPrior:
    section: str = ""
    cited_node_ids: list[str] = field(default_factory=list)

    @property
    def fired(self) -> bool:
        return bool(self.section)


def graph_readback_enabled() -> bool:
    return flag_enabled("graph.readback")


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
    """Assemble the CONNECTION GRAPH prior for a question. Empty (no section, no
    citations) when the flag is off, no graph is built for the connection, or nothing
    matches — so a caller can inject it unconditionally at zero cost. ``max_chars`` is
    the token-proportional budget the injected slice must respect (C3)."""
    _last_cited.set([])
    if not graph_readback_enabled():
        return GraphPrior()

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
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    from aughor.ontology.graph_warrant import warrant_of_edge, warrant_of_node

    cg = merge_graphs(load_graphs_for_connection(org_id, connection_id))
    if cg is None or not cg.nodes:
        return GraphPrior()

    seeds = search_graph(cg, question, top_k=top_k)
    if not seeds:
        return GraphPrior()

    nodes, edges = one_hop(cg, [n.id for n, _ in seeds])
    # G5: trim by clearance HERE, at retrieval — a blocked fact must never reach the
    # prompt. Once it is in the context window the model may repeat it, and a redaction
    # applied to the output is a redaction applied after the leak.
    nodes, edges, governance_notice = _trim_by_clearance(
        nodes, edges, connection_id=connection_id,
        schema_name=getattr(cg, "schema_name", "") or "")
    by_id = {n.id: n for n in nodes}
    cited: list[str] = []

    tables = [n for n in nodes if n.kind == "table"]
    findings = [n for n in nodes if n.kind == "finding"]
    terms = [n for n in nodes if n.kind == "glossary_term"]
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


def _trim_by_clearance(nodes, edges, *, connection_id: str, schema_name: str):
    """Wave G5 — drop nodes the caller lacks clearance for, plus every edge touching them.

    Returns ``(nodes, edges, notice)``. The notice is empty when nothing was withheld, and
    is a one-line, out-of-band sentence otherwise — never a silent thinning.

    Only `table` nodes carry a securable today; a finding or glossary term is withheld
    transitively when the table it hangs off is, via the edge sweep. An untagged
    securable is always allowed, so a deployment that tags nothing sees no trimming.
    """
    from aughor.govern.retrieval_trim import (
        caller_clearances,
        partition,
        securable_for_table,
        sweep_edges,
    )

    def _securables(node):
        """A table node's PHYSICAL tables — not its label.

        Found by probing: the node's `label` is the ontology entity's display name
        ("Return"), while the securable names the physical table ("returns"), so
        resolving from the label silently matched nothing and the trim never fired on a
        real graph. The backing tables live in `data["source_tables"]`, and an entity can
        have several — withholding on ANY of them is the correct reading, since showing
        an entity whose backing table is restricted shows the restricted thing.
        """
        if getattr(node, "kind", "") != "table":
            return None
        sources = (getattr(node, "data", None) or {}).get("source_tables") or []
        if not sources:
            return None
        return [securable_for_table(connection_id, schema_name, t) for t in sources]

    result = partition(list(nodes), _securables, caller_clearances())
    if not result.trimmed:
        return nodes, edges, ""

    kept_ids = {n.id for n in result.kept}
    return result.kept, sweep_edges(list(edges), kept_ids), result.notice()
