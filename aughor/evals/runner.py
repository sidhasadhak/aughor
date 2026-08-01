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
from typing import Any, Callable, Optional

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
    #: Mean perturbation-robustness over the measurable cases, or None when the run did not
    #: measure it. A first-class FIELD rather than a derived property so `fidelity.axis_of`
    #: reads it like any other axis, and so None stays distinguishable from 0.0.
    robustness: Optional[float] = None
    brittleness_detail: list = field(default_factory=list)

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
            "robustness": None if self.robustness is None else round(self.robustness, 4),
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
                         "capabilities.auto")}
    except Exception as exc:
        tolerate(exc, "eval run config: flag snapshot unavailable",
                 counter="evals.config.flags")
    try:
        # Wave E4: whatever a grid cell is forcing right now. Recorded for EVERY run, not
        # just experiment runs — a run that happened to execute inside a cell and did not
        # say so is the one whose number gets filed under the wrong configuration.
        from aughor.evals.experiments import fallback_disabled
        from aughor.kernel.flags import active_flag_overrides
        from aughor.llm.provider import current_run_temperature
        cfg["flag_overrides"] = active_flag_overrides()
        cfg["temperature"] = current_run_temperature()
        cfg["fallback_disabled"] = fallback_disabled()
    except Exception as exc:
        tolerate(exc, "eval run config: run-scoped overrides unavailable",
                 counter="evals.config.overrides")
    return cfg


def run_suite(suite_id: str, target: Target, *, iterations: int = 1,
              evaluators: Optional[list[str]] = None,
              checker: Optional[Checker] = None,
              persist: bool = True,
              config_extra: Optional[dict] = None,
              perturbations: Optional[Any] = None) -> RunSummary:
    """Run every case in ``suite_id`` through ``target``, ``iterations`` times.

    ``persist`` writes the run and every per-case result to the store; pass
    False for a dry measurement that leaves no trace. ``config_extra`` merges into the
    recorded config — how :func:`run_experiment` stamps a cell's label onto its run.

    ``perturbations`` (a sequence from :mod:`aughor.evals.perturb`, or None) additionally
    measures the brittleness axis: each case is re-asked in meaning-preserving rewordings and
    the result sets compared. It multiplies the run's cost by roughly the number of
    perturbations, so it is opt-in rather than on by default.
    """
    cases = store.list_cases(suite_id)
    config = _run_config()
    config["iterations"] = iterations
    config["evaluators"] = evaluators or "all"
    if config_extra:
        config.update(config_extra)

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
        if perturbations:
            # Inside the try so a brittleness failure marks the run FAILED rather than
            # reporting a run that measured less than it claims to have measured.
            from aughor.evals.perturb import suite_robustness
            cases_for_perturb = [_eval_case(row) for row in cases]
            summary.robustness, detail = suite_robustness(
                cases_for_perturb, target, perturbations=perturbations)
            summary.brittleness_detail = [b.to_dict() for b in detail]
    except BaseException:
        if persist:
            store.finish_run(run_id, status=store.FAILED, summary=summary.to_dict())
        raise

    if persist:
        store.finish_run(run_id, status=store.SUCCEEDED, summary=summary.to_dict())
    return summary


@dataclass
class CellResult:
    """One cell's replicated runs, with the configuration they actually ran under."""

    label: str
    runs: list = field(default_factory=list)          # list[RunSummary], one per replicate
    config: dict = field(default_factory=dict)
    discrepancies: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fixture_version: Optional[str] = None
    error: str = ""

    @property
    def run(self) -> Optional[RunSummary]:
        """The first replicate — the convenience view for a single-replicate grid."""
        return self.runs[0] if self.runs else None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "runs": [r.to_dict() for r in self.runs],
            "config": self.config,
            "discrepancies": self.discrepancies,
            "warnings": self.warnings,
            "fixture_version": self.fixture_version,
            "error": self.error,
        }


