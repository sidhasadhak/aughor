"""Arc OC-4 — what only the platform knows about a dashboard's pieces bound to the ontology (ROADMAP §3.56).

A process board names a declared process, an objects table an entity (and perhaps a segment of it), an object detail
the table it follows, and an action button a declared action — each by id, never by copying what the id means
(`web/lib/cockpit/catalog.ts`). The web's rules check the shape; what they cannot know is checked here before a spec
is kept: that building dashboards from the ontology is on, and that every id resolves in the ontology this connection
serves now. A piece whose id stops resolving later says so where it is drawn.

And one law about who places them: a person, by hand. A model arranges a piece — moves it, resizes it, takes it off —
and never adds one or changes what it names, the canvas's law for a note and an image.

Since 2026-10-10 three more read an entity's objects for a dashboard started from an object
(`aughor/dashboards/from_object.py`): a filter column over its categories, a figure and a chart of objects per day. They
are checked the same way, and need their own flag beside this one.

Arc AP-4 adds the pieces the builder's picker offers — a list of objects as cards, a map, a timeline, a choose-one and a
search. Each is checked as a table is, through the object door's listing over the served ontology; a map's places must
be numbers and a timeline's moments moments. They need the structure's flag beside this one (`app_pieces`). So does a
drawer, which holds pieces beside the page and opens on a chosen object: a person places it, as they place a piece.
"""
from __future__ import annotations

import json
from typing import Any, Optional

PIECES = ("ProcessBoard", "ObjectTable", "ObjectDetail", "ActionButton", "ObjectFilters", "ObjectFigure",
          "ObjectChart", "ActionButtons", "ObjectList", "ObjectMap", "ObjectTimeline", "ChooseOne", "ObjectSearch",
          "Drawer")
FLAG = "ontology.dashboard_pieces"
#: The pieces of a cockpit started from an object — refused unless its flag is on too.
FROM_OBJECT = ("ObjectFilters", "ObjectFigure", "ObjectChart")
_WORDS = {"ProcessBoard": "process board", "ObjectTable": "objects table", "ObjectDetail": "object detail",
          "ActionButton": "action button", "ObjectFilters": "filter column", "ObjectFigure": "figure",
          "ObjectChart": "chart", "ActionButtons": "action buttons", "ObjectList": "object list", "ObjectMap": "map",
          "ObjectTimeline": "timeline", "ChooseOne": "choose-one", "ObjectSearch": "search", "Drawer": "drawer"}
#: Arc AP-4 — the pieces that list a set's objects as a table does: the props naming the properties each lists — a list's
#: sort among them, since the object door sorts by a listed property only — and the prop it is ordered by.
LISTED = {"ObjectList": (("title", "figure", "mark", "sort"), "sort"), "ObjectMap": (("lat", "lng", "label"), ""),
          "ObjectTimeline": (("label", "start", "end"), "start"), "ChooseOne": (("label",), "label")}
#: The properties a map places by and a timeline draws between, and what each must hold.
_HOLDS = {"ObjectMap": {"lat": "number", "lng": "number"}, "ObjectTimeline": {"start": "moment", "end": "moment"}}
#: The pieces that read an entity and a segment — their own, or a named set's.
SEGMENTED = ("ObjectTable", "ObjectList", "ObjectMap", "ObjectTimeline", "ChooseOne")


def title_of(kind: str, props: dict) -> str:
    """A piece as a person approving an edit reads it, by what it names: "Process board · order fulfilment"."""
    named = {"ProcessBoard": props.get("process"), "ActionButton": props.get("action"),
             "ObjectTable": ", ".join(str(v) for v in (props.get("entity") or props.get("set"), props.get("segment")) if v),
             "ObjectFilters": props.get("entity"), "ObjectFigure": props.get("label"),
             "ObjectChart": props.get("label"), "ObjectSearch": props.get("label"), "Drawer": props.get("title"),
             **{k: props.get("entity") or props.get("set") for k in LISTED},
             "ActionButtons": ", ".join(str(b.get("label") or b.get("action")) for b in props.get("buttons") or []
                                        if isinstance(b, dict))}.get(kind)
    words = _WORDS.get(kind, kind).capitalize()
    return f"{words} · {str(named).replace('_', ' ')}" if named else words


