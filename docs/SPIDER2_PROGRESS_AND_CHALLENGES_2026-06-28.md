# Spider 2.0 — Aughor: What We Did, What Worked, What Remains (for second opinion)

*Date: 2026-06-28. Self-contained brief for an external reviewer. Companion to the deeper engineering
notes in `docs/SPIDER2_REATTEMPT_2026-06-28.md`. All numbers below are **measured**, not estimated,
unless explicitly flagged.*

---

## TL;DR

- **Aughor is a grounded NL2SQL + analytics product**, not a purpose-built benchmark agent. We
  re-attempted Spider 2.0 to (a) get an honest current number and (b) extract product-relevant wins.
- **Only the offline subset is runnable here.** Spider2-Snow (100% Snowflake) and ~75% of
  Spider2-Lite (BigQuery/Snowflake) cannot be executed because we have **no working cloud
  credentials**. The bundled Snowflake credential is dead (verified live). So all measured numbers
  below are on the **135 local SQLite instances of Spider2-Lite** (≈25% of the Lite track).
- **Measured progress on that slice:** `18.52%` (prior baseline, weaker model) → **`56.30%`**
  (current pipeline + `glm-5.2:cloud` + one new prompt rule). Best multi-call config `57.04%`.
- **The one durable win:** a cheap "answer-shape" prompt rule (**+8.15 pts**). Three separate pieces
  of heavier LLM machinery (self-consistency, formula grounding, faithful external-knowledge
  application) were **net-neutral to negative** on a strong model — a result we want a second opinion on.
- **"100%" is not achievable by anyone:** live leaderboard tops at **96.70** (Snow) / **73.13**
  (Lite) / **65.6** (DBT). The honest target is "match the top," which requires closed-loop agentic
  execution against the live engine — and credentials we don't have.

---

## 1. Environment reality (what is and isn't runnable)

| Track | Size | Engine | Runnable here? |
|---|---|---|---|
| Spider2-**Snow** | 547 | 100% Snowflake (cloud) | ❌ dead credentials (`250001: Incorrect username or password`, verified) |
| Spider2-**Lite** | 547 | 38% Snowflake + 37% BigQuery + **25% local SQLite** | ⚠️ only the **135 SQLite** instances run offline |
| Spider2-**DBT** | 68 | DuckDB/dbt project agent | not attempted |

- Full Spider2 repo is cloned locally (`/Users/amitkamlapure/dev/Spider2`).
- **No BigQuery credentials** either → the ~205 `bq*`/`ga*` Lite instances are also unrunnable.
- **Scoring is execution-based:** Spider's `evaluate.py --mode sql` re-executes the predicted SQL
  against the real engine and compares the result table to gold (binary 0/1, `abs_tol=1e-2`,
  honoring per-instance `condition_cols`/`ignore_order`). Generated SQL we can't execute is
  unscoreable — so the cloud tracks are fully blocked, not merely "harder."

**Consequence:** every number in this doc is on the 135 local SQLite instances. It is a legitimate
internal dev metric but is **not comparable** to the 547-instance leaderboard numbers, and the slice
is biased toward the smaller/self-contained databases (the cloud instances are the hard core —
1,000+ columns, semi-structured JSON, multi-dialect).

---

## 2. The benchmark, and the "100%" question

Spider 2.0 is an enterprise text-to-SQL benchmark (ICLR 2025). It is an **evaluation** set — no
official training split, and the maintainers **forbid training on released gold**.

Live leaderboard (pulled 2026-06-28):

| Track | #1 | Notes |
|---|---|---|
| Snow | **96.70** (Genloop Sentinel v2 Pro) | mid-80s–90s cluster, all closed-loop agents |
| Lite | **73.13** (DivSkill-SQL) | low-70s |
| DBT | **65.6** (SignalPilot) | mid-60s |

**Nobody is at 100%.** The top is 96.70 and the last few points are documented benchmark ambiguity
(the maintainers shipped two ambiguity refreshes). The defensible goal is "match the top," which is
achieved exclusively by systems that **execute candidate SQL against the live engine in a loop and
materialize results to the evaluator's exact CSV contract** — an architecture that requires the
credentials we lack.

---

