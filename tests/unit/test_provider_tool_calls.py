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


class _AnthropicMessages:
    """The raw Anthropic SDK's `messages.create`, scripted: records each request and answers
    with the next reply. Behind `.client`, where instructor keeps the client it wraps."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


def _anthropic_reply(*blocks, stop_reason="end_turn"):
    from types import SimpleNamespace
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=120, output_tokens=30))


def _anthropic(provider, replies):
    """Point the real provider at the anthropic binding, with a scripted raw client."""
    from types import SimpleNamespace
    messages = _AnthropicMessages(replies)
    provider.backend = "anthropic"
    provider._client = SimpleNamespace(client=SimpleNamespace(messages=messages))
    return messages


def test_anthropic_binding_speaks_tools_through_messages(provider):
    """PENDING item 17. This binding used to raise before any fallback, and every quick `/ask`
    turn on it ended in an error; it now speaks `client.messages` with the same result shape."""
    from types import SimpleNamespace
    sent = _anthropic(provider, [_anthropic_reply(
        SimpleNamespace(type="text", text="Let me count them."),
        SimpleNamespace(type="tool_use", id="toolu_1", name="run_sql", input={"sql": "SELECT 1"}),
        stop_reason="tool_use")])

    turn = provider.complete_with_tools("sys", "how many orders?", _TOOLS)

    assert turn.chose_tool and turn.tool_call.name == "run_sql"
    assert turn.tool_call.arguments == {"sql": "SELECT 1"} and turn.tool_call.id == "toolu_1"
    request = sent.requests[0]
    assert request["system"] == "sys"
    assert request["messages"] == [{"role": "user",
                                    "content": [{"type": "text", "text": "how many orders?"}]}]
    assert request["tools"] == [{"name": "run_sql", "description": "Execute a guarded SQL query.",
                                 "input_schema": _TOOLS[0]["function"]["parameters"]}]
    assert request["tool_choice"] == {"type": "auto"}
    assert "temperature" not in request            # as on this binding's structured path
    assert request["max_tokens"] > 0


def test_anthropic_prose_truncation_and_bad_arguments_read_like_every_binding(provider):
    from types import SimpleNamespace
    _anthropic(provider, [
        _anthropic_reply(SimpleNamespace(type="text", text="There were 412 orders.")),
        _anthropic_reply(stop_reason="max_tokens"),
        _anthropic_reply(SimpleNamespace(type="tool_use", id="t", name="run_sql", input="SELECT")),
    ])

    assert provider.complete_with_tools("s", "q", _TOOLS) == ToolTurn(text="There were 412 orders.")
    assert provider.complete_with_tools("s", "q", _TOOLS).truncated is True
    assert "not an object" in provider.complete_with_tools("s", "q", _TOOLS).malformed


def test_a_loop_runs_to_an_answer_on_the_anthropic_binding(provider):
    """Two requests: the second carries the call as a `tool_use` block and its answer as a
    `tool_result` inside a USER turn — Anthropic refuses a `role="tool"` message."""
    from types import SimpleNamespace

    from aughor.agent.tool_loop import ToolSpec, run_tool_loop
    sent = _anthropic(provider, [
        _anthropic_reply(SimpleNamespace(type="tool_use", id="toolu_7", name="run_sql",
                                         input={"sql": "SELECT COUNT(*) FROM orders"}),
                         stop_reason="tool_use"),
        _anthropic_reply(SimpleNamespace(type="text", text="There were 412 orders.")),
    ])
    tool = ToolSpec(name="run_sql", description="Execute a guarded SQL query.",
                    parameters=_TOOLS[0]["function"]["parameters"],
                    run=lambda args: {"rows": [[412]]})

    result = run_tool_loop(provider, "sys", "how many orders?", [tool], max_steps=4)

    assert result.answer == "There were 412 orders." and result.stop_reason == "answered"
    second = sent.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"] == [{"type": "tool_use", "id": "toolu_7", "name": "run_sql",
                                     "input": {"sql": "SELECT COUNT(*) FROM orders"}}]
    assert second[2]["content"][0]["type"] == "tool_result"
    assert second[2]["content"][0]["tool_use_id"] == "toolu_7"
    assert "412" in second[2]["content"][0]["content"]


def test_adjacent_user_turns_merge_for_anthropic():
    """A nudge after a tool result is a second user message in a row; Anthropic refuses that."""
    from aughor.llm.provider import _anthropic_messages
    history = [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "run_sql", "arguments": "{\"sql\": \"x\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "error: no such table"},
        {"role": "user", "content": "Try again with valid JSON."},
    ]

    turns = _anthropic_messages("q", history)

    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert [b["type"] for b in turns[2]["content"]] == ["tool_result", "text"]


def test_empty_turn_is_still_a_turn():
    """No choices at all (some local backends) must not raise inside the loop."""
    assert _parse_tool_turn(object()) == ToolTurn(text=None)


def test_history_reaches_the_model_so_a_loop_can_progress(provider):
    """A loop is a conversation that grows. Without the tool results going back, the
    model re-decides from the same two messages every step and picks the same tool
    forever — a loop that spends its whole budget re-running one query."""
    from aughor.llm import faux

    history = [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_1", "type": "function",
                         "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "412"},
    ]
    set_responses(["there were 412 orders"])

    provider.complete_with_tools("sys", "how many orders?", _TOOLS, history=history)

    sent = faux.calls()[-1].kwargs["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool"]
    assert sent[-1]["content"] == "412", "the tool's result never reached the model"


def test_first_turn_sends_no_history(provider):
    """Omitted rather than empty: the opening turn is just system + question."""
    from aughor.llm import faux

    set_responses(["hi"])
    provider.complete_with_tools("sys", "q", _TOOLS)

    assert [m["role"] for m in faux.calls()[-1].kwargs["messages"]] == ["system", "user"]


def test_a_dead_primary_falls_over_and_still_returns_the_choice(provider, monkeypatch):
    """An agent loop makes several calls per user turn, so a link that dies mid-loop must
    not take the turn with it. The chain has to carry a TOOL turn, not just a structured
    one — that is the part `complete()`'s existing failover does not cover."""
    from aughor.llm.provider import ToolCall, ToolTurn

    served: list[str] = []
    primary = provider.backend

    def _fake_tools_on(self, client, backend, model, *args, **kwargs):
        served.append(backend)
        if backend == primary:
            raise RuntimeError("primary is down")
        return ToolTurn(tool_call=ToolCall(name="run_sql", arguments={"sql": "SELECT 1"}))

    monkeypatch.setattr(provider, "_tools_fallbacks", lambda: ["openrouter"])
    monkeypatch.setattr(provider, "_fallback_provider", lambda b: provider)
    monkeypatch.setattr(type(provider), "_tools_on", _fake_tools_on)

    turn = provider.complete_with_tools("sys", "q", _TOOLS)

    assert turn.chose_tool
    assert served == [primary, "openrouter"], (
        f"expected the primary to be tried then the link to serve it, got {served}")


