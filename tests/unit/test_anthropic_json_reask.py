"""Claude is asked once more for the JSON as text before another provider answers (`provider._anthropic_json_reask`).

Measured 2026-10-11 on `claude-sonnet-5-5`: 3 of 160 structured calls fell back to OpenRouter — two "did not match
the schema", one "returned no content" — and none was repaired. Under `tool_choice: auto` (the current models refuse a
forced one) the model can answer in prose, call no tool, or say nothing. Its one repair now asks for the JSON as text
too, and when no repair was tried, it is asked once more that way. At most one extra Claude request either way, and
never for a truncation. No real request is made here: the client is a stand-in that answers by mode.
"""
from __future__ import annotations

import anthropic
import instructor
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from pydantic import BaseModel

from aughor.llm import provider as P
from aughor.llm.reliability import StructuredOutputError


class Out(BaseModel):
    finding: str
    novelty: int


def _msg(content, stop="end_turn"):
    return Message(id="m", content=content, model="claude-sonnet-5-5", role="assistant", stop_reason=stop,
                   type="message", usage=Usage(input_tokens=10, output_tokens=5))


PROSE = [TextBlock(type="text", text="The finding is that x leads, novelty three.")]
AS_TEXT = [TextBlock(type="text", text='{"finding": "x leads", "novelty": 3}')]


def _claude(tool_answer, text_answer=AS_TEXT, stop="end_turn"):
    """A stand-in Claude: a request carrying tools gets ``tool_answer``; one asking for text gets ``text_answer``."""
    sent: list[dict] = []

    class _Messages:
        def create(self, **kw):
            sent.append(kw)
            if "tools" in kw:
                return _msg(tool_answer, stop)
            return _msg(text_answer if text_answer is not None else PROSE)

    raw = anthropic.Anthropic(api_key="test-not-a-key")
    raw.messages = _Messages()
    return instructor.from_anthropic(raw, mode=instructor.Mode.ANTHROPIC_REASONING_TOOLS), sent


def _ask(client):
    return P.LLMProvider._complete_on(client, "anthropic", "claude-sonnet-5-5", "system", "user", Out, 0.1,
                                      role="coder")


def test_an_answer_in_prose_is_repaired_by_asking_for_the_json_as_text():
    client, sent = _claude(PROSE)
    assert _ask(client).model_dump() == {"finding": "x leads", "novelty": 3}
    assert ["tools" in kw for kw in sent] == [True, False]                       # the one repair asked for text


def test_an_answer_with_no_content_is_asked_once_more_for_text():
    client, sent = _claude([])
    assert _ask(client).model_dump() == {"finding": "x leads", "novelty": 3}
    assert ["tools" in kw for kw in sent] == [True, False]


def test_a_tool_call_that_misses_a_field_is_repaired_as_text():
    client, sent = _claude([ToolUseBlock(type="tool_use", id="t", name="Out", input={"finding": "x"})])
    assert _ask(client).novelty == 3 and len(sent) == 2


def test_a_truncated_answer_is_never_asked_again():
    client, sent = _claude([TextBlock(type="text", text='{"finding": "x lea')], stop="max_tokens")
    with pytest.raises(StructuredOutputError) as caught:
        _ask(client)
    assert caught.value.diagnosis.failure == "truncated" and len(sent) == 1


def test_when_text_fails_too_the_first_failure_is_what_is_said_and_one_request_was_added():
    client, sent = _claude([], text_answer=None)                             # nothing, then prose again
    with pytest.raises(StructuredOutputError) as caught:
        _ask(client)
    assert caught.value.diagnosis.failure == "empty" and len(sent) == 2


def test_what_came_back_is_said_in_a_few_words():
    client, _ = _claude(PROSE)
    try:
        client.messages.create_with_completion(model="m", max_tokens=10, system="s", messages=[], response_model=Out,
                                               max_retries=1)
    except Exception as exc:  # noqa: BLE001
        said = P._answer_shape(exc)
    assert said == "stop end_turn; blocks text; began 'The finding is that x leads, novelty three.'"


def test_a_repair_that_fails_is_not_followed_by_another_request():
    client, sent = _claude(PROSE, text_answer=None)                          # prose, and prose again as text
    with pytest.raises(StructuredOutputError):
        _ask(client)
    assert len(sent) == 2                                                     # the call and its one repair


def test_an_answer_asked_again_is_marked_so_in_the_model_call_log(monkeypatch):
    logged: list[dict] = []
    monkeypatch.setattr(P, "_record_llm_call", lambda **kw: logged.append(kw))
    client, _ = _claude([])
    _ask(client)
    assert [bool(kw.get("ok", True)) for kw in logged] == [False, True]      # the failure, then the answer
    assert (logged[-1].get("extra") or {}).get("reasked_as_json") is True


def test_a_memory_address_holding_429_is_not_a_rate_limit():
    """The flake behind the test above (2026-10-13): instructor's error chains tenacity's
    `RetryError[<Future at 0x1394290f0 …>]`, and a bare "429" substring read that address as an HTTP 429 — so an
    empty answer was said as "the request never reached the model (rate limited)" and never asked again."""
    address = RuntimeError("RetryError[<Future at 0x1394290f0 state=finished raised ValidationError>]")
    assert P.classify_provider_error(address) != "rate_limited"
    assert P.classify_provider_error(RuntimeError("Error code: 429 - {'type': 'rate_limit_error'}")) == "rate_limited"
    assert P.classify_provider_error(RuntimeError("HTTP 429 from upstream")) == "rate_limited"
