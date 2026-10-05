"""The day-one screen's numbers (the 2027 study §P and §W, phase 6; `IDEAS.md` 10 and 15):
onboarding hours as a release gate, the data shopping list, and coverage.

- **Onboarding hours** — one measured number for onboarding: hours from connect to the first
  warranted claim someone relied on. "Connect" is the connection's first ontology build (the moment
  the platform could speak about it); "relied on" is the first Decision on the connection that
  cites a claim (`record/decisions.relied_on`), at the moment of deciding. Below
  :data:`GATE_HOURS` the gate passes; with no decision yet it is "not yet", said — never a number
  guessed from activity.
- **The shopping list** — what the connected data cannot answer and what would unlock each line:
  a bound pack's expected objects no table matched (with the names it tried, and the links and
  processes that wait on it), a pack metric whose required roles the binding does not resolve
  (with the plays and goldens that wait on it), and a mission template whose metric nothing
  measures. *Confirm, do not configure*: what fits is proposed, what does not is listed.
- **Coverage** — the share of the business the platform can see (`ontology/visibility.py`): tables
  mapped of tables in scope, joins measured, and the one missing definition holding the most sends.

Nothing here is a model; a connection never profiled has no honest denominator and the dict says
so (the visibility module's own rule).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

#: Connect → first relied-on claim, in hours, below which onboarding passes its gate (the study §W: "under a day").
GATE_HOURS = 24


def _parse(ts: str) -> Optional[_dt.datetime]:
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def connected_at(connection_id: str, schema_name: Optional[str], graph=None) -> dict:
    """``{"at", "basis"}`` — when the platform could first speak about the connection: the served
    graph's first build, else the earliest pack binding, else the earliest claim in the Record."""
    g = graph
    if g is None:
        try:
            from aughor.agent.framing import served_graph
            g = served_graph(connection_id, schema_name)
        except Exception:  # noqa: BLE001
            g = None
    at = str(getattr(g, "generated_at", "") or "") if g is not None else ""
    if at:
        return {"at": at, "basis": "the connection's ontology build"}
    try:
        from aughor.packs.bindings import load_binding
        from aughor.packs.ontology_map import bound_pack_ids
        stamps = [str((load_binding(p, connection_id, schema_name or "") or {}).get("updated_at") or "")
                  for p in bound_pack_ids(connection_id, schema_name)]
        stamps = [s for s in stamps if s]
        if stamps:
            return {"at": min(stamps), "basis": "the earliest pack binding"}
    except Exception:  # noqa: BLE001
        pass
    try:
        from aughor.record import claims as C
        rows = C.list_claims(conn_id=connection_id, limit=2000)
        if rows:
            return {"at": min(c.recorded_at for c in rows if c.recorded_at), "basis": "the earliest claim in the Record"}
    except Exception:  # noqa: BLE001
        pass
    return {"at": "", "basis": "unknown: nothing built, bound or booked on this connection yet"}


def first_relied_on(connection_id: str) -> dict:
    """The first decision on the connection that relied on a claim, and the claim: ``{"decision",
    "claim", "at"}`` — empty when none has."""
    from aughor.record import claims as C
    from aughor.record import decisions as D
    best: Optional[dict] = None
    for d in D.list_decisions(conn_id=connection_id, limit=2000):
        if not d.relied_on or not d.decided_at:
            continue
        if best is None or d.decided_at < best["at"]:
            claim = C.get(d.relied_on[0])
            best = {"decision": d.id, "claim": d.relied_on[0], "at": d.decided_at,
                    "claim_text": claim.statement.text[:200] if claim else "", "decided_by": d.decided_by}
    return best or {}


def onboarding_hours(connection_id: str, schema_name: Optional[str] = None, graph=None, *,
                     gate_hours: int = GATE_HOURS) -> dict:
    """The release gate's number: hours from connect to the first relied-on claim, or "not yet"."""
    start = connected_at(connection_id, schema_name, graph)
    first = first_relied_on(connection_id)
    out: dict[str, Any] = {"connected_at": start["at"], "connected_basis": start["basis"], "first_relied_on": first,
                           "gate_hours": gate_hours, "hours": None, "passed": None}
    if not first:
        out["note"] = "not yet: no decision on this connection has relied on a claim — the clock is running, the number is not"
        return out
    if not start["at"]:
        out["note"] = "the first relied-on claim exists, but when the connection was made cannot be read; no hours to count"
        return out
    t0, t1 = _parse(start["at"]), _parse(first["at"])
    if t0 is None or t1 is None:
        out["note"] = "a timestamp could not be read"
        return out
    hours = round((t1 - t0).total_seconds() / 3600.0, 2)
    out.update({"hours": hours, "passed": hours <= gate_hours,
                "note": f"{hours:g} hours from connect to the first claim a decision relied on; the gate is {gate_hours}"})
    return out


# ── the shopping list ──────────────────────────────────────────────────────────────────────

def _pack_ids(connection_id: str, schema_name: Optional[str], pack_id: str = "") -> list[str]:
    if pack_id:
        return [pack_id]
    from aughor.packs.ontology_map import bound_pack_ids
    return bound_pack_ids(connection_id, schema_name)


