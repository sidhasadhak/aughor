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
# text and the required field missing. The same model answers correctly in JSON mode.

def test_a_disproved_tools_declaration_stops_being_trusted(monkeypatch):
    """The runtime correction must actually change the mode the next client uses."""
    import instructor
    from aughor.llm import provider as P

    monkeypatch.setattr(P, "model_supports_tools", lambda m: True)
    monkeypatch.setattr(P, "_TOOLS_DECLARATION_DISPROVED", set())

    first = P._build_ollama_client("m:1", "http://localhost:11434")
    assert first.mode == instructor.Mode.TOOLS      # the declaration is believed

    P._TOOLS_DECLARATION_DISPROVED.add(("ollama", "m:1"))
    second = P._build_ollama_client("m:1", "http://localhost:11434")
    assert second.mode == instructor.Mode.JSON      # and corrected once disproved

    other = P._build_ollama_client("m:2", "http://localhost:11434")
    assert other.mode == instructor.Mode.TOOLS      # scoped to the model that failed


def test_the_json_fallback_client_reuses_the_same_connection(monkeypatch):
    # `model_supports_tools` asks the live daemon, so the mode this builder picks
    # depends on the machine. Pin it: the subject is the fallback, not the lookup.
    import instructor
    from aughor.llm import provider as P
    from aughor.llm.provider import _build_ollama_client, _json_mode_fallback_client

    monkeypatch.setattr(P, "model_supports_tools", lambda m: True)
    monkeypatch.setattr(P, "_TOOLS_DECLARATION_DISPROVED", set())
    tools_client = _build_ollama_client("qwen2.5-coder:14b", "http://localhost:11434")
    assert tools_client.mode == instructor.Mode.TOOLS
    alt = _json_mode_fallback_client(tools_client)
    assert alt is not None
    assert alt.mode == instructor.Mode.JSON
    assert alt.client is tools_client.client          # same connection, not a new one


def test_there_is_no_fallback_from_json_mode():
    """Nothing to fall back FROM — the caller must let the original error stand."""
    import instructor
    from aughor.llm.provider import _json_mode_fallback_client

    class _Fake:
        mode = instructor.Mode.JSON
        client = object()

    assert _json_mode_fallback_client(_Fake()) is None
