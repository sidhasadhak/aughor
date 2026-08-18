"""/health LLM readiness field — shape, semantics, and resilience.

`aughor up` reads this field to print the boot summary, so its shape is a
contract: {backend, model, key_present, ready, reason}, derived from config only
(no network), and /health must keep answering 200 even when the LLM config is
broken.

`ready` is NOT `key_present`. Nothing ships a default model, so the default Ollama
binding — which needs no key — resolved to an empty model and still reported ready;
`aughor up` printed "ollama · ? · ready" on an install where the first question was
guaranteed to fail with NoModelConfigured.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_has_llm_field_with_contract_shape(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "llm" in body, f"/health body missing 'llm': {body}"
    llm = body["llm"]
    assert set(llm) >= {"backend", "model", "key_present", "ready", "reason"}, llm
    assert isinstance(llm["key_present"], bool)
    assert isinstance(llm["ready"], bool)


def test_health_llm_ready_requires_a_model_not_just_a_key(client: TestClient) -> None:
    """The regression this field existed to report. A keyless backend with no model
    configured must read as NOT ready, and say which half is missing."""
    llm = client.get("/health").json()["llm"]
    if llm["model"]:
        assert llm["ready"] == llm["key_present"]
        assert llm["reason"] is None or llm["reason"] == "no_key"
    else:
        assert llm["ready"] is False, f"no model configured, yet ready: {llm}"
        assert llm["reason"] == "no_model", llm


def test_llm_readiness_keyless_backend_is_ready(monkeypatch) -> None:
    """Local backends (ollama/lmstudio) need no key → ready by construction."""
    import aughor.llm.provider as provider
    from aughor.routers import system

    monkeypatch.setattr(
        provider, "resolve_binding",
        lambda role="coder", **kw: ("ollama", "qwen2.5-coder:14b", "http://localhost:11434/v1"),
    )
    out = system._llm_readiness()
    assert out == {
        "backend": "ollama",
        "model": "qwen2.5-coder:14b",
        "key_present": True,
        "ready": True,
        "reason": None,
    }


def test_llm_readiness_keyless_backend_without_a_model_is_not_ready(monkeypatch) -> None:
    """The shipped default: Ollama needs no key, and no model ships. `ready` used to
    mirror `key_present`, so this exact state reported ready."""
    import aughor.llm.provider as provider
    from aughor.routers import system

    monkeypatch.setattr(
        provider, "resolve_binding",
        lambda role="coder", **kw: ("ollama", "", "http://localhost:11434/v1"),
    )
    out = system._llm_readiness()
    assert out["key_present"] is True, "ollama needs no key — that part was right"
    assert out["ready"] is False, "no model configured means every request raises"
    assert out["reason"] == "no_model"


def test_llm_readiness_keyed_backend_without_key_is_not_ready(monkeypatch) -> None:
    import aughor.llm.provider as provider
    from aughor.routers import system

    monkeypatch.setattr(
        provider, "resolve_binding",
        lambda role="coder", **kw: ("groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
    )
    monkeypatch.setattr(provider, "_active_key", lambda backend: "")
    out = system._llm_readiness()
    assert out["backend"] == "groq"
    assert out["key_present"] is False
    assert out["ready"] is False
    assert out["reason"] == "no_key", "a missing key must not be reported as a missing model"


def test_llm_readiness_keyed_backend_with_key_is_ready(monkeypatch) -> None:
    import aughor.llm.provider as provider
    from aughor.routers import system

    monkeypatch.setattr(
        provider, "resolve_binding",
        lambda role="coder", **kw: ("anthropic", "claude-sonnet-4-6", ""),
    )
    monkeypatch.setattr(provider, "_active_key", lambda backend: "sk-ant-something")
    out = system._llm_readiness()
    assert out["key_present"] is True
    assert out["ready"] is True
    assert out["reason"] is None


def test_health_still_200_when_llm_config_is_broken(client: TestClient, monkeypatch) -> None:
    """A broken provider config must degrade the llm field, never 500 /health."""
    import aughor.llm.provider as provider

    def _boom(*a, **kw):
        raise RuntimeError("llm config exploded")

    monkeypatch.setattr(provider, "resolve_binding", _boom)
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm"]["ready"] is False
    assert body["llm"]["key_present"] is False
    assert body["llm"]["backend"] is None
