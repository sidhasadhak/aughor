"""LLMProvider.complete_streaming — instructor partial streaming (CK-0.2).

Hermetic: the instructor client is stubbed, so no network and no LLM. Covers the
contract complete_streaming promises its callers:
  - on_text receives the FULL text so far (replace semantics), monotonically growing;
  - the returned object is a fully-validated response_model equal to the last partial;
  - ANY streaming failure falls back to the blocking complete() path;
  - wall-clock metering is recorded even when the stream carries no usage.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from aughor.llm.provider import LLMProvider


class _Out(BaseModel):
    narrative: str = ""
    questions: list[str] = []


# ── Stub instructor client ─────────────────────────────────────────────────────

class _PartialOut(_Out):
    """Stands in for instructor's Partial[_Out] terminal yield (a subclass)."""


class _FakeEndpoint:
    def __init__(self, partials=None, exc=None):
        self._partials = partials or []
        self._exc = exc
        self.calls: list[dict] = []

    def create_partial(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        yield from self._partials


class _FakeChat:
    def __init__(self, endpoint):
        self.completions = endpoint


class _FakeClient:
    def __init__(self, endpoint):
        self.chat = _FakeChat(endpoint)


def _provider_with(endpoint) -> LLMProvider:
    # Building an ollama provider constructs an OpenAI client but never dials out;
    # swap in the stub so complete_streaming exercises the real _stream_on plumbing.
    prov = LLMProvider("ollama", "narrator", model="stub-model", base_url="http://localhost:1/v1")
    prov._client = _FakeClient(endpoint)
    return prov


_PARTIALS = [
    _PartialOut(narrative="Sales grew"),
    _PartialOut(narrative="Sales grew **12%** month"),
    _PartialOut(narrative="Sales grew **12%** month over month.",
                questions=["q1", "q2", "q3"]),
]


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_on_text_monotonic_and_final_equals_last_partial():
    endpoint = _FakeEndpoint(partials=_PARTIALS)
    prov = _provider_with(endpoint)
    seen: list[str] = []

    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  temperature=0.2, text_field="narrative",
                                  on_text=seen.append)

    # Every callback carries the full text so far and strictly grows.
    assert seen == [p.narrative for p in _PARTIALS]
    assert all(len(seen[i]) < len(seen[i + 1]) for i in range(len(seen) - 1))
    assert all(seen[i + 1].startswith(seen[i]) for i in range(len(seen) - 1))
    # The final object is the last partial, re-validated into the PLAIN model.
    assert type(out) is _Out
    assert out.narrative == _PARTIALS[-1].narrative
    assert out.questions == ["q1", "q2", "q3"]
    # The stub actually got the OpenAI-family kwargs (model + both messages).
    assert endpoint.calls and endpoint.calls[0]["model"] == "stub-model"
    assert [m["role"] for m in endpoint.calls[0]["messages"]] == ["system", "user"]


def test_on_text_skipped_when_text_did_not_grow():
    # A partial that repeats (or shrinks) the text must not re-fire the callback.
    endpoint = _FakeEndpoint(partials=[
        _PartialOut(narrative="abc"),
        _PartialOut(narrative="abc"),          # unchanged — no callback
        _PartialOut(narrative="abcdef"),
    ])
    prov = _provider_with(endpoint)
    seen: list[str] = []
    prov.complete_streaming(system="s", user="u", response_model=_Out,
                            text_field="narrative", on_text=seen.append)
    assert seen == ["abc", "abcdef"]


def test_on_text_exception_does_not_kill_the_stream():
    endpoint = _FakeEndpoint(partials=_PARTIALS)
    prov = _provider_with(endpoint)

    def _boom(_text: str) -> None:
        raise RuntimeError("callback bug")

    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=_boom)
    assert out.narrative == _PARTIALS[-1].narrative   # final object still returned


# ── Fallback path ──────────────────────────────────────────────────────────────

def test_create_partial_raising_falls_back_to_complete(monkeypatch):
    sentinel = _Out(narrative="from blocking fallback", questions=["a"])
    endpoint = _FakeEndpoint(exc=ValueError("stream refused"))
    prov = _provider_with(endpoint)
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


def test_empty_stream_falls_back_to_complete(monkeypatch):
    # A stream that yields nothing is a failure, not a silent None.
    sentinel = _Out(narrative="healed")
    prov = _provider_with(_FakeEndpoint(partials=[]))
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **k: sentinel)
    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=lambda t: None)
    assert out is sentinel


def test_missing_create_partial_falls_back_to_complete(monkeypatch):
    # An older instructor client without create_partial must degrade gracefully.
    class _Bare:
        pass

    class _BareClient:
        chat = type("C", (), {"completions": _Bare()})()

    sentinel = _Out(narrative="no partial support")
    prov = _provider_with(_FakeEndpoint())
    prov._client = _BareClient()
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **k: sentinel)
    out = prov.complete_streaming(system="s", user="u", response_model=_Out,
                                  text_field="narrative", on_text=lambda t: None)
    assert out is sentinel


def test_invalid_terminal_partial_falls_back_to_complete(monkeypatch):
    # If the terminal partial can't validate as the full model (stream cut off),
    # the blocking path heals it rather than returning a half-parsed object.
    class _Strict(BaseModel):
        narrative: str   # required — a partial without it must not escape

    class _LoosePartial(BaseModel):
        narrative: str | None = None

    sentinel = _Strict(narrative="healed")
    prov = _provider_with(_FakeEndpoint(partials=[_LoosePartial()]))
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **k: sentinel)
    out = prov.complete_streaming(system="s", user="u", response_model=_Strict,
                                  text_field="narrative", on_text=lambda t: None)
    assert out is sentinel


# ── Metering ───────────────────────────────────────────────────────────────────

def test_metering_records_wall_clock_even_without_usage(monkeypatch):
    import aughor.kernel.metering as metering

    recorded = {}

    def _fake_record(pt, ct, ms):
        recorded["call"] = (pt, ct, ms)

    monkeypatch.setattr(metering, "record_llm", _fake_record)
    prov = _provider_with(_FakeEndpoint(partials=_PARTIALS))
    prov.complete_streaming(system="s", user="u", response_model=_Out,
                            text_field="narrative", on_text=lambda t: None)
    assert "call" in recorded, "record_llm must be called for streamed completions"
    pt, ct, ms = recorded["call"]
    assert (pt, ct) == (0, 0)          # partial streams carry no usage — honest zeros
    assert ms >= 0.0                   # wall clock always real


def test_metering_budget_exceeded_propagates(monkeypatch):
    # check_budget raising (in-context budget blown) must surface, not be swallowed
    # into the blocking fallback (which would spend MORE budget).
    import aughor.kernel.metering as metering

    class _Budget(Exception):
        pass

    monkeypatch.setattr(metering, "record_llm", lambda *a, **k: None)
    monkeypatch.setattr(metering, "check_budget", lambda: (_ for _ in ()).throw(_Budget("over")))
    prov = _provider_with(_FakeEndpoint(partials=_PARTIALS))
    fallback_called = {}
    monkeypatch.setattr(LLMProvider, "complete",
                        lambda self, **k: fallback_called.setdefault("yes", True) or _Out())
    with pytest.raises(_Budget):
        prov._stream_on(prov._client, "ollama", "stub-model", "s", "u", _Out, 0.0,
                        "narrative", lambda t: None, base_url="http://localhost:1/v1")
