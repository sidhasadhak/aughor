"""The faux LLM backend's contract (unified plan Layer 0.1).

Every test here drives the REAL provider stack — ``get_provider`` → ``complete()``
→ ``_complete_on`` → salvage/repair/failover decisions — with the network replaced
by the scripted queue in ``aughor/llm/faux.py``. What is being pinned:

* scripted responses serve in order, and the factory form hands the test the exact
  prompt the code built;
* an unscripted call is LOUD (``FauxResponsesExhausted``) and can never be answered
  by the fallback chain (``never_failover``) — the silent fall-through that made two
  explorer tests race network latency (see tests/conftest.py's history note) is
  structurally impossible on this backend;
* the reliability taxonomy is exercisable offline: fenced JSON salvages at zero
  extra requests, a truncation refuses failover, a schema mismatch spends exactly
  one bounded repair, a rate limit walks the retry ladder;
* the faux model ids resolve capability tiers deterministically.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from aughor.llm import faux
from aughor.llm import provider as P
from aughor.llm.faux import (
    CAPABLE_MODEL,
    FauxQuotaExhausted,
    FauxRateLimit,
    FauxResponsesExhausted,
    FauxTruncation,
)
from aughor.llm.profile import tier_for
from aughor.llm.provider import get_provider
from aughor.llm.reliability import (
    SCHEMA_MISMATCH,
    TRUNCATED,
    UNPARSEABLE,
    StructuredOutputError,
)


class Verdict(BaseModel):
    answer: str
    confidence: float = 0.5


# ── Scripted success shapes ───────────────────────────────────────────────────

def test_scripted_json_string_round_trips(faux_llm):
    faux_llm.set_responses(['{"answer": "42", "confidence": 0.9}'])
    out = get_provider("coder").complete("sys prompt", "user prompt", Verdict)
    assert out == Verdict(answer="42", confidence=0.9)
    assert faux_llm.pending() == 0


def test_scripted_dict_and_model_instance(faux_llm):
    faux_llm.set_responses([{"answer": "from-dict"}, Verdict(answer="as-is")])
    prov = get_provider("narrator")
    assert prov.complete("s", "u", Verdict).answer == "from-dict"
    assert prov.complete("s", "u", Verdict).answer == "as-is"


def test_factory_sees_the_exact_prompt_and_binding(faux_llm):
    seen = {}

    def factory(system, user, role, model, call_index):
        seen.update(system=system, user=user, role=role, model=model, index=call_index)
        return Verdict(answer=f"call-{call_index}")

    faux_llm.set_responses([factory])
    out = get_provider("coder").complete("SYSTEM TEXT", "USER TEXT", Verdict)
    assert out.answer == "call-0"
    assert seen == {"system": "SYSTEM TEXT", "user": "USER TEXT",
                    "role": "coder", "model": "faux-coder", "index": 0}


def test_calls_log_records_what_the_code_asked(faux_llm):
    faux_llm.set_responses(['{"answer": "a"}'])
    get_provider("fast").complete("the system", "the user", Verdict)
    (call,) = faux_llm.calls()
    assert (call.role, call.model) == ("fast", "faux-fast")
    assert call.system == "the system" and call.user == "the user"
    assert call.response_model is Verdict


# ── The loud-exhaustion contract ──────────────────────────────────────────────

def test_unscripted_call_raises_loudly(faux_llm):
    with pytest.raises(FauxResponsesExhausted) as exc_info:
        get_provider("coder").complete("s", "u", Verdict)
    # The message names the unmodelled call so the fix is obvious from the traceback.
    assert "Verdict" in str(exc_info.value)
    assert "coder" in str(exc_info.value)


def test_exhaustion_never_reaches_the_fallback_chain(faux_llm, monkeypatch):
    """Even with a fully configured chain, an unscripted faux call must surface as
    itself — the chain answering in its place is the exact silent fall-through this
    backend exists to kill."""
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "anthropic,gemini")
    monkeypatch.setattr(P, "_active_key", lambda backend: "not-a-real-key")
    assert P._should_failover(FauxResponsesExhausted("boom")) is False
    with pytest.raises(FauxResponsesExhausted):
        get_provider("coder").complete("s", "u", Verdict)


def test_scripted_exception_instances_surface_as_themselves(faux_llm):
    marker = ValueError("scripted transport failure")
    faux_llm.set_responses([marker])
    with pytest.raises(ValueError) as exc_info:
        get_provider("coder").complete("s", "u", Verdict)
    assert exc_info.value is marker


# ── The reliability taxonomy, offline ─────────────────────────────────────────

def test_fenced_json_salvages_with_zero_extra_requests(faux_llm):
    faux_llm.set_responses(['```json\n{"answer": "fenced"}\n```'])
    out = get_provider("coder").complete("s", "u", Verdict)
    assert out.answer == "fenced"
    # Salvage is deterministic: exactly ONE completion was served, no repair spent.
    assert len(faux_llm.calls()) == 1


def test_truncation_classifies_and_refuses_failover(faux_llm):
    faux_llm.set_responses([FauxTruncation()])
    with pytest.raises(StructuredOutputError) as exc_info:
        get_provider("coder").complete("s", "u", Verdict)
    assert exc_info.value.diagnosis.failure == TRUNCATED
    # One call served; the chain was never walked and no repair was attempted.
    assert len(faux_llm.calls()) == 1


def test_unparseable_garbage_classifies(faux_llm):
    faux_llm.set_responses(["this is not JSON at all, sorry"])
    with pytest.raises(StructuredOutputError) as exc_info:
        get_provider("coder").complete("s", "u", Verdict)
    assert exc_info.value.diagnosis.failure == UNPARSEABLE


def test_schema_mismatch_spends_one_bounded_repair_which_can_succeed(faux_llm):
    """Valid JSON of the wrong shape is the repairable class: the provider sends ONE
    repair request carrying its own broken output. Scripting the corrected reply
    behind it exercises the whole repair loop offline."""
    faux_llm.set_responses([
        '{"wrong_field": "oops"}',
        '{"answer": "repaired"}',
    ])
    out = get_provider("coder").complete("s", "u", Verdict)
    assert out.answer == "repaired"
    calls = faux_llm.calls()
    assert len(calls) == 2
    # The repair prompt carries the broken output, not the original task.
    assert "wrong_field" in calls[1].user
    assert "s" != calls[1].system  # repair uses its own fix-the-output system prompt


def test_schema_mismatch_with_failed_repair_surfaces_typed(faux_llm):
    faux_llm.set_responses(['{"wrong_field": "oops"}'])  # nothing behind it: repair fails
    with pytest.raises(StructuredOutputError) as exc_info:
        get_provider("coder").complete("s", "u", Verdict)
    assert exc_info.value.diagnosis.failure == SCHEMA_MISMATCH


def test_rate_limit_walks_the_retry_ladder_then_succeeds(faux_llm, monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda s: None)  # the ladder's backoff, skipped
    faux_llm.set_responses([FauxRateLimit(), '{"answer": "after-retry"}'])
    out = get_provider("coder").complete("s", "u", Verdict)
    assert out.answer == "after-retry"
    assert len(faux_llm.calls()) == 2


def test_quota_exhaustion_marks_the_cooldown_and_raises(faux_llm):
    from aughor.llm.coordination import default as coordinator

    faux_llm.set_responses([FauxQuotaExhausted()])
    with pytest.raises(Exception) as exc_info:
        get_provider("coder").complete("s", "u", Verdict)
    assert P._is_quota_exhausted(exc_info.value)
    assert coordinator().in_cooldown(P.FAUX_BACKEND)


# ── Deterministic tier resolution ─────────────────────────────────────────────

def test_default_faux_models_resolve_the_baseline_floor(faux_llm):
    for model in P.DEFAULT_FAUX_MODELS.values():
        assert tier_for(model)["max_output_tokens"] == 4096
        assert tier_for(model)["reasoning_effort"] == "low"


def test_capable_faux_model_resolves_the_declared_tier():
    tier = tier_for(CAPABLE_MODEL)
    assert tier["max_output_tokens"] == 8192
    assert tier["reasoning_effort"] == "medium"


def test_faux_backend_is_not_operator_selectable():
    """The registry decision, pinned: faux builds like any backend but must never
    appear in the operator-facing surfaces (Settings dropdown / CLI mirror /
    fallback eligibility all derive from BACKENDS)."""
    assert P.FAUX_BACKEND not in P.BACKENDS
    assert P.FAUX_BACKEND in P._FAUX_MODELS
    prov = P.LLMProvider(P.FAUX_BACKEND, "coder")
    assert isinstance(prov._client, faux.FauxClient)


def test_a_stray_unscripted_call_cannot_pollute_calls(faux_llm):
    """The suite-wide flake this guards: a background thread left over from an earlier
    test (a scheduler heartbeat, a kernel task) fires an unscripted completion
    mid-test. It is refused loudly to its own caller — correct — but it was also
    RECORDED, so an unrelated test's ``(call,) = faux_llm.calls()`` unpacked two
    calls and failed on timing luck. A stray is by definition unscripted, so
    ``calls()`` must show served requests only; the refusal stays visible via
    ``refusals()``."""
    import threading

    stray_outcome: list[BaseException] = []

    def stray():
        try:
            get_provider("coder").complete("stray-system", "stray-user", Verdict)
        except FauxResponsesExhausted as e:
            stray_outcome.append(e)

    t = threading.Thread(target=stray)
    t.start()
    t.join()
    assert stray_outcome, "the stray call must still be refused loudly to its caller"

    faux_llm.set_responses(['{"answer": "ok"}'])
    get_provider("narrator").complete("s", "u", Verdict)

    (call,) = faux_llm.calls()          # exactly the flaky assertion, now safe
    assert call.role == "narrator" and call.served

    (refused,) = faux_llm.refusals()    # the stray is not lost, just not in calls()
    assert refused.role == "coder" and not refused.served
