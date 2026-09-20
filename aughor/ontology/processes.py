"""ON-9 — processes and promises, declared and measured (ROADMAP §3.15, the second movement).

Before this module the graph could say an Order has five timestamps and an unordered set of states; it could not
say they are the stages of ONE process, in an order, nor that the business promises to reach one of them by a
deadline. A dispatch delay was an anonymous timestamp compared, by whoever asked, with whichever column they guessed.

Here a person — or a pack, or an explorer's proposal — DECLARES a process: the type that goes through it, its stages
in order, each anchored to the moment an object reaches it (a date or timestamp property, through to-one links) or
to the lifecycle states that place an object in it, and on a stage the promise about reaching it: within N calendar
days of the previous stage, or by a per-object deadline property of the object that carries it (a marketplace's
per-line shipping limit is kept per LINE, and the line reaches its order through a measured to-one link).

Nothing is believed because it was declared. Every declaration is MEASURED before it is written and on every measure
pass — THROUGH THE OBJECT DOOR'S OWN COMPILER, so a declaration is counted by exactly the law it is later read by:
how many objects reach each stage; for each pair of consecutive moments how many objects carry both, skip the first,
or reach the second before the first, and the calendar days between them at the 50th/90th/95th percentile (computed
exactly from a per-day count, which every warehouse can run); for each promise how many objects reached the stage
with it in force, broke it and kept it, and how many have not reached the stage — of them, how many are already past
it as of the data's own latest moment. A stage no object reaches is measured-false; a promise never or always broken
is FLAGGED. The measurement rides the override file, so the overlay rebuilds the process with no database in hand.
"""
from __future__ import annotations

import copy
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from aughor.ontology.derived import (
    Derivations,
    derivations,
    lag_name,
    late_name,
    process_derivations,
    promise_filters,
    promise_noun,
    rate_name,
    rows_of,
)
from aughor.ontology.models import PROCESS_NAME_PATTERN, OntologyEntity, OntologyGraph, Process, ProcessStage, Promise

logger = logging.getLogger(__name__)

ORIGINS = ("human", "model", "pack")
_MAX_STAGES = 12
_MAX_DAYS = 3650
_MAX_HOURS = 24 * _MAX_DAYS
#: A per-day histogram wider than this is not a lag between two stages — it is a declaration read wrong.
_MAX_LAG_VALUES = 20_000
#: A property path: a property, or up to three links then a property. Each segment is a NAME the compiler resolves
#: against the graph before anything is quoted, so it may hold a space (`Order Date`, as a spreadsheet names a column) —
#: never a dot, a quote, a backtick or a semicolon.
PATH_PATTERN = re.compile(r"^[^.;'\"`\s][^.;'\"`]{0,127}(\.[^.;'\"`\s][^.;'\"`]{0,127}){0,3}$")


class NotMeasurable(ValueError):
    """The declaration could not be counted — a query the compiler refused or the warehouse failed."""


# ── the declaration's shape ─────────────────────────────────────────────────────────────────


def _stage_problem(i: int, stage: Any, stages: list) -> str:
    if not isinstance(stage, dict):
        return f"stage {i + 1} is a mapping with `name` and `timestamp` (or `state`)"
    name = str(stage.get("name") or "")
    if not PROCESS_NAME_PATTERN.match(name):
        return f"stage {i + 1}'s name is snake_case — placed, approved, dispatched"
    timestamp = str(stage.get("timestamp") or "").strip()
    state = stage.get("state")
    if state is not None and (not isinstance(state, list) or not state
                              or not all(isinstance(s, str) and s.strip() for s in state)):
        return f"stage '{name}': `state` lists the lifecycle states that place an object in it"
    if bool(timestamp) == bool(state):
        return (f"stage '{name}' is anchored to exactly one of `timestamp` (the moment an object reaches it) or "
                "`state` (the lifecycle states that place an object in it)")
    if stage.get("property") and not state:
        return f"stage '{name}': `property` names where its `state` is read, so it goes with a `state`"
    if timestamp and not PATH_PATTERN.match(timestamp):
        return f"stage '{name}': `timestamp` is a property path — order_approved_at, or link.property"
    promise = stage.get("promise")
    if promise is None:
        return ""
    if not isinstance(promise, dict):
        return f"stage '{name}': a promise is a mapping with `within_days` or `deadline`"
    if not timestamp:
        return (f"stage '{name}' is anchored to a state, which has no clock — a promise needs the moment an object "
                "reaches the stage")
    if promise.get("name") and not PROCESS_NAME_PATTERN.match(str(promise["name"])):
        return f"stage '{name}': a promise's name is snake_case — dispatch, delivery"
    within, hours = promise.get("within_days"), promise.get("within_hours")
    deadline = str(promise.get("deadline") or "").strip()
    if [within is not None, hours is not None, bool(deadline)].count(True) != 1:
        return (f"stage '{name}': a promise is exactly one of `within_days` (calendar days from the previous stage), "
                "`within_hours` (hours from the previous stage's moment) or `deadline` (a date or timestamp property of "
                "the object that carries it)")
    if within is not None or hours is not None:
        if within is not None and (isinstance(within, bool) or not isinstance(within, int) or not 0 <= within <= _MAX_DAYS):
            return f"stage '{name}': `within_days` is a whole number of days from 0 to {_MAX_DAYS}"
        if hours is not None and (isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= _MAX_HOURS):
            return f"stage '{name}': `within_hours` is a whole number of hours from 1 to {_MAX_HOURS}"
        if i == 0:
            return f"stage '{name}' is the first stage — there is no previous stage to count from"
        previous = stages[i - 1]
        if not (isinstance(previous, dict) and str(previous.get("timestamp") or "").strip()):
            return f"stage '{name}': the previous stage is anchored to a state, which has no clock to count from"
        if promise.get("grain") or promise.get("via"):
            return (f"stage '{name}': a promise within days or hours of the previous stage is kept per object of the "
                    "process's own type — `grain` and `via` go with a deadline")
    if deadline and not PATH_PATTERN.match(deadline):
        return f"stage '{name}': a promise's `deadline` is a property path of the object that carries it"
    if promise.get("via") and not PATH_PATTERN.match(str(promise["via"])):
        return f"stage '{name}': a promise's `via` is a link path — order_item_to_order"
    if promise.get("via") and not promise.get("grain"):
        return f"stage '{name}': `via` is the path from the promise's `grain` to the process's type, so it needs a `grain`"
    target = promise.get("target")
    if target is not None and (isinstance(target, bool) or not isinstance(target, (int, float))
                               or not 0 < float(target) <= 1):
        return f"stage '{name}': a promise's `target` is the share expected to keep it — above 0, at most 1 (0.95)"
    return ""