def pieces_of(spec: Any) -> dict[str, tuple[str, dict]]:
    """Each ontology piece a spec holds, by element key: ``(type, props)``."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    return {key: (el["type"], el["props"]) for key, el in (elements or {}).items()
            if isinstance(el, dict) and el.get("type") in PIECES and isinstance(el.get("props"), dict)}


def served_graph(connection_id: str):
    from aughor.routers.ontology import served_ontology_graph
    return served_ontology_graph(connection_id, None)


def _scope(props: dict, sets: dict) -> tuple[str, str, list]:
    """The entity, segment and conditions a piece reads (Arc AP-2): its named set's, read as the web reads it, or the
    entity and segment it names itself — an unread set reading as nothing, its own refusal said by the wiring check."""
    name = props.get("set")
    if name:
        s = sets.get(name) or {}
        return str(s.get("entity") or ""), str(s.get("segment") or ""), list(s.get("filters") or [])
    return str(props.get("entity") or ""), str(props.get("segment") or ""), []


def not_resolved(connection_id: str, spec: Any, *, graph: Optional[Any] = None,
                 wiring: Optional[dict] = None) -> list[str]:
    """A sentence for each ontology piece a spec holds that this connection cannot draw — what a keep is refused
    with. Empty when the spec holds none, whatever the flag says, so a dashboard without them keeps as it always did."""
    pieces = pieces_of(spec)
    if not pieces:
        return []
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled(FLAG):
        return [f"The dashboard holds {len(pieces)} piece(s) bound to the ontology, and building dashboards from the "
                "ontology is off on this install."]
    from aughor.dashboards.from_object import FLAG as FROM_OBJECT_FLAG
    late = [key for key, (kind, _) in pieces.items() if kind in FROM_OBJECT]
    if late and not flag_enabled(FROM_OBJECT_FLAG):
        return [f"The dashboard holds {len(late)} filter column, figure or chart piece(s), and starting a dashboard from "
                "an object is off on this install."]
    graph = graph if graph is not None else served_graph(connection_id)
    if graph is None:
        return ["The dashboard holds pieces bound to the ontology, and no ontology is built for this connection."]
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    said: list[str] = []
    tables: dict[str, str] = {}
    sets = (wiring or {}).get("sets") or {}
    for key, (kind, props) in pieces.items():
        if props.get("set") and not (sets.get(props["set"]) or {}).get("entity"):
            continue                                    # a set that cannot be read is said once, by the wiring check
        if kind in FROM_OBJECT:
            said += _from_object_read(key, kind, props, graph, connection_id, sets)
        if kind == "ProcessBoard" and props.get("process") not in (graph.processes or {}):
            said.append(f'The process board "{key}" names the process "{props.get("process")}", which this '
                        "connection does not declare.")
        elif kind == "ObjectTable":
            entity, segment, conditions = _scope(props, sets)
            body = {"entity": entity, "segment": segment, "filters": conditions,
                    "columns": list(props.get("columns") or []), "order_by": props.get("sort") or "",
                    "descending": bool(props.get("descending")), "limit": 1}
            try:
                tables[key], _ = check_listing(body, graph, connection_id)
            except ObjectQueryRefused as exc:
                said.append(f'The objects table "{key}" cannot be read: {exc.reason}.')
        elif kind in LISTED:
            refused, listed = _listed_read(key, kind, props, graph, connection_id, sets)
            said += refused
            if listed:
                tables[key] = listed
        elif kind == "ObjectSearch":
            body = {"entity": str(props.get("entity") or ""), "limit": 1,
                    "filters": [{"path": str(props.get("path") or ""), "op": "contains", "value": "a"}]}
            try:
                check_listing(body, graph, connection_id)
            except ObjectQueryRefused as exc:
                said.append(f'The search "{key}" cannot be read: {exc.reason}.')
    for key, (kind, props) in pieces.items():
        if kind != "ActionButton":
            continue
        action = next((a for a in graph.declared_actions() if a.id == props.get("action")), None)
        if action is None:
            said.append(f'The action button "{key}" names the action "{props.get("action")}", which this connection '
                        "does not declare.")
            continue
        table = _table_of(spec, key, pieces)
        if table in tables:
            try:
                on = find_object_type(graph, action.entity or action.object_type).id
            except ObjectQueryRefused:
                on = ""
            if on != tables[table]:
                said.append(f'The action button "{key}" runs "{action.id}" on {on or "no entity"}, and the detail it '
                            f"sits in shows {tables[table]} objects.")
    return said


def _from_object_probes(kind: str, props: dict, sets: Optional[dict] = None) -> list[tuple[str, dict]]:
    """The object queries a filter column, a figure or a chart makes, each as what a refusal names and its body — over
    its named set's entity, segment and conditions when it reads one (Arc AP-2)."""
    entity, segment, conditions = _scope(props, sets or {})
    scope = {"segment": segment, "filters": conditions} if (segment or conditions) else {}
    count = {"name": "n", "agg": "count"}
    if kind == "ObjectFilters":
        # counted within its set when it names one (Arc AP-2), else over every object of its entity, as before sets
        paths = [p.get("path") if isinstance(p, dict) else p for p in props.get("properties") or []]
        return [(f'its filter on "{p}"', {"object_type": entity, **scope, "measures": [count], "by": [p]}) for p in paths]
    if kind == "ObjectFigure":
        return [("it", {"object_type": entity, **scope, "measures": [{"name": "n", "agg": props.get("agg") or "count",
                                                                       "path": props.get("path") or ""}]})]
    # a chart's bars: how many objects, or what its measure says (Arc AP-1), per day — split by a property when it says one
    measure = {"name": "n", "agg": props.get("agg") or "count", "path": props.get("path") or ""}
    split = {"by": [props["split"]]} if props.get("split") else {}
    return [("it", {"object_type": entity, **scope, "measures": [measure], "time": props.get("time") or "",
                    "grain": "day", **split})]


