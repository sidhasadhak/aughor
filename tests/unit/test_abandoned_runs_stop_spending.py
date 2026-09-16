"""An abandoned run stops spending at its next model request.

Measured 2026-09-16: analyst jobs cancelled at their 900s time budget kept issuing model
calls for up to six minutes — their bodies are synchronous code on worker threads, which an
asyncio cancel cannot reach — and a synthesis abandoned at its timeout still launched a
full blocking redo when its stream failed validation. A thread cannot be interrupted
mid-request; these tests pin that it is never allowed to START another one.

Hermetic: stub clients and scripted cores only — no network, no LLM, no warehouse.
"""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from aughor.kernel import cancellation, metering
from aughor.kernel.cancellation import RunStopped, StopScope
from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.llm import provider as P
from aughor.llm.provider import LLMProvider


# ── the scope ─────────────────────────────────────────────────────────────────

def test_a_stopped_scope_raises_at_the_checkpoint_and_a_running_one_does_not():
    cancellation.checkpoint()                        # nothing scoped: a no-op
    with cancellation.scope() as s:
        cancellation.checkpoint()                    # running: a no-op
        s.stop("the reader left")
        with pytest.raises(RunStopped) as got:
            cancellation.checkpoint()
    assert got.value.reason == "the reader left"
    assert not isinstance(got.value, Exception), \
        "a stop the answer path's `except Exception` blocks can swallow stops nothing"


def test_a_child_sees_its_parents_stop_but_never_the_reverse():
    parent = StopScope()
    child = StopScope(parent)
    child.stop("synthesis timed out")
    assert parent.reason is None, "abandoning one bounded call must not stop the run"
    sibling = StopScope(parent)
    parent.stop("budget")
    assert sibling.reason == "budget"
    assert child.reason == "synthesis timed out", "the first reason wins"


def test_the_scope_crosses_the_context_pool_the_phases_run_on():
    with cancellation.scope() as s:
        s.stop("gone")
        with ContextThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(cancellation.checkpoint)
        with pytest.raises(RunStopped):
            fut.result()


def test_a_bounded_call_past_its_bound_is_stopped_but_its_caller_is_not():
    release = threading.Event()
    after: dict = {}

    def slow():
        release.wait(5)
        try:
            cancellation.checkpoint()                # the funnel, before its next request
            after["sent"] = True
        except RunStopped as exc:
            after["stopped"] = exc.reason

    with cancellation.scope() as caller:
        with pytest.raises(TimeoutError):
            cancellation.run_bounded(slow, 0.05, abandoned="synthesis passed its bound")
        release.set()
        for _ in range(200):
            if after:
                break
            time.sleep(0.01)
        assert after == {"stopped": "synthesis passed its bound"}
        assert caller.reason is None, "the run moved on without the call; it must not stop"


def test_a_bounded_call_keeps_the_runs_meter():
    """A plain executor dropped the run's context, so the synthesis — the largest prompt
    of the run — was never metered and never counted against a budget."""
    with metering.metered() as m:
        cancellation.run_bounded(lambda: metering.record_llm(1_000, 200), 5, abandoned="x")
        assert m.total_tokens == 1_200


# ── the funnel ────────────────────────────────────────────────────────────────

class _Out(BaseModel):
    narrative: str


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
                           usage=None)


class _Completions:
    def __init__(self, chunks, on_create=None):
        self.chunks, self.on_create, self.calls = chunks, on_create, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_create:
            self.on_create()
        return iter(self.chunks)


def _provider(completions) -> LLMProvider:
    prov = LLMProvider("ollama", "narrator", model="stub-model", base_url="http://localhost:1/v1")
    prov._client = SimpleNamespace(client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return prov


def test_a_stopped_run_sends_no_request():
    completions = _Completions([_chunk('{"narrative": "x"}')])
    with cancellation.scope() as s:
        s.stop("budget")
        with pytest.raises(RunStopped):
            _provider(completions).complete_streaming(
                system="s", user="u", response_model=_Out, text_field="narrative",
                on_text=lambda t: None)
    assert completions.calls == []


def test_a_stopped_analyst_sends_no_next_tool_choice(monkeypatch):
    """The tool-choice request skips `_run_resilient`; it must still honour the stop."""
    from aughor.llm.faux import set_responses

    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    prov = LLMProvider(backend="faux", role="coder")
    set_responses(["the queued turn"])
    with cancellation.scope() as s:
        s.stop("budget")
        with pytest.raises(RunStopped):
            prov.complete_with_tools("sys", "next step?", [])
    assert prov.complete_with_tools("sys", "next step?", []).text == "the queued turn", \
        "the stopped call consumed a turn — it reached the provider"


def test_a_stream_abandoned_in_flight_gets_no_blocking_redo(monkeypatch):
    """The 11:30:46 warning, reproduced: the stream was already running when its caller
    gave up, then failed validation. The redo is a second full request nobody reads."""
    redo: list = []
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **kw: redo.append(kw))
    with cancellation.scope() as s:
        completions = _Completions([_chunk('{"wrong_field": 1}')],
                                   on_create=lambda: s.stop("synthesis passed its bound"))
        with pytest.raises(RunStopped):
            _provider(completions).complete_streaming(
                system="s", user="u", response_model=_Out, text_field="narrative",
                on_text=lambda t: None)
    assert len(completions.calls) == 1 and redo == []


