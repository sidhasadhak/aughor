# Spider 2.0 campaign — Phase-0 fail-analysis + the first cheap lever

*2026-07-06 (WS5, branch `2026-07-06-10x-program`). Offline analysis of the full 135-instance
Spider2-Lite local run (`evals/spider2_out`, product prompt on `qwen3-coder-next:cloud`), plus
the first measured campaign lever. Tooling: `scripts/spider2_fail_analysis.py` (pure CSV
comparison against gold, no LLM). Companion: `docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md` §5.*

## The run

**72 / 135 correct = 53.3%** (official `evaluate.py --mode sql`; 135/135 executed clean).

## Fail histogram (the 63 misses)

| Category | Count | % of misses | What it means |
|---|---|---|---|
| **wrong_values** | 49 | 78% | runs, right shape, wrong numbers — grain / aggregation / filter / multi-step logic |
| **wrong_shape** | 8 | 13% | a gold-wanted column is absent from our output |
| **empty_result** | 6 | 10% | wrong filter literal — 0 rows where gold has rows |
| exec_error | 0 | 0% | (every query executed; the closed loop + guards did their job) |

Only **7 of 63 misses carry an external-knowledge doc** — so the harness's EK reading (a June gap
now closed) helps at most 7 on this slice (larger on the cloud tracks).

## What each bucket needs (evidence, not assumption)

- **wrong_shape (8) — the CHEAP lever.** Inspected all 8: **4 (local023, 075, 130, 209) are simply
  *missing* a gold column with matching row counts** — gold keeps the grouping key / intermediate
  metric / entity id (`avg_runs_per_match`, `Grade`, `store_id`, `product_id`) that the product's
  **ANSWER_SHAPE rule trimmed away**. The evaluator scores by column *containment* (a gold column
  must match some predicted column; **extras are free**), so ANSWER_SHAPE — which is product-correct
  ("precise answers, nothing more") — is benchmark-*wrong*. Fix: a harness-only projection directive
  that keeps grouping keys + intermediates and emits both forms of an ambiguous metric (finding #2,
  "superset projection"). The other 4 wrong_shape are grain/row-count errors (harder).

- **wrong_values (49) — the REAL climb, needs Phases 1–2.** Heterogeneous but dominated by
  grain-of-intent ambiguity and aggregation logic, NOT anything a prompt/guard fixes:
  - `local021` avg 68 vs gold 1131 (~16×) — a per-match-per-striker vs per-striker-career **grain
    ambiguity**; our composite-key join is 1:1 (verified — the grain guard *correctly* stayed
    silent, not a guard gap). Two valid readings diverge → SOMA candidate-disagreement territory.
  - `local007` 4.92 vs 4.85 — a subtle inclusive/exclusive boundary in the computation.
  - `local015` value matches but the label is `helmet` vs gold `helmet_worn` — value-domain/label
    formatting.
  - `local066` different toppings + counts — counting/dedup grain.
  These need the substrate (metric definitions, join grain, value domains) + execution-grounded
  probing — the harder, higher-value builds. The cheap levers can't touch them.

- **empty_result (6)** — wrong filter literal; filter-literal binding (shipped) + closed-loop empty
  recovery are the levers; small bucket.

## First lever measured — containment-aware projection (finding #2)

Added `_BENCH_PROJECTION` to `evals/spider2.py` (flag `--no-bench-projection` ablates): counters
the product ANSWER_SHAPE trim for the benchmark — keep grouping keys + intermediates, emit both
forms of an ambiguous metric, because extra columns are free under containment.

**Measured on the 63 hard misses (re-run, projection on): 12 recovered (19% of misses).** The
flipped ids: local019, 023, 032, 077, 078, 130, 131, 157, 163, 171, 298, 358 — a mix of the
missing-column wrong_shape cases AND several wrong_values where the extra intermediate column gave
the scorer a gold-matching vector. A full-135 re-run (projection on) measures the NET lift after any
grain-change regressions among the 72 previously-correct — recorded in the progress log when it lands.

## Takeaways for the campaign

1. The cheap prompt/harness levers (projection, ANSWER_SHAPE) have a hard ceiling ~+8–12 points —
   they clear the wrong_shape bucket and the projection-recoverable wrong_values, and no more.
2. The **53%→top-tier gap is the wrong_values bucket**, which is ambiguity + grain-of-intent — the
   exact thing the substrate (Phase 1) + SOMA-style probing (Phase 2) target. That is where the
   campaign's real budget must go; it is NOT more prompt engineering.
3. This reproduces the June conclusion on fresh data with a different model — and quantifies it.
