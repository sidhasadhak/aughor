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
    call. The org backend's own defaults serve instead."""
    monkeypatch.setenv("AUGHOR_CODER_MODEL", "llama3:8b")
    oc.save_org_config("acme", {"backend": "openrouter"})

    with using_org("acme"):
        model = prov._active_model("openrouter", "coder")
    assert model == prov._DEFAULT_MODELS["openrouter"]["coder"]
    assert model != "llama3:8b"


def test_an_org_save_never_bumps_the_global_config_version():
    """THE no-cancel claim. The deployment path's load_config() bumps the global
    version, which clears every cached provider in the process — the reload that
    cancels a running exploration. The org path must never reach it."""
    before = prov._config_version

    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-1"}})
    oc.clear_org_config("acme")

    assert prov._config_version == before


def test_one_orgs_save_leaves_the_other_orgs_cached_provider_alone():
    """Cache-level tenant isolation: after org A saves, the default org's provider
    is the SAME OBJECT — nothing about A's change evicted it."""
    default_provider = prov.get_provider("coder")

    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-or-acme"}})
    with using_org("acme"):
        acme_provider = prov.get_provider("coder")

    assert prov.get_provider("coder") is default_provider
    assert acme_provider is not default_provider
    assert acme_provider.backend == "openrouter"


def test_an_org_save_moves_only_its_own_fingerprint():
    """The surgical invalidation: the fingerprint is the cache-key component, so a
    save rebuilds exactly one tenant's providers on their next call."""
    oc.save_org_config("acme", {"backend": "openrouter",
                                "keys": {"openrouter": "sk-1"}})
    with using_org("acme"):
        first = prov.get_provider("coder")
    fp_before = oc.fingerprint("acme")

    oc.save_org_config("acme", {"keys": {"openrouter": "sk-2"}})

    assert oc.fingerprint("acme") != fp_before
    with using_org("acme"):
        rebuilt = prov.get_provider("coder")
    assert rebuilt is not first, "a key rotation must rebuild the org's client"
    assert oc.fingerprint("globex") == "", "another org's fingerprint moved"


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
