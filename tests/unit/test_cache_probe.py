"""Prefix-cache probe — verdict logic + the measured-override loop (§5b.3).

The probe itself makes real network calls (covered by a live run, not here); these tests
pin the *pure* verdict thresholds and the build→wire→leverage seam: a persisted verdict
overrides the declared cache_mode everywhere the capability is read (`capability_for`,
`vend_llm`, `current_config`). Hermetic — no network, isolated config file.
"""
from __future__ import annotations

import pytest

from aughor.llm import provider as P
from aughor.llm.cache_probe import verdict_for
from aughor.platform import capability_for, vend_llm


# ── the pure verdict ──────────────────────────────────────────────────────────

class TestVerdict:
    def test_warm_much_faster_means_reuse(self):
        label, ratio = verdict_for(warm_ms=[300, 320, 310], cold_ms=[1000, 1100, 980])
        assert label == "reuse_active" and ratio < 0.6

    def test_warm_equal_to_cold_means_no_reuse(self):
        label, ratio = verdict_for(warm_ms=[980, 1010], cold_ms=[1000, 1020, 990])
        assert label == "no_reuse" and ratio >= 0.85

    def test_middle_band_is_inconclusive(self):
        label, ratio = verdict_for(warm_ms=[700], cold_ms=[1000])
        assert label == "inconclusive" and 0.6 < ratio < 0.85

    def test_empty_samples_are_inconclusive(self):
        assert verdict_for([], [1000])[0] == "inconclusive"
        assert verdict_for([300], [])[0] == "inconclusive"


# ── the measured override loop (build → wire → leverage) ──────────────────────

@pytest.fixture
def clean_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_CONFIG_PATH", tmp_path / "llm_config.json")
    monkeypatch.setattr(P, "_runtime", None)
    for v in ("AUGHOR_BACKEND", "AUGHOR_MODEL", "AUGHOR_CODER_MODEL"):
        monkeypatch.delenv(v, raising=False)
    P._providers.clear()
    P._pinned_providers.clear()
    P._cache_version = -1
    P.load_config()
    yield


class TestMeasuredOverride:
    def test_override_replaces_declared_cache_mode(self):
        # declared default for a :cloud model is 'auto_prefix_unverified'…
        base = capability_for("ollama", "qwen3-coder-next:cloud", "coder", "http://localhost:11434/v1")
        assert base.cache_mode == "auto_prefix_unverified"
        # …a measurement overrides it (evidence > guess).
        measured = capability_for("ollama", "qwen3-coder-next:cloud", "coder",
                                  "http://localhost:11434/v1", cache_mode_override="auto_prefix")
        assert measured.cache_mode == "auto_prefix"

    def test_persisted_verdict_round_trips(self, clean_cfg):
        assert P.measured_cache_mode("ollama", "m1") is None
        P.set_measured_cache_mode("ollama", "m1", "none")
        assert P.measured_cache_mode("ollama", "m1") == "none"
        P.set_measured_cache_mode("ollama", "m1", None)          # clear
        assert P.measured_cache_mode("ollama", "m1") is None

    def test_vend_llm_adopts_the_measured_verdict(self, clean_cfg):
        cap0 = vend_llm("coder")                                  # default :cloud binding
        assert cap0.cache_mode == "auto_prefix_unverified"
        P.set_measured_cache_mode(cap0.backend, cap0.model, "none")  # probe found no reuse
        assert vend_llm("coder").cache_mode == "none"            # leveraged on the live seam

    def test_config_view_reflects_the_measurement(self, clean_cfg):
        c0 = P.current_config()
        assert c0["capabilities"]["coder"]["cache_mode"] == "auto_prefix_unverified"
        m = c0["models"]["coder"]
        P.set_measured_cache_mode("ollama", m, "auto_prefix")
        assert P.current_config()["capabilities"]["coder"]["cache_mode"] == "auto_prefix"