def shopping_list(connection_id: str, schema_name: Optional[str], graph, *, pack_id: str = "") -> list[dict]:
    """What the connected data cannot answer for the industry's usual questions, and what would
    unlock each line. Empty when no pack is bound and none is named — said by the caller."""
    from aughor.packs.bindings import load_binding
    from aughor.packs.ontology_map import apply_core_claims, load_pack_by_id, resolve_ontology
    items: list[dict] = []
    for pid in _pack_ids(connection_id, schema_name, pack_id):
        pack = load_pack_by_id(pid)
        po = resolve_ontology(pid)
        if po is not None and graph is not None:
            from aughor.ontology.models import OntologyGraph
            work = graph if isinstance(graph, OntologyGraph) else None
            if work is not None:
                report = apply_core_claims(work.model_copy(deep=True), po, pid, None)
                missing = {c.subject for c in report.claims if c.kind == "object" and c.tier == "expected"}
                for obj in po.objects:
                    if obj.name not in missing:
                        continue
                    waits = [f"link {lk.from_object} → {lk.to_object}" for lk in po.links if obj.name in (lk.from_object, lk.to_object)]
                    waits += [f"process {p.name}" for p in po.processes if p.object == obj.name]
                    waits += [f"lifecycle of {lc.object}" for lc in po.lifecycles if lc.object == obj.name]
                    items.append({"kind": "object", "pack": pid, "what": f"a table for {obj.name}",
                                  "tried": [obj.name] + list(obj.aliases[:6]),
                                  "unlocks": waits, "why": f"the pack expects {obj.name} and no table matched it"})
        if pack is None:
            continue
        binding = load_binding(pid, connection_id, schema_name or "") or {}
        resolved = set((binding.get("bindings") or {}).keys())
        for m in pack.metrics:
            unresolved = [r for r in m.binds.required if r not in resolved]
            if not unresolved:
                continue
            plays = [p.id or p.trigger_metric for p in pack.playbooks if p.trigger_metric == m.name]
            goldens = [e.question for e in pack.evals if str((e.expect or {}).get("metric") or "") == m.name]
            items.append({"kind": "metric", "pack": pid, "what": f"to compute {m.title or m.name}, bind the role{'s' if len(unresolved) != 1 else ''} "
                                                                  f"{', '.join(unresolved)}",
                          "unlocks": [f"play {p}" for p in plays] + [f"question: {q}" for q in goldens[:3]],
                          "why": ("no binding on this connection resolves the role" if not binding else "the binding leaves the role unresolved")})
        measurable = {m.name for m in pack.metrics} - {m.name for m in pack.metrics if [r for r in m.binds.required if r not in resolved]}
        from aughor.record.mission import spec_for_metric
        for t in pack.missions:
            names = [str((t.objective or {}).get("metric") or "")] + [str((c or {}).get("metric") or "") for c in t.constraints]
            gaps = [n for n in names if n and n not in measurable and spec_for_metric(n, connection_id) is None]
            if gaps:
                items.append({"kind": "mission", "pack": pid, "what": f"to run '{t.name}', a measurable {', '.join(gaps)}",
                              "unlocks": [f"mission template {t.id}"],
                              "why": "its objective or a constraint names a metric nothing on this connection measures"})
    return items


def coverage(connection_id: str, schema_name: Optional[str], graph, *, context_graph=None, universe=None,
             held_rows=None) -> dict:
    from aughor.ontology.visibility import visibility
    schema = schema_name or (getattr(graph, "schema_name", "") or "default")
    return visibility(connection_id, schema, graph, context_graph=context_graph, universe=universe, held_rows=held_rows)


def onboarding(connection_id: str, schema_name: Optional[str] = None, *, pack_id: str = "", graph=None,
               context_graph=None, universe=None, held_rows=None) -> dict:
    """The day-one screen in one read: the gate's hours, the shopping list, coverage, the bound
    packs' priors and templates — each line saying what it could not read."""
    if graph is None:
        try:
            from aughor.agent.framing import served_graph
            graph = served_graph(connection_id, schema_name)
        except Exception:  # noqa: BLE001
            graph = None
    packs = _pack_ids(connection_id, schema_name, pack_id)
    out: dict[str, Any] = {"connection_id": connection_id, "schema_name": schema_name or "",
                           "hours": onboarding_hours(connection_id, schema_name, graph), "packs": packs}
    out["shopping_list"] = shopping_list(connection_id, schema_name, graph, pack_id=pack_id)
    if not packs:
        out["shopping_note"] = "no pack is bound to this connection and none was named; the list is empty because nothing declared what to expect"
    out["coverage"] = coverage(connection_id, schema_name, graph, context_graph=context_graph, universe=universe, held_rows=held_rows) \
        if graph is not None else {"note": "no ontology is built for this connection; nothing to measure coverage against"}
    priors, templates = [], {"missions": [], "scenarios": []}
    try:
        from aughor.packs.ontology_map import load_pack_by_id
        from aughor.packs.priors import mission_templates, monitor_priors, scenario_templates
        for pid in packs:
            pack = load_pack_by_id(pid)
            if pack is None:
                continue
            priors += monitor_priors(pack)
            templates["missions"] += mission_templates(pack)
            templates["scenarios"] += scenario_templates(pack)
    except Exception as exc:  # noqa: BLE001 — the priors line is additive
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the packs' priors could not be read for the day-one screen", counter="onboarding.priors")
    out["priors"] = priors
    out["templates"] = templates
    return out
