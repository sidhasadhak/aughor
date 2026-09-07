"""Ollama's base URL works in either spelling (2026-09-07).

Ollama advertises `http://localhost:11434` — what `ollama serve` prints and what its
docs show — but its OpenAI-compatible surface lives under `/v1`. Pasting the advertised
URL sent every call to `/chat/completions`, which Ollama answers with a bare
`404 page not found`; the operator saw "structured output unavailable: the request never
reached the model (wrong endpoint)" with no hint that one path segment was missing.

Measured against a live daemon that day: `/chat/completions` 404,
`/v1/chat/completions` 200 on the same model.

The native side already tolerated both spellings (`_ollama_root` strips `/v1` before
`/api/tags`). These tests pin the other direction, and that the two are inverses.
"""
from __future__ import annotations

import pytest

from aughor.llm.models import _ollama_root
from aughor.llm.provider import _ollama_openai_base


@pytest.mark.parametrize("given", [
    "http://localhost:11434",       # what Ollama itself advertises — the reported bug
    "http://localhost:11434/",      # trailing slash
    "http://localhost:11434/v1",    # already correct
    "http://localhost:11434/v1/",   # correct, trailing slash
])
def test_every_spelling_reaches_the_openai_surface(given):
    assert _ollama_openai_base(given) == "http://localhost:11434/v1"


def test_a_remote_host_is_handled_the_same_way():
    assert _ollama_openai_base("http://ollama.lan:11434") == "http://ollama.lan:11434/v1"


def test_the_suffix_is_never_doubled():
    once = _ollama_openai_base("http://localhost:11434")
    assert _ollama_openai_base(once) == once


def test_an_empty_base_is_left_alone():
    """Empty means "unset"; inventing a path would turn a config gap into a bad URL."""
    assert _ollama_openai_base("") == ""


@pytest.mark.parametrize("given", [
    "http://localhost:11434",
    "http://localhost:11434/v1",
])
def test_it_is_the_inverse_of_the_native_root(given):
    """The pair must agree, or one surface breaks whenever the other is fixed."""
    assert _ollama_root(_ollama_openai_base(given)) == "http://localhost:11434"
    assert _ollama_openai_base(_ollama_root(given)) == "http://localhost:11434/v1"


def test_the_built_client_actually_targets_v1():
    """The outcome, not the helper: the constructed SDK client must carry /v1."""
    from aughor.llm.provider import _build_ollama_client
    client = _build_ollama_client("qwen2.5-coder:14b", "http://localhost:11434")
    assert str(client.client.base_url).rstrip("/").endswith("/v1")


# ── The second defect the same report exposed ─────────────────────────────────
#
# The health check said `reason: "unknown"` and `hint: "Unrecognised failure"` for a
# fault it HAD classified: `classify_provider_error` ran on `StructuredOutputError`,
# whose prose ("…(wrong endpoint) — The base URL does not look like this provider's
# API root.") carries none of the evidence markers. The provider's real 404 was in
# `__cause__` the whole time.

def test_a_wrapped_failure_keeps_the_diagnosis_its_cause_carries():
    from aughor.llm.provider import classify_provider_error
    from aughor.llm.reliability import Diagnosis, StructuredOutputError

    real = RuntimeError("404 page not found")          # what Ollama actually said
    wrapped = StructuredOutputError(
        Diagnosis(failure="unavailable",
                  detail="the request never reached the model (wrong endpoint)"),
        cause=real)

    assert classify_provider_error(real) == "wrong_endpoint"      # premise
    assert classify_provider_error(wrapped) == "wrong_endpoint"   # the fix


def test_the_wrapper_alone_is_still_unknown():
    """No cause, no evidence — the honest answer stays "unknown"."""
    from aughor.llm.provider import classify_provider_error
    from aughor.llm.reliability import Diagnosis, StructuredOutputError

    bare = StructuredOutputError(Diagnosis(failure="unavailable", detail="something odd"))
    assert classify_provider_error(bare) == "unknown"


def test_a_cyclic_cause_chain_terminates():
    from aughor.llm.provider import classify_provider_error
    a = RuntimeError("mystery a")
    b = RuntimeError("mystery b")
    a.__cause__ = b
    b.__cause__ = a
    assert classify_provider_error(a) == "unknown"   # must return, not hang


