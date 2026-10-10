"""Arc OC-5 — impacts: what one declared promise does to another, declared with its mechanism and measured.

ON-9 made a promise measurable on its own: how many objects reached a stage with it in force and how many broke it.
Nothing said that one promise moves another — that an order whose lines missed their dispatch limit misses its
delivery date more often — so "what is causing delivery delays" started from every dimension at equal distance, and a
Briefing that saw delivery slip could not point at dispatch. An impact is that statement, declared by a person (or a
pack) and measured before it is believed (`Impact`):

* **influence** — counted through the object door's own compiler, at the downstream promise's LEAD object (the type it
  is kept per). The upstream promise is reached from there through the graph's measured links: a to-one link reads
  the one upstream object; a to-many link reads "at least one of them broke it", an EXISTS, so no object is counted
  twice and none collapses into another's number. Of the lead objects that reached the downstream stage with its
  promise in force: how many saw the upstream promise broken and how many saw it kept, and the downstream breach rate
  in each — with the lag between the two moments when both are the lead object's own, and the window read. An
  influence the data does not bear out (too few objects on a side, or no higher rate when the upstream promise broke)
  is measured-false and says which;
* **validated** — an influence promoted on recorded evidence, measured the same way;
* **formula** — exact by definition, in words; nothing is measured, and a reader is told so.

An association is never a cause. Every reader words an impact by its mechanism (`impact_words`).
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from aughor.ontology.derived import cutoff_days, promise_filters, promise_noun
from aughor.ontology.models import PROCESS_NAME_PATTERN, Impact, OntologyGraph, Process
from aughor.ontology.processes import ORIGINS, NotMeasurable, ObjectCounter, cell_int

logger = logging.getLogger(__name__)

MECHANISMS = ("influence", "validated", "formula")
#: The fewest lead objects a side of the comparison may hold before its rate is read as evidence.
MIN_GROUP = 30
_MAX_WINDOW_DAYS = 3650
_MAX_HOPS = 2


# ── the declaration ─────────────────────────────────────────────────────────────────────────────────────────────────

def _ref_problem(ref: Any, which: str) -> str:
    pid, _, noun = str(ref or "").partition(".")
    if not (PROCESS_NAME_PATTERN.match(pid) and noun.strip()):
        return f"`{which}` names a promise as <process id>.<promise> — order_fulfilment.dispatch"
    return ""


def impact_spec_problem(spec: Any) -> str:
    """Why an impact cannot be declared as written, or "" — its shape only."""
    if not isinstance(spec, dict):
        return "an impact is declared as a mapping with `id`, `upstream`, `downstream` and its `mechanism`"
    if not PROCESS_NAME_PATTERN.match(str(spec.get("id") or "")):
        return "an impact id is snake_case — late_dispatch_late_delivery"
    for which in ("upstream", "downstream"):
        problem = _ref_problem(spec.get(which), which)
        if problem:
            return problem
    if str(spec["upstream"]).strip() == str(spec["downstream"]).strip():
        return "an impact runs from one promise to ANOTHER — upstream and downstream name the same one"
    mechanism = spec.get("mechanism") or "influence"
    if mechanism not in MECHANISMS:
        return f"an impact's mechanism is one of {', '.join(MECHANISMS)}"
    if mechanism == "formula" and not str(spec.get("formula") or "").strip():
        return "a formula impact says, in `formula`, the definition that makes it exact"
    if mechanism == "validated" and not str(spec.get("evidence") or "").strip():
        return "a validated impact names its recorded evidence in `evidence` — a decision's outcome or an intervention"
    window = spec.get("window_days")
    if window is not None and (not isinstance(window, int) or isinstance(window, bool)
                               or not 1 <= window <= _MAX_WINDOW_DAYS):
        return f"`window_days` is a whole number of days from 1 to {_MAX_WINDOW_DAYS}, or absent for all of the data"
    if spec.get("origin") and spec["origin"] not in ORIGINS:
        return f"an impact's origin is one of {', '.join(ORIGINS)}"
    return ""


def impact_fields(spec: dict) -> dict:
    """The override fields a declaration stores. Idempotent."""
    out: dict = {"declared": True, "upstream": str(spec["upstream"]).strip(),
                 "downstream": str(spec["downstream"]).strip(), "mechanism": spec.get("mechanism") or "influence",
                 "origin": spec.get("origin") or "human"}
    if spec.get("window_days") is not None:
        out["window_days"] = int(spec["window_days"])
    for key in ("display_name", "description", "owner", "provenance", "formula", "evidence"):
        if str(spec.get(key) or "").strip():
            out[key] = str(spec[key]).strip()
    for key in ("lead", "path", "to_many"):          # resolved — kept when a stored declaration is read again
        if key in spec:
            out[key] = spec[key]
    return out


def impact_from_fields(impact_id: str, fields: dict) -> Impact:
    return Impact(id=impact_id, display_name=fields.get("display_name") or impact_id.replace("_", " ").capitalize(),
                  description=fields.get("description") or "", owner=fields.get("owner") or "",
                  upstream=fields["upstream"], downstream=fields["downstream"],
                  mechanism=fields.get("mechanism") or "influence", formula=fields.get("formula") or "",
                  evidence=fields.get("evidence") or "", window_days=fields.get("window_days"),
                  origin=fields.get("origin") or "human", provenance=fields.get("provenance") or "",
                  lead=fields.get("lead") or "", path=fields.get("path") or "", to_many=bool(fields.get("to_many")))


def promise_at(graph: OntologyGraph, ref: str) -> tuple[Optional[Process], int]:
    """The process and stage index a ``<process id>.<promise>`` reference names — the promise's noun (its own name,
    else its stage's) — or ``(None, -1)``."""
    pid, _, noun = (ref or "").partition(".")
    process = (graph.processes or {}).get(pid)
    if process is None:
        return None, -1
    low = noun.strip().lower()
    index = next((i for i, s in enumerate(process.stages)
                  if s.promise is not None and promise_noun(s).lower() == low), -1)
    return (process, index) if index >= 0 else (None, -1)


