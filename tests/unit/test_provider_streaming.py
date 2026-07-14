"""LLMProvider.complete_streaming — raw JSON streaming for the OpenAI-compat family (CK-0.2).

Hermetic: the underlying OpenAI-compatible client is stubbed, so no network and no
LLM. The OpenAI-compat path streams RAW chat deltas and parses the growing buffer
itself (first-'{' scan + jiter partial parse) because instructor's partial parser
chokes on any preamble/fence before the JSON — observed live ("expected value at
line 1 column 1" on glm via the ollama shim). Covers the contract
complete_streaming promises its callers:
  - on_text receives the FULL text so far (replace semantics), monotonically growing;
  - preamble/fenced streams still yield deltas (the robustness win over instructor);
  - the returned object is a fully-validated response_model;
  - ANY streaming failure falls back to the blocking complete() path;
  - metering records REAL usage when the stream carries it (stream_options
    include_usage), honest zeros when it doesn't, wall-clock always.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from aughor.llm.provider import LLMProvider


class _Out(BaseModel):
    narrative: str = ""
    questions: list[str] = []


# ── Stub raw OpenAI-compatible client ──────────────────────────────────────────

def _chunk(content: str | None, usage=None):
    delta = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


_USAGE = SimpleNamespace(prompt_tokens=82, completion_tokens=786)


class _FakeRawCompletions:
    def __init__(self, chunks=None, exc=None, reject_stream_options=False):
        self._chunks = chunks or []
        self._exc = exc
        self._reject = reject_stream_options
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._reject and "stream_options" in kwargs:
            raise TypeError("unexpected keyword argument 'stream_options'")
        if self._exc is not None:
            raise self._exc
        return iter(self._chunks)


class _FakeInstructorWrapper:
    """Shape-compatible with instructor's wrapper: `.client` is the raw client."""
    def __init__(self, completions):
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _provider_with(completions) -> LLMProvider:
    # Building an ollama provider constructs an OpenAI client but never dials out;
    # swap in the stub so complete_streaming exercises the real _stream_on plumbing.
    prov = LLMProvider("ollama", "narrator", model="stub-model", base_url="http://localhost:1/v1")
    prov._client = _FakeInstructorWrapper(completions)
    return prov


# JSON streamed in pieces — WITH a fenced preamble, the exact shape that broke
# instructor's partial parser. Deltas below are what the narrative field grows to.
_JSON_PIECES = [
    "```json\n",                                   # preamble/fence — must be skipped
    '{"narrative": "Sales grew',
    ' **12%** month',
    ' over month.", "questions": ["q1", "q2", "q3"]}',
    "\n```",
]
_EXPECT_DELTAS = [
    "Sales grew",
    "Sales grew **12%** month",
    "Sales grew **12%** month over month.",
]


def _happy_chunks():
    chunks = [_chunk(p) for p in _JSON_PIECES]
    chunks.append(_chunk(None, usage=_USAGE))       # terminal usage-only chunk
    return chunks


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_on_text_monotonic_final_validated_and_preamble_tolerated():
    completions = _FakeRawCompletions(chunks=_happy_chunks())
    prov = _provider_with(completions)
    seen: list[str] = []

    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  temperature=0.2, text_field="narrative",
                                  on_text=seen.append)

    # Every callback carries the full text so far and strictly grows — despite the fence.
    assert seen == _EXPECT_DELTAS
    assert all(seen[i + 1].startswith(seen[i]) for i in range(len(seen) - 1))
    # The final object is the parsed terminal JSON, validated into the PLAIN model.
    assert type(out) is _Out
    assert out.narrative == _EXPECT_DELTAS[-1]
    assert out.questions == ["q1", "q2", "q3"]
    # The stub actually got the raw-stream kwargs (model + both messages + stream).
    call = completions.calls[0]
    assert call["model"] == "stub-model" and call["stream"] is True
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    # The compact JSON instruction rode the system prompt (we bypass instructor's).
    assert "Return ONLY a JSON object" in call["messages"][0]["content"]


def test_include_usage_rejected_retries_without():
    completions = _FakeRawCompletions(chunks=_happy_chunks(), reject_stream_options=True)
    prov = _provider_with(completions)
    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=lambda t: None)
    assert out.narrative == _EXPECT_DELTAS[-1]
    # First call carried stream_options and was rejected; the retry dropped it.
    assert "stream_options" in completions.calls[0]
    assert "stream_options" not in completions.calls[1]


def test_on_text_skipped_when_text_did_not_grow():
    # Chunks that don't extend the narrative must not re-fire the callback.
    chunks = [
        _chunk('{"narrative": "abc'),
        _chunk('", "questions": ['),               # narrative unchanged — no callback
        _chunk(']}'),
    ]
    prov = _provider_with(_FakeRawCompletions(chunks=chunks))
    seen: list[str] = []
    prov.complete_streaming(system="s", user="u", response_model=_Out,
                            text_field="narrative", on_text=seen.append)
    assert seen == ["abc"]


def test_on_text_exception_does_not_kill_the_stream():
    prov = _provider_with(_FakeRawCompletions(chunks=_happy_chunks()))

    def _boom(_text: str) -> None:
        raise RuntimeError("callback bug")

    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=_boom)
    assert out.narrative == _EXPECT_DELTAS[-1]   # final object still returned


