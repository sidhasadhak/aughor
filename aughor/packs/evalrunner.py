"""Eval runner (Bet 2) — execute a pack's golden questions and score them.

The promotion gate (evalgate.evaluate_activation) consumes a list of EvalResult; this produces
it. The CHECKER (check_expectation) is pure and testable: it scores a run's metadata against
the eval's `expect` block. The `ask_fn` that runs each golden question THROUGH the engine is the
connection-dependent glue passed in by the caller — so the structure is testable today and the
live executor slots in for step-by-step testing. Never raises.

**A checker that ignores what it cannot judge reports a pass it did not earn.** It used to skip
every expectation key it did not know, so IP-3's goldens — `metric`, `dataset`, `value`,
`tolerance`, `source`, `where` — scored as passing on every surface while nothing was computed,
one planner pass apiece. Two kinds of golden live here now:

- a golden an ENGINE RUN answers (`uses_recipe`, `grain`, `runs_decomposition`, `must_not`),
  scored from the run's metadata as before;
- a golden on a public DATASET (`dataset` + `metric`), which no engine run can answer: it is a
  published figure reproduced from that dataset with no model. Gate 4 measures it
  (`aughor packs measure <id>`) and writes `packs/<id>/measurements/<dataset>.json`, keyed to the
  package's fingerprint. `run_pack_evals` reports what that receipt says — this door downloads
  nothing, builds nothing and calls no model — and the checker refuses to judge one itself.

Any other key is refused by name rather than ignored.
"""
from __future__ import annotations

from typing import Callable

from aughor.packs.models import Pack
from aughor.packs.evalgate import EvalResult


#: The expectation keys an engine run's metadata can answer.
ENGINE_KEYS = ("uses_recipe", "grain", "runs_decomposition", "must_not")
#: The keys of a golden measured on a public dataset (IP-3) — gate 4's, never an engine run's.
DATASET_KEYS = ("metric", "dataset", "value", "tolerance", "source", "where")


def dataset_of(expect: dict) -> str:
    """The public dataset a golden is measured on, or "" when an engine run answers it."""
    expect = expect or {}
    return str(expect.get("dataset") or "") if expect.get("metric") else ""


def check_expectation(meta: dict, expect: dict) -> tuple[bool, str]:
    """Score one run's metadata against an eval's expectations. `meta` keys a live runner
    supplies: recipe_used, grain, ran_decomposition, text (the answer).

    A golden on a dataset is refused here: no engine run can answer it, and reporting it as
    passed was the false green this checker used to give. `run_pack_evals` reads gate 4's
    receipt for it. An expectation key this checker does not know is refused by name."""
    meta = meta or {}
    dataset = dataset_of(expect)
    if dataset:
        return False, (f"a golden on {dataset} is measured by gate 4 on that dataset, not by an engine run — "
                       f"read the package's receipt (measurements/{dataset}.json)")
    unknown = [k for k in (expect or {}) if k not in ENGINE_KEYS]
    if unknown:
        return False, ("this checker cannot judge " + ", ".join(f"'{k}'" for k in sorted(unknown))
                       + " — it scores what an engine run reports")
    for key, val in (expect or {}).items():
        if key == "uses_recipe":
            used = meta.get("recipe_used") or ""
            norm = lambda s: str(s).lower().replace("-", " ").replace("_", " ").strip()
            pool = [norm(used)] if isinstance(used, str) else [norm(u) for u in used]
            needle = norm(val)
            if not any(needle and (needle in u or u in needle) for u in pool if u):
                return False, f"expected recipe '{val}', got '{used}'"
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
        if dataset_of(ev.expect):
            results.append(receipt_verdict(pack, ev.question, ev.expect))
            continue
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


def receipt_verdict(pack: Pack, question: str, expect: dict) -> EvalResult:
    """What gate 4 measured for a golden on a public dataset, read from the package's own receipt.

    This door never downloads a dataset, never builds one and never calls a model: `aughor packs measure <id>`
    does that and writes the receipt, which CI holds to the package's fingerprint. A receipt that is missing, that
    describes an older package, or that does not carry this question is reported as exactly that — not as a pass.
    """
    from pathlib import Path

    from aughor.packs import gate4

    dataset = dataset_of(expect)
    measure = f"run `aughor packs measure {pack.id}`"
    try:
        receipt = gate4.read_receipt(pack, dataset)
        fingerprint = gate4.package_fingerprint(Path(pack.path)) if pack.path else ""
    except Exception as exc:                      # noqa: BLE001 — an unreadable receipt is a verdict, not a crash
        from aughor.kernel.errors import tolerate
        tolerate(exc, f"pack {pack.id}: receipt for {dataset} could not be read", counter="packs.eval_receipt")
        return EvalResult(question, passed=False, detail=f"the receipt for {dataset} could not be read: {exc}")
    if receipt is None:
        return EvalResult(question, passed=False,
                          detail=f"not measured here: gate 4 measures it on {dataset}, and the package carries no "
                                 f"receipt for it — {measure}")
    measured_at = receipt.get("measured_at") or "an unknown date"
    if fingerprint and receipt.get("package_fingerprint") != fingerprint:
        return EvalResult(question, passed=False,
                          detail=f"the package changed since {dataset} was measured on {measured_at} — {measure}")
    entry = next((g for g in receipt.get("goldens") or [] if g.get("question") == question), None)
    if entry is None:
        return EvalResult(question, passed=False,
                          detail=f"the receipt for {dataset}, measured {measured_at}, does not carry this "
                                 f"question — {measure}")
    if not entry.get("ok"):
        said = entry.get("error") or f"measured {entry.get('measured')}, published {entry.get('expected')}"
        return EvalResult(question, passed=False,
                          detail=f"did not reproduce on {dataset} ({measured_at}): {said}")
    return EvalResult(question, passed=True,
                      detail=f"reproduced on {dataset}: measured {entry.get('measured')}, published "
                             f"{entry.get('expected')} (tolerance {entry.get('tolerance')}), by gate 4 on {measured_at}")
