"""RC-2 — a conversational turn is filed, so the conversation is whole.

`_answer_core` writes a history row for every turn that runs a query, and
returns its id on the inner `done`. A converse turn that calls no tool — the
"are you sure?", the follow-up answered from the briefing or from context —
used to write nothing at all.

On the web that is invisible: the client holds the thread until a reload. On
every other door it is a hole. Slack keeps no client-side copy, so the
conversation a mention files under loses exactly the follow-ups that make it a
conversation, and the next turn rebuilds its history from a record missing the
one before it. Seen live in a thread before this was fixed.

These drive the REAL `_stream_converse` against a stubbed `converse()` and read
the history back, so the test fails if the filing is removed OR if it is written
somewhere the conversation cannot see.
"""
from __future__ import annotations

import asyncio
import json
import types

import pytest

from aughor.db.history import chat_session_turn_ids, get_investigation
from aughor.routers import investigations as inv

SESSION = "slack:C0TEST:1788000000.000100"


def _result(answer: str, steps=()):
    return types.SimpleNamespace(answer=answer, steps=list(steps), stop_reason="answered",
                                 injected_chars=0, reinjection_ratio=0.0)


@pytest.fixture
def offline(monkeypatch):
    """No provider, no prior-answer lookups — just the body under test."""
    monkeypatch.setattr(inv, "build_history_section", lambda h: "")
    monkeypatch.setattr(inv, "build_prior_answers_section", lambda a: "")
    monkeypatch.setattr(inv, "resolve_prior_answers", lambda *a, **k: [])
    monkeypatch.setattr("aughor.agent.converse_tools.ground_answer_numbers",
                        lambda answer, rows, question="": (answer, None))


def _drive(question: str, session_id: str = SESSION) -> list[dict]:
    """Run one converse turn and collect its frames."""
    async def _go():
        return [json.loads(chunk.split("data: ", 1)[1])
                for chunk in [c async for c in inv._stream_converse(question, "fixture", [],
                                                                    session_id=session_id)]
                if chunk.startswith("data: ")]
    return asyncio.run(_go())


def test_a_tool_less_turn_is_filed_under_its_conversation(offline, monkeypatch):
    monkeypatch.setattr("aughor.agent.converse_tools.converse",
                        lambda *a, **k: _result("Yes — the dip is inside normal variance."))

    before = set(chat_session_turn_ids(SESSION))
    frames = _drive("are you sure?")

    done = next(f for f in frames if f["type"] == "done")
    new = set(chat_session_turn_ids(SESSION)) - before
    assert len(new) == 1, "a turn answered without a tool must still join its conversation"

    # The row IS the one the turn reports, and it reads back as what the user saw.
    turn_id = new.pop()
    assert done["inv_id"] == turn_id
    row = get_investigation(turn_id)
    assert row["headline"] == "Yes — the dip is inside normal variance."
    # No SQL ran, so nothing claims a receipt.
    assert done["has_receipt"] is False


def test_a_turn_that_called_a_tool_is_not_filed_twice(offline, monkeypatch):
    """The tool's own row is the better one — it carries the SQL and the receipt.
    Two rows for one exchange would double-count every reader that counts turns."""
    monkeypatch.setattr("aughor.agent.converse_tools.converse",
                        lambda *a, **k: _result("East leads.", steps=[
                            types.SimpleNamespace(tool="answer_question", arguments={}, ok=True,
                                                  detail="", result_chars=10)]))

    # Stand in for `_answer_core`'s inner turn: it emits `done` with its row id,
    # which `_forward` keeps as the turn's identity.
    def _fake_converse(conn, q, *, tool_emit=None, on_step=None, **k):
        if on_step:
            on_step(types.SimpleNamespace(tool="answer_question", arguments={}, ok=True,
                                          detail="", result_chars=10))
        if tool_emit:
            tool_emit("sql", {"sql": "SELECT 1"})
            tool_emit("done", {"inv_id": "inner-row-1", "has_receipt": True})
        return _result("East leads.")

    monkeypatch.setattr("aughor.agent.converse_tools.converse", _fake_converse)

    before = set(chat_session_turn_ids(SESSION))
    frames = _drive("which region leads?")

    done = next(f for f in frames if f["type"] == "done")
    assert done["inv_id"] == "inner-row-1"
    assert done["has_receipt"] is True
    assert set(chat_session_turn_ids(SESSION)) == before, "the inner turn's row is the only one"


def test_filing_is_best_effort_and_never_costs_the_answer(offline, monkeypatch):
    """The answer has already been streamed by the time the row is written; a
    failed write must not turn a delivered answer into an error frame."""
    monkeypatch.setattr("aughor.agent.converse_tools.converse",
                        lambda *a, **k: _result("Yes."))
    monkeypatch.setattr(inv, "save_chat_turn",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("history is locked")))

    frames = _drive("are you sure?")
    assert [f["type"] for f in frames if f["type"] == "error"] == []
    assert next(f for f in frames if f["type"] == "headline")["headline"] == "Yes."
    assert next(f for f in frames if f["type"] == "done")["inv_id"] == ""
