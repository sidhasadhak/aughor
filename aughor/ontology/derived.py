"""ON-9 — what a declared process or rule DERIVES, by construction (ROADMAP §3.15, the second movement).

A promise says once what "late" means; a rule says once what "DACH" means. This module turns each into names the
object door's one compiler reads — segments, computed properties and metrics — built from the door's own IR
(filters and measure terms), so a derived definition is executed under the same laws as anything written against
the door: a comparison reads two properties at the object's own grain through to-one links only, a rate is a ratio
of two counts, a lag is a whole number of calendar days. Nothing here is rendered into a prompt.

Pure and database-free: every function reads the graph it is handed. Whether a derived name may be READ is the
verdict its declaration was measured to (`usable`), so a promise nobody reached, or one declared and never counted,
derives names the compiler refuses with the reason rather than names that quietly answer nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aughor.ontology.models import BusinessRule, OntologyEntity, OntologyGraph, Process, ProcessStage


@dataclass(frozen=True)
class DerivedSegment:
    """A segment of `entity` (an entity id): the objects its `filters` admit."""
    name: str
    entity: str
    filters: tuple[dict, ...]
    source: str
    description: str
    usable: bool
    why_not: str = ""
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class DerivedProperty:
    """A property of `entity`: the calendar days — or, when `unit` is hours, the hours — from the moment at `start` to the
    moment at `end` (paths from it)."""
    name: str
    entity: str
    start: str
    end: str
    source: str
    description: str
    usable: bool
    why_not: str = ""
    unit: str = "days"


@dataclass(frozen=True)
class DerivedMetric:
    """A rate over `entity`'s objects: those `breach` admits over those `reached` admits."""
    name: str
    entity: str
    breach: tuple[dict, ...]
    reached: tuple[dict, ...]
    source: str
    description: str
    target_value: Optional[float]
    usable: bool
    why_not: str = ""
    caveats: tuple[str, ...] = ()


@dataclass
class Derivations:
    segments: list[DerivedSegment] = field(default_factory=list)
    properties: list[DerivedProperty] = field(default_factory=list)
    metrics: list[DerivedMetric] = field(default_factory=list)

    def extend(self, other: "Derivations") -> None:
        self.segments += other.segments
        self.properties += other.properties
        self.metrics += other.metrics


# ── names ───────────────────────────────────────────────────────────────────────────────────


def promise_noun(stage: ProcessStage) -> str:
    """The noun a stage's derived names are built from: its promise's name, else the stage's own."""
    return stage.promise.name if stage.promise is not None and stage.promise.name else stage.name


def lag_name(stage: ProcessStage) -> str:
    return f"{promise_noun(stage)}_lag_days"


def lag_hours_name(stage: ProcessStage) -> str:
    """The lag an hours promise is read by: the hours, to the second, from the previous stage's moment."""
    return f"{promise_noun(stage)}_lag_hours"


def late_name(stage: ProcessStage) -> str:
    return f"late_{promise_noun(stage)}"


def rate_name(stage: ProcessStage) -> str:
    return f"{promise_noun(stage)}_breach_rate"


def _days(n: int) -> str:
    return f"{n} calendar day{'' if n == 1 else 's'}"


def _hours(n: int) -> str:
    return f"{n} hour{'' if n == 1 else 's'}"


