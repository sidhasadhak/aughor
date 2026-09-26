"""TJ-2 (§3.47) — `trajectory_of`: one record per run, joined at read.

The diagram's bottom strip — state, action, observation, outcome, reward, one format — did
not exist here: seventeen run-level stores, no shared run id, no persisted step record.
TJ-1 made the trace id the shared key (the session log, the history row, the audit rows,
the guard fires and the decision records all carry the run's ambient trace); this module
is the read that walks it. **No new store.** Steps ride `session_events` (the `step` kind,
written by `agent/tool_loop.run_tool_loop`); the answer rides the history row; execution
rides `audit_log`; guard fires ride `guard_verdicts`; picks ride `decision_record`; the
reward fields — a person's verdict, the re-check state, the execution outcome — are read
from where each already lives. The exporters may read this and nothing else, so a training
row carries the context the model saw.

**The lawful lane, at read time.** A step's tool, SQL, counts, errors, guard fires and
outcome are work artifacts and are served. Its arguments and result excerpt are payloads:
captured only under an open prompt window, and WITHHELD on an ungated read exactly as
`/learning/decisions` withholds `context` — the key stays, empty, and `payload_withheld`
says why. A reader who is handed a gated read (`gated=True`) gets them back.
"""
from __future__ import annotations

from typing import Any, Optional

#: Fields of a `step` event that are payload under §6 item 4 — served only on a gated read.
STEP_PAYLOAD_FIELDS: tuple[str, ...] = ("arguments", "result_excerpt")

_WITHHELD = ("the model's arguments and the tool's result are payloads under ROADMAP §6 "
             "item 4; they are captured only under an open prompt window and not served "
             "on this ungated read")
_ANSWER_CLIP = 2000
_SQL_CLIP = 4000


def trajectory_of(trace_id: str, *, org_id: Optional[str] = None,
                  gated: bool = False) -> Optional[dict]:
    """The run's trajectory, or None when nothing carries this trace.

    ``org_id`` is the tenant filter on every store that has one (DATA-06); ``None`` means
    no filter, as each store's own reader defines it. Every join is best-effort and says
    so: a store that could not be read contributes ``{"unavailable": …}`` rather than an
    empty list, because an empty list would teach the reader the data does not exist."""
    from aughor.obs import session_log

    trace_id = str(trace_id or "").strip()
    if not trace_id:
        return None
    events = session_log.recover_session(trace_id, org_id=org_id)
    turns = _read("history", lambda: _history_rows(trace_id))
    if not events and not (isinstance(turns, list) and turns):
        return None

    request = next((e for e in events if e.get("kind") == session_log.USER_REQUEST), None)
    final = next((e for e in reversed(events) if e.get("kind") == session_log.FINAL_RESPONSE), None)
    steps = [_step(e, gated=gated) for e in events if e.get("kind") == session_log.STEP]
    question = str(((request or {}).get("payload") or {}).get("question") or "")
    if not question and isinstance(turns, list) and turns:
        question = str(turns[0].get("question") or "")

    executions = _read("audit_log", lambda: _executions(trace_id, org_id))
    guards = _read("guard_verdicts", lambda: _guard_rows(trace_id, org_id))
    decisions = _read("decision_record", lambda: _decision_rows(trace_id))
    answers = [_answer(t) for t in turns] if isinstance(turns, list) else turns
    reward = _reward(answers, executions, guards)

    return {
        "trace_id": trace_id,
        "question": question,
        "conn_id": next((e.get("conn_id") for e in events if e.get("conn_id")), None)
                   or (turns[0].get("connection_id") if isinstance(turns, list) and turns else None),
        "agent_id": next((e.get("agent_id") for e in events if e.get("agent_id")), None),
        "started_at": (request or (events[0] if events else {})).get("at"),
        "ok": final.get("ok") if final else None,
        "duration_ms": final.get("duration_ms") if final else None,
        "steps": steps,
        "answers": answers,
        "executions": executions,
        "guards": guards,
        "decisions": decisions,
        "reward": reward,
        "payload_withheld": None if gated else _WITHHELD,
        "counts": {"events": len(events), "steps": len(steps),
                   "executions": len(executions) if isinstance(executions, list) else None,
                   "guards": len(guards) if isinstance(guards, list) else None,
                   "decisions": len(decisions) if isinstance(decisions, list) else None},
    }


# ── the joins ─────────────────────────────────────────────────────────────────────────

