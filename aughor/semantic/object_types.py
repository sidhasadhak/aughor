"""ON-3b / ON-3c — an object TYPE, as one connected slice (ROADMAP §3.15, amended 2026-09-11).

ON-3 opened one object; this module says what a type IS, from what the graph already measures: its key
and whether the data proved it unique, the property that names an instance, every property with its
role, type and SOURCE (the binding and column it is read from), its bindings, its links by name with
their measured cardinality and whether ON-2's compiler follows each — or why not — the declared actions
that take it, and its verified metrics. The entity-type map renders it (`GET /object-types/{type}`) and
the agent reads the same dict through `describe_entity`, so a person and an agent asking what a Shipment
is get one answer. `find_paths` answers "how does Customer reach Shipment?" with every hop marked the
way the compiler treats it.

Read-only and database-free: every fact here was measured before (ON-0a's cardinalities, ON-1's key
uniqueness and rows, the display measurement) or declared by a person; an unmeasured fact says so, and
nothing is inferred on the way out.
"""
from __future__ import annotations

from typing import Optional, Union

from aughor.ontology.display import display_of, key_of
from aughor.ontology.models import LINK_NAME_PATTERN, OntologyEntity, OntologyGraph
from aughor.semantic.object_query import (
    MAX_LINK_HOPS,
    ObjectLink,
    ObjectQueryRefused,
    find_object_type,
    link_problem,
    metric_on,
    object_links,
    overlay_properties,
)

#: Properties one description carries; a wider type says it was cut.
_MAX_PROPERTIES = 80
#: Paths one answer lists, and the longest path searched.
_MAX_PATHS = 12
_MAX_SEARCH_HOPS = 5
#: Links the path search expands before it stops — a dense graph must not turn a read into a crawl.
_MAX_EXPANSIONS = 20_000


