"""Arc FA, FA-3 — an earlier version of a declaration, put back into the draft (ROADMAP §3.60).

Every save and withdrawal of a declaration is a version (Arc OC-1, `ontology/history.py`), and a change waits in a
draft until a person publishes it (Arc OC-2, `ontology/release.py`). What was missing is the way back: what a promise
said on 1 October could be read, but putting it back meant typing it again. So:

* **A version's fields go back through the normal save path** — `overrides.save_override`, whose routing puts a
  change into the DRAFT. So a put back is classed like any change (`ontology.compatibility`) and reaches readers only
  when a person publishes it. A withdrawn version puts back the fields it had when it went. A version that says what
  readers read already takes the change waiting in the draft away, and nothing else.
* **It is counted again first**, by each kind's own measurement — a process's stages, a rule's admitted objects, an
  impact's rates, a declared link's sides, a declared entity's source and key, a binding's rows, an expression's probe
  — and every SQL field is EXPLAIN-bound (`bind_overrides`). A version is what the declaration SAID, never its
  verdicts, so it is measured rather than restored with the counts it once had; one that no longer resolves or counts
  on this ontology is refused with the reason and nothing is written, as the kind's own door refuses.
* **Refused with a sentence** for an organisation's ontology (outside releases for now), and for a version the
  history does not hold.

No model call: a version is a person's earlier words, and putting it back is a person's act.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: A declaration kind as a reader names it (the store's frozen `object_set` is a segment).
KIND_WORDS = {"entity": "entity", "object_set": "segment", "computed_property": "computed property",
              "metric": "metric", "action": "action", "link": "link", "process": "process", "rule": "rule",
              "impact": "impact"}


class PutBackRefused(ValueError):
    """A put back was refused; the message is the sentence a person reads. ``status`` is the HTTP answer: 404 for a
    version the history does not hold, 400 for one that no longer counts here, 409 for one that cannot go back now."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def unavailable(conn: str) -> str:
    """Why an earlier version cannot be put back on ``conn`` now, or "" when it can."""
    from aughor.ontology.overrides import organisation_scope
    if organisation_scope(conn):
        return ("an organisation's ontology is outside releases — an earlier version is not put back into it; "
                "declare it again through its own door")
    return ""


def _named(kind: str, target_id: str) -> str:
    return f"{KIND_WORDS.get(kind, kind)} '{target_id}'"


def version_of(conn: str, schema: str, kind: str, target_id: str, version: int) -> dict:
    """One recorded version of a declaration, as `history.versions` reads it. Refused (404) when there is none."""
    from aughor.ontology import history
    recorded = [r for r in history.versions(conn, schema, kind, target_id) if r.get("version") is not None]
    for row in recorded:
        if row["version"] == version:
            return row
    if not recorded:
        raise PutBackRefused(f"{_named(kind, target_id)} has no recorded version to put back — its history starts "
                             "at its next change", 404)
    numbers = sorted(int(r["version"]) for r in recorded)
    raise PutBackRefused(f"no version {version} of {_named(kind, target_id)} — its versions are "
                         f"{numbers[0]} to {numbers[-1]}", 404)


@dataclass
class Plan:
    """What a put back will do: ``outcome`` is ``draft`` (the version's fields wait in the draft) or ``discard`` (the
    version says what readers read already, so the change waiting for it is taken away)."""
    kind: str
    target_id: str
    version: int
    state: str
    outcome: str
    override: Any = None
    current: Any = None
    warnings: list[str] = field(default_factory=list)


