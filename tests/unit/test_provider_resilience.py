"""Tests for the LLM provider resilience layer (aughor/llm/provider.py):
per-endpoint concurrency semaphore + transient-error retry/backoff/deadline.

This is platform robustness — every Aughor LLM call goes through _run_resilient — so the contract
matters: retry throttle/transient, surface real failures immediately, never hold a slot while sleeping.
"""
from __future__ import annotations

import pytest

from aughor.llm import provider as P


class _Transient(Exception):
    status_code = 429


class _Fatal(Exception):
    pass


@pytest.fixture(autouse=True)
def _clear_quota_cooldown():
    """The cooldown is process-global by design (it must outlive any one provider), so a
    test that trips it would otherwise leak a skipped backend into every later test."""
    P._quota_cooldown.clear()
    yield
    P._quota_cooldown.clear()


def test_is_transient_classification():
    assert P._is_transient(_Transient())                       # 429 status
    assert P._is_transient(Exception("Read timed out"))
    assert P._is_transient(Exception("429 Too Many Requests"))
    assert P._is_transient(Exception("upstream overloaded"))
    # real failures must NOT be retried
    assert not P._is_transient(_Fatal("validation error: missing field"))
    assert not P._is_transient(Exception("no such column: foo"))
    bad = Exception("bad request"); bad.status_code = 400
    assert not P._is_transient(bad)


def test_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)      # no real backoff in tests
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "3")
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Transient()
        return "ok"
    assert P._run_resilient(do, "u1") == "ok"
    assert calls["n"] == 3                                     # initial + 2 retries


def test_non_transient_raises_immediately(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        raise _Fatal("bad sql")
    with pytest.raises(_Fatal):
        P._run_resilient(do, "u2")
    assert calls["n"] == 1                                     # no retry on real failure


def test_retries_bounded_by_max(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "2")
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        raise _Transient()
    with pytest.raises(_Transient):
        P._run_resilient(do, "u3")
    assert calls["n"] == 3                                     # initial + exactly 2 retries


def test_semaphore_shared_per_base_url():
    a = P._semaphore_for("http://x")
    b = P._semaphore_for("http://x")
    c = P._semaphore_for("http://y")
    assert a is b and a is not c                               # one gate per endpoint


def test_success_path_calls_once(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda *_: None)
    calls = {"n": 0}
    def do():
        calls["n"] += 1
        return 42
    assert P._run_resilient(do, "u4") == 42 and calls["n"] == 1   # happy path unchanged


# ── Quota exhaustion vs. throttle ────────────────────────────────────────────
# A free-tier daily quota arrives as a RateLimitError with status 429 and "rate limit"
# in the message, so it matched every transient test and was retried three times before
# raising. That burned ~15s per call AND delayed the fallback that would have answered —
# a full briefing (digest fan-out + narrator) took 80s to fail with an opaque 500.

def test_daily_quota_is_not_retried_even_though_it_is_a_429():
    quota = Exception(
        "Error code: 429 - Rate limit exceeded: free-models-per-day. "
        "Add 10 credits to unlock 1000 free model requests per day")
    quota.status_code = 429
    assert P._is_quota_exhausted(quota)
    assert not P._is_transient(quota)          # fail over now, don't wait on tomorrow


def test_spent_balance_is_not_retried():
    for msg in ("Credit limit exceeded, please add credits",
                "402 Payment Required"):
        assert P._is_quota_exhausted(Exception(msg)), msg
        assert not P._is_transient(Exception(msg)), msg


def test_ordinary_throttle_stays_retryable():
    """The narrow read matters: a per-minute throttle DOES clear on the retry
    timescale, so it must keep its backoff ladder."""
    for msg in ("429 Too Many Requests", "rate limit reached, retry in 2s",
                "upstream overloaded"):
        assert not P._is_quota_exhausted(Exception(msg)), msg
        assert P._is_transient(Exception(msg)), msg


def test_gemini_per_minute_limit_is_a_throttle_not_an_exhausted_allowance():
    """Verbatim from a live Gemini 429. It says "quota" and "billing" but the limit is
    per MINUTE — classifying it as day-scale parked the backend in a 15-minute cooldown
    over a 60-second throttle, which a live run caught. Retry it; do not cool it down."""
    msg = ("Error code: 429 - You exceeded your current quota, please check your plan and "
           "billing details. Quota exceeded for metric: "
           "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
           "limit: 5, model: gemini-3.6-flash")
    assert not P._is_quota_exhausted(Exception(msg))
    assert P._is_transient(Exception(msg))


def test_openrouter_daily_cap_is_an_exhausted_allowance():
    """Verbatim from a live OpenRouter 429 — the contrasting case: names a DAY, so it
    cannot clear on the retry ladder and must fail over immediately."""
    msg = ("Error code: 429 - Rate limit exceeded: free-models-per-day. Add 10 credits "
           "to unlock 1000 free model requests per day")
    assert P._is_quota_exhausted(Exception(msg))
    assert not P._is_transient(Exception(msg))


# ── Fallback chain ───────────────────────────────────────────────────────────

def test_fallback_chain_skips_primary_and_unkeyed_backends(monkeypatch):
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.delenv("AUGHOR_FALLBACK_BACKENDS", raising=False)
    monkeypatch.setattr(P, "_active_key", lambda b: "k" if b in ("gemini", "openrouter") else "")
    prov = P.LLMProvider.__new__(P.LLMProvider)   # no network in a unit test
    prov.backend, prov.role = "openrouter", "narrator"
    # openrouter is the primary (excluded); anthropic/groq/together hold no key
    assert prov._fallback_candidates() == ["gemini"]


def test_fallback_chain_is_empty_when_disabled(monkeypatch):
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    monkeypatch.setattr(P, "_active_key", lambda b: "k")
    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    assert prov._fallback_candidates() == []


def test_fallback_order_is_overridable_and_drops_typos(monkeypatch):
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "gemini, nosuchbackend ,groq")
    monkeypatch.setattr(P, "_active_key", lambda b: "k")
    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    assert prov._fallback_candidates() == ["gemini", "groq"]   # order honoured, typo dropped


