"""Arc OC-1 — what depends on a declaration, so a withdrawal that would break something is refused, naming it
(ROADMAP §3.56; the ON-7 promise in §3.15, never kept: `DELETE /ontology/entities/{id}` removed a declared type
without asking who used it).

A first index, read from what already names ontology things — nothing new is stored:

* **automations** — a `promise_breached` trigger names a process; a step that runs a declared action names it by
  `action_id`; a `source_change` or `entity_appears` trigger names a table an entity is read from;
* **processes** — the entity they run on, and every entity and link their stages and promises read, resolved by the
  object compiler's own law (`semantic.object_query.property_at`), so a path counts exactly as the measurement walks it;
* **rules, declared actions, declared links, parts and metrics** — the entity each is defined over or about, and an
  action another action's undo names.

A claim in the Record about an element is not a dependent here: what it said is kept, and OC-2 restates the claims a
meaning-changing release touches. A metric step in an automation names the governed registry's metric, not the
ontology's, and is not read. Each row says how it depends, in words a person can act on.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.ontology.models import OntologyGraph, Process


def _entity(graph: OntologyGraph, name: str):
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        return find_object_type(graph, name) if name else None
    except ObjectQueryRefused:
        return None


def _path_reach(graph: OntologyGraph, entity, path: str) -> list:
    """The links a property path crosses from ``entity``, by the compiler's law; [] when it does not resolve — a path
    the compiler cannot read depends on nothing it could break."""
    from aughor.semantic.object_query import ObjectQueryRefused, property_at
    if entity is None or not path:
        return []
    try:
        _, _, hops = property_at(graph, entity.api_name, path, purpose="dependents")
    except ObjectQueryRefused:
        return []
    return list(hops)


def _via_reach(graph: OntologyGraph, grain, via: str, home) -> list:
    """The hops a promise's objects take from its grain to the process's type, as its measurement walks them: the
    links `via` names one by one, or — `via` unset — the only measured to-one link between the two types."""
    from aughor.semantic.object_query import link_problem, object_links
    if grain is None or home is None or grain.id == home.id:
        return []
    if not via:
        usable = [h for h in object_links(graph, grain) if h.target.id == home.id and h.to_one and not link_problem(h)]
        return usable if len(usable) == 1 else []
    hops, current = [], grain
    for seg in via.split("."):
        hop = next((h for h in object_links(graph, current) if seg.lower() in (h.name.lower(), h.business.lower())),
                   None)
        if hop is None:
            break
        hops.append(hop)
        current = hop.target
    return hops


def process_reach(graph: OntologyGraph, process: Process) -> tuple[set[str], set[str]]:
    """Every entity id and relationship id a process reads: its own type, and what each stage's anchor and each
    promise's grain, deadline and `via` cross."""
    home = graph.entities.get(process.entity) or _entity(graph, process.entity)
    entities: set[str] = {home.id} if home is not None else set()
    links: set[str] = set()

    def take(hops: list) -> None:
        for h in hops:
            links.add(h.rel.id)
            entities.add(h.target.id)

    for stage in process.stages:
        take(_path_reach(graph, home, stage.timestamp))
        take(_path_reach(graph, home, stage.property))
        promise = stage.promise
        if promise is None:
            continue
        grain = _entity(graph, promise.grain) if promise.grain else home
        if grain is not None:
            entities.add(grain.id)
        take(_path_reach(graph, grain, promise.deadline))
        take(_via_reach(graph, grain, promise.via, home))
    return entities, links


def _row(consumer: str, cid: str, name: str, how: str) -> dict:
    return {"consumer": consumer, "id": cid, "name": name or cid, "how": how}


def _tables_of(entity) -> set[str]:
    names = {t.lower() for t in entity.source_tables}
    if entity.backing is not None and entity.backing.table:
        names.add(entity.backing.table.lower())
    return names | {n.rsplit(".", 1)[-1] for n in names}


def _automations(conn: str) -> list:
    from aughor.automations.store import list_automations
    return list_automations(conn_id=conn)


