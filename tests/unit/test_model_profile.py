"""A1 ModelProfile — model-sized capability budgets + transport-derived parallelism.

The contract under test, in order of what it would cost to get wrong:

1. An UNKNOWN model gets the old constants EXACTLY (the conservative floor every
   receipt was measured against) — pinned as absolute numbers, not derived from the
   module's own tables, so a table edit cannot silently move the floor and its test
   together (the Wave-3 lesson: a budget computed from the thing under test
   measures nothing).
2. Parallel waves require a DECLARED budget: unknown ⇒ serial. This is what keeps
   the out-of-box topology byte-identical to the four default-off flags the
   decision replaced (flag endgame Wave 6).
3. Env vars keep deciding over tier defaults, and are read at CALL time — a
   monkeypatch.setenv must be visible (the module-import-freeze trap).
"""
import pytest

from aughor.llm import profile as pr


# ── 1. The floor is the old constants, as absolute numbers ───────────────────

def test_unknown_model_gets_the_exact_legacy_constants(monkeypatch):
    monkeypatch.delenv("AUGHOR_LLM_RPM", raising=False)
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AUGHOR_LLM_STRUCTURED_ATTEMPTS", raising=False)
    monkeypatch.delenv("AUGHOR_REASONING_EFFORT", raising=False)
    p = pr.profile_for("coder", model="somebodys/fine-tune-7b")
    assert p.schema_char_limit == 20_000       # investigate._SCHEMA_CHAR_LIMIT
    assert p.evidence_budget == 6_000          # investigate._EVIDENCE_BUDGET
    assert p.interpret_max_rows == 12
    assert p.max_output_tokens == 4_096        # provider._MAX_OUTPUT_TOKENS
    assert p.structured_attempts == 1
    assert p.reasoning_effort == "low"
    assert p.parallel_waves is False