def test_anthropic_keeps_its_pinned_model_others_use_their_role_default(monkeypatch):
    """The pre-existing AUGHOR_FALLBACK_MODEL contract is Anthropic's alone — a narrator
    falling back to Gemini must not inherit a model id from another vendor."""
    monkeypatch.setenv("AUGHOR_FALLBACK_MODEL", "claude-opus-4-8")
    assert P._fallback_model_for("anthropic", "narrator") == "claude-opus-4-8"
    assert P._fallback_model_for("gemini", "narrator") == \
        P._DEFAULT_MODELS["gemini"]["narrator"]
    assert P._fallback_model_for("openrouter", "fast") == \
        P._DEFAULT_MODELS["openrouter"]["fast"]


def test_quota_exhausted_primary_fails_over_to_the_next_backend(monkeypatch):
    """The end-to-end contract this whole change exists for: an exhausted primary
    hands the SAME call to the next configured backend and the caller never sees
    the failure. Previously the fallback was Anthropic-or-nothing, so an install
    without an Anthropic key raised straight through as a 500."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        text: str = "ok"

    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "gemini")
    monkeypatch.setattr(P, "_active_key", lambda b: "k")

    seen: list[str] = []

    def fake_complete_on(client, backend, model, system, user, response_model,
                         temperature, **kw):
        seen.append(backend)
        if backend == "openrouter":
            raise Exception("Error code: 429 - Rate limit exceeded: free-models-per-day")
        return _Out(text=f"from {backend}")

    monkeypatch.setattr(P.LLMProvider, "_complete_on", staticmethod(fake_complete_on))

    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    prov._model, prov._client, prov._base_url = "m:free", object(), "u"
    monkeypatch.setattr(prov, "_warn_if_over_window", lambda *a, **k: None)
    # the fallback provider is built lazily; hand back a stub instead of touching the network
    stub = P.LLMProvider.__new__(P.LLMProvider)
    stub.backend, stub.role = "gemini", "narrator"
    stub._model, stub._client, stub._base_url = "gemini-flash-latest", object(), "g"
    monkeypatch.setattr(prov, "_fallback_provider", lambda b: stub)

    out = prov.complete("s", "u", _Out, 0.3)
    assert out.text == "from gemini"
    assert seen == ["openrouter", "gemini"]          # tried primary once, then failed over


def test_original_cause_is_raised_when_every_link_fails(monkeypatch):
    """Diagnosis depends on this: the LAST backend's error explains nothing about
    why the primary went down, so the chain must surface the ORIGINAL cause."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        text: str = "ok"

    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "gemini")
    monkeypatch.setattr(P, "_active_key", lambda b: "k")

    def fake_complete_on(client, backend, model, system, user, response_model,
                         temperature, **kw):
        raise Exception("primary is out of quota" if backend == "openrouter"
                        else "gemini key rejected")

    monkeypatch.setattr(P.LLMProvider, "_complete_on", staticmethod(fake_complete_on))

    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    prov._model, prov._client, prov._base_url = "m:free", object(), "u"
    monkeypatch.setattr(prov, "_warn_if_over_window", lambda *a, **k: None)
    stub = P.LLMProvider.__new__(P.LLMProvider)
    stub.backend, stub.role = "gemini", "narrator"
    stub._model, stub._client, stub._base_url = "gemini-flash-latest", object(), "g"
    monkeypatch.setattr(prov, "_fallback_provider", lambda b: stub)

    with pytest.raises(Exception, match="primary is out of quota"):
        prov.complete("s", "u", _Out, 0.3)


