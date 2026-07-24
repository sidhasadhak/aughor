"""Wave R1 — the structured-call reliability layer.

Two contracts are under test, and they pull in opposite directions:

* **Recover what is recoverable.** A response that is correct JSON wrapped in a
  markdown fence must not cost a second request against a second provider.
* **Never guess.** Salvage that quietly accepts a mangled object is worse than the
  failover it saves — a loud failure gets a better model; a plausible wrong answer
  gets shipped. Every "must still fail" test below is load-bearing.

Plus the classification contract: a failure another request cannot fix must not
become another request.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Literal, Optional

import pytest
from pydantic import BaseModel

from aughor.llm import reliability as R
from aughor.llm.provider import LLMProvider


class Verdict(BaseModel):
    verdict: Literal["high", "medium", "low"]
    note: str
    score: Optional[int] = None


# ── fakes: the completion shapes the three client paths produce ───────────────

def _completion(text: str, *, finish_reason: str = "stop", usage=None):
    """An OpenAI-compatible completion carrying ``text`` as message content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None),
                                 finish_reason=finish_reason)],
        usage=usage)


def _tool_completion(arguments: str, *, finish_reason: str = "stop"):
    """TOOLS mode — the payload is a tool call's arguments, not message content.
    This is the shape the Gemini and reasoning-model bindings actually use."""
    call = SimpleNamespace(function=SimpleNamespace(arguments=arguments))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]),
                                 finish_reason=finish_reason)],
        usage=None)


def _anthropic_completion(text: str, *, stop_reason: str = "end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(text=text, input=None)],
                           stop_reason=stop_reason, usage=None)


def _retry_exc(completion, message: str = "1 validation error for Verdict"):
    """The real instructor exception, built the way instructor builds it — so the
    extraction under test is the one that runs in production, not a stand-in."""
    from instructor.core import InstructorRetryException

    return InstructorRetryException(message, last_completion=completion,
                                    n_attempts=1, total_usage=0)


# ── the normalizer: what it repairs ───────────────────────────────────────────

GOOD = '{"verdict": "high", "note": "ok"}'


@pytest.mark.parametrize("label,text", [
    ("clean",           GOOD),
    ("fence",           f"```json\n{GOOD}\n```"),
    ("bare_fence",      f"```\n{GOOD}\n```"),
    ("unterminated",    f"```json\n{GOOD}"),          # what a near-ceiling response looks like
    ("prose_around",    f"Here is the analysis: {GOOD} Let me know if you need more!"),
    ("trailing_comma",  '{"verdict": "high", "note": "ok",}'),
    ("python_literals", '{"verdict": "high", "note": "ok", "flag": True}'),
    ("smart_quotes",    '{“verdict”: “high”, “note”: “ok”}'),
    ("python_repr",     "{'verdict': 'high', 'note': 'ok'}"),
    ("enum_case",       '{"verdict": "HIGH", "note": "ok"}'),
    ("enum_separators", '{"verdict": " High ", "note": "ok"}'),
])
def test_the_normalizer_recovers_structurally_broken_output(label, text):
    payload, repairs = R.parse_payload(text)
    assert payload is not None, f"{label}: nothing parsed"
    payload, coercions = R.coerce_payload(payload, Verdict)
    value = Verdict.model_validate(payload)
    assert value.verdict == "high" and value.note == "ok"
    if label != "clean":
        assert repairs or coercions, f"{label}: repaired but reported no repair"
    else:
        assert not repairs and not coercions, "clean JSON must report no repairs"


def test_prose_with_braces_after_the_json_does_not_break_extraction():
    """A naive first-brace/last-brace slice breaks the moment the trailing prose has a
    brace of its own — and chatty free-tier models produce exactly that."""
    payload, _ = R.parse_payload(f"Analysis: {GOOD} — see the {{docs}} for detail.")
    assert Verdict.model_validate(payload).verdict == "high"


def test_python_literals_inside_strings_are_left_alone():
    """`True` is a real word in our prompts' own example outputs. A word-boundary
    rewrite would corrupt the note text while 'repairing' the response."""
    payload, _ = R.parse_payload('{"verdict": "high", "note": "returns True when set",}')
    assert Verdict.model_validate(payload).note == "returns True when set"


