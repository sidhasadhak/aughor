"""OTel GenAI semantic conventions — the vocabulary an external backend already reads (VA-3).

Aughor's spans have always carried Aughor's own attribute names, plus Langfuse's
(``langfuse.observation.*``, hardcoded in ``telemetry.py`` for the same reason as
here). Both are correct and neither is portable: point the exporter at Jaeger,
Grafana Tempo, an otel-collector or VoltOps and the model calls arrive as spans
with no model, no provider and no token counts, because those readers key on the
OpenTelemetry **GenAI** names. This module is the translation layer — one place
that knows what an LLM call is called in the language everyone else speaks.

**The keys are hardcoded, not imported.** ``opentelemetry-semantic-conventions``
ships GenAI under ``_incubating``, a private path whose own README says it may
move or vanish in any release. Importing it would make a routine dependency bump
a runtime ``ImportError`` inside telemetry — the layer whose entire contract is
"never break the thing you observe". So the strings live here as literals and
``tests/unit/test_genai_semconv.py`` pins every one of them against the installed
package: a rename upstream fails a test, which is the failure mode we want, rather
than silently unlabelling every span (the exact shape of the Langfuse v2 death
that OA·LF-1 repaired).

**Unknown providers pass through; they are never forced into the enum.** Measured
2026-08-23 across 2,506 recorded model calls: ``openrouter`` (1,322) and ``ollama``
(4) have no well-known value in the spec at all, and they are two of the three
backends this deployment actually uses. The spec's instruction for that case is to
set a lowercase provider name, which is exactly what we already store — so the
honest mapping is "translate the three that have a standard name, pass the rest
through". Inventing ``openai`` for an OpenAI-compatible gateway would make every
downstream cost dashboard attribute OpenRouter's spend to OpenAI.
"""
from __future__ import annotations

from typing import Any

# ── The attribute keys ────────────────────────────────────────────────────────

OPERATION_NAME = "gen_ai.operation.name"
PROVIDER_NAME = "gen_ai.provider.name"
# Deprecated upstream in favour of `gen_ai.provider.name`, and still what most
# shipped dashboards match on (Grafana's LLM panels, older collector processors).
# Emitted as an alias so a backend written against either spec version reads the
# span; the rot guard asserts the deprecation note still points at its successor,
# so when upstream finally removes the key we are told to drop the alias rather
# than discovering it as a blank column.
SYSTEM = "gen_ai.system"
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
REQUEST_TEMPERATURE = "gen_ai.request.temperature"
USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
CONVERSATION_ID = "gen_ai.conversation.id"
AGENT_NAME = "gen_ai.agent.name"
TOOL_NAME = "gen_ai.tool.name"
TOOL_TYPE = "gen_ai.tool.type"
ERROR_TYPE = "error.type"  # stable (not GenAI-specific)

# Operation values.
OP_CHAT = "chat"
OP_EXECUTE_TOOL = "execute_tool"
OP_INVOKE_AGENT = "invoke_agent"

# ── Provider mapping ──────────────────────────────────────────────────────────

# Our backend name → the spec's well-known `gen_ai.provider.name` value. Only the
# backends that HAVE one appear here; anything else is passed through unchanged
# (see the module docstring — a wrong standard value is worse than a custom one,
# because it is the value a cost dashboard will believe).
_WELL_KNOWN: dict[str, str] = {
    "anthropic": "anthropic",
    "groq": "groq",
    "gemini": "gcp.gemini",
}


def provider_name(backend: str | None) -> str:
    """The `gen_ai.provider.name` value for one of our backend names.

    ``openrouter``/``together``/``ollama``/``lmstudio`` have no well-known value,
    so they travel as themselves — which the spec allows and which keeps a cost
    aggregate grouped by provider truthful.
    """
    if not backend:
        return ""
    b = str(backend).strip().lower()
    return _WELL_KNOWN.get(b, b)


def span_name(operation: str, target: str | None) -> str:
    """The span name the spec prescribes: ``{operation} {target}`` (e.g. ``chat
    gemini-3.1-flash-lite``), falling back to the bare operation when there is no
    target. Readers group by this, so getting it wrong costs aggregation, not
    display."""
    t = (target or "").strip()
    return f"{operation} {t}" if t else operation


# ── Attribute builders ────────────────────────────────────────────────────────

def generation_attrs(
    *,
    backend: str | None,
    model: str | None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    temperature: float | None = None,
    response_model: str | None = None,
    conversation_id: str | None = None,
    error_class: str | None = None,
) -> dict[str, Any]:
    """GenAI attributes for one model call.

    ``prompt_tokens``/``completion_tokens`` of ``None`` are OMITTED, never written
    as 0. Several backends report no usage at all, and a zero is a measurement
    claiming the call was free — the same distinction ``_record_llm_call`` keeps
    in the session log, carried across the wire instead of being flattened at the
    boundary.
    """
    attrs: dict[str, Any] = {OPERATION_NAME: OP_CHAT}
    if (prov := provider_name(backend)):
        attrs[PROVIDER_NAME] = prov
        attrs[SYSTEM] = prov
    if model:
        attrs[REQUEST_MODEL] = str(model)
    if response_model:
        attrs[RESPONSE_MODEL] = str(response_model)
    if prompt_tokens is not None:
        attrs[USAGE_INPUT_TOKENS] = int(prompt_tokens)
    if completion_tokens is not None:
        attrs[USAGE_OUTPUT_TOKENS] = int(completion_tokens)
    if temperature is not None:
        attrs[REQUEST_TEMPERATURE] = float(temperature)
    if conversation_id:
        attrs[CONVERSATION_ID] = str(conversation_id)
    if error_class:
        attrs[ERROR_TYPE] = str(error_class)
    return attrs


def tool_attrs(name: str, *, kind: str | None = None,
               error_class: str | None = None) -> dict[str, Any]:
    """GenAI attributes for a tool span.

    ``span_kind`` is our own vocabulary (``sql.execute``, ``delegation``, …); a
    delegation hop is an *agent invocation* in the spec's terms, not a tool call,
    so it is routed to :func:`agent_attrs` instead of being mislabelled here.
    """
    attrs: dict[str, Any] = {OPERATION_NAME: OP_EXECUTE_TOOL, TOOL_NAME: str(name)}
    if kind:
        attrs[TOOL_TYPE] = str(kind)
    if error_class:
        attrs[ERROR_TYPE] = str(error_class)
    return attrs


def agent_attrs(name: str, *, error_class: str | None = None) -> dict[str, Any]:
    """GenAI attributes for a delegation hop — VA-2's sub-agent calls, which the
    spec models as ``invoke_agent``. This is what lets an external trace viewer
    draw the delegation tree that VA-5's node view draws internally."""
    attrs: dict[str, Any] = {OPERATION_NAME: OP_INVOKE_AGENT}
    if name:
        attrs[AGENT_NAME] = str(name)
    if error_class:
        attrs[ERROR_TYPE] = str(error_class)
    return attrs
