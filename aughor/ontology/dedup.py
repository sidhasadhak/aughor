"""Embedding-similarity dedup for ontology entities — surface near-duplicate entities (e.g.
``Customer`` vs ``Client``, ``Order`` vs ``SalesOrder``) so the board can offer a merge.

**DETECTION ONLY — this never mutates the graph.** A wrong merge would corrupt the ontology (and the
SQL built on it), so collapsing entities stays an explicit, user-confirmed action; this finds the
candidates via an embedding self-similarity join + connected-components clustering and returns them as
*suggestions*. Conservative by default (high threshold → only near-identical entities cluster).
Fail-open: if embeddings are unavailable (no Ollama / embed model), it returns no suggestions rather
than raising.

The clustering core (``cluster_by_similarity``) is pure — it takes precomputed vectors — so it's
trivially testable with hand-made embeddings, no model required.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

DEFAULT_THRESHOLD = 0.85  # conservative — suggestions only, so prefer fewer, higher-confidence pairs


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def cluster_by_similarity(
    embeddings: Sequence[Sequence[float]],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[list[int]]:
    """Connected-components clustering over the embedding similarity graph.

    Any pair with cosine ≥ ``threshold`` is an edge; the returned clusters are the connected
    components of size ≥ 2 (singletons have no duplicate and are omitted). Transitive: if A~B and
    B~C, then {A,B,C} cluster even if A and C aren't directly above threshold."""
    n = len(embeddings)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if cosine(embeddings[i], embeddings[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _entity_text(e: Any) -> str:
    """The text we embed for an entity — name + description + its source tables."""
    parts = [getattr(e, "display_name", "") or getattr(e, "id", "")]
    if getattr(e, "description", ""):
        parts.append(e.description)
    tables = getattr(e, "source_tables", None)
    if tables:
        parts.append(" ".join(tables))
    return " — ".join(p for p in parts if p)


def detect_duplicate_entities(
    graph: Any,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[dict]:
    """Near-duplicate entity clusters in an OntologyGraph, as merge *suggestions* (never applied).

    Returns a list of ``{"entities": [{id, display_name, source_tables}, ...], "similarity": float}``,
    strongest first. ``[]`` when there are < 2 entities or embeddings are unavailable (fail-open)."""
    entities = list(getattr(graph, "entities", {}).values())
    if len(entities) < 2:
        return []

    texts = [_entity_text(e) for e in entities]
    try:
        if embed is None:
            from aughor.semantic.embedder import embed as _embed
            embed = _embed
        vectors = embed(texts)
    except Exception:
        return []  # fail-open: no embeddings → no suggestions

    if len(vectors) != len(entities):
        return []

    clusters = cluster_by_similarity(vectors, threshold)
    out: list[dict] = []
    for cl in clusters:
        members = [entities[i] for i in cl]
        sims = [cosine(vectors[a], vectors[b]) for a in cl for b in cl if a < b]
        out.append({
            "entities": [
                {"id": e.id, "display_name": getattr(e, "display_name", e.id),
                 "source_tables": list(getattr(e, "source_tables", []))}
                for e in members
            ],
            "similarity": round(min(sims), 3) if sims else 1.0,  # weakest link, for honesty
        })
    out.sort(key=lambda c: c["similarity"], reverse=True)
    return out
