"""L5 — the agent that chooses AMONG declared actions toward a mission, inside its budget (the 2027
study §M's ladder: "L5 autonomous: the agent chooses among declared actions toward a mission, inside
its budget; granted when: a long L4 record; reviewed on the mission's cadence"; phase 5's open line;
the arc's close-out, C6).

Until the close-out L5 was a row in the table and a note that no code path granted it. This module
is that code path, and it is small on purpose — every term it reads is something a person wrote or
the record earned:

- **the actions it may choose among** are the connection's declared actions at L5
  (`authority.level_for`): graduated to L4 on a receipt, :data:`authority.L5_N` verified executions,
  no failed verification, an undo declared, and an L5 receipt a person booked
  (`authority.grant_l5`) inside a mission whose ceiling sets the action at L5;
- **what it chooses by** is scenario method 4 (`record/scenario.intervention`): the measured effect
  past decisions that ran each action had on the mission's objective metric, read from Outcome
  entries and nothing else, with its count — an action with too few cases is listed, not chosen;
- **the parameters it runs with** are the ones the mission's owner wrote for the action under this
  mission (``mission.extra["autonomy"]["params"][action_id]``); an action with none written is listed
  as not runnable, never guessed at;
- **its budget** is the mission's: the authority ceiling, and ONE autonomous action per review period
  — reviewed on the mission's cadence, where the report lists what it did and what became of it;
- **what it books**: a Decision (source ``autonomy``, the options being every candidate with its
  projected effect, the expectation from method 4) and, through the SAME governed pipeline as any
  execution (`actions/executor`), the action's own entry; an execution the approval gate holds — no
  standing grant covers the written parameters — is said as held, never forced.

Nothing here is a model: the choice is arithmetic over the Record, and a person can read every term.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

#: Toward the objective: the sign a projected effect must carry to count as moving the metric the
#: way the mission wants it.
_WANT = {"up": 1.0, "down": -1.0, "hold": 0.0}


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _conn_of(m) -> str:
    return m.scope.connections[0] if len(m.scope.connections) == 1 else ""


def candidates(m, actions: list, *, now: Optional[_dt.datetime] = None) -> list[dict]:
    """Every declared action on the mission's connection, with its level, its method-4 projection on
    the objective metric, whether parameters are written for it, and whether it is choosable."""
    from aughor.actions import authority
    from aughor.record.scenario import intervention
    conn = _conn_of(m)
    written = ((m.extra.get("autonomy") or {}).get("params") or {}) if isinstance(m.extra, dict) else {}
    want = _WANT.get(m.objective.direction or "", None)
    out: list[dict] = []
    for a in actions:
        lv = authority.level_for(a, conn)
        row: dict[str, Any] = {"action_id": a.id, "level": lv["level"], "why_level": lv["why"],
                               "params": dict(written.get(a.id) or {}), "reasons": []}
        if lv["level"] < 5:
            row["reasons"].append(f"at L{lv['level']}, not L5")
        if not row["params"]:
            row["reasons"].append("no parameters written for it in the mission")
        p = intervention(metric=m.objective.metric, connection_id=conn, action_id=a.id, unit=m.objective.unit or "")
        row["projection"] = {"method": p.method, "value": p.value, "low": p.low, "high": p.high, "coverage": p.coverage,
                             "n": int((p.backtest or {}).get("n") or 0), "held": (p.backtest or {}).get("held"), "note": p.note,
                             "must_say": list(p.must_say)}
        if p.value is None:
            row["reasons"].append(p.note or "no measured effect on the objective")
            row["toward"] = None
        else:
            row["toward"] = (-abs(p.value) if want == 0.0 else p.value * want) if want is not None else p.value
            if want is not None and want != 0.0 and row["toward"] <= 0:
                row["reasons"].append("its measured effect moves the objective the wrong way, or not at all")
        row["choosable"] = not row["reasons"]
        out.append(row)
    return out


def choose(m, actions: list, *, now: Optional[_dt.datetime] = None) -> dict:
    """The one action to run, by the largest measured effect toward the objective among the
    choosable candidates (ties: the one whose past cases went the wanted way most often); or none,
    with why each candidate was not chosen."""
    rows = candidates(m, actions, now=now)
    choosable = [r for r in rows if r["choosable"]]
    if not choosable:
        return {"chosen": "", "candidates": rows,
                "why": ("no declared action is choosable: " + "; ".join(f"{r['action_id']}: {', '.join(r['reasons'])}" for r in rows))
                if rows else "no declared action on this connection"}
    best = max(choosable, key=lambda r: (r["toward"], (r["projection"].get("held") or 0) / max(r["projection"]["n"], 1)))
    return {"chosen": best["action_id"], "candidates": rows,
            "why": (f"{best['action_id']}: measured effect {best['projection']['value']} toward the objective over "
                    f"{best['projection']['n']} past decisions, the largest among {len(choosable)} choosable action"
                    f"{'s' if len(choosable) != 1 else ''}")}


def _period_days(m) -> int:
    from aughor.record.mission import CADENCE_DAYS
    return CADENCE_DAYS.get(m.review.cadence, 30)


def act(m, actions: list, *, now: Optional[_dt.datetime] = None, dispatch=None) -> dict:
    """Choose and RUN one action toward the mission, inside its budget: one autonomous action per
    review period, through the governed pipeline, booked as a Decision with its expectation and the
    action's own entry. Returns what happened, never raises for a refusal."""
    from aughor.record import decisions as D
    from aughor.record import mission as M
    now = now or _now()
    conn = _conn_of(m)
    if m.state != "active" or not m.owner:
        return {"acted": False, "why": "a mission acts only while active and owned", "mission": m.id}
    if not conn:
        return {"acted": False, "why": "the mission names no single connection to act on", "mission": m.id}
    auto = dict(m.extra.get("autonomy") or {})
    last = str(auto.get("last_acted_on") or "")
    if last and (now.date() - _dt.date.fromisoformat(last)).days < _period_days(m):
        return {"acted": False, "mission": m.id,
                "why": f"already acted on {last}; one autonomous action per {m.review.cadence} period, reviewed on the mission's cadence"}
    choice = choose(m, actions, now=now)
    if not choice["chosen"]:
        return {"acted": False, "mission": m.id, "why": choice["why"], "candidates": choice["candidates"]}
    action = next(a for a in actions if a.id == choice["chosen"])
    row = next(r for r in choice["candidates"] if r["action_id"] == action.id)
    proj = row["projection"]
    settles = m.review.next_report_on or (now + _dt.timedelta(days=_period_days(m))).date().isoformat()
    options = [D.Option(id=r["action_id"], actor="agent:autonomy", reversibility=getattr(next(a for a in actions if a.id == r["action_id"]), "reversibility", "") or "",
                        cost="no model call; the action's own cost",
                        description=(f"measured effect {r['projection']['value']} on {m.objective.metric} over {r['projection']['n']} past decisions"
                                     if r["projection"]["value"] is not None else "; ".join(r["reasons"])))
               for r in choice["candidates"]]
    decision = D.Decision(question=f"Which declared action moves {m.objective.metric} {m.objective.direction or 'as the mission wants'} for '{m.name}'?",
                          owner=m.owner, options=options, chosen=action.id, decided_by="agent:autonomy", objective=m.id,
                          actions=[action.id], connection_id=conn,
                          source=D.Source(kind="autonomy", ref=f"{m.id}:{now.date().isoformat()}", detail=choice["why"]),
                          extra={"mission": m.id, "level": 5, "by": "L5: the agent chose among the declared actions at L5",
                                 "projection": {k: proj[k] for k in ("method", "value", "low", "high", "coverage", "n")}})
    expectation = D.Expectation(metric=m.objective.metric, direction=m.objective.direction or "", low=proj["low"], mid=proj["value"],
                                high=proj["high"], unit=m.objective.unit or "", coverage=float(proj["coverage"] or 0.8),
                                settles_on=settles)
    did = D.book_decision(decision, expectation=expectation, author="agent:autonomy")
    from aughor.actions.executor import execute_kinetic_action
    result = execute_kinetic_action(action, dict(row["params"]), actor="agent:autonomy", scope=conn, dispatch=dispatch, approved=False)
    acted = result.status == "executed"
    entry = {"at": now.isoformat(), "action": action.id, "decision": did, "entry": result.action_entry, "status": result.status,
             "message": result.message, "projection": decision.extra["projection"],
             "verification": dict(result.verification or {})}
    if acted:
        auto["last_acted_on"] = now.date().isoformat()
    auto.setdefault("acted", []).append(entry)
    auto["acted"] = auto["acted"][-50:]
    m.extra["autonomy"] = auto
    M._book(m, lineage=[("acted", did, action.id)])
    why = ("" if acted else
           ("held at the approval gate: no standing policy grant covers the written parameters — a person widens one "
            "(POST /authority/{id}/widen) or accepts the proposal" if result.status == "approval_required" else result.message))
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit("action.autonomous", {"mission": m.id, "action_id": action.id, "decision": did, "entry": result.action_entry,
                                                    "status": result.status, "acted": acted}, conn_id=conn)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the autonomous action ran; only its spine event was lost", counter="autonomy.emit")
    return {"acted": acted, "mission": m.id, "action_id": action.id, "decision": did, "entry": result.action_entry,
            "status": result.status, "why": why or choice["why"], "candidates": choice["candidates"], "params": row["params"]}


def act_for_mission(m, *, now: Optional[_dt.datetime] = None, dispatch=None) -> dict:
    """The cadence's call: a mission with no L5 ceiling has nothing to choose; one with it chooses
    among the connection's declared actions. Loads the actions from the connection's ontology."""
    if not any(int(v) >= 5 for v in (m.budget.authority_ceiling or {}).values()):
        return {"acted": False, "mission": m.id, "why": "the mission sets no action's ceiling at L5"}
    conn = _conn_of(m)
    try:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(conn, None) if conn else None
        actions = list(graph.declared_actions()) if graph is not None else []
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "the declared actions could not be read for the mission", counter="autonomy.actions", conn_id=conn or None)
        actions = []
    if not actions:
        return {"acted": False, "mission": m.id, "why": "no declared action on the mission's connection"}
    return act(m, actions, now=now, dispatch=dispatch)
