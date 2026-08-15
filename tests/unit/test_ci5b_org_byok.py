"""CI-5b — org-scoped BYOK, and the two claims that make it safe to multi-tenant.

Keys are encrypted at rest and never leave the server (the read API says only WHICH
keys are set). And applying one org's config touches only that org: no global config
version bump, no other tenant's cached providers evicted — the deployment path's
reload-everything is the behaviour that cancels a running exploration, and these
tests exist to keep the org path from ever growing it.
"""
from __future__ import annotations

import json

import pytest

from aughor.llm import org_config as oc
from aughor.llm import provider as prov
from aughor.org.context import using_org


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Every test starts with no org rows, an empty overlay cache, and the faux
    deployment backend — so provider construction never builds a real client."""
    monkeypatch.setenv("AUGHOR_BACKEND", "faux")
    monkeypatch.delenv("AUGHOR_CODER_MODEL", raising=False)
    for org in ("acme", "globex", "default"):
        oc.clear_org_config(org)
    yield
    for org in ("acme", "globex", "default"):
        oc.clear_org_config(org)


def test_an_org_without_a_row_resolves_the_deployment_config():
    """The default posture: no BYOK row means byte-identical fallthrough, for the
    default org and every unconfigured tenant alike."""
    with using_org("acme"):
        assert prov.active_backend() == "faux"
    assert oc.overlay_for("acme") == {}


def test_keys_are_encrypted_at_rest_and_described_as_booleans():
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-or-secret-123"}})

    raw = oc._row("acme")
    assert raw["keys"]["openrouter"].startswith("enc:v1:"), "plaintext key on disk"
    assert "sk-or-secret" not in json.dumps(raw["keys"])

    desc = oc.describe_org_config("acme")
    assert desc["keys_set"] == {"openrouter": True}
    assert "sk-or-secret" not in json.dumps(desc), "a key value left the server"


def test_the_org_overlay_wins_and_the_neighbour_is_untouched():
    """Org A's binding must serve org A and ONLY org A — the other tenant and the
    default org keep resolving the deployment config."""
    oc.save_org_config("acme", {"backend": "openrouter",
                                "models": {"coder": "google/gemma-4-31b-it:free"},
                                "keys": {"openrouter": "sk-or-acme"}})

    with using_org("acme"):
        assert prov.active_backend() == "openrouter"
        assert prov._active_model("openrouter", "coder") == "google/gemma-4-31b-it:free"
        assert prov._active_key("openrouter") == "sk-or-acme"
    with using_org("globex"):
        assert prov.active_backend() == "faux"
        assert prov._active_key("openrouter") == "", "org A's key served org B"
    assert prov.active_backend() == "faux"


def test_an_org_backend_disables_the_env_model_overrides(monkeypatch):
    """The CI-5a precedence trap, one layer up: AUGHOR_*_MODEL names were tuned for
    the ENV backend — applying them to an org's openrouter binding would 404 every
    call. The env layer stays skipped; with no built-in defaults left underneath it,
    the org simply has no model until it sets one (and gets NoModelConfigured), which
    is a better outcome than a call dispatched to the wrong vendor's id."""
    monkeypatch.setenv("AUGHOR_CODER_MODEL", "llama3:8b")
    oc.save_org_config("acme", {"backend": "openrouter"})

    with using_org("acme"):
        assert prov._active_model("openrouter", "coder") == ""

    oc.save_org_config("acme", {"backend": "openrouter", "models": {"coder": "org/choice:free"}})
    with using_org("acme"):
        assert prov._active_model("openrouter", "coder") == "org/choice:free"


def test_an_org_save_never_bumps_the_global_config_version():
    """THE no-cancel claim. The deployment path's load_config() bumps the global
    version, which clears every cached provider in the process — the reload that
    cancels a running exploration. The org path must never reach it."""
    before = prov._config_version

    oc.save_org_config("acme", {"backend": "openrouter", "models": {"coder": "acme/model:free"},
                                "keys": {"openrouter": "sk-1"}})
    oc.clear_org_config("acme")

    assert prov._config_version == before


def test_one_orgs_save_leaves_the_other_orgs_cached_provider_alone():
    """Cache-level tenant isolation: after org A saves, the default org's provider
    is the SAME OBJECT — nothing about A's change evicted it."""
    prov.set_config({"models": {"coder": "default/model"}})
    default_provider = prov.get_provider("coder")

    oc.save_org_config("acme", {"backend": "openrouter", "models": {"coder": "acme/model:free"},
                                "keys": {"openrouter": "sk-or-acme"}})
    with using_org("acme"):
        acme_provider = prov.get_provider("coder")

    assert prov.get_provider("coder") is default_provider
    assert acme_provider is not default_provider
    assert acme_provider.backend == "openrouter"


def test_an_org_save_moves_only_its_own_fingerprint():
    """The surgical invalidation: the fingerprint is the cache-key component, so a
    save rebuilds exactly one tenant's providers on their next call."""
    oc.save_org_config("acme", {"backend": "openrouter", "models": {"coder": "acme/model:free"},
                                "keys": {"openrouter": "sk-1"}})
    with using_org("acme"):
        first = prov.get_provider("coder")
    fp_before = oc.config_stamp("acme")

    oc.save_org_config("acme", {"keys": {"openrouter": "sk-2"}})

    assert oc.config_stamp("acme") != fp_before
    with using_org("acme"):
        rebuilt = prov.get_provider("coder")
    assert rebuilt is not first, "a key rotation must rebuild the org's client"
    assert oc.config_stamp("globex") == "", "another org's fingerprint moved"


