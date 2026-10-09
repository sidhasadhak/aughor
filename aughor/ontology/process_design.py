"""The process designer's reading of the data — what a person designing a process is shown before anything is written.

The usability walk-through of 2026-10-09 (`docs/USABILITY_WALKTHROUGH_2026-10-09.md`) typed a delivery process the way
a person would — Order, shipped → delivered within 5 days — and found it would publish a board of ≈35,750 late
deliveries against a 0 % breach rate among delivered orders: on theLook 37,243 orders reached *Shipped* and never
*Delivered*, 22,152 of them over a year ago. The form showed column names and nothing else; the server could not count
a draft without writing it. Here the data is read FOR the person:

* `candidates` — the moments an object of a type carries (its own and its to-one linked records'), how many objects
  have each and the span they cover, and the properties whose few values place an object in a state, with how many
  objects hold each value: what a stage may be anchored to, and the statuses objects actually end in.
* `design_checks` — after a draft is measured (`processes.measure_process`, the declare door's own count): objects
  waiting at a stage for more than a year, said as a question with the state that explains them; moments dated after
  today; objects that skip a stage or reach it before the one before; who leaves. Each check carries the filters that
  list its objects through the object door.
* `creates` — what a published process derives, with its number now: the open-and-overdue list, the breach rate, the
  typical duration.

Every count goes through the object door's compiler (`processes.ObjectCounter`) — the law the board, the table and the
claims read by. Nothing here writes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from aughor.ontology.derived import (
    cutoff_days,
    lag_name,
    overdue_name,
    promise_filters,
    promise_noun,
    rate_name,
)
from aughor.ontology.models import EntityProperty, OntologyEntity, OntologyGraph, Process
from aughor.ontology.processes import NotMeasurable, ObjectCounter, cell_int, cell_text, provisional

#: A property with more distinct values than this is not read as a state an object is in.
MAX_STATE_VALUES = 20
#: How many state-like properties of a type are counted — status-like names first.
MAX_STATE_PROPERTIES = 4
#: How many linked types' moments are offered.
MAX_LINKED = 3
#: An object waiting at a stage longer than this is asked about: a record that left, or one really late?
STALE_DAYS = 365
#: The values of one state that together explain this share of the waiting objects are offered as the way they left —
#: the fewest that do, at most `MAX_EXIT_VALUES` (on the samples shop, *cancelled* and *refunded* between them).
EXPLAINS = 0.9
MAX_EXIT_VALUES = 3

_STATUS_LIKE = re.compile(r"status|state|stage|phase|step|outcome", re.I)


def is_moment(prop: EntityProperty) -> bool:
    return prop.semantic_type == "timestamp" or bool(re.search(r"DATE|TIME", prop.data_type or "", re.I))


def _label(entity: OntologyEntity) -> str:
    return entity.display_name or entity.id


def _state_like(entity: OntologyEntity) -> list[EntityProperty]:
    props = [p for p in (entity.properties or {}).values()
             if not (p.is_primary_key or p.is_foreign_key or is_moment(p))
             and (p.semantic_type in ("dimension", "category", "status") or re.search(r"CHAR|STRING|TEXT", p.data_type or "", re.I))]
    props.sort(key=lambda p: (not _STATUS_LIKE.search(p.name), p.name))
    return props[:MAX_STATE_PROPERTIES]


def _moments(counter: ObjectCounter, api: str, props: list[EntityProperty], via: str, on: OntologyEntity) -> list[dict]:
    if not props:
        return []
    paths = [f"{via}.{p.name}" if via else p.name for p in props]
    measures: list[dict] = []
    for i, path in enumerate(paths):
        measures += [{"name": f"set_{i}", "agg": "count", "where": [{"path": path, "op": "not_null"}]},
                     {"name": f"min_{i}", "agg": "min", "path": path},
                     {"name": f"max_{i}", "agg": "max", "path": path}]
    counts = counter.one(api, measures)
    return [{"path": path, "property": p.name, "label": p.display_name or p.name, "via": via, "on": on.id,
             "on_label": _label(on), "set": cell_int(counts.get(f"set_{i}")) or 0,
             "earliest": cell_text(counts.get(f"min_{i}")), "latest": cell_text(counts.get(f"max_{i}"))}
            for i, (path, p) in enumerate(zip(paths, props))]


def _values(counter: ObjectCounter, api: str, prop: str, filters: Optional[list[dict]] = None) -> Optional[list[dict]]:
    """``[{"value", "objects"}]`` for each value ``prop`` holds (most held first; a NULL as value None), or None when it
    holds more than `MAX_STATE_VALUES` — then it is not a state."""
    columns, rows = counter.rows({"object_type": api, "by": [prop], "measures": [{"name": "n", "agg": "count"}],
                                  "filters": list(filters or [])}, max_rows=MAX_STATE_VALUES + 2)
    if len(rows) > MAX_STATE_VALUES + 1:
        return None
    out = [{"value": (cell_text(r[0]) if r[0] is not None else None), "objects": cell_int(r[1]) or 0} for r in rows]
    return sorted(out, key=lambda v: -v["objects"])


def candidates(db: Any, graph: OntologyGraph, entity_id: str) -> dict:
    """What a stage of a process ``entity_id`` goes through may be anchored to, read from the data: its moments and its
    linked records' (each with how many objects have it and the span it covers), and its state-like properties with
    how many objects hold each value. A linked type that cannot be counted is left out and said."""
    from aughor.semantic.object_query import link_problem, object_links
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise NotMeasurable(f"no entity '{entity_id}' in this ontology")
    counter = ObjectCounter(db, graph)
    api = entity.api_name
    objects = cell_int(counter.one(api, [{"name": "objects", "agg": "count"}]).get("objects")) or 0
    moments = _moments(counter, api, [p for p in (entity.properties or {}).values() if is_moment(p)], "", entity)
    unread: list[str] = []
    linked = [h for h in object_links(graph, entity) if h.to_one and not link_problem(h)][:MAX_LINKED]
    for h in linked:
        props = [p for p in (h.target.properties or {}).values() if is_moment(p)]
        try:
            moments += _moments(counter, api, props, h.name, h.target)
        except NotMeasurable as exc:
            unread.append(f"{_label(h.target)}: {exc}")
    states = []
    for p in _state_like(entity):
        try:
            values = _values(counter, api, p.name)
        except NotMeasurable as exc:
            unread.append(f"{p.name}: {exc}")
            continue
        if values is not None:
            states.append({"property": p.name, "label": p.display_name or p.name, "values": values})
    b = entity.backing
    return {"entity": entity.id, "label": _label(entity), "api_name": api, "objects": objects,
            "table": (b.table if b is not None and b.kind == "table" else "") or "",
            "key": (b.primary_key if b is not None else "") or entity.identity_key or "",
            "moments": moments, "states": states, "unread": unread}


# ── the checks a draft is read against before it is published ───────────────────────────────────────────────────────

def _plural(entity: OntologyEntity, n: int) -> str:
    word = _label(entity).lower()
    return word if n == 1 else (word[:-1] + "ies" if word.endswith("y") and not word.endswith("ey") else word + "s")


def _what(stage) -> str:
    p = stage.promise
    return (f"the {p.deadline} deadline" if p.deadline else
            f"a {p.within_hours}-hour promise" if p.within_hours is not None else f"a {p.within_days}-day promise")


def _stuck(counter: ObjectCounter, work: OntologyGraph, process: Process, measured: Process, i: int,
           states: list[EntityProperty]) -> Optional[dict]:
    stage, previous = measured.stages[i], measured.stages[i - 1]
    p = stage.promise
    spec = promise_filters(work.processes[process.id], i)
    if p is None or spec is None or not spec.get("start") or not p.as_of or not p.open:
        return None
    grain = work.entities[spec["grain"]]
    cutoff = cutoff_days(p.as_of, STALE_DAYS)
    stale_filters = [*spec["open"], {"path": spec["start"], "op": "<", "value": cutoff}]
    stale = cell_int(counter.one(grain.api_name, [{"name": "n", "agg": "count", "where": stale_filters}]).get("n")) or 0
    if not stale:
        return None
    noun = _plural(grain, p.open)
    after = (f"while every one that reached {stage.display_name or stage.name} did so in time" if not p.breached else
             f"against {p.breach_rate:.1%} late among those that reached it" if p.breach_rate is not None else "")
    says = (f"{p.open:,} {noun} reached {previous.display_name or previous.name} and never "
            f"{stage.display_name or stage.name}, {stale:,} of them more than a year ago. With {_what(stage)}, "
            f"{p.open_overdue or 0:,} would be called late today" + (f", {after}." if after else "."))
    check = {"id": f"stuck:{stage.name}", "level": "ask", "stage": stage.name, "says": says,
             "numbers": {"open": p.open, "stale": stale, "overdue": p.open_overdue or 0, "breached": p.breached,
                         "reached": p.reached},
             "show": {"entity": grain.api_name, "filters": stale_filters,
                      "columns": [spec["start"], *([s.name for s in states[:1]])]}}
    for prop in states:
        try:
            values = _values(counter, grain.api_name, prop.name, stale_filters)
        except NotMeasurable as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "a state the waiting objects hold could not be counted; the question is asked without it",
                     counter="process_design.exit_values")
            continue
        chosen, explained = [], 0
        for v in values or []:
            if v["value"] is None or len(chosen) == MAX_EXIT_VALUES or explained >= EXPLAINS * stale:
                break
            chosen.append(v["value"])
            explained += v["objects"]
        if not chosen or explained < EXPLAINS * stale:
            continue
        held = counter.one(grain.api_name, [
            {"name": "holding", "agg": "count", "where": [{"path": prop.name, "op": "in", "values": chosen}]},
            {"name": "recent", "agg": "count", "where": [*spec["open"], {"path": prop.name, "op": "in", "values": chosen},
                                                          {"path": spec["start"], "op": ">=", "value": cutoff}]}])
        check["exit"] = {"property": prop.name, "label": prop.display_name or prop.name, "values": chosen,
                         "explains": explained, "of": stale, "holding": cell_int(held.get("holding")) or 0,
                         "recent": cell_int(held.get("recent")) or 0}
        break
    return check


def design_checks(db: Any, graph: OntologyGraph, process: Process, measured: Process, *,
                  now: Optional[str] = None) -> list[dict]:
    """What a person is asked or told about a measured draft before publishing it — each with the level it is said at
    (``ask`` a question with answers, ``warn``, ``error``, ``ok``) and, where there are objects to look at, the object
    door's filters that list them."""
    entity = graph.entities.get(process.entity)
    if entity is None:
        return []
    work = graph.model_copy()
    work.processes = {**(graph.processes or {}), process.id: provisional(process)}
    counter = ObjectCounter(db, work)
    states = _state_like(entity)
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    label = _label(entity)
    out: list[dict] = []
    for stage in measured.stages:
        if stage.verified is False:
            out.append({"id": f"unreached:{stage.name}", "level": "error", "stage": stage.name,
                        "says": f"No {label.lower()} reaches {stage.display_name or stage.name}: {stage.note}."})
    asked: set[str] = set()
    for i, stage in enumerate(measured.stages):
        if i and stage.promise is not None and stage.promise.verified:
            check = _stuck(counter, work, process, measured, i, states)
            if check is not None:
                out.append(check)
                asked.add(stage.name)
    timed = [s for s in measured.stages if s.timestamp]
    if timed:
        measures = []
        for j, s in enumerate(timed):
            measures += [{"name": f"future_{j}", "agg": "count", "where": [{"path": s.timestamp, "op": ">", "value": now}]},
                         {"name": f"latest_{j}", "agg": "max", "path": s.timestamp}]
        counts = counter.one(entity.api_name, measures)
        for j, s in enumerate(timed):
            future = cell_int(counts.get(f"future_{j}")) or 0
            if future:
                out.append({"id": f"future:{s.name}", "level": "warn", "stage": s.name,
                            "says": (f"{future:,} {s.display_name or s.name} moments are dated after today (the latest "
                                     f"is {cell_text(counts.get(f'latest_{j}'))[:10]})."),
                            "show": {"entity": entity.api_name, "columns": [s.timestamp],
                                     "filters": [{"path": s.timestamp, "op": ">", "value": now}]}})
    disorder = False
    for i, s in enumerate(measured.stages):
        previous = measured.stages[i - 1] if i else None
        if previous is None or not (s.timestamp and previous.timestamp):
            continue
        name, before = s.display_name or s.name, previous.display_name or previous.name
        if s.skipped:
            disorder = True
            out.append({"id": f"skipped:{s.name}", "level": "warn", "stage": s.name,
                        "says": f"{s.skipped:,} reach {name} with no moment for {before}.",
                        "show": {"entity": entity.api_name, "columns": [previous.timestamp, s.timestamp],
                                 "filters": [{"path": s.timestamp, "op": "not_null"},
                                             {"path": previous.timestamp, "op": "is_null"}]}})
        if s.out_of_order:
            disorder = True
            out.append({"id": f"early:{s.name}", "level": "warn", "stage": s.name,
                        "says": f"{s.out_of_order:,} reach {name} before they reach {before}.",
                        "show": {"entity": entity.api_name, "columns": [previous.timestamp, s.timestamp],
                                 "filters": [{"path": s.timestamp, "op": "<", "value_path": previous.timestamp}]}})
    pairs = [(measured.stages[i - 1], s) for i, s in enumerate(measured.stages)
             if i and s.timestamp and measured.stages[i - 1].timestamp]
    if pairs and not disorder:
        out.append({"id": "order", "level": "ok",
                    "says": "Every stage's moment follows the one before it: no object skips a stage or reaches one "
                            "before the stage before it."})
    leaves = measured.leaves
    if leaves is not None:
        if leaves.left:
            out.append({"id": "leaves", "level": "ok",
                        "says": (f"{leaves.left:,} {_plural(entity, leaves.left)} whose {leaves.property} is "
                                 f"{' or '.join(leaves.values)} leave the process: never open, never late.")})
        if leaves.missing:
            out.append({"id": "leaves:missing", "level": "warn",
                        "says": f"No {label.lower()} holds {', '.join(leaves.missing)} — check how the data spells it."})
        if leaves.unknown:
            out.append({"id": "leaves:unknown", "level": "warn",
                        "says": (f"{leaves.unknown:,} hold no {leaves.property}, so whether they left is not known; "
                                 "the open counts leave them out.")})
    for s in measured.stages:
        if s.promise is not None and s.name not in asked:
            for flag in s.promise.flags or []:
                out.append({"id": f"flag:{s.name}", "level": "warn", "stage": s.name, "says": flag[0].upper() + flag[1:]})
    return out


def creates(measured: Process) -> list[dict]:
    """What a published process derives, each with its number now — what can be placed on a cockpit."""
    out: list[dict] = []
    for i, s in enumerate(measured.stages):
        p = s.promise
        if p is None:
            continue
        noun = promise_noun(s)
        if i and p.verified:
            out.append({"kind": "segment", "name": overdue_name(s), "noun": noun, "value": p.open_overdue or 0,
                        "says": f"open and past the {noun} promise — a list to act on"})
            out.append({"kind": "metric", "name": rate_name(s), "noun": noun, "value": p.breach_rate,
                        "says": f"of those that reached {s.display_name or s.name}, the share past the promise"})
        if s.p50_days is not None and i:
            out.append({"kind": "property", "name": lag_name(s), "noun": noun, "value": s.p50_days,
                        "says": f"days from {measured.stages[i - 1].display_name or measured.stages[i - 1].name} to "
                                f"{s.display_name or s.name}, median"})
    return out
