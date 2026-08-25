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
GUARDRAIL = "guardrail"

EVENT_KINDS = (
    USER_REQUEST, TOOL_CALL, TOOL_CALL_RESULT, LLM_CALL,
    FINAL_RESPONSE, EXECUTION_ERROR, GUARDRAIL,
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
        # Which RUN and which CHARTER — the join Migration 10 exists for. Outside a job
        # (an /ask turn answered inline) both are empty, which is the honest answer:
        # the call belongs to a request, not to a background run.
        try:
            from aughor.kernel.jobs import run_attribution
            job_id, charter_id = run_attribution()
        except Exception:
            job_id, charter_id = "", ""
        _payload = payload or {}
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
            "job_id": job_id or None,
            "charter_id": charter_id or None,
            # `role` and `fallback` are NOT passed: the ledger derives both from the
            # payload, which every llm_call already carries. Migration 10 promoted them to
            # columns without a single emitter changing.
            "payload": {k: (v if k in _LONGFORM_KEYS else _clip(v))
                        for k, v in _payload.items()} or None,
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
                    scan: int = 2000, since: Optional[str] = None,
                    until: Optional[str] = None, agent_id: Optional[str] = None,
                    conn_id: Optional[str] = None) -> list[dict]:
    """One summary row per recent run, newest first.

    Derived by folding the raw events rather than kept as a separate table:
    a summary that can disagree with its own event log is worse than no summary.
    """
    from aughor.kernel.ledger import Ledger
    # Pushed to the query, not applied after the fold: a window the store can narrow is
    # one the scan does not have to spend on rows the caller will discard.
    rows = Ledger.default().session_events(org_id=org_id, limit=scan, since=since,
                                           until=until, agent_id=agent_id, conn_id=conn_id)
    runs: dict[str, dict] = {}
    for e in reversed(rows):  # oldest-first so `started`/question land correctly
        r = runs.setdefault(e["trace_id"], {
            "trace_id": e["trace_id"], "started": e["at"], "question": "",
            "events": 0, "tool_calls": 0, "llm_calls": 0, "errors": 0,
            "investigation_id": None, "session_id": e.get("session_id"),
            "agent_id": e.get("agent_id"), "conn_id": e.get("conn_id"),
            "ok": None, "duration_ms": None,
            # ── the index's columns ────────────────────────────────────────────────
            # Folded from the same rows as everything above, for the same reason: a
            # summary kept beside its event log is a summary that can disagree with it.
            "user_id": None, "ended_at": e["at"], "answer": "",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            # Cost is a FLOOR. `unpriced_calls` is what keeps a $0.00 from reading as
            # free when it means nobody published a rate for that model.
            "cost_usd": 0.0, "unpriced_calls": 0, "calls_without_usage": 0,
        })
        r["events"] += 1
        r["ended_at"] = e["at"]
        if not r["user_id"] and e.get("user_id"):
            r["user_id"] = e["user_id"]
        kind = e["kind"]
        if kind == USER_REQUEST:
            r["question"] = (e.get("payload") or {}).get("question", "")
        elif kind == TOOL_CALL:
            r["tool_calls"] += 1
        elif kind == LLM_CALL:
            r["llm_calls"] += 1
            if e.get("total_tokens") is None:
                # Unknown, not zero — several backends omit usage entirely.
                r["calls_without_usage"] += 1
            else:
                r["prompt_tokens"] += int(e.get("prompt_tokens") or 0)
                r["completion_tokens"] += int(e.get("completion_tokens") or 0)
                r["total_tokens"] += int(e.get("total_tokens") or 0)
                from aughor.obs.usage import cost_of_call
                usd, priced = cost_of_call(e)
                if priced:
                    r["cost_usd"] += usd
                else:
                    r["unpriced_calls"] += 1
        elif kind == EXECUTION_ERROR:
            r["errors"] += 1
        elif kind == FINAL_RESPONSE:
            r["ok"] = e.get("ok")
            r["duration_ms"] = e.get("duration_ms")
            # What the run ANSWERED, as far as the log knows: the headline is the only
            # answer text a final-response row carries. Named `answer` rather than
            # `output` so nobody reads it as the full response body.
            r["answer"] = (e.get("payload") or {}).get("headline", "") or ""
        if e.get("investigation_id"):
            r["investigation_id"] = e["investigation_id"]
        if e.get("conn_id"):
            r["conn_id"] = e["conn_id"]
    out = sorted(runs.values(), key=lambda r: r["started"], reverse=True)
    return out[:limit]


