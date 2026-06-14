#!/usr/bin/env python3
"""Reflective prompt optimization (GEPA-style) for Aughor's SQL-generation system prompt.

Optimizes ``CHAT_SQL_SYSTEM`` against the golden NL2SQL set:

    evaluate the current prompt on a train split (generate SQL per question via the real
    chat path, score deterministically with sql_accuracy) → reflect on the worst failures
    with an LLM to propose a REVISED prompt → evaluate the candidates → keep the best →
    repeat for a few rounds → report the lift on a held-out split.

The eval is the **gate**: a candidate prompt is only adopted if it scores *higher* on the
train split, so reflection can never regress quality (the worst case is "no change"). This
is the core GEPA idea — reflect on failures to mutate, let a measured metric select.

Offline only: it produces a better prompt string + a measured held-out lift; you review the
diff and paste the winner into ``aughor/agent/prompts.py``. Nothing is auto-shipped.

Run (needs the configured coder model available)::

    python -m evals.gepa_optimize --rounds 2 --candidates 3 --train-frac 0.6 --output evals/gepa_result.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Per-question generation + scoring result.
EvalResult = dict
# evaluate_fn(prompt, records) -> (mean_overall, [EvalResult]); reflect_fn(prompt, results, n) -> [prompt]
EvaluateFn = Callable[[str, list[dict]], tuple[float, list[EvalResult]]]
ReflectFn = Callable[[str, list[EvalResult], int], list[str]]


# ── Real LLM-backed evaluate + reflect (the CLI wires these) ──────────────────

def _gen_sql(question: str, conn_id: str, schema: str, system_prompt: str, temperature: float = 0.0) -> str:
    """Generate SQL for a question under an arbitrary system prompt (mirrors
    run_golden.generate_sql_chat, but the system prompt is the optimizable input)."""
    from pydantic import BaseModel, Field

    from aughor.agent.prompts import CHAT_PROMPT
    from aughor.llm.provider import get_provider

    user = CHAT_PROMPT.format(
        schema=schema, history_section="", question=question, schema_qualifier="",
        kb_patterns_section="", conn_kb_section="", sql_examples_section="", metrics_section="",
        exploration_section="", causal_section="", document_section="",
    )

    class ChatAnswerModel(BaseModel):
        sql: str = ""
        headline: str = ""
        chart_type: str = "auto"
        intent: str = ""
        approach: list[str] = Field(default_factory=list)

    ans = get_provider("coder").complete(
        system=system_prompt, user=user, response_model=ChatAnswerModel, temperature=temperature
    )
    return (ans.sql or "").strip()


def evaluate(system_prompt: str, records: list[dict], db, schema: str) -> tuple[float, list[EvalResult]]:
    """Generate + score SQL for every record under ``system_prompt``. Returns the mean overall
    score and the per-record results (used as reflection fuel)."""
    from evals.sql_accuracy import score_single

    results: list[EvalResult] = []
    for rec in records:
        ref = rec.get("reference_sql", "")
        try:
            sql = _gen_sql(rec["question"], rec.get("connection_id", "samples"), schema, system_prompt)
        except Exception as e:
            results.append({"id": rec["id"], "question": rec["question"], "generated_sql": None,
                            "reference_sql": ref, "overall": 0.0, "error": f"generation failed: {e}"})
            continue
        sc = score_single(db, rec, sql)
        results.append({"id": rec["id"], "question": rec["question"], "generated_sql": sql,
                        "reference_sql": ref, "overall": float(sc.get("overall", 0.0)), "error": sc.get("error")})
    mean = sum(r["overall"] for r in results) / len(results) if results else 0.0
    return mean, results


def format_failures(results: list[EvalResult], k: int = 8) -> str:
    """A digest of the worst k cases — the reflection LLM's fuel."""
    fails = sorted((r for r in results if r["overall"] < 0.99), key=lambda r: r["overall"])[:k]
    blocks = []
    for r in fails:
        err = f"\n  error: {r['error']}" if r.get("error") else ""
        blocks.append(
            f"Q: {r['question']}\n  reference: {r['reference_sql']}\n  generated: {r['generated_sql']}"
            f"\n  score: {r['overall']:.2f}{err}"
        )
    return "\n\n".join(blocks) if blocks else "(no failures — the prompt scores well already)"


_REFLECT_SYSTEM = (
    "You are an expert prompt engineer improving the SYSTEM PROMPT of a text-to-SQL data analyst. "
    "You are given the current system prompt and a set of FAILING examples (the analyst's generated "
    "SQL scored low against a reference). Propose a REVISED system prompt that fixes the observed "
    "failure patterns while preserving the rules that already work. Be surgical: sharpen or add "
    "concept-mapping / schema-fidelity / formatting rules that directly address the failures. Keep "
    "it a single coherent system prompt in the same terse style, with NO template placeholders "
    "(no curly-brace fields). Do not make it dramatically longer."
)


