"""Embedding-similarity dedup for ontology entities — surface near-duplicate entities (e.g.
``Customer`` vs ``Client``, ``Order`` vs ``SalesOrder``) so the board can offer a merge, and plan the
merge a person confirms.

**DETECTION NEVER MUTATES THE GRAPH.** A wrong merge would corrupt the ontology (and the SQL built on
it), so collapsing entities stays an explicit, user-confirmed action; this finds the candidates via an
embedding self-similarity join + connected-components clustering and returns them as *suggestions*.
Conservative by default (high threshold → only near-identical entities cluster). Fail-open: if
embeddings are unavailable (no Ollama / embed model), it returns no suggestions rather than raising.

**A merge is "two tables, one binding"** (ROADMAP §3.15): the survivor binds each other type's table on
its key, counted one row per object, and the other type becomes its PART (`aughor.ontology.parts`).
Nothing is deleted and nothing is repointed — ``merge_plan`` plans and counts it, and the merge door
writes it through the bind door into the overrides tree, so a rebuild keeps it.

The clustering core (``cluster_by_similarity``) is pure — it takes precomputed vectors — so it's
trivially testable with hand-made embeddings, no model required.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

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


@dataclass
class MergeStep:
    """One other type of a merge cluster, as the survivor will read it: the table its binding reads, the binding's
    name and spec (``spec`` None when the survivor already binds that table), what the count found, and why the step
    cannot be taken — "" when it can."""
    member: str
    table: str = ""
    name: str = ""
    spec: Optional[dict] = None
    note: str = ""
    problem: str = ""


def merge_plan(graph: Any, canonical_id: str, member_ids: Sequence[str], keys: Optional[dict[str, str]],
               describe: Callable, db: Any) -> list[MergeStep]:
    """How ``member_ids`` merge into ``canonical_id`` — "two tables, one binding" (ROADMAP §3.15): each other type's
    table is bound onto the survivor as a static binding on the survivor's key, counted one row per object, and the
    type becomes a PART of the survivor. Nothing is deleted and nothing is repointed: a part keeps its objects, links
    and pages by its name, and removing the binding releases it.

    ``keys`` names, per type, the column of its table that holds the survivor's key when that is not the type's own
    key. Planned against ``graph`` (the served graph) with each earlier step's binding attached, so the doors that
    apply it meet what was planned; one step with a ``problem`` refuses the whole merge before anything is written."""
    from aughor.ontology.bindings import bind_binding, declared_bindings, measure_binding
    from aughor.ontology.display import key_of
    from aughor.ontology.models import snake_name
    from aughor.ontology.parts import absorb_problem, backing_table, part_binding, parts_of

    survivor = graph.entities[canonical_id].model_copy(deep=True)
    planned = graph.model_copy(update={"entities": {**graph.entities, canonical_id: survivor}})
    steps: list[MergeStep] = []
    for member_id in dict.fromkeys(member_ids):
        if member_id == canonical_id:
            continue
        member = graph.entities[member_id]
        step = MergeStep(member=member_id, table=backing_table(member))
        steps.append(step)
        own_parts = [part.id for part, _ in parts_of(graph, member)]
        if own_parts:
            step.problem = (f"{member_id} has parts of its own ({', '.join(own_parts)}) — a part of a part is not a "
                            f"shape the map draws; merge them into {canonical_id} too, or release them first")
            continue
        bound = part_binding(survivor, member) if step.table else None
        if step.table and bound is None:
            step.name = snake_name(step.table)
            if any(b.name == step.name for b in survivor.bindings or []):
                step.problem = (f"{canonical_id} already has a binding named {step.name} over another source — "
                                "remove or rename it first")
                continue
            spec = {"kind": "static", "table": step.table, "key": (keys or {}).get(member_id) or key_of(member)}
            entry = bind_binding(survivor, step.name, spec, planned, describe)
            if not entry["bound"]:
                step.problem = entry["note"]
                continue
            built, _ = declared_bindings(survivor.model_copy(update={"bindings": []}), {step.name: entry["spec"]},
                                         {"entries": {step.name: entry}}, planned)
            if not built:
                step.problem = f"{step.table} bound, but not as the overlay reads it back"
                continue
            binding = built[0]
            measured = measure_binding(db, survivor, binding)
            if measured.verified is not True:
                step.problem = f"{step.table} counted against {canonical_id}: {measured.note or 'not measurable'}"
                continue
            measured.stamp(binding)
            survivor.bindings = [*(survivor.bindings or []), binding]
            step.spec, step.note = entry["spec"], measured.note
        elif bound is not None:
            if bound.verified is not True:
                step.problem = (f"{canonical_id}'s binding {bound.name} over {step.table} is not counted one row per "
                                f"{canonical_id} ({bound.note or 'uncounted'})")
                continue
            step.name, step.note = bound.name, bound.note
        problem = absorb_problem(planned, canonical_id, member)
        if problem:
            step.problem = problem
    return steps


def _entity_text(e: Any) -> str:
    """The text we embed for an entity — name + description + its source tables."""
    parts = [getattr(e, "display_name", "") or getattr(e, "id", "")]
    if getattr(e, "description", ""):
        parts.append(e.description)
    tables = getattr(e, "source_tables", None)
    if tables:
        parts.append(" ".join(tables))
    return " — ".join(p for p in parts if p)


def _is_part(graph: Any, entity: Any) -> bool:
    """Whether ``entity`` is already a part of another type — its mark holds — and so no duplicate to offer again."""
    if not getattr(entity, "absorbed_into", None):
        return False
    from aughor.ontology.parts import part_of
    return part_of(graph, entity) is not None


def detect_duplicate_entities(
    graph: Any,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[dict]:
    """Near-duplicate entity clusters in an OntologyGraph, as merge *suggestions* (never applied).

    Returns a list of ``{"entities": [{id, display_name, source_tables}, ...], "similarity": float}``,
    strongest first. ``[]`` when there are < 2 entities or embeddings are unavailable (fail-open). A type
    that is already a part of another is left out: it was merged (or read as a part), and offering it
    again would bind its table twice."""
    entities = [e for e in getattr(graph, "entities", {}).values() if not _is_part(graph, e)]
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