def _type_word(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _bare(table: str) -> str:
    return (table or "").strip().strip('"').rsplit(".", 1)[-1]


def _entity(graph: OntologyGraph, object_type: Union[str, OntologyEntity]) -> OntologyEntity:
    return object_type if isinstance(object_type, OntologyEntity) else find_object_type(graph, object_type)


def _binding(entity: OntologyEntity, supplies: int) -> dict:
    """The type's one binding today — its backing, with the facts measured on it (ON-1b makes it a list)."""
    b = entity.backing
    common = {"key": key_of(entity), "verified": b.verified if b is not None else None,
              "rows": b.rows if b is not None else None,
              "note": b.verification_note if b is not None else "", "supplies": supplies}
    if b is not None and b.kind == "query":
        return {"name": "query", "kind": "query", "sql": b.sql or "", **common}
    table = (b.table if b is not None else None) or (entity.source_tables[0] if entity.source_tables else "")
    return {"name": _bare(table), "kind": "table", "table": table, **common}


def _source(binding: dict, column: str) -> dict:
    if binding["kind"] == "query":
        return {"binding": binding["name"], "column": column}
    return {"binding": binding["name"], "table": binding["table"], "column": column}


def link_row(h: ObjectLink) -> dict:
    """One link as read from its source type: its names, its verb, its measured cardinality, and whether the
    compiler follows it. A refused link carries the compiler's own sentence for why."""
    problem = link_problem(h)
    rel = h.rel
    row = {"name": h.name, "business_name": h.business, "business_name_source": rel.business_name_source(),
           "verb": rel.verb, "relationship": rel.id,
           "direction": "out" if rel.from_entity == h.source.id else "in",
           "to": h.target.api_name, "to_type": h.target.id, "to_name": h.target.display_name or h.target.id,
           "cardinality": h.label, "measured": rel.measured_cardinality is not None,
           "kind": "to-one" if h.to_one else "to-many", "on": f"{h.local_col} = {h.remote_col}",
           "traversable": not problem}
    if problem:
        row["why_not"] = problem
    return row


def type_actions(graph: OntologyGraph, entity: OntologyEntity) -> list[dict]:
    """The declared actions about this type, or taking one of its objects — each with its parameters (the object
    ones typed) and the overlay properties it sets. Facts about the type; nothing here proposes or runs one."""
    words = {_type_word(entity.api_name), _type_word(entity.id)}
    key = key_of(entity).lower()
    out = []
    for action in graph.declared_actions():
        takes = [p.name for p in action.params if p.kind == "object" and _type_word(p.object_type) in words]
        keyed = [p.name for p in action.params if p.kind != "object" and key and p.name.lower() == key]
        owned = _type_word(action.entity) in words or _type_word(action.object_type) in words
        if not (owned or takes or keyed):
            continue
        why = (f"takes {' and '.join(takes)} ({entity.id})" if takes
               else f"takes {' and '.join(keyed)}" if keyed else f"declared on {entity.id}")
        out.append({"id": action.id, "display_name": action.display_name or action.id,
                    "description": action.description, "kind": action.kind, "risk": action.risk, "why": why,
                    "params": [{"name": p.name, "kind": p.kind, "object_type": p.object_type,
                                "data_type": p.data_type, "required": p.required} for p in action.params],
                    "edits": [{"object": e.object, "property": e.property} for e in action.edits]})
    return out


def _metrics(graph: OntologyGraph, entity: OntologyEntity) -> tuple[list[dict], list[str]]:
    """The verified metrics on this type, and the ids of the ones that are not — the compiler measures only with
    the first, so the second is named rather than silently dropped."""
    verified, unverified = [], []
    for metric_id, m in sorted(graph.metrics.items()):
        if not metric_on(m, entity):
            continue
        if m.verified:
            verified.append({"id": metric_id, "display_name": m.display_name or metric_id, "unit": m.unit,
                             "formula_sql": m.formula_sql})
        else:
            unverified.append(metric_id)
    return verified, unverified


def _count(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def _summary(d: dict) -> str:
    """One line an agent can quote: the key's verdict, what names an object, where its properties come from, and
    how many of its links the compiler follows."""
    key = d["key"]
    verdict = {True: "unique per object, measured", False: "NOT unique per row, measured",
               None: "uniqueness not yet measured"}[key["verified"]]
    rows = f" over {key['rows']:,} rows" if key.get("rows") is not None else ""
    shown = d["display_property"]
    named = "its key" if shown["is_key"] else shown["property"]
    binding = d["bindings"][0]
    source = binding.get("table") or "a keyed SELECT"
    counts = d["counts"]
    overlay = counts["properties"] - binding["supplies"]
    return (f"{d['display_name']} ({d['object_type']}): key {key['property']} — {verdict}{rows}; named by {named}; "
            f"{_count(binding['supplies'], 'property', 'properties')} read from {source}"
            + (f" and {_count(overlay, 'overlay property', 'overlay properties')} set by accepted actions"
               if overlay else "")
            + f"; {_count(counts['links'], 'link', 'links')}, {counts['traversable_links']:,} followed by the "
            f"compiler; {_count(counts['actions'], 'declared action', 'declared actions')}; "
            f"{_count(counts['metrics'], 'verified metric', 'verified metrics')}.")


def describe_object_type(graph: OntologyGraph, object_type: Union[str, OntologyEntity], *,
                         overlay: Optional[list] = None) -> dict:
    """What one object type is — the entity-type panel's content and `describe_entity`'s body, one dict."""
    entity = _entity(graph, object_type)
    key = key_of(entity)
    binding = _binding(entity, len(entity.properties or {}))
    properties = [{"name": name, "display_name": p.display_name or name, "role": p.semantic_type or "",
                   "data_type": p.data_type, "unit": p.unit, "is_key": name.lower() == key.lower(),
                   "null_rate": p.null_rate, "description": p.description, "source": _source(binding, name)}
                  for name, p in (entity.properties or {}).items()]
    for edits in overlay_properties(entity, overlay).values():
        properties.append({"name": edits[0].column, "display_name": edits[0].column, "role": "overlay",
                           "data_type": "", "unit": "", "is_key": False, "null_rate": None,
                           "description": "set by accepted actions and merged at read time; the source is never written",
                           "source": {"binding": "overlay", "edits": len(edits)}})
    links = [link_row(h) for h in object_links(graph, entity)]
    actions = type_actions(graph, entity)
    metrics, unverified = _metrics(graph, entity)
    b = entity.backing
    out = {
        "object_type": entity.api_name, "id": entity.id, "display_name": entity.display_name or entity.id,
        "description": entity.description, "role": entity.entity_type, "domain": entity.domain or "",
        "key": {"property": key, "verified": b.verified if b is not None else None,
                "rows": b.rows if b is not None else None, "note": b.verification_note if b is not None else ""},
        "display_property": display_of(entity),
        "time": entity.created_at_col or "",
        "properties": properties[:_MAX_PROPERTIES],
        "properties_truncated": len(properties) > _MAX_PROPERTIES,
        "bindings": [binding],
        "links": links,
        "actions": actions,
        "metrics": metrics,
        "unverified_metrics": unverified,
        "segments": sorted(k for k, s in (entity.segments or {}).items() if s.verified and (s.filter_sql or "").strip()),
        "lifecycle": ({"property": entity.lifecycle_column, "states": list(entity.lifecycle_states),
                       "terminal": list(entity.terminal_states), "verified": entity.lifecycle_verified,
                       "note": entity.lifecycle_note}
                      if entity.has_lifecycle and entity.lifecycle_column else None),
        "counts": {"properties": len(properties), "bindings": 1, "links": len(links),
                   "traversable_links": sum(1 for link in links if link["traversable"]),
                   "actions": len(actions), "metrics": len(metrics)},
    }
    out["summary"] = _summary(out)
    return out


def object_type_map(graph: OntologyGraph, *, overlay: Optional[list] = None) -> dict:
    """The entity-type map's data: every object type with the measured facts its card shows, and every link
    between two types with its verb, measured cardinality, and whether the compiler follows it."""
    types = []
    for e in sorted(graph.entities.values(), key=lambda x: (x.display_name or x.id).lower()):
        links = object_links(graph, e)
        shown = display_of(e)
        b = e.backing
        metrics, _ = _metrics(graph, e)
        types.append({"object_type": e.api_name, "id": e.id, "display_name": e.display_name or e.id,
                      "role": e.entity_type, "domain": e.domain or "", "key": key_of(e),
                      "key_verified": b.verified if b is not None else None,
                      "rows": b.rows if b is not None else None, "table": _binding(e, 0).get("table", ""),
                      "display_property": shown["property"], "display_is_key": shown["is_key"],
                      "properties": len(e.properties or {}) + len(overlay_properties(e, overlay)),
                      "bindings": 1, "links": len(links),
                      "traversable_links": sum(1 for h in links if not link_problem(h)),
                      "actions": len(type_actions(graph, e)), "metrics": len(metrics)})
    edges = []
    for r in graph.relationships.values():
        source, target = graph.entities.get(r.from_entity), graph.entities.get(r.to_entity)
        if source is None or target is None:
            continue
        forward = next((h for h in object_links(graph, source) if h.rel is r and h.target is target), None)
        problem = link_problem(forward) if forward is not None else "this link could not be read from its source"
        edges.append({"relationship": r.id, "from": source.api_name, "to": target.api_name,
                      "name": r.api_name, "reverse_name": r.reverse_api_name, "business_name": r.business_name(),
                      "verb": r.verb, "cardinality": r.measured_cardinality or r.cardinality,
                      "measured": r.measured_cardinality is not None, "traversable": not problem,
                      **({"why_not": problem} if problem else {})})
    return {"connection_id": graph.connection_id, "schema_name": graph.schema_name,
            "generated_at": graph.generated_at, "object_types": types, "links": edges}


def _hop_row(h: ObjectLink) -> dict:
    problem = link_problem(h)
    row = {"link": h.name, "business_name": h.business, "verb": h.rel.verb,
           "from": h.source.api_name, "from_name": h.source.display_name or h.source.id,
           "to": h.target.api_name, "to_name": h.target.display_name or h.target.id,
           "direction": "out" if h.rel.from_entity == h.source.id else "in",
           "cardinality": h.label, "kind": "to-one" if h.to_one else "to-many",
           "measured": h.rel.measured_cardinality is not None, "traversable": not problem}
    if problem:
        row["why_not"] = problem
    return row


def _path_row(chain: list[ObjectLink]) -> dict:
    """One path: its hops, whether every hop is followed, and what the compiler can build along it — a filter
    along any followed path within its hop limit, a dimension only when every hop reaches one object."""
    hops = [_hop_row(h) for h in chain]
    refused = next(((i, hop) for i, hop in enumerate(hops) if not hop["traversable"]), None)
    to_one = all(h.to_one for h in chain)
    within = len(chain) <= MAX_LINK_HOPS
    out = {"hops": hops, "length": len(chain), "traversable": refused is None,
           "reach": "to-one" if to_one else "to-many", "path": ".".join(h.name for h in chain),
           "compiles_as": (["filter", "dimension"] if to_one else ["filter"]) if refused is None and within else []}
    if refused is not None:
        i, hop = refused
        out["why_not"] = f"hop {i + 1} ({hop['link']}) is refused — {hop['why_not']}"
    elif not within:
        out["why_not"] = (f"every hop is followed, but the compiler crosses at most {MAX_LINK_HOPS} links in one path "
                          "— anchor the query on a type in between")
    return out


def find_paths(graph: OntologyGraph, source: str, target: str, *, max_hops: int = 4,
               limit: int = _MAX_PATHS) -> dict:
    """Every chain of links from one type to another within ``max_hops``, each hop marked the way the compiler
    treats it: followed paths first, shortest first, and a refused path naming the hop that stops it and why."""
    start, goal = find_object_type(graph, source), find_object_type(graph, target)
    if start.id == goal.id:
        raise ObjectQueryRefused(f"a path needs two different object types — both name {start.id}")
    depth = max(1, min(int(max_hops), _MAX_SEARCH_HOPS))
    found: list[list[ObjectLink]] = []
    budget = [_MAX_EXPANSIONS]

    def walk(entity: OntologyEntity, chain: list[ObjectLink], seen: frozenset) -> None:
        for h in object_links(graph, entity):
            if budget[0] <= 0 or h.target.id in seen:
                continue
            budget[0] -= 1
            step = chain + [h]
            if h.target.id == goal.id:
                found.append(step)
            elif len(step) < depth:
                walk(h.target, step, seen | {h.target.id})

    walk(start, [], frozenset({start.id}))
    limit = max(1, int(limit))
    paths = sorted((_path_row(chain) for chain in found),
                   key=lambda p: (not p["traversable"], p["length"], p["path"]))
    return {"from": start.api_name, "from_name": start.display_name or start.id,
            "to": goal.api_name, "to_name": goal.display_name or goal.id,
            "max_hops": depth, "compiler_max_hops": MAX_LINK_HOPS, "paths": paths[:limit],
            "found": len(paths), "truncated": len(paths) > limit or budget[0] <= 0}


def link_name_problem(graph: OntologyGraph, relationship_id: str, name: str) -> str:
    """Why ``name`` cannot be this link's business-verb name, or "". It must be snake_case and name nothing else
    on either type the link joins — no other link and no property — because a path segment names one thing."""
    rel = graph.relationships.get(relationship_id)
    if rel is None:
        return f"no link {relationship_id!r} in this ontology"
    wanted = (name or "").strip()
    if not LINK_NAME_PATTERN.match(wanted):
        return "a link name is snake_case: a lowercase letter, then lowercase letters, digits or underscores"
    for entity_id in dict.fromkeys((rel.from_entity, rel.to_entity)):
        entity = graph.entities.get(entity_id)
        if entity is None:
            continue
        for h in object_links(graph, entity):
            if h.rel is not rel and wanted in (h.name.lower(), h.business.lower()):
                return f"{entity.id} already has a link named {wanted!r} ({h.rel.id})"
        if any(k.lower() == wanted for k in (entity.properties or {})):
            return f"{entity.id} has a property named {wanted!r} — a path could not tell the two apart"
    return ""
