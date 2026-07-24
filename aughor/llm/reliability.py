"""The shared reliability layer for structured LLM calls (Wave R1).

Every structured call in Aughor goes through ``instructor`` with a Pydantic
``response_model``. Instructor is configured with its default single attempt, so
the moment a response does not parse or does not validate it raises — and
``LLMProvider.complete`` treats that raise like any other failure: it walks the
**fallback chain**, spending a whole extra request against a *different*
provider. A stray markdown fence around otherwise-perfect JSON therefore costs a
second provider request, and on the free tier requests — not tokens — are the
scarce resource (ROADMAP §0: the 1,000/day cap is a request cap).

This module inserts the missing step. Four stages, in this order:

1. **Deterministic normalizer first.** Fence stripping, prose stripping, trailing
   commas, Python literals, smart quotes, schema-driven enum case folding, extra-key
   dropping — every one of them a *structural* repair. It never invents a value and
   never guesses at a near-miss (see :func:`_coerce_enums`), because a normalizer
   that guesses turns a loud failure into a quiet wrong answer, which is strictly
   worse than the failover it saves.
2. **Classify before retry.** A canonical taxonomy (:data:`TAXONOMY`) separates the
   failures a second request could fix from the ones it cannot. A *truncation* is the
   load-bearing case: the response stopped because it hit the output ceiling, so
   re-sending the same prompt hits the same ceiling. Today that costs a full fallback
   request to learn nothing; here it fails immediately and says why.
3. **One bounded repair.** At most one — carrying the *specific* validation error,
   capped in output tokens, at temperature 0. Never for a truncation or an empty
   response, never twice.
4. **A deterministic gate in front of optional calls** (:func:`gate`), with a
   "skipped by gate" counter, so the request budget is spent on calls that can change
   an outcome.

Everything here is deterministic and offline: no network, no model, no clock. The
counters land in :mod:`aughor.stats` (``GET /dev/stats``) and, for the salvage path,
in ``obs.session_log`` — so J8 holds and Wave R's cost claims can be *measured*
before/after rather than computed from call-count arithmetic.
"""
from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from aughor.stats import bump

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ── The canonical failure taxonomy ────────────────────────────────────────────
# One vocabulary for "why did this structured call not produce an object". The
# point of naming them is the `repairable` column: three of these six can be
# fixed by asking again, and three provably cannot. Retrying the latter is how a
# free-tier request budget is spent on a guaranteed-identical failure.

TRUNCATED = "truncated"              # hit the output ceiling — the same prompt hits it again
EMPTY = "empty"                      # nothing came back; there is nothing to repair
UNPARSEABLE = "unparseable"          # text, but not JSON even after normalization
SCHEMA_MISMATCH = "schema_mismatch"  # valid JSON, wrong shape — the repairable one
REFUSAL = "refusal"                  # the model declined; a re-ask gets the same refusal
UNKNOWN = "unknown"                  # unrecognised — treated as unrepairable on purpose

TAXONOMY: tuple[str, ...] = (TRUNCATED, EMPTY, UNPARSEABLE, SCHEMA_MISMATCH, REFUSAL, UNKNOWN)

#: The classes where one more request, carrying the specific error, can plausibly help.
#: `UNKNOWN` is deliberately excluded: an unrecognised failure is not evidence that a
#: retry works, and the default for "we do not know" must be the cheap answer.
REPAIRABLE: frozenset[str] = frozenset({UNPARSEABLE, SCHEMA_MISMATCH})

#: Upper bound on the text we will try to normalize. A pathological multi-megabyte
#: blob must not turn a cheap salvage into a CPU stall on the request path; past
#: this size the failure is real and the caller should see it.
_MAX_SALVAGE_CHARS = 400_000

# Refusal wordings, matched only against the FIRST part of the response — the
# markers appear in ordinary prose too ("I cannot compute a margin without cost
# data" is a legitimate narrator sentence, not a refusal to answer).
_REFUSAL_MARKERS = (
    "i'm sorry, but i can", "i am sorry, but i can", "i cannot assist",
    "i can't assist", "i cannot help with", "i can't help with",
    "as an ai language model", "i'm unable to provide", "i am unable to provide",
)
_REFUSAL_WINDOW = 200


@dataclass(frozen=True)
class Diagnosis:
    """Why one structured call failed, in the shared vocabulary.

    ``detail`` is the specific error — the pydantic message, the JSON decoder's
    complaint — and is what a repair request must carry. A repair prompt that says
    only "that was invalid" is the reason repairs need two rounds; one that names
    the field usually needs none.
    """

    failure: str
    detail: str = ""
    text: str = ""                 # the raw model text we recovered, "" when none
    repairs: tuple[str, ...] = ()  # deterministic repairs applied before giving up

    @property
    def repairable(self) -> bool:
        """True when ONE more request, carrying :attr:`detail`, could plausibly fix it."""
        return self.failure in REPAIRABLE and bool(self.text.strip())


