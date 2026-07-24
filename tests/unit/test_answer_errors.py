"""Wave R4 — the typed error tail on the answer path.

A streamed turn that fails used to end in a sentence: fifteen sites each assembling
``{"message": str(e)}``, so a rate limit, a wrong API key, a retired model id and a
timed-out run all reached the user as the same red line — and every bit of the
classification Waves R1 and R2 built stopped at the provider boundary.

Two contracts:

* **`message` is never rewritten.** Each site's existing text is preserved exactly, so
  every consumer that reads only `message` is byte-identical. The typed fields ride
  alongside.
* **`retryable` must be honest in BOTH directions.** Offering a retry that cannot work
  wastes a request against the very limit that just refused us (the #200 spiral); refusing
  one that would work strands the user on a failure they could clear themselves.
"""
from __future__ import annotations

import pytest

from aughor.agent import answer_errors as AE


# ── classification ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("429 Too Many Requests: rate limit exceeded", "rate_limited"),
    ("RESOURCE_EXHAUSTED: GenerateRequestsPerDayPerProject", "quota_exhausted"),
    ("Incorrect API key provided: sk-xxx", "bad_key"),
    ("The model `x/y:free` does not exist or you do not have access", "model_not_found"),
    ("Connection refused: localhost:11434", "unreachable"),
    ("Request timed out after 30s", "timeout"),
    ("something nobody has ever seen", "unknown"),
])
def test_transport_failures_reach_the_user_classified(message, expected):
    """R2 built this classifier and nothing consumed it. This is the wire."""
    assert AE.classify(Exception(message)) == expected


def test_a_structured_output_failure_keeps_its_taxonomy():
    from aughor.llm.reliability import Diagnosis, StructuredOutputError, TRUNCATED

    exc = StructuredOutputError(Diagnosis(TRUNCATED, "hit the ceiling"))
    assert AE.classify(exc) == "truncated"


def test_the_answer_paths_own_terminal_states_win_over_the_broad_classifier():
    """Ordering mirrors the layering: an exact type cannot be mistaken for anything, and
    the provider classifier is broad enough to claim cases that are not its own."""
    class BudgetExceeded(Exception):
        pass

    assert AE.classify(BudgetExceeded("token budget exceeded")) == "budget_exceeded"


def test_every_reason_carries_a_policy():
    """A reason with no policy would silently fall through to `unknown`, which says
    'retry' — the worst default for a failure that cannot be retried."""
    for reason in AE.REASONS:
        assert reason in AE._POLICY, reason
        retryable, recovery, hint = AE._POLICY[reason]
        assert isinstance(retryable, bool) and hint
        assert recovery in (AE.RETRY, AE.SWITCH_MODEL, AE.FIX_CONFIG, AE.NONE)


# ── the retryable contract, in both directions ────────────────────────────────

@pytest.mark.parametrize("reason", ["bad_key", "model_not_found", "quota_exhausted",
                                    "wrong_endpoint", "config", "budget_exceeded",
                                    "not_found", "invalid_state", "refusal", "cancelled",
                                    "query_failed"])
def test_a_failure_a_retry_cannot_fix_never_offers_one(reason):
    """Offering a retry here spends a request against the very limit that refused us —
    the #200 spiral — or asks a user to click a button that cannot work."""
    assert AE.error_event(message="x", reason=reason)["retryable"] is False


@pytest.mark.parametrize("reason", ["rate_limited", "timeout", "unreachable", "stalled",
                                    "run_timeout", "unparseable", "schema_mismatch",
                                    "empty", "unknown"])
def test_a_clearable_failure_does_offer_a_retry(reason):
    """The other direction, and it matters just as much: refusing a retry that would work
    strands the user on a failure they could clear themselves."""
    assert AE.error_event(message="x", reason=reason)["retryable"] is True


def test_a_spent_quota_says_switch_model_rather_than_retry():
    """The blessed recovery. Retrying a day-scale allowance is the one move guaranteed to
    fail; another binding is the move that works."""
    ev = AE.error_event(Exception("RESOURCE_EXHAUSTED: GenerateRequestsPerDay"))
    assert ev["retryable"] is False and ev["recovery"] == AE.SWITCH_MODEL
    assert "switch" in ev["hint"].lower()


def test_a_truncation_says_switch_model_too():
    """R1 proved a truncation recurs on every binding at OUR ceiling — so the recovery is
    a model with more headroom, not the same request again."""
    from aughor.llm.reliability import Diagnosis, StructuredOutputError, TRUNCATED

    ev = AE.error_event(StructuredOutputError(Diagnosis(TRUNCATED, "ceiling")))
    assert ev["recovery"] == AE.SWITCH_MODEL


def test_a_bad_key_sends_the_user_to_settings_not_to_a_retry_button():
    ev = AE.error_event(Exception("Incorrect API key provided"))
    assert ev["recovery"] == AE.FIX_CONFIG and ev["retryable"] is False


# ── the message contract ──────────────────────────────────────────────────────

def test_the_existing_message_is_never_rewritten():
    """Every consumer that reads only `message` must be byte-identical."""
    assert AE.error_event(message="Investigation not found",
                          reason="not_found")["message"] == "Investigation not found"
    assert AE.error_event(Exception("boom"))["message"] == "boom"


