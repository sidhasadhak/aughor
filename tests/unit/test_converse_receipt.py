"""The `ask.converse` graduation receipt — a whole session, scripted, offline.

The plan's exit criterion for this flag is a ten-turn session that holds together, run
in CI with no credentials. A single-turn test proves the wiring; it does not prove the
thing the flag is actually asking about, which is whether a CONVERSATION survives its
own length — history accumulating turn after turn, tools called and recovered from,
the budget respected each time.

Everything here runs through the real provider against the faux backend, so what is
asserted is the code path production takes, not a mock of it.
"""
from __future__ import annotations

import pytest

from aughor.agent import converse_tools as ct
from aughor.llm.faux import FauxToolCall, calls, set_responses
from aughor.llm.provider import LLMProvider


class _Result:
    def __init__(self, rows=None, caveats=None):
        self.sql = ""
        self.columns = ["n"]
        self.rows = rows if rows is not None else [[412]]
        self.row_count = len(self.rows)
        self.error = None
        self.caveats = caveats or []


@pytest.fixture
def session(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AUGHOR_TOOL_LOOP_STEPS", raising=False)
    schema = "TABLE: analytics.orders\n  order_id  BIGINT\n  total  DOUBLE\n"
    monkeypatch.setattr(ct, "_connection",
                        lambda cid: type("C", (), {"get_schema": staticmethod(lambda: schema)})())
    monkeypatch.setattr("aughor.sql.executor.execute_guarded", lambda *a, **k: _Result())
    return LLMProvider(backend="faux", role="coder")


_QUESTIONS = [
    "how many orders are there?",
    "what tables do you have?",
    "describe the orders table",
    "what is total revenue?",
    "how many orders last month?",
    "which table holds revenue?",
    "what is the average order value?",
    "show me the order columns again",
    "how many rows in orders?",
    "summarise what you found",
]


def test_ten_turn_session_holds_together(session):
    """The receipt. Ten questions, each answered, tools used throughout, no turn
    leaking state into the next."""
    answers = []
    for i, question in enumerate(_QUESTIONS):
        # Alternate tool-using and direct answers: a session is not uniform, and a
        # loop that only works when every turn calls a tool is not a conversation.
        if i % 2 == 0:
            set_responses([
                FauxToolCall(payload={"sql": f"SELECT {i}"}, name="run_sql"),
                f"answer {i}",
            ])
        else:
            set_responses([f"answer {i}"])

        result = ct.converse("c1", question, provider=session)
        answers.append(result.answer)

    assert answers == [f"answer {i}" for i in range(10)], "a turn failed mid-session"


def test_each_turn_starts_from_its_own_question(session):
    """Turn N must not inherit turn N-1's history. A conversation is a sequence of
    turns; a loop that accumulates across them would grow the prompt without bound and
    let an earlier tool result answer a later, unrelated question."""
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"), "first"])
    ct.converse("c1", "first question", provider=session)

    set_responses(["second"])
    ct.converse("c1", "second question", provider=session)

    last = calls()[-1].kwargs["messages"]
    assert [m["role"] for m in last] == ["system", "user"]
    assert last[1]["content"] == "second question"


def test_a_session_recovers_from_a_bad_turn_and_continues(session):
    """Ten good turns is not the interesting claim. A session that survives a model
    mistake in the middle is."""
    set_responses([
        FauxToolCall(payload={}, name="no_such_tool"),
        FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"),
        "recovered and answered",
    ])

    result = ct.converse("c1", "q", provider=session)

    assert result.answer == "recovered and answered"
    assert [s.ok for s in result.steps] == [False, True]


def test_the_session_never_exceeds_its_budget_per_turn(session):
    """Ten turns must not become ten runaway loops. The ceiling is per turn, and the
    receipt is worthless if one turn can spend the day's allowance."""
    budget = 3
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")] * 40)

    for _ in range(4):
        result = ct.converse("c1", "q", provider=session, max_steps=budget)
        assert len(result.steps) <= budget
        assert result.stop_reason == "budget"


def test_every_turn_costs_at_most_one_request_per_step(session):
    """The free-tier arithmetic the plan cares about: a turn's REQUEST count is its step
    count, not some multiple of it. A hidden retry per step would quietly quadruple the
    day's spend."""
    before = len(calls())
    set_responses([
        FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"),
        "done",
    ])

    result = ct.converse("c1", "q", provider=session)

    requests = len(calls()) - before
    assert requests == len(result.steps) + 1, (
        f"{len(result.steps)} tool steps + 1 answering turn should be "
        f"{len(result.steps) + 1} requests, was {requests}")