def link_path(graph: OntologyGraph, start: str, goal: str) -> Optional[tuple[str, bool]]:
    """The shortest path of traversable links from entity ``start`` to entity ``goal`` (at most two hops), as the
    object door names it, and whether it crosses a to-many link — to-one paths preferred at equal length. None when no
    such path exists. ``("", False)`` when they are the same entity."""
    from aughor.semantic.object_query import link_problem, object_links
    if start == goal:
        return "", False
    found: list[tuple[int, bool, str]] = []
    queue: deque[tuple[str, list[str], bool]] = deque([(start, [], False)])
    while queue:
        at, names, many = queue.popleft()
        if len(names) >= _MAX_HOPS:
            continue
        entity = graph.entities.get(at)
        if entity is None:
            continue
        for link in object_links(graph, entity):
            if link_problem(link) or link.target.id in (start,) or link.name in names:
                continue
            step = (link.target.id, [*names, link.name], many or not link.to_one)
            if link.target.id == goal:
                found.append((len(step[1]), step[2], ".".join(step[1])))
            else:
                queue.append(step)
    if not found:
        return None
    hops, many, path = min(found)
    return path, many


def resolve_impact(graph: OntologyGraph, impact_id: str, fields: dict) -> tuple[str, dict]:
    """Resolve both promises on the served graph and the path from the downstream promise's lead object to the
    upstream one's: ``(problem, fields)`` — the fields with ``lead``, ``path`` and ``to_many`` filled — or the reason
    it does not resolve."""
    ends = {}
    for which in ("upstream", "downstream"):
        process, index = promise_at(graph, fields[which])
        if process is None:
            return (f"{which} '{fields[which]}' is not a declared promise here — name it <process id>.<promise>, as a "
                    "process's panel lists it"), fields
        spec = promise_filters(process, index)
        if spec is None:
            return (f"{which} '{fields[which]}' is a promise the object door cannot read (a window promise reached "
                    "through a link)"), fields
        ends[which] = (process, index, spec)
    if fields.get("mechanism") != "formula":
        for which, (process, index, _spec) in ends.items():
            if process.stages[index].promise.verified is not True:
                return (f"{which} '{fields[which]}' has not been measured to hold — an influence is read only between "
                        "measured promises"), fields
    lead, upstream_grain = ends["downstream"][2]["grain"], ends["upstream"][2]["grain"]
    path = link_path(graph, lead, upstream_grain)
    if path is None:
        return (f"no measured link joins {lead} (the downstream promise is kept per it) to {upstream_grain} (the "
                f"upstream one's) within {_MAX_HOPS} hops"), fields
    return "", {**fields, "lead": lead, "path": path[0], "to_many": path[1]}


# ── the measurement ─────────────────────────────────────────────────────────────────────────────────────────────────

def _prefixed(filters, prefix: str) -> list[dict]:
    out = []
    for f in filters:
        g = dict(f)
        if prefix:
            g["path"] = f"{prefix}.{g['path']}"
            if g.get("value_path"):
                g["value_path"] = f"{prefix}.{g['value_path']}"
        out.append(g)
    return out


def upstream_filters(spec: dict, path: str) -> tuple[list[dict], list[dict]]:
    """The upstream promise read from the lead object: ``(broke, reached)``. Through a to-many link each condition is
    "at least one linked object" (an EXISTS), and breaking implies reaching, so the lead objects that reached and did
    not break are the reached ones less the broken ones — counted, never re-derived."""
    return _prefixed(spec["breach"], path), _prefixed(spec["reached"], path)


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 6) if whole else None


