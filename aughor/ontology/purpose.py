"""Arc OC-5 — what a link carries, and the objects each stage touches, derived from the declarations (the study's §8.4).

A link was drawn with its verb and its cardinality, and nothing said what the business routes through it: that the
fulfilment process reads an order's lines through `order_items`, or that the dispatch promise is kept per line and
reaches its order through the line's link. A link a stage reaches through *carries* that process; one a promise is
kept through *carries* that promise; one an impact reads its upstream promise through carries the impact. Nothing is
authored: every purpose is read from today's declarations by the compiler's own path law, and changes when they do.

Events are object-centric: a stage's moment touches several objects, each with a role — the object that goes through
the process, the one each promise is kept per (its lead object: the type its deadline belongs to, which reaches the
process's type through measured to-one links, so its rate never repeats one object nor collapses several), the one a
moment is read from.
"""
from __future__ import annotations

from typing import Optional

from aughor.ontology.dependents import _entity, _path_reach, _via_reach
from aughor.ontology.derived import promise_filters, promise_noun
from aughor.ontology.models import OntologyGraph, Process


def _label(process: Process) -> str:
    return process.display_name or process.id.replace("_", " ")


def link_purposes(graph: Optional[OntologyGraph]) -> dict[str, list[dict]]:
    """``{relationship id: [{"process", "process_label", "stage" | "promise" | "impact", "how"}]}`` — what each link
    carries, from every declared process, promise and measured impact."""
    out: dict[str, list[dict]] = {}
    if graph is None:
        return out

    def carry(hops: list, row: dict) -> None:
        for h in hops:
            rows = out.setdefault(h.rel.id, [])
            if row not in rows:
                rows.append(row)

    for process in sorted((graph.processes or {}).values(), key=lambda p: p.id):
        home = graph.entities.get(process.entity) or _entity(graph, process.entity)
        base = {"process": process.id, "process_label": _label(process)}
        for stage in process.stages:
            carry(_path_reach(graph, home, stage.timestamp) + _path_reach(graph, home, stage.property),
                  {**base, "stage": stage.name, "how": f"stage {stage.name}'s moment is read through it"})
            promise = stage.promise
            if promise is None:
                continue
            noun = promise_noun(stage)
            grain = _entity(graph, promise.grain) if promise.grain else home
            how = (f"the {noun} promise is kept per {grain.id if grain is not None else promise.grain} and reaches "
                   f"{process.entity} through it")
            carry(_via_reach(graph, grain, promise.via, home), {**base, "promise": noun, "how": how})
            carry(_path_reach(graph, grain, promise.deadline),
                  {**base, "promise": noun, "how": f"the {noun} promise's deadline is read through it"})
    for impact in sorted((graph.impacts or {}).values(), key=lambda i: i.id):
        if impact.verified is not True or not impact.path:
            continue
        lead = graph.entities.get(impact.lead)
        carry(_path_reach_links(graph, lead, impact.path),
              {"process": impact.upstream.partition(".")[0], "process_label": impact.upstream, "impact": impact.id,
               "how": f"the impact {impact.id} reads {impact.upstream} from {impact.lead} through it"})
    return out


def _path_reach_links(graph: OntologyGraph, entity, path: str) -> list:
    """The links a path of LINK names crosses from ``entity`` — an impact's path ends at a type, not a property."""
    from aughor.semantic.object_query import object_links
    hops, current = [], entity
    for seg in (path or "").split("."):
        if current is None or not seg:
            break
        hop = next((h for h in object_links(graph, current) if seg.lower() in (h.name.lower(), h.business.lower())),
                   None)
        if hop is None:
            break
        hops.append(hop)
        current = hop.target
    return hops


def stage_roles(graph: OntologyGraph, process: Process, index: int) -> list[dict]:
    """The objects stage ``index`` touches, each with its role: the object that goes through the process, the lead
    object its promise is kept per (with why — the cardinality of the links it reaches the process's type through),
    and the objects its moment and its deadline are read from."""
    stage = process.stages[index]
    home = graph.entities.get(process.entity) or _entity(graph, process.entity)
    roles: list[dict] = [{"entity": process.entity, "role": "goes through the process"}]

    def add(entity_id: str, role: str, why: str = "") -> None:
        if not any(r["entity"] == entity_id and r["role"] == role for r in roles):
            roles.append({"entity": entity_id, "role": role, **({"why": why} if why else {})})

    hops = _path_reach(graph, home, stage.timestamp or stage.property)
    if hops:
        add(hops[-1].target.id, "its moment is read from it",
            " → ".join(f"{h.name} ({h.label})" for h in hops))
    spec = promise_filters(process, index)
    if spec is not None:
        grain = graph.entities.get(spec["grain"])
        via = _via_reach(graph, grain, stage.promise.via, home) if grain is not None else []
        why = ("the promise is kept per the object that goes through the process" if not via else
               f"its deadline is a property of each {spec['grain']}, which reaches {process.entity} through "
               + " → ".join(f"{h.name} ({h.label})" for h in via) + ", every hop to-one — so each object is counted "
               "once, and none is folded into another")
        add(spec["grain"], "the lead object its promise is kept per", why)
        if spec.get("deadline"):
            deadline_hops = _path_reach(graph, grain, spec["deadline"])
            add(deadline_hops[-1].target.id if deadline_hops else spec["grain"], "its deadline is read from it")
    return roles
