"""Arc OC-6 — entities the platform owns: a case, a review, an assignment (decision (b), the user's call 2026-10-09).

Every entity before this read a warehouse: a table, or a keyed SELECT. An app's unit of work — the case a person opens
on a late order, who has it, where it stands — lives in no source a customer holds. A platform-owned entity is declared
like any other (`backing: {kind: "platform", properties: [...]}`) and its objects live in the EDIT LAYER: each is made
by a declared action that names it in `creates` and changed only by declared actions, every change a version of the
property it set — so a case's whole history reads back, its status moves only as its type declares
(`OntologyEntity.edit_states`), and a press against a version someone changed since is refused. No customer row moves.

The object door compiles SQL against a warehouse, so it refuses a platform-owned type and says why; the object page,
the listing and the cockpit's pieces read one through here. An object of another type a case names in a property
(`about: "order:6"`) is linked both ways: the case's page opens the order, the order's page lists its cases.

Arc AP-4 — and counted here: how many objects, or how many different values of a property, in all or by one property —
what a cockpit's figure and its filter column ask of a case queue (`query`). Anything more is refused and says so.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph

#: What the type's card and every refusal say of where its objects live.
NOTE = "held by the platform — every object made and changed by a declared action, each change kept"
#: The key every platform-owned object carries.
KEY = "id"
_REF = re.compile(r"^(?P<type>[A-Za-z][A-Za-z0-9_]*):(?P<pk>.+)$")


def is_platform(entity: Optional[OntologyEntity]) -> bool:
    return entity is not None and entity.backing is not None and entity.backing.kind == "platform"


def _word(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def declared_properties(declared: list[dict]) -> dict[str, EntityProperty]:
    """The properties a platform-owned type declares, with its key first."""
    out = {KEY: EntityProperty(name=KEY, display_name="Id", data_type="VARCHAR", semantic_type="key", is_primary_key=True)}
    for p in declared or []:
        name = str(p.get("name") or "").strip()
        if name and name != KEY:
            out[name] = EntityProperty(name=name, display_name=name.replace("_", " ").capitalize(),
                                       data_type=str(p.get("data_type") or "VARCHAR"),
                                       semantic_type=str(p.get("semantic_type") or "dimension"),
                                       description=str(p.get("description") or ""))
    return out


def objects_of(entity: OntologyEntity, overlay: Optional[list]) -> dict[str, dict[str, Any]]:
    """Every object of ``entity`` the edit layer holds: ``{pk: {property: edit}}``, newest object first."""
    out: dict[str, dict[str, Any]] = {}
    want = {_word(entity.api_name), _word(entity.id)}
    for e in sorted(overlay or [], key=lambda e: str(getattr(e, "created_at", "") or ""), reverse=True):
        if getattr(e, "kind", "") == "property" and _word(getattr(e, "object_type", "")) in want:
            out.setdefault(str(e.row_key), {})[str(e.column)] = e
    return out


def _value(edit: Any) -> Any:
    raw = str(edit.body).strip()
    return raw.lower() == "true" if raw.lower() in ("true", "false") else edit.body


def ref_of(value: Any, graph: OntologyGraph) -> Optional[tuple[OntologyEntity, str]]:
    """The object a value names as ``<type>:<key>`` — an order a case is about — or None."""
    m = _REF.match(str(value or "").strip())
    if not m:
        return None
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        return find_object_type(graph, m.group("type")), m.group("pk")
    except ObjectQueryRefused:
        return None


def instance(graph: OntologyGraph, entity: OntologyEntity, pk: str, overlay: Optional[list]):
    """One platform-owned object, read from the edit layer — `ObjectNotFound` when none has that key."""
    from aughor.semantic.object_instances import ObjectInstance, ObjectNotFound
    edits = objects_of(entity, overlay).get(str(pk))
    if not edits:
        raise ObjectNotFound(f"no {entity.id} {pk!r} — {NOTE}, and none has that id")
    properties = [{"name": KEY, "value": str(pk), "display_name": "Id", "semantic_type": "key", "data_type": "VARCHAR",
                   "unit": "", "description": ""}]
    links = []
    for name, prop in (entity.properties or {}).items():
        if name == KEY:
            continue
        e = edits.get(name)
        row = {"name": name, "value": _value(e) if e is not None else None, "display_name": prop.display_name or name,
               "semantic_type": "overlay", "data_type": prop.data_type, "unit": "", "description": e.note if e else ""}
        if e is not None:
            row["overlay"] = {"by": e.actor or e.source, "at": e.created_at, "note": e.note, "origin": e.origin,
                              "provenance": e.provenance(), "id": e.id, "version": e.version}
            named = ref_of(e.body, graph)
            if named is not None:
                links.append({"name": name, "business_name": "", "verb": "is about", "to": named[0].api_name,
                              "to_type": named[0].id, "cardinality": "N:1", "on": f"{name} names it",
                              "kind": "to-one", "usable": True, "pk": named[1]})
        properties.append(row)
    title_prop = next((n for n in ("title", "name", "subject") if n in edits), "")
    title = str(_value(edits[title_prop])) if title_prop else None
    return ObjectInstance(object_type=entity.api_name, type_id=entity.id, type_name=entity.display_name or entity.id,
                          key=KEY, pk=str(pk), title=title, properties=properties, links=links,
                          caveats=[f"{entity.display_name or entity.id} is {NOTE}"], platform=True,
                          display={"property": title_prop or KEY, "is_key": not title_prop,
                                   "value": title if title is not None else str(pk)})


#: The conditions read on a platform-owned type — a reader's search words among them (Arc AP-4).
OPS = ("=", "!=", "in", "not_in", "is_null", "not_null", "contains")
#: What a platform-owned type is counted by: how many, and how many different.
COUNTS = ("count", "count_distinct")


def _matches(value: Any, f: dict) -> bool:
    op, want = str(f.get("op") or "="), f.get("value")
    have = "" if value is None else str(value)
    if op == "contains":
        return str(want or "").strip().lower() in have.lower()
    if op == "=":
        return have == str(want)
    if op == "!=":
        return have != str(want)
    if op == "in":
        return have in [str(v) for v in (f.get("values") or want or [])]
    if op == "not_in":
        return have not in [str(v) for v in (f.get("values") or want or [])]
    if op == "is_null":
        return value is None
    if op == "not_null":
        return value is not None
    raise ValueError(f"a {op!r} condition is not read on a platform-owned type — {', '.join(OPS)} are")


def _refusal(entity: OntologyEntity, *, paths: list[str], filters: list[dict], segment: str = "") -> Optional[dict]:
    """Why a read of a platform-owned type cannot be made as asked — a segment, a property it does not declare, a
    condition it does not read — or None. Said before any object is read, so a check with none held refuses alike."""
    if segment:
        return {"path": "refused", "refused": f"{entity.id} is {NOTE}; a segment is read on a warehouse type"}
    unknown = [c for c in paths if c and c not in entity.properties]
    if unknown:
        return {"path": "refused", "refused": f"{entity.id} has no property {unknown[0]!r}",
                "available": sorted(entity.properties)}
    op = next((str(f.get("op") or "=") for f in filters if str(f.get("op") or "=") not in OPS), None)
    if op is not None:
        return {"path": "refused", "refused": f"a {op!r} condition is not read on a platform-owned type — "
                                              f"{', '.join(OPS)} are"}
    return None


def _values(entity: OntologyEntity, overlay: Optional[list], filters: list[dict]) -> list[tuple[str, dict[str, Any]]]:
    """Each object's key and the values its properties hold now, kept to those the conditions admit."""
    out = []
    for pk, edits in objects_of(entity, overlay).items():
        values = {n: (_value(e) if (e := edits.get(n)) is not None else None) for n in entity.properties if n != KEY}
        values[KEY] = pk
        if all(_matches(values.get(f.get("path")), f) for f in filters):
            out.append((pk, values))
    return out


