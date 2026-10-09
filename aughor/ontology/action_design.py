"""The action designer's reading of a draft action — what a press would do, read from the data, with nothing written.

The usability walk-through of 2026-10-09 (`docs/USABILITY_WALKTHROUGH_2026-10-09.md`, job 2) found the declare form a
developer's: fourteen inputs and seven dropdowns mixing the business decision with a webhook, three of them pre-filled
with someone else's refund rule, and nothing to say — before declaring — which objects a person could press it on or
what a press would change. Here a draft is read as declaring would read it, and then:

- **who may be pressed on**: the criteria, when they are the designer's own shape (a property compared with values),
  are counted as the object door's filters — over every object, and over each segment a cockpit lists the action
  beside — so "25,061 orders allow it now" is a count, never an estimate;
- **a press on a real object**: one object is read live and the draft is dry-run against it by the executor's own
  `evaluate_proposal` — the same coercion and the same criteria a press meets — with the marks it would set and the
  call it would make filled in. Nothing is dispatched, approved or written.

A criterion beyond that shape is still judged on the sample, by the evaluator; it is only not counted, and that is said.
"""
from __future__ import annotations

import ast
from datetime import date
from typing import Any, Callable, Optional

from aughor.ontology.models import OntologyGraph
from aughor.ontology.processes import NotMeasurable, ObjectCounter, cell_int

#: The properties of the sample object shown beside a press: the criteria's first, then the object's own.
MAX_SHOWN = 8
_OPS = {ast.Eq: "=", ast.NotEq: "!=", ast.In: "in", ast.NotIn: "not_in"}
_NUMERIC = ("INTEGER", "INT", "BIGINT", "SMALLINT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")


def subject(action: Any) -> str:
    """The object parameter a declared action is about — its type's parameter, or its only object parameter — or ""."""
    taken = [p for p in action.params if p.kind == "object"]
    about = [p.name for p in taken if action.object_type and p.object_type.lower() == action.object_type.lower()]
    return about[0] if about else (taken[0].name if len(taken) == 1 else "")


def criteria_filters(action: Any) -> tuple[Optional[list[dict]], str]:
    """The criteria as the object door's filters on the objects the action is about, or None and why they are not
    counted. Counted: a property of the object (``order.status``, or ``object.status``) compared with values —
    ``=``, ``!=``, ``in``, ``not in`` — joined by ``and``."""
    who = subject(action)
    names = {who, "object"} if who else set()
    out: list[dict] = []
    for i, criterion in enumerate(action.submission_criteria, 1):
        try:
            tree = ast.parse(criterion.expr, mode="eval").body
        except SyntaxError:
            return None, f"condition {i} is not a valid expression"
        parts = tree.values if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And) else [tree]
        for node in parts:
            found = _filter(node, names)
            if found is None:
                return None, (f"condition {i} ({criterion.expr}) is more than a property compared with values, so "
                              "who may be pressed on is not counted; the press below still checks it")
            out.append(found)
    return out, ""


def _filter(node: ast.AST, names: set[str]) -> Optional[dict]:
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _OPS):
        return None
    left = node.left
    if not (isinstance(left, ast.Attribute) and isinstance(left.value, ast.Name) and left.value.id in names):
        return None
    try:
        value = ast.literal_eval(node.comparators[0])
    except (ValueError, TypeError, SyntaxError):
        return None
    op = _OPS[type(node.ops[0])]
    if op in ("in", "not_in"):
        return {"path": left.attr, "op": op, "values": list(value)} if isinstance(value, (list, tuple, set)) else None
    return None if isinstance(value, (list, tuple, set, dict)) else {"path": left.attr, "op": op, "value": value}


def _count(counter: ObjectCounter, api: str, filters: list[dict], segment: str = "") -> int:
    _, found = counter.rows({"object_type": api, "segment": segment, "filters": filters,
                             "measures": [{"name": "n", "agg": "count"}]}, max_rows=2)
    return (cell_int(found[0][0]) or 0) if found else 0


def _a_key(counter: ObjectCounter, api: str, key: str, filters: list[dict], segment: str) -> Optional[str]:
    _, found = counter.rows({"object_type": api, "segment": segment, "filters": filters, "by": [key],
                             "measures": [{"name": "n", "agg": "count"}], "order_by": key, "descending": False,
                             "limit": 1}, max_rows=2)
    return str(found[0][0]) if found and found[0][0] is not None else None


def _example(param: Any, said: dict[str, str]) -> Any:
    """What a press is tried with: the person's own example, else the parameter's default, else a stand-in of its type."""
    if param.name in said:
        return said[param.name]
    if param.default_value not in (None, ""):
        return param.default_value
    kind = (param.data_type or "VARCHAR").upper()
    if kind in _NUMERIC:
        return "0"
    if kind in ("BOOLEAN", "BOOL"):
        return "true"
    if kind == "DATE":
        return date.today().isoformat()
    return f"({param.display_name or param.name})"