def test_quota_cooldown_skips_the_primary_without_probing_it(provider, monkeypatch):
    """The wasted round trip is paid once per LOOP STEP, not once per question — which is
    why re-probing a spent primary is worse here than on the structured path."""
    import aughor.llm.provider as prov

    probed: list[str] = []
    monkeypatch.setattr(prov, "_in_quota_cooldown", lambda b: b == provider.backend)
    monkeypatch.setattr(provider, "_tools_fallbacks", lambda: ["openrouter"])
    monkeypatch.setattr(provider, "_fallback_provider", lambda b: provider)

    def _served(self, client, backend, model, *a, **k):
        probed.append(backend)
        from aughor.llm.provider import ToolTurn
        return ToolTurn(text="ok")

    monkeypatch.setattr(type(provider), "_tools_on", _served)

    provider.complete_with_tools("sys", "q", _TOOLS)

    assert probed == ["openrouter"], f"spent primary was probed anyway: {probed}"


def test_anthropic_can_serve_a_tool_turn_as_a_fallback(provider, monkeypatch):
    """It was filtered out of the chain while it could only raise; it now speaks tools."""
    monkeypatch.setattr(provider, "_fallback_candidates",
                        lambda: ["anthropic", "openrouter"])

    assert provider._tools_fallbacks() == ["anthropic", "openrouter"]


def test_every_link_failing_surfaces_the_original_cause(provider, monkeypatch):
    """The caller's real problem is whatever took the primary down, not the last link."""
    monkeypatch.setattr(provider, "_tools_fallbacks", lambda: ["openrouter"])
    monkeypatch.setattr(provider, "_fallback_provider", lambda b: provider)

    def _always_dead(self, client, backend, *a, **k):
        raise RuntimeError("primary is down" if backend == provider.backend
                           else "link also down")

    monkeypatch.setattr(type(provider), "_tools_on", _always_dead)

    with pytest.raises(RuntimeError, match="primary is down"):
        provider.complete_with_tools("sys", "q", _TOOLS)


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


def test_a_reasoning_models_reply_is_not_reported_as_silence():
    """Reasoning models leave `content` null and put the reply on `reasoning`. Reading
    only `content` reports an empty turn, which downstream reads as "the model declined"
    — a confident lie about a model that answered."""
    from types import SimpleNamespace
    raw = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=None,
                                reasoning="the orders table has 412 rows"),
        finish_reason="stop")])

    assert _parse_tool_turn(raw).text == "the orders table has 412 rows"


