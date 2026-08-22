"""Wave CR1/CR2 — the session log's HTTP face: traces and the activity stream.

`session_events` had four in-process readers and zero HTTP exposure — the
`/usage` rollup was the only consumer of a store that can reconstruct every
run. These routes are VIEWS over `Ledger.session_events()` and the folds in
`aughor.obs.session_log` (J10/J12: no second store, no copies, nothing here
writes).

Two honesty rules every response follows:

- **A quiet store is a confident empty.** Recording is permanent (the flag was
  hardwired 2026-08-01), so nothing recorded means nothing happened — the answer
  says so plainly instead of pointing at a switch that no longer exists.
- **The kind vocabulary comes from the data.** `/activity` reports the kinds
  actually present in the store, so a filter UI can never advertise event
  kinds nothing emits.

RBAC: the raw-event surfaces sit with `/audit/feed` at `admin.manage_org`
(see `rbac/policy.py`) — session events carry SQL text and, when the capture
flag is on, prompt content; the viewer-reads-everything floor is wrong for
them.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from aughor.kernel.ledger import Ledger
from aughor.obs import prompt_window, session_log
from aughor.obs.timeseries import resolve_window
from aughor.org.context import current_org_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["obs"])

_POLL_SECONDS = 1.0          # tail cadence (indexed seq > ? query)
_HEARTBEAT_EVERY = 25        # SSE comment keep-alive, in tail ticks

#: Payload keys that exist only when a prompt-capture window was open for the call.
_CONTENT_KEYS = ("system_prompt", "user_prompt", "response")


def _mark_content(event: dict) -> dict:
    """Label prompt content so a UI can gate it explicitly rather than discover
    it by accident: `content_captured` says whether this row carries any."""
    payload = event.get("payload")
    if isinstance(payload, dict) and any(k in payload for k in _CONTENT_KEYS):
        event["content_captured"] = True
    return event


# ── CR1: traces ──────────────────────────────────────────────────────────────────

@router.get("/traces")
def list_traces(limit: int = 50, investigation_id: Optional[str] = None,
                agent_id: Optional[str] = None):
    """Recent runs, one summary per trace, newest first — the waterfall's index.

    ``investigation_id`` / ``agent_id`` narrow to the traces that touched them
    (the H3 drill-in: a run row on the per-agent page opens its trace here).
    """
    org_id = current_org_id() or None
    ledger = Ledger.default()

    if investigation_id or agent_id:
        rows = ledger.session_events(
            investigation_id=investigation_id, agent_id=agent_id,
            org_id=org_id, limit=2000)
        trace_ids = list(dict.fromkeys(r["trace_id"] for r in rows))
        # A deep run's trace IS its investigation id (telemetry.new_trace
        # returns it verbatim), and its span rows carry a NULL
        # investigation_id column — the door wrapper only brackets /ask and
        # /chat. The direct match is the honest second half of this filter.
        if investigation_id and investigation_id not in trace_ids:
            if ledger.session_events(trace_id=investigation_id, limit=1):
                trace_ids.append(investigation_id)
        trace_ids = trace_ids[: max(1, int(limit))]
        summaries = [s for s in session_log.recent_sessions(org_id=org_id, limit=1000)
                     if s["trace_id"] in set(trace_ids)]
        return {"measured": True, "recording": True, "traces": summaries}

    summaries = session_log.recent_sessions(org_id=org_id, limit=max(1, min(int(limit), 200)))
    return {"measured": True, "recording": True, "traces": summaries}


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str):
    """One run's full event log plus its span tree — the waterfall.

    The tree is honest about what the data supports: tool spans pair their
    entry (`tool_call`) and exit (`tool_call_result`) rows by `span_id` and
    nest by `parent_span_id`; events with no span id (`llm_call`,
    `user_request`, `final_response`, `execution_error`) are TRACE-LEVEL, kept
    in `events` seq order and never given invented parents.
    """
    events = session_log.recover_session(trace_id, org_id=current_org_id() or None)
    if not events:
        raise HTTPException(status_code=404, detail="No events for this trace")

    spans: dict[str, dict] = {}
    order: list[str] = []
    for e in events:
        _mark_content(e)
        sid = e.get("span_id")
        if not sid:
            continue
        span = spans.get(sid)
        if span is None:
            span = spans[sid] = {
                "span_id": sid, "parent_span_id": e.get("parent_span_id"),
                "name": e.get("name"), "seq": e["seq"], "at": e["at"],
                "kind": (e.get("payload") or {}).get("span_kind") or "tool",
                "ok": None, "duration_ms": None, "error_class": None,
                "row_count": None, "children": [],
            }
            order.append(sid)
        if e["kind"] == session_log.TOOL_CALL_RESULT:
            span["ok"] = e.get("ok")
            span["duration_ms"] = e.get("duration_ms")
            span["error_class"] = e.get("error_class")
            span["row_count"] = e.get("row_count")

    roots: list[dict] = []
    for sid in order:
        span = spans[sid]
        parent = spans.get(span["parent_span_id"] or "")
        (parent["children"] if parent else roots).append(span)

    final = next((e for e in reversed(events) if e["kind"] == session_log.FINAL_RESPONSE), None)
    first = events[0]

    # Deep runs mint their trace FROM the investigation id (telemetry.new_trace
    # returns it verbatim) and their span rows carry no investigation_id column
    # — only the /ask+/chat door wrapper stamps one. Resolve the direct match
    # so a deep run's feedback tab attaches to the run it belongs to.
    inv_id = next((e["investigation_id"] for e in events if e.get("investigation_id")), None)
    question = ((first.get("payload") or {}).get("question", "")
                if first["kind"] == session_log.USER_REQUEST else "")
    if inv_id is None:
        try:
            from aughor.db.history import get_investigation
            inv = get_investigation(trace_id)
            if inv:
                inv_id = trace_id
                question = question or str(inv.get("question") or "")
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "trace→investigation resolve is best-effort; the "
                          "waterfall renders without the feedback link",
                     counter="obs.trace.inv_resolve")

    return {
        "measured": True,
        "recording": True,
        "trace_id": trace_id,
        "question": question,
        "investigation_id": inv_id,
        "conn_id": next((e["conn_id"] for e in events if e.get("conn_id")), None),
        "agent_id": next((e["agent_id"] for e in events if e.get("agent_id")), None),
        "ok": final.get("ok") if final else None,
        "duration_ms": final.get("duration_ms") if final else None,
        "events": events,
        "spans": roots,
    }


# ── Prompt capture as a bounded, self-expiring act ───────────────────────────────
# Storing model-call CONTENT is the most sensitive write this product makes, so it is
# never a standing setting: an operator opens a window bounded by a call budget AND a
# clock, and it closes itself. See aughor/obs/prompt_window.py.

class _OpenCaptureRequest(BaseModel):
    calls: int = prompt_window.DEFAULT_CALLS
    minutes: int = prompt_window.DEFAULT_MINUTES
    opened_by: str = ""
    reason: str = ""


@router.get("/obs/route-mix")
def route_mix(scan: int = 5000, since_seq: Optional[int] = None):
    """Which BODY served each `/ask` turn — `ask.converse`'s route receipt (Wave 6).

    The fold has existed and been tested since #288 with **no caller anywhere**: no route,
    no UI. A graduation input nobody can read is not an input, and this router exists
    precisely because `session_events` once had "four in-process readers and zero HTTP
    exposure" — the same gap, one fold later.

    Read it as COVERAGE, not as a verdict. `_converse_eligible` has no sampling: with the
    flag on, converse serves every quick turn that is not an escalation, a dossier drill
    or a seeded-SQL run. So `converse_share` answers "how much of real traffic would
    graduation change", which is genuinely unknown until traffic runs — but it does not
    answer "does a conversation answer better". That question belongs to the other two
    parts of the flag's exit criterion, the scripted faux receipt and the parity
    invariant, and reading this number as a quality signal would be a proxy standing in
    for the real measure.

    `converse_share` is null rather than 0.0 when no `/ask` turn has finished: a share of
    zero turns is undefined, and 0% would read as "converse is never chosen".

    The numbers are WINDOWED, and `window` in the response says how. The flag is off by
    default, so most of the log predates converse being able to run at all; counting those
    turns put a denominator around a population they were never part of, and the first
    live reading said 0.016 when the honest figure was 4 of 4. The window defaults to the
    first converse turn. `since_seq` overrides it — the flag's flip, a deploy, the start
    of a trial — and `window.lifetime_ask_turns` still reports the whole log, so nothing
    is hidden by narrowing it.
    """
    return {
        "measured": True,
        "recording": True,
        **session_log.route_mix(org_id=current_org_id() or None,
                                scan=max(1, min(int(scan), 20000)),
                                since_seq=since_seq),
    }


@router.get("/obs/prompt-weight")
def prompt_weight(scan: int = 5000):
    """Prompt-token spend per call site — which templates the budget goes to (PE-1).

    The prompt-economy program (roadmap §2.6) starts from a measured top-N. One
    specimen prompt measured 45% static boilerplate; this endpoint says whether
    that site is 1% or 40% of the monthly spend, for every site at once, from
    the ``caller`` attribution the provider stamps on each call. Sites served
    by backends that report no usage show ``calls_without_usage`` rather than
    reading as free; calls from before the attribution existed appear as an
    explicit ``(unattributed)`` row — the coverage of the measurement is part
    of the measurement."""
    return {
        "measured": True,
        **session_log.prompt_weight(org_id=current_org_id() or None,
                                    scan=max(1, min(int(scan), 20000))),
    }


@router.get("/obs/model-usage")
def model_usage(scan: int = 5000):
    """Per-model call counts, token totals, latency and failure rate.

    The fold has existed since the per-call record shipped, with no HTTP
    exposure — the same "reader with no route" gap this router's own history
    warns about. Exposed alongside prompt-weight: one answers "which template
    spends the tokens", the other "which model, and is it failing"."""
    return {"models": session_log.model_usage(org_id=current_org_id() or None,
                                              scan=max(1, min(int(scan), 20000)))}


