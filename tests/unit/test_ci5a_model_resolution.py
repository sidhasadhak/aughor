"""CI-5a — the per-role model env vars are the durable prod configuration, and a slow
narrator no longer ships a fallback report without a fight.

The premise check found the roadmap's main CI-5a deliverable ALREADY SHIPPED:
`AUGHOR_{CODER,NARRATOR,FAST_NARRATOR}_MODEL` exist in `_env_model_for_role`, and
`data/llm_config.json` is untracked — a serverless cold start has an empty runtime
config, so the env vars already govern prod. What was missing: the contract pinned as
tests (it lived only in the module docstring and one memory entry), the documented
precedence trap, and the fast-role rescue between a slow narrator and the
deterministic fallback (CI-0: 28% of deep reports shipped as fallbacks).
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from aughor.llm import provider as P

_ENV_VARS = (
    "AUGHOR_BACKEND", "AUGHOR_MODEL", "AUGHOR_CODER_MODEL", "AUGHOR_NARRATOR_MODEL",
    "AUGHOR_FAST_NARRATOR_MODEL",
)


@pytest.fixture
def clean_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_CONFIG_PATH", tmp_path / "llm_config.json")
    monkeypatch.setattr(P, "_runtime", None)
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    P._providers.clear()
    P._cache_version = -1
    P.load_config()
    yield tmp_path / "llm_config.json"


def _write_cfg(path, payload):
    path.write_text(json.dumps(payload))
    P.load_config()


# ── the resolution contract, pinned ──────────────────────────────────────────────

def test_serverless_posture_env_models_govern(clean_cfg, monkeypatch):
    """Empty runtime config (every cold start on Vercel) + env vars ⇒ env wins.
    This is the configuration prod actually runs on — the durable one."""
    monkeypatch.setenv("AUGHOR_NARRATOR_MODEL", "env-narrator-model")
    monkeypatch.setenv("AUGHOR_CODER_MODEL", "env-coder-model")
    assert P._active_model("openrouter", "narrator") == "env-narrator-model"
    assert P._active_model("openrouter", "coder") == "env-coder-model"


def test_fast_falls_back_to_narrator_env(clean_cfg, monkeypatch):
    monkeypatch.setenv("AUGHOR_NARRATOR_MODEL", "env-narrator-model")
    assert P._active_model("openrouter", "fast") == "env-narrator-model"
    monkeypatch.setenv("AUGHOR_FAST_NARRATOR_MODEL", "env-fast-model")
    assert P._active_model("openrouter", "fast") == "env-fast-model"


def test_config_backend_disables_env_models(clean_cfg, monkeypatch):
    """THE TRAP, pinned deliberately: a UI-chosen backend makes AUGHOR_*_MODEL a
    silent no-op even with no models chosen — env model names are tuned for the env
    backend, and applying one to a different binding would 404 every call. If this
    behaviour is ever changed, this test is the notice that the operator note in the
    module docstring must change with it."""
    monkeypatch.setenv("AUGHOR_NARRATOR_MODEL", "env-narrator-model")
    _write_cfg(clean_cfg, {"backend": "openrouter"})
    resolved = P._active_model("openrouter", "narrator")
    assert resolved != "env-narrator-model"
    # It used to resolve to the chosen backend's built-in default; with none shipped it
    # resolves to nothing, and the caller raises NoModelConfigured. The trap this test
    # exists for is unchanged — the env layer is still skipped.
    assert resolved == ""


def test_config_models_outrank_everything(clean_cfg, monkeypatch):
    monkeypatch.setenv("AUGHOR_NARRATOR_MODEL", "env-narrator-model")
    _write_cfg(clean_cfg, {"backend": "openrouter",
                           "models": {"narrator": "cfg-narrator-model"}})
    assert P._active_model("openrouter", "narrator") == "cfg-narrator-model"


# ── the fast-role rescue ─────────────────────────────────────────────────────────

class _Synth(SimpleNamespace):
    pass


def test_rescue_serves_a_report_when_the_narrator_died(monkeypatch):
    from aughor.agent import investigate as inv

    calls = []

    def _fake_provider(role):
        calls.append(role)
        return SimpleNamespace(complete=lambda **kw: _Synth(headline="rescued"))

    monkeypatch.setattr(inv, "_provider", _fake_provider)
    out = inv._fast_synthesis_rescue("sys", "user", _Synth)
    assert out is not None and out.headline == "rescued"
    assert calls == ["fast"], "the rescue runs on the CHEAP binding, not the narrator again"


def test_rescue_failure_lands_on_the_fallback(monkeypatch):
    from aughor.agent import investigate as inv

    def _fake_provider(role):
        return SimpleNamespace(complete=lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))

    monkeypatch.setattr(inv, "_provider", _fake_provider)
    assert inv._fast_synthesis_rescue("sys", "user", _Synth) is None, \
        "a failed rescue lands exactly where the run was already headed"


def test_rescue_respects_its_own_timeout(monkeypatch):
    from aughor.agent import investigate as inv

    def _fake_provider(role):
        def _slow(**kw):
            time.sleep(2)
            return _Synth(headline="too late")
        return SimpleNamespace(complete=_slow)

    monkeypatch.setattr(inv, "_provider", _fake_provider)
    monkeypatch.setenv("AUGHOR_SYNTH_FAST_TIMEOUT_S", "0.2")
    t0 = time.monotonic()
    assert inv._fast_synthesis_rescue("sys", "user", _Synth) is None
    assert time.monotonic() - t0 < 1.5, "the rescue's timeout binds — the user already waited once"