def _read(store: str, read):
    """A join that cannot be read says so — never an empty list posing as a true negative."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 — one store down must not hide the others
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"trajectory: {store} could not be read", counter="obs.trajectory.join")
        return {"unavailable": f"{store} could not be read ({type(exc).__name__})"}


def _step(e: dict, *, gated: bool) -> dict:
    p = dict(e.get("payload") or {})
    out = {
        "seq": e.get("seq"), "at": e.get("at"), "index": p.get("index"),
        "tool": e.get("name") or p.get("tool"), "site": p.get("site"),
        "ok": e.get("ok") if e.get("ok") is not None else p.get("ok"),
        "duration_ms": e.get("duration_ms"), "row_count": e.get("row_count"),
        "sql": str(p.get("sql") or "")[:_SQL_CLIP], "error": str(p.get("error") or ""),
        "guards": list(p.get("guards") or []), "result_chars": p.get("result_chars"),
        "captured": bool(p.get("captured")),
    }
    for field in STEP_PAYLOAD_FIELDS:
        out[field] = p.get(field, "") if gated else ""
    if not gated and out["captured"]:
        out["payload_withheld"] = True
    return out


def _history_rows(trace_id: str) -> list[dict]:
    from aughor.db.history import by_trace
    return by_trace(trace_id)


def _answer(t: dict) -> dict:
    report = t.get("report") if isinstance(t.get("report"), dict) else {}
    rechecks = [r for r in (report.get("rechecks") or []) if isinstance(r, dict)]
    return {
        "investigation_id": t.get("id"), "kind": t.get("kind"), "status": t.get("status"),
        "question": t.get("question"), "connection_id": t.get("connection_id"),
        "started_at": t.get("started_at"), "completed_at": t.get("completed_at"),
        "headline": str(t.get("headline") or report.get("headline") or "")[:_ANSWER_CLIP],
        "sql": str(report.get("sql") or "")[:_SQL_CLIP],
        "envelope": report.get("envelope") if isinstance(report.get("envelope"), dict) else None,
        "rechecks": [{"at": r.get("at") or r.get("checked_at"), "status": r.get("status")}
                     for r in rechecks],
        "verdict": _verdict(str(t.get("id") or "")),
    }


def _verdict(inv_id: str) -> Optional[dict]:
    if not inv_id:
        return None
    try:
        from aughor.feedback.verdicts import latest_verdict
        v = latest_verdict(inv_id)
    except Exception as exc:  # noqa: BLE001
        from aughor.kernel.errors import tolerate
        tolerate(exc, "trajectory: the verdict store could not be read", counter="obs.trajectory.verdict")
        return {"unavailable": "verdicts could not be read"}
    if not v:
        return None
    return {k: v.get(k) for k in ("verdict", "note", "created_at", "corrected_sql") if k in v}


def _executions(trace_id: str, org_id: Optional[str]) -> list[dict]:
    from aughor.security.audit import AuditLogger
    rows = AuditLogger.recent(limit=500, org_id=org_id, trace_id=trace_id)
    rows.reverse()                                   # newest-first store, oldest-first trajectory
    return [{"id": r.get("id"), "ts": r.get("ts"), "connection_id": r.get("connection_id"),
             "surface": r.get("hypothesis_id"), "sql": str(r.get("sql_full") or "")[:_SQL_CLIP],
             "verdict": r.get("verdict"), "row_count": r.get("row_count"),
             "duration_ms": r.get("duration_ms"), "error": r.get("error")} for r in rows]


def _guard_rows(trace_id: str, org_id: Optional[str]) -> list[dict]:
    from aughor.security.audit import GuardVerdicts
    rows = GuardVerdicts.recent(limit=500, trace_id=trace_id, org_id=org_id)
    rows.reverse()
    return [{"id": r.get("id"), "ts": r.get("ts"), "pattern": r.get("pattern"),
             "subject": r.get("subject"), "phase": r.get("phase"),
             "sql_digest": r.get("sql_digest"), "detail": r.get("detail")} for r in rows]


def _decision_rows(trace_id: str) -> list[dict]:
    from aughor.learning.decisions import list_for_trace
    return [{"id": d.get("id"), "ts": d.get("ts"), "site": d.get("site"),
             "chosen": d.get("chosen"), "label": d.get("label"), "options": d.get("options"),
             "outcome": d.get("outcome"), "confidence": d.get("confidence"),
             "inv_id": d.get("inv_id")} for d in list_for_trace(trace_id)]


def _reward(answers: Any, executions: Any, guards: Any) -> dict:
    """The reward FIELDS, never a number: TJ-3 owns the label, and it must take both
    values on real traffic before anything reads it. Here: what a person said, what the
    re-check found, and whether the statements ran."""
    human = None
    recheck = None
    if isinstance(answers, list):
        for a in answers:
            if a.get("verdict") and "verdict" in a["verdict"]:
                human = a["verdict"]["verdict"]
            if a.get("rechecks"):
                recheck = a["rechecks"][-1].get("status")
    execution = None
    if isinstance(executions, list):
        if not executions:
            execution = "none"
        elif any(x.get("error") for x in executions):
            execution = "error"
        else:
            execution = "ok"
    return {"human_verdict": human, "recheck": recheck, "execution": execution,
            "guard_fires": (len(guards) if isinstance(guards, list) else None),
            "label": "unlabeled"}
