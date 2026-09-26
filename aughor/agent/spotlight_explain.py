"""SP-15 (§3.11) — `explain`: the platform explains the object on screen.

The question that named the wave: a scheduled briefing's Slack post read *held ·
re-measured at departure: 1,648.08 … not in analysis ecb56660*, and the reader asked what
re-measure was and how to unblock it. The answer existed in the gate module's docstring
and nowhere a reader could reach; asked in the palette, the question ran Spotlight out of
its eight steps twice, because no tool on the roster could read a departure, an
automation's effects or a law (the baseline, measured 2026-09-25 from the session log).

This is that tool: ONE declared read over the object a screen shows, by kind and id,
returning its live state as a tool result the answer may cite — the departure's guards
with each law's sentence and remedy, the automation's effects and last run, the metric's
lifecycle and tests. Claims bound to tool results, the arc's standing law; reads free
within scope. The remedy words are the SAME the departures screen renders
(`govern/departure_remedies.py`) — one source, two readers. Every result ends in the
offered act, and an act this deployment cannot perform by sentence says which screen
holds it instead of posing as a door (SP-4's law).
"""
from __future__ import annotations

import logging
from typing import Optional

from aughor.agent.spotlight_text import clip
from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

#: The kinds `explain` covers, in the order §6 item 33 chose them — the three a held send
#: points at. Agent and analysis follow by the same three moves.
KINDS: tuple[str, ...] = ("departure", "automation", "metric", "agent", "analysis")

_MAX_RECENT = 5
_PREVIEW = 400
_SQL_PREVIEW = 300


def explain_object(connection_id: str, args: dict) -> dict:
    """The object's live state, or a found=False answer that says what was looked for."""
    kind = str(args.get("kind") or "").strip().lower()
    ident = str(args.get("id") or "").strip()
    if kind not in KINDS:
        return {"found": False, "kind": kind, "id": ident, "kinds": list(KINDS),
                "summary": (f"Nothing explained: {kind!r} is not a kind this tool knows — "
                            f"it explains {', '.join(KINDS)}.")}
    if not ident:
        return {"found": False, "kind": kind, "id": "",
                "summary": f"Nothing explained: name the {kind}'s id."}
    try:
        return _EXPLAINERS[kind](connection_id, ident)
    except Exception as exc:  # noqa: BLE001 — a read that failed is reported, never posed as absent
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"explain: the {kind} store could not be read",
                 counter="spotlight_explain.read_failed")
        return {"found": False, "kind": kind, "id": ident, "unavailable": True,
                "summary": (f"The {kind} store could not be read just now "
                            f"({type(exc).__name__}); this is not the same as the {kind} "
                            "not existing.")}


# ── departure ─────────────────────────────────────────────────────────────────────────

def _explain_departure(connection_id: str, departure_id: str) -> dict:
    from aughor.govern.departure import HELD, HELD_OWNER, HELD_PROBATION
    from aughor.govern.departure_remedies import remedy_for_row
    from aughor.govern.departure_store import decode_row, get_departure

    row = get_departure(departure_id)
    if row is None:
        return {"found": False, "kind": "departure", "id": departure_id,
                "summary": f"No departure {departure_id!r} is in the ledger."}
    d = decode_row(row)
    remedy = remedy_for_row(d)
    guards = d.get("guards") or {}
    checks = d.get("checks") or {}
    state = str(d.get("state") or "")
    held_by = [g["guard"] for g in (remedy or {}).get("guards", [])]
    automation = {"id": d.get("automation_id") or "", "name": d.get("automation_name") or ""}
    out = {
        "found": True, "kind": "departure", "id": d.get("id"),
        "state": state, "when": d.get("ts") or "", "message_kind": d.get("kind") or "",
        "target": d.get("target") or "", "connection_id": d.get("conn_id") or "",
        "automation": automation,
        "analysis_id": d.get("investigation_id") or "",
        "message_preview": clip(str(d.get("text_preview") or ""), _PREVIEW),
        "reasons": list(d.get("reasons") or []),
        "held_by": held_by,
        # Every guard in the gate's order with its outcome and the sentence it recorded —
        # a passed guard is evidence too ("definition: cites metric revenue v1").
        "checks": [{"guard": g, "outcome": str(guards.get(g) or "recorded"),
                    "reason": str(checks.get(g) or "")}
                   for g in _guard_order() if g in guards or g in checks],
        "remedy": remedy,
        "verdict": d.get("verdict") or "", "answer": d.get("answer") or "",
        "question": d.get("question") or {},
        "as_of": d.get("as_of") or "",
    }
    out["offer"] = _departure_offer(state, automation, remedy)
    out["summary"] = _departure_summary(out, HELD, HELD_OWNER, HELD_PROBATION)
    return out