def test_extra_keys_are_dropped_only_when_the_model_forbids_them():
    class Strict(BaseModel):
        model_config = {"extra": "forbid"}
        verdict: str

    payload, repairs = R.coerce_payload({"verdict": "high", "chatter": "hi"}, Strict)
    assert repairs == ["extra_keys"] and Strict.model_validate(payload).verdict == "high"
    # Verdict permits extras, so dropping them would be a no-op that lies in the list.
    _, none = R.coerce_payload({"verdict": "high", "note": "ok", "chatter": "hi"}, Verdict)
    assert none == []


# ── the normalizer: what it must REFUSE to repair ─────────────────────────────

def test_a_misspelled_enum_still_fails():
    """The one place the normalizer could 'helpfully' guess. Case and separators are the
    same token written differently; a typo is a different token. Closing this last gap
    would turn a loud failure into a wrong answer no downstream guard can see."""
    payload, _ = R.parse_payload('{"verdict": "hgih", "note": "ok"}')
    payload, coercions = R.coerce_payload(payload, Verdict)
    assert coercions == []
    with pytest.raises(Exception):
        Verdict.model_validate(payload)


def test_prose_with_no_json_is_unparseable():
    payload, _ = R.parse_payload("I think the answer is probably high, honestly.")
    assert payload is None


def test_a_missing_required_field_is_not_invented():
    payload, _ = R.parse_payload('{"verdict": "high"}')
    payload, _ = R.coerce_payload(payload, Verdict)
    with pytest.raises(Exception):
        Verdict.model_validate(payload)


def test_an_absurdly_large_blob_is_refused_rather_than_chewed_on():
    payload, repairs = R.parse_payload("x" * (R._MAX_SALVAGE_CHARS + 1))
    assert payload is None and repairs == []


# ── raw-text extraction across client shapes ──────────────────────────────────

def test_response_text_reads_every_client_shape():
    assert R.response_text(_completion(GOOD)) == GOOD
    assert R.response_text(_tool_completion(GOOD)) == GOOD      # TOOLS mode
    assert R.response_text(_anthropic_completion(GOOD)) == GOOD
    assert R.response_text(None) == ""


def test_a_tools_mode_response_is_salvaged_too():
    """The reasoning-model bindings all run in TOOLS mode. Reading only message.content
    would return "" for exactly the bindings that fail most often."""
    result = R.salvage(_retry_exc(_tool_completion(f"```json\n{GOOD}\n```")), Verdict)
    assert result.ok and result.value.verdict == "high"


# ── the taxonomy ──────────────────────────────────────────────────────────────

def test_truncation_is_classified_from_the_providers_own_stop_reason():
    d = R.classify(_retry_exc(_completion('{"verdict": "hi', finish_reason="length")))
    assert d.failure == R.TRUNCATED and not d.repairable


def test_truncation_is_detected_without_a_stop_reason():
    """Shims that report no finish_reason still truncate. An opened-but-never-closed
    object is the signature of a stream that stopped mid-write."""
    d = R.classify(_retry_exc(_completion('{"verdict": "high", "note": "ok')))
    assert d.failure == R.TRUNCATED


def test_malformed_but_complete_json_is_not_called_a_truncation():
    """Balanced braces + a real stop reason ⇒ the model finished and got it wrong,
    which is the repairable case. Conflating the two would refuse a repair that works."""
    d = R.classify(_retry_exc(_completion('{"verdict": "hgih", "note": "ok"}')))
    assert d.failure == R.SCHEMA_MISMATCH and d.repairable


def test_anthropic_max_tokens_is_a_truncation():
    d = R.classify(_retry_exc(_anthropic_completion('{"verdict":', stop_reason="max_tokens")))
    assert d.failure == R.TRUNCATED


def test_empty_and_refusal_are_their_own_classes():
    assert R.classify(_retry_exc(_completion(""))).failure == R.EMPTY
    refusal = R.classify(_retry_exc(_completion("I'm sorry, but I can't assist with that.")))
    assert refusal.failure == R.REFUSAL and not refusal.repairable


