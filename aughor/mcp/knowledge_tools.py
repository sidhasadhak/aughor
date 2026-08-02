"""Wave S6 — the knowledge tools an external agent needs, over stores this program built.

Four reads that had no MCP surface until every wave behind them landed: the context graph
(C), the quality results store (Q3), and the trusted-query store. None of them needs new
machinery; S6 is composition, which is what the last wave in a program should mostly be.

**The clearance question is the whole risk, and it is easy to miss.** MCP is an *external
agent* surface. `search_graph` returns node labels and `describe_entity` returns a table's
columns and joins — the same table-derived facts G5 spent a wave trimming out of prompts.
An external surface that skips the trim is a bigger hole than an internal one, because its
consumer is not a person who might notice something looks wrong. So every function here
that returns table-derived data goes through :mod:`aughor.govern.retrieval_trim`, and the
scoping doc pins it as a gate.

**Withheld is said, not implied** — the same rule as everywhere else in this program. A
trimmed result carries a `notice`, because an agent receiving a short list with no
explanation will report that the data does not exist, and it will report it confidently.

Read-only throughout; no writes, no model calls.
"""
from __future__ import annotations

from typing import Any, Optional


def _trim_nodes(nodes: list, connection_id: str, schema_name: str) -> tuple[list, str]:
    """Apply G5's clearance trim to graph nodes. Returns ``(kept, notice)``.

    Governance off (the default) returns everything untouched, so this is byte-identical
    when the flag is off — the same contract every other G5 call site has.
    """

    if not nodes:
        return nodes, ""

    from aughor.govern.retrieval_trim import (
        caller_clearances,
        partition,
        securable_for_table,
    )

    def _securables(node):
        if (node.get("kind") if isinstance(node, dict) else None) != "table":
            return None
        sources = (node.get("data") or {}).get("source_tables") or []
        return [securable_for_table(connection_id, schema_name, t) for t in sources] or None

    result = partition(nodes, _securables, caller_clearances())
    return result.kept, result.notice()


def _load_graph(connection_id: str, org_id: str = ""):
    from aughor.ontology.context_graph_search import merge_graphs
    from aughor.ontology.context_graph_store import load_graphs_for_connection
    from aughor.org.context import current_org_id

    return merge_graphs(
        load_graphs_for_connection(org_id or current_org_id(), connection_id))


def _node_dict(node) -> dict:
    return {"id": node.id, "kind": node.kind, "label": node.label,
            "summary": getattr(node, "summary", "") or "",
            "data": dict(getattr(node, "data", None) or {})}


def search_graph(connection_id: str, query: str, *, limit: int = 10,
                 schema_name: str = "", org_id: str = "") -> dict:
    """Search the connection knowledge graph — tables, metrics, terms, findings.

    The read-back protocol's search, exposed. Returns what an agent should ground on
    before asking Aughor to re-derive anything.
    """
    graph = _load_graph(connection_id, org_id)
    if graph is None or not graph.nodes:
        return {"available": False, "reason": "no context graph built for this connection",
                "nodes": [], "notice": ""}

    from aughor.ontology.context_graph_search import search_graph as _search

    hits = _search(graph, query, top_k=max(1, min(int(limit), 50)))
    nodes = [_node_dict(n) for n, _ in hits]
    kept, notice = _trim_nodes(nodes, connection_id, schema_name)
    return {"available": True, "count": len(kept), "nodes": kept, "notice": notice}