def _shown(obj: dict, first: list[str]) -> dict:
    props = dict(obj.get("properties") or {})
    order = [*[p for p in first if p in props], *[p for p in props if p not in first]]
    return {p: props[p] for p in order[:MAX_SHOWN]}


def _press(action: Any, key: str, said: dict[str, str], first: list[str], *, scope: str, schema_name: str,
           resolver: Optional[Callable[[str, str], dict]]) -> dict:
    """The draft dry-run on one object: read live, coerced and judged by the executor's own rules, nothing dispatched."""
    from aughor.actions.executor import default_object_resolver, fill_edit, fill_template
    from aughor.actions.propose import evaluate_proposal
    who = subject(action)
    about = next(p for p in action.params if p.name == who)
    read = resolver or default_object_resolver(action, scope, schema_name)
    if read is None:
        return {"key": key, "status": "unread", "message": "there is no connection to read the object from"}
    try:
        obj = read(about.object_type, key)
    except (LookupError, ValueError) as exc:
        return {"key": key, "status": "unread", "message": str(getattr(exc, "reason", "") or exc)[:300]}
    params = {p.name: (f"{p.object_type}:{key}" if p.name == who else _example(p, said))
              for p in action.params if p.kind == "value" or p.name == who}
    status, message, coerced = evaluate_proposal(action, params, scope=scope, schema_name=schema_name,
                                                 resolver=lambda _t, _k: obj)
    out = {"key": key, "status": "allowed" if status == "proposed" else status, "message": message,
           "properties": _shown(obj, first), "edits": [], "call": None}
    filled = {**params, **coerced}
    try:
        out["edits"] = [{"property": e.property, "value": fill_edit(e.value, filled), "note": fill_edit(e.note, filled)}
                        for e in action.edits]
        for effect in action.side_effects:
            if effect.kind == "http":
                config = effect.config or {}
                out["call"] = {"method": str(config.get("method") or "POST").upper(),
                               "url": fill_template(str(config.get("url") or ""), filled, quote_for_url=True),
                               "body": fill_template(config.get("body"), filled)}
    except RuntimeError as exc:          # the executor's dispatch error: a template names what the action does not ask
        out.update(status="invalid_params", message=str(exc)[:300])
    return out


def preview(db: Any, graph: OntologyGraph, action: Any, *, scope: str, schema_name: str = "",
            segments: Optional[list[str]] = None, said: Optional[dict[str, str]] = None,
            resolver: Optional[Callable[[str, str], dict]] = None) -> dict:
    """What declaring ``action`` — a declared action as the declare door checked it — would offer, counted: how many of the objects it is about allow a press now — over all
    of them and over each of ``segments`` — and one press, dry-run on a real object (one a segment lists when one is
    named, one the criteria allow when one does). Counts that cannot be read are said in ``unread``."""
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type
    try:
        entity = find_object_type(graph, action.object_type)
    except ObjectQueryRefused as exc:
        raise NotMeasurable(exc.reason) from exc
    counter = ObjectCounter(db, graph)
    api = entity.api_name or entity.id
    key = (entity.backing.primary_key if entity.backing is not None else "") or entity.identity_key or ""
    filters, uncounted = criteria_filters(action)
    unread: list[str] = []
    out: dict = {"entity": entity.id, "objects": None, "allowed": None, "uncounted": uncounted, "segments": [],
                 "sample": None, "unread": unread}
    try:
        out["objects"] = _count(counter, api, [])
        if filters is not None:
            out["allowed"] = _count(counter, api, filters)
    except NotMeasurable as exc:
        unread.append(f"{entity.id}: {exc}")
    for segment in segments or []:
        try:
            out["segments"].append({"segment": segment, "objects": _count(counter, api, [], segment),
                                    "allowed": _count(counter, api, filters, segment) if filters is not None else None})
        except NotMeasurable as exc:
            unread.append(f"{segment}: {exc}")
    if not subject(action) or not key:
        unread.append("no object the action is about can be read to try a press on")
        return out
    first = [f["path"] for f in filters or []]
    lens = (segments or [""])[0]
    try:
        picked = (_a_key(counter, api, key, filters, lens) if filters else None) or _a_key(counter, api, key, [], lens)
    except NotMeasurable as exc:
        unread.append(f"a sample {entity.id}: {exc}")
        picked = None
    if picked is not None:
        out["sample"] = _press(action, picked, said or {}, first, scope=scope, schema_name=schema_name,
                               resolver=resolver)
    return out