def test_a_narrator_sentence_about_inability_is_not_a_refusal():
    """'I cannot compute a margin without cost data' is a legitimate grounded answer —
    the exact sentence intake.loss_signals exists to produce. Matching it as a refusal
    would suppress honest output."""
    text = ('{"verdict": "low", "note": "I cannot compute a margin without cost data"}')
    assert R.classify(_retry_exc(_completion(text))).failure != R.REFUSAL


def test_unparseable_prose_is_repairable_but_truncation_is_not():
    assert R.classify(_retry_exc(_completion("no json here at all"))).repairable
    assert not R.classify(_retry_exc(_completion("", finish_reason="length"))).repairable


def test_only_truncation_blocks_the_failover():
    """Narrow on purpose. A refusal or an empty body is a property of THAT model on that
    prompt — a different one may well answer, and refusing to try would trade one cheap
    request for a dead investigation. A truncation hits OUR max_tokens on every link."""
    assert not R.should_failover(R.Diagnosis(R.TRUNCATED))
    for failure in (R.EMPTY, R.UNPARSEABLE, R.SCHEMA_MISMATCH, R.REFUSAL, R.UNKNOWN):
        assert R.should_failover(R.Diagnosis(failure)), failure


# ── salvage as a whole ────────────────────────────────────────────────────────

def test_salvage_returns_a_valid_object_and_names_its_repairs():
    result = R.salvage(_retry_exc(_completion(f"```json\n{GOOD}\n```")), Verdict)
    assert result.ok and result.value.verdict == "high" and "fence" in result.repairs


def test_salvage_declines_a_truncation_without_touching_the_normalizer():
    result = R.salvage(_retry_exc(_completion('{"verdict":', finish_reason="length")), Verdict)
    assert not result.ok and result.diagnosis.failure == R.TRUNCATED


def test_the_repair_prompt_carries_the_specific_error_and_forbids_invention():
    d = R.Diagnosis(R.SCHEMA_MISMATCH, "verdict: unexpected value 'hgih'", '{"verdict": "hgih"}')
    system, user = R.repair_prompt(d, Verdict)
    assert "never" in system.lower() and "invent" in system.lower()
    assert "verdict: unexpected value 'hgih'" in user      # the field, not just "invalid"
    assert '{"verdict": "hgih"}' in user


def test_the_gate_counts_both_sides():
    from aughor.stats import stats

    before = stats.snapshot()["counters"]
    assert R.gate("t.optional", True) is True
    assert R.gate("t.optional", False) is False
    after = stats.snapshot()["counters"]
    assert after.get("llm.gate.allowed.t.optional", 0) == before.get("llm.gate.allowed.t.optional", 0) + 1
    assert after.get("llm.gate.skipped.t.optional", 0) == before.get("llm.gate.skipped.t.optional", 0) + 1


# ── the provider wiring: does it actually save the request? ───────────────────

class _FakeEndpoint:
    """Records every request. `results` is consumed one per call; an Exception in the
    list is raised rather than returned."""

    def __init__(self, *results):
        self.calls: list[dict] = []
        self._results = list(results)

    def create_with_completion(self, **kw):
        self.calls.append(kw)
        nxt = self._results.pop(0) if self._results else RuntimeError("no result queued")
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _client(endpoint):
    return SimpleNamespace(chat=SimpleNamespace(completions=endpoint))


def _run(endpoint, backend="openrouter"):
    return LLMProvider._complete_on(_client(endpoint), backend, "m", "sys", "usr",
                                    Verdict, 0.1, base_url="http://x", role="coder")


def test_a_fenced_response_costs_zero_extra_requests():
    """The headline. Today this exception walks the fallback chain and spends a whole
    request against a second provider to re-answer a prompt whose first answer was
    already correct — because of three backticks."""
    ep = _FakeEndpoint(_retry_exc(_completion(f"```json\n{GOOD}\n```")))
    out = _run(ep)
    assert out.verdict == "high"
    assert len(ep.calls) == 1, "salvage must not issue a request"


