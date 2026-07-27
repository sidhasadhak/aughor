"""Wave L4 — the deterministic equivalence suite that graduates the `automations.*` flags.

The point of these tests is NOT to re-assert what the scenarios assert (the scenarios run real
code against a real warehouse and compare it themselves). It is to prove the harness can say NO:

  * the evaluator fails on a mismatch, and fails — rather than skips — when there is nothing to
    compare, because the runner scores a skipped evaluator as a pass;
  * the target refuses an unknown scenario instead of quietly contributing a pass;
  * a scenario whose two halves genuinely disagree is reported as non-equivalent.

A measurement instrument that cannot fail is not measuring.
"""
from __future__ import annotations

from aughor.evals.equivalence import (
    SCENARIOS,
    Comparison,
    DeterministicEquivalenceEvaluator,
    ensure_suite,
    equivalence_target,
)
from aughor.evals.evaluator import EvalCase, EvalObservation


def _obs(**meta) -> EvalObservation:
    return EvalObservation(meta=meta)


# ── the evaluator can fail ───────────────────────────────────────────────────────

def test_equivalence_passes_when_observed_matches_the_oracle():
    ev = DeterministicEquivalenceEvaluator()
    score = ev.evaluate(EvalCase(id="c1"), _obs(scenario="s", oracle="legacy",
                                                expected={"a": 1}, observed={"a": 1}))
    assert score.passed and score.value == 1.0
    assert all(c.ok for c in score.checks)


def test_equivalence_fails_on_any_difference():
    ev = DeterministicEquivalenceEvaluator()
    score = ev.evaluate(EvalCase(id="c1"), _obs(scenario="s", oracle="legacy",
                                                expected={"severity": "critical"},
                                                observed={"severity": "warning"}))
    assert not score.passed and not score.skipped
    assert score.blockers, "a mismatch must be a BLOCK-severity check, not advisory"


def test_a_missing_comparison_fails_rather_than_skips():
    """The runner scores `passed = not fired and not error`, so a skipped evaluator is a PASS.
    A scenario that produced no comparison verified nothing and must not be read as agreement."""
    ev = DeterministicEquivalenceEvaluator()
    score = ev.evaluate(EvalCase(id="c1"), EvalObservation())
    assert not score.passed
    assert not score.skipped, "'we could not check' must never round to 'it checks out'"


def test_the_evaluator_declares_no_requires():
    """`requires` is how the runner decides to SKIP. Any entry here would give this evaluator a
    route to a vacuous pass, so the emptiness is load-bearing, not incidental."""
    assert DeterministicEquivalenceEvaluator.requires == ()


# ── the target refuses what it cannot run ────────────────────────────────────────

def test_unknown_scenario_is_an_error_not_an_empty_pass():
    obs = equivalence_target()(EvalCase(id="nope", expected={"scenario": "does-not-exist"}))
    assert "unknown equivalence scenario" in obs.error


def test_every_registered_scenario_has_a_case_in_the_suite():
    """The suite is built from SCENARIOS, so a scenario added without a case would silently
    never run — the pass rate would be over a smaller corpus than the suite claims."""
    from aughor.evals import store

    suite_id = ensure_suite()
    covered = {(c.get("expected") or {}).get("scenario") for c in store.list_cases(suite_id)}
    assert set(SCENARIOS) <= covered


def test_ensure_suite_is_idempotent():
    first, second = ensure_suite(), ensure_suite()
    assert first == second

    from aughor.evals import store
    scenarios = [(c.get("expected") or {}).get("scenario") for c in store.list_cases(first)]
    assert len(scenarios) == len(set(scenarios)), "re-running duplicated the corpus"


# ── a real scenario, genuinely falsified ─────────────────────────────────────────

def test_monitor_equivalence_reports_a_real_disagreement(monkeypatch):
    """Break the legacy half and the scenario must report non-equivalence.

    This is the test that makes the other nine meaningful: with `run_monitor_job` stubbed out,
    the legacy side appends nothing while the engine side still fires, so `expected != observed`.
    If this passed, the comparison would be decorative.
    """
    monkeypatch.setattr("aughor.monitors.scheduler.run_monitor_job", lambda monitor_id: None)
    comparison = SCENARIOS["monitor_alert_equivalence"]()
    assert not comparison.equivalent
    assert comparison.expected["alerts"] == []
    assert len(comparison.observed["alerts"]) == 1


def test_monitor_alert_equivalence_holds_on_real_data():
    """The A5 claim itself, unpatched: same severity, same message, same numbers."""
    comparison = SCENARIOS["monitor_alert_equivalence"]()
    assert comparison.equivalent, (comparison.expected, comparison.observed)
    alert = comparison.observed["alerts"][0]
    assert alert["severity"] == "critical"
    assert alert["message"] == "Revenue floor: 1200 below critical threshold 2000"


def test_comparison_equivalence_is_exact():
    c = Comparison(scenario="s", expected={"n": 1}, observed={"n": 1.0}, oracle="declared")
    assert c.equivalent, "1 == 1.0 in Python; the comparison is value equality by design"
    assert not Comparison(scenario="s", expected={"n": 1}, observed={"n": 2},
                          oracle="declared").equivalent
