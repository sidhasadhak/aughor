"""ON-8 — which source a type, a binding or a link reads from, and how keys meet across two (ROADMAP §3.15).

An ontology built of one connection's schema reads every type from that connection. An organisation's ontology
(`aughor.ontology.domains`) declares its types on whichever connections hold them, so a backing and a binding may each
name their own connection. Two rules follow, and both live here so nothing downstream keeps a copy of either:

* **The source law.** A type reads from its backing's connection, else from the graph's; a binding from its own, else
  from its type's; a link crosses when its two types read from different connections. The traversal a door shows and
  the compiler's decision to read the far side by key are the same call.
* **Keys across sources.** No statement sees two connections, so a claim that spans them — a binding's coverage, a
  link's overlap — is counted on each side, and its keys meet here, in memory, in the canonical form the
  batched-foreach engine joins on (`remote_join.canon_key`). What a measurement says meets is exactly what the object
  query joins. Bounded: a side with more than `MAX_KEYS` distinct keys, or one its connection cannot return whole,
  leaves the claim unmeasured — never refuted, never guessed — and nothing reads an unmeasured claim.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import Binding, OntologyEntity, OntologyGraph, OntologyRelationship

#: The most distinct keys one side of a cross-source claim is read with. Past it the claim is left unmeasured.
MAX_KEYS = 2_000_000


def entity_source(graph: OntologyGraph, entity: OntologyEntity) -> str:
    """The connection a type's objects are read from: its backing's, else the graph's own."""
    b = entity.backing
    return (b.connection_id if b is not None else "") or graph.connection_id


def binding_source(graph: OntologyGraph, entity: OntologyEntity, binding: Binding) -> str:
    """The connection a binding's rows are read from: its own, else its type's."""
    return binding.connection_id or entity_source(graph, entity)


def link_crosses(graph: OntologyGraph, rel: OntologyRelationship) -> bool:
    """Whether a link's two types read from different connections, so that no one statement can join them."""
    a, b = graph.entities.get(rel.from_entity), graph.entities.get(rel.to_entity)
    return a is not None and b is not None and entity_source(graph, a) != entity_source(graph, b)


def stamp_traversals(graph: OntologyGraph) -> None:
    """Stamp every link `cross-source` or `join` by the source law: what the doors show of it."""
    for rel in graph.relationships.values():
        rel.traversal = "cross-source" if link_crosses(graph, rel) else "join"


def distinct_keys(db: Any, from_clause: str, alias: str, column: str) -> tuple[Optional[set[str]], str]:
    """``(the distinct non-null values of alias.column in canonical key form, "")``, or ``(None, why)`` when they could
    not all be read: a probe that failed, more than `MAX_KEYS` of them, or a connection that returned fewer rows than
    it held (a partial key set would measure a coverage that is not there)."""
    from aughor.connectors.remote_join import canon_key
    col = f"{alias}.{quote_ident(column)}"
    sql = f"SELECT DISTINCT {col} FROM {from_clause} WHERE {col} IS NOT NULL"
    try:
        result = db.execute_bounded("__source_keys__", sql, MAX_KEYS + 1)
    except Exception as exc:  # noqa: BLE001 — a side that cannot be read is unmeasured, not refuted
        return None, f"its keys could not be read: {exc}"[:200]
    if getattr(result, "error", None):
        return None, f"its keys could not be read: {result.error}"[:200]
    rows = list(getattr(result, "rows", None) or [])
    if len(rows) > MAX_KEYS:
        return None, f"more than {MAX_KEYS:,} distinct keys on one side — too many to meet across two connections"
    held = int(getattr(result, "row_count", 0) or 0)
    if held > len(rows):
        return None, (f"its connection returned {len(rows):,} of {held:,} distinct keys, and a partial key set would "
                      "measure a coverage that is not there")
    return {canon_key(str(row[0])) for row in rows}, ""