def _guard_order() -> tuple[str, ...]:
    from aughor.govern.departure import GUARDS
    return GUARDS


def _departure_offer(state: str, automation: dict, remedy) -> dict:
    """The act the answer ends in. A hold is a verdict — nothing re-sends — so the offer
    is the change that makes the NEXT run depart: the automation's schedule, name or
    enabled state by sentence (`edit_automation`), its question on the Automations
    canvas, or the mark/answer the departures screen owes."""
    if state == "departed":
        return {"tool": "", "sentence": "Nothing is owed: this message departed."}
    if state == "held_owner":
        return {"tool": "", "sentence": ("The owner is asked to choose between the readings "
                                         "on the departures screen; the next run binds the "
                                         "answer and is never asked twice.")}
    if state == "held_probation":
        return {"tool": "", "sentence": ("The declarer marks it accept, correct or reject on "
                                         "the departures screen; at the measured precision "
                                         "the automation graduates and its sends reach the "
                                         "channel.")}
    if automation.get("id"):
        name = automation.get("name") or automation["id"]
        return {"tool": "edit_automation", "automation": automation["id"],
                "sentence": (f"Fix the cause, then let the next run of \"{clip(name, 60)}\" "
                             "send it: its schedule, name or enabled state can be staged by "
                             "sentence with edit_automation; the question it asks is changed "
                             "on the Automations canvas.")}
    return {"tool": "", "sentence": "Fix the cause on the screen its remedy names; the next send departs fresh."}


def _departure_summary(out: dict, HELD: str, HELD_OWNER: str, HELD_PROBATION: str) -> str:
    who = out["automation"].get("name") or out["message_kind"] or "a send"
    if out["state"] == "departed":
        return f"Departure {out['id']}: \"{who}\" departed to {out['target'] or 'its target'} at {out['when']}."
    held = ", ".join(g["label"] for g in (out["remedy"] or {}).get("guards", [])) or "the gate"
    first = out["reasons"][0] if out["reasons"] else ""
    lead = f"Departure {out['id']}: \"{who}\" was held by {held}"
    if out["state"] == HELD_OWNER:
        lead += " — its owner is asked to choose a reading"
    elif out["state"] == HELD_PROBATION:
        lead += " — it reached only its declarer, who marks it"
    return f"{lead}. {first}".strip()


# ── automation ────────────────────────────────────────────────────────────────────────

def _explain_automation(connection_id: str, ref: str) -> dict:
    from aughor.agent.spotlight_act import resolve_automation
    from aughor.govern.departure_store import list_departures

    a, refusal = resolve_automation(connection_id, ref)
    if a is None:
        return {"found": False, "kind": "automation", "id": ref, "summary": f"Not explained: {refusal}"}
    conditions = [{"kind": c.kind, **_condition_detail(c)} for c in (a.conditions or [])]
    effects = [{"kind": e.kind, **_effect_detail(e)} for e in (a.effects or [])]
    recent = []
    for d in list_departures(automation_id=a.id, limit=_MAX_RECENT):
        recent.append({"id": d.get("id"), "state": d.get("state"), "when": d.get("ts"),
                       "target": d.get("target") or "",
                       "reason": clip(str(_first_reason(d)), 200)})
    paused = bool(a.paused_until)
    out = {
        "found": True, "kind": "automation", "id": a.id, "name": a.name,
        "description": clip(a.description or "", _PREVIEW),
        "connection_id": a.conn_id or "", "agent_id": a.agent_id or "",
        "enabled": bool(a.enabled), "paused_until": a.paused_until or "",
        "probation": bool(a.probation), "declared_by": a.declared_by or "",
        "last_run_at": getattr(a, "last_run_at", None) or "",
        "last_status": getattr(a, "last_status", None) or "",
        "conditions": conditions, "effects": effects,
        "recent_departures": recent,
    }
    questions = [e.get("question") for e in effects if e.get("question")]
    state = ("disabled" if not a.enabled else "paused" if paused else
             "on probation" if a.probation else "live")
    out["offer"] = {
        "tool": "edit_automation", "automation": a.id,
        "sentence": ("Its schedule, name, description or enabled state can be staged by "
                     "sentence with edit_automation; the question it asks"
                     + (f" (\"{clip(questions[0], 80)}\")" if questions else "")
                     + " is changed on the Automations canvas."),
    }
    out["summary"] = (
        f"Automation \"{clip(a.name, 60)}\" is {state}; "
        f"{len(conditions)} trigger{'s' if len(conditions) != 1 else ''} "
        f"({', '.join(c['kind'] for c in conditions) or 'none'}), "
        f"{len(effects)} step{'s' if len(effects) != 1 else ''} "
        f"({', '.join(e['kind'] for e in effects) or 'none'}); last run "
        f"{out['last_status'] or 'never'}"
        + (f" at {out['last_run_at']}" if out["last_run_at"] else "") + "; "
        f"{len(recent)} recent departure{'s' if len(recent) != 1 else ''}"
        + (f" ({', '.join(r['state'] for r in recent)})" if recent else "") + "."
    )
    return out


