"""Arc OC-2 — the compatibility catalogue: what a change to a declaration does to what reads it (ROADMAP §3.56).

Every change waiting in a draft is classed before it can be published, from what it changes and what depends on it:

* **ERR** — breaks what reads it: a withdrawal something depends on, a type's key or source changed, a link's join
  changed or widened from to-one to to-many, a process moved to another type, an action's parameters changed, a
  declaration whose own measurement did not bind. Publishing is refused while one stands.
* **MEANING** — Aughor's own class: the element still reads, but what it *means* moved — a promise from two days to
  three, a stage's anchor, how an object leaves a process, a rule's values, a segment's filter, a metric's statement. Publishing one restates every
  claim computed under the old meaning (`ontology.release.publish`), so nobody keeps a number whose definition changed
  under it without being told.
* **WARN** — readers keep working but should look: a governed action's criteria, effects or risk changed; a binding
  withdrawn; a promise renamed, which renames what it derives.
* **SAFE** — adds something, or changes only words: a name, a description, an owner.

A change's class is the most serious of its reasons, in that order. A field the catalogue does not know is a WARN —
said, never assumed safe. The falsifier (§3.56): replayed over the declarations' own history, every past change that
broke a consumer must class as ERR or WARN.
"""
from __future__ import annotations

from typing import Any, Optional

ORDER = ("ERR", "MEANING", "WARN", "SAFE")

#: Fields that change only words a person reads.
_WORDS = {"display_name", "description", "owner", "origin", "provenance", "domain", "entity_type", "label",
          "name_origin", "name_provenance", "declared", "note"}


def _changed(before: dict, after: dict) -> set[str]:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def _to_many(cardinality: Any) -> bool:
    return isinstance(cardinality, str) and cardinality.endswith(":N")


def _entity(before: dict, after: dict) -> list[tuple[str, str]]:
    out = []
    for k in sorted(_changed(before, after)):
        if k in _WORDS or k == "display_property":
            out.append(("SAFE", f"its {k.replace('_', ' ')} changed"))
        elif k == "backing":
            old, new = before.get(k) or {}, after.get(k) or {}
            moved = [f for f in ("kind", "table", "sql", "primary_key") if old.get(f) != new.get(f)]
            if moved:
                out.append(("ERR", "the rows it is made of or its key changed (" + ", ".join(moved) + ")"))
        elif k == "bindings":
            old, new = before.get(k) or {}, after.get(k) or {}
            for name in sorted(set(old) - set(new)):
                out.append(("WARN", f"its binding '{name}' was withdrawn — the properties it supplied stop reading"))
            for name in sorted(set(old) & set(new)):
                o, n = old[name] or {}, new[name] or {}
                if any(o.get(f) != n.get(f) for f in ("table", "sql", "key", "kind", "time_column")):
                    out.append(("ERR", f"its binding '{name}' reads another source or key"))
                elif o != n:
                    out.append(("MEANING", f"what its binding '{name}' supplies changed"))
            for name in sorted(set(new) - set(old)):
                out.append(("SAFE", f"a binding '{name}' was added"))
        elif k in ("active_filter", "default_filters", "exclude_when", "lifecycle_states", "terminal_states",
                   "expressions", "semiadditive"):
            out.append(("MEANING", f"its {k.replace('_', ' ')} changed — what counts as one of its objects, or how "
                                   "a property adds up, is different"))
        elif k in ("absorbed_into", "withdrawn_bindings"):
            out.append(("WARN", f"its {k.replace('_', ' ')} changed"))
        else:
            out.append(("WARN", f"'{k}' changed — the catalogue does not class it; read it before publishing"))
    return out


def _link(before: dict, after: dict) -> list[tuple[str, str]]:
    out = []
    for k in sorted(_changed(before, after)):
        if k in _WORDS or k in ("name", "reverse_name"):
            out.append(("SAFE", f"its {k.replace('_', ' ')} changed — renamed, the same link"))
        elif k in ("from_entity", "to_entity", "from_column", "to_column"):
            out.append(("ERR", f"what it joins changed ({k.replace('_', ' ')})"))
        elif k == "cardinality":
            if not _to_many(before.get(k)) and _to_many(after.get(k)):
                out.append(("ERR", "it widened from to-one to to-many — every path through it can multiply rows"))
            else:
                out.append(("MEANING", f"its cardinality changed ({before.get(k)} → {after.get(k)})"))
        else:
            out.append(("WARN", f"'{k}' changed — the catalogue does not class it; read it before publishing"))
    return out