def _from_object_read(key: str, kind: str, props: dict, graph: Any, connection_id: str,
                      sets: Optional[dict] = None) -> list[str]:
    """A sentence for each query a filter column, a figure or a chart would make that the compiler refuses — compiled
    over the served ontology, never run."""
    from aughor.semantic.object_query import ObjectQueryRefused
    said = []
    for what, body in _from_object_probes(kind, props, sets):
        try:
            check_query(body, graph, connection_id)
        except ObjectQueryRefused as exc:
            said.append(f'The {_WORDS[kind]} "{key}" cannot be read — {what}: {exc.reason}.')
    return said


def _platform(graph: Any, name: str):
    """The platform-owned type ``name`` names — a case, held in the edit layer (Arc OC-6) — or None."""
    from aughor.ontology.platform_objects import is_platform
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        entity = find_object_type(graph, name)
    except ObjectQueryRefused:
        return None
    return entity if is_platform(entity) else None


def check_listing(body: dict, graph: Any, connection_id: str) -> tuple[str, list[dict]]:
    """The type a listing reads and the columns it lists — compiled over the served ontology, never run — or
    `ObjectQueryRefused` with why. A platform-owned type is checked as its own listing reads it, from the edit layer,
    with no object read (Arc AP-4: a case queue is kept like any dashboard)."""
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_listing
    entity = _platform(graph, str(body.get("entity") or ""))
    if entity is not None:
        from aughor.ontology.platform_objects import listing
        page = listing(entity, [], columns=list(body.get("columns") or []), filters=list(body.get("filters") or []),
                       order_by=str(body.get("order_by") or ""), segment=str(body.get("segment") or ""), limit=1)
        if page["path"] == "refused":
            raise ObjectQueryRefused(page["refused"], page.get("available"))
        return entity.id, page["columns"]
    compiled = compile_object_listing(body, graph, overlay=accepted_edits(connection_id))
    return compiled.type_id, compiled.columns