def process_spec_problem(spec: Any) -> str:
    """Why a process cannot be declared as written, or "" — its shape only; whether its anchors exist is the graph's
    to say (`resolve_process`) and whether objects reach them the warehouse's (`measure_process`)."""
    if not isinstance(spec, dict):
        return "a process is declared as a mapping with `id`, `entity` and `stages`"
    if not PROCESS_NAME_PATTERN.match(str(spec.get("id") or "")):
        return "a process id is snake_case — a lower-case letter, then letters, digits and underscores (order_to_delivery)"
    if not str(spec.get("entity") or "").strip():
        return "a process names the object type that goes through it in `entity`"
    if spec.get("origin") and spec["origin"] not in ORIGINS:
        return f"a process's origin is one of {', '.join(ORIGINS)}"
    stages = spec.get("stages")
    if not isinstance(stages, list) or not 2 <= len(stages) <= _MAX_STAGES:
        return f"a process has from 2 to {_MAX_STAGES} stages, in the order an object goes through them"
    names: set[str] = set()
    nouns: set[str] = set()
    for i, stage in enumerate(stages):
        problem = _stage_problem(i, stage, stages)
        if problem:
            return problem
        if stage["name"] in names:
            return f"stage '{stage['name']}' is named twice — a stage's name names one stage"
        names.add(stage["name"])
        noun = str((stage.get("promise") or {}).get("name") or stage["name"])
        if noun in nouns:
            return f"two stages derive names from '{noun}' — name a promise (`promise.name`) differently"
        nouns.add(noun)
    return ""


def _stage_fields(stage: dict) -> dict:
    out: dict = {"name": str(stage["name"])}
    if str(stage.get("display_name") or "").strip():
        out["display_name"] = str(stage["display_name"]).strip()
    if str(stage.get("timestamp") or "").strip():
        out["timestamp"] = str(stage["timestamp"]).strip()
    else:
        out["state"] = [str(s).strip() for s in stage["state"]]
        if str(stage.get("property") or "").strip():
            out["property"] = str(stage["property"]).strip()
    promise = stage.get("promise")
    if promise:
        kept: dict = {}
        for key in ("name", "deadline", "grain", "via"):
            if str(promise.get(key) or "").strip():
                kept[key] = str(promise[key]).strip()
        if promise.get("within_days") is not None:
            kept["within_days"] = int(promise["within_days"])
        if promise.get("within_hours") is not None:
            kept["within_hours"] = int(promise["within_hours"])
        if promise.get("target") is not None:
            kept["target"] = float(promise["target"])
        out["promise"] = kept
    return out


def process_fields(spec: dict) -> dict:
    """The override fields a declaration stores — trimmed, the empty parts dropped. Idempotent."""
    out: dict = {"declared": True, "entity": str(spec["entity"]).strip(), "origin": spec.get("origin") or "human",
                 "stages": [_stage_fields(s) for s in spec["stages"]]}
    for key in ("display_name", "description", "owner", "provenance"):
        if str(spec.get(key) or "").strip():
            out[key] = str(spec[key]).strip()
    return out


def process_from_fields(process_id: str, fields: dict) -> Process:
    """The process a declaration describes, unmeasured."""
    stages = []
    for s in fields.get("stages") or []:
        promise = Promise(**s["promise"]) if s.get("promise") else None
        stages.append(ProcessStage(**{k: v for k, v in s.items() if k != "promise"}, promise=promise))
    return Process(id=process_id, display_name=fields.get("display_name") or process_id.replace("_", " ").capitalize(),
                   description=fields.get("description") or "", entity=fields["entity"], stages=stages,
                   owner=fields.get("owner") or "", origin=fields.get("origin") or "human",
                   provenance=fields.get("provenance") or "")