def session_index(
    *,
    org_id: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    scan: int = 4000,
    since: Optional[str] = None,
    until: Optional[str] = None,
    status: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    conn_id: Optional[str] = None,
    q: Optional[str] = None,
    min_duration_ms: Optional[float] = None,
    max_duration_ms: Optional[float] = None,
    min_tokens: Optional[int] = None,
) -> dict:
    """The trace index: filtered, counted, then paginated — in that order.

    Order is the whole contract. Filtering a PAGE and calling the result a filter is the
    defect this signature exists to prevent: it looks identical to the reader and answers
    a different question, and a total taken after the slice would confirm the wrong one.
    So the fold runs over the scan window, every filter applies to all of it, `total` is
    counted there, and only then does the page get cut.

    ⚠️ `scan` bounds how far back the fold reaches, so `total` is a total WITHIN that
    window and `scanned_events` is returned to say how wide it was. A count with no stated
    window is a claim about all of history that nobody checked.

    `status`: ``ok`` · ``error`` · ``unfinished``.

    ⚠️ ``unfinished`` means NO FINAL RESPONSE WAS RECORDED — not that a run is in flight.
    Only the `/ask` and `/chat` door wrapper emits one, so a run that reached the log by
    any other path never gets it. Measured on a real install: 53 of 73 runs, the oldest
    four days old. Calling that "running" would have been wrong about most of them, which
    is why the word is not used anywhere in this path.
    """
    rows = recent_sessions(org_id=org_id, limit=10_000, scan=scan,
                           since=since, until=until, agent_id=agent_id, conn_id=conn_id)

    def keep(r: dict) -> bool:
        if status == "ok" and r.get("ok") is not True:
            return False
        if status == "error" and not (r.get("ok") is False or r.get("errors")):
            return False
        if status == "unfinished" and r.get("ok") is not None:
            return False
        if user_id and str(r.get("user_id") or "") != user_id:
            return False
        if min_duration_ms is not None and (r.get("duration_ms") or 0) < min_duration_ms:
            return False
        if max_duration_ms is not None and (r.get("duration_ms") or 0) > max_duration_ms:
            return False
        if min_tokens is not None and int(r.get("total_tokens") or 0) < min_tokens:
            return False
        if q:
            needle = q.lower()
            hay = " ".join(str(r.get(k) or "") for k in
                           ("question", "answer", "trace_id", "agent_id", "conn_id"))
            if needle not in hay.lower():
                return False
        return True

    kept = [r for r in rows if keep(r)]
    start = max(0, int(offset))
    return {
        "rows": kept[start: start + max(1, int(limit))],
        "total": len(kept),
        "limit": int(limit),
        "offset": start,
        "scanned_events": scan,
    }


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


def route_mix(*, org_id: Optional[str] = None, scan: int = 5000,
              since_seq: Optional[int] = None) -> dict:
    """Which BODY served each `/ask` turn — the route receipt (Wave 6).

    This is `ask.converse`'s graduation input: the flag's stated exit is the headline
    receipt, the parity invariant, AND data on the converse/fast-path ratio, because the
    question "should conversation become the default door" is a measurement, not a taste.

    Folded from two kinds rather than one, which is the whole reason this function exists.
    The converse body logs itself (`tool_call` named `ask.converse`); every `/ask` turn
    logs a `final_response`. Counting only the first gives a numerator with nothing to
    divide it by — a ratio whose denominator was never recorded is the shape of mistake
    this codebase keeps paying for.

    THE WINDOW IS THE OTHER HALF OF THAT SAME MISTAKE, and this function shipped with it.
    The flag is off by default, so most of the log is traffic from before converse could
    run at all. Dividing by every turn ever recorded put 302 turns in a denominator that
    could never have contained them, and the first live reading came back 0.016 when the
    true figure was 4 of 4. A ratio's denominator must contain only things that could have
    had the property — the rule this repo has now paid for seven times, here inside the
    receipt built to answer the question.

    So the window defaults to the FIRST converse turn in the log. Before that marker
    converse was demonstrably serving nothing, which makes it the earliest point the
    question is even askable. `since_seq` overrides it (the flag's flip, a deploy, the
    start of a trial), and the window is reported back so the number is never read without
    its scope. With no converse turn at all the window is the whole log and the share is
    null — undefined, not zero.

    Deep turns stay IN the denominator on purpose, and that is a different question from
    the one above. They were never converse-eligible (`_converse_eligible` excludes
    `depth == "deep"`, escalations, dossier drills and seeded SQL), but the flag asks how
    much of the DOOR conversation would own, and a turn the router sent deep is still the
    door's traffic. What that makes this is a share of all `/ask` turns, not a hit rate
    over eligible ones — the label matters, and the honest one is on the field name.
    Recording the router's verdict per turn would let both be reported; `user_request`
    carries the REQUESTED depth ("auto"), which is not the same fact.

    `converse_turns` counts DISTINCT trace ids, not markers: one turn emits one marker
    today, but counting rows would silently become a lie the moment it emits two.

    Returns totals plus the per-turn tool/cost detail converse recorded, so "converse is
    chosen more" and "converse costs more" are answerable from one read.
    """
    from aughor.kernel.ledger import Ledger
    ledger = Ledger.default()

    finals = ledger.session_events(kind=FINAL_RESPONSE, org_id=org_id, limit=scan)
    ask_finals_all = [e for e in finals if (e.get("name") or "") == "ask"]

    marks_all = ledger.session_events(kind=TOOL_CALL, org_id=org_id, limit=scan)
    converse_all = [e for e in marks_all if (e.get("name") or "") == "ask.converse"]

    # Resolve the window before counting anything, so numerator and denominator can never
    # be taken from different populations.
    #
    # The window is per TURN, not per row, and that distinction is load-bearing. A turn
    # writes several rows — its converse marker and its final response at least — and
    # their order is not fixed. Filtering rows individually splits a turn across the
    # boundary: its marker counted in the numerator while its final sits outside the
    # denominator, which is the very "two different populations" error this window exists
    # to remove. Caught by the first test written against it, which read 1 of 2.
    seq_by_trace: dict = {}
    for e in (*ask_finals_all, *converse_all):
        trace, seq = e.get("trace_id"), e.get("seq")
        if trace is None or not isinstance(seq, int):
            continue
        prev = seq_by_trace.get(trace)
        seq_by_trace[trace] = seq if prev is None else min(prev, seq)

    converse_starts = [seq_by_trace[t] for t in
                       {e.get("trace_id") for e in converse_all if e.get("trace_id")}
                       if t in seq_by_trace]
    if since_seq is not None:
        window_from, window_reason = since_seq, "caller"
    elif converse_starts:
        window_from, window_reason = min(converse_starts), "first_converse_turn"
    else:
        window_from, window_reason = None, "no_converse_turn_yet"

    def _in_window(e) -> bool:
        if window_from is None:
            return True
        # An untimed row (no seq, or a trace with none) predates nothing and is kept —
        # dropping it would let a storage gap quietly shrink the denominator.
        start = seq_by_trace.get(e.get("trace_id"))
        return start is None or start >= window_from

    ask_finals = [e for e in ask_finals_all if _in_window(e)]
    converse_marks = [e for e in converse_all if _in_window(e)]
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
        # The scope every number above was computed in. Reported rather than assumed,
        # because the failure this replaced was not a wrong calculation — it was a right
        # calculation over the wrong population, and nothing in the response said so.
        "window": {
            "from_seq": window_from,
            "reason": window_reason,
            "excluded_before_window": len(ask_finals_all) - total,
            "lifetime_ask_turns": len(ask_finals_all),
        },
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