class StructuredOutputError(RuntimeError):
    """A structured call that produced no valid object, carrying its :class:`Diagnosis`.

    Raised in place of the opaque provider/instructor exception so the layers above can
    branch on *why* rather than re-deriving it from a message. ``__cause__`` keeps the
    original exception, so nothing is hidden.
    """

    def __init__(self, diagnosis: Diagnosis, cause: Optional[BaseException] = None):
        self.diagnosis = diagnosis
        super().__init__(f"structured output {diagnosis.failure}: {diagnosis.detail}")
        if cause is not None:
            self.__cause__ = cause


def should_failover(diagnosis: Diagnosis) -> bool:
    """Whether walking the fallback chain to a *different provider* can help.

    False for exactly one class today — :data:`TRUNCATED`. The ceiling that cut the
    response off is **ours** (``AUGHOR_MAX_OUTPUT_TOKENS``, sent on every backend), so
    the next provider in the chain generates against the same limit and stops in the
    same place. That failover is a guaranteed-identical failure costing a real request,
    and on a 1,000-request day those are the requests worth not spending.

    Everything else stays failover-eligible on purpose. A refusal, an empty body or an
    unparseable blob are all properties of *that model on that prompt*: a different
    model genuinely may answer, and refusing to try would trade a cheap request for a
    dead investigation. The narrow rule is the honest one.
    """
    return diagnosis.failure != TRUNCATED


def repair_prompt(diagnosis: Diagnosis, response_model: Type[BaseModel]) -> tuple[str, str]:
    """The ``(system, user)`` pair for the single bounded repair request.

    Deliberately not a re-ask: the original task, evidence and instructions are all
    omitted. The model is handed its own broken output plus the exact reason it was
    rejected, and asked only to re-emit it. That keeps the repair's input small (it is
    the cheapest request in the system, not a second copy of the most expensive one)
    and keeps it honest — with no evidence in the prompt there is nothing to
    re-generate a grounded number *from*, so a repair can only re-format what the model
    already said.
    """
    try:
        schema = json.dumps(response_model.model_json_schema(), separators=(",", ":"))[:2000]
    except Exception:
        schema = response_model.__name__
    system = (
        "You fix malformed structured output. You are given a previous response and the "
        "exact reason it was rejected. Re-emit the SAME content as one valid JSON object "
        "matching the schema. Preserve every value that was already present — never "
        "invent, drop or re-estimate a number. Output the JSON object only: no prose, no "
        "markdown fences."
    )
    user = (
        f"Schema:\n{schema}\n\n"
        f"Rejected because: {diagnosis.detail}\n\n"
        f"Previous response:\n{diagnosis.text[:8000]}"
    )
    return system, user


@dataclass
class SalvageResult:
    """The outcome of a deterministic salvage attempt."""

    value: Optional[BaseModel] = None
    diagnosis: Optional[Diagnosis] = None
    repairs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None


# ── Raw-text extraction ───────────────────────────────────────────────────────

def response_text(completion: Any) -> str:
    """The model's raw output text from a completion object, across the shapes the
    three client paths produce.

    Instructor hands the failed completion back on its exceptions, but the payload
    lives somewhere different per mode: message content in JSON mode, a tool call's
    arguments in TOOLS mode (which is what the reasoning-model bindings use — see
    ``_build_gemini_client``), a content block on Anthropic. Reading only
    ``message.content`` would silently return "" for exactly the bindings that fail
    most, so all of them are covered here.
    """
    if completion is None:
        return ""
    if isinstance(completion, str):
        return completion
    try:
        # OpenAI-compatible: choices[0].message.{content | tool_calls[0].function.arguments}
        choices = getattr(completion, "choices", None)
        if choices:
            msg = getattr(choices[0], "message", None)
            if msg is not None:
                calls = getattr(msg, "tool_calls", None)
                if calls:
                    fn = getattr(calls[0], "function", None)
                    args = getattr(fn, "arguments", None)
                    if args:
                        return args if isinstance(args, str) else json.dumps(args)
                content = getattr(msg, "content", None)
                if content:
                    return content if isinstance(content, str) else str(content)
            # Some shims put the text on the choice itself (completions-style).
            text = getattr(choices[0], "text", None)
            if text:
                return str(text)
        # Anthropic: content is a list of blocks (text | tool_use).
        content = getattr(completion, "content", None)
        if isinstance(content, list):
            for block in content:
                inp = getattr(block, "input", None)
                if inp:
                    return json.dumps(inp) if not isinstance(inp, str) else inp
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    return str(text)
        if isinstance(content, str) and content:
            return content
        if isinstance(completion, dict):
            return json.dumps(completion)
    except Exception:
        logger.debug("reliability: could not read completion text", exc_info=True)
    return ""