def _condition_detail(c) -> dict:
    cfg = dict(getattr(c, "config", None) or {})
    keep = {k: cfg[k] for k in ("cron", "metric", "table", "operator", "threshold", "entity")
            if k in cfg and cfg[k] not in (None, "")}
    return {"config": keep} if keep else {}


def _effect_detail(e) -> dict:
    cfg = dict(getattr(e, "config", None) or {})
    out: dict = {}
    if cfg.get("question"):
        out["question"] = clip(str(cfg["question"]), _PREVIEW)
    for k in ("target", "channel", "monitor_id", "agent_id", "automation_id", "kind_label"):
        if cfg.get(k):
            out[k] = str(cfg[k])
    if getattr(e, "alias", ""):
        out["alias"] = e.alias
    return out


def _first_reason(d: dict) -> str:
    raw = d.get("reasons")
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    return str(raw[0]) if isinstance(raw, list) and raw else ""


# ── metric ────────────────────────────────────────────────────────────────────────────

def _explain_metric(connection_id: str, name: str) -> dict:
    from aughor.govern.departure import metric_is_approved
    from aughor.semantic.metrics import get_metric

    m = get_metric(name, connection_id=connection_id) or get_metric(name)
    if m is None:
        return {"found": False, "kind": "metric", "id": name,
                "summary": f"No metric named {name!r} is defined for this connection."}
    approved = metric_is_approved(m)
    out = {
        "found": True, "kind": "metric", "id": m.name, "label": m.label,
        "status": m.status or ("approved" if approved else "draft"), "approved": approved,
        "version": m.version, "connection": m.connection,
        "sql": clip(m.sql or "", _SQL_PREVIEW), "unit": m.unit or "",
        "tables": list(m.tables or []), "dimensions": list(m.dimensions or []),
        "filters": list(m.filters or []), "caveats": m.caveats or "",
        "owner": m.owner or "", "approved_by": m.approved_by or "", "approved_at": m.approved_at or "",
        "proposed_by": m.proposed_by or "", "proposed_at": m.proposed_at or "",
        "freshness_sla": m.freshness_sla or "",
        "quality_tests": [clip(t, _SQL_PREVIEW) for t in (m.quality_tests or [])],
        "time_column": getattr(m, "time_column", None) or "",
        "time_kind": getattr(m, "time_kind", None) or "",
        "wrong_usage_examples": list(m.wrong_usage_examples or []),
    }
    out["offer"] = {
        "tool": "",
        "sentence": ("A metric is approved, edited and tested on the Semantic Layer › Metrics "
                     "screen; approval is a person's act and no chat tool performs it."),
    }
    out["summary"] = (
        f"Metric \"{m.label or m.name}\" ({m.name}) is {out['status']}"
        + (f", v{m.version}" if m.version else "")
        + (f", approved by {m.approved_by}" if m.approved_by else "")
        + f"; {len(out['quality_tests'])} quality test{'s' if len(out['quality_tests']) != 1 else ''}"
        + (f"; freshness SLA {m.freshness_sla}" if m.freshness_sla else "")
        + (" — a draft metric cannot back a number that leaves the platform (law 2)."
           if not approved else ".")
    )
    return out


# ── agent ─────────────────────────────────────────────────────────────────────────────