def plan(conn: str, schema: str, kind: str, target_id: str, version: int, *, by: str = "") -> Plan:
    """Read the version and decide what putting it back does — nothing is written. Refused (PutBackRefused) when it
    cannot go back now, the history does not hold it, or it changes nothing."""
    why = unavailable(conn)
    if why:
        raise PutBackRefused(why)
    from aughor.ontology.overrides import OntologyOverride, draft_entries, find_override, viewing
    row = version_of(conn, schema, kind, target_id, version)
    fields = copy.deepcopy(row.get("fields") or {})
    if not fields:
        raise PutBackRefused(f"version {version} of {_named(kind, target_id)} holds nothing to put back", 409)
    with viewing("published"):
        published = find_override(conn, schema, kind, target_id)  # type: ignore[arg-type]
    with viewing("draft"):
        current = find_override(conn, schema, kind, target_id)  # type: ignore[arg-type]
    waiting = any(k == kind and t == target_id for k, t, _, _ in draft_entries(conn, schema))
    if published is not None and published.fields == fields:
        if not waiting:
            raise PutBackRefused(f"version {version} of {_named(kind, target_id)} is what readers read already, "
                                 "and nothing waits in the draft for it", 409)
        return Plan(kind, target_id, version, row["state"], "discard", current=current)
    if waiting and current is not None and current.fields == fields:
        raise PutBackRefused(f"the draft already says what version {version} of {_named(kind, target_id)} says", 409)
    ov = OntologyOverride(target_kind=kind, target_id=target_id, fields=fields, source="human", edited_by=by,  # type: ignore[arg-type]
                          note=f"put back from version {version}")
    return Plan(kind, target_id, version, row["state"], "draft", override=ov, current=current)


# ── counted again, by each kind's own measurement ───────────────────────────────────────────────────────────────


def _refuse(plan_: Plan, why: str) -> PutBackRefused:
    return PutBackRefused(f"version {plan_.version} of {_named(plan_.kind, plan_.target_id)} does not hold on this "
                          f"ontology now — {why}; nothing was put back", 400)


def measure(plan_: Plan, graph: Any, db: Callable[[], Any], explain: Callable[[str], Optional[str]]) -> None:
    """Count the version again by its kind's own measurement, writing each verdict onto ``plan_.override.binding``.
    ``db()`` opens the scope's connection on first use; ``explain(sql)`` EXPLAIN-binds a fragment. Raises
    PutBackRefused (400) where the kind's own door would refuse; a field that merely does not bind is kept unbound and
    said in ``plan_.warnings`` — the release classes it as breaking, as it would any declaration."""
    from aughor.ontology.overrides import bind_overrides
    from aughor.ontology.processes import NotMeasurable
    ov, kind = plan_.override, plan_.kind
    ov.binding = {}
    try:
        if kind == "process" and ov.fields.get("declared"):
            from aughor.ontology.processes import measure_process, process_entry, resolve_process
            problem, resolved = resolve_process(graph, ov.target_id, ov.fields)
            if problem:
                raise _refuse(plan_, problem)
            measured = measure_process(db(), graph, ov.target_id, resolved)
            ov.fields, ov.binding = resolved, {"process": process_entry(resolved, measured)}
        elif kind == "rule" and ov.fields.get("declared"):
            from aughor.ontology.business_rules import measure_rule, resolve_rule, rule_entry
            problem, resolved = resolve_rule(graph, ov.target_id, ov.fields)
            if problem:
                raise _refuse(plan_, problem)
            measured = measure_rule(db(), graph, ov.target_id, resolved)
            ov.fields, ov.binding = resolved, {"rule": rule_entry(resolved, measured)}
        elif kind == "impact" and ov.fields.get("declared"):
            from aughor.ontology.impacts import impact_entry, measure_impact, resolve_impact
            problem, resolved = resolve_impact(graph, ov.target_id, ov.fields)
            if problem:
                raise _refuse(plan_, problem)
            measured = measure_impact(db(), graph, ov.target_id, resolved)
            ov.fields, ov.binding = resolved, {"impact": impact_entry(resolved, measured)}
        elif kind == "link":
            if ov.fields.get("declared") and not ov.fields.get("withdrawn"):
                from aughor.ontology.declared import measure_declared_link
                missing = [e for e in (ov.fields.get("from_entity"), ov.fields.get("to_entity"))
                           if e not in graph.entities]
                if missing:
                    raise _refuse(plan_, f"no entity {', '.join(map(str, missing))} on this ontology to join")
                entry = measure_declared_link(db(), graph, ov.fields)
                if not entry.get("bound"):
                    raise _refuse(plan_, str(entry.get("note") or "its sides could not be counted"))
                ov.binding = {"link": entry}
        elif kind == "entity":
            _measure_entity(plan_, graph, db, explain)
        else:
            bind_overrides(ov, graph, explain)          # a segment's filter, a metric's or a property's formula
    except NotMeasurable as exc:
        raise _refuse(plan_, f"it could not be counted: {exc}") from exc
    plan_.warnings = [f"{f}: {b.get('note')}" for f, b in ov.binding.items()
                      if isinstance(b, dict) and b.get("bound") is False]