def measure_impact(db: Any, graph: OntologyGraph, impact_id: str, fields: dict, *, open_source: Any = None) -> Impact:
    """Count a resolved impact through the object door's compiler and return it with every number and verdict stamped.
    A formula impact is returned unmeasured, said. Raises `NotMeasurable` when a count cannot be taken."""
    impact = impact_from_fields(impact_id, fields)
    impact.measured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if impact.mechanism == "formula":
        impact.verified = None
        impact.note = f"exact by definition ({impact.formula}) — not an association, so nothing is measured"
        return impact
    down_process, down_index = promise_at(graph, impact.downstream)
    up_process, up_index = promise_at(graph, impact.upstream)
    if down_process is None or up_process is None:
        raise NotMeasurable("a promise it names is no longer declared")
    down, up = promise_filters(down_process, down_index), promise_filters(up_process, up_index)
    lead = graph.entities.get(down["grain"])
    if lead is None:
        raise NotMeasurable(f"no entity '{down['grain']}' in this ontology")
    population = list(down["reached"])
    promise = down_process.stages[down_index].promise
    impact.as_of = promise.as_of
    if impact.window_days and promise.as_of:
        since = cutoff_days(promise.as_of, impact.window_days)
        population.append({"path": down["moment"], "op": ">=", "value": since})
        impact.window = f"the {impact.window_days} days to {promise.as_of[:10]} ({down['moment']} on or after {since})"
    else:
        impact.window = f"all of the data, to {promise.as_of[:10]}" if promise.as_of else "all of the data"
    broke, reached = upstream_filters(up, impact.path)
    breach = list(down["breach"])
    counts = ObjectCounter(db, graph, open_source).one(lead.api_name, [
        {"name": "objects", "agg": "count"},
        {"name": "up_broke", "agg": "count", "where": broke},
        {"name": "up_broke_down_broke", "agg": "count", "where": broke + breach},
        {"name": "up_reached", "agg": "count", "where": reached},
        {"name": "up_reached_down_broke", "agg": "count", "where": reached + breach},
    ], filters=population)
    objects = cell_int(counts.get("objects")) or 0
    n_broke, b_broke = cell_int(counts.get("up_broke")) or 0, cell_int(counts.get("up_broke_down_broke")) or 0
    n_reached, b_reached = cell_int(counts.get("up_reached")) or 0, cell_int(counts.get("up_reached_down_broke")) or 0
    impact.objects, impact.upstream_broke, impact.upstream_kept = objects, n_broke, n_reached - n_broke
    impact.rate_when_broke = _rate(b_broke, n_broke)
    impact.rate_when_kept = _rate(b_reached - b_broke, n_reached - n_broke)
    stage = down_process.stages[down_index]
    if not impact.path and down.get("start") and down["start"] == up["moment"]:
        impact.lag_days = stage.p50_days            # the downstream clock starts at the upstream stage's moment
    impact.flags = []
    down_noun, up_noun = promise_noun(stage), promise_noun(up_process.stages[up_index])
    lead_word = lead.id
    if not objects:
        impact.verified = False
        impact.note = f"no {lead_word} object reached {stage.name} with the {down_noun} promise in force ({impact.window})"
        return impact
    if impact.to_many:
        impact.flags.append(f"read through a to-many link: each {lead_word} counts as broken upstream when at least one "
                            f"of its linked objects broke the {up_noun} promise")
    small = [side for side, n in (("broken", n_broke), ("kept", impact.upstream_kept)) if n < MIN_GROUP]
    if small:
        impact.verified = False
        impact.note = (f"too few to read: the {up_noun} promise was {' and '.join(small)} on fewer than {MIN_GROUP} of the "
                       f"{objects:,} {lead_word} objects")
        return impact
    higher = (impact.rate_when_broke or 0.0) > (impact.rate_when_kept or 0.0)
    impact.verified = higher
    impact.note = (f"of the {objects:,} {lead_word} objects that reached {stage.name} with the {down_noun} promise in "
                   f"force ({impact.window}), {n_broke:,} saw the {up_noun} promise broken and "
                   f"{impact.rate_when_broke:.2%} of those broke {down_noun}, against {impact.rate_when_kept:.2%} of the "
                   f"{impact.upstream_kept:,} that saw it kept"
                   + (f"; {stage.name} came a median {impact.lag_days:g} days after {up['moment']}"
                      if impact.lag_days is not None else "")
                   + ("" if higher else f" — the data does not show {down_noun} broken more often when {up_noun} was"))
    return impact


# ── the override file ───────────────────────────────────────────────────────────────────────────────────────────────

def _substance(fields: dict) -> dict:
    return {k: fields.get(k) for k in ("upstream", "downstream", "mechanism", "window_days", "path")}