def reflect(current_prompt: str, failure_digest: str, n: int, model_role: str = "coder") -> list[str]:
    """Ask the reflection LLM for n revised prompts (varied via temperature)."""
    from pydantic import BaseModel

    from aughor.llm.provider import get_provider

    class Revision(BaseModel):
        revised_prompt: str
        rationale: str

    out: list[str] = []
    for i in range(n):
        user = (
            f"CURRENT SYSTEM PROMPT:\n\"\"\"\n{current_prompt}\n\"\"\"\n\n"
            f"FAILING EXAMPLES:\n{failure_digest}\n\n"
            f"Propose revision #{i + 1}. Vary your strategy across revisions. Return the full revised "
            f"system prompt in `revised_prompt` and a one-line `rationale`."
        )
        try:
            rev = get_provider(model_role).complete(
                system=_REFLECT_SYSTEM, user=user, response_model=Revision, temperature=0.7
            )
            if rev.revised_prompt and rev.revised_prompt.strip():
                out.append(rev.revised_prompt.strip())
        except Exception:
            continue
    return out


# ── The optimization loop (pure — injectable fns make it unit-testable) ───────

def optimize(
    records: list[dict],
    *,
    baseline_prompt: str,
    evaluate_fn: EvaluateFn,
    reflect_fn: ReflectFn,
    rounds: int = 2,
    n_candidates: int = 3,
    train_frac: float = 0.6,
    seed: int = 0,
) -> dict:
    """Reflective hill-climb: keep a candidate only if it beats the current best on the train
    split. Returns the best prompt + baseline/best scores on train and held-out + a round log."""
    recs = list(records)
    random.Random(seed).shuffle(recs)
    cut = max(1, int(len(recs) * train_frac))
    train, heldout = recs[:cut], (recs[cut:] or recs[:cut])

    base_score, base_results = evaluate_fn(baseline_prompt, train)
    best_prompt, best_score, best_results = baseline_prompt, base_score, base_results
    log = [{"round": 0, "candidate": None, "score": round(base_score, 4), "accepted": True, "source": "baseline"}]

    for rd in range(1, rounds + 1):
        candidates = reflect_fn(best_prompt, best_results, n_candidates)
        for ci, cand in enumerate(candidates):
            score, results = evaluate_fn(cand, train)
            accepted = score > best_score
            log.append({"round": rd, "candidate": ci, "score": round(score, 4), "accepted": accepted})
            if accepted:
                best_prompt, best_score, best_results = cand, score, results

    heldout_baseline, _ = evaluate_fn(baseline_prompt, heldout)
    heldout_best, _ = evaluate_fn(best_prompt, heldout) if best_prompt != baseline_prompt else (heldout_baseline, None)

    return {
        "best_prompt": best_prompt,
        "improved": best_prompt != baseline_prompt,
        "train_baseline": round(base_score, 4),
        "train_best": round(best_score, 4),
        "heldout_baseline": round(heldout_baseline, 4),
        "heldout_best": round(heldout_best, 4),
        "heldout_lift": round(heldout_best - heldout_baseline, 4),
        "n_train": len(train),
        "n_heldout": len(heldout),
        "log": log,
    }


def main(argv=None) -> int:
    import os
    os.environ.setdefault("AUGHOR_FALLBACK_DISABLED", "1")  # pin the model (no silent fallback mid-run)

    ap = argparse.ArgumentParser(description="Reflective optimization of the SQL-generation system prompt.")
    ap.add_argument("--dataset", default="evals/golden_sql_expanded.jsonl")
    ap.add_argument("--connection", default="samples")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output", default=None, help="write the optimized prompt + report JSON")
    args = ap.parse_args(argv)

    from aughor.agent.prompts import CHAT_SQL_SYSTEM
    from aughor.db.connection import open_connection_for
    from aughor.llm.provider import get_provider

    records = [json.loads(l) for l in open(args.dataset) if l.strip()]
    if args.limit:
        records = records[: args.limit]
    db = open_connection_for(args.connection)
    schema = db.get_schema()
    p = get_provider("coder")
    print(f"GEPA-SQL: optimizing CHAT_SQL_SYSTEM | model={p.backend}:{p._model} | "
          f"{len(records)} records | rounds={args.rounds} candidates={args.candidates}", flush=True)

    def _eval(prompt, recs):
        t = time.time()
        mean, res = evaluate(prompt, recs, db, schema)
        print(f"  evaluated {len(recs)} recs → mean={mean:.3f}  ({time.time()-t:.0f}s)", flush=True)
        return mean, res

    def _reflect(prompt, results, n):
        return reflect(prompt, format_failures(results), n)

    result = optimize(records, baseline_prompt=CHAT_SQL_SYSTEM, evaluate_fn=_eval, reflect_fn=_reflect,
                      rounds=args.rounds, n_candidates=args.candidates, train_frac=args.train_frac)
    db.close()

    print("\n" + "=" * 60)
    print(" GEPA-SQL result")
    print("=" * 60)
    print(f"  train : {result['train_baseline']:.3f} → {result['train_best']:.3f}")
    print(f"  HELD-OUT: {result['heldout_baseline']:.3f} → {result['heldout_best']:.3f}  "
          f"(lift {result['heldout_lift']:+.3f})  [n={result['n_heldout']}]")
    print(f"  improved: {result['improved']}")
    print("=" * 60)

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"wrote {args.output}  (review best_prompt, paste the winner into prompts.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
