"""Arc AP-8 — variables, as Workshop has them (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9.2).

A dashboard's values were the author's, set once ("Window · 14 days"), and only a number of days reached a set's condition.
A value now says where it comes from: the author; the reader, on the page — from the choices the author offers, or as
they type — kept in their own browser, never in the dashboard; how many objects one of the dashboard's sets holds; or a
property of the object a reader chose. A set compares any value as its kind allows, and a query of the person's own reads
one as a bound parameter, never pasted into its statement (`queries.py`).

The web's rules hold a value's shape — what each kind holds, that a count counts a set the dashboard has, that a choice a
value reads is made, that no value counts a set that reads it back (`web/lib/dashboards/rules.ts`). What only the platform
knows is checked here before a spec is kept: that the property a value reads off a chosen object is one its entity has.
"""
from __future__ import annotations

from typing import Any, Optional

def _named(spec: Any, key: str) -> dict:
    found = spec.get(key) if isinstance(spec, dict) else None
    return found if isinstance(found, dict) else {}


def unheld(spec: Any, card_ids: Any) -> list[str]:
    """A sentence for each query of a person's own the spec places that reads a value the dashboard does not hold — a value
    taken away while a query still reads it, or a card placed on a dashboard that never held its value."""
    from aughor.dashboards.queries import params_of
    from aughor.cards.store import get_card
    held = set(_named(spec, "values"))
    said: list[str] = []
    for cid in card_ids or ():
        card = get_card(str(cid))
        missing = [n for n in params_of(getattr(card, "sql", "") or "") if n not in held] if card is not None else []
        if missing:
            said.append(f'The card "{card.title}" reads {", ".join("{{" + n + "}}" for n in missing)}, and this dashboard '
                        f"holds no value of {'that name' if len(missing) == 1 else 'those names'}.")
    return said


def not_resolved(connection_id: str, spec: Any, *, graph: Optional[Any] = None, wiring: Optional[dict] = None) -> list[str]:
    """A sentence for each value read off a chosen object whose property that object's entity does not have; (Arc AP-8c)
    for each value summed over a set by a property its objects do not have, or have as something other than a number;
    and for each value read from a query that is not a query of the person's own the dashboard places, or reads itself."""
    wired = {name: v for name, v in ((wiring or {}).get("values") or {}).items() if isinstance(v, dict)}
    said = _queries_unread(spec, {n: v for n, v in wired.items() if v.get("by") == "query"})
    chosen = {name: v for name, v in wired.items() if v.get("by") in ("chosen", "sum")}
    if not chosen:
        return said
    from aughor.dashboards.pieces import served_graph
    from aughor.semantic.object_query import ObjectQueryRefused, find_computed, find_object_type, find_property
    graph = graph if graph is not None else served_graph(connection_id)
    if graph is None:
        return said + ["The dashboard reads a property of its objects, and no ontology is built for this connection."]
    for name, v in chosen.items():
        path, entity_name = str(v.get("path") or ""), str(v.get("entity") or "")
        summed = v.get("by") == "sum"
        try:
            entity = find_object_type(graph, entity_name)
        except ObjectQueryRefused:
            said.append(f'The value "{name}" reads {path} of an object of {entity_name or "no entity"}, which this connection '
                        "does not serve.")
            continue
        if summed:
            # the door compiles the sum it would read — a property it cannot reach, or cannot add up, is said its way
            why = _sum_refused(connection_id, graph, entity.id, path)
            if why:
                said.append(f'The value "{name}" sums {path} over the set "{v.get("set")}": {why}')
        elif find_property(entity, path) is None and find_computed(entity, path) is None:
            said.append(f'The value "{name}" reads {path} of the chosen {entity.id}, and {entity.id} has no property {path}.')
    return said


def _sum_refused(connection_id: str, graph: Any, entity: str, path: str) -> str:
    """Why the object door would not add ``path`` up over objects of ``entity``, or "" — the check every piece's read gets."""
    from aughor.dashboards.pieces import check_query
    from aughor.semantic.object_query import ObjectQueryRefused
    try:
        check_query({"object_type": entity, "measures": [{"name": "n", "agg": "sum", "path": path}]}, graph, connection_id)
    except ObjectQueryRefused as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 — a compile that breaks says so; it never passes unread
        return f"it could not be read ({str(exc)[:120]})"
    return ""


def _queries_unread(spec: Any, queried: dict) -> list[str]:
    """Arc AP-8c — a sentence for each value read from a query that is not a card of the person's own query the dashboard
    places, or whose query reads that value back: it would wait on itself."""
    from aughor.dashboards.queries import params_of
    from aughor.cards.store import get_card
    placed = {str((el or {}).get("props", {}).get("card") or "") for el in _named(spec, "elements").values()
              if isinstance(el, dict) and el.get("type") == "Card"}
    said: list[str] = []
    for name, v in queried.items():
        cid = str(v.get("card") or "")
        card = get_card(cid) if cid else None
        render = getattr(card, "render", None) if card is not None else None
        if card is None or cid not in placed or not (getattr(card, "sql", "") or "").strip() \
                or not (isinstance(render, dict) and render.get("shown")):
            said.append(f'The value "{name}" reads the first value of a query, and that is not a query of yours this dashboard '
                        "places.")
        elif name in params_of(card.sql):
            said.append(f'The value "{name}" reads a query that reads {{{{{name}}}}} itself: it would wait on itself.')
    return said