# ── Quota cooldown ───────────────────────────────────────────────────────────
# Without this, a briefing's dozens of LLM calls each paid one guaranteed-failed
# round trip to the exhausted primary: a 9s brief measured 76s.

def test_exhausted_backend_is_skipped_on_the_next_call(monkeypatch):
    from pydantic import BaseModel

    class _Out(BaseModel):
        text: str = "ok"

    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "gemini")
    monkeypatch.setattr(P, "_active_key", lambda b: "k")

    seen: list[str] = []

    def fake_complete_on(client, backend, model, system, user, response_model,
                         temperature, **kw):
        seen.append(backend)
        if backend == "openrouter":
            raise Exception("Error code: 429 - Rate limit exceeded: free-models-per-day")
        return _Out(text=f"from {backend}")

    monkeypatch.setattr(P.LLMProvider, "_complete_on", staticmethod(fake_complete_on))

    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    prov._model, prov._client, prov._base_url = "m:free", object(), "u"
    monkeypatch.setattr(prov, "_warn_if_over_window", lambda *a, **k: None)
    stub = P.LLMProvider.__new__(P.LLMProvider)
    stub.backend, stub.role = "gemini", "narrator"
    stub._model, stub._client, stub._base_url = "gemini-flash-latest", object(), "g"
    monkeypatch.setattr(prov, "_fallback_provider", lambda b: stub)

    assert prov.complete("s", "u", _Out, 0.3).text == "from gemini"
    assert seen == ["openrouter", "gemini"]      # first call learns the hard way
    seen.clear()
    assert prov.complete("s", "u", _Out, 0.3).text == "from gemini"
    assert seen == ["gemini"]                    # second call goes straight there


def test_cooldown_expires_so_a_topped_up_account_recovers(monkeypatch):
    """Self-healing matters: adding credits must not require a restart."""
    monkeypatch.setenv("AUGHOR_QUOTA_COOLDOWN_S", "0")
    P._mark_quota_exhausted("openrouter")
    assert not P._in_quota_cooldown("openrouter")
    assert "openrouter" not in P._quota_cooldown      # expired entry is dropped


def test_cooldown_holds_within_its_window(monkeypatch):
    monkeypatch.setenv("AUGHOR_QUOTA_COOLDOWN_S", "900")
    P._mark_quota_exhausted("openrouter")
    assert P._in_quota_cooldown("openrouter")
    assert not P._in_quota_cooldown("gemini")        # scoped to the backend that failed