def describe_entity(connection_id: str, entity: str, *, schema_name: str = "",
                    org_id: str = "") -> dict:
    """Everything the graph knows about one entity — J6's entity page, as data.

    The same slice the entity page renders, so the two cannot disagree: an agent and a
    human asking about `orders` get one answer, which is the point of a committed graph.
    """
    graph = _load_graph(connection_id, org_id)
    if graph is None or not graph.nodes:
        return {"available": False, "reason": "no context graph built for this connection"}

    wanted = str(entity or "").split(".")[-1].lower()
    match = None
    nodes = list(graph.nodes.values()) if isinstance(graph.nodes, dict) else list(graph.nodes)
    for node in nodes:
        if node.kind != "table":
            continue
        labels = {str(node.label or "").lower(), str(node.id or "").lower()}
        sources = {str(s).split(".")[-1].lower()
                   for s in (getattr(node, "data", None) or {}).get("source_tables") or []}
        if wanted in labels or wanted in sources:
            match = node
            break
    if match is None:
        return {"available": False, "reason": f"no entity {entity!r} in the graph"}

    kept, notice = _trim_nodes([_node_dict(match)], connection_id, schema_name)
    if not kept:
        # Withheld, and said so. An agent receiving "not found" would report that the table
        # does not exist — confidently, and wrongly.
        return {"available": False, "reason": "withheld by data governance",
                "notice": notice}

    edges = list(graph.edges.values() if isinstance(graph.edges, dict) else graph.edges)
    kept_ids = {match.id}
    related = []
    for e in edges:
        if e.from_id == match.id or e.to_id == match.id:
            other = e.to_id if e.from_id == match.id else e.from_id
            related.append({"edge": e.kind, "node_id": other,
                            "measured": getattr(e.provenance, "measured", None),
                            "note": getattr(e.provenance, "note", "")})
            kept_ids.add(other)
    return {"available": True, "entity": kept[0], "related": related, "notice": notice}


def get_table_health(connection_id: str, table: str = "", *,
                     org_id: Optional[str] = None) -> dict:
    """Wave Q3's health results for a table (or the whole connection).

    Includes each verdict's staleness, because a health verdict computed against
    yesterday's data is not authoritative today and an agent has no way to know that
    unless it is told.
    """
    from aughor.quality.results import latest_for_tables

    tables = [table] if table else []
    if not tables:
        return {"available": False,
                "reason": "name a table — connection-wide health needs a table list"}
    try:
        results = latest_for_tables(connection_id, tables, org_id=org_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "table health is best-effort for an external reader",
                 counter="mcp.table_health")
        return {"available": False, "reason": "health results are unavailable"}

    if not results:
        # "No checks have run" is NOT "this table is healthy", and an agent will read a
        # bare `healthy: true` as the latter.
        return {"available": True, "checked": False, "table": table, "results": [],
                "summary": "No quality checks have run for this table."}
    failing = [r for r in results if not r.passed]
    return {"available": True, "checked": True, "table": table,
            "results": [r.to_dict() for r in results],
            "failing": len(failing),
            "blocking": len([r for r in results if r.blocking]),
            "summary": (f"{len(failing)} of {len(results)} checks failing."
                        if failing else f"All {len(results)} checks passing.")}


def list_trusted_queries(connection_id: str, *, limit: int = 25) -> dict:
    """The verified query patterns for a connection, with the warrant each carries.

    The warrant is returned rather than a flat "trusted" flag, because a human-pinned
    answer and a consistency-promoted one are different claims — N1 built that distinction
    and flattening it here would throw it away at the boundary where it matters most.
    """
    try:
        from aughor.semantic.trusted_queries import list_trusted

        rows = list_trusted(connection_id)[: max(1, min(int(limit), 100))]
    except Exception as exc:
        from aughor.kernel.errors import tolerate

        tolerate(exc, "trusted queries are best-effort for an external reader",
                 counter="mcp.trusted_queries")
        return {"available": False, "queries": []}

    out: list[dict[str, Any]] = []
    for q in rows:
        tags = list(getattr(q, "tags", None) or [])
        out.append({
            "question": getattr(q, "question", ""),
            "sql": getattr(q, "sql", ""),
            "warrant": ("human_pinned" if "human_pinned" in tags
                        else ("eval_promoted" if tags else "recorded")),
            "tags": tags,
        })
    return {"available": True, "count": len(out), "queries": out}
