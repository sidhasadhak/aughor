"""Wave R2 — the vouched model matrix, and the two bug classes it closes structurally.

The load-bearing test here is :func:`test_every_shipped_default_resolves_through_the_matrix`.
Two ids that did not exist once shipped as OpenRouter defaults and the app kept
answering, because the failover chain covered for them. No amount of testing the code
catches that — it is a fact about the outside world the code assumed. This makes the
assumption a declared, dated entry, so a default that nobody checked fails CI instead of
a user's run.
"""
from __future__ import annotations

import pytest

from aughor.llm import matrix as M
from aughor.llm.models import KNOWN_MODELS
from aughor.llm.provider import _DEFAULT_MODELS


def test_every_shipped_default_resolves_through_the_matrix():
    """Every id we ship as a role default must be IN the matrix. Not necessarily
    verified — a backend with no key on the build machine cannot be — but recorded, with
    an explicit verification date or an explicit empty one. The forbidden state is
    'shipped and unaccounted for', which is what a guess looks like."""
    missing = [(b, role, m)
               for b, roles in _DEFAULT_MODELS.items()
               for role, m in roles.items()
               if not M.is_known(b, m)]
    assert not missing, (
        "shipped default(s) absent from the vouched matrix — add an entry to "
        f"aughor/llm/matrix.py (verified_on='' if you could not check it): {missing}")


def test_every_picker_suggestion_resolves_through_the_matrix():
    """Same bar for the curated offline fallback list — it is what a user picks from
    before any key is set, so a dead id there is a first-run failure."""
    missing = [(b, m) for b, models in KNOWN_MODELS.items()
               for m in models if not M.is_known(b, m)]
    assert not missing, f"picker suggestion(s) absent from the vouched matrix: {missing}"


def test_the_matrix_has_no_duplicate_entries():
    keys = [(v.backend, v.model) for v in M.VOUCHED]
    assert len(keys) == len(set(keys))


def test_a_verification_date_is_a_date_or_honestly_empty():
    """`verified_on` is the whole point: it must be a real ISO date or an explicit
    empty string. A matrix that laundered a guess into a plausible-looking date would be
    worse than no matrix."""
    for v in M.VOUCHED:
        if v.verified_on:
            assert len(v.verified_on) == 10 and v.verified_on.count("-") == 2, v


def test_the_openrouter_bindings_are_actually_verified():
    """OpenRouter is the backend the app is bound to and the one whose ids were guessed
    wrong. Its catalogue is public, so there is no excuse for an unverified entry."""
    unverified = [v.model for v in M.vouched_for("openrouter") if not v.vouched]
    assert not unverified, f"OpenRouter ids must be checked against the live /models: {unverified}"


# ── the tier-eligibility half: "pin clobbered the fast tier" ──────────────────

def test_the_550b_can_never_serve_the_fast_tier():
    """The concrete cost bug: a per-agent pin promoted every throwaway interpret call —
    up to ~7 per investigation plus the digest — onto a 550B reasoning model."""
    assert not M.fast_eligible("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free")


def test_an_unlisted_model_is_never_fast_eligible():
    """What makes wiring the matrix into `_pinned_model` safe: unknown resolves to the
    pre-R2 blanket rule, so nothing changes for a model nobody declared cheap."""
    assert not M.fast_eligible("openrouter", "some/model-nobody-declared:free")
    assert not M.fast_eligible("nosuchbackend", "whatever")


def test_a_declared_cheap_model_is_allowed_through_a_pin(monkeypatch):
    """The widening half — pinning a genuinely cheap model should not be blocked from
    the cheap tier. Before R2 the rule was blanket and this was refused for no reason."""
    from aughor.llm import provider as P

    monkeypatch.setattr(P, "_active_backend", lambda: "openrouter")
    token = P.set_run_model("nvidia/nemotron-3-nano-30b-a3b:free")
    try:
        assert P._pinned_model("fast", None) == "nvidia/nemotron-3-nano-30b-a3b:free"
        assert P._pinned_model("coder", None) == "nvidia/nemotron-3-nano-30b-a3b:free"
    finally:
        P.reset_run_model(token)


