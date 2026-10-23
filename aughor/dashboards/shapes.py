"""Arc AP-5 — shapes in the starter: what a dashboard started from an object is FOR, read from what the ontology holds
(ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.6; design-mockups/cockpit-builder.html screens 1 and 7).

The study measured that every entity got the same five pieces, or a subset: a distribution centre one figure, a case
refused. A shape is offered when the ontology says it fits, with one sentence of why:

  - a QUEUE — things waiting for a person, with something to do about each: a measured promise with its overdue
    segment, or a platform-owned type whose status moves as declared, and actions on the entity;
  - a MAP — a latitude and a longitude, on the entity or one link away;
  - ONE OBJECT — a name to choose one by, and several kinds of objects linking to it;
  - a TIMELINE — two moments on each object, one after the other;
  - an OVERVIEW — figures, how they move and what they break into: today's starter, offered for every entity.

The starter offers one to three, the one that fits best first, and the person picks; every piece can be changed after.
What a shape holds is read here — the sets, the coordinates, the moments, the links, the actions with how each parameter
is filled — and laid out by the web (`web/lib/dashboards/shapes.ts`), so a person keeps a spec its rules accept. Nothing is
offered that the install cannot build: a queue and one object need wiring, a map, a timeline and one object the pieces
the picker adds. No model is asked.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

FLAG = "dashboard.shapes"
#: The days a queue's set looks back over before a person says otherwise — what the desk of the mockup reads.
WINDOW_DAYS = 14
#: The most kinds of linked objects one object's dashboard shows — a table of each that can be listed, a count of each
#: that cannot (an event log that declares no key).
MAX_LINKED = 3
#: The most shapes offered, before Blank.
MAX_OFFERED = 3
#: The kinds of objects that must link to one before a page of one object is offered — a customer's orders, lines and
#: events; a product's two (its stock and its lines) read better as an overview.
MIN_LINKED_KINDS = 3

_NUMERIC = ("INT", "DECIMAL", "NUMERIC", "DOUBLE", "FLOAT", "REAL", "NUMBER")
_TEXT = ("CHAR", "STRING", "TEXT")


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def _words(name: str) -> str:
    return (name or "").replace("_", " ")


def _last(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower()


def _temporal(p: Any) -> bool:
    from aughor.semantic.object_query import is_temporal
    return is_temporal(p)


def _number(p: Any) -> bool:
    return not _temporal(p) and any(t in (p.data_type or "").upper() for t in _NUMERIC)


def _text(p: Any) -> bool:
    return (not _temporal(p) and (p.semantic_type or "") != "key" and not p.is_primary_key
            and any(t in (p.data_type or "").upper() for t in _TEXT))


def _readable(entity: Any, name: str) -> bool:
    from aughor.ontology.security import masked
    return masked(entity, name) is None


def _entity_id(graph: Any, name: str) -> str:
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        return find_object_type(graph, name).id
    except ObjectQueryRefused:
        return ""


def name_of(entity: Any) -> str:
    """The property an object is called by: its own name, a title, an email — "" when it has none (an order)."""
    own = [n for n, p in (entity.properties or {}).items() if _text(p) and _readable(entity, n)]
    return (next((n for n in own if n.lower() == "name"), None)
            or next((n for n in own if n.lower().endswith(("_name", "title"))), None)
            or next((n for n in own if n.lower().endswith("email")), None) or "")


def places_of(graph: Any, entity: Any) -> Optional[dict]:
    """A latitude and a longitude of the same object — the entity's own first, else one a to-one link reaches."""
    from aughor.semantic.object_query import link_problem, object_links

    def pair(target: Any, prefix: str) -> Optional[dict]:
        props = {n: p for n, p in (target.properties or {}).items() if _number(p) and _readable(target, n)}
        lat = next((n for n in props if n.lower() in ("lat", "latitude")), None)
        lng = next((n for n in props if n.lower() in ("lng", "lon", "long", "longitude")), None)
        return {"lat": f"{prefix}{lat}", "lng": f"{prefix}{lng}", "via": prefix.rstrip(".")} if lat and lng else None
    own = pair(entity, "")
    if own:
        return own
    for h in object_links(graph, entity):
        if h.to_one and not link_problem(h) and not _platform(h.target):
            found = pair(h.target, f"{h.name}.")
            if found:
                return {**found, "through": h.target.display_name or h.target.id}
    return None


