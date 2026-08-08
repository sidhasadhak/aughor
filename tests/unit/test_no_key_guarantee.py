"""The mechanical no-key guarantee (unified plan Layer 0.2).

The suite must be structurally unable to spend money: no provider credential in the
environment, no fallback chain to walk, no runtime config inherited from the
developer's machine. Discipline already failed once — a free primary's fallback
chain reached a PAID Together backend because the developer's ``.env`` held a key
(``provider-failover-chain``, 2026-07) — so the guarantee is enforcement in
``tests/conftest.py`` (`_no_provider_credentials`, ``AUGHOR_LLM_CONFIG_PATH``), and
this file is the proof that the enforcement holds.
"""
from __future__ import annotations

import os

from aughor.llm import provider as P


def test_every_registered_provider_credential_is_scrubbed():
    """Driven off _KEY_ENV itself: a backend added to the registry is asserted here
    with zero test changes — the scrub can never lag the registry."""
    for backend, var in P._KEY_ENV.items():
        assert os.getenv(var) is None, (
            f"{var} (backend {backend!r}) is visible to the test process — the "
            "conftest scrub must delete every registered provider credential")


def test_fallback_chain_is_pinned_empty():
    assert os.environ.get("AUGHOR_FALLBACK_BACKENDS") == "none"
    assert P._fallback_backends() == ()


def test_none_sentinel_and_default_semantics(monkeypatch):
    """'none' is the explicit empty-chain spelling; '' keeps its historical meaning
    (the default order) — pinned so the sentinel can never silently swallow the
    production default."""
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "NONE")
    assert P._fallback_backends() == ()
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "")
    assert P._fallback_backends() == P._FALLBACK_ORDER
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "gemini, nosuchbackend , groq")
    assert P._fallback_backends() == ("gemini", "groq")


def test_runtime_llm_config_is_isolated_from_the_developers_machine():
    """data/llm_config.json holds the operator's backend choice and encrypted keys,
    and api.py's import-time load_dotenv brings in the secret that decrypts them —
    so an unisolated config path is a paid binding with zero keys in the test env."""
    isolated = os.environ.get("AUGHOR_LLM_CONFIG_PATH", "")
    assert isolated, "conftest must pin AUGHOR_LLM_CONFIG_PATH before any app import"
    assert str(P._CONFIG_PATH) == isolated
    assert "aughor-test-stores-" in isolated  # the throwaway temp tree, never data/


def test_no_keyed_backend_resolves_a_key(monkeypatch):
    """End-to-end through _active_key with the runtime layer pinned empty: the env
    layer (the only other source) must resolve nothing for every keyed backend."""
    monkeypatch.setattr(P, "_runtime", {})
    for backend in P.NEEDS_KEY:
        assert P._active_key(backend) == ""


def test_fallback_candidates_are_empty_for_a_test_provider():
    prov = P.LLMProvider(P.FAUX_BACKEND, "coder")
    assert prov._fallback_candidates() == []