# ── the declaration against the graph ───────────────────────────────────────────────────────


def _temporal(graph: OntologyGraph, entity: OntologyEntity, path: str, what: str) -> str:
    from aughor.semantic.object_query import ObjectQueryRefused, is_temporal, property_at
    try:
        _, prop, _ = property_at(graph, entity.api_name, path, purpose=what)
    except ObjectQueryRefused as exc:
        return f"{what}: {exc.reason}"
    if not is_temporal(prop):
        return f"{what}: {path} on {entity.id} is not a date or timestamp ({prop.data_type or prop.semantic_type or 'untyped'})"
    return ""


def _via(graph: OntologyGraph, grain: OntologyEntity, entity: OntologyEntity, via: str) -> tuple[str, str]:
    """The to-one link path from ``grain`` to ``entity`` — the one named, checked hop by hop, or the only measured
    to-one link between them. (path, "") or ("", why)."""
    from aughor.semantic.object_query import link_problem, object_links
    if via:
        current = grain
        for seg in via.split("."):
            hop = next((h for h in object_links(graph, current) if seg.lower() in (h.name.lower(), h.business.lower())), None)
            if hop is None:
                return "", f"no link '{seg}' from {current.id}"
            problem = link_problem(hop)
            if problem:
                return "", problem
            if not hop.to_one:
                return "", (f"{hop.describe()} is to-many — a promise's objects reach the process's type through to-one "
                            "links only")
            current = hop.target
        if current.id != entity.id:
            return "", f"'{via}' reaches {current.id}, not {entity.id}"
        return via, ""
    hops = [h for h in object_links(graph, grain) if h.target.id == entity.id]
    usable = [h for h in hops if h.to_one and not link_problem(h)]
    if len(usable) == 1:
        return usable[0].name, ""
    if not usable:
        why = "; ".join(link_problem(h) or f"{h.describe()} is to-many" for h in hops)
        return "", (f"no measured to-one link from {grain.id} to {entity.id}" + (f" ({why})" if why else "")
                    + " — declare one (POST /ontology/links), or name the path in `via`")
    return "", f"{len(usable)} links reach {entity.id} from {grain.id} — name one in `via`: {', '.join(h.name for h in usable)}"


def _name_problem(graph: OntologyGraph, process: Process) -> str:
    """A derived name must be free where it lands: a lag among its type's properties, bindings and links; a segment
    among its type's segments; a metric among the graph's metrics — and none already derived by another declaration."""
    from aughor.ontology.bindings import taken_names
    mine = process_derivations(process)
    others = derivations(graph, except_process=process.id)
    for d in mine.properties:
        entity = graph.entities[d.entity]
        taken = taken_names(graph, entity, list(entity.bindings or []))
        if d.name.lower() in taken:
            return f"the lag it derives, {d.name}: {taken[d.name.lower()]} — name the promise or the stage differently"
        if any(o.entity == d.entity and o.name.lower() == d.name.lower() for o in others.properties):
            return f"the lag it derives, {d.name}, is already derived on {d.entity} by another process"
    for d in mine.segments:
        entity = graph.entities.get(d.entity)
        if entity is not None and d.name.lower() in {k.lower() for k in entity.segments or {}}:
            return f"the segment it derives, {d.name}: {d.entity} already has a segment {d.name}"
        if any(o.entity == d.entity and o.name.lower() == d.name.lower() for o in others.segments):
            return f"the segment it derives, {d.name}, is already derived on {d.entity} by another declaration"
    for d in mine.metrics:
        if d.name.lower() in {k.lower() for k in graph.metrics or {}}:
            return f"the metric it derives, {d.name}: a metric {d.name} already exists"
        if any(o.name.lower() == d.name.lower() for o in others.metrics):
            return f"the metric it derives, {d.name}, is already derived by another process"
    return ""


def resolve_process(graph: OntologyGraph, process_id: str, fields: dict) -> tuple[str, dict]:
    """``(problem, fields)``: why this declaration cannot land on THIS graph, or "" and its fields made canonical —
    the type by id, each state stage's property named, each promise's `grain` by id and its `via` resolved. Every
    anchor is resolved by the object door's own path law (`property_at`), so a stage the compiler could not read is
    refused before anything is written."""
    from aughor.semantic.object_query import ObjectQueryRefused, find_object_type, is_temporal, property_at
    try:
        entity = find_object_type(graph, fields["entity"])
    except ObjectQueryRefused as exc:
        return exc.reason, fields
    out = copy.deepcopy(fields)
    out["entity"] = entity.id
    for stage in out["stages"]:
        name = stage["name"]
        if stage.get("timestamp"):
            problem = _temporal(graph, entity, stage["timestamp"], f"stage '{name}'")
            if problem:
                return problem, fields
        else:
            prop_path = stage.get("property") or entity.lifecycle_column or ""
            if not prop_path:
                return (f"stage '{name}' is anchored to a state and {entity.id} has no lifecycle column — name the "
                        "`property` its state is read from"), fields
            try:
                _, prop, _ = property_at(graph, entity.api_name, prop_path, purpose=f"stage '{name}'")
            except ObjectQueryRefused as exc:
                return f"stage '{name}': {exc.reason}", fields
            if is_temporal(prop):
                return f"stage '{name}': {prop_path} is a moment, not a state — anchor the stage to it with `timestamp`", fields
            stage["property"] = prop_path
        promise = stage.get("promise")
        if not promise or not promise.get("deadline"):
            continue
        noun = promise.get("name") or name
        grain = entity
        if promise.get("grain"):
            try:
                grain = find_object_type(graph, promise["grain"])
            except ObjectQueryRefused as exc:
                return f"the {noun} promise: {exc.reason}", fields
        problem = _temporal(graph, grain, promise["deadline"], f"the {noun} promise's deadline")
        if problem:
            return problem, fields
        if grain.id == entity.id:
            if promise.get("via"):
                return f"the {noun} promise is kept per {entity.id}, the process's own type — it needs no `via`", fields
            promise.pop("grain", None)
            continue
        via, problem = _via(graph, grain, entity, promise.get("via") or "")
        if problem:
            return f"the {noun} promise is kept per {grain.id}: {problem}", fields
        promise["grain"], promise["via"] = grain.id, via
    problem = _name_problem(graph, process_from_fields(process_id, out))
    return problem, (fields if problem else out)