def moments_of(entity: Any) -> Optional[dict]:
    """The two moments a timeline draws between, of the object's own: the one it starts at — placed, created — and the
    one it ends at — shipped, sold, closed — else its first two."""
    times = [n for n, p in (entity.properties or {}).items() if _temporal(p) and _readable(entity, n)]
    start = next((n for n in times if any(w in n.lower() for w in ("created", "placed", "start", "open", "begin"))),
                 times[0] if times else None)
    rest = [n for n in times if n != start]
    end = next((n for n in rest if any(w in n.lower() for w in ("shipped", "delivered", "sold", "closed", "end",
                                                                  "resolved", "done", "finish"))),
               rest[0] if rest else None)
    return {"start": start, "end": end} if start and end else None


def listable(entity: Any) -> bool:
    """Whether the object door can list this type's objects one by one — by the compiler's own law, a key its backing
    or its identity names. An event log that declares none is counted and charted, never listed."""
    b = entity.backing
    return bool((b.primary_key if b is not None else "") or getattr(entity, "identity_key", ""))


def _platform(entity: Any) -> bool:
    from aughor.ontology.platform_objects import is_platform
    return is_platform(entity)


def linked_to(graph: Any, entity: Any) -> list[dict]:
    """The kinds of objects that link to this one, many to it — an order's lines, a customer's orders — each with the
    property of theirs that names it, what a set of the chosen one's links reads, and whether they can be listed (a
    kind that declares no key is counted, never listed). The ones that can be listed come first."""
    from aughor.semantic.object_query import link_problem, object_links
    out, seen = [], set()
    for h in object_links(graph, entity):
        if h.to_one or link_problem(h) or _platform(h.target) or h.target.id in seen:
            continue
        if h.remote_col not in (h.target.properties or {}) and not any(
                n.lower() == (h.remote_col or "").lower() for n in (h.target.properties or {})):
            continue
        seen.add(h.target.id)
        out.append({"entity": h.target.api_name, "type_id": h.target.id, "path": h.remote_col,
                    "label": h.target.display_name or _words(h.target.id), "listable": listable(h.target)})
    return sorted(out, key=lambda x: not x["listable"])


def _queue(graph: Any, entity: Any) -> Optional[dict]:
    """What a queue waits on: the first measured promise on a process this entity goes through — the objects placed
    in the window, those past the promise, those shipped late — or, for a platform-owned type, the objects whose
    status has not reached a state no move leaves."""
    from aughor.ontology.derived import overdue_derivations, process_derivations, promise_noun
    for process in (graph.processes or {}).values():
        if _entity_id(graph, process.entity) != entity.id:
            continue
        overdue = {d.name: d for d in overdue_derivations(process) if d.usable}
        late = {d.name for d in process_derivations(process).segments if d.usable}
        for i, stage in enumerate(process.stages):
            name = f"overdue_{promise_noun(stage)}"
            if name not in overdue or _entity_id(graph, overdue[name].entity) != entity.id or i == 0:
                continue
            placed = process.stages[i - 1].timestamp
            if not placed or "." in placed or "." in (stage.timestamp or ""):
                continue
            promise = stage.promise
            days = promise.within_days if promise is not None else None
            hours = promise.within_hours if promise is not None else None
            return {"kind": "promise", "process": process.id, "noun": promise_noun(stage), "placed": placed,
                    "reached": stage.timestamp or "", "stage": stage.display_name or stage.name,
                    "overdue": name, "late": f"late_{promise_noun(stage)}" if f"late_{promise_noun(stage)}" in late else "",
                    "promise": (f"{days} day{'s' if days != 1 else ''}" if days is not None
                                else f"{hours} hour{'s' if hours != 1 else ''}" if hours is not None else "")}
    if _platform(entity):
        for prop, machine in (entity.edit_states or {}).items():
            leaves = {m[0] for m in machine.moves if len(m) == 2}
            final = [s for s in machine.states if s not in leaves]
            if final and len(final) < len(machine.states):
                return {"kind": "states", "status": prop, "final": final,
                        "moves": " → ".join(machine.states)}
    return None


