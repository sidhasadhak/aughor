"""ON-9 — named business rules, declared and measured (ROADMAP §3.15, the second movement).

A rule is a definition the business holds and its data does not: "DACH is DE, AT and CH", "a fulfilled order
excludes the cancelled and the unavailable". Two kinds, both named, owned and measured:

* a **value set** — the values of one property the business groups under one name. The packs declare that a field
  HAS such groupings (`aliases: [{field: country, values: {}}]`) and leave the values empty, because only the
  business knows its own; a value-set rule is where the values are filled at last. Measured: rows per declared value,
  and a value no row holds is FLAGGED — a spelling the data does not use reads as nothing, silently, everywhere;
* a **condition** — the object door's own filters, named. Measured: how many objects it admits; one that admits every
  object is flagged (it excludes nothing), one that admits none is measured-false.

Counted through the object door's compiler, like a process, so a rule is measured by exactly the law it is read by;
the object door reads it as a segment of its type named by the rule's id (`aughor.ontology.derived`).
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from aughor.ontology.derived import derivations, rule_derivations, rule_filters, rows_of
from aughor.ontology.models import PROCESS_NAME_PATTERN, BusinessRule, OntologyGraph
from aughor.ontology.processes import ORIGINS, PATH_PATTERN, NotMeasurable, ObjectCounter, cell_int, cell_text

logger = logging.getLogger(__name__)

KINDS = ("value_set", "condition")
_MAX_VALUES = 1000
_MAX_CONDITIONS = 10
_OPS = ("=", "!=", ">", ">=", "<", "<=", "in", "not_in", "between", "is_null", "not_null", "exists", "not_exists")


def rule_spec_problem(spec: Any) -> str:
    """Why a rule cannot be declared as written, or "" — its shape only."""
    if not isinstance(spec, dict):
        return "a rule is declared as a mapping with `id`, `entity`, `kind` and its definition"
    if not PROCESS_NAME_PATTERN.match(str(spec.get("id") or "")):
        return "a rule id is snake_case — dach, fulfilled_orders — and names the segment it derives"
    if not str(spec.get("entity") or "").strip():
        return "a rule names the object type it is about in `entity`"
    kind = spec.get("kind") or "condition"
    if kind not in KINDS:
        return f"a rule's kind is one of {', '.join(KINDS)}"
    if spec.get("origin") and spec["origin"] not in ORIGINS:
        return f"a rule's origin is one of {', '.join(ORIGINS)}"
    if kind == "value_set":
        if not PATH_PATTERN.match(str(spec.get("property") or "")):
            return "a value set names the property its values are read from in `property`"
        values = spec.get("values")
        if (not isinstance(values, list) or not 1 <= len(values) <= _MAX_VALUES
                or not all(isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip() for v in values)):
            return f"a value set lists from 1 to {_MAX_VALUES} values in `values`"
        if len({str(v).strip() for v in values}) != len(values):
            return "a value set lists each value once"
        if spec.get("conditions"):
            return "a value set is defined by its values — `conditions` go with a condition rule"
        return ""
    conditions = spec.get("conditions")
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= _MAX_CONDITIONS:
        return f"a condition rule lists from 1 to {_MAX_CONDITIONS} filters in `conditions`, all of which hold"
    for c in conditions:
        if not isinstance(c, dict) or not PATH_PATTERN.match(str(c.get("path") or "")):
            return "each condition is a filter with a property `path`, an `op` and its value"
        if (c.get("op") or "=") not in _OPS:
            return f"a condition's op is one of {', '.join(_OPS)}"
    if spec.get("values") or spec.get("property"):
        return "a condition rule is defined by its conditions — `property` and `values` go with a value set"
    return ""


def rule_fields(spec: dict) -> dict:
    """The override fields a declaration stores. Idempotent."""
    kind = spec.get("kind") or "condition"
    out: dict = {"declared": True, "entity": str(spec["entity"]).strip(), "kind": kind,
                 "origin": spec.get("origin") or "human"}
    if kind == "value_set":
        out["property"] = str(spec["property"]).strip()
        out["values"] = [str(v).strip() for v in spec["values"]]
    else:
        out["conditions"] = [{k: v for k, v in dict(c).items() if k in ("path", "op", "value", "values", "value_path")
                              and v not in (None, "", [])} for c in spec["conditions"]]
        for c in out["conditions"]:
            c.setdefault("op", "=")
    for key in ("display_name", "description", "owner", "provenance"):
        if str(spec.get(key) or "").strip():
            out[key] = str(spec[key]).strip()
    return out


def rule_from_fields(rule_id: str, fields: dict) -> BusinessRule:
    return BusinessRule(id=rule_id, display_name=fields.get("display_name") or rule_id.replace("_", " ").capitalize(),
                        description=fields.get("description") or "", owner=fields.get("owner") or "",
                        entity=fields["entity"], kind=fields.get("kind") or "condition",
                        property=fields.get("property") or "", values=list(fields.get("values") or []),
                        conditions=[dict(c) for c in fields.get("conditions") or []],
                        origin=fields.get("origin") or "human", provenance=fields.get("provenance") or "")


def resolve_rule(graph: OntologyGraph, rule_id: str, fields: dict) -> tuple[str, dict]:
    """``(problem, fields)``: why the rule cannot land on THIS graph, or "" with its type named by id. Its filters are
    compiled by the object door — a rule the compiler would refuse is refused here, with the compiler's reason."""
    from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, find_object_type, is_temporal, property_at
    try:
        entity = find_object_type(graph, fields["entity"])
    except ObjectQueryRefused as exc:
        return exc.reason, fields
    out = copy.deepcopy(fields)
    out["entity"] = entity.id
    rule = rule_from_fields(rule_id, out)
    if rule.kind == "value_set":
        try:
            _, prop, _ = property_at(graph, entity.api_name, rule.property, purpose=f"rule {rule_id}")
        except ObjectQueryRefused as exc:
            return f"rule {rule_id}: {exc.reason}", fields
        if is_temporal(prop):
            return f"rule {rule_id}: {rule.property} is a moment — a value set groups the values of a dimension", fields
    try:
        compile_object_query({"object_type": entity.api_name, "filters": list(rule_filters(rule)),
                              "measures": [{"agg": "count"}]}, graph, fiscal_start_month=1)
    except ObjectQueryRefused as exc:
        return f"rule {rule_id}: {exc.reason}", fields
    if rule_id.lower() in {k.lower() for k in entity.segments or {}}:
        return f"rule {rule_id}: {entity.id} already has a segment {rule_id} — a rule is read as the segment it names", fields
    others = derivations(graph, except_rule=rule_id)
    if any(d.entity == entity.id and d.name.lower() == rule_id.lower() for d in others.segments):
        return f"rule {rule_id}: a segment {rule_id} is already derived on {entity.id} by another declaration", fields
    return "", out