## 3. Method, model, harness (reproduction)

- **Model:** `glm-5.2:cloud` (a reasoning model) as the SQL generator, via Ollama Cloud
  (`OLLAMA_BASE_URL=http://localhost:11434/v1`). Reflection/judge role used `kimi-k2.6:cloud`
  (flagged for replacement with a faster model / glm-only next time).
- **Harness:** `evals/spider2_lite.py` — generates one `<id>.sql` per instance, scores via Spider's
  official `evaluate.py`. Flags: `--consensus K`, `--reflect`, `--select`, `--explore`, `--engine`,
  `--ids`, `--score`. Schema context = DDL + FK paths (from PRAGMA) + 3 sample rows/table;
  schema-linking trims wide DBs with a full-schema fallback.
- **Scoring:** `evaluate.py --mode sql` (execution accuracy / result-table match).
- **Discipline:** flip-level regression analysis (gained/lost instance ids) on every change, since
  aggregate deltas hide churn. No training on gold; no `gold-tables` oracle.

---

## 4. Baseline + error histogram (single-shot, glm-5.2)

**Single-shot baseline: 48.15% (65/135)** (up from the prior attempt's 18.52% via the improved
current pipeline + the stronger model). Failure histogram of the 70 misses:

| Category | Count | % of misses | Meaning |
|---|---|---|---|
| **wrong_values** | 46 | 65.7% | runs, right shape, wrong numbers — logic/grain/filter/aggregation |
| **wrong_shape** | 18 | 25.7% | wrong column set vs gold (extra/missing/reordered) |
| empty_result | 3 | 4.3% | wrong filter literal |
| exec_error | 3 | 4.3% | syntax / runaway query |

By difficulty (gold-SQL tokens): easy 60% · medium 50.5% · hard 38.2%. Local-set difficulty:
gold-SQL median 143 tokens, max 1066; 13/135 ship an external-knowledge doc.

**Key targeting insight:** the closed-loop execute→repair substrate addresses only ~8.6% of misses
on SQLite (empty + exec_error). The dominant **91% is semantic correctness** (wrong_values +
wrong_shape).

---

## 5. Interventions tried — measured results

| # | Intervention | Result | Kept? |
|---|---|---|---|
| 1 | **ANSWER_SHAPE** projection rule | **+8.15 pts** (48.15→56.30) ✅ | **yes** |
| 2 | FP-aware reflection gate | revisions 37→21; +3 to the consensus config | yes (in harness) |
| 3 | consensus k=3 + reflection | 57.04% best, but only **+0.74 over single-shot+shape** at ~6× cost | not for blanket use |
| 4 | formula-intent grounding (prompt) | **net 0** (formula-only subset 15/20 → 15/20) | **removed** |
| 5 | faithful-EK application (extract→implement→verify) | **net −2** on 13 EK-doc instances (0 gained, regressed 2) | **removed** |

### 5.1 ANSWER_SHAPE (the win, +8.15)
A prompt rule appended to the product's SQL system prompt: *answer the question's implied output
shape — single-value → one scalar column; "which X" → the entity; no helper/intermediate columns.*
Causally confirmed: `wrong_shape` misses dropped 18→11; e.g. "distance of the longest route"
flipped from returning the whole row to the scalar. Flip detail: +16/−5 (occasionally over-trims a
wanted column; some churn is temp-0 cloud variance). **A single rule beat the far more expensive
consensus config**, and it is a genuine product improvement (precise answers). It works because
over-projection is a *systematic default-behavior bug* a rule can correct.

### 5.2 FP-aware reflection gate
The result-reflection pass previously adopted a revision whenever it "ran and returned rows" — too
weak; it overwrote correct queries (−5 regressions in an early run). The fixed gate only revises on
a **named concrete defect** (cardinality/grain/columns/filter), else keeps the query verbatim
(SOMA-SQL editing policy). Effect: revisions dropped 37→21 (more conservative) and lifted the
consensus config +3. Kept *if* consensus/reflect is used.

