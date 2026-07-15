"""Live-wiring integration test for POST /agui/run (CK-1) — the deep-clarify pause→resume
round-trip through the REAL endpoint: the flag gate, RunAgentInput parsing, ask_request_from,
the resume routing (interruptId + payload → build_resume_stream), and the translator, all
driven via the TestClient. The composed `/ask` stream is stubbed to recorded frames so the
round-trip is deterministic — the pure translator is unit-tested in test_agui_translator.py.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _sse_events(resp) -> list[dict]:
    out: list[dict] = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except Exception:
                pass
    return out


def _fresh_input(**over) -> dict:
    body = {
        "threadId": "t1", "runId": "r1", "state": {}, "tools": [], "context": [],
        "messages": [{"id": "m1", "role": "user", "content": "why is the refund rate high?"}],
        "forwardedProps": {"connection_id": "c", "deep": True},
    }
    body.update(over)
    return body


def test_agui_run_404_when_flag_off(client: TestClient, monkeypatch):
    monkeypatch.setenv("AUGHOR_AGUI_ENDPOINT", "0")
    r = client.post("/agui/run", json=_fresh_input())
    assert r.status_code == 404          # additive + gated: off by default ⇒ the route 404s


def test_agui_run_deep_clarify_pause_then_resume(client: TestClient, monkeypatch):
    monkeypatch.setenv("AUGHOR_AGUI_ENDPOINT", "1")
    captured: dict = {}

    async def fake_ask(req, request):
        # The endpoint parsed the AG-UI input into a real AskRequest before streaming.
        captured["question"] = req.question
        captured["deep"] = req.deep
        captured["connection_id"] = req.connection_id
        yield 'data: {"type": "start"}\n\n'
        yield 'data: {"type": "route", "depth": "deep"}\n\n'
        yield "data: " + json.dumps({
            "type": "clarify_pending", "investigation_id": "invZ",
            "question": "Which reading of refund rate?", "options": ["Governed", "As asked"]}) + "\n\n"
        yield 'data: {"type": "done"}\n\n'   # AT the gate the translator returns — never reached

    monkeypatch.setattr("aughor.routers.agui.build_ask_stream",
                        lambda req, request: fake_ask(req, request))

    r = client.post("/agui/run", json=_fresh_input())
    assert r.status_code == 200, r.text
    ev = _sse_events(r)
    types = [e["type"] for e in ev]

    # The question came from the AG-UI user message; deep + connection rode in forwardedProps.
    assert captured == {"question": "why is the refund rate high?", "deep": True, "connection_id": "c"}
    # The gate surfaced BOTH as a lossless Custom AND a protocol-native interrupt outcome…
    assert any(e["type"] == "CUSTOM" and e["name"] == "aughor.clarify_pending" for e in ev)
    finished = [e for e in ev if e["type"] == "RUN_FINISHED"]
    assert len(finished) == 1
    assert finished[0]["outcome"]["type"] == "interrupt"
    assert finished[0]["outcome"]["interrupts"][0]["id"] == "invZ"
    assert finished[0]["outcome"]["interrupts"][0]["reason"] == "input_required"
    # …and the run finished AT the gate (the trailing `done` frame was never translated).
    assert types[-1] == "RUN_FINISHED" and "RUN_ERROR" not in types

    # ── resume: the client sends the interrupt id + the chosen reading ──
    resumed: dict = {}

    async def fake_resume(inv_id, request, *, feedback="", keep_subquestions=None, clarify_choice=None):
        resumed["inv_id"] = inv_id
        resumed["clarify_choice"] = clarify_choice
        yield 'data: {"type": "start"}\n\n'
        yield "data: " + json.dumps({
            "type": "headline", "headline": "Refund rate, governed reading: 18.8%."}) + "\n\n"
        yield 'data: {"type": "insight", "narrative": "Resolved to the governed reading.", "confidence": "high"}\n\n'
        yield 'data: {"type": "done", "inv_id": "invZ"}\n\n'

    monkeypatch.setattr("aughor.routers.agui.build_resume_stream",
                        lambda inv_id, request, **kw: fake_resume(inv_id, request, **kw))

    r2 = client.post("/agui/run", json={
        "threadId": "t1", "runId": "r2", "state": {}, "tools": [], "context": [],
        "messages": [], "forwardedProps": {},
        "resume": [{"interruptId": "invZ", "status": "resolved",
                    "payload": {"clarify_choice": "Governed"}}]})
    assert r2.status_code == 200, r2.text
    ev2 = _sse_events(r2)

    # The resume routed to build_resume_stream with the interrupt id + the chosen reading…
    assert resumed == {"inv_id": "invZ", "clarify_choice": "Governed"}
    # …and the resumed run translated + finished cleanly, carrying the resolved headline.
    assert [e["type"] for e in ev2][-1] == "RUN_FINISHED"
    assert any(e["type"] == "TEXT_MESSAGE_CONTENT" and "18.8%" in e.get("delta", "") for e in ev2)