# ── Fallback path ──────────────────────────────────────────────────────────────

def test_stream_create_raising_falls_back_to_complete(monkeypatch):
    sentinel = _Out(narrative="from blocking fallback", questions=["a"])
    prov = _provider_with(_FakeRawCompletions(exc=ValueError("stream refused")))
    called = {}

    def _fake_complete(self, system, user, response_model, temperature=0.1):
        called["args"] = (system, user, response_model, temperature)
        return sentinel

    monkeypatch.setattr(LLMProvider, "complete", _fake_complete)
    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  temperature=0.3, text_field="narrative",
                                  on_text=lambda t: None)
    assert out is sentinel
    assert called["args"] == ("s", "u", _Out, 0.3)


def test_stream_with_no_json_falls_back_to_complete(monkeypatch):
    # Prose with no JSON object anywhere is a failure, not a silent half-answer.
    sentinel = _Out(narrative="healed")
    prov = _provider_with(_FakeRawCompletions(chunks=[_chunk("no json here at all")]))
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **k: sentinel)
    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=lambda t: None)
    assert out is sentinel


def test_missing_raw_client_falls_back_to_complete(monkeypatch):
    # An instructor wrapper without a `.client` raw handle must degrade gracefully.
    sentinel = _Out(narrative="no raw client")
    prov = _provider_with(_FakeRawCompletions())
    prov._client = SimpleNamespace()               # no .client attribute
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **k: sentinel)
    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=lambda t: None)
    assert out is sentinel


def test_invalid_terminal_json_falls_back_to_complete(monkeypatch):
    # If the terminal JSON can't validate as the full model, the blocking path
    # heals it rather than returning a half-parsed object.
    class _Strict(BaseModel):
        narrative: str                              # required
        score: int                                  # required — stream omits it

    sentinel = _Strict(narrative="healed", score=1)
    prov = _provider_with(_FakeRawCompletions(chunks=[_chunk('{"narrative": "x"}')]))
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **k: sentinel)
    out = prov.complete_streaming(system="s", user="u", response_model=_Strict,
                                  text_field="narrative", on_text=lambda t: None)
    assert out is sentinel


# ── Anthropic branch (instructor create_partial — exercised via _stream_on) ────

def test_anthropic_branch_uses_create_partial():
    class _Partial(_Out):
        pass

    partials = [_Partial(narrative="a"), _Partial(narrative="ab", questions=["q"])]
    calls: list[dict] = []

    def _create_partial(**kwargs):
        calls.append(kwargs)
        yield from partials

    fake_anthro = SimpleNamespace(messages=SimpleNamespace(create_partial=_create_partial))
    seen: list[str] = []
    out = LLMProvider._stream_on(fake_anthro, "anthropic", "claude-x", "s", "u",
                                 _Out, 0.2, "narrative", seen.append)
    assert seen == ["a", "ab"]
    assert type(out) is _Out and out.narrative == "ab"
    assert calls and calls[0]["model"] == "claude-x" and calls[0]["max_tokens"] == 4096


# ── Metering ───────────────────────────────────────────────────────────────────

def test_metering_records_real_usage_from_stream(monkeypatch):
    import aughor.kernel.metering as metering

    recorded = {}
    monkeypatch.setattr(metering, "record_llm",
                        lambda pt, ct, ms: recorded.setdefault("call", (pt, ct, ms)))
    prov = _provider_with(_FakeRawCompletions(chunks=_happy_chunks()))
    prov.complete_streaming(system="s", user="u", response_model=_Out,
                            text_field="narrative", on_text=lambda t: None)
    pt, ct, ms = recorded["call"]
    assert (pt, ct) == (82, 786)       # REAL usage from the terminal chunk
    assert ms >= 0.0


def test_metering_honest_zeros_when_stream_has_no_usage(monkeypatch):
    import aughor.kernel.metering as metering

    recorded = {}
    monkeypatch.setattr(metering, "record_llm",
                        lambda pt, ct, ms: recorded.setdefault("call", (pt, ct, ms)))
    chunks = [_chunk(p) for p in _JSON_PIECES]      # no usage chunk at all
    prov = _provider_with(_FakeRawCompletions(chunks=chunks))
    prov.complete_streaming(system="s", user="u", response_model=_Out,
                            text_field="narrative", on_text=lambda t: None)
    pt, ct, ms = recorded["call"]
    assert (pt, ct) == (0, 0)          # honest zeros — metering never guesses
    assert ms >= 0.0


def test_metering_budget_exceeded_propagates(monkeypatch):
    # check_budget raising (in-context budget blown) must surface from _stream_on,
    # not be swallowed — complete_streaming's caller-level fallback is a separate
    # concern; the stream path itself must never eat a budget stop.
    import aughor.kernel.metering as metering

    class _Budget(Exception):
        pass

    monkeypatch.setattr(metering, "record_llm", lambda *a, **k: None)
    monkeypatch.setattr(metering, "check_budget", lambda: (_ for _ in ()).throw(_Budget("over")))
    prov = _provider_with(_FakeRawCompletions(chunks=_happy_chunks()))
    with pytest.raises(_Budget):
        prov._stream_on(prov._client, "ollama", "stub-model", "s", "u", _Out, 0.0,
                        "narrative", lambda t: None, base_url="http://localhost:1/v1")