def check_query(body: dict, graph: Any, connection_id: str) -> None:
    """An object query compiled over the served ontology, never run — `ObjectQueryRefused` with why. A platform-owned
    type is checked as the query door counts it, from the edit layer (Arc AP-4)."""
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query
    entity = _platform(graph, str(body.get("object_type") or ""))
    if entity is not None:
        from aughor.ontology.platform_objects import query
        out = query(entity, [], measures=list(body.get("measures") or []), by=list(body.get("by") or []),
                    filters=list(body.get("filters") or []), segment=str(body.get("segment") or ""),
                    time=str(body.get("time") or ""), grain=str(body.get("grain") or ""))
        if out["path"] == "refused":
            raise ObjectQueryRefused(out["refused"], out.get("available"))
        return
    compile_object_query(body, graph, overlay=accepted_edits(connection_id))


def listed_columns(kind: str, props: dict) -> list[str]:
    """The properties a list, a map, a timeline or a choose-one asks the object door for, each once, in its order."""
    out: list[str] = []
    for name in LISTED[kind][0]:
        path = str(props.get(name) or "")
        if path and path not in out:
            out.append(path)
    return out


def _holds(column: dict, what: str) -> bool:
    """Whether a listed column holds numbers, or moments — read as the compiler reads a property's kind."""
    from aughor.semantic.object_query import NUMERIC_TYPES
    kind = str(column.get("type") or "").upper()
    if what == "number":
        return any(t in kind for t in NUMERIC_TYPES)
    return column.get("role") == "timestamp" or "DATE" in kind or "TIME" in kind


def _listed_read(key: str, kind: str, props: dict, graph: Any, connection_id: str, sets: dict) -> tuple[list[str], str]:
    """A sentence when the object door refuses what a list, a map, a timeline or a choose-one lists — compiled over the
    served ontology, never run — or when a map places by a property that holds no number, or a timeline draws between
    ones that hold no moment; and the type it lists, which a detail following it shows. A property of no known type is
    not refused: the piece says what it could not draw."""
    from aughor.semantic.object_query import ObjectQueryRefused
    entity, segment, conditions = _scope(props, sets)
    by = LISTED[kind][1]
    body = {"entity": entity, "segment": segment, "filters": conditions, "columns": listed_columns(kind, props),
            "order_by": str(props.get(by) or "") if by else "", "descending": bool(props.get("descending")), "limit": 1}
    try:
        type_id, columns = check_listing(body, graph, connection_id)
    except ObjectQueryRefused as exc:
        return [f'The {_WORDS[kind]} "{key}" cannot be read: {exc.reason}.'], ""
    typed = {c.get("path"): c for c in columns}
    said = []
    for name, what in _HOLDS.get(kind, {}).items():
        column = typed.get(str(props.get(name) or ""))
        if column and column.get("type") and not _holds(column, what):
            said.append(f'The {_WORDS[kind]} "{key}" reads its {name} from "{props.get(name)}", which holds no {what}.')
    return said, type_id


def _table_of(spec: dict, button: str, pieces: dict[str, tuple[str, dict]]) -> str:
    """The piece the detail holding ``button`` follows — a table, or since Arc AP-4 a list, a map or a timeline — or ""."""
    for key, (kind, props) in pieces.items():
        if kind == "ObjectDetail" and button in ((spec.get("elements") or {}).get(key) or {}).get("children", []):
            return str(props.get("follows") or "")
    return ""


def accepted_edits(connection_id: str) -> list:
    from aughor.actions.overlay import accepted_object_edits
    return accepted_object_edits(connection_id)