def _actions(graph: Any, entity: Any) -> list[dict]:
    """The actions declared on this entity a dashboard can fill: each object parameter of the entity's own from the
    chosen object, each value asked in the form when it is needed — an action needing an object of another type is
    left out, since nothing on the page holds one."""
    out = []
    for a in graph.declared_actions():
        if _entity_id(graph, a.entity or a.object_type) != entity.id:
            continue
        params, ok = [], True
        for p in a.params:
            if p.kind == "object":
                if _entity_id(graph, p.object_type) != entity.id:
                    ok = False
                    break
                params.append({"name": p.name, "source": "chosen"})
            elif p.required:
                params.append({"name": p.name, "source": "ask"})
        if ok:
            out.append({"id": a.id, "label": a.display_name or _words(a.id), "params": params})
    return out


def signals(graph: Any, entity: Any, *, wiring: bool, pieces: bool) -> dict:
    """What the ontology says about ``entity`` that a shape is offered on — read from the graph alone, no warehouse
    read. ``wiring`` and ``pieces`` say what this install can build."""
    actions = _actions(graph, entity)
    # a queue, a map, a timeline and one object each list the objects: a type the door cannot list gets an overview
    listed = listable(entity)
    queue = _queue(graph, entity) if wiring and actions and listed else None
    name = name_of(entity)
    links = linked_to(graph, entity)
    pieces = pieces and listed
    return {
        "entity": entity.api_name, "type_id": entity.id, "name": entity.display_name or _words(entity.id),
        # what each object is called by on a map, a timeline or a list — "" when it has no name (an order)
        "label": name,
        "queue": queue, "actions": actions,
        "places": places_of(graph, entity) if pieces else None,
        "moments": moments_of(entity) if pieces else None,
        "one": {"label": name, "links": links[:MAX_LINKED], "kinds": len(links)}
        if (wiring and pieces and name and len(links) >= MIN_LINKED_KINDS) else None,
        # what a queue lists of the chosen one: the first kind linking to it that can be listed
        "lines": next((x for x in links if x["listable"]), None),
    }


def _plural(word: str) -> str:
    from aughor.dashboards.from_object import plural
    return plural(word)


def offered(sig: dict) -> list[dict]:
    """The shapes that fit, the best first and an overview after it, at most three: each with what it is and one
    short line of why, for the list of what each entity suggests. A map of places one link away — an event placed by
    its customer — is offered after the overview, never as what the entity is for."""
    name = sig["name"]
    fits: list[dict] = []
    later: list[dict] = []
    q = sig.get("queue")
    if q:
        fits.append({"shape": "queue", "short": (f"a {q['noun']} promise · {len(sig['actions'])} action"
                                                 f"{'s' if len(sig['actions']) != 1 else ''}") if q["kind"] == "promise"
                     else f"held by the platform · {len(sig['actions'])} action{'s' if len(sig['actions']) != 1 else ''}"})
    if sig.get("one"):
        fits.append({"shape": "one", "short": f"a name · {sig['one']['kinds']} kinds link to it"})
    if sig.get("places"):
        through = sig["places"].get("through")
        (later if through else fits).append(
            {"shape": "map", "short": "a latitude and a longitude" + (f" through {through}" if through else "")})
    if sig.get("moments"):
        m = sig["moments"]
        fits.append({"shape": "timeline", "short": f"{_words(m['start'])} → {_words(m['end'])}"})
    overview = {"shape": "overview", "short": f"{_plural(name).lower()}: figures and what they break into"}
    return (fits[:1] + [overview] + fits[1:] + later)[:MAX_OFFERED]