def test_with_salvage_off_the_failure_still_surfaces(monkeypatch):
    monkeypatch.setenv("AUGHOR_LLM_STRUCTURED_SALVAGE", "0")
    ep = _FakeEndpoint(_retry_exc(_completion(f"```json\n{GOOD}\n```")))
    with pytest.raises(Exception):
        _run(ep)
    assert len(ep.calls) == 1


def test_turning_the_repair_off_gives_a_hard_ceiling_of_one_request(monkeypatch):
    """The operator's escape hatch: `llm.bounded_repair=0` means a structured call can
    never cost more than the one request it was asked to make."""
    monkeypatch.setenv("AUGHOR_LLM_BOUNDED_REPAIR", "0")
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hgih", "note": "ok"}')))
    with pytest.raises(R.StructuredOutputError):
        _run(ep)
    assert len(ep.calls) == 1


def test_instructor_gets_one_attempt_not_its_default_three(monkeypatch):
    """The leak this wave found. Instructor defaults to THREE attempts and we had never
    overridden it, so a malformed response re-sent the entire prompt — evidence block
    and all — three times before our code saw the error. Measured on the real transport
    stack: 3 requests for a trailing comma."""
    ep = _FakeEndpoint((Verdict(verdict="high", note="ok"), _completion(GOOD)))
    _run(ep)
    assert ep.calls[0]["max_retries"] == 1

    monkeypatch.setenv("AUGHOR_LLM_STRUCTURED_ATTEMPTS", "3")   # the escape hatch
    ep2 = _FakeEndpoint((Verdict(verdict="high", note="ok"), _completion(GOOD)))
    _run(ep2)
    assert ep2.calls[0]["max_retries"] == 3


def test_the_repair_does_not_inherit_a_retry_ladder(monkeypatch):
    """One repair means one request. A ladder on the repair would quietly restore the
    multiplier this wave just removed."""
    monkeypatch.setenv("AUGHOR_LLM_BOUNDED_REPAIR", "1")
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hgih", "note": "ok"}')),
                       (Verdict(verdict="high", note="ok"), _completion(GOOD)))
    _run(ep)
    assert ep.calls[1]["max_retries"] == 1


def test_the_bounded_repair_is_exactly_one_request(monkeypatch):
    monkeypatch.setenv("AUGHOR_LLM_BOUNDED_REPAIR", "1")
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hgih", "note": "ok"}')),
                       (Verdict(verdict="high", note="ok"), _completion(GOOD)))
    out = _run(ep)
    assert out.verdict == "high"
    assert len(ep.calls) == 2, "one original + one repair, never more"
    repair = ep.calls[1]
    assert repair["temperature"] == 0.0
    assert repair["max_tokens"] > 0                        # still capped
    assert "hgih" in repair["messages"][-1]["content"]     # carries the broken output


def test_a_failed_repair_surfaces_the_original_failure(monkeypatch):
    monkeypatch.setenv("AUGHOR_LLM_BOUNDED_REPAIR", "1")
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hgih", "note": "ok"}')),
                       RuntimeError("repair also failed"))
    with pytest.raises(R.StructuredOutputError) as caught:
        _run(ep)
    assert caught.value.diagnosis.failure == R.SCHEMA_MISMATCH
    assert len(ep.calls) == 2                              # and it stops there


def test_a_truncation_never_buys_a_repair(monkeypatch):
    """Classify BEFORE retry. The ceiling that cut the response off is ours and is sent
    on every request, so a repair regenerates into the same wall."""
    monkeypatch.setenv("AUGHOR_LLM_BOUNDED_REPAIR", "1")
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hi', finish_reason="length")))
    with pytest.raises(R.StructuredOutputError) as caught:
        _run(ep)
    assert caught.value.diagnosis.failure == R.TRUNCATED
    assert len(ep.calls) == 1


def test_a_truncation_does_not_walk_the_fallback_chain(monkeypatch):
    """The failover for a truncation is one request per backend to hit the same
    ceiling each time — the most expensive way there is to learn nothing."""
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hi', finish_reason="length")))
    provider = LLMProvider.__new__(LLMProvider)
    provider.backend, provider.role = "openrouter", "coder"
    provider._model, provider._base_url = "m", "http://x"
    provider._client = _client(ep)
    monkeypatch.setattr(LLMProvider, "_fallback_candidates", lambda self: ["anthropic"])
    monkeypatch.setattr(LLMProvider, "_fallback_provider",
                        lambda self, b: pytest.fail("fallback must not be attempted"))
    monkeypatch.setattr(LLMProvider, "_warn_if_over_window", lambda self, s, u: None)
    with pytest.raises(R.StructuredOutputError):
        provider.complete("sys", "usr", Verdict)


