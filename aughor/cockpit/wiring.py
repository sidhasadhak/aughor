"""Arc AP-2 and AP-3 — a cockpit wired as an App (ROADMAP §3.57; docs/COCKPIT_APP_BUILDER_STUDY_2026-10-10.md §4.1b, §4.3
and §4.5).

A wired cockpit names sets its pieces read and values its sets read, a table names what a click chooses and what its
ticks collect, a figure switches a list, and action buttons run declared actions on what a reader chose or ticked. The
web's rules hold the wiring's shape — every name resolves, no ring of sets — from the same file the browser draws with
(`web/lib/cockpit/rules.ts`), and what a set reads comes from one function there too (`web/lib/cockpit/sets.ts`, run here
through the validator bundle). What only the platform knows is checked here before a spec is kept:

  - that wiring is on here — off, a spec that says any of it is refused, and the cockpit is what it was;
  - that every set compiles through the object door over the ontology this connection serves;
  - that each button's action is declared, and takes for each object parameter a source holding objects of its
    entity — "an order parameter takes a chosen order, never a customer" — and for a value parameter the form or a
    fixed value, never a choice.

And who wires: a person. A model's edit may arrange a wired cockpit; it never changes its sets or values, and never
what a piece reads (`pieces.pieces_written`, whose comparison leaves out only a piece's room).
"""
from __future__ import annotations

import json
from typing import Any, Optional

FLAG = "cockpit.wiring"
#: The props that wire a piece to a set or a choice.
WIRED_PROPS = ("set", "set_from", "chooses", "ticks", "shows", "of", "opens_on")


def on() -> bool:
    from aughor.kernel.flags import flag_enabled
    return flag_enabled(FLAG)


def _elements(spec: Any) -> dict:
    elements = spec.get("elements") if isinstance(spec, dict) else None
    return elements if isinstance(elements, dict) else {}


def wired(spec: Any) -> list[str]:
    """What in ``spec`` only a wired cockpit says: its sets, its values, and each element that reads a set or makes a
    choice, or holds action buttons — in that order, each once."""
    out = [k for k in ("sets", "values") if isinstance(spec, dict) and spec.get(k)]
    for key, el in _elements(spec).items():
        if not isinstance(el, dict):
            continue
        props = el.get("props") if isinstance(el.get("props"), dict) else {}
        if el.get("type") == "ActionButtons" or any(props.get(p) is not None for p in WIRED_PROPS):
            out.append(str(key))
    return out


def refused_off(spec: Any) -> list[str]:
    """A sentence when ``spec`` is wired and wiring is off here — what a keep is refused with. Empty when it is not
    wired, whatever the flag says, so a cockpit that is not keeps as it always did."""
    said = wired(spec)
    if not said or on():
        return []
    return [f"The cockpit is wired — {', '.join(said[:6])}{'…' if len(said) > 6 else ''} read sets, make choices or run "
            "actions — and wiring a cockpit is off on this install."]


def read(spec: Any) -> Optional[dict]:
    """Each set as the object door would read it, and each button's parameters with their source's kind and entity —
    the web's own reading, through the bundle. None when the spec is not wired (nothing to read) or the rules cannot
    run."""
    if not wired(spec):
        return None
    from aughor.cockpit import validate
    return validate.wiring(spec)


def not_resolved(connection_id: str, spec: Any, *, graph: Optional[Any] = None,
                 wiring: Optional[dict] = None) -> list[str]:
    """A sentence for each set that does not compile here, and each button whose action is not declared or whose
    source holds the wrong kind of thing. Empty for a cockpit that is not wired."""
    if not wired(spec):
        return []
    wiring = wiring if wiring is not None else read(spec)
    if wiring is None:
        return ["The cockpit's wiring could not be read, so it was not checked; it is not kept unchecked."]
    from aughor.cockpit.pieces import check_query, served_graph
    graph = graph if graph is not None else served_graph(connection_id)
    if graph is None:
        return ["The cockpit reads sets, and no ontology is built for this connection."]
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    said: list[str] = []
    for name, s in (wiring.get("sets") or {}).items():
        if "refused" in s:
            said.append(str(s["refused"]))
            continue
        body = {"object_type": s.get("entity"), "segment": s.get("segment") or "", "filters": s.get("filters") or [],
                "measures": [{"name": "n", "agg": "count"}]}
        try:
            check_query(body, graph, connection_id)
        except ObjectQueryRefused as exc:
            said.append(f'The set "{name}" cannot be read: {exc.reason}.')

    def entity_id(name: str) -> str:
        try:
            return find_object_type(graph, name).id if name else ""
        except ObjectQueryRefused:
            return ""
    declared = {a.id: a for a in graph.declared_actions()}
    for b in wiring.get("buttons") or []:
        which = f'The button {int(b.get("index", 0)) + 1} of "{b.get("element")}"'
        action = declared.get(str(b.get("action") or ""))
        if action is None:
            said.append(f'{which} runs "{b.get("action")}", which this connection does not declare.')
            continue
        for param in action.params:
            src = (b.get("params") or {}).get(param.name)
            if src is None:
                continue
            kind = str(src.get("source") or "")
            if param.kind == "object":
                if kind in ("ask", "value"):
                    said.append(f'{which} asks for "{param.name}" in its form or fixes it, and "{param.name}" is an object '
                                "of the action's — it comes from a chosen object, ticked objects or a set.")
                    continue
                want, have = entity_id(param.object_type), entity_id(str(src.get("entity") or ""))
                if want and have != want:
                    said.append(f'{which} fills "{param.name}" — {want} objects — from {have or "nothing it can read"}.')
            elif kind in ("chosen", "ticked", "set"):
                said.append(f'{which} fills the value "{param.name}" from objects. A value comes from the form or is fixed.')
        unknown = sorted(set((b.get("params") or {})) - {p.name for p in action.params})
        if unknown:
            said.append(f'{which} fills {", ".join(repr(u) for u in unknown)}, which "{action.id}" does not take.')
    return said


def wiring_written(before: Any, after: Any, *, new: bool) -> list[str]:
    """The sentences for what a model's draft did to a cockpit's sets and values, which only a person may change: a
    new cockpit holds none, and an edit leaves them as they were. Pieces' own wiring is `pieces.pieces_written`'s."""
    def wiring_of(spec: Any) -> str:
        return json.dumps({k: (spec or {}).get(k) or {} for k in ("sets", "values")} if isinstance(spec, dict) else {},
                          sort_keys=True, default=str)
    if new:
        return ["The cockpit names sets or values. A new cockpit is wired by a person, by hand."] \
            if wired({"sets": (after or {}).get("sets"), "values": (after or {}).get("values")}) else []
    if wiring_of(before) != wiring_of(after):
        return ["The edit changes the cockpit's sets or values. A person wires a cockpit: you may arrange it, never "
                "change what its pieces read."]
    return []
