"""Runtime LLM provider config — precedence, key encryption, cache invalidation."""
import json

import pytest

from aughor.llm import provider as P

_ENV_VARS = (
    "AUGHOR_BACKEND", "AUGHOR_MODEL", "AUGHOR_CODER_MODEL", "AUGHOR_NARRATOR_MODEL",
    "AUGHOR_FAST_NARRATOR_MODEL", "GROQ_API_KEY", "TOGETHER_API_KEY", "ANTHROPIC_API_KEY",
)


@pytest.fixture
def clean_cfg(tmp_path, monkeypatch):
    """Isolate the config file + module state + env so tests see only what they set."""
    monkeypatch.setattr(P, "_CONFIG_PATH", tmp_path / "llm_config.json")
    monkeypatch.setattr(P, "_runtime", None)
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    P._providers.clear()
    P._cache_version = -1
    P.load_config()
    yield tmp_path / "llm_config.json"


def test_defaults_when_empty(clean_cfg):
    c = P.current_config()
    assert c["backend"] == "ollama"
    assert c["models"]["coder"] == "qwen3-coder-next:cloud"   # ollama built-in default
    assert c["models"]["fast"] == "qwen3-coder-next:cloud"    # fast shares the coder default
    assert c["models"]["narrator"] == "kimi-k2.6:cloud"       # narrator is the one exception
    assert set(c["backends"]) >= {"ollama", "groq", "anthropic"}
    assert c["keys_set"] == {"groq": False, "together": False, "anthropic": False,
                             "gemini": False, "openrouter": False}


def test_config_surfaces_per_role_capability_profile(clean_cfg):
    # §5b: the config view carries the vended capability per role so Settings → Inference
    # can show what the bound model can do — and, crucially, where its prompts go.
    c = P.current_config()
    caps = c["capabilities"]
    assert set(caps) == {"coder", "narrator", "fast"}
    coder = caps["coder"]
    # the shipped default (qwen3-coder-next:cloud) egresses to Ollama Cloud — flagged honestly
    assert coder["privacy_class"] == "public_api"
    assert coder["cache_mode"] == "auto_prefix_unverified"
    assert coder["cost"] == "unknown"
    assert {"cache_mode", "tooling", "structured_output", "token_accounting",
            "max_context", "privacy_class", "cost"} <= set(coder)


def test_local_ollama_model_is_marked_on_device(clean_cfg):
    # A bare (non-:cloud) model on a localhost Ollama is local — no egress.
    c = P.set_config({"models": {"coder": "qwen3-coder:7b"}})
    assert c["capabilities"]["coder"]["privacy_class"] == "local"
    assert c["capabilities"]["coder"]["cost"] == "flat"


def test_backend_switch_uses_that_backends_default_model(clean_cfg):
    c = P.set_config({"backend": "groq"})
    assert c["backend"] == "groq"
    # NOT an ollama/env model — groq's own default
    assert c["models"]["coder"] == "llama-3.3-70b-versatile"


def test_model_override_roundtrip(clean_cfg):
    P.set_config({"backend": "groq"})
    c = P.set_config({"models": {"coder": "my-special-model"}})
    assert c["models"]["coder"] == "my-special-model"
    assert c["models_set"]["coder"] == "my-special-model"
    # clearing reverts to the backend default
    c = P.set_config({"models": {"coder": ""}})
    assert c["models"]["coder"] == "llama-3.3-70b-versatile"
    assert "coder" not in c["models_set"]


def test_keys_are_encrypted_masked_and_never_returned(clean_cfg):
    c = P.set_config({"keys": {"groq": "sk-secret-abc123"}})
    assert c["keys_set"]["groq"] is True
    assert "sk-secret-abc123" not in json.dumps(c)          # never in the API view
    raw = clean_cfg.read_text()
    assert "sk-secret-abc123" not in raw and "enc:v1:" in raw  # encrypted on disk
    assert P._active_key("groq") == "sk-secret-abc123"        # decrypt path works
    # a masked echo leaves it unchanged
    P.set_config({"keys": {"groq": "••••••"}})
    assert P._active_key("groq") == "sk-secret-abc123"
    # empty string clears it
    c = P.set_config({"keys": {"groq": ""}})
    assert c["keys_set"]["groq"] is False
    assert P._active_key("groq") == ""


def test_invalid_backend_raises(clean_cfg):
    with pytest.raises(ValueError):
        P.set_config({"backend": "does-not-exist"})


def test_get_provider_rebuilds_on_config_change(clean_cfg):
    p1 = P.get_provider("coder")
    assert p1.backend == "ollama"
    P.set_config({"backend": "groq", "keys": {"groq": "k"}})
    p2 = P.get_provider("coder")
    assert p2.backend == "groq"
    assert p2 is not p1                                       # cache was invalidated


def test_base_url_override_for_local_backend(clean_cfg):
    c = P.set_config({"backend": "ollama", "base_urls": {"ollama": "http://gpu-box:11434/v1"}})
    assert c["base_urls"]["ollama"] == "http://gpu-box:11434/v1"
    c = P.set_config({"base_urls": {"ollama": ""}})
    assert c["base_urls"]["ollama"] == "http://localhost:11434/v1"  # back to default