def pieces_written(before: Any, after: Any, *, new: bool) -> list[str]:
    """The sentences for what a model's draft did to the ontology's pieces that only a person may do: add one, or
    change what one names. Moving, resizing and taking one off are arrangement, and pass."""
    was = {} if new else pieces_of(before)
    said = []
    for key, (kind, props) in pieces_of(after).items():
        words = _WORDS[kind]
        if new:
            said.append(f'The dashboard holds the {words} "{key}". A new dashboard holds none: a piece bound to the '
                        "ontology is the person's to place, by hand.")
        elif key not in was:
            said.append(f'The edit adds the {words} "{key}". A person places a piece bound to the ontology: you may '
                        "move one, resize it or take it off, never add one.")
        elif _named(was[key][1]) != _named(props):
            said.append(f'The edit changes what the {words} "{key}" names. A person chose it: move it, resize it or '
                        "take it off, never change what it reads.")
    return said


#: A piece's room — by name, or in columns and rows on a section's grid (Arc AP-1). Changing it is arrangement.
_ROOM = frozenset({"size", "w", "h"})


def _named(props: dict) -> str:
    """What a piece names — everything but its room, which is arrangement."""
    return json.dumps({k: v for k, v in props.items() if k not in _ROOM}, sort_keys=True, default=str)


# ── the release a cockpit was composed against (the study's §8.7: checked against the release it is pinned to) ──

def _set_scope(spec: Any, name: str) -> tuple[str, str]:
    """The entity and segment a named set reads, down the sets it starts from (Arc AP-2) — what a release a piece reads
    through a set is tracked by. Its conditions are read by the web (`sets.ts`); an entity and a segment are all a
    release names."""
    sets = (spec.get("sets") if isinstance(spec, dict) else None) or {}
    seen: set[str] = set()
    segment = ""
    while name and name not in seen and isinstance(sets.get(name), dict):
        seen.add(name)
        s = sets[name]
        segment = segment or str(s.get("segment") or "")
        if s.get("entity"):
            return str(s["entity"]), segment
        name = str(s.get("from") or "")
    return "", segment


def _effective(spec: Any, props: dict) -> dict:
    """A piece's props with a named set's entity and segment in place, for what reads an entity and a segment."""
    if not props.get("set"):
        return props
    entity, segment = _set_scope(spec, str(props["set"]))
    return {**props, "entity": entity, "segment": segment}


def depends(spec: Any, graph: Any) -> dict[tuple[str, str], list[str]]:
    """The ontology elements a spec's pieces read, as release elements ``(kind, id)`` — each with the pieces that read
    it. A table reads its entity and, for a segment, the declaration that derives it: a rule's own, a process's (its
    late, overdue and the rest), or the entity's verified segment."""
    out: dict[tuple[str, str], list[str]] = {}

    def add(kind: str, target: str, key: str) -> None:
        if target:
            out.setdefault((kind, target), []).append(key)
    for key, (kind, props) in pieces_of(spec).items():
        props = _effective(spec, props)
        if kind == "ProcessBoard":
            add("process", str(props.get("process") or ""), key)
        elif kind == "ActionButton":
            add("action", str(props.get("action") or ""), key)
        elif kind in FROM_OBJECT:
            add("entity", _entity_id(graph, str(props.get("entity") or "")), key)
        elif kind in SEGMENTED:
            entity = _entity_id(graph, str(props.get("entity") or ""))
            add("entity", entity, key)
            segment = str(props.get("segment") or "")
            if segment:
                add(*_segment_source(graph, entity, segment), key)
        elif kind == "ObjectSearch":
            add("entity", _entity_id(graph, str(props.get("entity") or "")), key)
    return out


def _entity_id(graph: Any, name: str) -> str:
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        return find_object_type(graph, name).id if graph is not None else name
    except ObjectQueryRefused:
        return name


def _segment_source(graph: Any, entity: str, segment: str) -> tuple[str, str]:
    if graph is not None and segment in (graph.rules or {}):
        return "rule", segment
    if graph is not None:
        from aughor.ontology.derived import overdue_derivations, process_derivations
        for process in (graph.processes or {}).values():
            derived = {d.name for d in process_derivations(process).segments} | {d.name for d in overdue_derivations(process)}
            if segment in derived:
                return "process", process.id
    return "object_set", f"{entity}::{segment}"


