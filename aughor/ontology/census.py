"""Arc OC-0 — the ontology census: how much of the business is declared, measured and leaned on (ROADMAP §3.56).

The study that opened Arc OC counted these once, by hand, over HTTP (`docs/ONTOLOGY_FIRST_STUDY_2026-10-09.md` §5):
35 of 35 entities were tables, one action was declared, no Record claim was about an object, a segment or an entity,
and none named the version of the definition it was measured under. Its finding orders the arc — every wave must
give a person a reason to declare something — so the count is the arc's baseline, and a baseline counted by hand
once cannot say whether a wave moved it. This module counts the same things the same way every time:

* **declared** — per scope, the entities and how many are anything but one table each, their parts and detail
  bindings, the links and how many carry a name, the processes, promises, rules, segments and declared actions;
* **measured** — of those, how many the data verified: backings, display properties, links counted, bindings,
  segments, computed properties, and properties with a description;
* **leaned on** — the automations that read the ontology (a promise trigger, a declared-action step), and the
  Record's claims by what they are about and whether they name a metric, a segment or a definition version;
* **the catalogue's replay** — Arc OC-2's falsifier over the kept declaration history (`compatibility.replay`), so
  each reading says again whether a change that moved what consumers read was ever classed safe.

Read-only and cache-only: a scope whose ontology was never built is listed as not built, never built here (a read
never builds). `take_census` is the door's live reading; `record_if_due` journals one reading a day as
`ontology.census` behind the `ontology.census` flag, so a later wave reads its before and after from the journal
instead of from a document.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aughor.ontology.models import OntologyGraph

logger = logging.getLogger(__name__)

#: The journal kind a daily reading is written under (`aughor/kernel/events.py`).
EVENT_KIND = "ontology.census"

def _share(part: int, whole: int) -> dict:
    return {"of": whole, "n": part}


def scope_census(graph: OntologyGraph) -> dict[str, Any]:
    """What one served graph declares and what the data verified of it. Pure: the graph as `GET /ontology` serves
    it — the build with every declaration applied."""
    entities = list(graph.entities.values())
    links = list(graph.relationships.values())
    processes = list(graph.processes.values())
    bindings = [b for e in entities for b in e.bindings]
    segments = [s for e in entities for s in e.segments.values()]
    computed = [c for e in entities for c in e.computed_properties]
    properties = [p for e in entities for p in e.properties.values()]
    return {
        "declared": {
            "entities": len(entities),
            "one_table_each": sum(1 for e in entities if e.origin == "table"),
            "query_backed": sum(1 for e in entities if e.backing is not None and e.backing.kind == "query"),
            "parts": sum(1 for e in entities if e.absorbed_into),
            "with_detail_binding": sum(1 for e in entities if any(b.kind == "detail" for b in e.bindings)),
            "links": len(links),
            # A link's name is its `name` (ON-7b) — the enricher's `verb` is a label every link gets, not a name.
            "links_named": sum(1 for r in links if r.name),
            "links_named_by_a_person": sum(1 for r in links if r.name and r.name_origin == "human"),
            "processes": len(processes),
            "promises": sum(1 for p in processes for s in p.stages if s.promise is not None),
            "rules": len(graph.rules),
            "segments": len(segments),
            "declared_actions": len(graph.declared_actions()),
        },
        "measured": {
            "backing_verified": _share(sum(1 for e in entities if e.backing is not None and e.backing.verified),
                                       len(entities)),
            "display_property_verified": _share(sum(1 for e in entities if e.display_property is not None
                                                    and e.display_property.verified), len(entities)),
            "links_counted": _share(sum(1 for r in links if r.measured_cardinality is not None), len(links)),
            "bindings_verified": _share(sum(1 for b in bindings if b.verified), len(bindings)),
            "segments_verified": _share(sum(1 for s in segments if s.verified), len(segments)),
            "computed_verified": _share(sum(1 for c in computed if c.verified), len(computed)),
            "properties_described": _share(sum(1 for p in properties if p.description), len(properties)),
        },
    }


def _add(total: dict, part: dict) -> None:
    for section, counts in part.items():
        into = total.setdefault(section, {})
        for name, value in counts.items():
            if isinstance(value, dict):
                cell = into.setdefault(name, {"of": 0, "n": 0})
                cell["of"] += value["of"]
                cell["n"] += value["n"]
            else:
                into[name] = into.get(name, 0) + value


def consumption() -> dict[str, Any]:
    """What leans on the ontology: automations that read it, and the Record's claims by what they are attached to.
    A store that cannot be read is said — `None` and the reason — never counted as zero."""
    out: dict[str, Any] = {}
    try:
        from aughor.automations.store import list_automations
        autos = list_automations()
        promise = [a for a in autos if any(c.kind == "promise_breached" for c in a.conditions)]
        # A step that runs a declared action names it by `action_id` — the one key that step kind requires.
        action = [a for a in autos if any(e.config.get("action_id") for e in a.effects)]
        out["automations"] = {"total": len(autos),
                              "read_the_ontology": len({a.id for a in promise + action}),
                              "on_a_promise": len(promise), "run_a_declared_action": len(action)}
    except Exception as exc:  # noqa: BLE001 — a census says what it could not read
        out["automations"] = None
        out.setdefault("unread", {})["automations"] = str(exc)[:200]
    try:
        from aughor.record.claims import list_claims
        claims = list_claims(limit=100_000)
        about: dict[str, int] = {}
        for c in claims:
            about[c.about.kind] = about.get(c.about.kind, 0) + 1
        out["record"] = {
            "claims": len(claims),
            "about": about,
            "about_the_ontology": sum(about.get(k, 0) for k in ("object", "segment", "type")),
            "citing_a_metric": sum(1 for c in claims if c.statement.metric),
            "citing_a_segment": sum(1 for c in claims if c.statement.object_set),
            "citing_a_definition_version": sum(1 for c in claims if c.definition_version),
        }
    except Exception as exc:  # noqa: BLE001
        out["record"] = None
        out.setdefault("unread", {})["record"] = str(exc)[:200]
    for name, lister in (("decisions", "aughor.record.decisions:list_decisions"),
                         ("missions", "aughor.record.mission:list_missions")):
        module, fn = lister.split(":")
        try:
            out[name] = len(getattr(__import__(module, fromlist=[fn]), fn)(limit=100_000))
        except Exception as exc:  # noqa: BLE001
            out[name] = None
            out.setdefault("unread", {})[name] = str(exc)[:200]
    return out


def take_census() -> dict[str, Any]:
    """The live reading: every connection's built scopes, their totals, and what leans on them."""
    from aughor.db.registry import list_connections
    from aughor.ontology.store import list_schemas, load_latest_ontology

    scopes: list[dict] = []
    totals: dict[str, Any] = {}
    not_built: list[str] = []
    for conn in list_connections():
        conn_id = str(conn.get("id") or "")
        schemas = list_schemas(conn_id)
        if not schemas:
            not_built.append(conn_id)
            continue
        for schema in schemas:
            graph = load_latest_ontology(conn_id, schema)
            if graph is None:
                continue
            reading = scope_census(graph)
            _add(totals, reading)
            scopes.append({"connection_id": conn_id, "name": str(conn.get("name") or ""),
                           "schema": schema, **reading})
    from aughor.ontology.keys import keyed_counts
    return {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scopes": scopes, "totals": totals, "not_built": not_built, "leaned_on": consumption(),
            "keyed": keyed_counts(), "replay": _replay()}