def test_content_wins_over_reasoning_when_both_are_present():
    """The reasoning is the working, not the answer."""
    from types import SimpleNamespace
    raw = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="412", tool_calls=None, reasoning="let me think"),
        finish_reason="stop")])

    assert _parse_tool_turn(raw).text == "412"


def test_a_truncated_turn_is_distinct_from_an_empty_one():
    """A reasoning model can exhaust `max_tokens` on thinking tokens having emitted
    nothing. Calling that "declined" is a lie about a budget problem, and the fix (raise
    the ceiling) is nothing like the fix for a model that chose to say nothing."""
    from types import SimpleNamespace
    raw = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=None), finish_reason="length")])

    turn = _parse_tool_turn(raw)

    assert turn.truncated is True
    assert turn.text is None and not turn.chose_tool


def test_instructor_passthrough_shape_is_handled(monkeypatch, provider):
    """The defect a live call found and no offline test could.

    instructor's `response_model=None` pass-through returns (completion, None) — the
    OPPOSITE of the structured path, where the first element is the validated object and
    the second is the raw response. Faux returns both halves non-None, so this shape was
    unreachable offline. Untreated, the turn parses to nothing AND usage reads (0, 0):
    an empty reply that appears to cost zero tokens.
    """
    from types import SimpleNamespace

    completion = _fake_completion(name="run_sql", arguments='{"sql": "SELECT 1"}')
    completion.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    monkeypatch.setattr(
        provider._client.chat.completions, "create_with_completion",
        lambda **kw: (completion, None))          # the live shape

    turn = provider.complete_with_tools("sys", "q", _TOOLS)

    assert turn.chose_tool, "the pass-through completion was dropped on the floor"
    assert turn.tool_call.arguments == {"sql": "SELECT 1"}


def test_the_passthrough_turn_is_still_metered(monkeypatch, provider):
    """The half that fails silently. `_extract_usage(None)` returns (0, 0) honestly, so
    an unswapped pass-through meters every live tool turn as free — and a loop that
    appears to cost nothing is how an allowance disappears with no line item."""
    from types import SimpleNamespace

    from aughor.kernel import metering

    completion = _fake_completion(name="run_sql", arguments='{"sql": "SELECT 1"}')
    completion.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
    monkeypatch.setattr(
        provider._client.chat.completions, "create_with_completion",
        lambda **kw: (completion, None))
    recorded: list[tuple] = []
    monkeypatch.setattr(metering, "record_llm",
                        lambda pt, ct, ms: recorded.append((pt, ct)))

    provider.complete_with_tools("sys", "q", _TOOLS)

    assert recorded == [(11, 7)], f"live tool turns metered as {recorded}, not (11, 7)"


# ── the vendor's extras survive parsing ──────────────────────────────────────
# Gemini signs its reasoning and hangs the signature off the tool call, then refuses
# any later request that replays the call without it. The parser has to keep what it
# does not understand, and `extra_content` is not in the OpenAI schema — so where it
# lands depends on the client: a typed attribute on some versions, an unmodelled extra
# in `model_extra` on others (the SDK's models are `extra="allow"`).

_SIGNED = {"google": {"thought_signature": "Ci8BgOe...opaque"}}


def _signed_completion(where: str):
    """One tool call carrying `extra_content` the way `where` says the client exposes it."""
    from types import SimpleNamespace
    call = SimpleNamespace(id="call_1", type="function",
                           function=SimpleNamespace(name="run_sql", arguments='{"sql": "a"}'))
    if where == "attribute":
        call.extra_content = _SIGNED
    else:                                  # pydantic's bag of unmodelled fields
        call.model_extra = {"extra_content": _SIGNED}
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=None, tool_calls=[call]),
        finish_reason="tool_calls")])


@pytest.mark.parametrize("where", ["attribute", "model_extra"])
def test_a_signature_survives_parsing_however_the_client_exposes_it(where):
    turn = _parse_tool_turn(_signed_completion(where))

    assert turn.tool_call is not None
    assert turn.tool_call.extra_content == _SIGNED


def test_a_call_without_extras_carries_none():
    """Absent stays absent — the echo is conditional on this being falsy, so an empty
    dict promoted to a field would put a new wire shape in front of every backend."""
    turn = _parse_tool_turn(_fake_completion(name="run_sql", arguments='{"sql": "a"}'))

    assert turn.tool_call is not None
    assert turn.tool_call.extra_content is None
