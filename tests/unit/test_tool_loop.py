"""The loop, driven through the real provider against faux — no credentials, no network.

Every test here scripts what the model does and asserts what the loop did with it. The
three recovery paths (bad tool name, bad arguments, tool raised) matter most: each is a
thing a real model does routinely, and each is a place where raising would end the turn
and throw away every step already paid for.
"""
from __future__ import annotations

import pytest

from aughor.agent.tool_loop import ToolSpec, run_tool_loop
from aughor.llm.faux import FauxToolCall, set_responses
from aughor.llm.provider import LLMProvider

_PARAMS = {"type": "object", "properties": {"sql": {"type": "string"}}}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AUGHOR_TOOL_LOOP_STEPS", raising=False)
    return LLMProvider(backend="faux", role="coder")


def _tool(name="run_sql", fn=None, calls=None):
    def _default(args):
        if calls is not None:
            calls.append(args)
        return "412"
    return ToolSpec(name=name, description=f"the {name} tool",
                    parameters=_PARAMS, run=fn or _default)


def test_a_tool_is_called_and_its_result_reaches_the_answer(provider):
    """The whole point: look something up, then answer using what came back."""
    seen: list[dict] = []
    set_responses([
        FauxToolCall(payload={"sql": "SELECT count(*) FROM orders"}, name="run_sql"),
        "there were 412 orders",
    ])

    result = run_tool_loop(provider, "sys", "how many orders?", [_tool(calls=seen)])

    assert result.answer == "there were 412 orders"
    assert result.stop_reason == "answered"
    assert seen == [{"sql": "SELECT count(*) FROM orders"}]
    assert [s.tool for s in result.steps] == ["run_sql"]


def test_answering_without_a_tool_costs_one_turn(provider):
    """Not every question needs a lookup, and the loop must not force one."""
    set_responses(["four"])

    result = run_tool_loop(provider, "sys", "what is 2+2?", [_tool()])

    assert result.answer == "four"
    assert not result.used_tools


def test_a_tool_that_raises_becomes_a_value_the_model_can_use(provider):
    """P2. 'That query failed, here is why' is something a model can act on; an
    exception ends the turn and discards the steps already paid for."""
    def _explode(args):
        raise ValueError("no such column: ordr_id")

    set_responses([
        FauxToolCall(payload={"sql": "SELECT ordr_id"}, name="run_sql"),
        "that column does not exist — did you mean order_id?",
    ])

    result = run_tool_loop(provider, "sys", "q", [_tool(fn=_explode)])

    assert result.answer is not None
    assert result.steps[0].ok is False
    assert "no such column" in result.steps[0].detail


def test_the_failure_text_is_actually_shown_to_the_model(provider):
    """Recording the failure is not the same as telling the model about it — the value
    has to reach the next prompt or the recovery is imaginary."""
    from aughor.llm import faux

    set_responses([
        FauxToolCall(payload={"sql": "bad"}, name="run_sql"),
        "recovered",
    ])
    run_tool_loop(provider, "sys", "q",
                  [_tool(fn=lambda a: (_ for _ in ()).throw(ValueError("boom")))])

    last_messages = faux.calls()[-1].kwargs["messages"]
    tool_msgs = [m for m in last_messages if m.get("role") == "tool"]
    assert tool_msgs and "boom" in tool_msgs[-1]["content"]


def test_an_unknown_tool_name_is_answered_with_the_real_ones(provider):
    """Models hallucinate tool names. Naming the real ones back costs one turn and
    almost always corrects; raising costs the whole question."""
    from aughor.llm import faux

    set_responses([
        FauxToolCall(payload={}, name="run_sqll"),
        "sorry — there were 412",
    ])

    result = run_tool_loop(provider, "sys", "q", [_tool()])

    assert result.answer == "sorry — there were 412"
    assert result.steps[0].ok is False
    tool_msgs = [m for m in faux.calls()[-1].kwargs["messages"] if m.get("role") == "tool"]
    assert "run_sql" in tool_msgs[-1]["content"]


def test_malformed_arguments_are_handed_back_for_a_retry(provider):
    """The model chose a tool and wrote the arguments badly. It is told exactly that."""
    set_responses([
        FauxToolCall(payload="{not valid json", name="run_sql"),
        "412",
    ])

    result = run_tool_loop(provider, "sys", "q", [_tool()])

    assert result.answer == "412"
    assert result.steps[0].ok is False


