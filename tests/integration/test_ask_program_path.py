"""Stage B: plan-as-program on the live `/ask` answer path (Rec 4).

Verifies the eligibility gate, the `_stream_program` event vocabulary, and that `_stream_ask` takes the
program path on a fresh auto turn (flag on) and falls through to normal routing when the program can't answer.
The program itself is faked (a canned `ProgramResult`); no LLM is called.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import aughor.agent.program_planner as pp
from aughor.agent.program_planner import Program, ProgramResult, ProgramStep
from aughor.platform.contracts.execution import QueryResult
from aughor.routers.investigations import (
    AskRequest,
    ChatHistoryTurn,
    _program_eligible,
    _stream_ask,
    _stream_program,
)


def _events(agen) -> list[dict]:
    async def _run():
        return [json.loads(ev[6:]) async for ev in agen]   # strip the "data: " SSE prefix
    return asyncio.run(_run())


def _good_pr() -> ProgramResult:
    return ProgramResult(
        QueryResult(hypothesis_id="p", sql="SELECT n FROM t", columns=["n"], rows=[["2"]], row_count=1),
        Program(steps=[ProgramStep(id="s0", kind="data", writes="t", sql="SELECT 1 AS n")],
                rationale="count the urgent tickets"),
        {"t": "art1"}, ["s0: note"], [])


# ── eligibility gate ──────────────────────────────────────────────────────────

def test_program_eligible_flag_off(monkeypatch):
    monkeypatch.delenv("AUGHOR_PLAN_PROGRAM", raising=False)
    assert _program_eligible(AskRequest(question="q")) is False


def test_program_eligible_fresh_vs_followups(monkeypatch):
    monkeypatch.setenv("AUGHOR_PLAN_PROGRAM", "1")
    assert _program_eligible(AskRequest(question="q")) is True                        # fresh auto turn
    assert _program_eligible(AskRequest(question="q", deep=True)) is False
    assert _program_eligible(AskRequest(question="q", insight_id="x")) is False
    assert _program_eligible(AskRequest(question="q", canvas_id="x")) is False
    assert _program_eligible(AskRequest(question="q", skip_clarify=True)) is False
    assert _program_eligible(AskRequest(question="q", depth="quick")) is False
    assert _program_eligible(
        AskRequest(question="q", history=[ChatHistoryTurn(question="prior", sql="SELECT 1")])) is False


# ── _stream_program event vocabulary ──────────────────────────────────────────

def test_stream_program_emits_answer_vocab():
    evs = _events(_stream_program(_good_pr(), "c"))
    types = [e["type"] for e in evs]
    assert types == ["route", "columns", "rows", "headline", "sql", "tables_used", "program_warnings", "done"]
    route = next(e for e in evs if e["type"] == "route")
    assert route["mode"] == "program" and route["steps"] == 1
    assert next(e for e in evs if e["type"] == "columns")["columns"] == ["n"]
    assert next(e for e in evs if e["type"] == "rows")["rows"] == [["2"]]


# ── _stream_ask routing ───────────────────────────────────────────────────────

def test_ask_takes_program_path_when_eligible(monkeypatch):
    monkeypatch.setenv("AUGHOR_PLAN_PROGRAM", "1")
    monkeypatch.setenv("AUGHOR_ASK_CLARIFY", "0")             # keep the clarify LLM out of the test
    monkeypatch.setattr(pp, "answer_program", lambda q, c, **kw: _good_pr())

    req = AskRequest(question="which tickets are urgent?", connection_id="c", depth="auto")
    evs = _events(_stream_ask(req, None, "c"))
    types = [e["type"] for e in evs]
    assert "route" in types and "columns" in types and "rows" in types and "done" in types
    assert next(e for e in evs if e["type"] == "route")["mode"] == "program"


def test_ask_falls_through_when_program_has_no_answer(monkeypatch):
    monkeypatch.setenv("AUGHOR_PLAN_PROGRAM", "1")
    monkeypatch.setenv("AUGHOR_ASK_CLARIFY", "0")
    err_pr = ProgramResult(
        QueryResult(hypothesis_id="p", sql="", columns=[], rows=[], row_count=0, error="nope"),
        None, {}, [], ["planning failed"])
    monkeypatch.setattr(pp, "answer_program", lambda q, c, **kw: err_pr)

    class _FellThrough(Exception):
        pass

    import aughor.agent.ask_router as ar
    def _sentinel(*a, **k):
        raise _FellThrough()
    monkeypatch.setattr(ar, "decide_ask_route", _sentinel)     # the first step of the NORMAL path

    req = AskRequest(question="why", connection_id="c", depth="auto")
    with pytest.raises(_FellThrough):
        _events(_stream_ask(req, None, "c"))                   # reaching the normal path proves fall-through
