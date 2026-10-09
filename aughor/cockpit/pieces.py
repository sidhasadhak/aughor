"""Arc OC-4 — what only the platform knows about a cockpit's pieces bound to the ontology (ROADMAP §3.56).

A process board names a declared process, an objects table an entity (and perhaps a segment of it), an object detail
the table it follows, and an action button a declared action — each by id, never by copying what the id means
(`web/lib/cockpit/catalog.ts`). The web's rules check the shape; what they cannot know is checked here before a spec
is kept: that building cockpits from the ontology is on, and that every id resolves in the ontology this connection
serves now. A piece whose id stops resolving later says so where it is drawn.

And one law about who places them: a person, by hand. A model arranges a piece — moves it, resizes it, takes it off —
and never adds one or changes what it names, the canvas's law for a note and an image.
"""
from __future__ import annotations

import json
from typing import Any, Optional

PIECES = ("ProcessBoard", "ObjectTable", "ObjectDetail", "ActionButton")
FLAG = "ontology.cockpit_pieces"
_WORDS = {"ProcessBoard": "process board", "ObjectTable": "objects table", "ObjectDetail": "object detail",
          "ActionButton": "action button"}


def pieces_of(spec: Any) -> dict[str, tuple[str, dict]]:
    """Each ontology piece a spec holds, by element key: ``(type, props)``."""
    elements = spec.get("elements") if isinstance(spec, dict) else None
    return {key: (el["type"], el["props"]) for key, el in (elements or {}).items()
            if isinstance(el, dict) and el.get("type") in PIECES and isinstance(el.get("props"), dict)}


def _graph(connection_id: str):
    from aughor.routers.ontology import served_ontology_graph
    return served_ontology_graph(connection_id, None)


def not_resolved(connection_id: str, spec: Any, *, graph: Optional[Any] = None) -> list[str]:
    """A sentence for each ontology piece a spec holds that this connection cannot draw — what a keep is refused
    with. Empty when the spec holds none, whatever the flag says, so a cockpit without them keeps as it always did."""
    pieces = pieces_of(spec)
    if not pieces:
        return []
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled(FLAG):
        return [f"The cockpit holds {len(pieces)} piece(s) bound to the ontology, and building cockpits from the "
                "ontology is off on this install."]
    graph = graph if graph is not None else _graph(connection_id)
    if graph is None:
        return ["The cockpit holds pieces bound to the ontology, and no ontology is built for this connection."]
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_listing, find_object_type
    said: list[str] = []
    tables: dict[str, str] = {}
    for key, (kind, props) in pieces.items():
        if kind == "ProcessBoard" and props.get("process") not in (graph.processes or {}):
            said.append(f'The process board "{key}" names the process "{props.get("process")}", which this '
                        "connection does not declare.")
        elif kind == "ObjectTable":
            body = {"entity": props.get("entity"), "segment": props.get("segment") or "",
                    "columns": list(props.get("columns") or []), "order_by": props.get("sort") or "",
                    "descending": bool(props.get("descending")), "limit": 1}
            try:
                compiled = compile_object_listing(body, graph, overlay=_accepted_edits(connection_id))
                tables[key] = compiled.type_id
            except ObjectQueryRefused as exc:
                said.append(f'The objects table "{key}" cannot be read: {exc.reason}.')
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


def _table_of(spec: dict, button: str, pieces: dict[str, tuple[str, dict]]) -> str:
    """The objects table the detail holding ``button`` follows, or ""."""
    for key, (kind, props) in pieces.items():
        if kind == "ObjectDetail" and button in ((spec.get("elements") or {}).get(key) or {}).get("children", []):
            return str(props.get("follows") or "")
    return ""


def _accepted_edits(connection_id: str) -> list:
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
            said.append(f'The cockpit holds the {words} "{key}". A new cockpit holds none: a piece bound to the '
                        "ontology is the person's to place, by hand.")
        elif key not in was:
            said.append(f'The edit adds the {words} "{key}". A person places a piece bound to the ontology: you may '
                        "move one, resize it or take it off, never add one.")
        elif _named(was[key][1]) != _named(props):
            said.append(f'The edit changes what the {words} "{key}" names. A person chose it: move it, resize it or '
                        "take it off, never change what it reads.")
    return said


def _named(props: dict) -> str:
    """What a piece names — everything but its size, which is arrangement."""
    return json.dumps({k: v for k, v in props.items() if k != "size"}, sort_keys=True, default=str)
