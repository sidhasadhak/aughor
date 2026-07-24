"""Wave R2 — reading the provider's error BODY, not just its status code.

"Google's quotaId is the authority, its retry-in prose lies" generalised chain-wide.
A 4xx flattens together a wrong key, a wrong model id, a wrong base URL and a spent
allowance — four different jobs for whoever has to fix it. Two contracts here:

* a model id the backend will not serve is a CONFIG error and must not be papered over
  by the failover chain, because that is exactly how two non-existent ids shipped as
  defaults and the app kept answering;
* the classifier must never steal a case from the quota/rate-limit path, whose cooldown
  is load-bearing (#197).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from aughor.llm import provider as P
from aughor.llm.provider import BindingConfigError, LLMProvider


class Out(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def _clear_cooldown():
    P._quota_cooldown.clear()
    yield
    P._quota_cooldown.clear()


# ── the marker sets ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Error code: 404 - {'error': {'message': 'The model `foo/bar` does not exist or you "
    "do not have access to it.', 'code': 'model_not_found'}}",
    "model_not_found",
    "404: no such model: llama-9",
    "unknown model 'gemini-99-ultra'",
    "invalid model id supplied",
])
def test_a_bad_model_id_is_recognised(message):
    assert P._is_model_not_found(Exception(message))


@pytest.mark.parametrize("message", [
    "429 Too Many Requests",
    "RESOURCE_EXHAUSTED: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
    "You exceeded your current quota, please check your plan and billing details",
    "insufficient_quota: add credits",
])
def test_quota_and_rate_limits_are_never_read_as_a_bad_id(message):
    """An exhausted free tier sometimes phrases itself as 'you do not have access'.
    Mistaking that for a bad id turns a self-healing 15-minute cooldown into a
    permanent hard failure on a binding that is perfectly fine."""
    exc = Exception(message)
    assert not P._is_model_not_found(exc)


def test_plain_prose_containing_not_found_is_not_a_bad_id():
    """'not found' alone is ordinary text in a SQL error or a tool result that could ride
    along in an exception chain. A false positive here fails a call that would have
    succeeded, so the markers name an IDENTIFIER, never a bare phrase."""
    assert not P._is_model_not_found(Exception("column 'revenue' not found in table orders"))
    assert not P._is_model_not_found(Exception("404 page not found"))


@pytest.mark.parametrize("message,expected", [
    ("Incorrect API key provided: sk-xxx", "bad_key"),
    ("API key not valid. Please pass a valid API key.", "bad_key"),
    ("RESOURCE_EXHAUSTED: quota GenerateRequestsPerDay", "quota_exhausted"),
    ("The model `x` does not exist or you do not have access", "model_not_found"),
    ("429 Too Many Requests: rate limit", "rate_limited"),
    ("<!doctype html><html>404</html>", "wrong_endpoint"),
    ("Connection refused: localhost:11434", "unreachable"),
    ("Request timed out after 30s", "timeout"),
    ("something nobody has seen before", "unknown"),
])
def test_the_health_check_names_the_failure(message, expected):
    assert P.classify_provider_error(Exception(message)) == expected


def test_a_401_status_is_a_bad_key_even_without_the_words():
    exc = Exception("forbidden")
    exc.status_code = 401
    assert P.classify_provider_error(exc) == "bad_key"


def test_every_class_carries_an_action():
    """A health check exists to tell an operator what to DO. A class with no hint is a
    red cross with a paragraph, which is the state this replaced."""
    for cls in P.PROVIDER_ERROR_CLASSES:
        assert P._ERROR_HINTS.get(cls), cls


def test_the_ping_result_carries_reason_and_hint(monkeypatch):
    monkeypatch.setattr(P, "LLMProvider",
                        lambda *a, **k: (_ for _ in ()).throw(
                            Exception("Incorrect API key provided")))
    out = P._ping("openrouter", "some/model")
    assert out["ok"] is False
    assert out["reason"] == "bad_key" and out["hint"]
    assert "Incorrect API key" in out["error"]      # the provider's own words survive


# ── the failover contract ─────────────────────────────────────────────────────

class _Endpoint:
    def __init__(self, exc):
        self.calls = 0
        self._exc = exc

    def create_with_completion(self, **kw):
        self.calls += 1
        raise self._exc


def _provider_raising(exc):
    p = LLMProvider.__new__(LLMProvider)
    p.backend, p.role = "openrouter", "coder"
    p._model, p._base_url = "vendor/guessed-id:free", "http://x"
    ep = _Endpoint(exc)
    p._client = SimpleNamespace(chat=SimpleNamespace(completions=ep))
    return p, ep


def test_a_guessed_model_id_fails_loudly_instead_of_falling_over(monkeypatch):
    """The headline. With a silent failover, a binding on a model that does not exist
    produces working answers from a DIFFERENT model — which is how two non-existent
    OpenRouter ids shipped as defaults and nobody noticed."""
    exc = Exception("404 - The model `vendor/guessed-id:free` does not exist or you do "
                    "not have access to it. (code: model_not_found)")
    p, _ = _provider_raising(exc)
    monkeypatch.setattr(LLMProvider, "_fallback_candidates", lambda self: ["anthropic"])
    monkeypatch.setattr(LLMProvider, "_fallback_provider",
                        lambda self, b: pytest.fail("a config error must not fail over"))
    monkeypatch.setattr(LLMProvider, "_warn_if_over_window", lambda self, s, u: None)

    with pytest.raises(BindingConfigError) as caught:
        p.complete("s", "u", Out)
    msg = str(caught.value)
    assert "vendor/guessed-id:free" in msg and "openrouter" in msg
    assert "Settings" in msg                                   # names the fix
    assert caught.value.__cause__ is exc                       # the raw error survives


def test_the_strict_check_has_an_escape_hatch(monkeypatch):
    """An operator mid-migration can restore the old papering-over behaviour."""
    monkeypatch.setenv("AUGHOR_MODEL_ID_STRICT", "0")
    p, _ = _provider_raising(Exception("model_not_found: nope"))
    tried = []
    monkeypatch.setattr(LLMProvider, "_fallback_candidates", lambda self: ["anthropic"])
    monkeypatch.setattr(LLMProvider, "_fallback_provider",
                        lambda self, b: (tried.append(b), None)[1])
    monkeypatch.setattr(LLMProvider, "_warn_if_over_window", lambda self, s, u: None)
    with pytest.raises(Exception):
        p.complete("s", "u", Out)
    assert tried == ["anthropic"]


def test_a_rate_limit_still_walks_the_chain(monkeypatch):
    """The complement: R2 narrows the failover by exactly one class and must not touch
    the case the chain exists for."""
    p, _ = _provider_raising(Exception("429 Too Many Requests"))
    tried = []
    monkeypatch.setattr(LLMProvider, "_fallback_candidates", lambda self: ["gemini"])
    monkeypatch.setattr(LLMProvider, "_fallback_provider",
                        lambda self, b: (tried.append(b), None)[1])
    monkeypatch.setattr(LLMProvider, "_warn_if_over_window", lambda self, s, u: None)
    with pytest.raises(Exception):
        p.complete("s", "u", Out)
    assert tried == ["gemini"]


def test_a_daily_quota_still_trips_the_cooldown(monkeypatch):
    """#197's cooldown is load-bearing — R2's classification must not intercept it."""
    p, _ = _provider_raising(Exception("RESOURCE_EXHAUSTED: GenerateRequestsPerDay"))
    monkeypatch.setattr(LLMProvider, "_fallback_candidates", lambda self: [])
    monkeypatch.setattr(LLMProvider, "_warn_if_over_window", lambda self, s, u: None)
    with pytest.raises(Exception):
        p.complete("s", "u", Out)
    assert P._in_quota_cooldown("openrouter")
