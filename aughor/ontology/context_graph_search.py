"""Search the connection knowledge graph — Wave C2 (grep-the-graph-first).

Two ranked modes, fused: a deterministic **lexical** rank (token overlap over each
node's searchable text — always available, no infrastructure) and a **vector** rank
over a per-connection Qdrant collection (wired on day one — J4). The lexical path is
the floor: if Qdrant/embeddings are unavailable the search still returns a *ranked*
result, never the unranked ``nodes[:k]`` that the connection-KB vector bug silently
degraded to. A vector failure is counted through ``tolerate`` (loud), not swallowed.

Given the matched seed nodes, :func:`one_hop` pulls the 1-hop subgraph — which is
where the previously-unread context (finding nodes, resolves edges) reaches the plan.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.kernel.errors import tolerate
from aughor.ontology.context_graph import ContextGraph, GraphNode

GRAPH_COLLECTION = "aughor_context_graph"

# Conservative floor, same spirit as trusted_queries / priors: an unrelated question
# matches nothing rather than pull irrelevant nodes into the plan.
_MIN_LEXICAL_SCORE = 0.12

_STOP = frozenset({
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by", "per",
    "each", "what", "which", "how", "many", "is", "are", "was", "were", "do",
    "does", "show", "list", "give", "me", "their", "its", "with", "that", "this",
    "why", "did", "has", "have", "over", "from", "into", "all", "get",
})


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if t not in _STOP and len(t) > 2}


def node_text(node: GraphNode) -> str:
    """The searchable text for a node — label + summary + tags + the kind-specific
    payload that carries meaning (a finding's text, a term's definition, a metric's
    formula, a table's columns)."""
    parts = [node.label, node.summary, " ".join(node.tags)]
    d = node.data or {}
    if node.kind == "table":
        parts.append(" ".join(d.get("columns", []) or []))
        parts.append(" ".join(d.get("source_tables", []) or []))
        parts.append(d.get("domain") or "")
    elif node.kind == "metric":
        parts.append(d.get("formula_sql", ""))
    elif node.kind == "finding":
        parts.append(" ".join(d.get("tables", []) or []))
    elif node.kind == "glossary_term":
        parts.append(d.get("table", ""))
        parts.append(d.get("column", ""))
        parts.append(d.get("subject", ""))
    return " ".join(p for p in parts if p)


def _scope(cg: ContextGraph) -> str:
    """The per-graph scope stamped on every Qdrant point — org|conn|schema, so one
    connection's index can neither answer for nor overwrite another's (the exact bug
    the schema retriever's scope_key fixed)."""
    return f"{cg.org_id}|{cg.connection_id}|{cg.schema_name}"


def graph_scope_filter(scope: str):
    """A Qdrant filter restricting a search to one graph's scope (or None). Defined
    here rather than reusing the schema retriever's private ``_scope_filter`` — the
    same shape, but importing another module's ``_internals`` is exactly what the
    private-cross-import ratchet forbids."""
    if not scope:
        return None
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        return Filter(must=[FieldCondition(key="scope", match=MatchValue(value=scope))])
    except Exception:
        return None


# ── lexical (always available) ────────────────────────────────────────────────

def lexical_search(cg: ContextGraph, question: str, top_k: int) -> list[tuple[GraphNode, float]]:
    qtok = _tokens(question)
    if not qtok:
        return []
    scored: list[tuple[GraphNode, float]] = []
    for n in cg.nodes.values():
        ntok = _tokens(node_text(n))
        if not ntok:
            continue
        score = len(qtok & ntok) / len(qtok)
        if score >= _MIN_LEXICAL_SCORE:
            scored.append((n, round(score, 3)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ── vector (Qdrant, wired day one) ────────────────────────────────────────────

def index_graph(cg: ContextGraph) -> int:
    """Embed every node's text into the per-connection Qdrant collection. Returns the
    number of points indexed. Raises on a genuine embed/Qdrant failure — the caller
    (C2 read-back / a build hook) decides whether to tolerate; this function does not
    silently pretend success."""
    from aughor.semantic.embedder import embed
    from aughor.semantic.vector_store import ensure_collection, upsert

    nodes = list(cg.nodes.values())
    if not nodes:
        return 0
    scope = _scope(cg)
    texts = [node_text(n) or n.label for n in nodes]
    ensure_collection(GRAPH_COLLECTION)
    vectors = embed(texts)
    points = [
        {"id": f"{scope}|{n.id}", "vector": v,
         "payload": {"node_id": n.id, "kind": n.kind, "scope": scope}}
        for n, v in zip(nodes, vectors)
    ]
    upsert(GRAPH_COLLECTION, points)
    return len(points)


def _vector_search(cg: ContextGraph, question: str, top_k: int) -> list[tuple[str, float]]:
    """Vector rank → [(node_id, score)]. Empty list when the collection is empty; may
    raise on an unreachable Qdrant/embedder (the hybrid caller counts it and falls back
    to the lexical floor)."""
    from aughor.semantic.embedder import embed_one
    from aughor.semantic.vector_store import collection_count, search

    if collection_count(GRAPH_COLLECTION) == 0:
        return []
    vec = embed_one(question)
    hits = search(GRAPH_COLLECTION, vec, top_k=top_k, query_filter=graph_scope_filter(_scope(cg)))
    out: list[tuple[str, float]] = []
    for h in hits:
        payload = h.get("payload") or {}
        nid = payload.get("node_id")
        if nid and nid in cg.nodes:
            out.append((nid, float(h.get("score", 0.0))))
    return out


# ── hybrid (the search callers use) ───────────────────────────────────────────

def search_graph(cg: ContextGraph, question: str, *, top_k: int = 6) -> list[tuple[GraphNode, float]]:
    """Hybrid search: the deterministic lexical rank always runs; the vector rank is
    fused in when Qdrant is reachable (Reciprocal Rank Fusion, k=60 — robust to the
    lexical/cosine score-scale mismatch). A vector failure is counted, not swallowed,
    and the lexical floor still stands."""
    lex = lexical_search(cg, question, top_k * 3)
    vec: list[tuple[str, float]] = []
    try:
        vec = _vector_search(cg, question, top_k * 3)
    except Exception as exc:
        tolerate(exc, "context-graph vector search is best-effort; lexical rank still "
                      "stands (never degrades to unranked)",
                 counter="context_graph.vector_search")

    # RRF over the two ranked lists, keyed by node id.
    K = 60
    fused: dict[str, float] = {}
    for rank, (node, _s) in enumerate(lex):
        fused[node.id] = fused.get(node.id, 0.0) + 1.0 / (K + rank + 1)
    for rank, (nid, _s) in enumerate(vec):
        fused[nid] = fused.get(nid, 0.0) + 1.0 / (K + rank + 1)
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [(cg.nodes[nid], round(score, 5)) for nid, score in ranked if nid in cg.nodes]


# ── subgraph ──────────────────────────────────────────────────────────────────

def one_hop(cg: ContextGraph, seed_ids: list[str]) -> tuple[list[GraphNode], list]:
    """The 1-hop subgraph around the seed nodes: every edge touching a seed, plus the
    nodes on the far end. This is where the read-back gains its reach — a matched
    `table` pulls in the `finding` nodes and `resolves` edges attached to it."""
    seed = set(seed_ids)
    edges = [e for e in cg.edges.values() if e.from_id in seed or e.to_id in seed]
    node_ids = set(seed)
    for e in edges:
        node_ids.add(e.from_id)
        node_ids.add(e.to_id)
    nodes = [cg.nodes[nid] for nid in node_ids if nid in cg.nodes]
    return nodes, edges


def merge_graphs(graphs: list[ContextGraph]) -> Optional[ContextGraph]:
    """Union several per-schema graphs of one connection into a single search space.
    Node/edge ids are kind-prefixed and unique within a graph; a collision across
    schemas keeps the first (deterministic). Returns None for an empty list."""
    graphs = [g for g in graphs if g is not None]
    if not graphs:
        return None
    if len(graphs) == 1:
        return graphs[0]
    base = graphs[0].model_copy(deep=True)
    for g in graphs[1:]:
        for nid, n in g.nodes.items():
            base.nodes.setdefault(nid, n)
        for eid, e in g.edges.items():
            base.edges.setdefault(eid, e)
    return base
