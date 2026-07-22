"""The suite runner — cases × targets × evaluators, with replication.

Generalises the shape ``packs/evalrunner.run_pack_evals`` already proves: batch
over cases with the TARGET INJECTED, so the same runner measures ``/ask``, a
headless investigation, a brief, or a plain SQL replay without knowing which.

**The replication machinery is the point, not decoration.** The Spider 2.0 work
established, expensively, that a single run of a stochastic pipeline is not a
measurement:

- runs flip-flop between reps even at temperature 0, so a suite reports
  ``stable_pass`` / ``stable_fail`` / ``flaky`` rather than a bare percentage —
  a case that passes 2 of 3 times is telling you something a percentage hides;
- aggregate deltas lie at small n, so every result carries **which evaluators
  fired on it**, making per-case causal attribution ("did my change touch this
  case, and did that case flip?") possible instead of eyeballing a total;
- a feature that no-ops silently looks exactly like one that did not help, so
  skips are counted and reported separately from failures.

None of that is inferable after the fact from a stored percentage, which is why
it is computed here and persisted per case.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from aughor.evals import store
from aughor.evals.evaluator import EvalCase, EvalObservation, EvalScore
from aughor.evals.registry import run_all
from aughor.evals.store import FLAKY, STABLE_FAIL, STABLE_PASS

#: A target turns a case into what actually happened. The one seam every
#: answer path plugs into.
Target = Callable[[EvalCase], EvalObservation]

#: Optional correctness check — did the observation match what the case expected?
#: Separate from the evaluators on purpose: "the guards found nothing wrong" and
#: "the answer is right" are different claims and a suite must not conflate them.
Checker = Callable[[EvalCase, EvalObservation], Optional[bool]]


@dataclass
class CaseOutcome:
    """One case across all iterations."""
    case_id: str
    question: str = ""
    iterations: int = 0
    passes: int = 0
    corrects: int = 0
    correctness_known: int = 0
    verdict: str = STABLE_PASS
    fired: list[str] = field(default_factory=list)      # union across iterations
    unstable_evaluators: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mean_ms: float = 0.0
    scores: list[EvalScore] = field(default_factory=list)   # last iteration's detail

    @property
    def pass_rate(self) -> float:
        return self.passes / self.iterations if self.iterations else 0.0


@dataclass
class RunSummary:
    run_id: str
    suite_id: str
    iterations: int
    total: int = 0
    stable_pass: int = 0
    stable_fail: int = 0
    flaky: int = 0
    correct: int = 0
    correctness_known: int = 0
    errors: int = 0
    fired_counts: dict[str, int] = field(default_factory=dict)
    outcomes: list[CaseOutcome] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        """Stable passes only. A flaky case is deliberately NOT counted as a
        pass — rounding it up is how a suite talks itself into a green number."""
        return self.stable_pass / self.total if self.total else 0.0

    @property
    def accuracy(self) -> Optional[float]:
        """Correctness against expectations, over the cases that HAD one."""
        if not self.correctness_known:
            return None
        return self.correct / self.correctness_known

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "suite_id": self.suite_id,
            "iterations": self.iterations, "total": self.total,
            "stable_pass": self.stable_pass, "stable_fail": self.stable_fail,
            "flaky": self.flaky, "pass_rate": round(self.pass_rate, 4),
            "correct": self.correct, "correctness_known": self.correctness_known,
            "accuracy": None if self.accuracy is None else round(self.accuracy, 4),
            "errors": self.errors, "fired_counts": self.fired_counts,
            "config": self.config,
        }


def _run_config() -> dict:
    """What this run ran UNDER — model, backend, active flags.

    Recorded because the ratchet's five historical runs have no model column, so
    their 0.62–0.66 spread cannot be compared against anything: a later number
    would silently mix a harness change with a model change. A measurement
    without its configuration is not a measurement.
    """
    from aughor.kernel.errors import tolerate

    cfg: dict = {}
    try:
        # resolve_binding is the public seam and returns (backend, model, base_url),
        # so the backend comes from it rather than from provider internals.
        from aughor.llm.provider import resolve_binding
        cfg["backend"] = resolve_binding("coder")[0]
        cfg["models"] = {role: resolve_binding(role)[1] for role in ("coder", "narrator")}
    except Exception as exc:
        cfg["backend"] = "unknown"
        tolerate(exc, "eval run config: model binding unavailable; recorded as unknown",
                 counter="evals.config.model")
    try:
        from aughor.kernel.flags import flag_enabled
        cfg["flags"] = {name: flag_enabled(name) for name in
                        ("trust.verify_live", "trust.e1_live", "ask.resolve_first",
                         "capabilities.auto", "plan.program")}
    except Exception as exc:
        tolerate(exc, "eval run config: flag snapshot unavailable",
                 counter="evals.config.flags")
    return cfg


def run_suite(suite_id: str, target: Target, *, iterations: int = 1,
              evaluators: Optional[list[str]] = None,
              checker: Optional[Checker] = None,
              persist: bool = True) -> RunSummary:
    """Run every case in ``suite_id`` through ``target``, ``iterations`` times.

    ``persist`` writes the run and every per-case result to the store; pass
    False for a dry measurement that leaves no trace.
    """
    cases = store.list_cases(suite_id)
    config = _run_config()
    config["iterations"] = iterations
    config["evaluators"] = evaluators or "all"

    trace_id = ""
    try:
        from aughor import telemetry
        trace_id = telemetry.current_trace_id()
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "eval run: ambient trace unavailable; run recorded uncorrelated",
                 counter="evals.trace")

    run_id = store.start_run(suite_id, iterations=iterations, config=config,
                             trace_id=trace_id) if persist else "dry"
    summary = RunSummary(run_id=run_id, suite_id=suite_id, iterations=iterations,
                         total=len(cases), config=config)

    try:
        for case_row in cases:
            outcome = _run_case(run_id, case_row, target, iterations=iterations,
                                evaluators=evaluators, checker=checker,
                                persist=persist)
            summary.outcomes.append(outcome)
            if outcome.verdict == STABLE_PASS:
                summary.stable_pass += 1
            elif outcome.verdict == STABLE_FAIL:
                summary.stable_fail += 1
            else:
                summary.flaky += 1
            summary.correct += outcome.corrects
            summary.correctness_known += outcome.correctness_known
            if outcome.errors:
                summary.errors += 1
            for name in outcome.fired:
                summary.fired_counts[name] = summary.fired_counts.get(name, 0) + 1
    except BaseException:
        if persist:
            store.finish_run(run_id, status=store.FAILED, summary=summary.to_dict())
        raise

    if persist:
        store.finish_run(run_id, status=store.SUCCEEDED, summary=summary.to_dict())
    return summary


def _run_case(run_id: str, case_row: dict, target: Target, *, iterations: int,
              evaluators: Optional[list[str]], checker: Optional[Checker],
              persist: bool) -> CaseOutcome:
    from aughor.trust import Scope

    case = EvalCase(
        id=case_row["id"], question=case_row.get("question", ""),
        artifact=case_row.get("artifact", ""),
        expected=case_row.get("expected") or {},
        tags=tuple(case_row.get("tags") or ()),
        scope=Scope(),      # the target owns connection/dialect binding
    )
    outcome = CaseOutcome(case_id=case.id, question=case.question,
                          iterations=iterations)
    fired_per_iteration: list[set[str]] = []
    total_ms = 0.0

    for i in range(iterations):
        t0 = time.monotonic()
        error = ""
        fired: list[str] = []
        scores: list[EvalScore] = []
        correct: Optional[bool] = None
        try:
            obs = target(case)
            scores = run_all(case, obs, names=evaluators)
            fired = [s.evaluator for s in scores if not s.passed and not s.skipped]
            error = obs.error or ""
            if checker is not None:
                correct = checker(case, obs)
        except Exception as exc:
            # A target that blows up is a failed case, not a failed run — one bad
            # case must not cost you the other 52 results.
            error = f"{type(exc).__name__}: {exc}"
        ms = (time.monotonic() - t0) * 1000.0
        total_ms += ms

        passed = not fired and not error
        if passed:
            outcome.passes += 1
        if correct is not None:
            outcome.correctness_known += 1
            if correct:
                outcome.corrects += 1
        if error:
            outcome.errors.append(error)
        fired_per_iteration.append(set(fired))
        outcome.scores = scores

        if persist:
            store.record_result(run_id, case.id, i, passed=passed, correct=correct,
                                duration_ms=ms, error=error, fired=fired,
                                scores=[s.to_dict() for s in scores])

    outcome.mean_ms = round(total_ms / iterations, 2) if iterations else 0.0
    outcome.fired = sorted(set().union(*fired_per_iteration)) if fired_per_iteration else []
    # An evaluator that fires in some iterations but not others is itself a
    # flake signal, and a more precise one than the case-level verdict.
    if fired_per_iteration:
        common = set.intersection(*fired_per_iteration)
        outcome.unstable_evaluators = sorted(set(outcome.fired) - common)
    outcome.verdict = (STABLE_PASS if outcome.passes == iterations else
                       STABLE_FAIL if outcome.passes == 0 else FLAKY)
    return outcome