def _finish_reason(completion: Any) -> str:
    """The provider's own stop reason, lowercased, or ``""``.

    This is the authority on truncation — better than any heuristic over the text,
    and the same lesson as "Google's quotaId is the authority, its retry-in prose
    lies": when the provider states a fact about its own response, believe it.
    """
    try:
        choices = getattr(completion, "choices", None)
        if choices:
            reason = getattr(choices[0], "finish_reason", None) or getattr(
                choices[0], "stop_reason", None)
            if reason:
                return str(reason).lower()
        reason = getattr(completion, "stop_reason", None)   # Anthropic
        if reason:
            return str(reason).lower()
    except Exception:
        logger.debug("reliability: could not read finish_reason", exc_info=True)
    return ""


def _is_truncated(completion: Any, text: str) -> bool:
    """True when the response was cut off at the output ceiling.

    Provider-stated reason first; the text shape only as a second opinion for shims
    that report nothing. Unbalanced-JSON *alone* is not truncation — a model can emit
    malformed JSON at full length — so the fallback demands both an opening brace and
    no closing one, which is the signature of a stream that stopped mid-object.
    """
    if _finish_reason(completion) in ("length", "max_tokens", "max_output_tokens"):
        return True
    body = text.strip()
    if not body:
        return False
    opener = body[0] if body[0] in "{[" else ("{" if "{" in body else "")
    if not opener:
        return False
    closer = "}" if opener == "{" else "]"
    return body.count(opener) > body.count(closer)


