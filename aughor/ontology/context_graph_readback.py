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


def _clip(text: str, cap: int = _TEXT_CAP) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= cap else t[: cap - 1] + "…"


def build_graph_prior(
    question: str, connection_id: str, *, org_id: str = "", top_k: int = 6
) -> GraphPrior:
    """Assemble the CONNECTION GRAPH prior for a question. Empty (no section, no
    citations) when the flag is off, no graph is built for the connection, or nothing
    matches — so a caller can inject it unconditionally at zero cost."""
    _last_cited.set([])
    if not graph_readback_enabled():
        return GraphPrior()

    try:
        return _build(question, connection_id, org_id or current_org_id(), top_k)
    except Exception as exc:
        tolerate(exc, "context-graph read-back is best-effort; the plan proceeds "
                      "without it rather than failing",
                 counter="context_graph.readback")
        return GraphPrior()


def _build(question: str, connection_id: str, org_id: str, top_k: int) -> GraphPrior:
    from aughor.ontology.context_graph_search import merge_graphs, one_hop, search_graph
    from aughor.ontology.context_graph_store import load_graphs_for_connection

    cg = merge_graphs(load_graphs_for_connection(org_id, connection_id))
    if cg is None or not cg.nodes:
        return GraphPrior()

    seeds = search_graph(cg, question, top_k=top_k)
    if not seeds:
        return GraphPrior()

    nodes, edges = one_hop(cg, [n.id for n, _ in seeds])
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
        lines.append("\nVerified joins (measured value-domain overlap — real, probed "
                     "confidence, not a guess):")
        for e in joins[:_MAX_JOINS]:
            frm = by_id.get(e.from_id)
            to = by_id.get(e.to_id)
            if not (frm and to):
                continue
            m = e.provenance.measured
            conf = f"overlap {m:.0%}" if m is not None else "unprobed"
            lines.append(f"  • {frm.label} → {to.label}  ({conf}, "
                         f"{e.provenance.note.split()[-1] if e.provenance.note else ''})  [{e.id}]")
            cited.append(e.id)

    if findings:
        lines.append("\nFindings already established on these entities (from prior "
                     "investigations — do NOT re-derive; build on them):")
        for f in findings[:_MAX_FINDINGS]:
            src = f.provenance.source
            lines.append(f'  • "{_clip(f.summary or f.label)}"  [{f.id}] '
                         f"(source: {src})")
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
    # is not worth injecting.
    if len(lines) <= 1:
        return GraphPrior()

    section = "\n".join(lines)
    if len(section) > _SECTION_CAP:
        section = section[:_SECTION_CAP].rstrip() + "\n  … (graph slice truncated to budget)"
    section += "\n"

    # de-dup citations preserving order
    cited = list(dict.fromkeys(cited))
    _last_cited.set(cited)
    return GraphPrior(section=section, cited_node_ids=cited)


def build_graph_prior_section(question: str, connection_id: str, **kw) -> str:
    """Convenience: just the prompt text (empty when nothing applies)."""
    return build_graph_prior(question, connection_id, **kw).section