def run_experiment(suite_id: str, target_factory: Callable[[], Target],
                   cells: list, *, iterations: int = 1, replicates: int = 1,
                   evaluators: Optional[list[str]] = None,
                   checker: Optional[Checker] = None,
                   persist: bool = True,
                   fixture: Any = None, fixture_tables: Optional[list[str]] = None,
                   connection_id: str = "",
                   allow_exploration: bool = False,
                   freeze: bool = False,
                   perturbations: Optional[Any] = None,
                   request_budget: int = 0,
                   requests_per_case: int = 1) -> list[CellResult]:
    """Run ``suite_id`` once per cell, each under that cell's configuration.

    ``target_factory`` is a factory rather than a target on purpose. Graph-topology flags
    are read at COMPILE time (``agent/graph.py`` 128/140/229, inside ``_compile()``), so a
    target built before the loop would bake in the process-global topology while every
    other axis moved — a half-overridden cell that reports as fully overridden. Taking a
    factory means the target can only be constructed inside the cell's context; the trap is
    closed by the signature instead of by a comment somebody has to read. Same inversion as
    R5's parallel-safety declaration: put the obligation where it cannot be forgotten.

    One cell's failure does not abandon the grid — it is recorded on that cell and the rest
    still run, because a baseline plus three of four variants is a usable result and losing
    all four to one bad cell is not.

    ``replicates`` runs each cell's whole suite that many times, which is a different noise
    source from ``iterations`` and neither substitutes for the other: ``iterations`` repeats
    each CASE inside one run and produces E3's stable/flaky verdict, while ``replicates``
    repeats the entire RUN and is what :mod:`aughor.evals.fidelity` needs to establish a
    noise floor. A configuration compared only against another configuration, never against
    itself, cannot tell a four-point effect from four-point jitter.

    ``fixture`` (a connection) stamps ``snapshot.data_version`` onto every cell and re-probes
    it after each one, so "the data moved mid-grid" becomes a recorded warning instead of an
    unexplained delta somebody attributes to the variant. ``connection_id`` additionally
    applies the frozen-semantics guard before anything runs.
    """
    from aughor.evals.experiments import (
        assert_frozen_semantics, assert_measurable, assert_within_budget,
        data_version_of, estimate_requests,
    )
    from aughor.kernel.flags import flag_enabled

    if not flag_enabled("evals.experiments"):
        raise RuntimeError(
            "grid experiments are off — enable the `evals.experiments` flag "
            "(AUGHOR_EVALS_EXPERIMENTS=1) before running one. Refusing rather than "
            "silently running every cell under one configuration, which would produce a "
            "grid of identical numbers that looks like 'the variant made no difference'."
        )
    # Both integrity guards sit OUTSIDE the per-cell try, because both describe conditions
    # that invalidate the WHOLE grid rather than one cell of it: a live failover chain is
    # process-global, and a connection's volatile semantics are shared by every cell. Letting
    # either fall into the per-cell handler would report one global fault as N identical cell
    # failures, which reads as "the grid ran and everything broke" instead of "the grid was
    # never eligible to run". `applied()` re-checks measurability for callers that use a cell
    # directly, where the per-cell blast radius IS the whole blast radius.
    assert_measurable()
    if connection_id:
        # `freeze` supersedes the emptiness check with a stronger one. The guard refuses
        # a connection carrying volatile state because it DRIFTS between cells; the
        # frozen harness pins that state, suppresses the writers that would move it, and
        # verifies afterwards that it did not. "Identical for every cell" is a strictly
        # stronger guarantee than "empty", and it is the only way to measure a flag whose
        # value depends on the connection having accumulated something to read.
        # It is not `allow_exploration` by another name: that one stops mentioning the
        # confound, this one proves it did not occur.
        assert_frozen_semantics(connection_id,
                                allow_exploration=allow_exploration or freeze)
    if request_budget:
        assert_within_budget(
            estimate_requests(cells=len(cells), cases=len(store.list_cases(suite_id)),
                              replicates=replicates, iterations=iterations,
                              perturbations=len(perturbations or ()),
                              requests_per_case=requests_per_case),
            budget=request_budget)

    opening_version = data_version_of(fixture, fixture_tables) if fixture is not None else None

    results: list[CellResult] = []
    from contextlib import ExitStack
    with ExitStack() as _pin:
        # Entered around the WHOLE grid, not per cell: the point is that every cell saw
        # the same state, which a per-cell pin could not establish. Its exit re-probes
        # and raises if anything moved — voiding the grid rather than returning numbers
        # nobody can attribute.
        if freeze and connection_id:
            from aughor.evals.frozen import frozen_semantics
            _pin.enter_context(frozen_semantics(connection_id, strict=True))
        results.extend(_run_cells(
            cells, suite_id, target_factory, opening_version,
            iterations=iterations, replicates=replicates, evaluators=evaluators,
            checker=checker, persist=persist, fixture=fixture,
            fixture_tables=fixture_tables, perturbations=perturbations))
    return results


def _run_cells(cells, suite_id, target_factory, opening_version, *,
               iterations, replicates, evaluators, checker, persist,
               fixture, fixture_tables, perturbations) -> list["CellResult"]:
    """The grid's inner loop, lifted so the freeze pin can wrap it without indenting
    (and re-indenting) the body every time the surrounding contract changes."""
    from aughor.evals.experiments import applied, data_version_of
    from aughor.kernel.errors import tolerate

    results: list[CellResult] = []
    for cell in cells:
        result = CellResult(label=cell.label, fixture_version=opening_version)
        try:
            with applied(cell) as resolved:
                result.config = resolved["effective"]
                result.discrepancies = resolved["discrepancies"]
                for rep in range(max(1, replicates)):
                    result.runs.append(run_suite(
                        suite_id, target_factory(), iterations=iterations,
                        evaluators=evaluators, checker=checker, persist=persist,
                        config_extra={"cell": cell.label,
                                      "replicate": rep,
                                      "cell_requested": resolved["requested"],
                                      "discrepancies": resolved["discrepancies"],
                                      "data_version": opening_version},
                        perturbations=perturbations,
                    ))
        except Exception as exc:
            tolerate(exc, f"experiment cell {cell.label!r} failed; remaining cells still run",
                     counter="evals.experiment.cell_failed")
            result.error = f"{type(exc).__name__}: {exc}"
        if fixture is not None:
            now = data_version_of(fixture, fixture_tables)
            if now != opening_version:
                result.warnings.append(
                    f"the fixture moved during cell {cell.label!r} "
                    f"({opening_version} → {now}); this cell did not see the same data as "
                    f"the ones before it, so its delta is not attributable to the variant.")
                result.fixture_version = now
                opening_version = now
        results.append(result)
    return results