def test_a_wide_context_window_earns_the_larger_budgets(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AUGHOR_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("AUGHOR_MODEL_CONTEXT_TOKENS", "1000000")
    p = pr.profile_for("coder", model="any/model")
    assert p.schema_char_limit == 60_000
    assert p.evidence_budget == 18_000
    assert p.interpret_max_rows == 36
    assert p.max_output_tokens == 8_192
    assert p.reasoning_effort == "medium"
    # structured attempts are retry ECONOMICS, not capability — 1 on every tier
    assert p.structured_attempts == 1


def test_the_tier_is_derived_from_the_declared_context_not_the_name(monkeypatch):
    """The tier used to come from a hand-maintained table of model-id prefixes, which
    went stale in the direction that costs you: this deployment's own coder model was
    listed under its OpenRouter spelling but not its Ollama-cloud one, so a capable model
    silently ran on 20k of schema instead of 60k. The provider's declared context window
    is the fact the family table was a proxy for, so it decides directly now — and it is
    right about a model nobody here has ever heard of."""
    monkeypatch.delenv("AUGHOR_MODEL_CONTEXT_TOKENS", raising=False)
    monkeypatch.setattr(pr, "declared_context",
                        lambda m: {"wide/one": 200_000, "narrow/one": 8_000}.get(m))
    assert pr.tier_for("wide/one")["schema_char_limit"] == 60_000
    assert pr.tier_for("narrow/one")["schema_char_limit"] == 20_000
    # Unknown ⇒ BASELINE. The conservative floor, and the same answer the old table
    # gave for anything it had not heard of.
    assert pr.tier_for("never/seen")["schema_char_limit"] == 20_000


def test_an_operator_can_declare_the_context_window(monkeypatch):
    """The escape hatch for a backend that publishes no context length — and the only
    thing that stands in for the deleted list."""
    monkeypatch.setenv("AUGHOR_MODEL_CONTEXT_TOKENS", "128000")
    assert pr.tier_for("anything/at-all")["schema_char_limit"] == 60_000
    monkeypatch.setenv("AUGHOR_MODEL_CONTEXT_TOKENS", "32000")
    assert pr.tier_for("anything/at-all")["schema_char_limit"] == 20_000


# ── 2. Parallelism needs a DECLARED budget ───────────────────────────────────

def test_undeclared_budget_is_not_an_unlimited_one(monkeypatch):
    """No env, no :free suffix ⇒ the budget is UNKNOWN ⇒ serial.

    This is the property that keeps CI (no llm_config.json → ollama default
    binding) and a dev machine (llm_config binds an OpenRouter :free model) on the
    SAME topology — both serial — instead of the suite compiling different graphs
    on each side."""
    monkeypatch.delenv("AUGHOR_LLM_RPM", raising=False)
    assert pr._rpm_budget("ollama-something") is None
    assert pr.profile_for("coder", model="ollama-something").parallel_waves is False


def test_free_suffix_is_a_20_rpm_declaration(monkeypatch):
    monkeypatch.delenv("AUGHOR_LLM_RPM", raising=False)
    p = pr.profile_for("coder", model="vendor/model:free")
    assert p.rpm_budget == 20
    assert p.parallel_waves is False           # 20 < the wave floor


@pytest.mark.parametrize("rpm,expected", [
    ("0", True),      # declared-unbounded — the same value that disables _pace
    ("29", False),    # below the wave floor
    ("30", True),
    ("120", True),
])
def test_explicit_rpm_wins_in_both_directions(monkeypatch, rpm, expected):
    monkeypatch.setenv("AUGHOR_LLM_RPM", rpm)
    # even on a :free binding — the operator's declaration outranks the suffix
    p = pr.profile_for("coder", model="x:free")
    assert p.parallel_waves is expected, f"rpm={rpm}"


def test_single_slot_concurrency_forces_serial(monkeypatch):
    monkeypatch.setenv("AUGHOR_LLM_RPM", "0")
    monkeypatch.setenv("AUGHOR_LLM_MAX_CONCURRENCY", "1")
    assert pr.profile_for("coder", model="anything").parallel_waves is False


def test_parallel_waves_enabled_is_fail_safe(monkeypatch):
    """Any resolution error means serial — the byte-identical sequential path."""
    monkeypatch.setattr(pr, "profile_for", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert pr.parallel_waves_enabled() is False


# ── 3. Env overrides are call-time and outrank the tier ──────────────────────

def test_env_overrides_are_read_at_call_time_not_import(monkeypatch):
    monkeypatch.setattr(pr, "declared_context", lambda m: 200_000)   # a capable binding
    p1 = pr.profile_for("coder", model="wide/model:free")
    monkeypatch.setenv("AUGHOR_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("AUGHOR_REASONING_EFFORT", "high")
    p2 = pr.profile_for("coder", model="wide/model:free")
    assert (p1.max_output_tokens, p2.max_output_tokens) == (8_192, 2_048)
    assert p2.reasoning_effort == "high"


# ── 4. The consumers actually consult the profile ────────────────────────────

def test_investigate_budgets_follow_the_profile(monkeypatch):
    """The agent's helpers must reach the profile, not a frozen constant."""
    from aughor.agent import investigate as inv
    cap = pr.ModelProfile(backend="t", model="m", schema_char_limit=42_000,
                          evidence_budget=17_000, interpret_max_rows=33,
                          max_output_tokens=8192, structured_attempts=1,
                          reasoning_effort="low", linker_top_tables=4,
                          linker_top_cols=8, context_table_cap=10,
                          parallel_waves=False, rpm_budget=None,
                          tool_loop_steps=4)
    monkeypatch.setattr("aughor.llm.profile.profile_for", lambda *a, **k: cap)
    assert inv._schema_limit() == 42_000
    assert inv._evidence_budget() == 17_000
    assert inv._interpret_rows() == 33


def test_investigate_budgets_fail_safe_to_the_baseline(monkeypatch):
    from aughor.agent import investigate as inv
    monkeypatch.setattr("aughor.llm.profile.profile_for",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no binding")))
    assert inv._schema_limit() == 20_000
    assert inv._evidence_budget() == 6_000
    assert inv._interpret_rows() == 12


def test_topology_helpers_follow_one_transport_decision(monkeypatch):
    """The former four flags now answer from ONE derivation — all together."""
    from aughor.agent import graph as g
    from aughor.agent import explore as ex
    from aughor.agent import investigate as inv
    monkeypatch.setenv("AUGHOR_LLM_RPM", "120")
    monkeypatch.setenv("AUGHOR_LLM_MAX_CONCURRENCY", "4")
    on = [g._explore_parallel_enabled(), g._ada_parallel_lenses_enabled(),
          g._ada_parallel_phases_enabled(), ex._parallel_subq_on(),
          inv._parallel_why_lenses_enabled()]
    assert on == [True] * 5
    monkeypatch.setenv("AUGHOR_LLM_RPM", "20")
    off = [g._explore_parallel_enabled(), g._ada_parallel_lenses_enabled(),
           g._ada_parallel_phases_enabled(), ex._parallel_subq_on(),
           inv._parallel_why_lenses_enabled()]
    assert off == [False] * 5


def test_topology_flags_dict_keeps_its_shape():
    from aughor.agent.graph import topology_flags
    tf = topology_flags()
    assert set(tf) == {"ada_parallel_lenses", "ada_parallel_phases", "explore_parallel"}


# ── 5. The registry really let go ────────────────────────────────────────────

def test_the_four_parallelism_flags_are_gone_and_stay_gone():
    from aughor.kernel import flags as fl
    for name in ("explore.parallel_subq", "deep_analysis.parallel_lenses",
                 "deep_analysis.parallel_phases", "deep_analysis.parallel_why_lenses"):
        assert name not in fl.FLAG_ENV, name
        assert name not in fl.FLAG_META, name
        assert name not in fl.RENAMED, name          # dead aliases go with their targets
    assert fl.COST_LATENCY_PROFILE == frozenset()    # declared and EMPTY, like AUTO_ELIGIBLE
    assert "AUGHOR_ADA_PARALLEL_LENSES" not in fl.RETIRED_ENV