def impact_entry(fields: dict, measured: Impact) -> dict:
    return {"bound": True, "note": measured.note, "substance": _substance(fields),
            "measured": measured.model_dump(mode="json")}


def declared_impact(ov, graph: Optional[OntologyGraph]) -> Optional[Impact]:
    """The impact an override describes, with what its measurement recorded when it is of this very definition."""
    fields, entry = ov.fields, ov.binding.get("impact") or {}
    if not fields.get("declared") or entry.get("bound") is not True:
        return None
    if graph is not None and any(promise_at(graph, fields.get(w) or "")[0] is None for w in ("upstream", "downstream")):
        return None
    base = impact_from_fields(ov.target_id, fields)
    measured = entry.get("measured")
    if isinstance(measured, dict) and entry.get("substance") == _substance(fields):
        try:
            stamped = Impact.model_validate(measured)
        except Exception:  # noqa: BLE001
            stamped = None
        if stamped is not None:
            return stamped.model_copy(update={k: getattr(base, k) for k in
                                              ("id", "display_name", "description", "owner", "origin", "provenance",
                                               "formula", "evidence")})
    base.note = "declared; its definition changed since it was counted — POST /ontology/measure counts it again"
    return base


def measure_override_impacts(connection_id: str, schema_name: Optional[str], db: Any,
                             graph: Optional[OntologyGraph], *, open_source: Any = None,
                             save: Any = None) -> list[dict]:
    """Re-resolve and re-count every declared impact against the served graph (after its processes were counted);
    one summary row per impact."""
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
        if ov.target_kind != "impact" or not ov.fields.get("declared"):
            continue
        problem, resolved = resolve_impact(graph, ov.target_id, ov.fields)
        if problem:
            measured = impact_from_fields(ov.target_id, ov.fields)
            measured.verified, measured.note = False, f"no longer resolves on this graph: {problem}"[:500]
        else:
            try:
                measured = measure_impact(db, graph, ov.target_id, resolved, open_source=open_source)
                ov.fields = resolved
            except NotMeasurable as exc:
                measured = impact_from_fields(ov.target_id, ov.fields)
                measured.note = f"not measurable on this pass: {exc}"[:500]
        ov.binding["impact"] = impact_entry(ov.fields, measured)
        try:
            save(connection_id, schema_name or "default", ov)
        except Exception as exc:  # noqa: BLE001
            logger.debug("impact measurement not saved for %s: %s", ov.target_id, exc)
        out.append({"impact": ov.target_id, "verified": measured.verified, "objects": measured.objects,
                    "rate_when_broke": measured.rate_when_broke, "rate_when_kept": measured.rate_when_kept,
                    "note": measured.note})
    return out


# ── reading it ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _label(graph: OntologyGraph, ref: str) -> str:
    process, index = promise_at(graph, ref)
    if process is None:
        return ref
    return f"the {promise_noun(process.stages[index])} promise of {process.display_name or process.id}"


def impact_words(graph: OntologyGraph, impact: Impact) -> str:
    """The impact in a reader's words, by its mechanism. An influence is said as the counts it is — descriptive, so
    it departs (`agent/claim_type.py`) — and never with a verb that relates one promise to the other: an association
    departs only on an analysis's licence, and a cause on an intervention's."""
    up, down = _label(graph, impact.upstream), _label(graph, impact.downstream)
    if impact.mechanism == "formula":
        return f"{down} follows from {up} by definition: {impact.formula}"
    if impact.verified is not True or impact.rate_when_broke is None or impact.rate_when_kept is None:
        return f"{up} is declared to bear on {down} — {impact.note or 'not measured yet'}"
    said = (f"where {up} was broken, {down} was broken {impact.rate_when_broke:.0%} of the time, against "
            f"{impact.rate_when_kept:.0%} where it was kept ({impact.upstream_broke:,} and {impact.upstream_kept:,} "
            f"{impact.lead or 'objects'})")
    if impact.mechanism == "validated":
        return f"{said} — shown by {impact.evidence}"
    return said


def impacts_into(graph: Optional[OntologyGraph], process_id: str, noun: str) -> list[Impact]:
    """The declared impacts whose downstream promise is ``<process_id>.<noun>``, measured-true first."""
    if graph is None:
        return []
    low = f"{process_id}.{noun}".lower()
    hits = [i for i in (graph.impacts or {}).values() if i.downstream.lower() == low]
    return sorted(hits, key=lambda i: (i.verified is not True, -(i.rate_when_broke or 0) + (i.rate_when_kept or 0), i.id))


def describe_impact(graph: OntologyGraph, impact: Impact) -> dict:
    return {**impact.model_dump(mode="json"), "upstream_label": _label(graph, impact.upstream),
            "downstream_label": _label(graph, impact.downstream), "reading": impact_words(graph, impact)}