# ── Stage 1: the deterministic normalizer ─────────────────────────────────────

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\s*\n?(.*?)(?:\n?```|$)", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
# Python literals only where a JSON value can start: after `:` `,` `[` or the very
# beginning. Bare word-boundary matching would rewrite the *inside of strings*
# ("returns True when …" is real prose in our prompts' example outputs).
_PY_LITERAL_RE = re.compile(r"(^|[:,\[]\s*)(True|False|None)(\s*(?=[,}\]]|$))")
_SMART_QUOTES = {"“": '"', "”": '"', "‘": "'", "’": "'",
                 "„": '"', "″": '"'}


def _strip_fence(text: str) -> Optional[str]:
    """The body of the first fenced block, or None when there is no fence.

    Handles the unterminated fence too (`````json`` with no closing pair),
    which is what a response clipped near the ceiling looks like.
    """
    if "```" not in text:
        return None
    m = _FENCE_RE.search(text)
    if not m:
        return None
    body = m.group(1).strip()
    return body or None


def _extract_json_span(text: str) -> Optional[str]:
    """The outermost balanced JSON object/array embedded in prose, or None.

    Brace counting is string-aware: a `}` inside a string value must not close the
    object. ("Chatty" models wrap the JSON in a sentence — 'Here is the analysis:
    {...} Let me know if…' — and a naive `text[first:last+1]` slice breaks the
    moment the trailing prose contains a brace.)
    """
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    span = text[start:i + 1]
                    return span if span != text.strip() else None
    return None


def _loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def parse_payload(text: str) -> tuple[Optional[Any], list[str]]:
    """Parse model text into a JSON payload, applying text-level repairs as needed.

    Returns ``(payload, repairs)``. ``repairs`` names only the transforms that were
    actually applied *and* needed — an honest list, because it is the evidence for
    the "repair calls saved" counter. Clean JSON returns ``(payload, [])`` and
    touches nothing.
    """
    repairs: list[str] = []
    body = (text or "").strip()
    if not body:
        return None, repairs
    if len(body) > _MAX_SALVAGE_CHARS:
        return None, repairs

    payload = _loads(body)
    if payload is not None:
        return payload, repairs

    # Each step is tried in isolation-then-accumulation order: cheapest and most
    # common first (a fence), structural next, lexical last.
    for label, transform in (
        ("fence", _strip_fence),
        ("prose", _extract_json_span),
    ):
        candidate = transform(body)
        if candidate:
            parsed = _loads(candidate)
            repairs.append(label)
            if parsed is not None:
                return parsed, repairs
            body = candidate      # keep the narrowed span for the lexical passes

    if any(q in body for q in _SMART_QUOTES):
        for bad, good in _SMART_QUOTES.items():
            body = body.replace(bad, good)
        repairs.append("smart_quotes")
        parsed = _loads(body)
        if parsed is not None:
            return parsed, repairs

    if _TRAILING_COMMA_RE.search(body):
        body = _TRAILING_COMMA_RE.sub(r"\1", body)
        repairs.append("trailing_comma")
        parsed = _loads(body)
        if parsed is not None:
            return parsed, repairs

    if _PY_LITERAL_RE.search(body):
        body = _PY_LITERAL_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2).lower().replace('none', 'null')}{m.group(3)}",
            body)
        repairs.append("python_literals")
        parsed = _loads(body)
        if parsed is not None:
            return parsed, repairs

    # Last resort: a Python dict/list *repr* (single quotes throughout). literal_eval
    # evaluates literals only — no names, no calls — so this cannot execute model
    # output. Anything richer than a container of literals raises and we give up.
    if body[:1] in "{[" and "'" in body:
        try:
            parsed = ast.literal_eval(body)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            repairs.append("python_repr")
            return parsed, repairs

    return None, repairs


# ── Schema-driven coercion (still deterministic, still no guessing) ───────────

def _enum_options(schema: dict, defs: dict) -> Optional[list[str]]:
    """The allowed string values for a field schema, or None if it is not an enum.
    Resolves one level of ``$ref``/``anyOf`` — the shapes ``Enum`` and
    ``Optional[Enum]`` produce."""
    if not isinstance(schema, dict):
        return None
    enum = schema.get("enum")
    if isinstance(enum, list) and all(isinstance(v, str) for v in enum):
        return enum
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return _enum_options(defs.get(ref.rsplit("/", 1)[-1], {}), defs)
    for branch in schema.get("anyOf", []) or []:
        found = _enum_options(branch, defs)
        if found:
            return found
    return None


def _fold(value: str) -> str:
    """Case/separator-insensitive form used to match an enum value.

    Deliberately NOT a fuzzy match. ``"HIGH"`` → ``"high"`` and ``"not_applicable"``
    → ``"not applicable"`` are the same token written differently; ``"hgih"`` is a
    different token and must fail loudly. A normalizer that closes that last gap is
    guessing, and a guess here becomes a wrong answer that no downstream guard can
    see — the exact trade the deterministic-first thesis refuses.
    """
    return re.sub(r"[\s_\-]+", "", value.strip().lower())


def coerce_payload(payload: Any, response_model: Type[BaseModel]) -> tuple[Any, list[str]]:
    """Schema-driven coercions on a parsed payload. Returns ``(payload, repairs)``.

    Two moves, both structural:

    * **enum case folding** — a model that answers ``"HIGH"`` for a
      ``Literal["high","medium","low"]`` produced the right token in the wrong case.
    * **extra-key dropping** — only when the model *forbids* extras (pydantic ignores
      them otherwise, so dropping unconditionally would be a no-op that lies in the
      repairs list).
    """
    if not isinstance(payload, dict):
        return payload, []
    try:
        schema = response_model.model_json_schema()
    except Exception:
        logger.debug("reliability: no JSON schema for %r", response_model, exc_info=True)
        return payload, []

    repairs: list[str] = []
    defs = schema.get("$defs", {}) or {}
    props = schema.get("properties", {}) or {}
    out = dict(payload)

    for key, sub in props.items():
        if key not in out:
            continue
        options = _enum_options(sub, defs)
        if not options:
            continue
        value = out[key]
        if not isinstance(value, str) or value in options:
            continue
        folded = {_fold(o): o for o in options}
        match = folded.get(_fold(value))
        if match is not None:
            out[key] = match
            repairs.append(f"enum_case:{key}")

    if schema.get("additionalProperties") is False:
        extra = [k for k in out if k not in props]
        if extra:
            for k in extra:
                out.pop(k, None)
            repairs.append("extra_keys")

    return out, repairs


# ── Stage 2: classify, then salvage ───────────────────────────────────────────

def _validation_detail(exc: BaseException) -> str:
    """A compact, field-naming description of a validation failure — what a repair
    request must carry. Capped: the prompt this feeds is itself budgeted.

    Digs for the underlying :class:`ValidationError` rather than stringifying whatever
    wrapper caught it. Instructor's own wrapper stringifies to a bare
    ``<failed_attempts…>`` repr, which names no field at all — and a repair prompt that
    says only "that was invalid" is the reason a repair needs two rounds instead of one.
    """
    for candidate in (exc, getattr(exc, "__cause__", None), *(
            getattr(a, "exception", None) for a in (getattr(exc, "failed_attempts", None) or []))):
        if isinstance(candidate, ValidationError):
            parts = []
            for err in candidate.errors()[:6]:
                loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
                parts.append(f"{loc}: {err.get('msg', 'invalid')}")
            return "; ".join(parts)[:600]
    text = str(exc).strip()
    return text[:600] if text and not text.startswith("<") else "the response did not match the schema"


def _looks_like_refusal(text: str) -> bool:
    head = text.strip()[:_REFUSAL_WINDOW].lower()
    return any(marker in head for marker in _REFUSAL_MARKERS)


def classify(exc: BaseException, *, completion: Any = None, text: str = "") -> Diagnosis:
    """Name the structured-output failure behind ``exc``, without asking the model.

    Ordering is load-bearing. Truncation is checked FIRST because a truncated
    response also fails to parse and also fails to validate: classified by its
    downstream symptom it looks repairable, and we would spend a request proving
    that the output ceiling is still where it was.
    """
    raw = text or response_text(completion if completion is not None
                                else getattr(exc, "last_completion", None)
                                or getattr(exc, "raw_response", None))
    if type(exc).__name__ == "IncompleteOutputException" or _is_truncated(completion, raw):
        return Diagnosis(TRUNCATED, "response hit the output token ceiling", raw)
    if not raw.strip():
        return Diagnosis(EMPTY, "the model returned no content", "")
    if _looks_like_refusal(raw):
        return Diagnosis(REFUSAL, "the model declined to answer", raw)

    payload, repairs = parse_payload(raw)
    if payload is None:
        return Diagnosis(UNPARSEABLE, "response is not valid JSON", raw, tuple(repairs))
    return Diagnosis(SCHEMA_MISMATCH, _validation_detail(exc), raw, tuple(repairs))


def salvage(exc: BaseException, response_model: Type[T], *,
            completion: Any = None) -> SalvageResult:
    """Try to recover a valid ``response_model`` from a failed call — deterministically,
    with **zero additional requests**.

    This is the whole point of stage 1: when it succeeds, the caller neither issues a
    repair request nor walks the fallback chain to a second provider. When it fails,
    the returned :class:`Diagnosis` tells the caller whether one repair request is
    worth spending.
    """
    raw_source = (completion if completion is not None
                  else getattr(exc, "last_completion", None)
                  or getattr(exc, "raw_response", None))
    raw = response_text(raw_source)
    diagnosis = classify(exc, completion=raw_source, text=raw)
    if diagnosis.failure in (TRUNCATED, EMPTY, REFUSAL):
        bump(f"llm.failure.{diagnosis.failure}")
        return SalvageResult(diagnosis=diagnosis)

    payload, repairs = parse_payload(raw)
    if payload is None:
        bump(f"llm.failure.{UNPARSEABLE}")
        return SalvageResult(diagnosis=diagnosis, repairs=repairs)

    payload, coercions = coerce_payload(payload, response_model)
    repairs = repairs + coercions
    try:
        value = response_model.model_validate(payload)
    except ValidationError as verr:
        bump(f"llm.failure.{SCHEMA_MISMATCH}")
        return SalvageResult(
            diagnosis=Diagnosis(SCHEMA_MISMATCH, _validation_detail(verr), raw, tuple(repairs)),
            repairs=repairs)

    bump("llm.salvage.repaired")
    for r in repairs:
        bump(f"llm.salvage.repair.{r.split(':')[0]}")
    logger.info("llm: salvaged a %s response deterministically (%s) — no repair request spent",
                response_model.__name__, ", ".join(repairs) or "no repair needed")
    return SalvageResult(value=value, repairs=repairs)


# ── Stage 4: the deterministic gate in front of optional calls ────────────────

def gate(name: str, allow: bool, *, reason: str = "") -> bool:
    """Record a deterministic decision about whether an *optional* LLM call runs.

    The leverage gate applied to the request budget: a follow-up detector, a digest
    trigger or a classifier that a cheap local predicate can settle should not spend
    one of the day's requests. Callers keep their own predicate — this names the
    decision, counts it, and makes "how many requests did the gates save today" a
    query (``GET /dev/stats`` → ``llm.gate.skipped.*``) instead of an estimate.

    Returns ``allow`` unchanged, so it reads inline::

        if gate("ask.followups", bool(rows) and len(rows) > 1):
            ...
    """
    key = name.replace(" ", "_")
    if allow:
        bump(f"llm.gate.allowed.{key}")
    else:
        bump(f"llm.gate.skipped.{key}")
        logger.debug("llm: optional call %s skipped by gate%s",
                     name, f" ({reason})" if reason else "")
    return allow