async def schedule_experiment(
    suite_id: str, target_factory: Callable[[], "Target"], cells: list, *,
    iterations: int = 1, replicates: int = 1,
    evaluators: Optional[list[str]] = None, checker: Optional["Checker"] = None,
    persist: bool = True, fixture: Any = None, fixture_tables: Optional[list[str]] = None,
    connection_id: str = "", allow_exploration: bool = False,
    perturbations: Optional[Any] = None, request_budget: int = 0,
    requests_per_case: int = 1, org_id: Optional[str] = None,
) -> str:
    """Run a grid as a SUPERVISED BACKGROUND JOB instead of inline in the caller.

    ``run_experiment`` blocks its caller for the whole grid — fine from a script, wrong from a
    request handler or a scheduler tick, where a multi-cell × multi-replicate run would hold the
    call open for minutes. This submits the grid to the job kernel: it runs off the event loop
    (the cells stay serial — the LLM concurrency semaphore is a rate limiter, not a bottleneck to
    parallelise around, see the E4c note), emits ``job.state`` so its progress is followable, and
    is heartbeat-supervised and cancellable like any other job.

    **The budget guard is the precondition, checked HERE — before a job row exists.** A grid
    estimated over its allowance is refused synchronously at schedule time, so the caller never
    receives a job id for a run doomed to fail asymmetrically halfway through (``run_experiment``
    re-checks it inside the job too; this is defence in depth, not a substitute). ``assert_measurable``
    runs up front for the same reason: reject an unmeasurable grid before enqueue, not after.

    Returns the job id. Grid results land in the eval store per cell (``persist``); assemble the
    :class:`CellResult` view for the ``FidelityReport`` from those runs by suite/run id.
    """
    import asyncio

    from aughor.evals.experiments import (
        assert_measurable, assert_within_budget, estimate_requests,
    )
    from aughor.kernel.flags import flag_enabled
    from aughor.kernel.jobs import kernel

    if not flag_enabled("evals.experiments"):
        raise RuntimeError(
            "grid experiments are off — enable the `evals.experiments` flag "
            "(AUGHOR_EVALS_EXPERIMENTS=1) before scheduling one.")

    # Preconditions BEFORE the job is created: an ineligible grid must fail at the call that
    # schedules it, not silently as a job that transitions straight to FAILED.
    assert_measurable()
    if request_budget:
        assert_within_budget(
            estimate_requests(cells=len(cells), cases=len(store.list_cases(suite_id)),
                              replicates=replicates, iterations=iterations,
                              perturbations=len(perturbations or ()),
                              requests_per_case=requests_per_case),
            budget=request_budget)

    def _work() -> list:
        # run_experiment re-runs the full guard battery (measurable · frozen semantics · budget)
        # inside the job — the schedule-time checks above are the early, synchronous copy.
        return run_experiment(
            suite_id, target_factory, cells, iterations=iterations, replicates=replicates,
            evaluators=evaluators, checker=checker, persist=persist, fixture=fixture,
            fixture_tables=fixture_tables, connection_id=connection_id,
            allow_exploration=allow_exploration, perturbations=perturbations,
            request_budget=request_budget, requests_per_case=requests_per_case)

    return await kernel().submit(
        "eval_experiment",
        lambda: asyncio.to_thread(_work),
        conn_id=connection_id or None,
        org_id=org_id,
        idempotency_key=f"eval_experiment:{suite_id}:{len(cells)}x{max(1, replicates)}",
        payload={"suite_id": suite_id, "cells": [getattr(c, "label", str(c)) for c in cells],
                 "replicates": replicates, "iterations": iterations,
                 "request_budget": request_budget},
    )


def _eval_case(case_row: dict) -> EvalCase:
    """A stored row as the EvalCase a target consumes.

    Extracted so the brittleness pass and `_run_case` cannot drift: two hand-built copies of
    one construction is the shape where a field added to one is missed by the other, and the
    brittleness pass would then measure a subtly different case than the run it annotates.
    """
    from aughor.trust import Scope

    return EvalCase(
        id=case_row["id"], question=case_row.get("question", ""),
        artifact=case_row.get("artifact", ""),
        expected=case_row.get("expected") or {},
        tags=tuple(case_row.get("tags") or ()),
        scope=Scope(),      # the target owns connection/dialect binding
    )


def _run_case(run_id: str, case_row: dict, target: Target, *, iterations: int,
              evaluators: Optional[list[str]], checker: Optional[Checker],
              persist: bool) -> CaseOutcome:
    case = _eval_case(case_row)
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
