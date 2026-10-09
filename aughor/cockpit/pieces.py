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


# ── the release a cockpit was composed against (the study's §8.7: checked against the release it is pinned to) ──

def depends(spec: Any, graph: Any) -> dict[tuple[str, str], list[str]]:
    """The ontology elements a spec's pieces read, as release elements ``(kind, id)`` — each with the pieces that read
    it. A table reads its entity and, for a segment, the declaration that derives it: a rule's own, a process's (its
    late, overdue and the rest), or the entity's verified segment."""
    out: dict[tuple[str, str], list[str]] = {}

    def add(kind: str, target: str, key: str) -> None:
        if target:
            out.setdefault((kind, target), []).append(key)
    for key, (kind, props) in pieces_of(spec).items():
        if kind == "ProcessBoard":
            add("process", str(props.get("process") or ""), key)
        elif kind == "ActionButton":
            add("action", str(props.get("action") or ""), key)
        elif kind == "ObjectTable":
            entity = _entity_id(graph, str(props.get("entity") or ""))
            add("entity", entity, key)
            segment = str(props.get("segment") or "")
            if segment:
                add(*_segment_source(graph, entity, segment), key)
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
    """What a reader is owed before a cockpit's pieces are read: the release it was composed against, the one in force,
    and every change published between them that touches an element its pieces read — with the class it was published
    as. None when the spec holds no piece, or pieces or releases are off (the read says nothing new)."""
    from aughor.kernel.flags import flag_enabled
    from aughor.ontology import release
    if not pieces_of(spec) or not flag_enabled(FLAG) or not release.enabled():
        return None
    schema = release.connection_scope(connection_id)
    rows = release.releases(connection_id, schema)
    graph = graph if graph is not None else _graph(connection_id)
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


def cockpits_reading(connection_id: str, names: set[str], *, graph: Optional[Any] = None) -> list[dict]:
    """Every cockpit on the connection, whoever keeps it, whose pieces read one of ``names`` — what a change waiting
    in the ontology's draft touches, beside its claims, cards and automations (Arc OC-2's release strip)."""
    from aughor.cockpit.versions import KIND, title_of
    from aughor.kernel.ledger import Ledger
    graph = graph if graph is not None else _graph(connection_id)
    out = []
    for row in Ledger.default().artifacts_of_kind(KIND, conn_id=connection_id, limit=1000):
        payload = row.get("payload") or {}
        spec = payload.get("spec")
        if payload.get("retired") or not pieces_of(spec):
            continue
        reads = depends(spec, graph)
        hit = sorted({key for (_, t), keys in reads.items() if t in names for key in keys}
                     | {key for key, (k, p) in pieces_of(spec).items() if k == "ObjectTable" and p.get("segment") in names})
        if hit:
            key = str(row.get("natural_key") or "")
            out.append({"cockpit": key.rsplit(":", 1)[-1], "title": title_of(spec), "pieces": hit})
    return out