def prompt_weight(*, org_id: Optional[str] = None, scan: int = 5000) -> dict:
    """Prompt-token spend per CALL SITE — which templates the token budget actually
    goes to (PE-1). The prompt-economy work starts from a measured top-N, not an
    RTF export of one specimen; this is that measurement, folded from the same
    per-call records ``model_usage`` reads, keyed by the ``caller`` attribution
    the provider stamps on every call.

    Shares are computed over calls that REPORTED usage; calls without usage are
    counted per site (``calls_without_usage``) rather than folded into zero — a
    site served by a backend that omits usage must not read as free. Events from
    before the attribution existed fold into a visible ``(unattributed)`` row,
    never silently dropped: the coverage of the measurement is part of the
    measurement."""
    from aughor.kernel.ledger import Ledger
    rows = Ledger.default().session_events(kind=LLM_CALL, org_id=org_id, limit=scan)
    agg: dict[str, dict] = {}
    reported_prompt_total = 0
    for e in rows:
        p = e.get("payload") or {}
        caller = p.get("caller") or "(unattributed)"
        a = agg.setdefault(caller, {
            "caller": caller, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "calls_without_usage": 0, "roles": {}, "models": {},
        })
        a["calls"] += 1
        if e.get("prompt_tokens") is None and e.get("completion_tokens") is None:
            a["calls_without_usage"] += 1
        else:
            pt = int(e.get("prompt_tokens") or 0)
            a["prompt_tokens"] += pt
            a["completion_tokens"] += int(e.get("completion_tokens") or 0)
            reported_prompt_total += pt
        role = p.get("role")
        if role:
            a["roles"][role] = a["roles"].get(role, 0) + 1
        if e.get("model"):
            a["models"][e["model"]] = a["models"].get(e["model"], 0) + 1
    sites = []
    for a in agg.values():
        reported = a["calls"] - a["calls_without_usage"]
        a["mean_prompt_tokens"] = round(a["prompt_tokens"] / reported, 1) if reported else None
        a["prompt_share"] = (round(a["prompt_tokens"] / reported_prompt_total, 3)
                             if reported_prompt_total else None)
        a["roles"] = dict(sorted(a["roles"].items(), key=lambda kv: kv[1], reverse=True))
        a["models"] = dict(sorted(a["models"].items(), key=lambda kv: kv[1], reverse=True))
        sites.append(a)
    sites.sort(key=lambda a: (a["prompt_tokens"], a["calls"]), reverse=True)
    return {
        "sites": sites,
        "scanned_calls": len(rows),
        "reported_prompt_tokens": reported_prompt_total,
    }


def keep_days() -> int:
    """Retention window in days (0 = keep forever). Enforced on write."""
    return int(os.environ.get("AUGHOR_SESSION_LOG_KEEP_DAYS", "14") or 0)
