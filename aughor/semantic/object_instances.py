"""ON-3 — instances: one object, resolved live through its backing (ROADMAP §3.15).

An object type (ON-1) says what its instances ARE; this module reads one of them. `get_object`
fetches ONE row through the type's backing — its table, or the keyed SELECT a human set — by its
primary key, at read time: no object store, no sync, no copy of the warehouse (§3.15's second law).

Its links are read the way ON-2's compiler reads them. A to-one link resolves to the linked object's
key, so a page can link straight to it; a to-many link resolves to a COUNT of its objects, listed a
page at a time on demand by `list_linked`; a link the compiler would refuse — unmeasured, N:N, or
touching a query backing — is shown with its reason and never traversed. Every statement here is
assembled from the graph plus a key literal typed by its column (`typed_literal`); nothing a caller
types reaches SQL as text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from aughor.ontology.cardinality import quote_ident
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph
from aughor.semantic.object_query import (
    ObjectLink,
    ObjectQueryRefused,
    backing_from,
    find_object_type,
    find_property,
    link_problem,
    object_links,
    typed_literal,
)

_MAX_PAGE = 200
#: Property-name fragments that make a column an object's human title, in preference order.
_TITLE_HINTS = ("full_name", "display_name", "name", "title", "label")


class ObjectNotFound(LookupError):
    """No instance has that key — an answer, not a failure."""


@dataclass
class ObjectInstance:
    object_type: str                    # the type's api name
    type_id: str
    type_name: str                      # the type's display name
    key: str                            # the key column
    pk: str
    title: Optional[str]                # the object's own name when the type carries one
    properties: list[dict]
    links: list[dict]
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"object_type": self.object_type, "type_id": self.type_id, "type_name": self.type_name,
                "key": self.key, "pk": self.pk, "title": self.title, "properties": list(self.properties),
                "links": list(self.links), "caveats": list(self.caveats)}


def _key_of(entity: OntologyEntity) -> str:
    backing = entity.backing
    key = (backing.primary_key if backing is not None else "") or entity.identity_key
    if not key:
        raise ObjectQueryRefused(f"object type {entity.id} declares no key, so it has no instances to open")
    return key


def _key_property(entity: OntologyEntity, column: str) -> EntityProperty:
    return find_property(entity, column) or EntityProperty(name=column)


def _value(row: dict, column: str) -> Any:
    if column in row:
        return row[column]
    low = column.lower()
    return next((v for k, v in row.items() if k.lower() == low), None)


def _read(db: Any, sql: str, what: str):
    result = db.execute("object_instance", sql)
    if getattr(result, "error", None):
        raise ObjectQueryRefused(f"{what} could not be read: {result.error}"[:300])
    return result


def title_column(entity: OntologyEntity) -> Optional[str]:
    """The column that names an instance (`full_name`, `product_name`, `brand`…), or None. A
    deterministic reading of the profile — a text or dimension property whose name says it is a
    name — never a guess about the data."""
    candidates = [n for n, p in (entity.properties or {}).items()
                  if (p.semantic_type or "") in ("dimension", "text") and not p.is_primary_key]
    for hint in _TITLE_HINTS:
        for name in candidates:
            if hint in name.lower():
                return name
    return None


def _fetch_row(db: Any, entity: OntologyEntity, pk: str) -> tuple[dict, list[str], bool]:
    key = _key_of(entity)
    prop = _key_property(entity, key)
    sql = (f"SELECT * FROM {backing_from(entity, 't0')} "
           f"WHERE t0.{quote_ident(prop.name)} = {typed_literal(str(pk), prop, key)} LIMIT 2")
    result = _read(db, sql, f"{entity.id} {pk!r}")
    rows = list(result.rows or [])
    if not rows:
        raise ObjectNotFound(f"no {entity.id} has {key} = {pk!r}")
    columns = list(result.columns or [])
    return dict(zip(columns, rows[0])), columns, len(rows) > 1


def _link_view(db: Any, link: ObjectLink, row: dict) -> dict:
    view = {"name": link.name, "to": link.target.api_name, "to_type": link.target.id,
            "cardinality": link.label, "on": f"{link.local_col} = {link.remote_col}",
            "kind": "to-one" if link.to_one else "to-many"}
    problem = link_problem(link)
    if problem:
        return {**view, "usable": False, "why_not": problem}
    value = _value(row, link.local_col)
    if value is None:
        return {**view, "usable": True, **({"pk": None} if link.to_one else {"count": 0})}
    remote = _key_property(link.target, link.remote_col)
    literal = typed_literal(str(value), remote, link.remote_col)
    source = backing_from(link.target, "l")
    if link.to_one:
        target_key = _key_of(link.target)
        if link.remote_col.lower() == target_key.lower():
            return {**view, "usable": True, "pk": str(value)}
        found = _read(db, f"SELECT l.{quote_ident(target_key)} FROM {source} "
                          f"WHERE l.{quote_ident(link.remote_col)} = {literal} LIMIT 1", link.describe())
        return {**view, "usable": True, "pk": str(found.rows[0][0]) if found.rows else None}
    counted = _read(db, f"SELECT COUNT(*) FROM {source} WHERE l.{quote_ident(link.remote_col)} = {literal}",
                    link.describe())
    return {**view, "usable": True, "count": int(counted.rows[0][0]) if counted.rows else 0}


def get_object(graph: OntologyGraph, db: Any, object_type: str, pk: str) -> ObjectInstance:
    """One object — its properties, and its links resolved to a key or a count."""
    entity = find_object_type(graph, object_type)
    row, columns, repeated = _fetch_row(db, entity, pk)
    key = _key_of(entity)
    caveats: list[str] = []
    if repeated:
        note = (entity.backing.verification_note if entity.backing is not None else "") or "unmeasured"
        caveats.append(f"{key} = {pk!r} matches more than one {entity.id} row — the key is not unique "
                       f"({note}); showing the first")
    properties = []
    for column in columns:
        prop = find_property(entity, column)
        properties.append({"name": column, "value": row[column],
                           "display_name": (prop.display_name if prop else "") or column,
                           "semantic_type": prop.semantic_type if prop else "",
                           "data_type": prop.data_type if prop else "",
                           "unit": prop.unit if prop else "",
                           "description": prop.description if prop else ""})
    title_col = title_column(entity)
    title = _value(row, title_col) if title_col else None
    links = [_link_view(db, link, row) for link in object_links(graph, entity)]
    return ObjectInstance(object_type=entity.api_name, type_id=entity.id,
                          type_name=entity.display_name or entity.id, key=key, pk=str(pk),
                          title=str(title) if title is not None else None,
                          properties=properties, links=links, caveats=caveats)


def _find_link(graph: OntologyGraph, entity: OntologyEntity, name: str) -> ObjectLink:
    links = object_links(graph, entity)
    low = (name or "").strip().lower()
    named = [x for x in links if x.name.lower() == low]
    reaching = [x for x in links if low in (x.target.api_name.lower(), x.target.id.lower())]
    chosen = named or reaching
    if len(chosen) != 1:
        names = sorted(x.name for x in links)
        what = "names several links" if chosen else "is not a link"
        raise ObjectQueryRefused(f"'{name}' {what} from {entity.id} — its links: {', '.join(names) or 'none'}",
                                 names)
    return chosen[0]


def list_linked(graph: OntologyGraph, db: Any, object_type: str, pk: str, link: str, *,
                limit: int = 50, offset: int = 0) -> dict:
    """One page of the objects a link reaches from one object — refused when the link is."""
    entity = find_object_type(graph, object_type)
    chosen = _find_link(graph, entity, link)
    problem = link_problem(chosen)
    if problem:
        raise ObjectQueryRefused(problem)
    limit = max(1, min(int(limit), _MAX_PAGE))
    offset = max(0, int(offset))
    row, _, _ = _fetch_row(db, entity, pk)
    target = chosen.target
    target_key = _key_of(target)
    base = {"link": chosen.name, "object_type": target.api_name, "type_id": target.id,
            "type_name": target.display_name or target.id, "key": target_key,
            "title_column": title_column(target), "cardinality": chosen.label,
            "offset": offset, "limit": limit}
    value = _value(row, chosen.local_col)
    if value is None:
        return {**base, "columns": [], "rows": [], "has_more": False}
    remote = _key_property(target, chosen.remote_col)
    source = backing_from(target, "l")
    sql = (f"SELECT * FROM {source} WHERE l.{quote_ident(chosen.remote_col)} = "
           f"{typed_literal(str(value), remote, chosen.remote_col)} "
           f"ORDER BY l.{quote_ident(target_key)} LIMIT {limit + 1} OFFSET {offset}")
    result = _read(db, sql, chosen.describe())
    rows = list(result.rows or [])
    return {**base, "columns": list(result.columns or []), "rows": rows[:limit], "has_more": len(rows) > limit}
