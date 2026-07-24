"""The typed error tail for the answer path (Wave R4) — one shape, one function.

A streamed ``/ask`` turn that fails mid-flight ends with an ``error`` SSE frame carrying
``{"message": str(exc)}``, assembled independently at fifteen call sites. Two things follow
from that, and both are the point of this module:

* **The turn ends in a sentence, not a state.** A rate limit, a wrong API key, a retired
  model id and a timed-out investigation all render as the same red line of prose. The
  user cannot tell which of them is worth retrying, and the UI cannot either — so the
  blessed recovery for the most common failure ("switch model, then retry") is something
  a user has to already know.
* **Wave R1 and R2 built the classification and nothing consumes it.**
  :func:`aughor.llm.provider.classify_provider_error` names bad_key / quota_exhausted /
  rate_limited / model_not_found; :class:`aughor.llm.reliability.StructuredOutputError`
  carries a taxonomy. All of it stops at the provider boundary. This is the wire that
  carries it to the person waiting.

:func:`error_event` is that one function. ``message`` is unchanged from what each site
already produced, so every existing consumer keeps working byte-for-byte; the typed fields
are additive.

**The no-orphan contract.** A failed turn must leave *exactly* the partial the user
watched plus one typed error tail — never a dropped turn (a spinner with no terminal
frame) and never a duplicated one (a retry that appends a second turn). The stream layer
already guarantees "always one terminal frame"; what this adds is the *typed* half, so a
retry can be offered where it can actually work and withheld where it cannot.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The recovery a user can actually perform. Deliberately a tiny closed set — an error
#: taxonomy is only useful if the UI can branch on it, and a UI cannot branch on twelve.
RETRY = "retry"                  # the same request may simply work
SWITCH_MODEL = "switch_model"    # this binding is spent/throttled; another may answer
FIX_CONFIG = "fix_config"        # a human must change a setting first
NONE = ""                        # nothing the user can do from here

#: reason → (retryable, recovery, hint). The reasons are R2's provider classes plus the
#: answer-path's own terminal states, so one vocabulary spans transport and orchestration.
_POLICY: dict[str, tuple[bool, str, str]] = {
    # transport (from aughor.llm.provider.classify_provider_error)
    "rate_limited":     (True,  SWITCH_MODEL, "The model is throttling right now. Retry in a moment, or switch to another model."),
    "quota_exhausted":  (False, SWITCH_MODEL, "This model's allowance is spent for now. Switch to another model — the quota resets on the provider's own schedule."),
    "bad_key":          (False, FIX_CONFIG,   "The API key is missing, wrong, or lacks access. Fix it in Settings → Inference."),
    "model_not_found":  (False, FIX_CONFIG,   "The configured model id is not one this provider serves. Pick another in Settings → Inference."),
    "wrong_endpoint":   (False, FIX_CONFIG,   "The base URL does not look like this provider's API root."),
    "unreachable":      (True,  RETRY,        "Nothing answered at that address. Check the server is running, then retry."),
    "timeout":          (True,  RETRY,        "The model did not answer in time. Retry, or switch to a faster model."),
    "config":           (False, FIX_CONFIG,   "The model client could not be built — usually a missing key."),
    # structured output (from aughor.llm.reliability)
    "truncated":        (True,  SWITCH_MODEL, "The answer hit the output limit before it finished. A model with more headroom will do better."),
    "refusal":          (False, NONE,         "The model declined to answer this question."),
    "schema_mismatch":  (True,  RETRY,        "The model's answer did not match the expected shape. Retrying often clears it."),
    "unparseable":      (True,  RETRY,        "The model's answer could not be read. Retrying often clears it."),
    "empty":            (True,  RETRY,        "The model returned nothing. Retrying often clears it."),
    # answer-path terminal states
    "query_failed":     (False, NONE,         "The query could not be run against this connection."),
    # Used by two callers — a missing investigation and a missing connection — so the
    # wording has to be true for both. A hint that names the wrong noun is worse than a
    # generic one: it sends the user looking in the wrong place.
    "not_found":        (False, NONE,         "That connection or run no longer exists."),
    "invalid_state":    (False, NONE,         "That run is not in a state where this is possible."),
    "budget_exceeded":  (False, NONE,         "The run hit its configured budget and stopped. Raise the budget to go further."),
    "run_timeout":      (True,  RETRY,        "The run exceeded its time limit."),
    "stalled":          (True,  RETRY,        "The run stopped making progress."),
    "cancelled":        (False, NONE,         "The run was cancelled."),
    "unknown":          (True,  RETRY,        "Something went wrong. Retrying is usually safe."),
}

REASONS: tuple[str, ...] = tuple(_POLICY)


def classify(exc: BaseException) -> str:
    """The reason code for ``exc``, in the shared vocabulary.

    Order matters and mirrors the layering: the answer path's own terminal states first
    (they are exact types, so they cannot be confused for anything), then the structured
    taxonomy, then the provider classifier, which is the broadest and would otherwise
    claim cases that belong to the two above.
    """
    name = type(exc).__name__
    if name == "BudgetExceeded":
        return "budget_exceeded"
    if name in ("CancelledError", "TaskCancelled"):
        return "cancelled"
    try:
        from aughor.llm.reliability import StructuredOutputError

        if isinstance(exc, StructuredOutputError):
            return exc.diagnosis.failure
    except Exception:
        logger.debug("answer_errors: structured taxonomy unavailable", exc_info=True)
    try:
        from aughor.llm.provider import classify_provider_error

        cls = classify_provider_error(exc)
        if cls in _POLICY:
            return cls
    except Exception:
        logger.debug("answer_errors: provider classifier unavailable", exc_info=True)
    return "unknown"


def error_event(exc: Optional[BaseException] = None, *, message: str = "",
                reason: str = "") -> dict[str, Any]:
    """The one payload shape for an ``error`` SSE frame.

    ``message`` is what the site already produced and is never rewritten — every existing
    consumer keeps rendering exactly what it rendered before. The typed fields ride
    alongside:

    * ``reason`` — a stable code from :data:`REASONS`
    * ``retryable`` — whether re-sending the SAME request could plausibly succeed
    * ``recovery`` — the one action a user can take (:data:`RETRY`, :data:`SWITCH_MODEL`,
      :data:`FIX_CONFIG`, or none)
    * ``hint`` — that action in a sentence

    Never raises. An error frame is the last thing a failed turn emits; a helper that can
    fail *here* converts a legible failure into a hung spinner, which is the one outcome
    worse than the error itself.
    """
    try:
        code = reason or (classify(exc) if exc is not None else "unknown")
        retryable, recovery, hint = _POLICY.get(code, _POLICY["unknown"])
        text = message or _safe_str(exc) or "Something went wrong."
        return {"message": text, "reason": code, "retryable": retryable,
                "recovery": recovery, "hint": hint}
    except Exception:
        logger.debug("answer_errors: falling back to a bare message", exc_info=True)
        # `message` only — never `_safe_str(exc)` again. The reason we are HERE may be
        # that stringifying the exception is itself what failed, and repeating it in the
        # rescue path is how a fallback stops being one.
        return {"message": message or "Something went wrong.",
                "reason": "unknown", "retryable": True, "recovery": RETRY,
                "hint": _POLICY["unknown"][2]}


def _safe_str(exc: Optional[BaseException]) -> str:
    """``str(exc)``, or ``""`` when even that fails. A pathological ``__str__`` must not
    be able to take down the frame that reports the failure."""
    if exc is None:
        return ""
    try:
        return str(exc)
    except Exception:
        return f"{type(exc).__name__} (unprintable)"
