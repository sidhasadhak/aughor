"""The transport learns to take a tool call — Layer 3's first prerequisite.

Until now the provider could only ask for a *shape*: `complete()` hands instructor a
`response_model` and gets a validated object back. An agent turn is a different
question — "what should I do next?" — whose answer may be "call this tool with these
arguments". Structured output and tool choice are the same wire feature pointed at
opposite purposes, and no tool-calling path existed anywhere in the repo.

These tests drive the REAL provider through the faux backend, so they assert the
actual code path a converse loop will take, with zero provider credentials in the
environment. That is the property Layer 0 was built for; the tests exist partly to
prove `complete_with_tools` did not route around it.
"""
from __future__ import annotations

import pytest

from aughor.llm.faux import FauxToolCall, set_responses
from aughor.llm.provider import LLMProvider, ToolTurn, _parse_tool_turn

_TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": "Execute a guarded SQL query.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}},
    },
}]


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    return LLMProvider(backend="faux", role="coder")


def test_model_choosing_a_tool_is_readable_as_a_choice(provider):
    """The headline. A turn that picks a tool must arrive as a decision, not silence."""
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")])

    turn = provider.complete_with_tools("sys", "how many orders?", _TOOLS)

    assert turn.chose_tool
    assert turn.tool_call is not None
    assert turn.tool_call.name == "run_sql"
    assert turn.tool_call.arguments == {"sql": "SELECT 1"}
    assert turn.text is None


def test_model_answering_in_prose_is_not_mistaken_for_a_tool_call(provider):
    """The other branch: an ordinary reply must not read as a tool choice."""
    set_responses(["there were 412 orders"])

    turn = provider.complete_with_tools("sys", "how many orders?", _TOOLS)

    assert not turn.chose_tool
    assert turn.text == "there were 412 orders"


def test_the_tools_array_actually_reaches_the_provider(provider):
    """Check the claim, not something adjacent to it.

    A reply comes back whether or not the tools were sent, so asserting on the reply
    proves nothing about routing. This asserts the kwargs the transport received —
    the adapter-fidelity trap named in the deepagents risk list.
    """
    from aughor.llm import faux

    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")])
    provider.complete_with_tools("sys", "q", _TOOLS)

    sent = faux.calls()[-1].kwargs
    assert sent["tools"] == _TOOLS
    assert sent["tool_choice"] == "auto"
    # An agent turn asks a question, not for a shape. A response_model here would put
    # instructor back in the loop and silently turn the tool call into a validation.
    assert sent["response_model"] is None


def test_which_tool_was_chosen_is_asserted_not_assumed(provider):
    """With several tools offered, the loop must learn WHICH one the model took."""
    tools = _TOOLS + [{
        "type": "function",
        "function": {"name": "search_history", "description": "Past findings.",
                     "parameters": {"type": "object", "properties": {}}},
    }]
    set_responses([FauxToolCall(payload={"query": "margin"}, name="search_history")])

    turn = provider.complete_with_tools("sys", "have we looked at margin?", tools)

    assert turn.tool_call is not None
    assert turn.tool_call.name == "search_history"


def test_malformed_arguments_are_a_value_not_a_crash():
    """P2 — failures are values. A model that picks a tool and then emits broken JSON
    has still made a decision, and a loop told nothing at all would read the turn as
    silence and answer from thin air."""
    raw = _fake_completion(name="run_sql", arguments="{'sql': not json}")

    turn = _parse_tool_turn(raw)

    assert not turn.chose_tool
    assert turn.malformed is not None
    assert "run_sql" in turn.malformed


def test_non_object_arguments_are_malformed_too():
    """`json.loads("[1,2]")` succeeds and is useless as kwargs — valid JSON is not the
    same claim as valid arguments."""
    turn = _parse_tool_turn(_fake_completion(name="run_sql", arguments="[1, 2]"))

    assert turn.malformed is not None
    assert "not an object" in turn.malformed


def test_a_tool_call_is_read_before_empty_content():
    """The TOOLS-mode shape sets content to None and puts the payload on the tool call.
    Reading content first sees an empty answer and reports silence where there was a
    decision — the bug this ordering exists to prevent."""
    raw = _fake_completion(name="run_sql", arguments='{"sql": "SELECT 1"}', content=None)

    assert _parse_tool_turn(raw).chose_tool


def test_the_turn_is_metered(provider, monkeypatch):
    """A loop that runs untracked is how a free-tier allowance disappears with no line
    item. A tool-choosing turn costs the same tokens as an answering one."""
    from aughor.kernel import metering

    recorded: list[tuple] = []
    monkeypatch.setattr(metering, "record_llm",
                        lambda pt, ct, ms: recorded.append((pt, ct, ms)))
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql")])

    provider.complete_with_tools("sys", "q", _TOOLS)

    assert recorded, "a tool-calling turn was not metered"
    assert recorded[0][0] > 0 and recorded[0][1] > 0


def test_anthropic_binding_refuses_loudly(monkeypatch):
    """It speaks a different surface (`client.messages`). Silently answering without
    the tools would look like a model that ignores them."""
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    p = LLMProvider.__new__(LLMProvider)
    p.backend = "anthropic"

    with pytest.raises(NotImplementedError, match="client.messages"):
        p.complete_with_tools("sys", "q", _TOOLS)


def test_empty_turn_is_still_a_turn():
    """No choices at all (some local backends) must not raise inside the loop."""
    assert _parse_tool_turn(object()) == ToolTurn(text=None)


def _fake_completion(*, name: str, arguments: str, content=None):
    from types import SimpleNamespace
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(
            content=content,
            tool_calls=[SimpleNamespace(
                id="call_1", type="function",
                function=SimpleNamespace(name=name, arguments=arguments))],
        ),
        finish_reason="tool_calls",
    )])