def test_an_explicit_reason_beats_the_classifier():
    """A site that KNOWS its terminal state should not have its text re-guessed from
    prose — 'Investigation timed out' is a run timeout, not a model timeout."""
    ev = AE.error_event(message="Investigation timed out after 600s.", reason="run_timeout")
    assert ev["reason"] == "run_timeout"


def test_error_event_never_raises():
    """An error frame is the last thing a failed turn emits. A helper that can fail HERE
    turns a legible failure into a hung spinner — the one outcome worse than the error."""
    class Hostile(Exception):
        def __str__(self):
            raise RuntimeError("even __str__ fails")

    ev = AE.error_event(Hostile())
    assert ev["message"] and ev["reason"] and "retryable" in ev


def test_a_bare_call_still_produces_a_complete_event():
    ev = AE.error_event()
    assert set(ev) == {"message", "reason", "retryable", "recovery", "hint"}
    assert ev["message"] and ev["hint"]


# ── the router's one choke point ──────────────────────────────────────────────

def test_no_error_frame_is_assembled_by_hand_any_more():
    """The T2.4 principle applied to the outbound error path: ONE function decides the
    shape. Fifteen hand-assembled copies is how the classification went missing from all
    fifteen at once."""
    import pathlib
    import re

    src = pathlib.Path("aughor/routers/investigations.py").read_text()
    bare = re.findall(r'_sse\(\s*"error"\s*,\s*\{', src)
    assert not bare, f"{len(bare)} error frame(s) built inline — route them through _error_event"


def test_every_error_frame_carries_the_typed_fields():
    from aughor.routers.investigations import _error_event

    ev = _error_event(Exception("429 rate limit"))
    assert ev["reason"] == "rate_limited" and ev["recovery"] == AE.SWITCH_MODEL
    assert _error_event(message="plain", reason="not_found")["message"] == "plain"


# ── the message a human actually reads ────────────────────────────────────────

_DUMP = ('<failed_attempts>\n\n<generation number="1">\n<exception>\n    Connection error.\n'
         '</exception>\n<completion>\nNone\n</completion>\n</generation>\n</failed_attempts>\n'
         '<last_exception>\nConnection error.\n</last_exception>')


def test_a_library_attempt_dump_is_unwrapped_to_its_cause():
    """Found by LOOKING at a failed turn in the browser: the most prominent line read
    `<failed_attempts> <generation number="1"> <exception> Connection error. </exception> …`
    with the actual cause — two words — buried inside it."""
    assert AE.legible(_DUMP) == "Connection error."


def test_the_dump_is_unwrapped_wherever_it_enters():
    """Both doors: an exception the classifier stringifies, and an explicit `message=`
    from a call site."""
    assert AE.error_event(Exception(_DUMP))["message"] == "Connection error."
    assert AE.error_event(message=_DUMP, reason="unreachable")["message"] == "Connection error."


def test_distinct_causes_across_attempts_are_all_kept():
    """Unwrapping must not silently pick one attempt — a chain that failed two DIFFERENT
    ways is telling you something a single line would hide."""
    two = ("<failed_attempts><exception>Connection error.</exception>"
           "<exception>Read timed out.</exception></failed_attempts>")
    assert AE.legible(two) == "Connection error. · Read timed out."


def test_an_ordinary_message_is_returned_untouched():
    """The narrowing is 'never replaced', not 'never touched' — every non-dump message
    must come through exactly as its site wrote it."""
    for msg in ("Investigation not found", "Could not connect: no such file",
                "Answer stopped — token budget exceeded.", ""):
        assert AE.legible(msg) == msg


def test_an_unrecognised_dump_is_kept_whole_rather_than_emptied():
    """If the shape is not understood, showing scaffolding beats showing nothing."""
    odd = "<failed_attempts>something we do not parse</failed_attempts>"
    assert AE.legible(odd) == odd


def test_unwrapping_never_raises():
    assert AE.legible(None) == "" and AE.legible("") == ""


# ── the real route ────────────────────────────────────────────────────────────

def test_a_failed_ask_ends_in_one_typed_error_frame():
    """End to end through the real ASGI app: a `/ask` that cannot run must end in exactly
    one terminal frame, and that frame must be classified.

    This is also where the classification was caught being WRONG: a missing connection
    fell through to `unknown`, whose default is retryable=True — telling the user that
    re-asking against a connection that does not exist is "usually safe". It is not; it
    fails identically every time."""
    import json

    from fastapi.testclient import TestClient

    from aughor.api import app

    r = TestClient(app).post("/ask", json={"question": "what were sales last month?",
                                           "connection_id": "no-such-connection-xyz"})
    assert r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", "")
    frames = [json.loads(ln[len("data: "):]) for ln in r.text.splitlines()
              if ln.startswith("data: ")]
    errors = [f for f in frames if f.get("type") == "error"]
    assert len(errors) == 1, f"expected exactly one error frame, got {len(errors)}"

    e = errors[0]
    assert "no-such-connection-xyz" in e["message"]        # the original text survives
    assert e["reason"] == "not_found"
    assert e["retryable"] is False                          # never offer a retry that cannot work
    assert e["hint"]
