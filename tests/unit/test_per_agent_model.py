"""Per-agent LLM model selection — an agent (Scout/Analyst/…) can be pinned to a specific
model, resolved override-wins from governance and applied per-run via a contextvar that
get_provider() consults. Hermetic: provider construction needs no network; the governance
store uses the test Ledger."""
from __future__ import annotations

import aughor.llm.provider as provider
from aughor.kernel.agents import effective_governance, set_governance


# ── provider: explicit pin + contextvar pin ──────────────────────────────────────

def test_get_provider_pins_explicit_model():
    p = provider.get_provider("coder", model="some-custom-model:latest")
    assert p._model == "some-custom-model:latest"
    # cached per (role, model) — same pin returns the same object
    assert provider.get_provider("coder", model="some-custom-model:latest") is p
    # a different role with the same pin is a distinct provider
    assert provider.get_provider("narrator", model="some-custom-model:latest") is not p


def test_run_model_contextvar_is_honored_by_get_provider():
    token = provider.set_run_model("run-scoped-model")
    try:
        assert provider.get_provider("coder")._model == "run-scoped-model"
        assert provider.get_provider("narrator")._model == "run-scoped-model"
    finally:
        provider.reset_run_model(token)
    # after reset, the role default is back (not the pinned model)
    assert provider.get_provider("coder")._model != "run-scoped-model"


def test_explicit_model_overrides_the_contextvar():
    token = provider.set_run_model("run-scoped-model")
    try:
        assert provider.get_provider("coder", model="explicit-wins")._model == "explicit-wins"
    finally:
        provider.reset_run_model(token)


def test_empty_run_model_is_a_noop():
    token = provider.set_run_model("")          # blank → treated as no pin
    try:
        assert provider.current_run_model() is None
    finally:
        provider.reset_run_model(token)


# ── governance: per-agent model resolves override-wins ───────────────────────────

def test_set_and_resolve_per_agent_model():
    set_governance("scout", model="scout-special-model")
    gov = effective_governance("scout")
    assert gov.model == "scout-special-model"
    # budget/enabled still resolve alongside it
    assert gov.enabled is True
    # clearing with "" returns to the role default (None)
    set_governance("scout", model="")
    assert effective_governance("scout").model is None


def test_workspace_model_override_wins_over_app():
    set_governance("analyst", model="app-model")                       # app scope
    set_governance("analyst", scope="ws-1", model="workspace-model")   # workspace scope
    assert effective_governance("analyst").model == "app-model"
    assert effective_governance("analyst", workspace_id="ws-1").model == "workspace-model"
    # cleanup
    set_governance("analyst", model="")
    set_governance("analyst", scope="ws-1", model="")
