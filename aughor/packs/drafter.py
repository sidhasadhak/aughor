"""A pack's structure, proposed over the tables a connection actually holds (2026-10-10).

A pack's `ontology.yaml` describes how an industry is usually shaped: which objects it has, which of them are rows OF
another (an order's lines), the verbs its links are read with, the stages its objects move through. None of that
creates an object. The builder makes one type per table; this module reads the pack against what the builder made
and proposes, deterministically and with no model call:

* **parts** — where the data holds both an object and one the pack lists as its part, the part's table read under
  the object (an Order made of its order lines);
* **link names** — a link the builder found, named with the pack's verb, in the direction the builder oriented it;
* **links** — a link the pack expects on a named key, where both tables hold it and the builder found no join;
* **processes** — the pack's stages, each resolved to a moment on the object, where at least two resolve.

An object the data does not hold is never proposed and never mentioned: a business whose head office is its warehouse
has no warehouse table, and an object for it would describe someone else's process.

The proposals are the explorer's own shape (`BusinessDraft`), so they go through `ontology.explorer.apply_draft`
unchanged: each measured against the data before it lands, written with the pack's provenance (`pack:<id>@<version>`),
PROPOSED until a person confirms it, and never proposed again once a person withdraws it.
"""
from __future__ import annotations

from aughor.ontology.explorer import (
    BusinessDraft, ProposedLink, ProposedLinkName, ProposedPart, ProposedProcess, ProposedStage,
)
from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyRelationship, snake_name
from aughor.ontology.parts import backing_table
from aughor.packs.models import ExpectedLink, PackOntology
from aughor.packs.ontology_map import moment_named_like, match_objects

#: A process is proposed only when this many of its stages resolve to a moment on the object — one stage is a
#: timestamp, not a process.
MIN_STAGES = 2


def pack_draft(graph: OntologyGraph, po: PackOntology, pack_id: str = "") -> BusinessDraft:
    """The pack's structure over ``graph``, as proposals. Never an entity: every object comes from a table."""
    matched = match_objects(po, graph)
    names, links = _links(po, graph, matched, pack_id)
    return BusinessDraft(parts=_parts(po, graph, matched, pack_id), links=links, link_names=names,
                         processes=_processes(po, graph, matched, pack_id))


def _key_of(entity: OntologyEntity) -> str:
    return (entity.backing.primary_key if entity.backing is not None else "") or entity.identity_key


def _between(graph: OntologyGraph, a: str, b: str) -> list[OntologyRelationship]:
    return sorted((r for r in graph.relationships.values() if {r.from_entity, r.to_entity} == {a, b}),
                  key=lambda r: r.id)


def _on(rels: list[OntologyRelationship], via: str) -> list[OntologyRelationship]:
    low = (via or "").lower()
    return [r for r in rels if low and low in (r.from_col.lower(), r.to_col.lower())]


def _parts(po: PackOntology, graph: OntologyGraph, matched: dict[str, str], pack_id: str) -> list[ProposedPart]:
    out: list[ProposedPart] = []
    for obj in po.objects:
        parent_id = matched.get(obj.name)
        for child in obj.parts:
            child_id = matched.get(child)
            if not parent_id or not child_id or parent_id == child_id:
                continue
            table = backing_table(graph.entities[child_id])
            if not table:
                continue
            # the column on the part's own rows that holds the object's key: the found join first, the pack's key second
            column = ""
            for rel in _between(graph, parent_id, child_id):
                column = rel.from_col if rel.from_entity == child_id else rel.to_col
                break
            if not column:
                expected = next((lk.via for lk in po.links if {lk.from_object, lk.to_object} == {obj.name, child}
                                 and lk.via), "")
                if expected and any(expected.lower() == p.lower() for p in graph.entities[child_id].properties):
                    column = expected
            if not column:
                continue
            out.append(ProposedPart(entity=parent_id, table=table, key=column, name=snake_name(child),
                                    reason=f"{_by(pack_id)}: a {obj.name} is made of its {child} rows"))
    return out


def _links(po: PackOntology, graph: OntologyGraph, matched: dict[str, str],
           pack_id: str) -> tuple[list[ProposedLinkName], list[ProposedLink]]:
    names: list[ProposedLinkName] = []
    links: list[ProposedLink] = []
    for lk in po.links:
        a, b = matched.get(lk.from_object), matched.get(lk.to_object)
        if not a or not b or a == b:
            continue
        rels = _between(graph, a, b)
        if rels:
            rel = _one(rels, lk)
            if rel is None or rel.origin != "join_map":
                continue          # ambiguous, or declared — a declared link carries the name its declarer gave it
            verb = lk.verb if rel.from_entity == a else lk.reverse_verb
            if verb.strip():
                names.append(ProposedLinkName(
                    link=rel.id, name=f"{snake_name(rel.from_entity)}_{snake_name(verb)}_{snake_name(rel.to_entity)}",
                    reason=f"{_by(pack_id)}: {lk.from_object} {lk.verb or 'relates to'} {lk.to_object}"))
            continue
        # no join found: proposed on the pack's key where the from-side holds it, and counted before it lands
        holder = graph.entities[a]
        via = next((p for p in holder.properties if lk.via and p.lower() == lk.via.lower()), "")
        target_key = _key_of(graph.entities[b])
        if via and target_key:
            links.append(ProposedLink(from_entity=a, to_entity=b, verb=lk.verb or "relates to", from_column=via,
                                      to_column=target_key,
                                      reason=f"{_by(pack_id)}: {lk.from_object} {lk.verb or 'relates to'} {lk.to_object}"))
    return names, links


def _one(rels: list[OntologyRelationship], lk: ExpectedLink):
    """The found link a pack link names: the one join between the pair — links on the same two columns are one join,
    however many times it was declared, and the builder's copy is the one named — or the one on the pack's key when
    the pair is joined more than one way; none when that still leaves several, rather than a guess."""
    joins: dict[frozenset, list[OntologyRelationship]] = {}
    for r in rels:
        joins.setdefault(frozenset({(r.from_entity, r.from_col.lower()), (r.to_entity, r.to_col.lower())}), []).append(r)
    if len(joins) > 1:
        on = _on(rels, lk.via)
        joins = {k: v for k, v in joins.items() if any(r in on for r in v)}
    if len(joins) != 1:
        return None
    [same] = joins.values()
    return next((r for r in same if r.origin == "join_map"), same[0])


def _processes(po: PackOntology, graph: OntologyGraph, matched: dict[str, str],
               pack_id: str) -> list[ProposedProcess]:
    out: list[ProposedProcess] = []
    for proc in po.processes:
        eid = matched.get(proc.object)
        if not eid:
            continue
        if any(p.entity == eid for p in (graph.processes or {}).values()):
            continue          # a process declared on the object settles it, as it settles the pack's claim
        entity = graph.entities[eid]
        stages, used = [], set()
        for stage in proc.stages:
            moment = moment_named_like(entity, stage.timestamp_hints)
            if moment and moment not in used:
                stages.append(ProposedStage(name=stage.name, timestamp=moment))
                used.add(moment)
        if len(stages) < MIN_STAGES:
            continue
        out.append(ProposedProcess(id=proc.name, entity=eid, display_name=proc.name.replace("_", " ").capitalize(),
                                   stages=stages, reason=f"{_by(pack_id)}: {proc.description or proc.name}"))
    return out


def _by(pack_id: str) -> str:
    return f"the {pack_id} pack" if pack_id else "the pack"