def test_masked_keys_round_trip_unchanged_and_empty_clears():
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-real"}})
    stored = oc._row("acme")["keys"]["openrouter"]

    oc.save_org_config("acme", {"keys": {"openrouter": "sk-••••"}})
    assert oc._row("acme")["keys"]["openrouter"] == stored, "a mask overwrote the key"

    oc.save_org_config("acme", {"keys": {"openrouter": ""}})
    assert "openrouter" not in oc._row("acme")["keys"]


def test_an_unknown_backend_is_refused():
    with pytest.raises(ValueError):
        oc.save_org_config("acme", {"backend": "attacker-endpoint"})


def test_a_paid_model_needs_the_deliberate_flag():
    """Free-by-default applies to tenants exactly as to the operator — paying must
    be a deliberate act, never a typo, on either surface."""
    with pytest.raises(ValueError):
        oc.save_org_config("acme", {"backend": "openrouter",
                                    "models": {"coder": "anthropic/claude-sonnet-4-6"}})

    out = oc.save_org_config("acme", {"backend": "openrouter",
                                      "models": {"coder": "anthropic/claude-sonnet-4-6"},
                                      "allow_paid": True})
    assert out["models"]["coder"] == "anthropic/claude-sonnet-4-6"


def test_a_broken_store_fails_open_to_the_deployment_config(monkeypatch):
    """A tenant's inference degrades to the operator binding, never to an outage."""
    def _boom(org_id):
        raise RuntimeError("store down")

    monkeypatch.setattr(oc, "overlay_for", _boom)

    with using_org("acme"):
        assert prov.active_backend() == "faux"


# ── failover scoping (user decision 2026-08-13) ──────────────────────────────────────
#
# A BYOK org's failover chain may reach ONLY backends that org configured itself.
# `_active_key` resolves org → deployment → env, which is right for the primary binding
# and wrong for failover: it let a tenant's failed call land on the OPERATOR's key.

@pytest.fixture
def _deployment_keys(monkeypatch):
    """The operator holding keys for several backends — the spend surface a BYOK org
    must not be able to reach."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-operator-anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-operator-gemini")
    monkeypatch.setenv("GROQ_API_KEY", "sk-operator-groq")
    monkeypatch.delenv("AUGHOR_FALLBACK_DISABLED", raising=False)
    monkeypatch.delenv("AUGHOR_FALLBACK_BACKENDS", raising=False)


def _candidates(backend="openrouter", role="coder"):
    """The failover chain a provider bound to `backend` would try."""
    p = prov.LLMProvider.__new__(prov.LLMProvider)
    p.backend, p.role = backend, role
    return p._fallback_candidates()


def test_a_byok_org_never_fails_over_onto_the_operators_key(_deployment_keys):
    """THE leak. An org that brought only an OpenRouter key must not reach the
    operator's Anthropic/Gemini/Groq keys when its own call fails — the operator
    would silently absorb that tenant's spend and nothing would surface it."""
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-or-acme"}})

    with using_org("acme"):
        chain = _candidates(backend="openrouter")

    leaked = [b for b in chain if b in ("anthropic", "gemini", "groq", "together")]
    assert leaked == [], (
        f"BYOK org 'acme' brought only an openrouter key, but its failover chain "
        f"reaches {leaked} — those keys belong to the operator, who would absorb "
        f"this tenant's spend invisibly")


def test_a_byok_org_still_fails_over_across_its_own_backends(_deployment_keys):
    """Scoping must not mean 'no failover'. An org that brought two keys keeps the
    resilience it paid for — across exactly the providers it declared."""
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-or-acme",
                                         "anthropic": "sk-ant-acme"}})

    with using_org("acme"):
        chain = _candidates(backend="openrouter")

    assert "anthropic" in chain, "the org's own second key must remain reachable"
    assert "gemini" not in chain and "groq" not in chain


def test_an_org_without_byok_keeps_the_deployment_chain_unchanged(_deployment_keys):
    """The no-op half. An org with no BYOK row IS the deployment, so the deployment's
    chain is its own — this path must be byte-identical to before the fix."""
    with using_org("globex"):
        scoped = _candidates(backend="openrouter")

    assert "anthropic" in scoped and "gemini" in scoped and "groq" in scoped


def test_scoping_does_not_disable_the_fallback_kill_switch(_deployment_keys,
                                                           monkeypatch):
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-or-acme",
                                         "anthropic": "sk-ant-acme"}})
    monkeypatch.setenv("AUGHOR_FALLBACK_DISABLED", "1")

    with using_org("acme"):
        assert _candidates(backend="openrouter") == []


def test_scoping_leaves_keyless_local_backends_reachable(_deployment_keys, monkeypatch):
    """Local backends cost nothing to try, so excluding them would shorten a BYOK
    org's chain for no benefit."""
    monkeypatch.setenv("AUGHOR_FALLBACK_BACKENDS", "ollama,anthropic")
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-or-acme"}})

    with using_org("acme"):
        chain = _candidates(backend="openrouter")

    assert "ollama" in chain, "a keyless local backend is nobody's spend"
    assert "anthropic" not in chain


def test_an_unconfigured_org_stays_on_the_free_tier_binding():
    """The settled spend posture for tenants that brought no key (user decision
    2026-08-13): the operator's free-tier binding, no paid operator key promoted to
    them, and no per-org budget machinery. Pinned so a future 'be helpful' change
    to the default has to argue with a test."""
    with using_org("globex"):
        assert prov.active_backend() == "faux"
        assert oc.describe_org_config("globex")["configured"] is False