def _promise(stage: str, old: Optional[dict], new: Optional[dict], watched: set[str]) -> list[tuple[str, str]]:
    if old == new:
        return []
    if old is None:
        return [("SAFE", f"a promise was added on '{stage}'")]
    name = old.get("name") or stage
    if new is None:
        return [("ERR" if name in watched else "MEANING", f"the promise on '{stage}' was dropped"
                 + (" — an automation watches it" if name in watched else ""))]
    out = []
    if (new.get("name") or stage) != name:
        out.append(("WARN", f"the promise '{name}' was renamed — what it derives is renamed with it"))
    moved = [f for f in ("within_days", "within_hours", "deadline", "grain", "via", "target")
             if old.get(f) != new.get(f)]
    if moved:
        said = ", ".join(f"{f} {old.get(f)} → {new.get(f)}" for f in moved)
        out.append(("MEANING", f"the promise '{name}' changed: {said}"))
    return out


def _leaving(leaves: Any) -> str:
    if not isinstance(leaves, dict) or not leaves.get("values"):
        return "none declared"
    return f"{leaves.get('property')} is {', '.join(str(v) for v in leaves['values'])}"


def _process(before: dict, after: dict, watched: set[str]) -> list[tuple[str, str]]:
    out = []
    for k in sorted(_changed(before, after) - {"stages"}):
        if k in _WORDS:
            out.append(("SAFE", f"its {k.replace('_', ' ')} changed"))
        elif k == "entity":
            out.append(("ERR", f"it runs on another type ({before.get(k)} → {after.get(k)})"))
        elif k == "leaves":
            # Who has left the process is who is never open, never overdue: the board's open and overdue counts and
            # every `overdue_<noun>` list move with it (OC-4, found on theLook's live receipt — 18,726 Cancelled).
            out.append(("MEANING", f"how an object leaves it changed ({_leaving(before.get(k))} → {_leaving(after.get(k))})"
                                   " — what is open and overdue moves with it"))
        else:
            out.append(("WARN", f"'{k}' changed — the catalogue does not class it; read it before publishing"))
    old = {s.get("name"): s for s in before.get("stages") or []}
    new = {s.get("name"): s for s in after.get("stages") or []}
    for name in [n for n in old if n not in new]:
        promise = (old[name] or {}).get("promise")
        named = (promise or {}).get("name") or name
        out.append(("ERR" if promise and named in watched else "MEANING", f"the stage '{name}' was removed"))
    for name in [n for n in new if n not in old]:
        out.append(("SAFE", f"a stage '{name}' was added"))
    for name in [n for n in new if n in old]:
        o, n = old[name] or {}, new[name] or {}
        for f in ("timestamp", "state", "property"):
            if o.get(f) != n.get(f):
                out.append(("MEANING", f"the stage '{name}' is anchored differently ({f})"))
        out.extend(_promise(name, o.get("promise"), n.get("promise"), watched))
    if [s.get("name") for s in before.get("stages") or []] != [s.get("name") for s in after.get("stages") or []] \
            and set(old) == set(new):
        out.append(("MEANING", "its stages are in a different order"))
    return out


def _rule(before: dict, after: dict) -> list[tuple[str, str]]:
    out = []
    for k in sorted(_changed(before, after)):
        if k in _WORDS:
            out.append(("SAFE", f"its {k.replace('_', ' ')} changed"))
        elif k == "entity":
            out.append(("ERR", f"it is defined over another type ({before.get(k)} → {after.get(k)})"))
        elif k in ("values", "conditions", "property", "kind"):
            out.append(("MEANING", f"what it admits changed ({k})"))
        else:
            out.append(("WARN", f"'{k}' changed — the catalogue does not class it; read it before publishing"))
    return out


def _sql_bearing(before: dict, after: dict, meaning: set[str]) -> list[tuple[str, str]]:
    out = []
    for k in sorted(_changed(before, after)):
        if k in _WORDS:
            out.append(("SAFE", f"its {k.replace('_', ' ')} changed"))
        elif k in meaning:
            out.append(("MEANING", f"its {k.replace('_', ' ')} changed"))
        else:
            out.append(("WARN", f"'{k}' changed — the catalogue does not class it; read it before publishing"))
    return out