# ── measurement ─────────────────────────────────────────────────────────────────────────────


def cell_int(value: Any) -> Optional[int]:
    """A result cell as a whole number, or None for an empty or NULL cell — cells come back as text."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "NULL":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def cell_text(value: Any) -> str:
    """A result cell as trimmed text, "" for an empty or NULL cell."""
    text = "" if value is None else str(value).strip()
    return "" if text.upper() == "NULL" else text


def quantile_cont(histogram: list[tuple[float, int]], q: float) -> Optional[float]:
    """The q-quantile of the values a histogram counts, interpolated between the two nearest order statistics — what
    `quantile_cont` / `PERCENTILE_CONT` compute over the raw values, exactly, from ``(value, count)`` pairs."""
    pairs = sorted((float(v), int(n)) for v, n in histogram if v is not None and n)
    total = sum(n for _, n in pairs)
    if not total:
        return None
    position = (total - 1) * q
    low, high = math.floor(position), math.ceil(position)

    def at(k: int) -> float:
        seen = 0
        for value, n in pairs:
            seen += n
            if k < seen:
                return value
        return pairs[-1][0]

    a, b = at(low), at(high)
    return round(a + (position - low) * (b - a), 6)


class ObjectCounter:
    """Object queries compiled over one graph and run where their rows live — the measurement's only way to the data.
    On one connection's ontology that is ``db``. On an organisation's (ON-8), ``open_source`` opens the connection each
    query's anchor type lives on, and a query whose sources span two runs as the object door runs it, split at its keyed
    reads (`aughor.semantic.cross_source`)."""

    def __init__(self, db: Any, graph: OntologyGraph, open_source: Any = None):
        self.db, self.graph, self.open_source = db, graph, open_source

    def rows(self, query: dict, *, max_rows: int = 500) -> tuple[list[str], list]:
        from aughor.semantic.object_query import ObjectQueryRefused, compile_object_query, find_object_type
        home_db, home, opened = self.db, "", None
        try:
            if self.open_source is not None:
                from aughor.ontology.sources import entity_source
                try:
                    anchor = find_object_type(self.graph, str(query.get("object_type") or ""))
                except ObjectQueryRefused as exc:
                    raise NotMeasurable(exc.reason) from exc
                home = entity_source(self.graph, anchor)
                home_db = opened = self.open_source(home)
            try:
                compiled = compile_object_query(query, self.graph, dialect=getattr(home_db, "dialect", "") or "duckdb",
                                                fiscal_start_month=1)
            except ObjectQueryRefused as exc:
                raise NotMeasurable(exc.reason) from exc
            try:
                if compiled.cross_source is not None:
                    if self.open_source is None:
                        raise NotMeasurable("the count reads sources on more than one connection, and this ontology "
                                            "reads one")
                    from aughor.semantic.cross_source import execute_plan
                    result, _ = execute_plan(compiled.cross_source, home_connection_id=home, home_db=home_db,
                                             open_source=self.open_source, label="__process_probe__",
                                             display_sql=compiled.sql)
                else:
                    bounded = getattr(home_db, "execute_bounded", None)
                    result = (bounded("__process_probe__", compiled.sql, max_rows) if callable(bounded)
                              else home_db.execute("__process_probe__", compiled.sql))
            except NotMeasurable:
                raise
            except Exception as exc:  # noqa: BLE001 — a failed count is an unmeasured declaration, not a crash
                raise NotMeasurable(f"{type(exc).__name__}: {exc}") from exc
        finally:
            if opened is not None:
                opened.close()
        if getattr(result, "error", None):
            raise NotMeasurable(str(result.error)[:300])
        return list(getattr(result, "columns", None) or []), list(getattr(result, "rows", None) or [])

    def one(self, object_type: str, measures: list[dict], filters: Optional[list[dict]] = None) -> dict:
        columns, rows = self.rows({"object_type": object_type, "measures": measures, "filters": filters or []})
        if not rows:
            raise NotMeasurable("the count returned no row")
        return {str(c): rows[0][i] for i, c in enumerate(columns)}


def _provisional(process: Process) -> Process:
    """A copy that reads as measured, so the object door compiles what the process derives WHILE it is being counted.
    Never saved, never served."""
    work = process.model_copy(deep=True)
    work.verified = True
    for stage in work.stages:
        stage.verified = True
        if stage.promise is not None:
            stage.promise.verified = True
    return work


def _reached_filters(stage: ProcessStage) -> list[dict]:
    if stage.timestamp:
        return [{"path": stage.timestamp, "op": "not_null"}]
    return [{"path": stage.property, "op": "in", "values": list(stage.state)}]


def _cutoff(as_of: str, days: int) -> str:
    """The date ``days`` calendar days before ``as_of``'s date: a moment before it is more than ``days`` days back."""
    try:
        moment = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        day = moment.date()
    except ValueError:
        day = date.fromisoformat(as_of[:10])
    return (day - timedelta(days=days)).isoformat()


