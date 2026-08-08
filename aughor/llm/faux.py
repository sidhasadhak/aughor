"""The faux LLM backend — scripted completions for tests (unified plan Layer 0.1).

Every structured completion in Aughor funnels through ``LLMProvider._complete_on``,
which only ever touches ``client.chat.completions.create_with_completion(**kwargs)``
on the OpenAI-compatible path. This module supplies that client: a process-global
queue of *scripted* responses served in order, so a test exercises the REAL provider
stack — metering, the per-call session-log record, the deterministic salvage layer,
the failure taxonomy, the failover decision — with zero network and zero spend.

Why a backend and not another per-file fake: the suite has ~30 hand-rolled
``def complete(...)`` fakes patched in at 58 call sites, three of which still fall
through to the real provider on an unmodelled call (the exact failure recorded in
``tests/conftest.py`` — a fake that falls through races network latency under load
and spends real requests). This one is loud instead: an exhausted queue raises
:class:`FauxResponsesExhausted`, and that exception is marked ``never_failover`` so
the chain can never answer in its place.

Usage (via the ``faux_llm`` fixture in ``tests/conftest.py``)::

    def test_something(faux_llm):
        faux_llm.set_responses(['{"answer": "42"}'])
        ... code under test ...
        assert faux_llm.calls()[0].system.startswith("You are")

Response items, in order of fidelity:

* ``str``   — the model's raw text. Parsed and validated exactly as strictly as
  instructor would (``json.loads`` + ``model_validate``); invalid text raises the
  same name-matched exception shape the real path produces, carrying the completion,
  so the salvage layer sees precisely what it sees in production. A fenced-JSON
  string therefore tests the zero-request deterministic repair for free.
* ``dict``  — a parsed payload, validated into the call's ``response_model``.
* ``BaseModel`` instance — returned as-is (type-checked against ``response_model``).
* ``BaseException`` instance — raised as-is (the test owns classification).
* :class:`FauxTruncation` / :class:`FauxRateLimit` / :class:`FauxQuotaExhausted`
  — the transport failures the reliability layer classifies, pre-shaped.
* callable — a factory ``(system, user, role, model, call_index) -> item``; the
  returned item is processed by the same rules. This is the payoff form: the test
  receives the exact prompt the code built and controls the reply.

Exception fidelity: the classifiers in ``aughor/llm/provider.py`` match failures by
``type(exc).__name__`` / message / ``status_code`` *on purpose* (see
``_STRUCTURED_EXC_TYPES``: "named by string so this module … does not depend on the
exception module's layout"), and no app code catches instructor/openai classes by
identity (grepped 2026-08-08). The local shims below are therefore exactly as
faithful as the real classes to every consumer in this codebase, and immune to
instructor moving its exception module again.

Registration: the ``faux`` backend is wired in ``LLMProvider.__init__`` and
``_DEFAULT_MODELS`` but deliberately NOT in ``BACKENDS`` — that tuple is the
operator-facing registry (Settings → Inference dropdown, the CLI ``--backend``
choices via its literal mirror, fallback-chain eligibility), and a scripted backend
must not be selectable there. Select it with ``AUGHOR_BACKEND=faux`` (the fixture
does). Model ids resolve tiers deterministically: ``faux-coder`` / ``faux-narrator``
/ ``faux-fast`` get the BASELINE floor (unknown-model rule), and any ``faux-capable``
model id is declared CAPABLE in ``profile.py`` — so tier-dependent defaults
(``max_output_tokens``, reasoning effort, linker budgets) are testable in both
directions.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ValidationError

#: A model id whose tier is declared CAPABLE (see profile._FAMILY_TIERS) — pin it in
#: a test (``get_provider(role, model=CAPABLE_MODEL)`` or the runtime config) to
#: exercise the capable-tier budgets deterministically.
CAPABLE_MODEL = "faux-capable"


class FauxResponsesExhausted(AssertionError):
    """The code under test made an LLM call the test did not script.

    An ``AssertionError`` because it is a TEST bug, never a transport condition —
    and ``never_failover`` so ``LLMProvider.complete`` re-raises it instead of
    spending a fallback request answering in the faux backend's place (the silent
    fall-through this backend exists to kill). The message deliberately avoids the
    words the transport classifiers match on (rate/quota/timeout wordings).
    """

    never_failover = True


class InstructorRetryException(Exception):
    """Name-matched shim for instructor's structured-output failure (see module
    docstring for why a shim is exactly as faithful here as the real class).
    Carries ``last_completion`` — the attribute the salvage layer reads."""

    def __init__(self, message: str, last_completion: Any = None):
        super().__init__(message)
        self.last_completion = last_completion


class IncompleteOutputException(Exception):
    """Name-matched shim for instructor's truncation failure. ``reliability.classify``
    keys on this exact type name FIRST, before any completion heuristic."""

    def __init__(self, message: str, last_completion: Any = None):
        super().__init__(message)
        self.last_completion = last_completion


class RateLimitError(Exception):
    """Name-matched shim for openai's 429. ``_is_rate_limited`` matches the type
    name and ``status_code``; ``_is_transient`` matches the type name — so the
    retry ladder treats it exactly like the real thing (budget: ONE retry)."""

    status_code = 429


@dataclass(frozen=True)
class FauxToolCall:
    """The model answering through a TOOL CALL rather than message content.

    Two things need this. Today: instructor's TOOLS mode is how several real bindings
    deliver structured output (``_build_gemini_client`` defaults to it; the ollama
    reasoning models use it to keep ``<think>`` tokens out of the JSON), and
    ``reliability.response_text`` has a whole branch for reading
    ``tool_calls[0].function.arguments`` that no test could reach while the faux
    backend only ever set ``content``.

    And next: a tool-choosing loop needs to script *which* tool the model picked.
    ``name`` carries that choice, so a test can assert the model was offered a
    pipeline and took it.

    ``payload`` is the arguments — a dict, or a raw string when the test wants to
    exercise malformed arguments. With a ``response_model`` in play it is validated
    exactly as content would be, because that is what instructor does with them.
    """

    payload: Any
    name: str = "structured_output"
    id: str = "call_faux_1"


@dataclass(frozen=True)
class FauxTruncation:
    """A response cut off at the output ceiling: ``finish_reason="length"`` plus a
    (typically unbalanced) partial body. Classifies TRUNCATED — the class that must
    never failover and never repair."""

    text: str = '{"partial": "the response stopped mid-'


@dataclass(frozen=True)
class FauxRateLimit:
    """A 429 the retry ladder sees as transient. NOTE: unless the test pins
    ``AUGHOR_LLM_MAX_RETRIES=0``, the ladder spends its one rate-limit retry with a
    ~2s backoff sleep — script a success behind it to model a recovering endpoint."""

    message: str = "429 rate limit exceeded, too many requests"


@dataclass(frozen=True)
class FauxQuotaExhausted:
    """A day-scale allowance failure (``_QUOTA_EXHAUSTED_MSGS`` wording) — routed to
    the fallback chain immediately, never the retry ladder, and puts the backend in
    quota cooldown exactly like the real thing."""

    message: str = "429 you have hit your requests per day allowance"


@dataclass(frozen=True)
class FauxCall:
    """One recorded completion request — what the code under test actually asked."""

    index: int
    role: str
    model: str
    system: str
    user: str
    response_model: Optional[type]
    kwargs: dict = field(repr=False, default_factory=dict)


_LOCK = threading.Lock()          # provider calls arrive from worker threads
_QUEUE: list[Any] = []
_CALLS: list[FauxCall] = []


def set_responses(items: Iterable[Any]) -> None:
    """Replace the scripted-response queue (the call log is left intact)."""
    with _LOCK:
        _QUEUE[:] = list(items)


def push_responses(*items: Any) -> None:
    """Append to the queue without disturbing what is already scripted."""
    with _LOCK:
        _QUEUE.extend(items)


def calls() -> tuple[FauxCall, ...]:
    """Every completion request served (or refused) so far, in order."""
    with _LOCK:
        return tuple(_CALLS)


def pending() -> int:
    """Scripted responses not yet consumed — assert 0 to prove the code under test
    made exactly the calls the script modelled."""
    with _LOCK:
        return len(_QUEUE)


def reset() -> None:
    """Clear the queue and the call log (the fixture does this on both sides)."""
    with _LOCK:
        _QUEUE.clear()
        _CALLS.clear()


def build_client(role: str) -> "FauxClient":
    """The client ``LLMProvider.__init__`` binds for ``backend="faux"``."""
    return FauxClient(role)


class FauxClient:
    """Duck-types the one surface ``_complete_on`` uses on an OpenAI-compatible
    client: ``.chat.completions.create_with_completion(**kwargs)`` (and ``.create``
    for the repair path's older-client fallback). Partial streaming is deliberately
    unsupported — ``complete_streaming`` already self-heals onto the blocking
    ``complete()``, which consumes one scripted response as normal."""

    def __init__(self, role: str):
        self.role = role
        self.chat = SimpleNamespace(completions=_FauxCompletions(role))


class _FauxCompletions:
    def __init__(self, role: str):
        self._role = role

    def create_with_completion(self, **kwargs):
        return _serve(self._role, kwargs)

    def create(self, **kwargs):
        return _serve(self._role, kwargs)[0]


def _messages_parts(kwargs: dict) -> tuple[str, str]:
    system, user = "", ""
    for msg in kwargs.get("messages") or []:
        content = msg.get("content", "")
        if msg.get("role") == "system" and not system:
            system = content
        elif msg.get("role") == "user" and not user:
            user = content
    return system, user


def _completion(text: str, *, system: str, user: str,
                finish_reason: str = "stop",
                tool_call: Optional["FauxToolCall"] = None) -> SimpleNamespace:
    """A raw completion shaped the way ``reliability.response_text`` /
    ``_finish_reason`` / ``provider._extract_usage`` read it. Usage is a crude
    chars//4 estimate — nonzero on purpose, so metering paths are exercised with
    real-looking numbers instead of silent zeros.

    With ``tool_call``, the payload rides ``tool_calls[0].function.arguments`` and
    ``content`` is None — the shape instructor's TOOLS mode produces, which is what
    the reasoning-model bindings actually use (gemini by default, and any ollama
    model matching the tools list). Until now the faux backend could only speak
    through ``content``, so that whole extraction branch was unreachable in a test.
    """
    _tool_calls = None
    if tool_call is not None:
        _tool_calls = [SimpleNamespace(
            id=tool_call.id, type="function",
            function=SimpleNamespace(name=tool_call.name, arguments=text),
        )]
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=None if tool_call else text,
                                    tool_calls=_tool_calls),
            finish_reason=finish_reason,
            text=None,
        )],
        usage=SimpleNamespace(prompt_tokens=max(1, (len(system) + len(user)) // 4),
                              completion_tokens=max(1, len(text) // 4)),
        stop_reason=None,
    )


def _serve(role: str, kwargs: dict):
    system, user = _messages_parts(kwargs)
    model = str(kwargs.get("model") or "")
    response_model = kwargs.get("response_model")
    with _LOCK:
        index = len(_CALLS)
        _CALLS.append(FauxCall(index=index, role=role, model=model, system=system,
                               user=user, response_model=response_model,
                               kwargs=dict(kwargs)))
        if not _QUEUE:
            raise FauxResponsesExhausted(
                f"faux backend: no scripted response left for call #{index} "
                f"(role={role!r}, model={model!r}, "
                f"response_model={getattr(response_model, '__name__', response_model)!r}). "
                "The code under test made a completion the test did not model — "
                "script it with set_responses([...]) rather than letting it "
                "fall through."
            )
        item = _QUEUE.pop(0)

    if callable(item) and not isinstance(item, (type, BaseModel, BaseException)):
        item = item(system, user, role, model, index)
    return _realize(item, response_model, system=system, user=user)


def _realize(item: Any, response_model: Optional[type], *, system: str, user: str):
    """Turn one scripted item into ``(validated_object, raw_completion)`` — or raise
    the same failure shape the real transport would."""
    if isinstance(item, BaseException):
        raise item
    if isinstance(item, FauxTruncation):
        completion = _completion(item.text, system=system, user=user,
                                 finish_reason="length")
        raise IncompleteOutputException(
            "faux: response hit the output token ceiling", completion)
    if isinstance(item, FauxRateLimit):
        raise RateLimitError(item.message)
    if isinstance(item, FauxQuotaExhausted):
        raise RateLimitError(item.message)
    if isinstance(item, BaseModel):
        if response_model is not None and not isinstance(item, response_model):
            raise FauxResponsesExhausted(
                f"faux backend: scripted a {type(item).__name__} where the code "
                f"under test asked for {getattr(response_model, '__name__', response_model)} "
                "— the script and the call sequence have drifted."
            )
        text = item.model_dump_json()
        return item, _completion(text, system=system, user=user)

    tool_call: Optional[FauxToolCall] = None
    if isinstance(item, FauxToolCall):
        tool_call = item
        item = item.payload

    if isinstance(item, dict):
        text = json.dumps(item)
        payload: Any = item
    else:
        text = str(item)
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
    completion = _completion(text, system=system, user=user, tool_call=tool_call)
    if response_model is None:
        return text, completion
    if payload is not None:
        try:
            return response_model.model_validate(payload), completion
        except ValidationError as verr:
            raise InstructorRetryException(str(verr), completion) from verr
    # Not strict JSON — exactly what instructor rejects; the salvage layer decides
    # whether a fence-strip/normalize recovers it, same as production.
    raise InstructorRetryException(
        "faux: response is not valid JSON for the response_model", completion)


#: Everything a test needs, importable as one name (the fixture returns this module).
__all__ = [
    "FauxResponsesExhausted", "FauxTruncation", "FauxRateLimit",
    "FauxQuotaExhausted", "FauxCall", "FauxClient", "FauxToolCall", "CAPABLE_MODEL",
    "set_responses", "push_responses", "calls", "pending",
    "reset", "build_client",
]