def _explain_agent(connection_id: str, ref: str) -> dict:
    from aughor.agent.spotlight_guide import eval_sentence
    from aughor.custom_agents.store import get_agent, list_agents

    a = get_agent(ref)
    if a is None:
        matches = [x for x in list_agents() if x.name == ref]
        if len(matches) == 1:
            a = matches[0]
        elif len(matches) > 1:
            return {"found": False, "kind": "agent", "id": ref,
                    "summary": f"{len(matches)} agents are named {clip(ref, 60)!r} — use an id: "
                               + ", ".join(x.id for x in matches)}
    if a is None:
        known = ", ".join(sorted(clip(x.name, 40) for x in list_agents())[:12]) or "(none)"
        return {"found": False, "kind": "agent", "id": ref,
                "summary": f"No agent named {clip(ref, 60)!r}; the agents here are: {known}."}
    runs = _agent_runs(a.id)
    out = {
        "found": True, "kind": "agent", "id": a.id, "name": a.name,
        "purpose": clip(a.purpose or "", _PREVIEW), "instructions": clip(a.instructions or "", _PREVIEW),
        "connection_id": a.connection_id or "", "schema_scope": a.schema_scope or "",
        "documents": len(a.doc_ids or []), "packs": list(a.pack_ids or []),
        "tool_grants": list(a.tool_grants or []), "enabled": bool(a.enabled),
        "owner": a.owner or "", "workspace_id": a.workspace_id or "",
        "evaluation": eval_sentence(a), "eval_basis": a.eval_basis,
        "recent_runs": runs,
        "created_at": a.created_at or "", "updated_at": a.updated_at or "",
    }
    out["offer"] = {
        "tool": "propose_agent_grant", "agent": a.id,
        "sentence": (f"A declared action can be added to \"{clip(a.name, 60)}\"'s grants by sentence with "
                     "propose_agent_grant (staged for approval); its instructions, documents and golden "
                     "questions are edited on the Agents screen, where the Prove step re-runs its suite."),
    }
    out["summary"] = (
        f"Agent \"{clip(a.name, 60)}\" is {'enabled' if a.enabled else 'disabled'}"
        + (f", bound to connection {a.connection_id}" if a.connection_id else ", unbound (answers on the ask's connection)")
        + f"; {out['documents']} document{'s' if out['documents'] != 1 else ''}, "
        f"{len(out['tool_grants'])} grant{'s' if len(out['tool_grants']) != 1 else ''}; {out['evaluation']}; "
        f"{len(runs)} recent run{'s' if len(runs) != 1 else ''}."
    )
    return out


def _agent_runs(agent_id: str) -> list[dict]:
    try:
        from aughor.db.history import list_investigations_for_agent
        rows = list_investigations_for_agent(agent_id, limit=_MAX_RECENT)
    except Exception as exc:  # noqa: BLE001 — a store down says so, never an empty list
        from aughor.kernel.errors import tolerate
        tolerate(exc, "explain: the agent's runs could not be read", counter="spotlight_explain.agent_runs")
        return [{"unavailable": "the run history could not be read"}]
    out = []
    for r in rows[:_MAX_RECENT]:
        out.append({"id": r.get("id"), "kind": r.get("kind"), "status": r.get("status"),
                    "question": clip(str(r.get("question") or ""), 120),
                    "started_at": r.get("started_at") or ""})
    return out


# ── analysis ──────────────────────────────────────────────────────────────────────────

