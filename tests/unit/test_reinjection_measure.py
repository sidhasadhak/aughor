"""4.3's OTHER half — the one repeat-counting never measured.

The pre-check called for two numbers: repeated-identical-query counts AND
chars-of-tool-results-injected-per-prompt. Only the first was run, and it came back 0%
on the explorer — a pipeline that PLANS its queries up front and therefore structurally
cannot re-ask. A denominator that could not exhibit the property is not evidence.

This measures the second number, on the population handles actually target: an agentic
loop. History is re-sent whole on every turn, so a result fetched once is transmitted
again on each later turn. That re-sending is what a handle registry removes — and it
happens at zero repeated queries.
"""
from __future__ import annotations

import pytest

from aughor.agent.tool_loop import ToolSpec, run_tool_loop
from aughor.llm.faux import FauxToolCall, set_responses
from aughor.llm.provider import LLMProvider

_PARAMS = {"type": "object", "properties": {"n": {"type": "string"}}}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AUGHOR_TOOL_LOOP_STEPS", raising=False)
    return LLMProvider(backend="faux", role="coder")


def _big_tool(size: int):
    return ToolSpec(name="fetch", description="d" * 70, parameters=_PARAMS,
                    run=lambda a: "x" * size)


def test_a_result_is_paid_for_again_on_every_later_turn(provider):
    """The mechanism, made visible. Four fetches of 1 KB each is 4 KB fetched — but the
    model is shown far more than 4 KB, because turn N carries turns 1..N-1 with it."""
    set_responses([FauxToolCall(payload={"n": str(i)}, name="fetch") for i in range(4)]
                  + ["done"])

    r = run_tool_loop(provider, "sys", "q", [_big_tool(1000)], max_steps=6)

    fetched = sum(s.result_chars for s in r.steps)
    assert fetched == 4000
    # Step 1 sees nothing; step 2 sees step 1's result; step 3 sees 1+2; step 4 sees 1+2+3.
    assert r.injected_chars > 0
    assert r.reinjection_ratio > 1.0, (
        f"results were never re-sent (ratio {r.reinjection_ratio:.2f}) — either the loop "
        "stopped carrying history or this measure is wrong")


def test_reinjection_grows_superlinearly_with_turns(provider):
    """Why this is 4.3's real argument. Doubling the turns more than doubles the bytes
    shipped, because each new turn re-sends everything before it."""
    def _run(n_steps: int) -> int:
        set_responses([FauxToolCall(payload={"n": str(i)}, name="fetch")
                       for i in range(n_steps)] + ["done"])
        return run_tool_loop(provider, "sys", "q", [_big_tool(500)],
                             max_steps=n_steps + 1).injected_chars

    short, long = _run(2), _run(4)
    assert long > short * 2, (
        f"2 steps injected {short}, 4 steps injected {long} — expected worse than linear; "
        "if it is linear, history is not accumulating and the loop has a different bug")


def test_a_turn_that_calls_no_tool_injects_nothing(provider):
    """The floor. Handles cannot help a conversation that never fetched anything."""
    set_responses(["just an answer"])

    r = run_tool_loop(provider, "sys", "q", [_big_tool(1000)])

    assert r.injected_chars == 0 and r.reinjection_ratio == 0.0


def test_small_results_do_not_justify_handles(provider):
    """The honest negative case: if results are tiny, re-injection is cheap and 4.3
    dissolves regardless of how many turns a loop takes. The measure has to be able to
    say no, or it is not a measurement."""
    set_responses([FauxToolCall(payload={"n": str(i)}, name="fetch") for i in range(4)]
                  + ["done"])

    r = run_tool_loop(provider, "sys", "q", [_big_tool(8)], max_steps=6)

    assert r.injected_chars < 200, "8-char results cannot bloat a prompt"