def test_cooled_backend_is_dropped_from_the_fallback_chain(monkeypatch):
    """A spent FALLBACK deserves the same treatment as a spent primary."""
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "gemini,groq")
    monkeypatch.setenv("AUGHOR_QUOTA_COOLDOWN_S", "900")
    monkeypatch.setattr(P, "_active_key", lambda b: "k")
    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    assert prov._fallback_candidates() == ["gemini", "groq"]
    P._mark_quota_exhausted("gemini")
    assert prov._fallback_candidates() == ["groq"]


def test_primary_still_tried_when_it_is_the_only_option(monkeypatch):
    """Cooldown must never strand a call: with no fallback configured, the primary
    is still attempted so the caller gets a real error (or a recovered quota)."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        text: str = "ok"

    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")
    monkeypatch.setenv("AUGHOR_QUOTA_COOLDOWN_S", "900")
    P._mark_quota_exhausted("openrouter")

    seen: list[str] = []

    def fake_complete_on(client, backend, model, system, user, response_model,
                         temperature, **kw):
        seen.append(backend)
        return _Out(text="recovered")

    monkeypatch.setattr(P.LLMProvider, "_complete_on", staticmethod(fake_complete_on))
    prov = P.LLMProvider.__new__(P.LLMProvider)
    prov.backend, prov.role = "openrouter", "narrator"
    prov._model, prov._client, prov._base_url = "m:free", object(), "u"
    monkeypatch.setattr(prov, "_warn_if_over_window", lambda *a, **k: None)

    assert prov.complete("s", "u", _Out, 0.3).text == "recovered"
    assert seen == ["openrouter"]


# ── Server-stated retry delay ────────────────────────────────────────────────
# Our ladder tops out near 15s. Gemini's free-tier throttle says "Please retry in 42.3s",
# so every retry was spent inside a window that had not reopened — the call failed even
# though waiting slightly longer would have succeeded.

def test_retry_after_is_parsed_from_the_provider_message():
    msg = ("429 You exceeded your current quota … limit: 20, model: gemini-3.6-flash "
           "Please retry in 42.327199508s.")
    assert P._retry_after_seconds(Exception(msg)) == pytest.approx(42.327, abs=0.01)


def test_retry_after_handles_the_common_spellings():
    for msg, want in (("Retry-After: 30s", 30.0),
                      ('"retryDelay": "17s"', 17.0),
                      ("please retry again in 5s", 5.0)):
        assert P._retry_after_seconds(Exception(msg)) == pytest.approx(want), msg


def test_retry_after_absent_returns_none():
    assert P._retry_after_seconds(Exception("429 Too Many Requests")) is None


def test_retry_after_is_capped():
    """A pathological value must not park a request indefinitely."""
    assert P._retry_after_seconds(Exception("retry in 99999s")) == P._RETRY_AFTER_MAX_S


def test_ladder_waits_the_server_stated_delay(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(P.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "1")
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("429 rate limit. Please retry in 42.3s")
        return "ok"

    assert P._run_resilient(do, "u-retry-after") == "ok"
    assert slept and slept[0] == pytest.approx(42.3, abs=0.01)   # not the ~2s ladder guess


def test_ladder_keeps_its_own_backoff_when_the_delay_is_shorter(monkeypatch):
    """The server's number wins only when it is LONGER — a "retry in 0s" must not
    turn the ladder into a hot loop."""
    slept: list[float] = []
    monkeypatch.setattr(P.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "1")
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("429 rate limit. Please retry in 0.1s")
        return "ok"

    assert P._run_resilient(do, "u-retry-short") == "ok"
    assert slept[0] >= 2.0


def test_gemini_daily_quota_id_is_an_exhausted_allowance():
    """Verbatim from a live Gemini 429. The prose is IDENTICAL to its per-minute throttle —
    only the quotaId distinguishes them, and it spells the period with no separator. It also
    advertises "retry in 36s", which is wrong for a day-long block: honouring that retried a
    dead backend three times and cost ~110s. The id is the authority, not the prose."""
    msg = ('Error code: 429 - You exceeded your current quota, please check your plan and '
           'billing details. "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier". '
           'Please retry in 36.284972143s.')
    assert P._is_quota_exhausted(Exception(msg))
    assert not P._is_transient(Exception(msg))     # no retry, and no cooldown-defeating wait