def _explain_analysis(connection_id: str, inv_id: str) -> dict:
    from aughor.db.history import get_investigation
    from aughor.govern.departure_store import list_departures

    row = get_investigation(inv_id)
    if row is None:
        return {"found": False, "kind": "analysis", "id": inv_id,
                "summary": f"No analysis {inv_id!r} is in the run history."}
    report = row.get("report") if isinstance(row.get("report"), dict) else {}
    kind = str(row.get("kind") or "investigation")
    envelope = report.get("envelope") if isinstance(report.get("envelope"), dict) else None
    rechecks = [c for c in (report.get("rechecks") or []) if isinstance(c, dict)]
    departures = [
        {"id": d.get("id"), "state": d.get("state"), "when": d.get("ts"),
         "target": d.get("target") or "", "automation": d.get("automation_name") or ""}
        for d in list_departures(limit=500) if str(d.get("investigation_id") or "") == str(row.get("id"))
    ][:_MAX_RECENT]
    out = {
        "found": True, "kind": "analysis", "id": row.get("id"),
        "analysis_kind": "quick answer" if kind == "chat" else "deep analysis",
        "status": row.get("status") or "", "question": clip(str(row.get("question") or ""), _PREVIEW),
        "connection_id": row.get("connection_id") or "", "agent_id": row.get("agent_id") or "",
        "started_at": row.get("started_at") or "", "completed_at": row.get("completed_at") or "",
        "headline": clip(str(row.get("headline") or report.get("headline") or ""), _PREVIEW),
        "sql": clip(str(report.get("sql") or ""), _SQL_PREVIEW),
        "queries": int(row.get("query_count") or 0),
        "hypotheses": int(row.get("hypothesis_count") or 0),
        "confidence": report.get("confidence"),
        "executive_summary": clip(str(report.get("executive_summary") or ""), _PREVIEW),
        "recommendations": len(report.get("recommendations") or []) if isinstance(report.get("recommendations"), list) else 0,
        "data_gaps": len(report.get("data_gaps") or []) if isinstance(report.get("data_gaps"), list) else 0,
        "guards_clean": _guards_clean(envelope),
        "rechecks": [{"at": c.get("at") or c.get("checked_at"), "status": c.get("status")} for c in rechecks][-3:],
        "verdict": _latest_verdict(str(row.get("id") or "")),
        "departures": departures,
        "trace_id": row.get("trace_id") or (row.get("id") if kind != "chat" else ""),
        "error": row.get("error") or "",
    }
    out["offer"] = {
        "tool": "",
        "sentence": ("Ask a follow-up about it in this conversation, or open it under Agent runs; a "
                     "re-run on a schedule is the automation's, on the Automations canvas."
                     + (f" Its full record is at /traces/{out['trace_id']}/trajectory." if out["trace_id"] else "")),
    }
    held = [d for d in departures if d["state"] != "departed"]
    out["summary"] = (
        f"{out['analysis_kind'].capitalize()} {out['id']} ({out['status']}): \"{clip(out['question'], 80)}\""
        + (f" — {out['queries']} quer{'ies' if out['queries'] != 1 else 'y'}" if out["queries"] else "")
        + (f", confidence {out['confidence']}" if out["confidence"] not in (None, "") else "")
        + (f"; guards {'clean' if out['guards_clean'] else 'not vouched for'}" if envelope is not None else "; no envelope")
        + (f"; {len(departures)} departure{'s' if len(departures) != 1 else ''} cite{'' if len(departures) != 1 else 's'} it"
           + (f", {len(held)} held" if held else "") if departures else "")
        + "."
    )
    return out


def _guards_clean(envelope) -> Optional[bool]:
    if envelope is None:
        return None
    from aughor.answer.envelope import guards_clean
    return bool(guards_clean(envelope))


def _latest_verdict(inv_id: str) -> Optional[dict]:
    if not inv_id:
        return None
    try:
        from aughor.feedback.verdicts import latest_verdict
        v = latest_verdict(inv_id)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "explain: the verdict store could not be read", counter="spotlight_explain.verdict")
        return {"unavailable": "verdicts could not be read"}
    return {k: v.get(k) for k in ("verdict", "note", "created_at") if k in v} if v else None


_EXPLAINERS = {
    "departure": _explain_departure,
    "automation": _explain_automation,
    "metric": _explain_metric,
    "agent": _explain_agent,
    "analysis": _explain_analysis,
}


# ── the roster ────────────────────────────────────────────────────────────────────────

_EXPLAIN_PARAMS = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS),
                 "description": "What the id names: departure, automation, metric, agent or analysis."},
        "id": {"type": "string",
               "description": "The object's id as the screen shows it — a departure id, an "
                              "automation or agent id or exact name, a metric's name, or an "
                              "analysis (run) id."},
    },
    "required": ["kind", "id"],
}


def spotlight_explain_tools(connection_id: str, *, session_id: str = "") -> list[ToolSpec]:
    """SP-15's one declared read — the Guide limb's second tool."""
    return [
        ToolSpec(
            name="explain",
            description=(
                "The live state of ONE object on screen, by kind and id — a departure "
                "(why the gate held or passed it: every guard's outcome, the law behind "
                "each, what a hold means and what to change), an automation (its "
                "triggers, steps, last run and recent departures), a metric (its "
                "lifecycle, definition and tests), an agent (its scope, grants, evaluation "
                "and recent runs) or an analysis (a run: its question, status, queries, "
                "confidence, re-checks, verdict and the departures that cite it). Call it "
                "FIRST when the question names one of these by id or name, "
                "and cite its fields — the remedy text is the same the screen shows. "
                "For what a law or concept IS in general use platform_help; END your "
                "answer with the offer the result names — its tool is on your roster, "
                "or it says which screen holds the act."
            ),
            parameters=_EXPLAIN_PARAMS,
            run=lambda a: explain_object(connection_id, a),
        ),
    ]
