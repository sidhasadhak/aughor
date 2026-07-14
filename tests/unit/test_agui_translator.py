"""Hermetic tests for the AG-UI translator (aughor/routers/agui.py, CK-1.1).

`translate_ask_stream` is PURE over the input SSE stream — no LLM, no DB — so we feed recorded
Aughor `/ask` event sequences and assert the AG-UI event order + shapes
(docs/COPILOTKIT_AGUI_ADOPTION_PLAN_2026-07-13.md §6). No live server needed.
"""
import asyncio
import json

from ag_ui.encoder import EventEncoder
from aughor.routers.agui import translate_ask_stream


def _sse(ev: dict) -> str:
    return "data: " + json.dumps(ev) + "\n\n"


async def _agen(frames):
    for f in frames:
        yield _sse(f)


def _run(frames):
    """Drive the translator over recorded frames; return the AG-UI event dicts in order."""
    async def collect():
        enc = EventEncoder()
        out = []
        async for chunk in translate_ask_stream(_agen(frames), enc, thread_id="t1", run_id="r1"):
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    out.append(json.loads(line[6:]))
        return out
    return asyncio.run(collect())


def _types(events):
    return [e["type"] for e in events]


def test_quick_happy_path_order_and_run_finished_last():
    frames = [
        {"type": "start"},
        {"type": "route", "depth": "quick"},
        {"type": "sql", "sql": "SELECT 1"},
        {"type": "columns", "columns": ["a"]},
        {"type": "rows", "rows": [[1]]},
        {"type": "headline", "headline": "One."},
        {"type": "chart_type", "chart_type": "bar"},
        {"type": "tables_used", "tables": ["t"]},   # NOTE: data field is `tables`, event type is `tables_used`
        {"type": "done", "has_receipt": True, "inv_id": "inv1"},
        {"type": "insight", "narrative": "Because reasons.", "confidence": "high"},
        {"type": "followups", "questions": ["next?"]},
    ]
    ev = _run(frames)
    t = _types(ev)
    assert t[0] == "RUN_STARTED"
    assert t[-1] == "RUN_FINISHED"          # post-done insight/followups absorbed BEFORE finish
    assert "RUN_ERROR" not in t
    assert {"TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"} <= set(t)
    starts = [e for e in ev if e["type"] == "TOOL_CALL_START"]
    assert len(starts) == 1 and starts[0]["toolCallName"] == "render_answer"
    customs = {e["name"] for e in ev if e["type"] == "CUSTOM"}
    assert {"aughor.route", "aughor.insight", "aughor.followups"} <= customs
    args = [e for e in ev if e["type"] == "TOOL_CALL_ARGS"]
    figure = json.loads(args[0]["delta"])
    assert figure["sql"] == "SELECT 1" and figure["columns"] == ["a"] and figure["chart_type"] == "bar"
    assert figure["tables_used"] == ["t"]   # the tables_used event's `tables` list, keyed for round-trip
    # the done receipt rides into RunFinished.result so the AG-UI path keeps the receipt affordance
    finished = [e for e in ev if e["type"] == "RUN_FINISHED"][0]
    assert finished["result"]["has_receipt"] is True and finished["result"]["inv_id"] == "inv1"


def test_insight_delta_streams_into_one_message():
    frames = [
        {"type": "start"},
        {"type": "insight_delta", "narrative": "Be"},
        {"type": "insight_delta", "narrative": "cause"},
        {"type": "insight", "narrative": "Because.", "confidence": "high"},
        {"type": "done"},
    ]
    ev = _run(frames)
    contents = [e for e in ev if e["type"] == "TEXT_MESSAGE_CONTENT" and e["messageId"] == "r1-insight"]
    assert [c["delta"] for c in contents] == ["Be", "cause"]   # streamed, not re-emitted whole
    ends = [e for e in ev if e["type"] == "TEXT_MESSAGE_END" and e["messageId"] == "r1-insight"]
    assert len(ends) == 1
    assert _types(ev)[-1] == "RUN_FINISHED"


def test_error_is_terminal_no_run_finished():
    frames = [
        {"type": "start"},
        {"type": "sql", "sql": "SELECT bad"},
        {"type": "error", "message": "boom"},
    ]
    ev = _run(frames)
    t = _types(ev)
    assert t[-1] == "RUN_ERROR"          # terminal — no RunFinished after an error
    assert "RUN_FINISHED" not in t
    assert [e for e in ev if e["type"] == "RUN_ERROR"][0]["message"] == "boom"


def test_deep_report_maps_to_render_ada():
    frames = [
        {"type": "start"},
        {"type": "answer_report", "headline": "Root cause", "phases": []},
        {"type": "done"},
    ]
    ev = _run(frames)
    starts = [e for e in ev if e["type"] == "TOOL_CALL_START"]
    assert any(s["toolCallName"] == "render_ada" for s in starts)
    assert _types(ev)[-1] == "RUN_FINISHED"


def test_unknown_event_is_lossless_custom():
    # the risk-register guarantee: an unmapped Aughor event survives as aughor.<type> Custom.
    ev = _run([{"type": "start"}, {"type": "playbook_refs", "refs": ["p1"]}, {"type": "done"}])
    custom = [e for e in ev if e["type"] == "CUSTOM" and e["name"] == "aughor.playbook_refs"]
    assert len(custom) == 1 and custom[0]["value"]["refs"] == ["p1"]