def listing(entity: OntologyEntity, overlay: Optional[list], *, columns: list[str], filters: list[dict],
            order_by: str = "", descending: bool = False, offset: int = 0, limit: int = 50, segment: str = "") -> dict:
    """A page of a platform-owned type's objects, in the listing door's shape — or ``{"path": "refused", ...}``."""
    names = [c for c in (columns or [n for n in entity.properties if n != KEY][:4]) if c != KEY]
    refused = _refusal(entity, paths=names + [f.get("path", "") for f in filters], filters=filters, segment=segment)
    if refused:
        return refused
    if order_by and order_by not in [KEY, *names]:
        # the object door's own law: a page is sorted by a listed column, or by the key
        return {"path": "refused", "refused": f"order_by {order_by!r} is not a listed column", "available": [KEY, *names]}
    try:
        rows = [[pk, *(values.get(n) for n in names)] for pk, values in _values(entity, overlay, filters)]
    except ValueError as exc:
        return {"path": "refused", "refused": str(exc)}
    sort_at = ([KEY, *names].index(order_by) if order_by in [KEY, *names] else 0)
    rows.sort(key=lambda r: ("" if r[sort_at] is None else str(r[sort_at]), str(r[0])), reverse=descending)
    return {"path": "listed", "object_type": entity.api_name, "type_id": entity.id, "key": KEY, "title": "",
            "columns": [{"name": n, "path": n, "label": n.replace("_", " "), "type": entity.properties[n].data_type,
                         "edited": True} for n in names],
            "names": [KEY, *names], "rows": rows[offset:offset + limit], "total": len(rows), "offset": offset,
            "limit": limit, "segment_said": "", "plan": [f"list({entity.id}) from the edit layer — {NOTE}"],
            "caveats": [], "error": None, "sql": "", "count_sql": "", "dialect": "", "links": [], "overlay": []}


