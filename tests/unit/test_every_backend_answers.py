"""PENDING item 17 — the default answer works on every model backend.

The conversation and the analyst are tool loops, and `ask.converse` routes every quick and
deep `/ask` turn to them. Measured 2026-09-24: the `anthropic` binding raised before any
fallback and every such turn ended in an error (the translation itself is pinned in
`test_provider_tool_calls.py`). Two routes out for a binding that cannot make a tool call:

* known in advance — the model declares no tool calling, or refused one earlier in this
  process — the turn is routed to the bodies that need none, exactly as with the flag off;
* found on the turn's first request — the quick body answers instead, and the step trail
  says why. A failure after a step has run is still the turn's error: something was already
  answered, and restarting would repeat it.
"""
from __future__ import annotations

import asyncio
import json
import types

import pytest

from aughor.agent import converse_tools as ct
from aughor.routers import investigations as inv


@pytest.fixture(autouse=True)
def _no_remembered_refusals():
    ct._REFUSED_TOOLS.clear()
    yield
    ct._REFUSED_TOOLS.clear()


@pytest.fixture
def binding(monkeypatch):
    declared = {"tools": None}
    monkeypatch.setattr("aughor.llm.provider.resolve_binding",
                        lambda role="coder", **kw: ("ollama", "gemma:2b", ""))
    monkeypatch.setattr("aughor.llm.provider.model_supports_tools",
                        lambda model: declared["tools"])
    return declared


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(inv, "build_history_section", lambda h: "")
    monkeypatch.setattr(inv, "build_prior_answers_section", lambda a: "")
    monkeypatch.setattr(inv, "resolve_prior_answers", lambda *a, **k: [])
    monkeypatch.setattr("aughor.agent.converse_tools.ground_answer_numbers",
                        lambda answer, rows, question="": (answer, None))

    def _quick(question, connection_id, history, *, emit, cancelled, **kw):
        emit("headline", {"headline": "There were 1,744 orders."})
        emit("done", {"inv_id": "quick-1"})
        return {}

    monkeypatch.setattr(inv, "_answer_core", _quick)


def _drive(question: str = "how many orders?") -> list[dict]:
    async def _go():
        return [json.loads(chunk.split("data: ", 1)[1])
                for chunk in [c async for c in inv._stream_converse(question, "fixture", [],
                                                                    session_id="s1")]
                if chunk.startswith("data: ")]
    return asyncio.run(_go())


def _raising(exc, *, after_a_step: bool = False):
    def _converse(*args, **kwargs):
        if after_a_step:
            kwargs["on_step"](types.SimpleNamespace(tool="run_sql", arguments={}, ok=True,
                                                    detail="", result_chars=10))
        raise exc
    return _converse


def test_the_refusals_that_mean_no_tools_at_all():
    assert ct.tools_unsupported(NotImplementedError("the binding uses client.messages"))
    assert ct.tools_unsupported(RuntimeError(
        'registry.ollama.ai/library/gemma:2b does not support tools (status code: 400)'))
    assert ct.tools_unsupported(RuntimeError("Tool use is not supported for this model"))
    assert ct.tools_unsupported(RuntimeError("function calling is not supported by this endpoint"))
    assert not ct.tools_unsupported(RuntimeError("429: rate limited"))
    assert not ct.tools_unsupported(RuntimeError("the tool raised: no such table orders"))


def test_a_binding_known_to_refuse_tools_takes_the_bodies_that_need_none(binding):
    assert ct.converse_available() is True       # never asked: routed exactly as before
    binding["tools"] = True
    assert ct.converse_available() is True
    binding["tools"] = False                      # the model's own catalogue says no
    assert ct.converse_available() is False
    binding["tools"] = None
    ct.remember_tools_refused()                   # or it refused on an earlier turn
    assert ct.converse_available() is False


def test_the_analyst_door_follows_the_same_rule(binding):
    route = types.SimpleNamespace(depth="deep", forced="", mode="")
    req = types.SimpleNamespace(escalate=False)
    assert inv._analyst_eligible(req, route) is True
    binding["tools"] = False
    assert inv._analyst_eligible(req, route) is False     # the phase script serves it


def test_a_turn_refused_at_its_first_request_is_answered_by_the_quick_body(
        binding, offline, monkeypatch):
    monkeypatch.setattr("aughor.agent.converse_tools.converse", _raising(
        RuntimeError("registry.ollama.ai/library/gemma:2b does not support tools")))

    frames = _drive()

    assert "error" not in [f["type"] for f in frames]
    step = next(f for f in frames if f["type"] == "converse_step")
    assert step["ok"] is False and "cannot call tools" in step["detail"]
    assert "quick pipeline" in step["detail"]
    assert any(f.get("headline") == "There were 1,744 orders." for f in frames)
    assert ("ollama", "gemma:2b") in ct._REFUSED_TOOLS     # the next turn routes there at once


def test_any_other_failure_is_still_the_turns_error(binding, offline, monkeypatch):
    monkeypatch.setattr("aughor.agent.converse_tools.converse",
                        _raising(RuntimeError("401: invalid key")))
    assert [f["type"] for f in _drive()][-1] == "error"
    assert not ct._REFUSED_TOOLS


def test_a_refusal_after_a_step_has_run_is_not_restarted(binding, offline, monkeypatch):
    monkeypatch.setattr("aughor.agent.converse_tools.converse", _raising(
        RuntimeError("does not support tools"), after_a_step=True))
    frames = _drive()
    assert frames[-1]["type"] == "error"
    assert not any(f.get("headline") == "There were 1,744 orders." for f in frames)