def test_a_schema_mismatch_still_walks_the_fallback_chain(monkeypatch):
    """The complement, and why the no-failover rule stays narrow: a stronger model
    genuinely may get the shape right."""
    ep = _FakeEndpoint(_retry_exc(_completion('{"verdict": "hgih", "note": "ok"}')))
    provider = LLMProvider.__new__(LLMProvider)
    provider.backend, provider.role = "openrouter", "coder"
    provider._model, provider._base_url = "m", "http://x"
    provider._client = _client(ep)
    tried: list[str] = []
    monkeypatch.setattr(LLMProvider, "_fallback_candidates", lambda self: ["anthropic"])
    monkeypatch.setattr(LLMProvider, "_fallback_provider",
                        lambda self, b: (tried.append(b), None)[1])
    monkeypatch.setattr(LLMProvider, "_warn_if_over_window", lambda self, s, u: None)
    with pytest.raises(Exception):
        provider.complete("sys", "usr", Verdict)
    assert tried == ["anthropic"]


# ── the boundary that must not move: transport stays transport ────────────────

def test_a_rate_limit_is_never_reclassified_as_a_formatting_problem():
    """Instructor wraps whatever ended the attempt, so a 429 can arrive as an
    InstructorRetryException. Reading that as bad formatting would strip the markers
    the quota cooldown matches on — turning a day-long block back into a per-call
    probe, which is the regression #197 was landed to prevent."""
    from aughor.llm import provider as P

    exc = _retry_exc(_completion(""), message="429 Too Many Requests: rate limit exceeded")
    assert not P._is_structured_failure(exc)
    assert P._typed_structured_error(exc, Verdict) is exc
    assert P._should_failover(exc)


def test_a_daily_quota_error_still_reaches_the_cooldown():
    from aughor.llm import provider as P

    exc = _retry_exc(_completion(""), message="RESOURCE_EXHAUSTED: GenerateRequestsPerDay")
    assert not P._is_structured_failure(exc)
    assert P._is_quota_exhausted(P._typed_structured_error(exc, Verdict))


def test_an_ordinary_transport_error_is_untouched():
    from aughor.llm import provider as P

    exc = RuntimeError("connection reset by peer")
    assert not P._is_structured_failure(exc)
    assert P._typed_structured_error(exc, Verdict) is exc


# ── the pre-existing leak this wave found ─────────────────────────────────────

def test_a_validation_failure_does_not_buy_a_reasoning_extras_retry(monkeypatch):
    """The extras-degrade is for a shim that rejects `reasoning` with a 4xx. Its guard
    admitted anything neither transient nor quota-blocked — and a validation error is
    neither, so on OpenRouter (the only backend that sends extra_body, and the primary)
    EVERY structured-output failure re-sent the whole prompt to test a hypothesis that
    was already false. Measured before the fix: 2 requests per validation failure."""
    monkeypatch.setenv("AUGHOR_LLM_STRUCTURED_SALVAGE", "0")   # isolate the degrade path
    ep = _FakeEndpoint(_retry_exc(_completion("not json")))
    with pytest.raises(Exception):
        _run(ep, backend="openrouter")
    assert len(ep.calls) == 1, "a validation error must not re-send the prompt"
    assert "extra_body" in ep.calls[0]                          # extras were never the problem


def test_a_shim_that_really_rejects_the_extras_still_degrades():
    """The complement — the behaviour the guard exists for must survive the fix."""
    ep = _FakeEndpoint(ValueError("400: unrecognized field 'reasoning'"),
                       (Verdict(verdict="high", note="ok"), _completion(GOOD)))
    assert _run(ep, backend="openrouter").verdict == "high"
    assert len(ep.calls) == 2
    assert "extra_body" in ep.calls[0] and "extra_body" not in ep.calls[1]