def why(shape: str, sig: dict, measured: dict) -> str:
    """The one sentence a shape is offered with, its numbers the door's."""
    name, n = sig["name"], measured.get
    if shape == "queue":
        q, k = sig["queue"], len(sig["actions"])
        acts = f"{k} action{'s are' if k != 1 else ' is'} declared on it"
        if q["kind"] == "promise":
            waiting = n("waiting")
            past = (f"; {waiting:,} {_plural(name).lower()} placed in the last {WINDOW_DAYS} days are past it"
                    if isinstance(waiting, int) else "")
            return f"{name} has a {q['noun']} promise of {q['promise'] or 'its stage'}{past}, and {acts}."
        waiting = n("waiting")
        open_ = (f"; {waiting:,} {'is' if waiting == 1 else 'are'} not {' or '.join(q['final'])}"
                 if isinstance(waiting, int) else "")
        return f"{name} is held by the platform and moves {q['moves']}{open_}, and {acts}."
    if shape == "map":
        p, placed, total = sig["places"], n("placed"), n("total")
        where = f" through {p['through']}" if p.get("through") else ""
        count = (f" — {placed:,} of {total:,} have a place" if isinstance(placed, int) and isinstance(total, int) else "")
        return f"{name} holds a latitude and a longitude{where}{count}."
    if shape == "one":
        o = sig["one"]
        kinds = ", ".join(x["label"].lower() for x in o["links"])
        more = " and more" if o["kinds"] > len(o["links"]) else ""
        return (f"Each {name.lower()} has a {_words(o['label'])} to find it by, and {o['kinds']} kinds of objects link "
                f"to it — {kinds}{more}.")
    if shape == "timeline":
        m, both = sig["moments"], n("both")
        count = f" — {both:,} hold both" if isinstance(both, int) else ""
        return f"Each {name.lower()} holds two moments, {_words(m['start'])} and {_words(m['end'])}{count}."
    return f"Figures over {_plural(name).lower()}, how they move and what they break into."


def measure(sig: dict, shapes: list[str], run: Callable[[dict], tuple[list[str], list[list[Any]], list[str]]]) -> dict:
    """The numbers the sentences say, each read through the object door: the queue's objects waiting in its window,
    the map's places, the timeline's objects holding both moments. A read refused or failed leaves its number out —
    the sentence says less, never a guess."""
    out: dict[str, Any] = {}

    def count(body: dict) -> Optional[int]:
        try:
            _, rows, _ = run({"object_type": sig["entity"], "measures": [{"name": "n", "agg": "count"}], **body})
        except Exception:  # noqa: BLE001 — a number the door would not give is left out of the sentence, not invented
            return None
        try:
            return int(float(rows[0][0])) if rows and rows[0] and rows[0][0] is not None else None
        except (TypeError, ValueError):
            return None
    q = sig.get("queue")
    if "queue" in shapes and q:
        if q["kind"] == "promise":
            out["waiting"] = count({"segment": q["overdue"],
                                    "filters": [{"path": q["placed"], "op": "in_last", "value": WINDOW_DAYS}]})
        else:
            out["waiting"] = count({"filters": [{"path": q["status"], "op": "not_in", "values": q["final"]}]})
    if "map" in shapes and sig.get("places"):
        out["total"] = count({})
        out["placed"] = count({"filters": [{"path": sig["places"]["lat"], "op": "not_null"},
                                           {"path": sig["places"]["lng"], "op": "not_null"}]})
    if "timeline" in shapes and sig.get("moments"):
        out["both"] = count({"filters": [{"path": sig["moments"]["start"], "op": "not_null"},
                                         {"path": sig["moments"]["end"], "op": "not_null"}]})
    return out
