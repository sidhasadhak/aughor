"""Eval runner (Bet 2) — execute a pack's golden questions and score them.

The promotion gate (evalgate.evaluate_activation) consumes a list of EvalResult; this produces
it. The CHECKER (check_expectation) is pure and testable: it scores a run's metadata against
the eval's `expect` block. The `ask_fn` that runs each golden question THROUGH the engine is the
connection-dependent glue passed in by the caller — so the structure is testable today and the
live executor slots in for step-by-step testing. Never raises.
"""
from __future__ import annotations

from typing import Callable

from aughor.packs.models import Pack
from aughor.packs.evalgate import EvalResult


def check_expectation(meta: dict, expect: dict) -> tuple[bool, str]:
    """Score one run's metadata against an eval's expectations. `meta` keys a live runner
    supplies: recipe_used, grain, ran_decomposition, text (the answer). Unknown expectation
    keys are ignored (forward-compatible)."""
    meta = meta or {}
    for key, val in (expect or {}).items():
        if key == "uses_recipe":
            if (meta.get("recipe_used") or "") != val:
                return False, f"expected recipe '{val}', got '{meta.get('recipe_used')}'"
        elif key == "grain":
            if (meta.get("grain") or "") != val:
                return False, f"expected grain '{val}', got '{meta.get('grain')}'"
        elif key == "runs_decomposition":
            if bool(meta.get("ran_decomposition")) != bool(val):
                return False, "decomposition expectation not met"
        elif key == "must_not":
            text = (meta.get("text") or "").lower()
            for bad in (val or []):
                if str(bad).lower() in text:
                    return False, f"must_not violated: '{bad}' present in the answer"
    return True, ""


def run_pack_evals(pack: Pack, ask_fn: Callable[[str], dict]) -> list[EvalResult]:
    """Run every golden question through `ask_fn` (the engine call) and score it. A question
    that errors counts as a fail (the expectation wasn't met), never crashing the run."""
    results: list[EvalResult] = []
    for ev in pack.evals:
        try:
            meta = ask_fn(ev.question) or {}
        except Exception as e:
            from aughor.kernel.errors import tolerate
            tolerate(e, f"eval question errored: {ev.question[:60]}", counter="packs.eval_run")
            results.append(EvalResult(ev.question, passed=False, detail=f"errored: {e}"))
            continue
        ok, detail = check_expectation(meta, ev.expect)
        results.append(EvalResult(ev.question, passed=ok, detail=detail))
    return results
