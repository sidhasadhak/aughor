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
             since_seq: Optional[int] = None, limit: int = 100):
    """A paged tail over the session log, newest first.

    `kinds` reports what the store actually contains (unfiltered), so a filter
    UI offers only vocabularies something emitted — a stream that pads its
    kind list reads as coverage that doesn't exist.
    """
    org_id = current_org_id() or None
    ledger = Ledger.default()
    rows = ledger.session_events(
        kind=kind, agent_id=agent_id, conn_id=conn_id, errors_only=errors_only,
        org_id=org_id, since_seq=since_seq, limit=max(1, min(int(limit), 500)))
    all_recent = ledger.session_events(org_id=org_id, limit=2000)
    kinds: dict[str, int] = {}
    for r in all_recent:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1

    return {"measured": True, "recording": True,
            "events": [_mark_content(e) for e in rows], "kinds": kinds}


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