def _cutoff_hours(as_of: str, hours: int) -> str:
    """The moment ``hours`` hours before ``as_of``: a moment before it is more than ``hours`` hours back."""
    moment = datetime.fromisoformat(as_of.replace("Z", "+00:00").replace("T", " ")).replace(tzinfo=None)
    return (moment - timedelta(hours=hours)).isoformat(sep=" ", timespec="seconds")


#: The prefix of the flag raised when impossible rows MOVE the number. LOAD-BEARING TEXT, not
#: a label — the departure gate matches on it to decide that a caveat refutes the figure
#: rather than qualifying it, exactly as `TRUST_BANNER` is matched in departing text. A reword
#: here without the same reword at the gate would unhook the hold silently, which is why
#: `tests/unit/test_departure_laws.py` locks the round trip.
IMPOSSIBLE_LAG_FLAG = "counted as kept although impossible"

#: The same finding when the two readings agree within the noise band: still said, never a
#: hold. A DISTINCT prefix, not a suffix on the one above — a `startswith` match against a
#: shared stem would block both and the distinction would exist only in the prose.
IMPOSSIBLE_LAG_NOISE_FLAG = "impossible lag, within the noise band"

#: How far the two readings must differ before the impossible rows refute the number rather
#: than qualify it — relative, |a-b| / max(|a|,|b|). This is the platform's OWN bar for two
#: readings of one number disagreeing materially (`govern.departure.NOISE_REL`, itself the
#: deep run's `_METRIC_DIVERGENCE_REL`); it is restated here rather than imported because the
#: ontology does not depend on govern, and `tests/unit/test_departure_laws.py` asserts the two
#: stay equal so the restatement cannot drift.
#:
#: Measured 2026-09-20, the three live promises carrying impossible rows: LuxExperience's
#: refund 23.27% → 25.41% (8.4% relative, HOLDS), theLook's dispatch 9.35% → 9.47% (1.2%) and
#: its delivery 8.11% → 8.11% (0.0%). Holding every one of them would stop two working sends
#: over a tenth of a point and nothing at all; saying nothing about the first would let a
#: number the measurement itself refutes leave the building.
IMPOSSIBLE_LAG_MATERIAL_REL = 0.05


def _flag_out_of_order(promise: Any, stage: ProcessStage, spec: dict, process: Process, grain: Any) -> None:
    """Carry the stage's impossible orderings onto the PROMISE, with what they do to its rate.

    The measurement already counts objects whose moment here precedes the previous stage's
    (`stage.out_of_order`) and already says so — in `stage.note`, one level up from the
    promise block. But the promise is what a reader is shown and what departs, and its rate
    is computed over a population that silently includes those objects on the KEPT side: a
    negative lag is never greater than the window. Live on LuxExperience 2026-09-20: 4,199
    of 50,048 Returns were refunded BEFORE they were received, the promise read 23.27%
    breached with `flags: []`, and without them it is 25.41% — the failure understated by
    2.14 points, in the business's favour, on a number that leaves the platform.

    The alternative rate is arithmetic, not a second query, and it is only stated when it is
    SOUND to state:

    * a window promise, never a `deadline` one — `out_of_order` compares this stage's moment
      with the PREVIOUS stage's, which is the window's start (`derived.promise_filters`) but
      has nothing to do with a deadline column;
    * the promise counted per the process's own type, so the two counts share a population
      (`promise.grain` may name another);
    * and at least one object left once they are removed.

    When any of those fails the ordering is still flagged, just without a rate — saying less
    beats saying something that was derived from the wrong denominator.
    """
    early = stage.out_of_order or 0
    if not early or not promise.reached:
        return
    previous_name = spec.get("start")
    if not previous_name:
        # A deadline promise. `out_of_order` compares this stage's moment with the PREVIOUS
        # STAGE's, and the deadline has nothing to do with either — an object that arrived
        # out of order can still miss its deadline, so "cannot break the promise" would be
        # a false sentence here, not merely an unhelpful one.
        return
    remaining = promise.reached - early
    if spec.get("grain") == process.entity and remaining > 0:
        without = promise.breached / remaining
        moved = abs(without - promise.breach_rate) / max(abs(without), abs(promise.breach_rate) or 1.0)
        prefix = IMPOSSIBLE_LAG_FLAG if moved >= IMPOSSIBLE_LAG_MATERIAL_REL else IMPOSSIBLE_LAG_NOISE_FLAG
        promise.flags.append(
            f"{prefix}: {early:,} of the {promise.reached:,} {grain.id} objects reached "
            f"{stage.name} BEFORE {previous_name}, so their lag is negative and none of them can break the promise — "
            f"without them the rate is {without:.2%}, not {promise.breach_rate:.2%}")
        return
    # The rate could not be computed, so the impossible rows are not KNOWN to be immaterial.
    # Unquantified is not the same as small, and the conservative direction is the blocking one.
    promise.flags.append(
        f"{IMPOSSIBLE_LAG_FLAG}: {early:,} of the {promise.reached:,} {grain.id} objects reached "
        f"{stage.name} BEFORE {previous_name}, so their lag is negative and none of them can break the promise")


