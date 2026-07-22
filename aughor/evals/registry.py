"""The Evals plane's evaluator registry — the swap-point.

A new evaluator drops in by ``register_evaluator(impl)``; a runner finds it by
name with ``get_evaluator`` / ``run_evaluator``, touching no other plane.
Matches the module-level-dict registry idiom of ``kernel/registries/*`` and
``capability/registry.py`` (a plain dict + register/get + ``clear`` for tests).
"""
from __future__ import annotations

from typing import Optional

from aughor.evals.evaluator import (
    EvalCase,
    EvalObservation,
    EvalScore,
    Evaluator,
    available,
)

_EVALUATORS: dict[str, Evaluator] = {}


def register_evaluator(ev: Evaluator) -> None:
    """Register (or replace) the evaluator for ``ev.name``."""
    _EVALUATORS[ev.name] = ev


def get_evaluator(name: str) -> Optional[Evaluator]:
    return _EVALUATORS.get(name)


def registered_evaluators() -> list[str]:
    return sorted(_EVALUATORS)


def deterministic_evaluators() -> list[str]:
    """Only the guard-backed ones. A suite that mixes deterministic guards with
    judge-style evaluators must be able to say which produced a verdict — the two
    claims do not carry the same weight."""
    return sorted(n for n, e in _EVALUATORS.items() if getattr(e, "deterministic", True))


def run_evaluator(name: str, case: EvalCase, obs: EvalObservation) -> Optional[EvalScore]:
    """Run one evaluator, or None when nothing is registered under ``name``.

    Skips (never fails) when the case cannot supply what the evaluator needs, and
    tolerates its exceptions — the guards' own contract is fail-open, and a suite
    that turns a guard's internal error into a red test would punish the case
    rather than the bug.
    """
    ev = _EVALUATORS.get(name)
    if ev is None:
        return None
    missing = set(getattr(ev, "requires", ())) - available(case, obs)
    if missing:
        return EvalScore(evaluator=name, passed=True, value=0.0, skipped=True,
                         rationale=f"needs {', '.join(sorted(missing))}")
    try:
        return ev.evaluate(case, obs)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"evaluator {name!r} raised; scored as skipped",
                 counter=f"evals.evaluator.{name}")
        return EvalScore(evaluator=name, passed=True, value=0.0, skipped=True,
                         rationale=f"{type(exc).__name__}: {exc}")


def run_all(case: EvalCase, obs: EvalObservation, *,
            names: Optional[list[str]] = None) -> list[EvalScore]:
    """Every registered evaluator (or a named subset) over one case."""
    return [s for s in (run_evaluator(n, case, obs)
                        for n in (names or registered_evaluators())) if s is not None]


def clear() -> None:
    """Drop all registrations (tests). Call ``register_builtins()`` to restore."""
    _EVALUATORS.clear()