def _measure_entity(plan_: Plan, graph: Any, db: Callable[[], Any], explain: Callable[[str], Optional[str]]) -> None:
    """An entity's version, counted as its doors count it: a declared type's source and key, every SQL field and
    routing table, its display property and part mark, then each binding, expression and semiadditive property it
    names. A verdict the declaration as it stands already holds for the very same spec is kept, not counted twice."""
    from aughor.ontology.bindings import describe_with
    from aughor.ontology.overrides import bind_overrides
    ov, current = plan_.override, plan_.current
    carried = dict(current.binding) if current is not None else {}
    held = dict(current.fields) if current is not None else {}
    # a backing's key count and a display property's measurement survive a re-bind of the very same value
    # (`_bind_backing`, `_bind_display_property` compare what they measured), so they start from what is held
    ov.binding = {k: copy.deepcopy(carried[k]) for k in ("backing", "display_property") if k in carried}
    backing = None
    if ov.fields.get("declared"):
        spec = ov.fields.get("backing") if isinstance(ov.fields.get("backing"), dict) else {}
        if spec.get("kind") == "platform":
            from aughor.ontology.platform_objects import NOTE
            backing = {"bound": True, "note": NOTE, "primary_key": "id"}
        elif not spec:
            raise _refuse(plan_, "it declares no source to read its objects from")
        else:
            from aughor.ontology.declared import measure_declared_backing
            backing = measure_declared_backing(db(), ov.fields, describe_with(db()))
            if not backing.get("bound"):
                raise _refuse(plan_, str(backing.get("note") or "its source could not be read"))
        ov.binding["backing"] = backing
    bind_overrides(ov, graph, explain)
    if backing is not None:
        ov.binding["backing"] = backing                 # the source and key as the declare door counted them
    entity = graph.entities.get(ov.target_id) if graph is not None else None
    if entity is None and ov.fields.get("declared"):
        from aughor.ontology.declared import declared_entity
        entity = declared_entity(ov, graph)
    specs = ov.fields.get("bindings")
    if isinstance(specs, dict) and specs:
        if entity is None:
            raise _refuse(plan_, "no entity on this ontology to bind its further sources to")
        ov.binding["bindings"] = _bindings(plan_, entity, graph, db, specs, carried)
    expressions = ov.fields.get("expressions")
    if isinstance(expressions, dict) and expressions:
        if entity is None:
            raise _refuse(plan_, "no entity on this ontology to read its expressions on")
        ov.binding["expressions"] = _expressions(plan_, entity, graph, db, expressions, carried, held)
    semiadditive = ov.fields.get("semiadditive")
    if isinstance(semiadditive, dict) and semiadditive:
        from aughor.ontology.semiadditive import normalized_semiadditive, semiadditive_problem
        verdicts = {}
        for prop, raw in semiadditive.items():
            spec = normalized_semiadditive(raw)
            problem = semiadditive_problem(graph, entity, prop, spec) if entity is not None else "no such entity"
            if problem:
                raise _refuse(plan_, f"{prop} cannot be read as a reading at a moment: {problem}")
            verdicts[prop] = {"bound": True, "note": "", "over": spec["over"]}
        ov.binding["semiadditive"] = verdicts