def _measure_promise(counter: ObjectCounter, work: OntologyGraph, process: Process, index: int, measured: Process) -> None:
    spec = promise_filters(work.processes[process.id], index)
    stage = measured.stages[index]
    promise = stage.promise
    if spec is None or promise is None:
        return
    grain = work.entities[spec["grain"]]
    counts = counter.one(grain.api_name, [
        {"name": "objects", "agg": "count"},
        {"name": "reached", "agg": "count", "where": list(spec["reached"])},
        {"name": "breached", "agg": "count", "where": list(spec["breach"])},
        {"name": "still_open", "agg": "count", "where": list(spec["open"])},
        {"name": "as_of", "agg": "max", "path": spec["moment"]},
    ])
    promise.objects, promise.reached = cell_int(counts.get("objects")), cell_int(counts.get("reached")) or 0
    promise.breached, promise.open = cell_int(counts.get("breached")) or 0, cell_int(counts.get("still_open")) or 0
    promise.as_of = cell_text(counts.get("as_of"))
    promise.kept = promise.reached - promise.breached
    promise.open_overdue = None
    if promise.as_of and promise.open:
        overdue = ([{"path": spec["deadline"], "op": "<", "value": promise.as_of}] if spec.get("deadline")
                   else [{"path": spec["start"], "op": "<", "value": _cutoff_hours(promise.as_of, spec["within_hours"])}]
                   if spec.get("within_hours") is not None
                   else [{"path": spec["start"], "op": "<", "value": _cutoff(promise.as_of, spec["within_days"])}])
        promise.open_overdue = cell_int(counter.one(grain.api_name, [
            {"name": "overdue", "agg": "count", "where": list(spec["open"]) + overdue}]).get("overdue")) or 0
    noun = promise_noun(stage)
    what = (f"the {promise.deadline} deadline" if promise.deadline else
            f"{promise.within_hours} hours" if promise.within_hours is not None else f"{promise.within_days} calendar days")
    check = (f"check {spec['deadline']} and the moment it is compared with, {spec['moment']}" if spec.get("deadline")
             else f"check the two moments the days are counted between, {spec['start']} and {spec['moment']}")
    promise.flags = []
    if not promise.reached:
        promise.verified, promise.breach_rate = False, None
        promise.note = f"no {grain.id} object reached {stage.name} with the {noun} promise in force"
        return
    promise.verified = True
    promise.breach_rate = round(promise.breached / promise.reached, 6)
    if promise.breached == 0:
        promise.flags.append(f"never broken: none of the {promise.reached:,} {grain.id} objects that reached "
                             f"{stage.name} went past {what} — {check}")
    elif promise.breached == promise.reached:
        promise.flags.append(f"always broken: every one of the {promise.reached:,} {grain.id} objects that reached "
                             f"{stage.name} went past {what} — {check}")
    _flag_out_of_order(promise, stage, spec, process, grain)
    promise.note = (f"{promise.breached:,} of the {promise.reached:,} {grain.id} objects that reached {stage.name} broke "
                    f"the {noun} promise ({promise.breach_rate:.2%}); {promise.open:,} have not reached it"
                    + (f", {promise.open_overdue:,} of them already past it as of {promise.as_of}"
                       if promise.open_overdue is not None else ""))