# ── A model that DECLARES tools but cannot deliver them ───────────────────────
#
# qwen2.5-coder:14b advertises `capabilities: [completion, tools, insert]`, yet a
# tool-choice-forced call returns `tool_calls: null` with the call rendered as plain
# text and the required field missing. The platform REFUSES rather than quietly
# answering in another mode: the mode is chosen from the model's own declaration, so
# working around a false one leaves a model that misreports itself in place.

def _completion(tool_calls):
    """Minimal stand-in for an OpenAI-shaped response."""
    from types import SimpleNamespace
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"name": "Ping", "arguments": {}}',
                                tool_calls=tool_calls))])


def _tools_client():
    import instructor
    from types import SimpleNamespace
    return SimpleNamespace(mode=instructor.Mode.TOOLS, client=object())


class InstructorRetryException(Exception):
    """`_is_structured_failure` keys on the exception's TYPE NAME, so the name here is
    the contract, not the base class — pinned deliberately."""


def _failed_call(tool_calls):
    exc = InstructorRetryException("validation failed")
    exc.last_completion = _completion(tool_calls=tool_calls)
    return exc


def test_no_tool_call_is_named_as_a_configuration_fault():
    from aughor.llm.provider import ToolsDeclarationError, _raise_if_tools_declaration_false
    from aughor.llm import provider as P

    assert P._is_structured_failure(_failed_call(None))          # premise

    exc = _failed_call(tool_calls=None)                          # the fingerprint
    with pytest.raises(ToolsDeclarationError) as caught:
        _raise_if_tools_declaration_false(_tools_client(), "ollama", "m:1", exc)
    msg = str(caught.value)
    assert "ollama/m:1" in msg                     # NAMES the model
    assert "declares tool calling" in msg
    assert caught.value.__cause__ is exc           # evidence survives


def test_a_model_that_did_call_the_tool_is_never_accused():
    """A real tool call that merely failed its schema is ordinary flakiness."""
    from aughor.llm.provider import _raise_if_tools_declaration_false
    exc = _failed_call(tool_calls=[{"id": "1"}])
    _raise_if_tools_declaration_false(_tools_client(), "ollama", "m:1", exc)   # no raise


def test_no_reachable_response_means_no_accusation():
    """Absent evidence, stay silent — a guess here slanders a working model."""
    from aughor.llm.provider import _raise_if_tools_declaration_false, _tool_call_absent
    exc = InstructorRetryException("validation failed")   # no response attached
    assert _tool_call_absent(exc) is None
    _raise_if_tools_declaration_false(_tools_client(), "ollama", "m:1", exc)   # no raise


def test_json_mode_is_out_of_scope():
    """Only a TOOLS-mode call can disprove a tools declaration."""
    import instructor
    from types import SimpleNamespace
    from aughor.llm.provider import _raise_if_tools_declaration_false
    exc = _failed_call(tool_calls=None)
    json_client = SimpleNamespace(mode=instructor.Mode.JSON, client=object())
    _raise_if_tools_declaration_false(json_client, "ollama", "m:1", exc)       # no raise


def test_the_failure_reaches_the_operator_as_its_own_class():
    """A red cross with a paragraph is what this replaced — it must be actionable."""
    from aughor.llm.provider import (ToolsDeclarationError, classify_provider_error,
                                     error_hint, PROVIDER_ERROR_CLASSES)
    from aughor.agent import answer_errors as AE

    exc = ToolsDeclarationError("ollama", "m:1", RuntimeError("no tool call"))
    reason = classify_provider_error(exc)
    assert reason == "tools_unsupported"
    assert reason in PROVIDER_ERROR_CLASSES
    assert error_hint(reason)                       # provider-side hint exists
    assert reason in AE._POLICY                     # answer-path policy exists
    retryable, _recovery, hint = AE._POLICY[reason]
    assert retryable is False                       # retrying cannot help
    assert "tool calling" in hint


def test_the_declaration_is_still_taken_at_face_value(monkeypatch):
    """No memo, no second-guessing: the model's answer picks the mode."""
    import instructor
    from aughor.llm import provider as P
    monkeypatch.setattr(P, "model_supports_tools", lambda m: True)
    assert P._build_ollama_client("m:1", "http://localhost:11434").mode == instructor.Mode.TOOLS
    monkeypatch.setattr(P, "model_supports_tools", lambda m: False)
    assert P._build_ollama_client("m:1", "http://localhost:11434").mode == instructor.Mode.JSON
