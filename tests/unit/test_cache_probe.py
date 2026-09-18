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
from aughor.control_plane import capability_for, vend_llm


# ── the pure verdict ──────────────────────────────────────────────────────────

class TestVerdict:
    def test_warm_much_faster_means_reuse(self):
        label, ratio = verdict_for(warm_ms=[300, 320, 310], cold_ms=[1000, 1100, 980])
        assert label == "reuse_active" and ratio < 0.6

    def test_warm_equal_to_cold_means_no_reuse(self):
        label, ratio = verdict_for(warm_ms=[980, 1010], cold_ms=[1000, 1020, 990])
        assert label == "no_reuse" and ratio >= 0.85

    def test_middle_band_is_inconclusive(self):
        # Multi-sample and tight on purpose: single samples are now refused for having no
        # readable noise floor, which would make this pass without ever reaching the band
        # it exists to test. (`test_a_single_sample_cannot_be_read` covers that path.)
        label, ratio = verdict_for(warm_ms=[700, 710, 705], cold_ms=[1000, 1010, 990])
        assert label == "inconclusive" and 0.6 < ratio < 0.85

    def test_empty_samples_are_inconclusive(self):
        assert verdict_for([], [1000])[0] == "inconclusive"
        assert verdict_for([300], [])[0] == "inconclusive"


# ── refusing to answer from noise (2026-09-18) ────────────────────────────────

#: The three probes that exposed the defect: one live binding (gemini-3.1-flash-lite),
#: rounds=5, minutes apart. `shared[0]` is the cold anchor and is excluded from warm, as
#: `probe_prefix_cache` does. Before the guards these returned no_reuse / no_reuse /
#: reuse_active — two confident opposite answers about the same binding within minutes.
LIVE_RUNS = {
    "A": ([2482, 9512, 11368, 741], [18594, 7343, 2958, 2640, 876]),
    "B": ([2788, 11179, 2598, 3097], [1023, 741, 686, 2017, 2996]),
    "C": ([836, 1485, 1043, 768], [8937, 909, 6846, 46114, 988]),
}


class TestRefusesNoise:
    @pytest.mark.parametrize("run", sorted(LIVE_RUNS))
    def test_the_three_live_runs_are_all_inconclusive(self, run):
        warm, cold = LIVE_RUNS[run]
        label, _ = verdict_for(warm_ms=warm, cold_ms=cold)
        assert label == "inconclusive", f"live run {run} still yields a verdict"

    def test_the_live_runs_no_longer_disagree(self):
        """The defect was not any single wrong answer — it was two CONFIDENT OPPOSITE
        answers about one binding minutes apart. Whatever the rules become, they must not
        reproduce that."""
        labels = {verdict_for(w, c)[0] for w, c in LIVE_RUNS.values()}
        assert labels == {"inconclusive"}, f"runs disagree again: {labels}"

    def test_warm_slower_than_cold_is_refused_not_called_no_reuse(self):
        """A cache can only make a warm call faster or leave it alone. Warm being slower
        says the run measured something that is not caching — the old rule read it as the
        STRONGEST no_reuse signal, because it only asked `ratio >= 0.85`."""
        label, ratio = verdict_for(warm_ms=[2000, 2100, 2050], cold_ms=[1000, 1010, 990])
        assert ratio > 1.0
        assert label == "inconclusive"

    def test_a_noisy_series_is_refused_even_when_the_ratio_looks_clean(self):
        """Medians can land on a tidy ratio while the samples under them are garbage. The
        ratio here is ~0.5 — squarely `reuse_active` — but each series spans 30x."""
        label, ratio = verdict_for(warm_ms=[100, 500, 3000], cold_ms=[200, 1000, 6000])
        assert ratio <= 0.60, "this fixture must sit inside the reuse_active band"
        assert label == "inconclusive"

    def test_a_single_sample_cannot_be_read(self):
        """One call per series has no spread, so its noise floor is unknown. The ratio is
        still returned — it is the diagnostic, not the verdict."""
        label, ratio = verdict_for(warm_ms=[300], cold_ms=[1000])
        assert label == "inconclusive" and ratio == 0.3

    def test_clean_samples_still_get_a_verdict(self):
        """The guards must not swallow the signal they were added to protect: tight series,
        clear separation, verdict stands."""
        assert verdict_for([300, 310, 305], [1000, 1010, 990])[0] == "reuse_active"
        assert verdict_for([980, 1010, 995], [1000, 1020, 990])[0] == "no_reuse"


class TestDeclineReason:
    def test_every_refusal_says_why_and_the_reason_matches_the_rule(self):
        """The report's sentence and the verdict come from ONE ordered rule list, so they
        cannot drift apart. Checked by asserting the reason names the rule that fired."""
        from aughor.llm.cache_probe import _decline_reason, spread_of

        warm, cold = LIVE_RUNS["C"]
        reason = _decline_reason(warm, cold, ratio=0.137)
        assert reason and "noise floor" in reason
        assert f"{max(spread_of(warm), spread_of(cold)):.1f}x" in reason

        slower = _decline_reason([2000, 2100], [1000, 1010], ratio=2.03)
        assert slower and "SLOWER" in slower

        assert _decline_reason([300, 310], [1000, 1010], ratio=0.3) is None

    def test_spread_of_reads_the_noise_floor(self):
        from aughor.llm.cache_probe import spread_of

        assert spread_of([100, 200, 400]) == 4.0
        assert spread_of([500]) == 1.0          # nothing to compare
        assert spread_of([]) == 1.0
        assert spread_of([0, 0, 900, 300]) == 3.0   # zeros are dropped, not counted as min


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
    # An explicit binding, because nothing ships a default one any more (2026-08-15).
    # These tests are about a MEASUREMENT overriding a declared cache mode, so they need
    # a model whose declared mode is known — a `:cloud` id declares
    # `auto_prefix_unverified`. Previously this rode on the built-in ollama default
    # happening to be `:cloud`, which made the fixture depend on a shipped model id.
    P.write_config({"backend": "ollama",
                    "models": {"coder": "some-model:cloud", "narrator": "some-model:cloud",
                               "fast": "some-model:cloud"}})
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