def test_a_live_stream_that_fails_validation_still_heals_through_the_redo(monkeypatch):
    """The guard must not invert: a caller that is still waiting keeps its fallback."""
    healed = _Out(narrative="healed")
    monkeypatch.setattr(LLMProvider, "complete", lambda self, **kw: healed)
    with cancellation.scope():
        out = _provider(_Completions([_chunk('{"wrong_field": 1}')])).complete_streaming(
            system="s", user="u", response_model=_Out, text_field="narrative",
            on_text=lambda t: None)
    assert out is healed


def test_no_retry_is_sent_after_the_stop(monkeypatch):
    monkeypatch.setattr(P, "_is_transient", lambda exc: True)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    attempts: list = []

    with cancellation.scope() as s:
        def do():
            attempts.append(1)
            s.stop("its reader went away")
            raise RuntimeError("upstream 503")

        with pytest.raises(RunStopped):
            P._run_resilient(do, "http://localhost:1/v1", max_retries=3)
    assert len(attempts) == 1


# ── the answer-core bridge ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_a_reader_that_leaves_stops_the_body_at_its_next_model_call(monkeypatch):
    """`emit` only reaches code that emits. A phase issues several model calls between
    emits, so the stop has to reach the funnel itself."""
    from aughor.routers import investigations as inv

    started, outcome = threading.Event(), {}

    def core(*a, emit, cancelled, **kw):
        emit("headline_delta", {"headline": "working"})
        started.set()
        try:
            for _ in range(2_000):                   # a silent phase: model calls, no emits
                cancellation.checkpoint()
                time.sleep(0.005)
            outcome["ran_out"] = True
        except RunStopped as exc:
            outcome["stopped"] = exc.reason
            raise

    monkeypatch.setattr(inv, "_answer_core", core)
    gen = inv._stream_chat("q", "fixture", [])
    await gen.__anext__()
    assert started.wait(5)
    await gen.aclose()
    for _ in range(500):
        if outcome:
            break
        await asyncio.sleep(0.01)
    assert "stopped" in outcome, f"the body ran on after its reader left: {outcome}"


@pytest.mark.anyio
async def test_a_body_that_finished_is_never_stopped(monkeypatch):
    """Work a finished answer handed to a background thread must outlive the turn."""
    from aughor.routers import investigations as inv

    seen: dict = {}

    def core(*a, emit, cancelled, **kw):
        seen["scope"] = cancellation.current()
        return inv._AnswerCoreResult(outcome="answered")

    monkeypatch.setattr(inv, "_answer_core", core)
    _ = [c async for c in inv._stream_chat("q", "fixture", [])]
    assert seen["scope"] is not None and seen["scope"].reason is None


# ── the synthesis rescue ──────────────────────────────────────────────────────

def test_an_abandoned_rescue_sends_nothing_more(monkeypatch):
    from aughor.agent import investigate as I

    release, after = threading.Event(), {}

    class _SlowFast:
        def complete(self, **kw):
            release.wait(5)
            try:
                cancellation.checkpoint()            # what the real funnel does next
                after["sent"] = True
            except RunStopped:
                after["stopped"] = True
                raise

    monkeypatch.setenv("AUGHOR_SYNTH_FAST_TIMEOUT_S", "0.05")
    monkeypatch.setattr(I, "_provider", lambda role: _SlowFast())
    assert I._fast_synthesis_rescue("s", "u", _Out) is None
    release.set()
    for _ in range(200):
        if after:
            break
        time.sleep(0.01)
    assert after == {"stopped": True}