def _named_set(spec: Any) -> list[str]:
    return sorted(f"{kind}:{_named(props)}" for kind, props in pieces_of(spec).values())


def pin_for(connection_id: str, before: dict, spec: Any, *, repin: bool = False) -> str:
    """The release a kept version is pinned to: none when it holds no piece; the release in force now when a person
    re-pins, when it had none, or when what its pieces name changed (they were composed against now); otherwise the
    version before's — resizing a piece is not reading the ontology again."""
    if not pieces_of(spec):
        return ""
    from aughor.ontology import release
    if not release.enabled():
        return ""
    prior = str((before or {}).get("ontology_release") or "")
    if repin or not prior or _named_set((before or {}).get("spec")) != _named_set(spec):
        return release.current_id_for_connection(connection_id)
    return prior


def _number(release_id: str) -> Optional[int]:
    tail = release_id.rsplit("@", 1)[-1] if "@" in release_id else ""
    return int(tail) if tail.isdigit() else None


def since(connection_id: str, spec: Any, pinned: str, *, graph: Optional[Any] = None) -> Optional[dict]:
    """What a reader is owed before a dashboard's pieces are read: the release it was composed against, the one in force,
    and every change published between them that touches an element its pieces read — with the class it was published
    as. None when the spec holds no piece, or pieces or releases are off (the read says nothing new)."""
    from aughor.kernel.flags import flag_enabled
    from aughor.ontology import release
    if not pieces_of(spec) or not flag_enabled(FLAG) or not release.enabled():
        return None
    schema = release.connection_scope(connection_id)
    rows = release.releases(connection_id, schema)
    graph = graph if graph is not None else served_graph(connection_id)
    reads = depends(spec, graph)
    after = _number(pinned)
    out = []
    for row in reversed(rows):
        if after is None or row["number"] <= after:
            continue
        for change in row.get("changes") or []:
            kind, target = _element(str(change.get("element") or ""))
            if (kind, target) in reads:
                out.append({"release": row["id"], "number": row["number"], "kind": kind, "target_id": target,
                            "change": change.get("change", ""), "class": change.get("class", ""),
                            "pieces": reads[(kind, target)]})
    return {"pinned": pinned, "current": rows[0]["id"] if rows else "", "changes": out}


def _element(key: str) -> tuple[str, str]:
    """``ontology:<conn>/<schema>/<kind>/<id>`` → ``(kind, id)``."""
    parts = key.removeprefix("ontology:").split("/", 3)
    return (parts[2], parts[3]) if len(parts) == 4 else ("", "")


def dashboards_reading(connection_id: str, names: set[str], *, graph: Optional[Any] = None) -> list[dict]:
    """Every dashboard on the connection, whoever keeps it, whose pieces read one of ``names`` — what a change waiting
    in the ontology's draft touches, beside its claims, cards and automations (Arc OC-2's release strip)."""
    from aughor.dashboards.versions import KIND, title_of
    from aughor.kernel.ledger import Ledger
    graph = graph if graph is not None else served_graph(connection_id)
    out = []
    for row in Ledger.default().artifacts_of_kind(KIND, conn_id=connection_id, limit=1000):
        payload = row.get("payload") or {}
        spec = payload.get("spec")
        if payload.get("retired") or not pieces_of(spec):
            continue
        reads = depends(spec, graph)
        hit = sorted({key for (_, t), keys in reads.items() if t in names for key in keys}
                     | {key for key, (k, p) in pieces_of(spec).items()
                        if k in SEGMENTED and _effective(spec, p).get("segment") in names})
        if hit:
            key = str(row.get("natural_key") or "")
            out.append({"cockpit": key.rsplit(":", 1)[-1], "title": title_of(spec), "pieces": hit})
    return out