def measure_rule(db: Any, graph: OntologyGraph, rule_id: str, fields: dict, *,
                 open_source: Any = None) -> BusinessRule:
    """Count a (resolved) rule through the object door's compiler: the type's objects, the ones it admits, and for a
    value set the rows holding each declared value. Raises `NotMeasurable` when a count cannot be taken."""
    rule = rule_from_fields(rule_id, fields)
    entity = graph.entities.get(rule.entity)
    if entity is None:
        raise NotMeasurable(f"no object type '{rule.entity}' in this ontology")
    counter = ObjectCounter(db, graph, open_source)
    filters = list(rule_filters(rule))
    counts = counter.one(entity.api_name, [{"name": "objects", "agg": "count"},
                                           {"name": "admitted", "agg": "count", "where": filters}])
    rule.objects, rule.admitted = cell_int(counts.get("objects")) or 0, cell_int(counts.get("admitted")) or 0
    rule.flags = []
    if rule.kind == "value_set":
        columns, rows = counter.rows({"object_type": entity.api_name, "filters": filters, "by": [rule.property],
                                      "measures": [{"name": "n", "agg": "count"}]}, max_rows=_MAX_VALUES + 1)
        rule.observed = {cell_text(r[0]): cell_int(r[1]) or 0 for r in rows if cell_text(r[0])}
        rule.missing = [v for v in rule.values if v not in rule.observed]
        if rule.missing:
            rule.flags.append(f"never observed: {', '.join(rule.missing)} — no {entity.id} holds "
                              f"{'that value' if len(rule.missing) == 1 else 'those values'} in {rule.property}; "
                              "a spelling the data does not use?")
    if rule.admitted and rule.admitted == rule.objects and rule.kind == "condition":
        rule.flags.append(f"admits every one of the {rule.objects:,} {entity.id} objects — it excludes nothing")
    rule.verified = rule.admitted > 0
    rule.note = (f"admits {rule.admitted:,} of {rule.objects:,} {entity.id} objects" if rule.admitted
                 else f"admits none of the {rule.objects:,} {entity.id} objects")
    return rule


