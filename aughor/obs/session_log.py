"""The agent-session log — one append-only event per thing that happened in a run.

Always on (graduated on receipt ``45dcc137f55b``; the flag was deleted 2026-08-01).

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

#: Payload keys the producer has already capped, with truncation marked. `_clip`
#: leaves them alone so a deliberately larger prompt cap is not silently cut back
#: to `_MAX_TEXT` — which would make the `*_truncated` markers lie.
_LONGFORM_KEYS = frozenset({"system_prompt", "user_prompt", "response"})


def enabled() -> bool:
    """Recording is permanent (the ``obs.session_log`` flag was hardwired 2026-08-01).

    Kept as a function because the writers call it on every event and a future kill
    switch — a store outage, a retention emergency — would land here rather than at
    the ~6 call sites.
    """
    return True


#: How much of a list/dict payload value survives, and how deep the walk goes. Bounds
#: exist so preserving structure cannot turn one event into an unbounded row.
_MAX_ITEMS = 50
_MAX_DEPTH = 3


def _clip(value: Any, _depth: int = 0) -> Any:
    """Cap strings, leave scalars alone, and keep lists/dicts as lists/dicts.

    The old rule stringified everything that was not a scalar, on the reasoning that
    "payloads are JSON". That is the argument for the opposite: JSON carries arrays and
    objects natively, and `str()` is precisely what destroys them. A writer that passed
    `{"tools": ["list_tables", "run_sql"]}` had it stored as the *repr*
    `"['list_tables', 'run_sql']"`, so `route_mix`'s tool tally — iterating what it
    reasonably assumed was a list — counted CHARACTERS, and reported
    `{"'": 4, "l": 3, "s": 3, ...}` as the tools a conversation used.

    Nothing was reading the repr back (no `literal_eval` anywhere), so this is a
    fidelity fix with no parsing counterpart to update. Anything still exotic — a model,
    an exception, a set — stringifies exactly as before.
    """
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if _depth < _MAX_DEPTH:
        if isinstance(value, (list, tuple)):
            return [_clip(v, _depth + 1) for v in list(value)[:_MAX_ITEMS]]
        if isinstance(value, dict):
            return {str(k): _clip(v, _depth + 1)
                    for k, v in list(value.items())[:_MAX_ITEMS]}
    return str(value)[:_MAX_TEXT]


def prompt_capture_enabled() -> bool:
    """True when a capture WINDOW is currently open — the deliberate, self-expiring
    opt-in to storing the actual content of model calls.

    The rest of the log is metadata; this is the material itself (schema, sampled
    values, glossary, the user's question), so it is never a standing setting: an
    operator opens a window bounded by a call budget AND a clock, and it closes itself.
    See :mod:`aughor.obs.prompt_window`. A store failure means off, like :func:`enabled`.
    """
    try:
        from aughor.obs import prompt_window
        return prompt_window.active()
    except Exception:
        return False


def _prompt_cap() -> int:
    try:
        return max(0, int(os.environ.get("AUGHOR_OBS_PROMPT_MAX_CHARS", str(_MAX_TEXT))))
    except ValueError:
        return _MAX_TEXT


def _cap_text(value: Any, cap: int) -> tuple[str, bool]:
    """(text, was_truncated). Truncation is reported, never silent: a shortened
    prompt reproduces a *different* call than the one that ran, so a consumer
    that replays it must be able to tell."""
    text = value if isinstance(value, str) else str(value)
    if cap and len(text) > cap:
        return text[:cap], True
    return text, False


def capture_prompt(system: Any = None, user: Any = None, output: Any = None) -> dict:
    """The prompt/response fields for an ``llm_call`` payload, or ``{}`` when no
    capture window is open.

    Claiming budget (:func:`prompt_window.consume`) is what makes the operator's
    number mean what it says: the window shortens only when content is actually
    stored. That is why recording has to be ON here too — this function is evaluated
    as an ARGUMENT to :func:`emit`, which is a no-op when the log is off, so
    consuming first would spend an operator's window on calls that wrote nothing.

    The capping and truncation-marking policy lives here rather than at each call
    site, so every producer stores content the same way and there is one place to
    change if redaction is ever added.
    """
    if system is None and user is None and output is None:
        return {}
    if not enabled():
        return {}
    try:
        from aughor.obs import prompt_window
        if not prompt_window.consume():
            return {}
    except Exception:
        return {}
    cap = _prompt_cap()
    out: dict[str, Any] = {}
    for key, value in (("system_prompt", system), ("user_prompt", user),
                       ("response", output)):
        if value is None:
            continue
        text, truncated = _cap_text(value, cap)
        out[key] = text
        if truncated:
            out[f"{key}_truncated"] = True
    return out


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
            "payload": {k: (v if k in _LONGFORM_KEYS else _clip(v))
                        for k, v in (payload or {}).items()} or None,
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


def route_mix(*, org_id: Optional[str] = None, scan: int = 5000) -> dict:
    """Which BODY served each `/ask` turn — the route receipt (Wave 6).

    This is `ask.converse`'s graduation input: the flag's stated exit is the headline
    receipt, the parity invariant, AND data on the converse/fast-path ratio, because the
    question "should conversation become the default door" is a measurement, not a taste.

    Folded from two kinds rather than one, which is the whole reason this function exists.
    The converse body logs itself (`tool_call` named `ask.converse`); every `/ask` turn
    logs a `final_response`. Counting only the first gives a numerator with nothing to
    divide it by — a ratio whose denominator was never recorded is the shape of mistake
    this codebase keeps paying for. So the denominator is every finished `/ask` turn, and
    a turn is `fast_path` exactly when it finished without a converse marker.

    `converse_turns` counts DISTINCT trace ids, not markers: one turn emits one marker
    today, but counting rows would silently become a lie the moment it emits two.

    Returns totals plus the per-turn tool/cost detail converse recorded, so "converse is
    chosen more" and "converse costs more" are answerable from one read.
    """
    from aughor.kernel.ledger import Ledger
    ledger = Ledger.default()

    finals = ledger.session_events(kind=FINAL_RESPONSE, org_id=org_id, limit=scan)
    ask_finals = [e for e in finals if (e.get("name") or "") == "ask"]

    marks = ledger.session_events(kind=TOOL_CALL, org_id=org_id, limit=scan)
    converse_marks = [e for e in marks if (e.get("name") or "") == "ask.converse"]
    converse_traces = {e.get("trace_id") for e in converse_marks if e.get("trace_id")}

    total = len(ask_finals)
    # Intersect with FINISHED turns: a converse marker whose turn never completed (crash,
    # disconnect) must not inflate the share of a denominator it is not in.
    converse = len({e.get("trace_id") for e in ask_finals
                    if e.get("trace_id") in converse_traces})
    steps = [int(e.get("row_count") or 0) for e in converse_marks]
    payloads = [e.get("payload") or {} for e in converse_marks]

    def _avg(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "ask_turns": total,
        "converse_turns": converse,
        "fast_path_turns": total - converse,
        # None, not 0.0, when nothing has run: a share of zero turns is undefined, and
        # reporting 0% would read as "converse is never chosen".
        "converse_share": round(converse / total, 3) if total else None,
        "converse_mean_steps": _avg(steps),
        "converse_mean_injected_chars": _avg([p.get("injected_chars") for p in payloads]),
        "converse_stop_reasons": _tally(p.get("stop_reason") for p in payloads),
        "converse_tools": _tally(t for p in payloads for t in (p.get("tools") or [])),
        # Markers without a finished turn — visible rather than silently dropped, because
        # a rising count here means turns are dying mid-conversation.
        "converse_unfinished": len(converse_traces) - converse,
    }


def _tally(values) -> dict:
    out: dict[str, int] = {}
    for v in values:
        if v:
            out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


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
