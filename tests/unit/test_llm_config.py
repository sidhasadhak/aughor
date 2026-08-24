"""Runtime LLM provider config — precedence, key encryption, cache invalidation."""
import json

import pytest

from aughor.llm import provider as P

# Every env var that can move what `current_config()` reports. GEMINI_API_KEY and
# OPENROUTER_API_KEY were missing until 2026-08-04, so `test_defaults_when_empty` — which
# asserts `keys_set` is all-False — failed for any developer whose `.env` set either. A
# fixture named `clean_cfg` has to clear everything it claims to isolate, or it reports a
# pass that depends on whose machine it ran on.
_ENV_VARS = (
    "AUGHOR_BACKEND", "AUGHOR_MODEL", "AUGHOR_CODER_MODEL", "AUGHOR_NARRATOR_MODEL",
    "AUGHOR_FAST_NARRATOR_MODEL", "GROQ_API_KEY", "TOGETHER_API_KEY", "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY", "OPENROUTER_API_KEY",
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
    # NO model, for any role. This assertion used to name the shipped ollama default,
    # and it is exactly how a dead id survived: the pair before it —
    # `qwen3-coder-next:cloud` (RETIRED 2026-07-15) and `kimi-k2.6:cloud` (subscription
    # required) — were BOTH dead, and this test pinned the first as correct for three
    # weeks. Nothing ships a default now, so there is nothing here to go stale.
    assert c["models"]["coder"] == ""
    assert c["models"]["fast"] == ""
    assert c["models"]["narrator"] == ""
    assert set(c["backends"]) >= {"ollama", "groq", "anthropic"}
    assert c["keys_set"] == {"groq": False, "together": False, "anthropic": False,
                             "gemini": False, "openrouter": False}


def test_config_surfaces_per_role_capability_profile(clean_cfg):
    # §5b: the config view carries the vended capability per role so Settings → Inference
    # can show what the bound model can do — and, crucially, where its prompts go.
    c = P.current_config()
    caps = c["capabilities"]
    assert set(caps) == {"coder", "narrator", "fast"}
    # Bind something `:cloud` so the classifier has a model to read; nothing ships one
    # any more, and an unbound role has no capabilities to describe.
    P.set_config({"models": {"coder": "some-model:cloud"}})
    coder = P.current_config()["capabilities"]["coder"]
    # a `:cloud` binding egresses to a hosted API — flagged honestly
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


def test_backend_switch_does_not_inherit_the_previous_backends_model(clean_cfg):
    c = P.set_config({"backend": "groq"})
    assert c["backend"] == "groq"
    # The CI-5a precedence trap: an ollama/env model name must NOT leak into a
    # deliberately-chosen backend. It used to resolve to groq's own built-in default;
    # with none shipped it resolves to nothing, and the operator picks one.
    assert c["models"]["coder"] == ""


def test_model_override_roundtrip(clean_cfg):
    P.set_config({"backend": "groq"})
    c = P.set_config({"models": {"coder": "my-special-model"}})
    assert c["models"]["coder"] == "my-special-model"
    assert c["models_set"]["coder"] == "my-special-model"
    # clearing leaves the role unbound — there is no backend default to revert to
    c = P.set_config({"models": {"coder": ""}})
    assert c["models"]["coder"] == ""
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
    # Both bindings need an explicit model: constructing a provider for an unbound role
    # raises NoModelConfigured, which is the point of this change and not what this
    # test is about.
    P.set_config({"models": {"coder": "local/one"}})
    p1 = P.get_provider("coder")
    assert p1.backend == "ollama"
    P.set_config({"backend": "groq", "keys": {"groq": "k"},
                  "models": {"coder": "hosted/two"}})
    p2 = P.get_provider("coder")
    assert p2.backend == "groq"
    assert p2 is not p1                                       # cache was invalidated


def test_base_url_override_for_local_backend(clean_cfg):
    c = P.set_config({"backend": "ollama", "base_urls": {"ollama": "http://gpu-box:11434/v1"}})
    assert c["base_urls"]["ollama"] == "http://gpu-box:11434/v1"
    c = P.set_config({"base_urls": {"ollama": ""}})
    assert c["base_urls"]["ollama"] == "http://localhost:11434/v1"  # back to default


def test_a_sized_cloud_tag_is_not_reported_as_on_device(clean_cfg):
    """`privacy_class` tells an operator whether their prompts left the machine, so an
    error in the permissive direction is the one this surface must never make.

    A bare `endswith(":cloud")` test missed every SIZED cloud tag, and three of the five
    ollama ids this repo ships carry one. They were reported `local` / `flat` while
    egressing to Ollama Cloud (found 2026-08-04).
    """
    for model in ("gemma4:31b-cloud", "gpt-oss:120b-cloud", "qwen3.5:397b-cloud",
                  "kimi-k2.6:cloud"):
        c = P.set_config({"backend": "ollama", "models": {"coder": model}})
        cap = c["capabilities"]["coder"]
        assert cap["privacy_class"] == "public_api", f"{model} reported as on-device"
        assert cap["cost"] == "unknown", f"{model} reported with local flat cost"


def test_a_genuinely_local_tag_is_still_local(clean_cfg):
    """The fix must not sweep in real on-device models — `31b` is a size, not a cloud."""
    for model in ("qwen2.5-coder:14b", "gemma4:31b", "llama3:latest"):
        c = P.set_config({"backend": "ollama", "models": {"coder": model}})
        assert c["capabilities"]["coder"]["privacy_class"] == "local", model


# ── the third key state ──────────────────────────────────────────────────────────

def _undecryptable() -> str:
    """A well-formed ciphertext written under a DIFFERENT vault key.

    Not `enc:v1:garbage`: malformed input can fail base64 decoding rather than
    decryption, which would exercise a different branch than the one that bites in
    production, where the ciphertext is perfectly good and the key that made it is gone.
    """
    from cryptography.fernet import Fernet
    return "enc:v1:" + Fernet(Fernet.generate_key()).encrypt(b"sk-real-key").decode()


def test_a_stored_key_that_cannot_be_decrypted_is_not_reported_as_set(clean_cfg):
    """It answered `keys_set: true` and the provider rejected the call, so a person was
    sent to rotate a key that was never the problem. Both answers a boolean can give are
    wrong here; the state that names the fix is the third one."""
    clean_cfg.write_text(json.dumps({"keys": {"groq": _undecryptable()}}))
    P._runtime = None
    P._cache_version = -1
    P.load_config()

    c = P.current_config()

    assert c["keys_state"]["groq"] == "unreadable"
    assert c["keys_set"]["groq"] is False, "a key that cannot be read is not a key that is set"
    # The ciphertext is what reaches the provider today — that is the defect this names,
    # and the reason the state has to be surfaced rather than silently treated as unset.
    assert P._active_key("groq").startswith("enc:v1:")


def test_the_other_two_states_are_unchanged(clean_cfg):
    """Prove the third state is an addition, not a reinterpretation of the other two."""
    assert P.current_config()["keys_state"]["groq"] == "unset"

    P.set_config({"keys": {"groq": "sk-secret-abc123"}})
    c = P.current_config()
    assert c["keys_state"]["groq"] == "set" and c["keys_set"]["groq"] is True


def test_the_org_overlay_reads_a_stored_key_rather_than_assuming_it(clean_cfg):
    """The org panel reported `True` for the mere PRESENCE of a stored key, without ever
    decrypting it — so it could not tell a working tenant key from an unreadable one."""
    from aughor.llm.org_config import _stored_key_state
    from aughor.secretvault import encrypt_secret

    assert _stored_key_state(None) == "unset"
    assert _stored_key_state("") == "unset"
    assert _stored_key_state(_undecryptable()) == "unreadable"
    assert _stored_key_state(encrypt_secret("sk-tenant-key")) == "set"
