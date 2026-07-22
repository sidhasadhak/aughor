"""The model catalogue — OpenRouter as a provider, and the picker's list of values.

Live fetches are disabled here (``AUGHOR_LLM_MODEL_FETCH=0``) so the suite never
depends on a remote host being up; the merge logic, persistence and API surface
are what these cover. The live path is exercised separately by its own test with
a stubbed transport.
"""
from __future__ import annotations

import json

import pytest

from aughor.llm import models as M
from aughor.llm import provider as P


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point the inference config at a tmp file — it holds encrypted API keys, so
    a test must never touch the real one."""
    cfg = tmp_path / "llm_config.json"
    cfg.write_text(json.dumps({"backend": "openrouter"}))
    original = P._CONFIG_PATH
    P._CONFIG_PATH = cfg          # restored below, NOT via monkeypatch: the reload
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "0")   # in teardown must happen AFTER
    P.load_config()               # the path is put back, or the module keeps the tmp
    M.clear_cache()               # config cached and later tests see this backend.
    yield
    P._CONFIG_PATH = original
    P.load_config()
    M.clear_cache()


# ── OpenRouter is a first-class provider ──────────────────────────────────────

def test_openrouter_is_registered():
    assert "openrouter" in P.BACKENDS
    assert "openrouter" in P.NEEDS_KEY               # it takes a key
    assert P._DEFAULT_BASE_URLS["openrouter"] == "https://openrouter.ai/api/v1"
    assert P._KEY_ENV["openrouter"] == "OPENROUTER_API_KEY"
    for role in ("coder", "narrator", "fast"):
        assert P._DEFAULT_MODELS["openrouter"][role]


def test_openrouter_defaults_are_free_tier():
    """A fresh key should work without first picking a paid model."""
    assert all(m.endswith(":free") for m in P._DEFAULT_MODELS["openrouter"].values())


def test_openrouter_is_not_treated_as_a_local_backend():
    assert "openrouter" not in P.LOCAL_BACKENDS      # its base URL is fixed


# ── the catalogue ─────────────────────────────────────────────────────────────

def test_known_models_are_the_offline_floor():
    out = M.list_models("openrouter")
    assert out["live"] is False
    assert out["models"], "the picker must never be empty"
    assert all(m["source"] == "known" for m in out["models"])
    assert out["defaults"]["coder"] == P._DEFAULT_MODELS["openrouter"]["coder"]


def test_every_backend_has_a_floor():
    for backend in P.BACKENDS:
        assert M.list_models(backend)["models"], f"{backend} has no suggestions"


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        M.list_models("not-a-backend")


# ── custom entries persist ────────────────────────────────────────────────────

def test_add_custom_model_persists_and_is_idempotent():
    M.add_custom_model("openrouter", "acme/private-v3")
    assert M.custom_models("openrouter") == ["acme/private-v3"]

    M.add_custom_model("openrouter", "acme/private-v3")          # again
    assert M.custom_models("openrouter") == ["acme/private-v3"]

    # survives a config reload — the point of persisting it
    P.load_config()
    assert M.custom_models("openrouter") == ["acme/private-v3"]

    out = M.list_models("openrouter")
    entry = next(m for m in out["models"] if m["id"] == "acme/private-v3")
    assert entry["source"] == "custom"
    assert out["custom"] == ["acme/private-v3"]


def test_custom_models_are_per_backend():
    M.add_custom_model("openrouter", "acme/one")
    M.add_custom_model("anthropic", "acme/two")
    assert M.custom_models("openrouter") == ["acme/one"]
    assert M.custom_models("anthropic") == ["acme/two"]
    assert "acme/two" not in {m["id"] for m in M.list_models("openrouter")["models"]}


def test_remove_custom_model():
    M.add_custom_model("openrouter", "acme/a")
    M.add_custom_model("openrouter", "acme/b")
    assert M.remove_custom_model("openrouter", "acme/a") == ["acme/b"]
    P.load_config()
    assert M.custom_models("openrouter") == ["acme/b"]


def test_built_in_entries_are_not_removable():
    """Hiding a model the backend actually serves would make the picker disagree
    with reality — removal is for entries the user added."""
    builtin = M.KNOWN_MODELS["openrouter"][0]
    with pytest.raises(ValueError, match="not a custom entry"):
        M.remove_custom_model("openrouter", builtin)


def test_add_rejects_blank_and_unknown_backend():
    with pytest.raises(ValueError):
        M.add_custom_model("openrouter", "   ")
    with pytest.raises(ValueError):
        M.add_custom_model("nope", "x")


def test_custom_entry_wins_when_it_also_appears_live(monkeypatch):
    """A live model the user also kept stays removable — the custom marking is
    what the UI keys its remove affordance on."""
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    monkeypatch.setattr(M, "fetch_live_models",
                        lambda backend, timeout=6.0: ([{"id": "vendor/m", "source": "live"}], ""))
    M.clear_cache()
    M.add_custom_model("openrouter", "vendor/m")

    entry = next(m for m in M.list_models("openrouter")["models"] if m["id"] == "vendor/m")
    assert entry["source"] == "custom"


def test_live_failure_surfaces_the_reason(monkeypatch):
    """A failed fetch must be stated, not hidden behind a fallback that then
    poses as the real catalogue."""
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    monkeypatch.setattr(M, "fetch_live_models",
                        lambda backend, timeout=6.0: ([], "ConnectError: refused"))
    M.clear_cache()

    out = M.list_models("openrouter")
    assert out["live"] is False
    assert "refused" in out["error"]
    assert out["models"], "still shows the floor"


def test_live_results_are_cached(monkeypatch):
    monkeypatch.setenv("AUGHOR_LLM_MODEL_FETCH", "1")
    calls = {"n": 0}

    def _fetch(backend, timeout=6.0):
        calls["n"] += 1
        return [{"id": "vendor/m", "source": "live"}], ""

    monkeypatch.setattr(M, "fetch_live_models", _fetch)
    M.clear_cache()
    M.list_models("openrouter")
    M.list_models("openrouter")
    assert calls["n"] == 1, "the catalogue moves in days; do not refetch per render"

    M.list_models("openrouter", refresh=True)
    assert calls["n"] == 2, "an explicit refresh must bypass the cache"


# ── the API surface ───────────────────────────────────────────────────────────

def test_model_routes(client):
    listed = client.get("/llm/models", params={"backend": "openrouter"})
    assert listed.status_code == 200
    assert listed.json()["backend"] == "openrouter"

    added = client.post("/llm/models", json={"backend": "openrouter", "model": "acme/x"})
    assert added.status_code == 200
    assert added.json()["custom"] == ["acme/x"]

    removed = client.delete("/llm/models", params={"backend": "openrouter", "model": "acme/x"})
    assert removed.status_code == 200
    assert removed.json()["custom"] == []


def test_removing_a_non_custom_model_is_a_400(client):
    r = client.delete("/llm/models",
                      params={"backend": "openrouter", "model": M.KNOWN_MODELS["openrouter"][0]})
    assert r.status_code == 400


def test_config_exposes_openrouter_to_the_ui(client):
    body = client.get("/llm/config").json()
    assert "openrouter" in body["backends"]
    assert "openrouter" in body["needs_key"]
    assert "openrouter" in body["default_models"]


# ── the curated OpenRouter list ───────────────────────────────────────────────

def test_openrouter_floor_is_all_free_tier():
    """We only run free models on this provider, so a paid id in the floor would
    quietly start costing money the moment someone picked it."""
    assert all(m.endswith(":free") for m in M.KNOWN_MODELS["openrouter"])


def test_openrouter_defaults_are_in_the_floor():
    """The first pass shipped two default ids that do not exist on OpenRouter
    (guessed rather than looked up). This keeps defaults and the list in step."""
    floor = set(M.KNOWN_MODELS["openrouter"])
    for role, model in P._DEFAULT_MODELS["openrouter"].items():
        assert model in floor, f"{role} default {model!r} is not in the curated list"


def test_music_models_are_not_offered_as_text_models():
    """Lyria is a music-generation model. OpenRouter lists it under Text and
    reports it free, but offering it where a SQL writer is chosen is a trap."""
    assert not [m for m in M.KNOWN_MODELS["openrouter"] if "lyria" in m]
