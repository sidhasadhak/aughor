"""The quick turn's closing prose, driven live through /ask, is held to its own rows.

The live failure this pins: asked for flights per route, the converse body ran the
query, streamed the real rows to the chart — and then closed with a markdown table of
numbers none of those rows contained. Everything else on screen was right; only the
sentence the user actually reads was invented.

Driven through the real router and the real loop against the faux backend, so what is
asserted is the path production takes.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def _frames(client: TestClient, body: dict) -> list[dict]:
    out: list[dict] = []
    with client.stream("POST", "/ask", json=body) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line and line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


@pytest.fixture
def one_query_turn(monkeypatch):
    """The converse `run_sql` tool, returning a fixed result the way a real query does —
    including the `rows` frame the chart is drawn from and the guard now reads."""
    rows = [["ZRH-LHR", 28], ["GVA-LHR", 42], ["ZRH-CDG", 35]]

    from aughor.agent import converse_tools as ct
    real = ct.converse_tools

    def _tools(connection_id, **kwargs):
        # `**kwargs`, not a spelled-out signature. This double named every keyword the
        # real `converse_tools` took, so the day VA-9c added `agent` the stub raised
        # TypeError, the /ask stream died before any frame, and both tests in this file
        # failed on `StopIteration` from `next(... "headline")` — a stack trace that
        # points at the assertion and says nothing about the cause. Forwarding whatever
        # the caller passes keeps the double faithful to a signature that will grow again.
        specs = [s for s in real(connection_id, **kwargs) if s.name != "run_sql"]
        emit = kwargs.get("emit")

        def _run(args):
            if emit is not None:
                emit("sql", {"sql": "SELECT route_id, n FROM flights GROUP BY 1"})
                emit("columns", {"columns": ["route_id", "n_flights"]})
                emit("rows", {"rows": rows})
            return {"columns": ["route_id", "n_flights"], "rows": rows}

        from aughor.agent.tool_loop import ToolSpec
        specs.append(ToolSpec(name="run_sql", description="Run a guarded query.",
                              parameters={"type": "object",
                                          "properties": {"sql": {"type": "string"}}},
                              run=_run))
        return specs

    monkeypatch.setattr(ct, "converse_tools", _tools)
    return rows


def test_a_fabricated_table_never_reaches_the_headline(
        client, builtin_conn_id, one_query_turn, faux_llm, monkeypatch):
    """The live case, end to end: the model queries, then writes numbers the result
    does not contain. The turn must not present them."""
    from aughor.llm.faux import FauxToolCall

    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")
    faux_llm.set_responses([
        FauxToolCall(payload={"sql": "SELECT route_id, count(*) FROM flights GROUP BY 1"},
                     name="run_sql"),
        # …and then invents the table (the real answer said 108 / 96 / 84).
        "Flights per route: ZRH-LHR 108, GVA-LHR 96, ZRH-CDG 84.",
        # the re-ask, still ungrounded — so the claim must be withheld, not shipped
        "Flights per route: ZRH-LHR 108, GVA-LHR 96, ZRH-CDG 84.",
    ])

    frames = _frames(client, {
        "question": "give me route wise number of flights",
        "connection_id": builtin_conn_id,
        "depth": "quick",
        "session_id": "grounding-live",
    })

    headline = next(f for f in frames if f.get("type") == "headline")["headline"]
    assert "108" not in headline and "96" not in headline, headline
    assert "could not ground" in headline

    # The guard is visible, not silent — same receipt chain every other guard uses.
    receipts = [f for f in frames if f.get("type") == "guard_receipt"]
    assert any(r.get("guard") == "numeric grounding" for r in receipts), receipts
    fired = next(r for r in receipts if r.get("guard") == "numeric grounding")
    assert "108" in fired["detail"]

    # And the REAL result still reached the user — the rows are what the guard defends.
    rows = next(f for f in frames if f.get("type") == "rows")["rows"]
    assert rows == one_query_turn


def test_a_faithful_answer_is_untouched(
        client, builtin_conn_id, one_query_turn, faux_llm, monkeypatch):
    """The guard removes false claims; it must not disturb a true one."""
    from aughor.llm.faux import FauxToolCall

    monkeypatch.setenv("AUGHOR_ASK_CONVERSE", "1")
    faithful = "GVA-LHR leads with 42 flights, then ZRH-CDG at 35 and ZRH-LHR at 28."
    faux_llm.set_responses([
        FauxToolCall(payload={"sql": "SELECT route_id, count(*) FROM flights GROUP BY 1"},
                     name="run_sql"),
        faithful,
    ])

    frames = _frames(client, {
        "question": "give me route wise number of flights",
        "connection_id": builtin_conn_id,
        "depth": "quick",
        "session_id": "grounding-live-ok",
    })

    assert next(f for f in frames if f.get("type") == "headline")["headline"] == faithful
    assert not [f for f in frames if f.get("type") == "guard_receipt"
                and f.get("guard") == "numeric grounding"]