def _replay() -> dict[str, Any]:
    """Arc OC-2's falsifier over the kept declaration history (`compatibility.replay`), read with every reading so it
    re-runs itself as history grows; a replay that cannot be read is said, never an empty pass."""
    from aughor.ontology.compatibility import replay
    try:
        return replay()
    except Exception as exc:  # noqa: BLE001
        return {"unread_reason": str(exc)[:200]}


def history(limit: int = 90) -> list[dict]:
    """The journaled daily readings, newest first: each one's date, totals and what leaned on the ontology."""
    from aughor.kernel.ledger import Ledger
    out = []
    for ev in Ledger.default().events(kind=EVENT_KIND, limit=limit):
        payload = ev.get("payload") or {}
        out.append({"at": ev.get("at"), "totals": payload.get("totals", {}),
                    "leaned_on": payload.get("leaned_on", {}), "keyed": payload.get("keyed", {}),
                    "replay": payload.get("replay", {})})
    return out


def _stamp(value: Any) -> Optional[datetime]:
    """A journal stamp as an aware datetime; None when it cannot be read — and a stamp that cannot be read cannot
    prove the last reading is fresh, so the census is taken."""
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def record_if_due(now: Optional[datetime] = None) -> Optional[int]:
    """Journal one reading if none was journaled in the last day. Behind `ontology.census`, off by default: off,
    nothing is read or written. Returns the journal seq, or None when off, not due or failed."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("ontology.census"):
        return None
    from aughor.kernel.ledger import Ledger
    now = now or datetime.now(timezone.utc)
    ledger = Ledger.default()
    last = ledger.events(kind=EVENT_KIND, limit=1)
    at = _stamp(last[0].get("at")) if last else None
    if at is not None and now - at < timedelta(hours=23):
        return None
    try:
        reading = take_census()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ontology census not taken: %s", exc)
        return None
    return ledger.emit(EVENT_KIND, {"totals": reading["totals"], "scopes": reading["scopes"],
                                    "not_built": reading["not_built"], "leaned_on": reading["leaned_on"],
                                    "keyed": reading.get("keyed", {}), "replay": reading.get("replay", {})})