def promise_filters(process: Process, index: int) -> Optional[dict]:
    """The promise on stage ``index`` as filters on the type it is kept per — what breaks it, what reaching the stage
    with it in force means, what has not reached the stage yet — or None when the stage carries no promise the door
    can execute. The one definition the measurement counts and the derived segment and metric compile."""
    stage = process.stages[index]
    promise = stage.promise
    if promise is None or not stage.timestamp:
        return None
    previous = process.stages[index - 1] if index > 0 else None
    grain = promise.grain or process.entity
    moment = f"{promise.via}.{stage.timestamp}" if promise.via else stage.timestamp
    if promise.deadline:
        return {"grain": grain, "moment": moment, "deadline": promise.deadline,
                "breach": ({"path": moment, "op": ">", "value_path": promise.deadline},),
                "reached": ({"path": moment, "op": "not_null"}, {"path": promise.deadline, "op": "not_null"}),
                "open": ({"path": moment, "op": "is_null"}, {"path": promise.deadline, "op": "not_null"}),
                "words": f"{stage.name} ({moment}) after the deadline {promise.deadline}"}
    if promise.within_hours is not None and previous is not None and previous.timestamp and not promise.via:
        return {"grain": grain, "moment": moment, "start": previous.timestamp, "within_hours": int(promise.within_hours),
                "breach": ({"path": lag_hours_name(stage), "op": ">", "value": int(promise.within_hours)},),
                "reached": ({"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "not_null"}),
                "open": ({"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "is_null"}),
                "words": f"more than {_hours(int(promise.within_hours))} from {previous.name} to {stage.name}"}
    if promise.within_days is not None and previous is not None and previous.timestamp and not promise.via:
        return {"grain": grain, "moment": moment, "start": previous.timestamp, "within_days": int(promise.within_days),
                "breach": ({"path": lag_name(stage), "op": ">", "value": int(promise.within_days)},),
                "reached": ({"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "not_null"}),
                "open": ({"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "is_null"}),
                "words": f"more than {_days(int(promise.within_days))} from {previous.name} to {stage.name}"}
    return None


# ── what a process and a rule derive ────────────────────────────────────────────────────────


def _stage_why(*stages: ProcessStage) -> str:
    for stage in stages:
        if stage.verified is False:
            return f"was measured and no object reaches stage {stage.name} ({stage.note})"
        if stage.verified is None:
            return "has not been measured — POST /ontology/measure counts it"
    return ""


def _claim_why(verified: Optional[bool], note: str) -> str:
    if verified is False:
        return f"was measured and does not hold ({note})"
    return "has not been measured — POST /ontology/measure counts it"


def process_derivations(process: Process) -> Derivations:
    """Every name ``process`` derives: a lag for each stage whose moment follows another's, and for each promise the
    segment of the objects that broke it and the rate at which it is broken."""
    out = Derivations()
    for i, stage in enumerate(process.stages):
        previous = process.stages[i - 1] if i else None
        if stage.timestamp and previous is not None and previous.timestamp:
            usable = stage.verified is True and previous.verified is True
            out.properties.append(DerivedProperty(
                name=lag_name(stage), entity=process.entity, start=previous.timestamp, end=stage.timestamp,
                source=f"process {process.id}",
                description=f"calendar days from {previous.name} ({previous.timestamp}) to {stage.name} ({stage.timestamp})",
                usable=usable, why_not="" if usable else _stage_why(previous, stage)))
            if stage.promise is not None and stage.promise.within_hours is not None:
                out.properties.append(DerivedProperty(
                    name=lag_hours_name(stage), entity=process.entity, start=previous.timestamp, end=stage.timestamp,
                    source=f"process {process.id}",
                    description=f"hours from {previous.name} ({previous.timestamp}) to {stage.name} ({stage.timestamp})",
                    usable=usable, why_not="" if usable else _stage_why(previous, stage), unit="hours"))
        spec = promise_filters(process, i)
        if spec is None:
            continue
        promise = stage.promise
        assert promise is not None                       # promise_filters returns a spec only for a promise
        noun = promise_noun(stage)
        source = f"the {noun} promise of process {process.id}"
        usable = promise.verified is True
        why = "" if usable else _claim_why(promise.verified, promise.note)
        caveats = tuple(f"{source}: {flag}" for flag in promise.flags)
        out.segments.append(DerivedSegment(
            name=late_name(stage), entity=spec["grain"], filters=spec["breach"], source=source,
            description=f"the {spec['grain']} objects that broke the {noun} promise — {spec['words']}",
            usable=usable, why_not=why, caveats=caveats))
        out.metrics.append(DerivedMetric(
            name=rate_name(stage), entity=spec["grain"], breach=spec["breach"], reached=spec["reached"], source=source,
            description=(f"the share of the {spec['grain']} objects that reached {stage.name} with the {noun} promise in "
                         "force and broke it"),
            target_value=round(1.0 - promise.target, 6) if promise.target is not None else None,
            usable=usable, why_not=why, caveats=caveats))
    return out


def _condition_words(condition: dict) -> str:
    rhs = condition.get("value_path") or condition.get("values") or condition.get("value")
    return f"{condition.get('path')} {condition.get('op')}" + ("" if rhs in (None, "", []) else f" {rhs}")


def rule_filters(rule: BusinessRule) -> tuple[dict, ...]:
    """The rule as the door's filters: a value set is one `in`, a condition is its filters."""
    if rule.kind == "value_set":
        return ({"path": rule.property, "op": "in", "values": list(rule.values)},)
    return tuple(dict(c) for c in rule.conditions)


def rule_derivations(rule: BusinessRule) -> Derivations:
    """A rule derives one segment of its type, named by the rule's id."""
    usable = rule.verified is True
    words = (f"{rule.property} is one of {', '.join(rule.values)}" if rule.kind == "value_set"
             else "; ".join(_condition_words(c) for c in rule.conditions))
    source = f"rule {rule.id}" + (f" (owned by {rule.owner})" if rule.owner else "")
    return Derivations(segments=[DerivedSegment(
        name=rule.id, entity=rule.entity, filters=rule_filters(rule), source=source,
        description=rule.description or words, usable=usable, why_not="" if usable else _claim_why(rule.verified, rule.note),
        caveats=tuple(f"rule {rule.id}: {flag}" for flag in rule.flags))])


def derivations(graph: Optional[OntologyGraph], *, except_process: str = "", except_rule: str = "") -> Derivations:
    """Everything every declared process and rule on ``graph`` derives (the named ones left out)."""
    out = Derivations()
    if graph is None:
        return out
    for process in (graph.processes or {}).values():
        if process.id != except_process:
            out.extend(process_derivations(process))
    for rule in (graph.rules or {}).values():
        if rule.id != except_rule:
            out.extend(rule_derivations(rule))
    return out


def derived_for(graph: Optional[OntologyGraph], entity: OntologyEntity) -> Derivations:
    """What is derived ON ``entity``."""
    every = derivations(graph)
    return Derivations(segments=[d for d in every.segments if d.entity == entity.id],
                       properties=[d for d in every.properties if d.entity == entity.id],
                       metrics=[d for d in every.metrics if d.entity == entity.id])


def _named(items: list, name: str):
    low = (name or "").strip().lower()
    return next((d for d in items if d.name.lower() == low), None)


def find_derived_segment(graph: Optional[OntologyGraph], entity: OntologyEntity, name: str) -> Optional[DerivedSegment]:
    return _named(derived_for(graph, entity).segments, name)


def find_derived_property(graph: Optional[OntologyGraph], entity: OntologyEntity, name: str) -> Optional[DerivedProperty]:
    return _named(derived_for(graph, entity).properties, name)


def find_derived_metric(graph: Optional[OntologyGraph], entity: OntologyEntity, name: str) -> Optional[DerivedMetric]:
    return _named(derived_for(graph, entity).metrics, name)


def _row(d, kind: str) -> dict:
    out = {"name": d.name, "kind": kind, "source": d.source, "description": d.description, "usable": d.usable}
    if not d.usable:
        out["why_not"] = d.why_not
    if getattr(d, "caveats", ()):
        out["caveats"] = list(d.caveats)
    if kind == "metric" and d.target_value is not None:
        out["target_value"] = d.target_value
    return out


def rows_of(derived: Derivations) -> dict:
    """The derivations as plain rows, for a panel or a catalog."""
    return {"segments": [_row(d, "segment") for d in derived.segments],
            "properties": [_row(d, "property") for d in derived.properties],
            "metrics": [_row(d, "metric") for d in derived.metrics]}


def derived_rows(graph: Optional[OntologyGraph], entity: OntologyEntity) -> dict:
    return rows_of(derived_for(graph, entity))
