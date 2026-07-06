# Spider 2.0 campaign — Phase-0 fail-analysis + the first cheap lever

*2026-07-06 (WS5, branch `2026-07-06-10x-program`). Offline analysis of the full 135-instance
Spider2-Lite local run (`evals/spider2_out`, product prompt on **`glm-5.2:cloud`** — the runtime
inference-plane config pins coder=glm-5.2, overriding the `.env` default; same model class as June), plus
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

## First lever measured — containment-aware projection (finding #2): NET-NEGATIVE, discarded

Added `_BENCH_PROJECTION` to `evals/spider2.py` (opt-in `--bench-projection`, default OFF): counters
the product ANSWER_SHAPE trim — keep grouping keys + intermediates, emit both forms of an ambiguous
metric, because extra columns are free under containment.

**The honest measurement arc (a lesson in controlled evaluation):**
- Misses-only re-run (63 misses, projection on): **12 recovered** — looked like a clear +12 win.
- **Controlled same-instance comparison** (the 62 instances of a full re-run that completed before
  the throttled endpoint stalled, projection-on vs the original projection-off): **31 correct vs 33
  — NET −2** (5 recovered: local008/017/032/077/298; **7 regressed: local002/009/030/050/063/096/198**).

The +12 was a **measurement artifact**: a misses-only re-run can only *observe* recoveries — it is
structurally blind to the regressions the directive causes on previously-correct queries (it
restructures their grain), and temp-0 cloud nondeterminism inflated the apparent gain. The
controlled view shows the recoveries are offset by regressions — within the range temp-0 noise
alone could explain. **This reproduces the June meta-pattern precisely: added machinery (even a
prompt directive) perturbs already-correct queries about as often as it fixes wrong ones on a
strong model.** The lever is kept only as an ablation switch + this recorded negative result.

*Measurement lesson (→ AGENT_NOTES): never measure a lever on the failing subset alone — it cannot
see regressions. Always compare the SAME instances on/off, and separate the effect from temp-0
cloud noise before believing a sub-single-digit delta.*

## Per-question loop (throttled-endpoint mode) — root-cause taxonomy of the 63 misses

Tooling: `evals/spider2_diag.py` (`show <id>` full offline diagnostic + official per-question
score · `run <id>` re-run one instance + score · `triage` compact root-cause hint for all misses).
Compact triage of the 63 misses:

| Root cause | Count | Nature |
|---|---|---|
| **VALUES** (logic / column-choice / computation) | 36 (57%) | same shape, wrong numbers — genuine SQL reasoning |
| **ROWCOUNT** (grain) | 11 (17%) | aggregation level / "for each X" misread |
| **MISSING-COL** | 10 (16%) | gold keeps an intermediate/grouping column (the net-negative projection target) |
| **EMPTY** (filter / join / date-column) | 6 (10%) | wrong filter literal or wrong date column (`db_year` vs `collision_date`) |

## Column-semantics lever — built, tested per-question, NOT a clean win

Hypothesis from inspection: many VALUES/EMPTY misses are COLUMN-CHOICE errors (the model picks the
wrong column because it sees only DDL + 3 sample rows). Built `column_semantics_section`
(`evals/spider2.py`, opt-in `--col-semantics`): enumerates distinct values for low-cardinality text
columns + tags date columns — Aughor's data-portrait signal, harness-side, general (no per-question
tuning). Tested per-question:
- **local017** (empty, cause-category + date): still failed — a multi-factor hard case (complex
  top-2-per-year logic + wrong output shape), not a clean column-choice isolate.
- **local015** (value-label): still failed — but the gold ships **5 accepted label conventions**
  (`helmet_worn` / `helmet` / `Helmet Used` / …) and our answer is numerically correct (16.67% / 0%);
  the label formatting matched none. A benchmark *annotation* limitation the lever can't fix.

Neither flipped. The lever is kept opt-in + unproven (needs a controlled full-set A/B — not
affordable on the throttled endpoint). The per-question loop reconfirmed, case by case, that the
misses are genuine reasoning / grain-of-intent ambiguity / annotation issues — NOT mechanically
fixable by prompt/schema enrichment.

## The deep recheck (2026-07-06, second pass) — three harness gaps + measured fixes

A re-audit against "what else besides a better endpoint" found three VERIFIED gaps in the
rebuilt harness itself: **(A1)** the June-built `recover_empty_fn` was never wired into the
closed loop; **(A2)** the schema context carried NO PK/FK information (June's 56.3% context
had "DDL + FK paths from PRAGMA" — the model was guessing join paths blind); **(A3)**
generation reused the product's multi-field answer model + 6.6k-char chart rulebook
(headline/chart output tax). All three fixed; plus two new levers built and unit-tested:
**Lever 7** — a deterministic grain-of-intent check (`aughor/sql/grain_intent.py`: "top
three X"/"which single Y"/"for each Z" vs the observed rowcount → one diagnosis-fed repair
round); **Levers 4+5** — strategy-diverse candidates (direct · decompose · plan-first ·
adversarial-self-check) + execution-signature plurality selection (`--candidates K`).

**A1–A3 controlled verification (18 instances: 10 misses + 8 correct sentinels):**
- **Sentinels 8/8 stayed correct — zero regressions** (the first monotonic lever measured;
  contrast the projection directive's 7 regressions).
- **Misses 1/10 recovered** (local354 — the empty-recovery loop fired end-to-end). Trace
  detail: recovery also fired on local299 (0→3 rows, values still wrong), and A2/A3 alone
  converted local018/344/360 from empty to row-returning (still wrong values) — the empty
  bucket dissolves from two directions; local017 resisted (no row-returning rewrite found).

Net: **+1 recovered, −0 regressed** — foundation restored (June-parity context), not a
needle-mover; consistent with the diagnosis that the remaining misses are reasoning/
ambiguity. The candidates lever (the oracle-gap play) is the next controlled measurement.

## Takeaways for the campaign

1. **The cheap prompt/harness levers do NOT move the net score.** The one tested (projection) was
   net −2 under controlled measurement. ANSWER_SHAPE stays (June proved it; it's product-good) but a
   *more* aggressive projection directive regresses as much as it recovers. Prompt engineering is
   exhausted on this model — the June conclusion, re-confirmed and quantified on fresh data.
2. The **53%→top-tier gap is the wrong_values bucket** (grain-of-intent ambiguity), which needs
   EXECUTION-GROUNDED work, not prompting: the substrate (Phase 1 — resolve the metric/grain/value
   domain from the DB) + SOMA-style disagreement probing (Phase 2 — generate candidate readings,
   execute them, resolve only where they diverge). That is the only lever the evidence supports, and
   where the campaign budget must go.
3. **Operational blocker surfaced:** the Ollama Cloud endpoint throttles hard under sustained load —
   after three back-to-back 60–135-instance runs it crawled to ~5 instances/hour, stalling the full
   controlled re-run at 62/135. A campaign at Phase-1/2 budgets (dozens of calls/question) needs
   either a faster/dedicated endpoint or the confidence-tiered triggering (probe only the hard cases)
   the study already flagged. Iterate on the hard subset; full runs sparingly.