def query(entity: OntologyEntity, overlay: Optional[list], *, measures: list[dict], by: Optional[list[str]] = None,
          filters: Optional[list[dict]] = None, segment: str = "", time: str = "", grain: str = "") -> dict:
    """Arc AP-4 — a platform-owned type's objects counted, in the object door's shape: how many, or how many different
    values of a property, in all or by one property, kept to the conditions given — a case queue's open cases, and how
    many each assignee has. Read from the edit layer, never compiled into SQL; over days, a sum or a second grouping is
    refused, and says so."""
    by, filters = list(by or []), list(filters or [])
    paths = [*by, *(str(m.get("path") or "") for m in measures), *(str(f.get("path") or "") for f in filters)]
    refused = _refusal(entity, paths=paths, filters=filters, segment=segment)
    if refused:
        return refused
    if time or grain:
        return {"path": "refused", "refused": f"{entity.id} is {NOTE}; it is counted, never drawn over days"}
    if len(by) > 1:
        return {"path": "refused", "refused": f"{entity.id} is {NOTE}; it is counted by one property at most"}
    agg = next((str(m.get("agg") or "count") for m in measures if str(m.get("agg") or "count") not in COUNTS), None)
    if agg is not None:
        return {"path": "refused", "refused": f"a {agg} is not read on a platform-owned type — how many, and how many "
                                              "different, are"}
    if any(str(m.get("agg")) == "count_distinct" and not m.get("path") for m in measures):
        return {"path": "refused", "refused": "how many different names the property it counts"}
    names = [str(m.get("name") or f"m{i}") for i, m in enumerate(measures)]
    try:
        objects = [values for _, values in _values(entity, overlay, filters)]
    except ValueError as exc:
        return {"path": "refused", "refused": str(exc)}

    def measured(group: list[dict]) -> list[int]:
        return [len(group) if str(m.get("agg") or "count") == "count"
                else len({str(v.get(m["path"])) for v in group if v.get(m["path"]) is not None}) for m in measures]
    if by:
        groups: dict[Any, list[dict]] = {}
        for v in objects:
            groups.setdefault(v.get(by[0]), []).append(v)
        rows = [[value, *measured(group)] for value, group in groups.items()]
        rows.sort(key=lambda r: (-r[1], "" if r[0] is None else str(r[0])))
    else:
        rows = [measured(objects)]
    return {"path": "compiled", "sql": "", "dialect": "", "object_type": entity.api_name, "columns": [*by, *names],
            "dimensions": by, "measures": names, "plan": [f"count({entity.id}) from the edit layer — {NOTE}"],
            "links": [], "caveats": [], "overlay": [], "bindings": [], "rows": rows, "row_count": len(rows),
            "truncated": False, "error": None, "guard_receipts": []}


def referring(graph: OntologyGraph, overlay: Optional[list], entity: OntologyEntity, pk: str) -> list[dict]:
    """The platform-owned objects that name this object (`about: "order:6"`): what an order's page lists as its cases."""
    out = []
    for other in graph.entities.values():
        if not is_platform(other) or other.id == entity.id:
            continue
        for opk, edits in objects_of(other, overlay).items():
            for name, e in edits.items():
                named = ref_of(e.body, graph)
                if named is not None and named[0].id == entity.id and named[1] == str(pk):
                    out.append({"object_type": other.api_name, "type_id": other.id, "type_name": other.display_name,
                                "pk": opk, "via": name,
                                "summary": {n: _value(x) for n, x in edits.items() if n != name}})
    return out


def new_target(graph: OntologyGraph, entity_id: str) -> dict:
    """The object a `creates` action is about to make, as the executor's object map holds one: a fresh key, nothing
    set yet, and its type's declared moves (an object starts in each one's ``initial``)."""
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        entity = find_object_type(graph, entity_id)
    except ObjectQueryRefused as exc:
        raise ValueError(f"the action creates a {entity_id}, which is not declared here") from exc
    if not is_platform(entity):
        raise ValueError(f"the action creates a {entity.id}, which reads a warehouse — only a platform-owned type's "
                         "objects are made by an action")
    pk = f"{_word(entity.id)[:12]}-{uuid.uuid4().hex[:8]}"
    return {"object_type": entity.api_name, "type_id": entity.id, "pk": pk, "key": KEY, "table": entity.api_name,
            "title": None, "properties": {KEY: pk}, "source": [KEY], "edited": {},
            "state_machines": {k: v.model_dump() for k, v in (entity.edit_states or {}).items()}}