def measure_process(db: Any, graph: OntologyGraph, process_id: str, fields: dict, *, open_source: Any = None) -> Process:
    """Count a (resolved) declaration against the warehouse through the object door's compiler and return the process
    with every number and verdict stamped. Raises `NotMeasurable` when a count cannot be taken. On an organisation's
    ontology ``db`` is None and ``open_source`` opens each count's connection (`ObjectCounter`)."""
    process = process_from_fields(process_id, fields)
    work = graph.model_copy()
    work.processes = {**(graph.processes or {}), process_id: _provisional(process)}
    entity = work.entities.get(process.entity)
    if entity is None:
        raise NotMeasurable(f"no object type '{process.entity}' in this ontology")
    counter = ObjectCounter(db, work, open_source)
    measures: list[dict] = [{"name": "objects", "agg": "count"}]
    for i, stage in enumerate(process.stages):
        measures.append({"name": f"reached_{i}", "agg": "count", "where": _reached_filters(stage)})
        previous = process.stages[i - 1] if i else None
        if stage.timestamp and previous is not None and previous.timestamp:
            measures += [
                {"name": f"both_{i}", "agg": "count", "where": [{"path": previous.timestamp, "op": "not_null"},
                                                                  {"path": stage.timestamp, "op": "not_null"}]},
                {"name": f"skipped_{i}", "agg": "count", "where": [{"path": stage.timestamp, "op": "not_null"},
                                                                     {"path": previous.timestamp, "op": "is_null"}]},
                {"name": f"early_{i}", "agg": "count", "where": [{"path": stage.timestamp, "op": "<",
                                                                   "value_path": previous.timestamp}]},
            ]
    counts = counter.one(entity.api_name, measures)
    measured = process.model_copy(deep=True)
    measured.objects = cell_int(counts.get("objects")) or 0
    for i, stage in enumerate(measured.stages):
        previous = measured.stages[i - 1] if i else None
        stage.reached = cell_int(counts.get(f"reached_{i}")) or 0
        anchor = stage.timestamp or f"{stage.property} in {', '.join(stage.state)}"
        if stage.reached:
            stage.verified = True
            stage.note = f"{stage.reached:,} of {measured.objects:,} {entity.id} objects reached {stage.name} ({anchor})"
        else:
            stage.verified = False
            stage.note = (f"no {entity.id} object reaches {stage.name} — {stage.timestamp} is never set" if stage.timestamp
                          else f"no {entity.id} object is in {', '.join(stage.state)}")
        if not (stage.timestamp and previous is not None and previous.timestamp):
            continue
        stage.both = cell_int(counts.get(f"both_{i}")) or 0
        stage.skipped = cell_int(counts.get(f"skipped_{i}")) or 0
        stage.out_of_order = cell_int(counts.get(f"early_{i}")) or 0
        if stage.both:
            columns, rows = counter.rows({
                "object_type": entity.api_name, "by": [lag_name(stage)], "measures": [{"name": "n", "agg": "count"}],
                "filters": [{"path": previous.timestamp, "op": "not_null"}, {"path": stage.timestamp, "op": "not_null"}]},
                max_rows=_MAX_LAG_VALUES + 1)
            if len(rows) > _MAX_LAG_VALUES:
                stage.note += f"; more than {_MAX_LAG_VALUES:,} distinct day counts — percentiles not taken"
            else:
                histogram = [(float(r[0]), cell_int(r[1]) or 0) for r in rows if cell_text(r[0])]
                stage.p50_days, stage.p90_days, stage.p95_days = (quantile_cont(histogram, q) for q in (0.5, 0.9, 0.95))
        if stage.out_of_order:
            stage.note += f"; {stage.out_of_order:,} reached {stage.name} BEFORE {previous.name}"
        if stage.skipped:
            stage.note += f"; {stage.skipped:,} reached {stage.name} with no moment for {previous.name}"
    for i, stage in enumerate(measured.stages):
        if stage.promise is not None:
            _measure_promise(counter, work, process, i, measured)
    verdicts = [s.verified for s in measured.stages] + [s.promise.verified for s in measured.stages if s.promise]
    measured.verified = bool(measured.objects) and all(v is True for v in verdicts)
    reached = sum(1 for s in measured.stages if s.verified)
    promises = [s for s in measured.stages if s.promise is not None]
    measured.note = (f"{measured.objects:,} {entity.id} objects; {reached} of {len(measured.stages)} stages reached"
                     + (f"; {len(promises)} promise{'s' if len(promises) != 1 else ''} measured" if promises else ""))
    measured.measured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return measured


# ── the override file ───────────────────────────────────────────────────────────────────────


def substance(fields: dict) -> dict:
    """What a measurement is OF: the type and the stages. Renaming the process, describing it, naming its owner or
    confirming a model's proposal changes none of it, so the measurement stands."""
    return {"entity": fields.get("entity"), "stages": fields.get("stages")}


def process_entry(fields: dict, measured: Process) -> dict:
    return {"bound": True, "note": measured.note, "substance": substance(fields),
            "measured": measured.model_dump(mode="json")}


def declared_process(ov, graph: Optional[OntologyGraph]) -> Optional[Process]:
    """The process an override describes, with what its measurement recorded when that measurement is of these very
    stages — no database. None when it never bound or its type is not in the graph."""
    fields, entry = ov.fields, ov.binding.get("process") or {}
    if not fields.get("declared") or entry.get("bound") is not True:
        return None
    if graph is not None and fields.get("entity") not in graph.entities:
        return None
    base = process_from_fields(ov.target_id, fields)
    measured = entry.get("measured")
    if isinstance(measured, dict) and entry.get("substance") == substance(fields):
        try:
            stamped = Process.model_validate(measured)
        except Exception:  # noqa: BLE001 — a hand-edited measurement reads as unmeasured, never as verified
            stamped = None
        if stamped is not None:
            return stamped.model_copy(update={k: getattr(base, k) for k in
                                              ("id", "display_name", "description", "owner", "origin", "provenance")})
    base.note = "declared; its stages changed since they were counted — POST /ontology/measure counts them again"
    return base


