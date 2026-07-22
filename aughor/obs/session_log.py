"""The agent-session log — one append-only event per thing that happened in a run.

Flag: ``obs.session_log`` (env ``AUGHOR_OBS_SESSION_LOG``). Strict no-op when off.

**Why this exists alongside ``task_history``.** That table is span-shaped: one row
per *completed* unit of work, written on exit, ordered by a start-time string.
This is event-shaped — separate records with a monotonic ``seq``, written as
things happen. Three things follow from the difference, and each is a gap we
could not close otherwise:

1. **The quick answer path was invisible.** ``telemetry.new_trace`` is called in
   exactly one place — inside the deep path — so a quick ``/ask`` or ``/chat``
   turn minted no trace id at all, and its SQL runs through ``db.execute``
   rather than the span-emitting guarded executor. The most-used door in the
   product could not be reconstructed after the fact. Binding the trace at the
   ask door (:func:`aughor.telemetry.bind_trace`) fixes that for every path at
   once.
2. **A call that never returns left no evidence.** ``tool_call`` is written on
   ENTRY, so a hang, a cancellation, or a killed process is still visible as a
   call with no result. A span row only ever appears after the body returns.
3. **LLM calls were aggregated and discarded.** ``metering.record_llm`` sums
   tokens into a per-run counter; model, role, latency, retries and the silent
   fallback that can swap the model mid-run all vanished. Each is now a row.

The vocabulary follows the AIP session-log shape so the events mean the same
thing to a reader who knows that model. ``tool_call``/``tool_call_result`` cover
both graph nodes and genuine tools — ``payload.span_kind`` (``node`` | ``tool``)
keeps the distinction rather than pretending a router node is a tool call.

Every writer here is best-effort: observability must never break the answer path
it observes.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The event vocabulary. Kept small and closed on purpose — a reader should be
# able to hold it in their head, and a monitor written against a kind should not
# silently miss a synonym.
USER_REQUEST = "user_request"
TOOL_CALL = "tool_call"
TOOL_CALL_RESULT = "tool_call_result"
LLM_CALL = "llm_call"
FINAL_RESPONSE = "final_response"
EXECUTION_ERROR = "execution_error"

EVENT_KINDS = (
    USER_REQUEST, TOOL_CALL, TOOL_CALL_RESULT, LLM_CALL,
    FINAL_RESPONSE, EXECUTION_ERROR,
)

# Cap free-text payload values (a question, a SQL string, an error). Matches the
# span sink's cap so the two tables truncate identically.
_MAX_TEXT = 2000


def enabled() -> bool:
    """True when the ``obs.session_log`` flag is on. Never raises — a flag-store
    failure means "off", not a broken answer path."""
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("obs.session_log")
    except Exception:
        return False


def _clip(value: Any) -> Any:
    """Cap strings; leave scalars alone; stringify the rest (payloads are JSON)."""
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_TEXT]


def emit(
    kind: str,
    *,
    name: str = "",
    trace_id: str = "",
    span_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    ok: Optional[bool] = None,
    duration_ms: Optional[float] = None,
    error_class: Optional[str] = None,
    investigation_id: Optional[str] = None,
    conn_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    row_count: Optional[int] = None,
    retries: Optional[int] = None,
    payload: Optional[dict] = None,
) -> None:
    """Append one session event. Strict no-op when the flag is off.

    ``trace_id`` defaults to the ambient trace (whatever
    :func:`aughor.telemetry.bind_trace` pinned for this run). An event with no
    trace at all is dropped rather than written orphaned — an uncorrelated row
    is noise that cannot be reconstructed into anything, and writing it would
    make the table look healthier than it is.

    Identity (``session_id``/``user_id``/``agent_id``) is read from the ambient
    contextvars, so nothing has to be threaded through the graph to attribute an
    event.
    """
    if not enabled():
        return
    try:
        from aughor import telemetry as _tel
        tid = trace_id or _tel.current_trace_id()
        if not tid:
            return
        session_id, user_id, agent_id = _tel.trace_identity()
        from aughor.kernel.ledger import Ledger
        from aughor.org.context import current_org_id
        Ledger.default().session_event_insert({
            "trace_id": tid,
            "kind": kind,
            "name": name or None,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "ok": ok,
            "duration_ms": duration_ms,
            "error_class": error_class,
            "investigation_id": investigation_id,
            "session_id": session_id or None,
            "user_id": user_id or None,
            "agent_id": agent_id or None,
            "conn_id": conn_id,
            "org_id": current_org_id() or "default",
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            # Only a real total when at least one half was actually reported —
            # summing two unknowns into 0 is how a cost aggregate starts lying.
            "total_tokens": (None if prompt_tokens is None and completion_tokens is None
                             else (prompt_tokens or 0) + (completion_tokens or 0)),
            "row_count": row_count,
            "retries": retries,
            "payload": {k: _clip(v) for k, v in (payload or {}).items()} or None,
        })
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "session_log sink best-effort; the run it observes proceeds",
                 counter="obs.session_log.sink")


# ── Read side ─────────────────────────────────────────────────────────────────

def recover_session(trace_id: str, *, org_id: Optional[str] = None,
                    limit: int = 2000) -> list[dict]:
    """Every event for one run, in the order it happened — the replay."""
    from aughor.kernel.ledger import Ledger
    return Ledger.default().session_events(
        trace_id=trace_id, org_id=org_id, limit=limit, ascending=True)


def recent_sessions(*, org_id: Optional[str] = None, limit: int = 50,
                    scan: int = 2000) -> list[dict]:
    """One summary row per recent run, newest first.

    Derived by folding the raw events rather than kept as a separate table:
    a summary that can disagree with its own event log is worse than no summary.
    """
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().session_events(org_id=org_id, limit=scan)
    runs: dict[str, dict] = {}
    for e in reversed(rows):  # oldest-first so `started`/question land correctly
        r = runs.setdefault(e["trace_id"], {
            "trace_id": e["trace_id"], "started": e["at"], "question": "",
            "events": 0, "tool_calls": 0, "llm_calls": 0, "errors": 0,
            "investigation_id": None, "session_id": e.get("session_id"),
            "agent_id": e.get("agent_id"), "conn_id": e.get("conn_id"),
            "ok": None, "duration_ms": None,
        })
        r["events"] += 1
        kind = e["kind"]
        if kind == USER_REQUEST:
            r["question"] = (e.get("payload") or {}).get("question", "")
        elif kind == TOOL_CALL:
            r["tool_calls"] += 1
        elif kind == LLM_CALL:
            r["llm_calls"] += 1
        elif kind == EXECUTION_ERROR:
            r["errors"] += 1
        elif kind == FINAL_RESPONSE:
            r["ok"] = e.get("ok")
            r["duration_ms"] = e.get("duration_ms")
        if e.get("investigation_id"):
            r["investigation_id"] = e["investigation_id"]
        if e.get("conn_id"):
            r["conn_id"] = e["conn_id"]
    out = sorted(runs.values(), key=lambda r: r["started"], reverse=True)
    return out[:limit]


def tool_reliability(*, org_id: Optional[str] = None, scan: int = 5000) -> list[dict]:
    """Per-tool call/failure counts and latency, folded from ``tool_call_result``.

    The question this answers — "which tool fails, and how slowly" — is the one
    the AIP session-log docs single out as the reason to log tool results
    structurally rather than as text.
    """
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().session_events(
        kind=TOOL_CALL_RESULT, org_id=org_id, limit=scan)
    agg: dict[str, dict] = {}
    for e in rows:
        name = e.get("name") or "(unnamed)"
        a = agg.setdefault(name, {"tool": name, "calls": 0, "failures": 0,
                                  "total_ms": 0.0, "max_ms": 0.0})
        a["calls"] += 1
        if e.get("ok") is False:
            a["failures"] += 1
        ms = e.get("duration_ms") or 0.0
        a["total_ms"] += ms
        a["max_ms"] = max(a["max_ms"], ms)
    out = []
    for a in agg.values():
        a["mean_ms"] = round(a["total_ms"] / a["calls"], 1) if a["calls"] else 0.0
        a["total_ms"] = round(a["total_ms"], 1)
        a["failure_rate"] = round(a["failures"] / a["calls"], 3) if a["calls"] else 0.0
        out.append(a)
    return sorted(out, key=lambda a: a["calls"], reverse=True)


def model_usage(*, org_id: Optional[str] = None, scan: int = 5000) -> list[dict]:
    """Per-model call counts, token totals, latency and failure rate.

    The question the per-call record exists to answer — "what did each model
    cost us, and which one is failing" — folded from real columns rather than
    JSON. ``tokens`` counts only calls whose backend actually reported usage;
    ``calls_without_usage`` says how many did not, so a low token total is never
    silently mistaken for a cheap model.
    """
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().session_events(kind=LLM_CALL, org_id=org_id, limit=scan)
    agg: dict[tuple, dict] = {}
    for e in rows:
        key = (e.get("provider") or "", e.get("model") or "(unknown)")
        a = agg.setdefault(key, {
            "provider": key[0], "model": key[1], "calls": 0, "failures": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "calls_without_usage": 0, "retried_calls": 0, "total_ms": 0.0,
        })
        a["calls"] += 1
        if e.get("ok") is False:
            a["failures"] += 1
        if e.get("total_tokens") is None:
            a["calls_without_usage"] += 1
        else:
            a["prompt_tokens"] += e.get("prompt_tokens") or 0
            a["completion_tokens"] += e.get("completion_tokens") or 0
            a["total_tokens"] += e.get("total_tokens") or 0
        if e.get("retries"):
            a["retried_calls"] += 1
        a["total_ms"] += e.get("duration_ms") or 0.0
    out = []
    for a in agg.values():
        a["mean_ms"] = round(a["total_ms"] / a["calls"], 1) if a["calls"] else 0.0
        a["total_ms"] = round(a["total_ms"], 1)
        a["failure_rate"] = round(a["failures"] / a["calls"], 3) if a["calls"] else 0.0
        out.append(a)
    return sorted(out, key=lambda a: a["calls"], reverse=True)


def keep_days() -> int:
    """Retention window in days (0 = keep forever). Enforced on write."""
    return int(os.environ.get("AUGHOR_SESSION_LOG_KEEP_DAYS", "14") or 0)
