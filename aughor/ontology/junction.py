"""Arc NV-2 — the junction mark: an entity that only relates two others, said as a measured fact.

`order_products(order_id, product_id)`, `user_groups(user_id, group_id, joined_at)`: a table whose every non-key
column is a foreign key exists to relate two entities, and a writer who aggregates ON it, or joins it as if it
held one row per order, multiplies rows in silence. NVIDIA's Auto-Ontology marks such a table structurally — every
column a foreign key — and then has a model write the join (`docs/NVIDIA_AUTO_ONTOLOGY_STUDY_2026-11-04.md` §5.2).
Aughor's version is a builder fact with no model call:

* an entity minted from ONE table qualifies when it carries **no measure**, exactly **two** foreign-key columns
  whose join edges were **value-verified** (containment ≥ :data:`MIN_OVERLAP`, `join_guard`'s own floor) or
  declared by the engine, pointing at **two different** entities, and nothing else but its own key and timestamps;
* it is marked (`OntologyEntity.junction`, both overlaps on record, `verified` only when both edges were measured),
  and ONE N:N link is declared **between the two far entities through it** (`OntologyRelationship.via`), its
  `join_sql` holding both hops, so the relationship block and the ENTITY MODEL block say "junction between X and Y"
  and "via" rather than leaving the writer to discover the shape from column names.

What this deliberately does NOT do yet: teach the object compiler to traverse an N:N through a junction with
pre-aggregation on the far side. The compiler refuses every N:N today and keeps refusing this one (it reads the
label, not `via`); the study's falsifier says the compiler change waits until a live connection has a table that
qualifies. Pure: runs on a graph whose edges were already measured (`store.get_or_build_ontology`, after
`apply_cardinality_measurements`), reads nothing, calls nothing.
"""
from __future__ import annotations

import logging
import re

from aughor.ontology.models import Junction, OntologyGraph, OntologyRelationship, snake_name

logger = logging.getLogger(__name__)

#: `aughor.sql.join_guard`'s containment floor: below it two keys sharing values is a coincidence, not an edge.
MIN_OVERLAP = 0.15

_TIMESTAMP_TYPES = re.compile(r"\b(TIMESTAMP|DATE|DATETIME|TIMESTAMPTZ|TIME)\b", re.IGNORECASE)


def _is_time(prop) -> bool:
    return prop.semantic_type == "timestamp" or bool(_TIMESTAMP_TYPES.search(prop.data_type or ""))


def _fk_edges(graph: OntologyGraph, entity_id: str) -> dict[str, OntologyRelationship]:
    """The entity's outgoing edges that are FACTS: measured past the floor, or the engine's own declared key."""
    out: dict[str, OntologyRelationship] = {}
    for rel in graph.relationships.values():
        if rel.from_entity != entity_id or rel.via or rel.from_entity == rel.to_entity:
            continue
        measured = rel.value_overlap is not None and rel.value_overlap >= MIN_OVERLAP
        if measured or rel.join_confidence == "declared":
            out[rel.from_col] = rel
    return out


def qualifies(graph: OntologyGraph, entity_id: str) -> list[OntologyRelationship]:
    """The two foreign-key edges that make ``entity_id`` a junction, or [] when it is not one.

    The rule, in the order a reader checks it: one source table, minted from a table (a person's declared type is
    theirs to describe), not absorbed into a parent, no measure property, exactly two fact edges to two different
    entities, and every other property its own key or a timestamp."""
    e = graph.entities.get(entity_id)
    if e is None or e.origin != "table" or e.absorbed_into or len(e.source_tables) != 1 or not e.properties:
        return []
    if any(p.semantic_type == "measure" for p in e.properties.values()):
        return []
    edges = _fk_edges(graph, entity_id)
    if len(edges) != 2 or len({r.to_entity for r in edges.values()}) != 2:
        return []
    for name, p in e.properties.items():
        if name in edges or name == e.identity_key or p.is_primary_key or _is_time(p):
            continue
        return []           # a dimension or a flag of its own: it describes the pair, it is not only a bridge
    return sorted(edges.values(), key=lambda r: r.to_entity)


def mark_junctions(graph: OntologyGraph) -> list[str]:
    """Mark every junction in ``graph`` and declare the N:N link through each. Returns the ids marked.

    Idempotent: an entity already marked, or a through-link already present, is left as it is."""
    marked: list[str] = []
    for entity_id in sorted(graph.entities):
        e = graph.entities[entity_id]
        if e.junction is not None:
            continue
        pair = qualifies(graph, entity_id)
        if not pair:
            continue
        a, b = pair
        overlaps = [a.value_overlap, b.value_overlap]
        verified = all(o is not None and o >= MIN_OVERLAP for o in overlaps)
        said = ", ".join(f"{r.from_col} → {r.to_entity} "
                         + (f"{r.value_overlap:.0%} of keys found" if r.value_overlap is not None
                            else "declared by the engine, overlap not measured")
                         for r in pair)
        e.junction = Junction(
            between=[a.to_entity, b.to_entity], through=[a.from_col, b.from_col],
            overlaps=[max(0.0, o) if o is not None else 0.0 for o in overlaps], verified=verified,
            note=f"every non-key column is a foreign key and the table carries no measure: {said}",
        )
        rid = f"{a.to_entity}_RELATES_TO_{b.to_entity}_via_{entity_id}"
        if rid not in graph.relationships:
            rel = OntologyRelationship(
                id=rid, from_entity=a.to_entity, to_entity=b.to_entity, verb="RELATES_TO",
                cardinality="N:N", measured_cardinality="N:N",
                join_sql=(f"{a.to_table}.{a.to_col} = {a.from_table}.{a.from_col} "
                          f"AND {b.from_table}.{b.from_col} = {b.to_table}.{b.to_col}"),
                from_table=a.to_table, from_col=a.to_col, to_table=b.to_table, to_col=b.to_col,
                join_confidence="verified" if verified else "inferred",
                value_overlap=min(o for o in overlaps if o is not None) if verified else None,
                cardinality_note=f"N:N through the junction {entity_id} ({a.from_col}, {b.from_col}); "
                                 "pre-aggregate the far side before joining",
                via=entity_id,
                api_name=f"{snake_name(a.to_entity)}_to_{snake_name(b.to_entity)}_via_{snake_name(entity_id)}",
                reverse_api_name=f"{snake_name(b.to_entity)}_to_{snake_name(a.to_entity)}_via_{snake_name(entity_id)}",
            )
            graph.relationships[rid] = rel
            graph.relationship_index.setdefault(a.to_entity, []).append(b.to_entity)
            graph.relationship_index.setdefault(b.to_entity, []).append(a.to_entity)
        marked.append(entity_id)
    if marked:
        logger.info("[ontology:%s] %d junction(s) marked: %s", graph.connection_id, len(marked), ", ".join(marked))
    return marked