def test_the_expensive_pin_still_never_reaches_fast(monkeypatch):
    from aughor.llm import provider as P

    monkeypatch.setattr(P, "_active_backend", lambda: "openrouter")
    token = P.set_run_model("nvidia/nemotron-3-ultra-550b-a55b:free")
    try:
        assert P._pinned_model("fast", None) == ""            # the cheap tier is protected
        assert P._pinned_model("coder", None) == "nvidia/nemotron-3-ultra-550b-a55b:free"
    finally:
        P.reset_run_model(token)


def test_an_explicit_model_argument_still_wins_everywhere(monkeypatch):
    """A direct pin (bakeoff arm, health probe, a test) is a deliberate act and the
    matrix must not veto it."""
    from aughor.llm import provider as P

    monkeypatch.setattr(P, "_active_backend", lambda: "openrouter")
    assert P._pinned_model("fast", "nvidia/nemotron-3-ultra-550b-a55b:free") == \
        "nvidia/nemotron-3-ultra-550b-a55b:free"


# ── id normalization: the false-alarm the drift check would otherwise produce ──

def test_gemini_catalogue_ids_are_normalized():
    """Gemini's /models returns `models/gemini-…` while /chat/completions takes the bare
    id. Comparing raw marks every correct Gemini binding as gone — measured on the live
    catalogue: all three of ours 'missing' until the prefix is stripped."""
    assert M.normalize_id("gemini", "models/gemini-3.1-flash-lite") == "gemini-3.1-flash-lite"
    assert M.lookup("gemini", "models/gemini-pro-latest") is not None
    # Every other backend is left alone — an OpenRouter id contains a slash by design.
    assert M.normalize_id("openrouter", "google/gemma-4-31b-it:free") == "google/gemma-4-31b-it:free"


def test_gemini_drift_is_clean_against_a_prefixed_catalogue():
    live = ["models/gemini-3.1-flash-lite", "models/gemini-flash-latest",
            "models/gemini-pro-latest", "models/aqa"]
    report = M.drift("gemini", live)
    assert report["gone"] == []
    assert "aqa" in report["unlisted"]


# ── drift ─────────────────────────────────────────────────────────────────────

def test_drift_reports_a_vouched_id_that_disappeared():
    report = M.drift("openrouter", ["google/gemma-4-31b-it:free"])
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in report["gone"]


def test_an_unverified_entry_can_never_be_reported_gone():
    """It was never claimed present. Reporting it would invent a regression out of an
    absence the matrix already documents — and a drift warning that cries wolf is a
    drift warning nobody reads."""
    report = M.drift("ollama", ["qwen3-coder-next:cloud", "kimi-k2.6:cloud", "qwen3.5:397b-cloud"])
    assert report["gone"] == []                      # glm-5.2/gpt-oss are verified_on=""


def test_check_drift_never_raises_and_says_when_it_could_not_look(monkeypatch):
    """A startup check that can fail a startup is worse than the drift it looks for —
    and 'we could not look' must never render as 'everything is gone'."""
    import aughor.llm.models as models_mod

    monkeypatch.setattr(models_mod, "fetch_live_models",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down")))
    out = M.check_drift("openrouter")
    assert out["gone"] == [] and out.get("skipped")

    monkeypatch.setattr(models_mod, "fetch_live_models", lambda *a, **k: ([], ""))
    assert M.check_drift("openrouter").get("skipped") == "empty catalogue"


# ── the write path a guessed id enters through ────────────────────────────────

def test_pinning_an_unvouched_model_warns_but_is_never_blocked(caplog):
    """Warn, never block. A closed list would break the day a provider ships a new id —
    'you cannot use the model you are paying for' is the worse failure."""
    from aughor.kernel import agents

    with caplog.at_level("WARNING"):
        agents._warn_if_unvouched("analyst", "vendor/brand-new-model:free")
    assert any("vouched model matrix" in r.getMessage() for r in caplog.records)


def test_pinning_a_vouched_model_is_silent(caplog, monkeypatch):
    from aughor.kernel import agents
    from aughor.llm import provider as P

    monkeypatch.setattr(P, "_active_backend", lambda: "openrouter")
    with caplog.at_level("WARNING"):
        agents._warn_if_unvouched("analyst", "google/gemma-4-31b-it:free")
    assert not [r for r in caplog.records if "matrix" in r.getMessage()]


@pytest.mark.parametrize("model", ["", None])
def test_clearing_a_pin_warns_about_nothing(model, caplog):
    from aughor.kernel import agents

    with caplog.at_level("WARNING"):
        agents._warn_if_unvouched("analyst", model or "")
    assert not caplog.records