def dependents_of(graph: Optional[OntologyGraph], conn: str, kind: str, target_id: str, *,
                  automations: Optional[list] = None) -> list[dict]:
    """What depends on one declaration — a list of rows, each with the consumer, its id and name, and how it
    depends. Empty when nothing does, or when the scope has no graph to read paths on (said by the door)."""
    if graph is None:
        return []
    autos = _automations(conn) if automations is None else automations
    rows: list[dict] = []
    procs = {pid: process_reach(graph, p) for pid, p in graph.processes.items()}
    actions = {a.id: a for a in graph.declared_actions()}

    def automations_on(process_ids: set[str], action_ids: set[str], tables: set[str], why_suffix: str = "") -> None:
        for a in autos:
            for c in a.conditions:
                pid = str(c.config.get("process") or "")
                if c.kind == "promise_breached" and pid in process_ids:
                    rows.append(_row("automation", a.id, a.name, f"its trigger watches the process '{pid}'{why_suffix}"))
                elif c.kind in ("source_change", "entity_appears") and str(c.config.get("table") or "").lower() \
                        .rsplit(".", 1)[-1] in tables:
                    rows.append(_row("automation", a.id, a.name,
                                     f"its trigger watches the table '{c.config.get('table')}'{why_suffix}"))
            for e in a.effects:
                aid = str(e.config.get("action_id") or "")
                if aid and aid in action_ids:
                    rows.append(_row("automation", a.id, a.name, f"a step runs the declared action '{aid}'{why_suffix}"))

    if kind == "entity":
        ent = graph.entities.get(target_id) or _entity(graph, target_id)
        if ent is None:
            return []
        names = {ent.id, ent.api_name}
        on_it = {pid for pid, (ents, _) in procs.items() if ent.id in ents}
        for pid in sorted(on_it):
            p = graph.processes[pid]
            how = "the process runs on it" if p.entity in names else "a stage or a promise of the process reads it"
            rows.append(_row("process", pid, p.display_name, how))
        for rid, r in sorted(graph.rules.items()):
            if r.entity in names:
                rows.append(_row("rule", rid, r.display_name, "the rule is defined over it"))
        about = set()
        for aid, act in sorted(actions.items()):
            if act.entity in names or act.object_type in names:
                about.add(aid)
                rows.append(_row("action", aid, act.display_name, "the action is about it"))
            elif any(p.object_type in names for p in act.params):
                about.add(aid)
                rows.append(_row("action", aid, act.display_name, "a parameter takes one of its objects"))
        for lid, rel in sorted(graph.relationships.items()):
            if rel.origin != "join_map" and ent.id in (rel.from_entity, rel.to_entity):
                rows.append(_row("link", lid, rel.name or lid, "the declared link joins it"))
        for eid, other in sorted(graph.entities.items()):
            if other.absorbed_into in names and eid != ent.id:
                rows.append(_row("part", eid, other.display_name, "it is marked a part of this entity"))
        for mid, m in sorted(graph.metrics.items()):
            if m.entity in names:
                rows.append(_row("metric", mid, m.display_name, "the metric belongs to it"))
        automations_on(on_it, about, _tables_of(ent), f", which reads {ent.id}")
    elif kind == "link":
        on_it = {pid for pid, (_, links) in procs.items() if target_id in links}
        for pid in sorted(on_it):
            rows.append(_row("process", pid, graph.processes[pid].display_name,
                             "a stage or a promise of the process is read through it"))
        automations_on(on_it, set(), set(), ", which is read through this link")
    elif kind == "process":
        automations_on({target_id}, set(), set())
    elif kind == "action":
        for aid, act in sorted(actions.items()):
            if act.undo is not None and act.undo.action_id == target_id and aid != target_id:
                rows.append(_row("action", aid, act.display_name, "its undo is this action"))
        automations_on(set(), {target_id}, set())
    seen, out = set(), []
    for r in rows:
        key = (r["consumer"], r["id"], r["how"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def refusal(kind: str, target_id: str, rows: list[dict]) -> str:
    """The sentence a refused withdrawal answers with: what would break, and what to do first."""
    named = "; ".join(f"{r['consumer']} '{r['name']}' ({r['how']})" for r in rows[:8])
    more = f"; and {len(rows) - 8} more" if len(rows) > 8 else ""
    return (f"{kind} '{target_id}' is not withdrawn — {len(rows)} thing{'s' if len(rows) != 1 else ''} depend"
            f"{'' if len(rows) != 1 else 's'} on it: {named}{more}. Change or withdraw those first.")


def guard_withdrawal(graph: Optional[OntologyGraph], conn: str, kind: str, target_id: str) -> Any:
    """Arc OC-1's door check: the dependents when `ontology.history` (or `ontology.release`, which keeps history) is on
    and something depends, else []. Off, it reads nothing — a withdrawal behaves exactly as before."""
    from aughor.ontology import history
    if not history.enabled():
        return []
    return dependents_of(graph, conn, kind, target_id)