def _bindings(plan_: Plan, entity: Any, graph: Any, db: Callable[[], Any], specs: dict, carried: dict) -> dict:
    """Each further binding the version names, bound and counted as the bindings door does — a bind entry the
    declaration already holds for the very same spec is kept with its count."""
    from aughor.ontology.bindings import (
        bind_binding, binding_block, declared_bindings, describe_with, measure_binding, normalized_spec, spec_problem,
    )
    from aughor.ontology.models import Backing
    backing = plan_.override.fields.get("backing")
    if isinstance(backing, dict) and backing.get("kind") != "platform":
        entity = entity.model_copy(update={"backing": Backing(**{k: v for k, v in backing.items()
                                                                 if k in Backing.model_fields})})
    # the bindings the version itself names are the type's others; one it does not name takes no property name
    entity = entity.model_copy(update={"bindings": [b for b in entity.bindings or [] if b.name in specs]})
    kept = (carried.get("bindings") or {}).get("entries") or {}
    entries: dict = {}
    fresh: set[str] = set()
    for name, raw in specs.items():
        old = kept.get(name)
        same = not spec_problem(name, raw) and isinstance(old, dict) and old.get("spec") == normalized_spec(raw)
        if same and old.get("bound") is True:
            entries[name] = old
            continue
        entry = bind_binding(entity, name, raw, graph, describe_with(db()))
        if not entry.get("bound"):
            raise _refuse(plan_, f"its binding '{name}' does not bind: {entry.get('note')}")
        entries[name], fresh = entry, fresh | {name}
    built, _ = declared_bindings(entity.model_copy(update={"bindings": []}), specs, {"entries": entries}, graph)
    for binding in built:
        if binding.name in fresh:
            counted = measure_binding(db(), entity, binding)
            entries[binding.name] = {**entries[binding.name],
                                     "measured": {"spec": entries[binding.name]["spec"], **counted.counts()}}
    return binding_block(entries)


def _expressions(plan_: Plan, entity: Any, graph: Any, db: Callable[[], Any], specs: dict, carried: dict,
                 held: dict) -> dict:
    """Each expression property the version names, probed as its door probes it — a verdict the declaration already
    holds for the very same expression is kept."""
    from aughor.ontology.expressions import normalized_expression, probe_expression
    kept = carried.get("expressions") or {}
    was = held.get("expressions") or {}
    verdicts: dict = {}
    for name, raw in specs.items():
        spec = normalized_expression(dict(raw or {}))
        if name in kept and was.get(name) == raw and (kept[name] or {}).get("bound"):
            verdicts[name] = kept[name]
            continue
        verdict = probe_expression(db(), graph, entity, spec["expression"], name=name)
        if not verdict.get("bound"):
            raise _refuse(plan_, f"its expression '{name}' does not bind: {verdict.get('note')}")
        verdicts[name] = verdict
    return verdicts


def landed(conn: str, schema: str, plan_: Plan) -> dict:
    """What a put back did, in a person's words, with the change as the release classes it."""
    from aughor.ontology import release as R
    named = _named(plan_.kind, plan_.target_id)
    change = next((c for c in R.changes(conn, schema) if c["kind"] == plan_.kind and c["target_id"] == plan_.target_id),
                  None)
    if plan_.outcome == "discard":
        said = (f"Version {plan_.version} of {named} is what readers read already — the change waiting in the draft "
                "was taken away.")
    else:
        said = (f"Version {plan_.version} of {named} waits in the draft"
                + (f", classed {change['class']}" if change else "")
                + " — readers get it when a person publishes the draft.")
    return {"put_back": True, "kind": plan_.kind, "target_id": plan_.target_id, "version": plan_.version,
            "version_state": plan_.state, "landed": plan_.outcome, "said": said, "change": change,
            "warnings": list(plan_.warnings)}
