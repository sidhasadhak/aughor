"""ON-7 — parts: a source that is many rows per object, and a type that is a PART of another (ROADMAP §3.15, the
second movement).

The builder mints one type per table, so an order's lines are a type beside Order and a return's logistics row a
type beside Return. The business does not speak that way: an order HAS lines; the logistics row IS the return's.
Two things make one business entity out of them here, and neither deletes anything:

* a **detail binding** (`Binding.kind == "detail"`) — a table or keyed SELECT that carries the object's key on
  many rows with no clock. None of its columns is a property of the object as it stands, so it supplies exactly
  the properties its **rollups** declare (`Rollup`): each computed inside the object's own partition (GROUP BY
  the key) before the join, one value per object, so it joins under a static binding's law and can never
  multiply the object set (`detail_from`);
* **absorption** (`OntologyEntity.absorbed_into`) — the table's own type is marked a part of the parent. It
  stays a type: its objects, its links and its pages keep working by its name, and the rows themselves are
  still reached at their own grain through the measured link (`order_to_order_item.category`). It is hidden
  from the map and listed under its parent instead. The mark HOLDS only while the parent carries a binding over
  the part's table (`part_of`), so removing that binding releases the part without a second edit.

Every claim here is measured the ON-0a way: a detail binding is counted for the objects it covers, a rollup's
SQL is the compiler's, and an absorption that no longer holds is reported as lapsed rather than believed.
"""
from __future__ import annotations

from typing import Optional

from aughor.ontology.bindings import bare, binding_from
from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import Binding, OntologyEntity, OntologyGraph

#: The alias of the detail rows inside the pre-aggregation.
INNER = "d"


def detail_from(binding: Binding, alias: str, *, key_equals: Optional[str] = None) -> str:
    """The aliased FROM fragment that reads a detail binding as ONE row per object: its key, and every rollup
    computed over the object's own rows. ``key_equals`` is an already-typed literal that narrows the rows to one
    object first, which is how an object page reads its own line.

    Returns "" when the binding names no source, no key or no rollup, the way `binding_from` returns "" — every
    caller checks `binding_problem` first, which refuses exactly those."""
    if not (binding_from(binding, INNER) and binding.key and binding.rollups):
        return ""
    key = f"{INNER}.{quote_ident(binding.key)}"
    select = [f"{key} AS {quote_ident(binding.key)}"]
    for name, rollup in binding.rollups.items():
        select.append(f"{rollup.agg.upper()}({INNER}.{quote_ident(rollup.column)}) AS {quote_ident(name)}")
    where = f" WHERE {key} IS NOT NULL"
    if key_equals is not None:
        where += f" AND {key} = {key_equals}"
    return f"(SELECT {', '.join(select)} FROM {binding_from(binding, INNER)}{where} GROUP BY {key}) AS {alias}"


def rollup_note(binding: Binding) -> str:
    """What the pre-aggregation did, for a plan line, a caveat or a receipt."""
    parts = ", ".join(f"{name} = {r.agg}({r.column})" for name, r in binding.rollups.items())
    return (f"rolled up to one row per {binding.key} before the join — {parts} — so it cannot multiply the "
            f"objects it binds to")


def backing_table(entity: OntologyEntity) -> str:
    """The bare name of the table whose rows ARE this type's objects, or "" for a keyed-SELECT backing."""
    b = entity.backing
    if b is not None and b.kind == "query" and b.sql:
        return ""
    table = (b.table if b is not None else None) or (entity.source_tables[0] if entity.source_tables else "")
    return bare(table)


def part_binding(parent: OntologyEntity, entity: OntologyEntity) -> Optional[Binding]:
    """The parent's binding that reads ``entity``'s own table — the binding under which the entity is a part."""
    table = backing_table(entity).lower()
    if not table:
        return None
    return next((b for b in parent.bindings or [] if bare(b.table or "").lower() == table), None)


def absorb_problem(graph: OntologyGraph, parent_id: str, entity: OntologyEntity) -> str:
    """Why ``entity`` cannot be a part of ``parent_id``, or "" when it can — the one law the bind door, the
    entity override and the read side share, so a mark that does not hold is never believed."""
    parent = graph.entities.get(parent_id or "")
    if parent is None:
        return f"no object type '{parent_id}' to be a part of"
    if parent.id == entity.id:
        return f"{entity.id} cannot be a part of itself"
    if parent.absorbed_into:
        return (f"{parent.id} is itself a part of {parent.absorbed_into} — a part of a part is not a shape "
                "the map draws; absorb into the top-level type instead")
    if not backing_table(entity):
        return f"{entity.id} is read through a keyed SELECT, so no binding of {parent.id}'s can name its table"
    if part_binding(parent, entity) is None:
        return (f"{parent.id} has no binding over {backing_table(entity)} — bind it first (a detail binding for "
                f"many rows per {parent.id}, a static one for one row each); the mark holds only while that "
                "binding does")
    return ""


def part_of(graph: OntologyGraph, entity: OntologyEntity) -> Optional[OntologyEntity]:
    """The type ``entity`` is a part of — when the mark HOLDS — else None."""
    if not entity.absorbed_into or absorb_problem(graph, entity.absorbed_into, entity):
        return None
    return graph.entities.get(entity.absorbed_into)


def parts_of(graph: OntologyGraph, entity: OntologyEntity) -> list[tuple[OntologyEntity, Binding]]:
    """Every type that is a part of ``entity``, with the binding it is read through — in id order."""
    out = []
    for other in sorted(graph.entities.values(), key=lambda e: e.id):
        if other.absorbed_into == entity.id and part_of(graph, other) is entity:
            binding = part_binding(entity, other)
            if binding is not None:
                out.append((other, binding))
    return out


def lapsed_parts(graph: OntologyGraph) -> dict[str, str]:
    """``{entity id: why}`` for every mark that no longer holds — reported, never silently dropped."""
    return {e.id: absorb_problem(graph, e.absorbed_into, e)
            for e in graph.entities.values() if e.absorbed_into and absorb_problem(graph, e.absorbed_into, e)}
