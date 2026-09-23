"""The output ceiling can be filled by THINKING, and then there is a dial to turn.

`POST /business-profile/rebuild` returned 422 for theLook on 2026-09-23 —
*"structured output truncated: response hit the output token ceiling"* — after 50 seconds
and a full budget of tokens spent producing nothing.

The cause is not a schema too large for the ceiling. Measured on the same deployment:

* a complete stored profile is **~2,072 tokens of content**, against a coder ceiling of
  **8,192** — roughly 6,120 tokens of headroom;
* the model changed. theLook's profile was generated successfully on 2026-09-18 under
  `gemini-3.1-flash-lite`, which averages **259** completion tokens per call. The current
  binding, `deepseek/deepseek-v4.1-flash`, averages **1,286** — 5x — at 27s against 3.7s.

On a reasoning model `max_tokens` bounds reasoning AND content together, so the headroom
is what the model thinks in, and medium effort spends it.

`reliability.TRUNCATED` is deliberately NOT repairable — "the same prompt hits it again" —
and these guards keep that rule intact. The retry here changes the reasoning budget, so it
is a different call; when there is no dial to turn (effort already `low`, or no extras
going out at all) the original diagnosis stands and no request is spent proving the ceiling
is where it was.
"""
from __future__ import annotations

import pytest

from aughor.llm.provider import _retry_at_low_reasoning
from aughor.llm.reliability import EMPTY, TRUNCATED, Diagnosis, StructuredOutputError


def _truncated() -> StructuredOutputError:
    return StructuredOutputError(Diagnosis(TRUNCATED, "response hit the output token ceiling", ""))


def _kwargs(effort: str = "medium") -> dict:
    return {"model": "deepseek/deepseek-v4.1-flash", "max_tokens": 8192,
            "extra_body": {"reasoning": {"effort": effort}}}


def test_it_retries_once_with_reasoning_cut_to_low():
    seen = []

    def call(kw):
        seen.append(kw)
        return ("PROFILE", "RAW")

    got = _retry_at_low_reasoning(_truncated(), _kwargs("medium"), call)
    assert got == ("PROFILE", "RAW")
    assert len(seen) == 1, "exactly one more request, never a ladder"
    assert seen[0]["extra_body"]["reasoning"]["effort"] == "low"


def test_the_ceiling_itself_is_NOT_raised():
    """Raising `max_tokens` would give reasoning more room to expand into and would cost
    it on every call, not on the rare one that truncates. The dial turned is the one that
    caused the overrun."""
    seen = []
    _retry_at_low_reasoning(_truncated(), _kwargs("high"), lambda kw: (seen.append(kw), (1, 2))[1])
    assert seen[0]["max_tokens"] == 8192


def test_already_low_spends_NOTHING():
    """`TRUNCATED` is classified first precisely so we do not pay a request to prove the
    ceiling has not moved. With no dial left, that rule is unchanged."""
    called = []
    assert _retry_at_low_reasoning(_truncated(), _kwargs("low"),
                                   lambda kw: called.append(kw)) is None
    assert called == []


def test_a_backend_sending_no_extras_spends_NOTHING():
    """Anthropic's branch carries no `extra_body` at all — there is no reasoning dial to
    turn there, and a retry would be the identical call the rule forbids."""
    called = []
    kwargs = {"model": "claude", "max_tokens": 8192}
    assert _retry_at_low_reasoning(_truncated(), kwargs, lambda kw: called.append(kw)) is None
    assert called == []


@pytest.mark.parametrize("failure", [EMPTY, "unparseable", "schema_mismatch"])
def test_only_TRUNCATION_earns_the_retry(failure):
    """A validation error is not a budget problem. Re-sending the whole prompt to test a
    hypothesis that is already false is the exact waste Wave R1 removed from this path —
    2 requests per validation failure against a 1,000/day cap."""
    called = []
    exc = StructuredOutputError(Diagnosis(failure, "not a ceiling problem", ""))
    assert _retry_at_low_reasoning(exc, _kwargs("medium"), lambda kw: called.append(kw)) is None
    assert called == []


def test_a_non_typed_exception_is_left_alone():
    called = []
    assert _retry_at_low_reasoning(RuntimeError("network"), _kwargs("medium"),
                                   lambda kw: called.append(kw)) is None
    assert called == []


def test_a_failed_retry_surrenders_to_the_ORIGINAL_error():
    """The caller raises the first diagnosis. If the second attempt also fails, this must
    return None rather than raise the second — otherwise a truncation would surface as
    whatever the retry happened to hit, and the log would blame the wrong thing."""
    def call(kw):
        raise RuntimeError("still truncated")

    assert _retry_at_low_reasoning(_truncated(), _kwargs("medium"), call) is None
