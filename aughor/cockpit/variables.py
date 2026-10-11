"""Arc AP-8 — variables, as Workshop has them (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §9.2).

A cockpit's values were the author's, set once ("Window · 14 days"), and only a number of days reached a set's condition.
A value now says where it comes from: the author; the reader, on the page — from the choices the author offers, or as
they type — kept in their own browser, never in the cockpit; how many objects one of the cockpit's sets holds; or a
property of the object a reader chose. A set compares any value as its kind allows, and a query of the person's own reads
one as a bound parameter, never pasted into its statement (`queries.py`).

The web's rules hold a value's shape — what each kind holds, that a count counts a set the cockpit has, that a choice a
value reads is made, that no value counts a set that reads it back (`web/lib/cockpit/rules.ts`). What only the platform
knows is checked here before a spec is kept: that variables are on here — off, a spec that says any of it is refused and
the cockpit is what it was — and that the property a value reads off a chosen object is one its entity has.
"""
from __future__ import annotations

from typing import Any, Optional

FLAG = "cockpit.variables"


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def _named(spec: Any, key: str) -> dict:
    found = spec.get(key) if isinstance(spec, dict) else None
    return found if isinstance(found, dict) else {}


def uses(spec: Any) -> list[str]:
    """What in ``spec`` only a cockpit with variables says: a value of a day, a value that comes from anyone but its author,
    a set that compares a value other than by counting the last days, and (Arc AP-8b) a set that reaches its objects'
    linked objects or is combined with another — each once."""
    out: list[str] = []
    for name, v in _named(spec, "values").items():
        if not isinstance(v, dict):
            continue
        by = str((v.get("from") or {}).get("by") or "author") if isinstance(v.get("from"), dict) else "author"
        if v.get("kind") == "date" or by != "author":
            out.append(f"the value {name!r}")
    for name, s in _named(spec, "sets").items():
        where = s.get("where") if isinstance(s, dict) else None
        if any(isinstance(c, dict) and c.get("value_from") and c.get("op") != "in_last" for c in (where or [])) \
                or (isinstance(s, dict) and (s.get("traverse") or s.get("combine"))):
            out.append(f"the set {name!r}")
    return out


def refused_off(spec: Any) -> list[str]:
    """A sentence when ``spec`` reads variables and variables are off here — what a keep is refused with. Empty when it does
    not, whatever the flag says, so a cockpit that does not keeps as it always did."""
    said = uses(spec)
    if not said or on():
        return []
    return [f"The cockpit reads variables — {', '.join(said[:4])}{'…' if len(said) > 4 else ''} come from the reader, a count "
            "or a chosen object, compare a value in a set, or read a set's linked objects or another set whole — and "
            "variables are off on this install."]


def refused_query(sql: str) -> str:
    """What a query of a person's own that reads the cockpit's values is refused with while variables are off here."""
    from aughor.cockpit.queries import params_of
    names = params_of(sql)
    return (f"The query reads {', '.join('{{' + n + '}}' for n in names[:4])}{'…' if len(names) > 4 else ''} — the cockpit's "
            "values — and variables are off on this install.")


def unheld(spec: Any, card_ids: Any) -> list[str]:
    """A sentence for each query of a person's own the spec places that reads a value the cockpit does not hold — a value
    taken away while a query still reads it, or a card placed on a cockpit that never held its value."""
    from aughor.cockpit.queries import params_of
    from aughor.dashboard.store import get_card
    held = set(_named(spec, "values"))
    said: list[str] = []
    for cid in card_ids or ():
        card = get_card(str(cid))
        missing = [n for n in params_of(getattr(card, "sql", "") or "") if n not in held] if card is not None else []
        if missing:
            said.append(f'The card "{card.title}" reads {", ".join("{{" + n + "}}" for n in missing)}, and this cockpit '
                        f"holds no value of {'that name' if len(missing) == 1 else 'those names'}.")
    return said


def not_resolved(connection_id: str, spec: Any, *, graph: Optional[Any] = None, wiring: Optional[dict] = None) -> list[str]:
    """A sentence for each value read off a chosen object whose property that object's entity does not have."""
    chosen = {name: v for name, v in ((wiring or {}).get("values") or {}).items() if isinstance(v, dict) and v.get("by") == "chosen"}
    if not chosen:
        return []
    from aughor.cockpit.pieces import served_graph
    from aughor.semantic.object_query import ObjectQueryRefused, find_computed, find_object_type, find_property
    graph = graph if graph is not None else served_graph(connection_id)
    if graph is None:
        return ["The cockpit reads a chosen object's property, and no ontology is built for this connection."]
    said: list[str] = []
    for name, v in chosen.items():
        path, entity_name = str(v.get("path") or ""), str(v.get("entity") or "")
        try:
            entity = find_object_type(graph, entity_name)
        except ObjectQueryRefused:
            said.append(f'The value "{name}" reads {path} of an object of {entity_name or "no entity"}, which this connection '
                        "does not serve.")
            continue
        if find_property(entity, path) is None and find_computed(entity, path) is None:
            said.append(f'The value "{name}" reads {path} of the chosen {entity.id}, and {entity.id} has no property {path}.')
    return said
