"""Inference plane — `vend_llm` + the capability profile (PLATFORM_ARCHITECTURE.md §5b).

Invariant #7: inference is *vended, never ambient*. The control plane resolves the
binding (Org → Workspace → Agent) once and hands back a scoped `InferenceCapability`
that describes the bound backend *and* what it can do (cache_mode, privacy_class, …), so
nothing downstream branches on provider identity. These tests pin the capability profile
per backend/model, the org-from-context behaviour, and — the load-bearing one — *parity*:
the vended capability always describes the binding a real `get_provider().complete()` uses.

Hermetic: the profile is a pure function of (backend, model, base_url); resolution reads
the process config and builds no network clients beyond what `get_provider` already does.
"""
from __future__ import annotations

import aughor.llm.provider as provider
from aughor.org import using_org
from aughor.platform import InferenceCapability, capability_for, vend_llm


# ── the capability profile (pure: strings → declared behaviour) ───────────────

class TestProfile:
    def test_anthropic_is_explicit_breakpoint_public_paid(self):
        cap = capability_for("anthropic", "claude-sonnet-4-6", "narrator", "")
        assert cap.cache_mode == "explicit_breakpoint"
        assert cap.privacy_class == "public_api"
        assert cap.cost == "per_token"
        assert cap.tooling == "native_tools"
        assert cap.structured_output == "native"
        assert cap.max_context == 200_000

    def test_local_ollama_reasoning_model_is_local_free_native(self):
        cap = capability_for("ollama", "qwen3-coder-next:latest", "coder",
                             "http://localhost:11434/v1")
        assert cap.cache_mode == "auto_prefix"
        assert cap.privacy_class == "local"
        assert cap.cost == "flat"
        assert cap.tooling == "native_tools"            # qwen3 → TOOLS mode
        assert cap.structured_output == "native"

    def test_cloud_ollama_egresses_and_is_unverified(self):
        # ':cloud' tag → hosted egress: public_api, unknown cost, prefix reuse unproven.
        cap = capability_for("ollama", "qwen3-coder-next:cloud", "coder",
                             "http://localhost:11434/v1")
        assert cap.cache_mode == "auto_prefix_unverified"
        assert cap.privacy_class == "public_api"
        assert cap.cost == "unknown"

    def test_self_hosted_ollama_is_private_endpoint(self):
        cap = capability_for("ollama", "llama-3.3-70b", "coder",
                             "https://llm.internal.acme.com/v1")
        assert cap.privacy_class == "private_endpoint"
        assert cap.cost == "unknown"

    def test_lmstudio_is_local_native_but_estimated_tokens(self):
        cap = capability_for("lmstudio", "local-model", "coder", "http://localhost:1234/v1")
        assert cap.privacy_class == "local"
        assert cap.structured_output == "native"        # JSON_SCHEMA mode
        assert cap.token_accounting == "estimated"      # usage block often omitted

    def test_groq_is_public_auto_prefix_emulated(self):
        cap = capability_for("groq", "llama-3.3-70b-versatile", "coder",
                             "https://api.groq.com/openai/v1")
        assert cap.cache_mode == "auto_prefix"
        assert cap.privacy_class == "public_api"
        assert cap.structured_output == "instructor_emulated"   # plain JSON mode
        assert cap.token_accounting == "exact"

    def test_gemini_is_public_paid_native_million_context(self):
        cap = capability_for("gemini", "gemini-flash-latest", "coder",
                             "https://generativelanguage.googleapis.com/v1beta/openai/")
        assert cap.privacy_class == "public_api"          # Google's hosted API — governance routes it as such
        assert cap.cost == "per_token"
        assert cap.tooling == "native_tools"
        assert cap.structured_output == "native"          # TOOLS / json_schema mode enforces the schema
        assert cap.token_accounting == "exact"
        assert cap.max_context == 1_048_576               # 1M-token window (vs the 32k default)

    def test_unknown_model_falls_back_to_conservative_context(self):
        assert capability_for("ollama", "some-tiny-model", "fast", "http://localhost:11434/v1").max_context == 32_768


# ── org stamping (Invariant #1) ───────────────────────────────────────────────

class TestOrgScope:
    def test_org_comes_from_context(self):
        with using_org("acme"):
            assert vend_llm("coder").org_id == "acme"

    def test_explicit_org_overrides_context(self):
        with using_org("acme"):
            assert vend_llm("coder", org_id="globex").org_id == "globex"

    def test_defaults_to_bootstrap_org(self):
        assert vend_llm("coder").org_id == "default"


# ── parity: the capability describes the binding a real call uses ─────────────

class TestParityWithProvider:
    def test_vend_matches_role_default_binding(self):
        cap = vend_llm("coder")
        p = provider.get_provider("coder")
        assert (cap.backend, cap.model) == (p.backend, p._model)
        assert cap.base_url == p._base_url

    def test_explicit_pin_flows_through_to_capability(self):
        cap = vend_llm("coder", model="pinned-model:tag")
        assert cap.model == "pinned-model:tag"
        assert cap.model == provider.get_provider("coder", model="pinned-model:tag")._model

    def test_agent_override_contextvar_is_honoured(self):
        token = provider.set_run_model("run-scoped-model")
        try:
            assert vend_llm("coder").model == "run-scoped-model"     # agent override wins
        finally:
            provider.reset_run_model(token)
        assert vend_llm("coder").model != "run-scoped-model"          # default restored

    def test_provider_capability_property_matches_vend(self):
        p = provider.get_provider("narrator")
        cap = p.capability
        assert isinstance(cap, InferenceCapability)
        assert (cap.backend, cap.model, cap.role) == (p.backend, p._model, "narrator")
        assert cap == vend_llm("narrator")


# ── the capability is a working front door ────────────────────────────────────

def test_capability_provider_round_trips_to_the_bound_model():
    cap = vend_llm("coder", model="round-trip-model:tag")
    p = cap.provider()
    assert p._model == "round-trip-model:tag"
    assert p is provider.get_provider("coder", model="round-trip-model:tag")  # cached


# ── gemini backend construction (hermetic — no network at build time) ──────────

class TestGeminiProvider:
    URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_builder_requires_a_key(self):
        import pytest
        with pytest.raises(RuntimeError, match="Gemini API key"):
            provider._build_gemini_client(self.URL, "")

    def test_provider_constructs_gemini_openai_compat_binding(self):
        p = provider.LLMProvider("gemini", "coder", model="gemini-flash-latest",
                                 api_key="test-key", base_url=self.URL)
        assert p.backend == "gemini"
        assert p._base_url == self.URL
        assert p._client is not None
        # instructor wraps an OpenAI client pointed at the Gemini OpenAI-compat endpoint
        assert "generativelanguage.googleapis.com" in str(p._client.client.base_url)

    def test_instructor_mode_is_env_overridable(self, monkeypatch):
        import instructor
        monkeypatch.setenv("AUGHOR_GEMINI_INSTRUCTOR_MODE", "JSON")
        client = provider._build_gemini_client(self.URL, "test-key")
        assert getattr(client, "mode", None) == instructor.Mode.JSON
