"""CA-3 — the door: a deep `/ask` turn is served by the ANALYST body when the
converse experiment is on, and its frames stream in the deep path's own vocabulary.

Hermetic: the faux backend scripts the loop's tool choices; the intake and synthesis
nodes are faked at the seam (their own machinery has its own tests); the phase body
is faked to a canned phase so the wire contract — route(body=analyst) → start →
phase_complete… → converse_step… → answer_report → done(body=analyst) — is what this
file pins, not the phases' internals. With the flag off the same request must reach
the phase script exactly as before (§5's ladder: the library stays the fallback).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def _frames(client: TestClient, body: dict) -> list[dict]:
    out: list[dict] = []
    with client.stream("POST", "/ask", json=body) as r:
        assert r.status_code == 200, r.text
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    out.append(json.loads(line[5:].strip()))
                except Exception:
                    continue
    return out


@pytest.fixture
def analyst_seams(monkeypatch):
    """Fake the intake / phase / synthesis nodes at their public seams."""

    def _fake_intake(state, conn=None):
        return {"_ada_intake": {
            "metric_label": "revenue", "metric_sql": "SUM(total_amount)",
            "metric_table": "ecommerce.orders", "date_column": "ecommerce.orders.order_date",
            "observation_start": "2024-12-01", "observation_end": "2024-12-31",
            "observation_label": "December 2024",
            "comparison_start": "2024-11-01", "comparison_end": "2024-11-30",
            "comparison_label": "November 2024",
            "dimensions": ["ecommerce.orders.payment_method"],
            "data_understanding_block": "",
        }, "investigation_phases": [{
            "phase_id": "intake", "phase_name": "Question Intake", "phase_icon": "🎯",
            "status": "complete", "summary": "spec resolved", "findings": [],
        }]}

    def _fake_decompose(state, conn):
        phases = state.get("investigation_phases", [])
        return {"investigation_phases": phases + [{
            "phase_id": "decomposition", "phase_name": "Decomposition", "phase_icon": "🧭",
            "status": "complete", "summary": "card carries the December move.",
            "findings": [{"finding_id": "d1", "title": "Revenue by payment method",
                          "sql": "SELECT 1", "columns": ["payment_method", "revenue"],
                          "rows": [["card", 100]], "row_count": 1, "error": None,
                          "interpretation": "card leads", "key_numbers": [],
                          "chart_type": "bar", "stat_note": None, "is_significant": True}],
        }]}

    def _fake_synthesize(state):
        return {"answer_report": {
            "headline": "Card carries the December move",
            "executive_summary": "One segment carries it.",
            "metric": "revenue", "observation_period": "Dec 2024",
            "comparison_basis": "Nov 2024", "total_change_label": "+12%",
            "phases": state.get("investigation_phases") or [],
            "attribution_waterfall": [], "confidence": "MEDIUM",
            "confidence_justification": "one agreeing slice",
            "recommendations": [], "data_gaps": [],
        }}

    monkeypatch.setattr("aughor.agent.investigate.ada_intake", _fake_intake)
    monkeypatch.setattr("aughor.agent.investigate.ada_decompose", _fake_decompose)
    monkeypatch.setattr("aughor.agent.investigate.ada_synthesize", _fake_synthesize)


def test_deep_turn_streams_through_the_analyst(client, builtin_conn_id,
                                               analyst_seams, faux_llm, monkeypatch):
    from aughor.llm.faux import FauxToolCall

    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")
    faux_llm.set_responses([
        FauxToolCall(payload={"dimension": "payment_method"}, name="decompose"),
        "Card payments carry the December rise — about +12% of the move.",
    ])

    frames = _frames(client, {
        "question": "why did revenue move in December?",
        "connection_id": builtin_conn_id,
        "depth": "deep",
        "session_id": "ca3-analyst-door",
    })
    types = [f.get("type") for f in frames]

    route = next(f for f in frames if f.get("type") == "route")
    assert route.get("body") == "analyst", route
    assert route.get("depth") == "deep"

    assert types.count("phase_complete") == 2, types      # intake + decomposition
    assert "converse_step" in types
    step = next(f for f in frames if f.get("type") == "converse_step")
    assert step["tool"] == "decompose"

    report = next(f for f in frames if f.get("type") == "answer_report")
    assert report["answer_report"]["headline"] == "Card carries the December move"
    assert report["query_mode"] == "investigate"

    done = next(f for f in frames if f.get("type") == "done")
    assert done.get("body") == "analyst"
    assert done.get("stop_reason") == "answered"
    # Frame order: every phase and step lands BEFORE the report; the report before done.
    assert max(i for i, t in enumerate(types) if t == "phase_complete") \
        < types.index("answer_report") < types.index("done")

    # The run is FILED: a real investigation row, under the session it was asked in.
    from aughor.db.history import get_investigation
    start = next(f for f in frames if f.get("type") == "start")
    inv = get_investigation(start["investigation_id"])
    assert inv is not None and inv.get("status") == "complete"
    assert inv["report"]["headline"] == "Card carries the December move"


def test_flag_off_keeps_the_phase_script(client, builtin_conn_id, monkeypatch):
    """§5's ladder: with the experiment off, a deep turn reaches the phase script —
    the analyst body must not have replaced the fallback."""
    monkeypatch.delenv("AUGHOR_ASK_CONVERSE", raising=False)
    seen = {}

    async def _fake_job_stream(question, conn_id, request, **kw):
        seen["question"] = question
        yield 'data: {"type": "done"}\n\n'

    monkeypatch.setattr("aughor.routers.investigations._investigation_job_streamed",
                        _fake_job_stream)

    frames = _frames(client, {
        "question": "why did revenue move in December?",
        "connection_id": builtin_conn_id,
        "depth": "deep",
    })
    types = [f.get("type") for f in frames]

    assert seen.get("question") == "why did revenue move in December?", (
        "the phase script (the job stream) must serve a deep turn when the flag is off")
    route = next(f for f in frames if f.get("type") == "route")
    assert route.get("body") is None, "no analyst/converse body claim with the flag off"
    assert "done" in types
