"""VA-3 rot guard — our hardcoded GenAI keys against the installed spec package.

`aughor/obs/genai.py` writes the OpenTelemetry GenAI attribute names as string
literals rather than importing them, because upstream ships them under
`opentelemetry.semconv._incubating`, a private path that may move in any release —
and an ImportError inside the telemetry layer breaks the thing it observes.

Hardcoding is only safe if something notices when upstream moves. That is this
file. Every literal is compared to the installed constant, so a rename fails a
test instead of silently unlabelling every exported span — the failure mode that
kept the Langfuse v2 backend "enabled" and shipping nothing for months
(`test_telemetry_sdk_surface.py` is the sibling guard for that one).
"""
from __future__ import annotations

import pytest

from aughor.obs import genai

semconv = pytest.importorskip(
    "opentelemetry.semconv._incubating.attributes.gen_ai_attributes",
    reason="observability extra not installed")


# ── 1. every key we hardcode still is what the spec calls it ──────────────────

def test_hardcoded_keys_match_the_installed_semantic_conventions():
    """Each literal against its upstream constant. A failure here means a rename:
    fix the literal, do not delete the assertion."""
    expected = {
        "OPERATION_NAME": semconv.GEN_AI_OPERATION_NAME,
        "PROVIDER_NAME": semconv.GEN_AI_PROVIDER_NAME,
        "SYSTEM": semconv.GEN_AI_SYSTEM,
        "REQUEST_MODEL": semconv.GEN_AI_REQUEST_MODEL,
        "RESPONSE_MODEL": semconv.GEN_AI_RESPONSE_MODEL,
        "REQUEST_TEMPERATURE": semconv.GEN_AI_REQUEST_TEMPERATURE,
        "USAGE_INPUT_TOKENS": semconv.GEN_AI_USAGE_INPUT_TOKENS,
        "USAGE_OUTPUT_TOKENS": semconv.GEN_AI_USAGE_OUTPUT_TOKENS,
        "CONVERSATION_ID": semconv.GEN_AI_CONVERSATION_ID,
        "AGENT_NAME": semconv.GEN_AI_AGENT_NAME,
        "TOOL_NAME": semconv.GEN_AI_TOOL_NAME,
        "TOOL_TYPE": semconv.GEN_AI_TOOL_TYPE,
    }
    for attr, upstream in expected.items():
        assert getattr(genai, attr) == upstream, (
            f"genai.{attr} is {getattr(genai, attr)!r}; the spec now says "
            f"{upstream!r} — every exported span is carrying the old key")


def test_error_type_is_the_stable_key():
    """`error.type` is stable (not GenAI-specific), so it lives outside the
    incubating module and is the one key here that will not move."""
    from opentelemetry.semconv.attributes import error_attributes
    assert genai.ERROR_TYPE == error_attributes.ERROR_TYPE


def test_operation_values_are_spec_values_not_our_prose():
    """The operation name is an enum, not free text: a reader filtering
    `gen_ai.operation.name = "chat"` finds nothing if we invent our own word."""
    ops = semconv.GenAiOperationNameValues
    assert genai.OP_CHAT == ops.CHAT.value
    assert genai.OP_EXECUTE_TOOL == ops.EXECUTE_TOOL.value
    assert genai.OP_INVOKE_AGENT == ops.INVOKE_AGENT.value


def test_gen_ai_system_alias_is_still_the_documented_predecessor():
    """We emit the deprecated `gen_ai.system` alongside `gen_ai.provider.name`
    because shipped dashboards still key on it. When upstream stops describing it
    as replaced-by — i.e. removes it — this fails, and the alias should be dropped
    rather than left to rot as a blank column."""
    doc = (semconv.__doc__ or "") + open(semconv.__file__).read()
    assert "gen_ai.system" in doc
    assert "Replaced by `gen_ai.provider.name`" in doc, (
        "gen_ai.system no longer documents gen_ai.provider.name as its successor "
        "— re-check whether the compatibility alias in obs/genai.py is still wanted")


# ── 2. the provider mapping, in both directions ───────────────────────────────

def test_mapped_backends_use_the_specs_own_values():
    """The three we translate must land on real enum values — a typo here is a
    provider column that matches nothing."""
    known = {m.value for m in semconv.GenAiProviderNameValues}
    for backend in ("anthropic", "groq", "gemini"):
        assert genai.provider_name(backend) in known, (
            f"{backend} maps to {genai.provider_name(backend)!r}, which is not a "
            f"well-known provider value")
    assert genai.provider_name("gemini") == semconv.GenAiProviderNameValues.GCP_GEMINI.value