### 5.3 consensus k=3 + reflection
Self-consistency vote + reflection. Best absolute config (**57.04%**), but only **+0.74 over
single-shot+ANSWER_SHAPE** while costing ~6× the compute/time, with +10/−9 churn (largely temp-0
cloud nondeterminism). Helped *hard* (41→44%) but slightly hurt *medium*. **Conclusion: blanket
consensus is not worth it; if used at all, tier it onto hard/uncertain cases only.**

### 5.4 formula-intent grounding (removed)
A detector for parameterized analytical concepts (moving avg / percentile / RFM / running total /
growth / regression …) + a prompt block instructing the model to pin down each formula's degrees of
freedom. **Net 0** on the formula-only subset. A strong model already reasons about frames/methods,
so prompt *guidance* adds nothing. Removed.

### 5.5 faithful-EK application (removed)
For questions shipping an external-knowledge doc that defines a formula (e.g. RFM.md), a specialized
loop: **extract** the doc's exact spec → **generate** SQL conditioned on it → **verify** coverage →
repair once. It *provably improved fidelity* (added the missing `NTILE(5)` on local003, the full
haversine on local010). But on the 13 EK-doc instances it scored **5/13, net −2** (0 gained,
regressed 2 previously-correct queries). The extract→verify→regenerate loop overwrote correct
queries more than it fixed wrong ones. Removed (kept only as this written record).

---

## 6. The meta-pattern (the headline finding — please scrutinize)

With a **strong** model (`glm-5.2`), across four increments, **only the cheap rule that corrects a
systematic behavioral default helped.** Every piece of added *LLM machinery* (self-consistency,
spec-extract-verify, formula grounding) was net-neutral-to-negative — it overwrites already-correct
queries about as often as it fixes wrong ones.

This matches the published SOMA-SQL / ReFoRCE finding that such machinery (gold examples, probing,
multi-candidate selection) **helps weak models but barely helps — or hurts — strong models**. We
observed it three independent times on our own data.

**Implication we drew:** the offline-SQLite slice is at its ceiling for this model class via
prompt/machinery engineering. Remaining gains require a *different lever*: a stronger base model, or
the cloud tracks (credentials), not more machinery on this slice.

> **This is the central claim we want a second opinion on.** Is it a correct generalization, or an
> artifact of (a) small n (135), (b) temp-0 cloud nondeterminism inflating "no-effect" reads, (c)
> our specific implementations of the machinery being weak, or (d) the SQLite slice being too easy
> to show machinery's value (which shines on the hard cloud cases)?

---

## 7. Reusable substrate built (kept, committed)

These are product-relevant and serve the cloud tracks once unblocked (committed in `e614acf`):

- **`aughor/sql/closed_loop.py`** — backend-agnostic execute→observe→repair loop + evaluator-faithful
  `rows_to_csv` (real NULL→empty cell, cursor column order, no row cap). Fixes the output-contract
  gaps (`"NULL"` stringification, `MAX_ROWS=2000` truncation) that would zero a correct query.
- **Dialect-aware repair** (`writer._make_diagnosis`) — DuckDB-only function advice
  (`datediff`/`strftime`/`epoch_days`) is now gated to DuckDB; a Snowflake branch added; no longer
  mis-removes valid Snowflake `TIMESTAMPDIFF`.
- **Snowflake dialect rules** — added `QUALIFY` / `LATERAL FLATTEN` / `VARIANT` `:`-path / `ILIKE` /
  `ARRAY_AGG`.
- **`SnowflakeConnection.export_csv`** — raw cursor, no cap, `STATEMENT_TIMEOUT`, matching the
  evaluator's CSV contract.
- **ANSWER_SHAPE rule** (§5.1) in the product prompt.

All additive; 1878 unit tests green; zero net "silent-swallow" ratchet debt.

---

## 8. Prior art studied (and how it shaped the work)