def _params(before: list, after: list) -> list[tuple[str, str]]:
    old = {p.get("name"): p for p in before or []}
    new = {p.get("name"): p for p in after or []}
    out = []
    for name in sorted(set(old) - set(new)):
        out.append(("ERR", f"its parameter '{name}' was removed — a caller still passes it"))
    for name in sorted(set(new) - set(old)):
        if new[name].get("required", True) and new[name].get("default_value") in (None, ""):
            out.append(("ERR", f"a required parameter '{name}' was added — no caller passes it"))
        else:
            out.append(("SAFE", f"an optional parameter '{name}' was added"))
    for name in sorted(set(old) & set(new)):
        o, n = old[name], new[name]
        if any(o.get(f) != n.get(f) for f in ("data_type", "kind", "object_type")):
            out.append(("ERR", f"its parameter '{name}' takes something else now"))
        elif not o.get("required", True) and n.get("required", True):
            out.append(("ERR", f"its parameter '{name}' became required"))
    return out


def _action(before: dict, after: dict) -> list[tuple[str, str]]:
    out = []
    for k in sorted(_changed(before, after)):
        if k in _WORDS:
            out.append(("SAFE", f"its {k.replace('_', ' ')} changed"))
        elif k == "params":
            out.extend(_params(before.get(k) or [], after.get(k) or []))
        elif k == "submission_criteria":
            out.append(("WARN", "its submission criteria changed — a proposal that passed may now be refused"))
        else:
            out.append(("WARN", f"what it does changed ({k.replace('_', ' ')})"))
    return out


def _unbound(binding: Optional[dict]) -> list[str]:
    """The verdicts a draft carries that did not bind — a declaration that does not compile or measure."""
    out = []
    for field, verdict in (binding or {}).items():
        if isinstance(verdict, dict) and verdict.get("bound") is False:
            out.append(f"{field}: {verdict.get('note') or 'did not bind'}")
    return out


def classify(kind: str, before: Optional[dict], after: Optional[dict], *, dependents: list[dict] = (),
             binding: Optional[dict] = None, watched_promises: set[str] = frozenset()) -> tuple[str, list[dict]]:
    """``(class, reasons)`` for one change: ``before`` is the published declaration's fields (None when the draft adds
    it), ``after`` the draft's (None when the draft withdraws it). ``dependents`` are what rely on the published
    element (`ontology.dependents`); ``watched_promises`` the promise names an automation's trigger names."""
    reasons: list[tuple[str, str]] = []
    if after is None or (kind == "link" and after.get("withdrawn") and not (before or {}).get("withdrawn")):
        if dependents:
            named = "; ".join(f"{d['consumer']} '{d['name']}' ({d['how']})" for d in dependents[:6])
            reasons.append(("ERR", f"it is withdrawn, and {len(dependents)} thing"
                                   f"{'s' if len(dependents) != 1 else ''} rely on it: {named}"))
        else:
            reasons.append(("SAFE", "it is withdrawn, and nothing relies on it"))
    elif before is None:
        reasons.append(("SAFE", "it is added"))
    else:
        handler = {"entity": _entity, "link": _link, "rule": _rule, "action": _action}.get(kind)
        if kind == "process":
            reasons.extend(_process(before, after, set(watched_promises)))
        elif handler is not None:
            reasons.extend(handler(before, after))
        elif kind == "object_set":
            reasons.extend(_sql_bearing(before, after, {"filter_sql", "is_default"}))
        elif kind in ("metric", "computed_property"):
            reasons.extend(_sql_bearing(before, after, {"formula_sql", "grain", "unit"}))
        else:
            reasons.append(("WARN", f"a {kind} changed — the catalogue does not class it; read it before publishing"))
        if not reasons:
            reasons.append(("SAFE", "nothing it says changed"))
    if after is not None:
        for why in _unbound(binding):
            reasons.append(("ERR", f"it does not bind — {why}"))
    worst = min((ORDER.index(c) for c, _ in reasons), default=ORDER.index("SAFE"))
    return ORDER[worst], [{"class": c, "why": w} for c, w in reasons]