def rule_entry(fields: dict, measured: BusinessRule) -> dict:
    return {"bound": True, "note": measured.note, "substance": _substance(fields), "measured": measured.model_dump(mode="json"),
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _substance(fields: dict) -> dict:
    return {k: fields.get(k) for k in ("entity", "kind", "property", "values", "conditions")}


def declared_rule(ov, graph: Optional[OntologyGraph]) -> Optional[BusinessRule]:
    """The rule an override describes, with what its measurement recorded when it is of this very definition."""
    fields, entry = ov.fields, ov.binding.get("rule") or {}
    if not fields.get("declared") or entry.get("bound") is not True:
        return None
    if graph is not None and fields.get("entity") not in graph.entities:
        return None
    base = rule_from_fields(ov.target_id, fields)
    measured = entry.get("measured")
    if isinstance(measured, dict) and entry.get("substance") == _substance(fields):
        try:
            stamped = BusinessRule.model_validate(measured)
        except Exception:  # noqa: BLE001
            stamped = None
        if stamped is not None:
            return stamped.model_copy(update={k: getattr(base, k) for k in
                                              ("id", "display_name", "description", "owner", "origin", "provenance")})
    base.note = "declared; its definition changed since it was counted — POST /ontology/measure counts it again"
    return base


def measure_override_rules(connection_id: str, schema_name: Optional[str], db: Any,
                           graph: Optional[OntologyGraph], *, open_source: Any = None,
                           save: Any = None) -> list[dict]:
    """Re-resolve and re-count every declared rule against the served graph; one summary row per rule. On an
    organisation's ontology (ON-8) ``db`` is None, ``open_source`` opens each count's connection, and ``save`` is the
    organisation's own writer."""
    out: list[dict] = []
    if graph is None:
        return out
    try:
        from aughor.ontology.overrides import load_overrides, save_override
        overrides = load_overrides(connection_id, schema_name or "default")
    except Exception:  # noqa: BLE001
        return out
    save = save or save_override
    for ov in overrides:
        if ov.target_kind != "rule" or not ov.fields.get("declared"):
            continue
        problem, resolved = resolve_rule(graph, ov.target_id, ov.fields)
        if problem:
            measured = rule_from_fields(ov.target_id, ov.fields)
            measured.verified, measured.note = False, f"no longer resolves on this graph: {problem}"[:500]
        else:
            try:
                measured = measure_rule(db, graph, ov.target_id, resolved, open_source=open_source)
                ov.fields = resolved
            except NotMeasurable as exc:
                measured = rule_from_fields(ov.target_id, ov.fields)
                measured.note = f"not measurable on this pass: {exc}"[:500]
        ov.binding["rule"] = rule_entry(ov.fields, measured)
        try:
            save(connection_id, schema_name or "default", ov)
        except Exception as exc:  # noqa: BLE001
            logger.debug("rule measurement not saved for %s: %s", ov.target_id, exc)
        out.append({"rule": ov.target_id, "verified": measured.verified, "admitted": measured.admitted,
                    "objects": measured.objects, "missing": list(measured.missing), "flags": list(measured.flags),
                    "note": measured.note})
    return out


def describe_rule(graph: OntologyGraph, rule: BusinessRule) -> dict:
    entity = graph.entities.get(rule.entity)
    return {"id": rule.id, "display_name": rule.display_name or rule.id, "description": rule.description,
            "owner": rule.owner, "entity": entity.api_name if entity is not None else rule.entity,
            "entity_id": rule.entity, "kind": rule.kind, "property": rule.property, "values": list(rule.values),
            "conditions": [dict(c) for c in rule.conditions], "origin": rule.origin, "provenance": rule.provenance,
            "objects": rule.objects, "admitted": rule.admitted, "observed": dict(rule.observed),
            "missing": list(rule.missing), "verified": rule.verified, "flags": list(rule.flags), "note": rule.note,
            "segment": rule.id, "derived": rows_of(rule_derivations(rule))}
