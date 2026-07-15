"""AG-UI protocol seam — POST /agui/run (CK-1.1 of the CopilotKit/AG-UI adoption plan).

An ADDITIVE translator: it consumes the SAME composed `/ask` event generator the legacy
endpoint uses (`investigations.build_ask_stream`) and re-frames each Aughor SSE frame as a
standard AG-UI protocol event (via the `ag-ui-protocol` SDK), so any AG-UI client — the
`@ag-ui/client` transport (CK-1.2), CopilotKit, or another AG-UI host — can drive Aughor.

The legacy `/ask`, `/chat`, `/investigate` emission is untouched and byte-identical: this is a
separate endpoint, gated OFF by default behind the `agui.endpoint` flag (⇒ 404 when off). The
translator OWNS framing, so it also absorbs emission-order warts the legacy stream carries (e.g.
the post-`done` `insight`/`followups`): AG-UI `RunFinished` is emitted ONLY at generator
exhaustion.

Mapping (docs/COPILOTKIT_AGUI_ADOPTION_PLAN_2026-07-13.md §6):
  start ................................. (RunStarted, emitted once up-front)
  headline .............................. assistant TextMessage  (id "<run>-headline")
  insight / insight_delta ............... assistant TextMessage  (id "<run>-insight", streamed)
  sql/columns/rows/chart_*/tables_used .. ToolCall render_answer (figure args, one JSON blob)
  answer_report/report/dossier_report/
    explore_report/overview_report ...... ToolCall render_ada / render_report / render_dossier / …
  error ................................. RunError (terminal)
  done .................................. no-op (flush figure; RunFinished only at exhaustion)
  everything else (route/agent/mode/
    phase_*/hypotheses/score/followups/
    clarify*/plan_pending/…) ............ Custom{name:"aughor.<type>", value:ev} — lossless default
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ag_ui.core import (
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    CustomEvent,
    RunAgentInput,
)
from ag_ui.encoder import EventEncoder

from aughor.kernel.errors import tolerate
from aughor.kernel.flags import flag_enabled
from aughor.routers.investigations import (
    AskRequest, ChatHistoryTurn, build_ask_stream, build_resume_stream,
)

router = APIRouter()

# Aughor "figure" frames → one render_answer ToolCall payload. Maps each event type to the data
# key ON that event — note the `tables_used` event carries its list under `tables`, not `tables_used`.
_FIGURE_FIELDS = {
    "sql": "sql", "columns": "columns", "rows": "rows",
    "chart_type": "chart_type", "chart_config": "chart_config", "tables_used": "tables",
}
# Whole-payload report frames → the render_* tool the frontend adapter routes on.
_REPORT_TOOLS = {
    "answer_report": "render_ada",
    "report": "render_report",
    "dossier_report": "render_dossier",
    "explore_report": "render_explore",
    "overview_report": "render_overview",
}


def _latest_user_question(inp: RunAgentInput) -> str:
    for m in reversed(inp.messages or []):
        if getattr(m, "role", None) == "user":
            content = getattr(m, "content", "") or ""
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _forwarded(inp: RunAgentInput, key: str, default: Any = None) -> Any:
    """Aughor specifics travel in AG-UI `forwardedProps` (dict or object)."""
    fp = inp.forwarded_props
    if isinstance(fp, dict):
        return fp.get(key, default)
    return getattr(fp, key, default) if fp is not None else default


def ask_request_from(inp: RunAgentInput) -> AskRequest:
    """Build the AskRequest from AG-UI input: the latest user message is the question, Aughor
    specifics ride in forwardedProps, threadId is the session_id. Pure — unit-testable."""
    raw_hist = _forwarded(inp, "history") or []
    history: list[ChatHistoryTurn] = []
    for h in raw_hist:
        try:
            history.append(ChatHistoryTurn(**h) if isinstance(h, dict) else h)
        except Exception as exc:
            tolerate(exc, "AG-UI forwardedProps carried a malformed history item; skipping it",
                     counter="agui.bad_history_item")
    return AskRequest(
        question=_latest_user_question(inp),
        connection_id=_forwarded(inp, "connection_id") or "",
        canvas_id=_forwarded(inp, "canvas_id"),
        session_id=inp.thread_id or "",
        history=history,
        schema=_forwarded(inp, "schema"),
        depth=_forwarded(inp, "depth") or "auto",
        agent_id=_forwarded(inp, "agent_id"),
        skip_clarify=bool(_forwarded(inp, "skip_clarify", False)),
        clarify_reading=_forwarded(inp, "clarify_reading") or "",
        clarify_subject=_forwarded(inp, "clarify_subject") or "",
        clarify_source=_forwarded(inp, "clarify_source") or "",
        deep=bool(_forwarded(inp, "deep", False)),
        insight_id=_forwarded(inp, "insight_id"),
        seed_sql=_forwarded(inp, "seed_sql"),
        seed_context=_forwarded(inp, "seed_context") or "",
        hitl=bool(_forwarded(inp, "hitl", False)),
        skip_cache=bool(_forwarded(inp, "skip_cache", False)),
    )


async def translate_ask_stream(
    stream: AsyncGenerator[str, None], encoder: EventEncoder, *, thread_id: str, run_id: str,
) -> AsyncGenerator[str, None]:
    """Re-frame Aughor's `/ask` SSE stream as AG-UI events. Pure over the input stream (no I/O,
    no LLM) so it is fully unit-testable by feeding a recorded frame list. See module §6 map."""
    hl_id = f"{run_id}-headline"
    ins_id = f"{run_id}-insight"
    tool_id = uuid.uuid4().hex
    figure: dict[str, Any] = {}
    ins_open = False
    figure_flushed = False
    done_payload: dict | None = None   # the Aughor `done` event → carried into RunFinished.result

    def custom(name: str, ev: dict) -> str:
        return encoder.encode(CustomEvent(type=EventType.CUSTOM, name=f"aughor.{name}", value=ev))

    def flush_figure() -> list[str]:
        nonlocal figure_flushed
        if figure_flushed or not figure:
            return []
        figure_flushed = True
        return [
            encoder.encode(ToolCallStartEvent(
                type=EventType.TOOL_CALL_START, tool_call_id=tool_id, tool_call_name="render_answer")),
            encoder.encode(ToolCallArgsEvent(
                type=EventType.TOOL_CALL_ARGS, tool_call_id=tool_id, delta=json.dumps(figure))),
            encoder.encode(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_id)),
        ]

    yield encoder.encode(RunStartedEvent(
        type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))

    try:
        async for raw in stream:
            if not isinstance(raw, str) or not raw.startswith("data: "):
                continue
            try:
                ev = json.loads(raw[6:])
            except Exception as exc:
                tolerate(exc, "AG-UI: non-JSON SSE frame from the ask stream; skipping it",
                         counter="agui.bad_frame")
                continue
            etype = ev.get("type")

            if etype in ("start", "done"):
                # `start` is already framed as RunStarted. `done` is a no-op for RunFinished
                # (emitted only at exhaustion, so post-`done` insight/followups land BEFORE it —
                # the wart-fix) but is where the figure flushes and the done receipt is captured
                # to ride into RunFinished.result (so the AG-UI path keeps the receipt affordance).
                if etype == "done":
                    done_payload = ev
                    for e in flush_figure():
                        yield e
                continue

            if etype == "headline":
                hl = ev.get("headline", "")
                if hl:
                    yield encoder.encode(TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START, message_id=hl_id, role="assistant"))
                    yield encoder.encode(TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT, message_id=hl_id, delta=hl))
                    yield encoder.encode(TextMessageEndEvent(
                        type=EventType.TEXT_MESSAGE_END, message_id=hl_id))
                continue

            if etype == "insight_delta":
                delta = ev.get("narrative", "")   # the ask.stream_text delta frame carries `narrative`
                if delta:
                    if not ins_open:
                        ins_open = True
                        yield encoder.encode(TextMessageStartEvent(
                            type=EventType.TEXT_MESSAGE_START, message_id=ins_id, role="assistant"))
                    yield encoder.encode(TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT, message_id=ins_id, delta=delta))
                continue

            if etype == "insight":
                # Terminal narrative: close the streamed insight message, or emit it whole if no
                # deltas arrived. The full payload (anomalies/confidence) rides along as Custom.
                narrative = ev.get("narrative") or ev.get("text") or ""
                if ins_open:
                    yield encoder.encode(TextMessageEndEvent(
                        type=EventType.TEXT_MESSAGE_END, message_id=ins_id))
                    ins_open = False
                elif narrative:
                    yield encoder.encode(TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START, message_id=ins_id, role="assistant"))
                    yield encoder.encode(TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT, message_id=ins_id, delta=narrative))
                    yield encoder.encode(TextMessageEndEvent(
                        type=EventType.TEXT_MESSAGE_END, message_id=ins_id))
                yield custom("insight", ev)
                continue

            if etype in _FIGURE_FIELDS:
                figure[etype] = ev.get(_FIGURE_FIELDS[etype])
                continue

            if etype in _REPORT_TOOLS:
                rid = uuid.uuid4().hex
                yield encoder.encode(ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START, tool_call_id=rid, tool_call_name=_REPORT_TOOLS[etype]))
                yield encoder.encode(ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS, tool_call_id=rid, delta=json.dumps(ev)))
                yield encoder.encode(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=rid))
                continue

            if etype == "error":
                for e in flush_figure():
                    yield e
                yield encoder.encode(RunErrorEvent(
                    type=EventType.RUN_ERROR, message=ev.get("message", "error")))
                return

            if etype in ("clarify_pending", "plan_pending"):
                # A mid-run gate (CK-1.3). Pass it through as Custom (our adapter → the existing
                # CLARIFY_PENDING/PLAN_PENDING pause our reducer already renders) AND finish the run
                # with a protocol-native INTERRUPT outcome, so an AG-UI ecosystem client can resume
                # via `POST /agui/run` with a `resume[]`. The run pauses here — stop translating.
                yield custom(etype, ev)
                yield encoder.encode(RunFinishedEvent(
                    type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id,
                    outcome={"type": "interrupt", "interrupts": [{
                        "id": ev.get("investigation_id") or run_id,
                        "reason": "input_required" if etype == "clarify_pending" else "confirmation",
                        "message": ev.get("question") or ev.get("subject") or "",
                    }]}))
                return

            if etype:  # everything else → lossless Custom passthrough
                yield custom(etype, ev)

        # Generator exhausted — flush any un-flushed figure, close a dangling insight, finish.
        for e in flush_figure():
            yield e
        if ins_open:
            yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=ins_id))
        yield encoder.encode(RunFinishedEvent(
            type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id, result=done_payload))
    except Exception as exc:  # a translation failure must still terminate the AG-UI run cleanly
        tolerate(exc, "AG-UI translation failed mid-stream; emitting RunError", counter="agui.translate_failed")
        yield encoder.encode(RunErrorEvent(type=EventType.RUN_ERROR, message=str(exc)))


def _resume_field(item, *keys):
    """Read a field off an AG-UI resume item, tolerating dict or model (snake/camel)."""
    for k in keys:
        if isinstance(item, dict):
            if k in item:
                return item[k]
        elif hasattr(item, k):
            return getattr(item, k)
    return None


@router.post("/agui/run")
async def agui_run(inp: RunAgentInput, request: Request):
    """AG-UI-protocol translator over the unified `/ask` stream (fresh run, or a resume from an
    interrupt outcome). Additive + flag-gated."""
    if not flag_enabled("agui.endpoint"):
        raise HTTPException(status_code=404, detail="AG-UI endpoint is disabled")

    encoder = EventEncoder(accept=request.headers.get("accept"))
    run_id = inp.run_id or uuid.uuid4().hex

    if inp.resume:
        # Resume a paused investigation from an interrupt (CK-1.3): the interruptId is the
        # investigation id; the payload carries the clarify choice or the kept plan indices.
        item = inp.resume[0]
        inv_id = _resume_field(item, "interrupt_id", "interruptId") or ""
        payload = _resume_field(item, "payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        stream = build_resume_stream(
            inv_id, request,
            feedback=str(payload.get("feedback", "")),
            keep_subquestions=payload.get("keep_subquestions"),
            clarify_choice=payload.get("clarify_choice"),
        )
    else:
        ask_req = ask_request_from(inp)
        # Resolve connection/agent + apply bindings BEFORE streaming, so a binding conflict (409) or
        # a missing/disabled agent (404/409) surfaces as an HTTP error rather than mid-SSE.
        stream = build_ask_stream(ask_req, request)

    return StreamingResponse(
        translate_ask_stream(stream, encoder, thread_id=inp.thread_id or run_id, run_id=run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
