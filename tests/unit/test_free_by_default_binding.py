"""Free-by-default model bindings — paid is an explicit act, never a typo.

The deployment's posture: OpenRouter's `:free` tier is the default; the credit
balance is a threshold reserve, not a spend budget. Binding a paid model —
centrally (roles) or per-agent (governance pin) — must name `allow_paid`.
BYO-key backends are the operator's own paid choice and pass untouched.
"""
from __future__ import annotations

import pytest

from aughor.llm.provider import ensure_free_or_allowed, set_config
from aughor.control_plane.inference import _cost, _privacy_class


# ── the guard itself ────────────────────────────────────────────────────────────

def test_free_models_bind_without_ceremony():
    ensure_free_or_allowed("openrouter", "nvidia/nemotron-3-nano-30b-a3b:free")


def test_paid_openrouter_model_is_refused_without_consent():
    with pytest.raises(ValueError, match="paid OpenRouter model"):
        ensure_free_or_allowed("openrouter", "moonshotai/kimi-k3")


def test_paid_openrouter_model_binds_with_explicit_consent():
    ensure_free_or_allowed("openrouter", "moonshotai/kimi-k3", allow_paid=True)


def test_byo_key_backends_pass_untouched():
    ensure_free_or_allowed("anthropic", "claude-opus-5")
    ensure_free_or_allowed("gemini", "gemini-3.5-flash-lite")


def test_empty_model_is_a_clear_not_a_bind():
    ensure_free_or_allowed("openrouter", "")


# ── the guard wired into the config writer ──────────────────────────────────────

@pytest.fixture()
def _isolated_config(monkeypatch):
    """set_config reads/writes the on-disk config — capture it in memory."""
    import aughor.llm.provider as provider

    store: dict = {"backend": "openrouter"}
    monkeypatch.setattr(provider, "_read_config", lambda: dict(store))
    monkeypatch.setattr(provider, "write_config", store.update)
    return store


def test_set_config_refuses_a_silent_paid_bind(_isolated_config):
    with pytest.raises(ValueError, match="paid OpenRouter model"):
        set_config({"models": {"narrator": "moonshotai/kimi-k3"}})
    assert "narrator" not in (_isolated_config.get("models") or {})


def test_set_config_binds_paid_with_allow_paid(_isolated_config):
    set_config({"models": {"narrator": "moonshotai/kimi-k3"}, "allow_paid": True})
    assert _isolated_config["models"]["narrator"] == "moonshotai/kimi-k3"


def test_set_config_binds_free_without_ceremony(_isolated_config):
    set_config({"models": {"fast": "nvidia/nemotron-3-nano-30b-a3b:free"}})
    assert _isolated_config["models"]["fast"] == "nvidia/nemotron-3-nano-30b-a3b:free"


# ── the per-agent pin takes the same gate ───────────────────────────────────────

def test_agent_model_pin_takes_the_same_gate(client, monkeypatch):
    import aughor.llm.provider as provider
    monkeypatch.setattr(provider, "_active_backend", lambda: "openrouter")

    r = client.patch("/agents/analyst", json={"model": "moonshotai/kimi-k3"})
    assert r.status_code == 400
    assert "paid OpenRouter model" in r.json()["detail"]

    ok = client.patch("/agents/analyst",
                      json={"model": "moonshotai/kimi-k3", "allow_paid": True})
    assert ok.status_code == 200
    assert ok.json()["governance"]["model"] == "moonshotai/kimi-k3"

    # clear the pin back to the role default
    assert client.patch("/agents/analyst", json={"model": ""}).status_code == 200


# ── the capability chips stop lying about OpenRouter ────────────────────────────

def test_openrouter_cost_classifies_by_free_suffix():
    assert _cost("openrouter", "x:free", "") == "free"
    assert _cost("openrouter", "moonshotai/kimi-k3", "") == "per_token"


def test_openrouter_is_a_public_api_not_a_private_endpoint():
    assert _privacy_class("openrouter", "any", "") == "public_api"
