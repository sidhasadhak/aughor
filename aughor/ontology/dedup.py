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


def merge_entities(graph: Any, merge_ids: list[str], canonical_id: str) -> Any:
    """Merge ``merge_ids`` into ``canonical_id``, returning a NEW graph with every cross-reference
    repointed consistently — relationships (from/to, regenerated id, self-loops dropped, deduped),
    interfaces' ``implementing_entities``, metrics' / actions' ``entity``, and the three reverse maps
    (``entity_to_tables`` / ``table_to_entity`` / ``relationship_index``). The canonical entity absorbs
    the others' ``source_tables`` / ``properties`` / ``object_sets`` (deduped by name); all other fields
    are the canonical's. Deterministic, no LLM. Raises ``ValueError`` for an unknown entity id."""
    entities = getattr(graph, "entities", {})
    if canonical_id not in entities:
        raise ValueError(f"canonical entity {canonical_id!r} is not in the graph")
    unknown = [e for e in merge_ids if e not in entities]
    if unknown:
        raise ValueError(f"unknown entities: {unknown}")
    remove = set(merge_ids) - {canonical_id}
    if not remove:
        return graph  # nothing to merge

    def repoint(eid: str) -> str:
        return canonical_id if eid in remove else eid

    g = graph.model_copy(deep=True)

    # 1) entities — canonical absorbs the others' tables/properties/object-sets, then drop the rest
    canon = g.entities[canonical_id]
    tables = list(canon.source_tables)
    prop_names = {p.name for p in canon.properties}
    set_names = {s.name for s in canon.object_sets}
    for m in merge_ids:
        if m == canonical_id:
            continue
        me = g.entities[m]
        for t in me.source_tables:
            if t not in tables:
                tables.append(t)
        for p in me.properties:
            if p.name not in prop_names:
                canon.properties.append(p); prop_names.add(p.name)
        for s in me.object_sets:
            if s.name not in set_names:
                canon.object_sets.append(s); set_names.add(s.name)
    canon.source_tables = tables
    g.entities = {eid: e for eid, e in g.entities.items() if eid not in remove}
    g.entities[canonical_id] = canon

    # 2) relationships — repoint, drop self-loops, regenerate id, dedup
    new_rels: dict = {}
    for rel in graph.relationships.values():
        fe, te = repoint(rel.from_entity), repoint(rel.to_entity)
        if fe == te:
            continue  # now internal to the merged entity
        r = rel.model_copy(deep=True)
        r.from_entity, r.to_entity = fe, te
        r.id = f"{fe}_RELATES_TO_{te}"
        new_rels.setdefault(r.id, r)
    g.relationships = new_rels

    # 3) interfaces — repoint implementing_entities (dedup, preserve order)
    for iface in g.interfaces.values():
        seen: list[str] = []
        for eid in iface.implementing_entities:
            r = repoint(eid)
            if r not in seen:
                seen.append(r)
        iface.implementing_entities = seen

    # 4/5) metrics & actions — repoint .entity
    for m in g.metrics.values():
        m.entity = repoint(m.entity)
    for a in g.actions.values():
        a.entity = repoint(a.entity)

    # 6) entity_to_tables — union under canonical, drop removed keys
    e2t: dict[str, list[str]] = {}
    for eid, tbls in graph.entity_to_tables.items():
        tgt = repoint(eid)
        bucket = e2t.setdefault(tgt, [])
        for t in tbls:
            if t not in bucket:
                bucket.append(t)
    g.entity_to_tables = e2t

    # 7) table_to_entity — repoint values
    g.table_to_entity = {t: repoint(eid) for t, eid in graph.table_to_entity.items()}

    # 8) relationship_index — rebuild from the rewritten relationships
    idx: dict[str, list[str]] = {eid: [] for eid in g.entities}
    for rel in g.relationships.values():
        idx.setdefault(rel.from_entity, [])
        if rel.to_entity not in idx[rel.from_entity]:
            idx[rel.from_entity].append(rel.to_entity)
        idx.setdefault(rel.to_entity, [])
        if rel.from_entity not in idx[rel.to_entity]:
            idx[rel.to_entity].append(rel.from_entity)
    g.relationship_index = idx

    return g


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