def test_unknown_backends_pass_through_rather_than_being_mislabelled():
    """The measured majority of this deployment's traffic. `openrouter` is a
    gateway with no spec value; calling it `openai` would attribute its spend to
    OpenAI in every downstream cost aggregate."""
    known = {m.value for m in semconv.GenAiProviderNameValues}
    for backend in ("openrouter", "together", "ollama", "lmstudio", "faux"):
        got = genai.provider_name(backend)
        assert got == backend, f"{backend} was rewritten to {got!r}"
        if backend in ("openrouter", "ollama"):
            assert got not in known, (
                f"{backend} now HAS a well-known value — move it into _WELL_KNOWN")


def test_every_backend_the_provider_ships_gets_a_nonempty_provider_name():
    """Guard against a new backend arriving with no telemetry identity at all —
    the pass-through is what makes this hold, so it must keep holding."""
    from aughor.llm.provider import BACKENDS
    for backend in BACKENDS:
        assert genai.provider_name(backend), f"{backend} produced an empty provider name"


def test_provider_name_is_case_and_whitespace_insensitive():
    assert genai.provider_name("  Gemini ") == "gcp.gemini"
    assert genai.provider_name(None) == ""
    assert genai.provider_name("") == ""


# ── 3. the attribute builders ─────────────────────────────────────────────────

def test_generation_attrs_carries_provider_model_and_tokens():
    attrs = genai.generation_attrs(
        backend="gemini", model="gemini-3.1-flash-lite",
        prompt_tokens=1200, completion_tokens=85, temperature=0.2,
        conversation_id="inv-1")
    assert attrs[genai.OPERATION_NAME] == "chat"
    assert attrs[genai.PROVIDER_NAME] == "gcp.gemini"
    assert attrs[genai.SYSTEM] == "gcp.gemini"
    assert attrs[genai.REQUEST_MODEL] == "gemini-3.1-flash-lite"
    assert attrs[genai.USAGE_INPUT_TOKENS] == 1200
    assert attrs[genai.USAGE_OUTPUT_TOKENS] == 85
    assert attrs[genai.REQUEST_TEMPERATURE] == 0.2
    assert attrs[genai.CONVERSATION_ID] == "inv-1"


def test_unreported_usage_is_absent_not_zero():
    """The distinction `_record_llm_call` is careful about, carried onto the wire.
    A backend that reports no usage must not export a span claiming zero tokens —
    that is a cost aggregate silently understating itself."""
    attrs = genai.generation_attrs(backend="ollama", model="llama3",
                                   prompt_tokens=None, completion_tokens=None)
    assert genai.USAGE_INPUT_TOKENS not in attrs
    assert genai.USAGE_OUTPUT_TOKENS not in attrs
    # …while a genuine zero completion IS reported.
    attrs0 = genai.generation_attrs(backend="ollama", model="llama3",
                                    prompt_tokens=10, completion_tokens=0)
    assert attrs0[genai.USAGE_OUTPUT_TOKENS] == 0


def test_error_class_lands_on_the_stable_error_key():
    attrs = genai.generation_attrs(backend="groq", model="m", error_class="TimeoutError")
    assert attrs[genai.ERROR_TYPE] == "TimeoutError"
    assert genai.ERROR_TYPE not in genai.generation_attrs(backend="groq", model="m")


def test_tool_and_agent_attrs_use_different_operations():
    """A delegation hop is an agent invocation, not a tool call. Collapsing them
    is what makes a delegation tree unreadable in an external viewer."""
    t = genai.tool_attrs("sql.execute", kind="sql")
    a = genai.agent_attrs("Luxury Revenue Analyst")
    assert t[genai.OPERATION_NAME] == "execute_tool"
    assert t[genai.TOOL_NAME] == "sql.execute"
    assert a[genai.OPERATION_NAME] == "invoke_agent"
    assert a[genai.AGENT_NAME] == "Luxury Revenue Analyst"
    assert t[genai.OPERATION_NAME] != a[genai.OPERATION_NAME]


def test_span_name_follows_the_spec_shape():
    assert genai.span_name(genai.OP_CHAT, "gpt-x") == "chat gpt-x"
    assert genai.span_name(genai.OP_CHAT, None) == "chat"
    assert genai.span_name(genai.OP_CHAT, "  ") == "chat"