def test_the_budget_ends_the_loop_instead_of_running_forever(provider):
    """A model that keeps calling tools must stop, and the turn must say so rather than
    present a half-derived guess as a conclusion."""
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")] * 12)

    result = run_tool_loop(provider, "sys", "q", [_tool()], max_steps=3)

    assert result.answer is None
    assert result.stop_reason == "budget"
    assert len(result.steps) == 3


def test_the_budget_comes_from_the_model_profile_not_a_constant(provider, monkeypatch):
    """ModelProfile exists so capability knobs stop coming back as module constants."""
    import aughor.agent.tool_loop as loop_mod
    from aughor.llm.profile import profile_for

    assert profile_for("coder").tool_loop_steps >= 1
    monkeypatch.setattr(loop_mod, "_budget", lambda p: 1)
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")] * 4)

    result = run_tool_loop(provider, "sys", "q", [_tool()])

    assert len(result.steps) == 1
    assert result.stop_reason == "budget"


def test_each_step_echoes_its_tool_call_so_the_wire_stays_legal(provider):
    """An OpenAI-compatible backend rejects a `role="tool"` message that answers no
    call, so a loop that sends only results dies on the SECOND turn — invisible in a
    one-step test."""
    from aughor.llm import faux

    set_responses([
        FauxToolCall(payload={"sql": "a"}, name="run_sql"),
        FauxToolCall(payload={"sql": "b"}, name="run_sql"),
        "done",
    ])

    run_tool_loop(provider, "sys", "q", [_tool()])

    messages = faux.calls()[-1].kwargs["messages"]
    assistant = [m for m in messages if m.get("role") == "assistant"]
    tools = [m for m in messages if m.get("role") == "tool"]
    assert len(assistant) == len(tools) == 2
    for a, t in zip(assistant, tools):
        assert a["tool_calls"][0]["id"] == t["tool_call_id"]


def test_the_model_sees_what_it_already_learned(provider):
    """Without history the model re-decides from the same two messages and picks the
    same tool forever — the loop that spends its budget re-running one query."""
    from aughor.llm import faux

    set_responses([
        FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"),
        "412 orders",
    ])
    run_tool_loop(provider, "sys", "how many orders?", [_tool()])

    roles = [m["role"] for m in faux.calls()[-1].kwargs["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]


# ── silence is not an answer ──────────────────────────────────────────────────
# Found live: a question whose tables were sitting in the `list_tables` result the
# model had just been handed came back "I ran out of steps" after ONE step of a
# budget of eight. The model had chosen no tool and written nothing, and the loop
# returned that empty string as a successful answer.


def test_a_silent_turn_is_nudged_rather_than_accepted_as_an_answer(provider):
    """Neither a tool call nor text is a stall, not a conclusion."""
    set_responses([
        FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"),
        "",                                   # silence — used to end the turn
        "there were 412 orders",               # what the nudge recovers
    ])

    result = run_tool_loop(provider, "sys", "how many orders?", [_tool()])

    assert result.answer == "there were 412 orders"
    assert result.stop_reason == "answered"


def test_whitespace_only_counts_as_silence(provider):
    set_responses(["   \n\t  ", "a real answer"])

    result = run_tool_loop(provider, "sys", "q", [_tool()])

    assert result.answer == "a real answer"


def test_the_nudge_is_recorded_so_the_turn_cost_stays_honest(provider):
    """A step the turn paid for that no step list showed is a cost that vanished."""
    set_responses(["", "answered at last"])

    result = run_tool_loop(provider, "sys", "q", [_tool()])

    assert len(result.steps) == 1
    assert result.steps[0].ok is False
    assert "neither a tool call nor text" in result.steps[0].detail


def test_a_second_silence_ends_the_turn_as_silent_not_as_budget(provider):
    """Two silences is a real stall — but calling it "budget" tells the user to
    narrow a question that was never the problem."""
    set_responses(["", "", "never reached"])

    result = run_tool_loop(provider, "sys", "q", [_tool()])

    assert result.answer is None
    assert result.stop_reason == "silent"          # NOT "budget"
    assert len(result.steps) == 1                  # one nudge, then it stops


def test_the_nudge_does_not_let_the_turn_exceed_its_budget(provider):
    """The recovery must not become an extra step the ceiling does not cover."""
    set_responses(["", *[FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")] * 20])

    result = run_tool_loop(provider, "sys", "q", [_tool()], max_steps=3)

    assert result.stop_reason == "budget"
    assert len(result.steps) <= 3