@router.get("/obs/timeseries")
def obs_timeseries(group: str = "model", measure: str = "calls", kind: Optional[str] = None,
                   source: str = "events",
                   range: str = "24h", since: str = "", until: str = "",
                   limit: int = 20000):
    """Session events bucketed on the SHARED time axis, one series per group value.

    Every other fold in this router is row-windowed (`scan=N` = "the last N rows"), which
    means a quiet week and a busy hour draw the same width and no two panels can be read
    against each other. This is the time-windowed one, and `window` ships with the answer
    so a reader always knows what span the bars cover.

    Two SOURCES, and picking the wrong one draws a chart that contradicts the tile above
    it. `source=jobs` counts RUNS, attributed by the charter that owns each job kind —
    complete for every row, including history, because the attribution is derived at read
    time. `source=events` counts model CALLS, attributed by the `charter_id` stamped at
    write time — which is empty for every call made before that column existed, and for
    every call answered inline rather than inside a run. A panel headed "runs by agent"
    must ask for jobs; one headed "tokens by model" must ask for events.
    """
    from aughor.obs.timeseries import event_series, job_series
    win = resolve_window(range, since=since, until=until)
    if source == "jobs":
        payload = job_series(win, limit=max(100, min(int(limit), 50000)))
        return {"measured": True, "group": "charter", "measure": "runs",
                "scanned": payload["agent_runs"] + payload["runner_runs"],
                "attributed": payload["agent_runs"] + payload["runner_runs"],
                "coverage": 1.0 if (payload["agent_runs"] or payload["runner_runs"]) else None,
                **payload}
    try:
        return {"measured": True,
                **event_series(win, group=group, measure=measure, kind=kind,
                               org_id=current_org_id() or None,
                               limit=max(100, min(int(limit), 50000)))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/obs/usage-summary")
def usage_summary(range: str = "24h", since: str = "", until: str = "",
                  scan: int = 20000):
    """The Usage page's tiles and ranked lists over one window — calls, tokens, cost,
    fallback rate, and coverage, plus top models and top call sites.

    Coverage is a first-class number here, not a footnote: `calls_without_usage` and
    `unpriced_calls` are what stop a low total reading as a cheap week. The fallback rate
    is served from the Migration 10 column — it has been written since the failover work
    and read by nothing, so this is its first reader.
    """
    from aughor.obs.usage import price_for, rollup
    win = resolve_window(range, since=since, until=until)
    rows = Ledger.default().session_events(
        kind=session_log.LLM_CALL, org_id=current_org_id() or None,
        since=win.since, until=win.until, limit=max(100, min(int(scan), 50000)))
    report = rollup(rows, axes=("provider", "model"))
    by_site: dict[str, dict] = {}
    by_role: dict[str, dict] = {}
    fell_back = attributed_fallback = 0
    cost = 0.0
    unpriced = 0
    for e in rows:
        if e.get("fallback") is not None:
            attributed_fallback += 1
            if e.get("fallback"):
                fell_back += 1
        site = (e.get("payload") or {}).get("caller") or "(unattributed)"
        s = by_site.setdefault(site, {"caller": site, "calls": 0, "prompt_tokens": 0,
                                      "total_tokens": 0, "calls_without_usage": 0})
        s["calls"] += 1
        if e.get("total_tokens") is None:
            s["calls_without_usage"] += 1
        else:
            s["prompt_tokens"] += int(e.get("prompt_tokens") or 0)
            s["total_tokens"] += int(e.get("total_tokens") or 0)
        role = e.get("role") or "(unattributed)"
        r = by_role.setdefault(role, {"role": role, "calls": 0, "total_tokens": 0})
        r["calls"] += 1
        r["total_tokens"] += int(e.get("total_tokens") or 0)
        price = price_for(str(e.get("provider") or ""), str(e.get("model") or ""))
        if price is None:
            unpriced += 1
        else:
            cost += (int(e.get("prompt_tokens") or 0) / 1e6) * price.input_per_1m
            cost += (int(e.get("completion_tokens") or 0) / 1e6) * price.output_per_1m
    tokens = sum(int(e.get("total_tokens") or 0) for e in rows)
    no_usage = sum(1 for e in rows if e.get("total_tokens") is None)
    return {
        "measured": True,
        "window": win.as_dict(),
        "calls": len(rows),
        "tokens": tokens,
        "cost_usd": round(cost, 4),
        "unpriced_calls": unpriced,
        "cost_is_complete": unpriced == 0,
        "calls_without_usage": no_usage,
        "usage_coverage": round(1 - no_usage / len(rows), 3) if rows else None,
        # A rate whose denominator is invisible gets read as "right now". Both halves ship.
        "fallback": {"fell_back": fell_back, "of_attributed": attributed_fallback,
                     "rate": (round(fell_back / attributed_fallback, 3)
                              if attributed_fallback else None)},
        # `to_dict` already derives mean_ms and failure_rate from the counters, guarding
        # the divide-by-zero. Reaching past it for attributes that do not exist is how
        # this endpoint 500'd on its first live call — the seam was already there.
        "models": [r.to_dict() for r in report.rows[:12]],
        "sites": sorted(by_site.values(), key=lambda s: s["prompt_tokens"],
                        reverse=True)[:12],
        "roles": sorted(by_role.values(), key=lambda r: r["calls"], reverse=True)[:12],
    }


@router.get("/obs/prompt-capture")
def prompt_capture_status():
    """Is anything being recorded right now, and for how much longer?"""
    return prompt_window.status()


@router.post("/obs/prompt-capture")
def prompt_capture_open(body: _OpenCaptureRequest):
    """Open a capture window. Both bounds are clamped (see ``MAX_CALLS`` /
    ``MAX_MINUTES``) and reported back, so an operator always knows what they got
    rather than what they asked for."""
    return prompt_window.open_window(calls=body.calls, minutes=body.minutes,
                                     opened_by=body.opened_by, reason=body.reason)


@router.delete("/obs/prompt-capture")
def prompt_capture_close():
    """Close the window now. Idempotent."""
    return prompt_window.close_window()


# ── CR2: the activity stream ─────────────────────────────────────────────────────

@router.get("/activity")
def activity(kind: Optional[str] = None, agent_id: Optional[str] = None,
             conn_id: Optional[str] = None, errors_only: bool = False,
             since_seq: Optional[int] = None,
             model: Optional[str] = None, provider: Optional[str] = None,
             charter: Optional[str] = None, job_id: Optional[str] = None,
             role: Optional[str] = None, trace_id: Optional[str] = None,
             range: str = "", since: str = "", until: str = "",
             limit: int = 100):
    """A paged tail over the session log, newest first.

    `kinds` reports what the store actually contains (unfiltered), so a filter
    UI offers only vocabularies something emitted — a stream that pads its
    kind list reads as coverage that doesn't exist.

    The `model` / `provider` / `charter` / `job_id` / `role` filters are what make every
    ranked list on the usage surface a DOOR: clicking a model row has to be able to ask
    for exactly that model's calls. Before them the top-N was a dead end — the columns
    were indexed and unreachable. `range` (or explicit `since`/`until`) scopes the same
    window every other panel uses.
    """
    org_id = current_org_id() or None
    ledger = Ledger.default()
    win = resolve_window(range, since=since, until=until) if (range or since or until) else None
    rows = ledger.session_events(
        kind=kind, agent_id=agent_id, conn_id=conn_id, errors_only=errors_only,
        org_id=org_id, since_seq=since_seq, model=model, provider=provider,
        charter_id=charter, job_id=job_id, role=role, trace_id=trace_id,
        since=(win.since if win else None), until=(win.until if win else None),
        limit=max(1, min(int(limit), 500)))
    all_recent = ledger.session_events(org_id=org_id, limit=2000)
    kinds: dict[str, int] = {}
    for r in all_recent:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1

    return {"measured": True, "recording": True,
            "events": [_mark_content(e) for e in rows], "kinds": kinds,
            "window": win.as_dict() if win else None}


@router.get("/activity/stream")
async def activity_stream(request: Request, kind: Optional[str] = None,
                          agent_id: Optional[str] = None,
                          conn_id: Optional[str] = None,
                          errors_only: bool = False, since_seq: int = 0):
    """SSE tail of session events — the `/events/stream` idiom over the session
    log. `since_seq` resumes a dropped connection without losing events."""
    org_id = current_org_id() or None
    ledger = Ledger.default()

    async def _gen():
        last = int(since_seq)
        if last == 0:
            head = ledger.session_events(org_id=org_id, limit=1)
            last = head[0]["seq"] if head else 0
        yield f"data: {json.dumps({'kind': 'stream.open', 'seq': last, 'recording': True})}\n\n"
        tick = 0
        while True:
            if await request.is_disconnected():
                return
            try:
                rows = ledger.session_events(
                    kind=kind, agent_id=agent_id, conn_id=conn_id,
                    errors_only=errors_only, org_id=org_id,
                    since_seq=last, limit=200, ascending=True)
            except Exception:
                logger.warning("activity stream: session log read failed", exc_info=True)
                rows = []
            for ev in rows:
                last = max(last, ev["seq"])
                yield f"data: {json.dumps(_mark_content(ev), default=str)}\n\n"
            tick += 1
            if tick % _HEARTBEAT_EVERY == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(_POLL_SECONDS)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