def measure_override_processes(connection_id: str, schema_name: Optional[str], db: Any,
                               graph: Optional[OntologyGraph], *, open_source: Any = None,
                               save: Any = None) -> list[dict]:
    """Re-resolve and re-count every declared process against the SERVED graph (declared types, links and bindings in
    it) and record what was counted on its override file. A process whose anchors no longer resolve is measured-false
    with the reason; one that cannot be counted on this pass keeps no verdict. One summary row per process. On an
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
        if ov.target_kind != "process" or not ov.fields.get("declared"):
            continue
        problem, resolved = resolve_process(graph, ov.target_id, ov.fields)
        if problem:
            measured = process_from_fields(ov.target_id, ov.fields)
            measured.verified, measured.note = False, f"no longer resolves on this graph: {problem}"[:500]
            measured.measured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        else:
            try:
                measured = measure_process(db, graph, ov.target_id, resolved, open_source=open_source)
                ov.fields = resolved
            except NotMeasurable as exc:
                measured = process_from_fields(ov.target_id, ov.fields)
                measured.note = f"not measurable on this pass: {exc}"[:500]
        ov.binding["process"] = process_entry(ov.fields, measured)
        try:
            save(connection_id, schema_name or "default", ov)
        except Exception as exc:  # noqa: BLE001
            logger.debug("process measurement not saved for %s: %s", ov.target_id, exc)
        out.append({"process": ov.target_id, "verified": measured.verified, "objects": measured.objects,
                    "note": measured.note,
                    "promises": [{"stage": s.name, "promise": promise_noun(s), "reached": s.promise.reached,
                                  "breached": s.promise.breached, "breach_rate": s.promise.breach_rate,
                                  "flags": list(s.promise.flags)} for s in measured.stages if s.promise is not None]})
    return out


# ── what a person and an agent read ─────────────────────────────────────────────────────────


def describe_process(graph: OntologyGraph, process: Process) -> dict:
    """One process as the map's panel and the API show it: each stage with its anchor and how many objects reach it,
    each transition timed, each promise with its counts, flags and the names it derives."""
    entity = graph.entities.get(process.entity)
    api = (lambda eid: graph.entities[eid].api_name if eid in graph.entities else eid)  # noqa: E731
    stages = []
    for i, stage in enumerate(process.stages):
        previous = process.stages[i - 1] if i else None
        row: dict = {"name": stage.name, "display_name": stage.display_name or stage.name.replace("_", " "),
                     "anchor": ({"timestamp": stage.timestamp} if stage.timestamp
                                else {"state": list(stage.state), "property": stage.property}),
                     "reached": stage.reached,
                     "share": (round(stage.reached / process.objects, 6)
                               if stage.reached is not None and process.objects else None),
                     "verified": stage.verified, "note": stage.note, "transition": None, "promise": None}
        if stage.timestamp and previous is not None and previous.timestamp:
            row["transition"] = {"from": previous.name, "both": stage.both, "skipped": stage.skipped,
                                 "out_of_order": stage.out_of_order, "p50_days": stage.p50_days,
                                 "p90_days": stage.p90_days, "p95_days": stage.p95_days, "lag": lag_name(stage)}
        promise = stage.promise
        if promise is not None:
            spec = promise_filters(process, i)
            grain = spec["grain"] if spec else (promise.grain or process.entity)
            kind = ("deadline" if promise.deadline else
                    "within_hours" if promise.within_hours is not None else "within_days")
            row["promise"] = {"name": promise_noun(stage), "kind": kind, "deadline": promise.deadline,
                              "within_days": promise.within_days, "within_hours": promise.within_hours,
                              "grain": api(grain), "grain_id": grain, "via": promise.via, "target": promise.target,
                              "objects": promise.objects, "reached": promise.reached, "breached": promise.breached,
                              "kept": promise.kept, "open": promise.open, "open_overdue": promise.open_overdue,
                              "breach_rate": promise.breach_rate, "as_of": promise.as_of, "verified": promise.verified,
                              "flags": list(promise.flags), "note": promise.note,
                              "segment": late_name(stage), "metric": rate_name(stage)}
        stages.append(row)
    return {"id": process.id, "display_name": process.display_name or process.id, "description": process.description,
            "entity": entity.api_name if entity is not None else process.entity, "entity_id": process.entity,
            "owner": process.owner, "origin": process.origin, "provenance": process.provenance,
            "objects": process.objects, "verified": process.verified, "note": process.note,
            "measured_at": process.measured_at, "stages": stages, "derived": rows_of(process_derivations(process))}


def processes_of(graph: OntologyGraph, entity: OntologyEntity) -> list[dict]:
    """The processes ``entity`` takes part in — as the type that goes through one, or as the type a promise is kept
    per — one short row each."""
    out = []
    for process in sorted((graph.processes or {}).values(), key=lambda p: p.id):
        roles = []
        if process.entity == entity.id:
            roles.append("goes through it")
        for i, stage in enumerate(process.stages):
            spec = promise_filters(process, i)
            if spec is not None and spec["grain"] == entity.id and process.entity != entity.id:
                roles.append(f"keeps its {promise_noun(stage)} promise")
        if roles:
            out.append({"id": process.id, "display_name": process.display_name or process.id, "roles": roles,
                        "verified": process.verified, "stages": [s.name for s in process.stages]})
    return out


__all__ = ["Derivations", "NotMeasurable", "declared_process", "describe_process", "measure_override_processes",
           "measure_process", "process_entry", "process_fields", "process_from_fields", "process_spec_problem",
           "processes_of", "quantile_cont", "resolve_process", "substance"]