- **SOMA-SQL** (Oracle AI, arXiv 2606.11424; #2 on live Spider2-Lite, 72.02): reframes formula/metric
  failures as **ambiguity** — resolve via candidate-disagreement detection + execution-grounded
  probing + minimal repair. Source of the projection-minimality rule (ANSWER_SHAPE) and the FP-aware
  reflection/critique gate.
- **ReFoRCE** (Snowflake AI, arXiv 2502.00675): DB-info **compression** (table grouping for wide
  schemas, its #1 ablation lever), self-refinement, majority-vote with **deferral**, and
  **confidence-tiered column exploration** (probe only the hard ~100/547 cases — keeps cost down).
- **OmniSQL / SynSQL-2.5M** (arXiv 2503.02240): a 2.5M-example synthetic, Apache-2.0 training corpus
  — the legitimate way to *fine-tune our own small model* (a path we have not taken; see §9).

Net: the **techniques are sound for the cloud tracks** (compression for 1,000-col schemas, tiered
probing for the hard cases), but our offline-slice experiments suggest they pay off mainly with
weaker models or on the harder cloud distribution.

---

## 9. What remains a challenge (active blockers to higher numbers)

1. **The high-ceiling tracks are unrunnable.** Dead Snowflake creds + no BigQuery creds → 100% of
   Snow and ~75% of Lite cannot be executed/scored. We are capped to the 135-instance SQLite slice.
   *This is the #1 blocker and it is not an engineering problem — it needs credentials.*
2. **Base-model ceiling on hard reasoning.** `glm-5.2` plateaus on genuinely hard multi-step cases
   (RFM segment-mapping tables, multi-step inventory logic, seasonality forecasts). We proved (3×)
   that added LLM machinery doesn't lift a strong model — so these need a *stronger/frontier base
   model*, a swap not available on the current cloud-API setup.
3. **Remaining offline misses are at the hard/ambiguous edge.** ~70% are `wrong_values`
   (formula/grain/multi-step) needing real reasoning depth, plus some under-specified gold; binary
   exact-match gives no partial credit (faithful-EK got cases *close* and still scored 0).
4. **Measurement noise.** `glm-5.2:cloud` at temp 0 is non-deterministic, so small real gains are
   swamped by ±flip churn — hard to detect/attribute at n=135, worse on tiny slices. (We mitigate
   with per-instance flip analysis, but it limits confidence in sub-+2-pt effects.)
5. **Operational fragility.** The cloud endpoint throttles/hangs after sustained load (~2.5h); no
   retry/backoff or per-endpoint concurrency cap. Limits reliable full-set runs and iteration speed.
6. **No fine-tuning lever.** We use cloud-API models we can't fine-tune; the proven "small model +
   agentic workflow" path (OmniSQL/Arctic-Text2SQL) needs local GPU infrastructure we don't have.
7. **Latent (activates the moment Snow is reachable):** semi-structured handling
   (`VARIANT`/`FLATTEN`/`QUALIFY`), 1,000+-column schema-linking, and DB-info compression are built
   as dialect rules but **never tested live** — untested risk, not yet a measured number.

---

## 10. Deliberately NOT done (integrity guardrails)

- No training/SFT on Spider2 released gold (maintainer rule).
- No `gold-tables` oracle (excluded from official ranking).
- No tuning of prompts to make specific released-gold instances pass (overfitting to a 135-instance
  slice with visible gold would be meaningless).

---

## 11. Where a second opinion is most valuable

1. **Is the "machinery doesn't help strong models" conclusion sound**, or an artifact of small n /
   temp-0 cloud variance / our specific implementations / the easy SQLite slice? Would it reverse on
   the hard cloud distribution?
2. **Is "stronger base model" really the only offline lever left**, or is there a class of
   engineering (e.g. genuine execution-grounded *data* probing à la ReFoRCE column exploration, done
   right) that we under-implemented and dismissed too early?
3. **Given no fine-tuning infra**, is it worth standing up local GPUs to distill a SynSQL/Arctic-style
   7B + agentic workflow, vs. simply paying for a frontier API model under the same harness?
4. **For the cloud tracks (once creds land):** is our planned approach (closed-loop execute→repair→CSV
   + dialect rules + ReFoRCE compression + tiered probing) the right priority order, or is something
   missing?
5. **Measurement:** what's the right protocol to detect sub-2-pt real gains under cloud
   nondeterminism (n, repetitions, seeds, held-out split) without burning excessive budget?

---

*Commits of record: `e614acf` (ANSWER_SHAPE + reusable substrate — the kept wins), `9e15d78`
(removal of non-helping increments + this negative-results record). Branch:
`2026-06-28-spider2-lite-substrate` (not merged).*
