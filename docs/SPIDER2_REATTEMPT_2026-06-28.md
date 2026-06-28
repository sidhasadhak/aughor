# Spider 2.0 — Aughor re-attempt & brutally-honest path-to-top assessment

*Date: 2026-06-28. Author: engineering pass on branch `2026-06-28-spider2-lite-substrate`.
Supersedes the architecture-only `SPIDER2_SNOW_ASSESSMENT.md` (external agent, never run live)
by (a) verifying its claims against current `main` and (b) replacing its estimates with a real
measured run on the only track runnable offline today.*

---

## 0. The headline you need to hear first: "100%" is not a real target

I pulled the **live** leaderboard (`spider2-sql.github.io`) on 2026-06-28:

| Track | Examples | Current #1 | Honest ceiling |
|---|---|---|---|
| Spider2-**Snow** | 547 | **96.70** (Genloop Sentinel v2 Pro) | mid-90s, all closed-loop agents |
| Spider2-**Lite** | 547 | **73.13** (DivSkill-SQL) | low-70s |
| Spider2-**DBT** | 67 | **65.6** (SignalPilot) | mid-60s |

**Nobody is at 100% on any track.** The top is 96.70 on Snow, and the last ~3 points are
benchmark noise — the maintainers have already shipped *two* ambiguity refreshes because some
gold queries are genuinely under-specified. Chasing "a tidy 100%" means fighting that noise and,
in practice, overfitting to released gold (which the maintainers explicitly forbid) or using the
`gold-tables` oracle (excluded from the official ranking). **The honest, defensible goal is
"match/beat the top of the leaderboard," not 100%.**

> Note on a stale number: a first web search returned ReFoRCE ~31% as "SOTA." That was the
> *early-2025* paper SOTA. The leaderboard has since climbed ~65 points via closed-loop agentic
> systems. The mid-90s figure in the external assessment is **correct** against today's board.

One more honest flag: the Snow #1 (96.7) is *higher* than the Lite #1 (73.1) for the **same 547
questions**. That inversion suggests the very top Snow numbers come from heavy engineering against
the Snow harness's execution loop, not generally-smarter SQL. Treat 96.7 as "what a maximally
tuned closed-loop agent reaches," not "what good NL2SQL reaches."

---

## 1. The harder blocker: the target track cannot be run right now

Verified end-to-end in this environment:

- The full Spider2 repo **is** cloned at `/Users/amitkamlapure/dev/Spider2` (snow/lite/dbt, all
  547+547+67 examples, per-DB documents).
- **The Snowflake credentials are DEAD.** Installed the driver, tested the live connection:
  `250001 (08001): Incorrect username or password`. **Spider2-Snow is 100% Snowflake-hosted —
  nothing runs offline — so the entire track the external assessment targets is blocked until
  fresh credentials are obtained** (request form in the Spider2 README).
- **No BigQuery credentials**, so the ~400 `bq*`/`ga*` Lite instances are also blocked.
- **The only thing runnable offline is the 135 local SQLite instances of Spider2-Lite** (all 30
  required DB files present, confirmed). This is the subset the prior attempt scored 18.52% EX on
  (that was the *initial* single-shot baseline; the branch later reached ~28%).

Decision taken with the user: **skip Snow for now**, re-measure Lite-local with the current
pipeline + a stronger model (`glm-5.2:cloud`), and build the reusable substrate that also serves
Snow once credentials land.

---

## 2. The external assessment is accurate — verified line-by-line against `main`

It admitted it was architecture-derived and never executed, so every claim was re-checked:

| Claim | Verdict | Evidence on current `main` |
|---|---|---|
| `MAX_ROWS = 2000` hard truncation | ✅ true | `snowflake.py:17` |
| NULL stringified as literal `"NULL"` (≠ pandas `NaN`) | ✅ true | `snowflake.py:66` |
| `dry_run` = `EXPLAIN` only — never executes | ✅ true | `snowflake.py:79-85` |
| `get_schema` returns only (table, col, type) — no FKs/comments/samples | ✅ true | `snowflake.py:87-107` |
| No CSV materialization matching the evaluator contract | ✅ true | no `to_csv(index=False)` path anywhere in the connector |
| Snowflake dialect rules silent on QUALIFY/FLATTEN/VARIANT/ILIKE/ARRAY_AGG | ✅ true | `dialects.py:57-65` (6 terse lines) |
| `_make_diagnosis` is DuckDB-rewired; tries to *remove* `TIMESTAMPDIFF` (valid on Snowflake) | ✅ true | `writer.py:121-304` |

**Where it under-states the problem:** it frames these as separate bugs. They are one thing —
**the production path validates that SQL *binds* (`preflight_repair` → `dry_run`/EXPLAIN) but never
closes the loop on the actual *result*.** There is no execute→observe→repair cycle in the product
(`safety.py:31-89`). That single architectural fact, not the model, is the gap to the leaderboard.

**Where it is now partly moot:** for the *runnable* (SQLite) track, the eval harness
(`evals/spider2_lite.py`) already implements the closed loop the assessment calls "intervention
#1" — execute-and-retry, consensus-by-execution, reflection on the result preview, empty-recovery,
a deterministic composite-key fan-out guard, and diverse generation strategies (direct / decompose
/ plan). So "intervention #1" exists *for SQLite, in the harness*. What's missing is the same loop
as a **first-class, dialect-agnostic capability in the Aughor product** (and the Snowflake variant,
which is blocked).

---

## 3. Measured results (real, this run)

Model: `glm-5.2:cloud` (a reasoning model) as coder; `kimi-k2.6:cloud` as the reflection/judge.
Track: Spider2-Lite **local/SQLite, 135 instances**, scored with Spider's official `evaluate.py`
(`--mode sql`, execution-accuracy / result-table match).

Local-set difficulty (for context): gold-SQL token length median **143**, mean 184, **max 1066**;
34 hard / 91 medium / 10 easy; 13/135 require an external-knowledge doc.

| Config | EX | Notes |
|---|---|---|
| **Single-shot** (1 gen + 1 error-repair) | **48.15%** (65/135) | raw model + minimal repair |
| **Single-shot + ANSWER_SHAPE rule** | **56.30%** (76/135) | projection-minimality (SOMA G.1) — **+8.15 pts over single-shot**, beats the old consensus config |
| consensus k=3 + reflection (pre-fix) | 54.81% (74/135) | self-consistency vote + weak reflection gate (−5 reflect regressions) |
| **consensus k=3 + reflection + both fixes** | **57.04% (77/135)** | ANSWER_SHAPE + FP-aware reflection gate — best, but only **+0.74 over single-shot+shape** |

**The verdict on where to spend compute (the important finding):** the FP-aware reflection gate
worked — revisions dropped 37→21 (more conservative, keeps the original more often) and lifted the
consensus config +3 over the pre-fix version (54.81→57.04). BUT consensus k=3 + reflect adds only
**+0.74 net over single-shot + ANSWER_SHAPE** (76→77) while costing **~6× the compute/time** and
churning +10/−9 instances (≈ glm-5.2 temp-0 cloud nondeterminism + voting instability). By
difficulty the consensus helped *hard* (41.2→44.1%) but slightly hurt *medium* (61.5→60.4%) — a
wash on the easy majority. **Conclusion: ANSWER_SHAPE is the keeper (cheap, +8 pts, product-good);
blanket consensus+reflect is NOT worth it.** This empirically confirms the ReFoRCE confidence-tiered
lesson — reserve the expensive path (consensus + SOMA/ReFoRCE probing) for the *hard/uncertain*
cases only, not every query.

**ANSWER_SHAPE win (measured):** adding the projection-minimality rule to `CHAT_SQL_SYSTEM` lifted
single-shot 48.15%→**56.30%** (+8.15 pts). Causally confirmed: `wrong_shape` misses dropped 18→11
(its exact target), e.g. `local009` "distance of the longest route" flipped to PASS (was returning
the whole row). Flip detail: +16 / −5 (the rule occasionally over-trims a wanted column; some churn
is temp-0 cloud nondeterminism). A single prompt rule beat the old, far more expensive consensus+
reflect config — the cheapest, highest-leverage win in this whole effort, and it helps the product
(precise answers) as much as the benchmark.

Prior reference: 18.52% (initial single-shot, weaker model) → ~28% (branch best, mid-2026). The
jump to **48.15%** is the combined effect of current-`main` pipeline + the `glm-5.2` reasoning
model + the harness scaffolding (FK+sample schema, schema-linking, composite-key fan-out guard).
This is the local/SQLite subset only — not directly comparable to the all-547 Lite leaderboard
(73.13 top), which mixes BigQuery + Snowflake + SQLite instances.

**Honest flip detail (regression ratchet):** consensus+reflect gained **+14** and lost **−5**
(net +9). It is *not* strictly dominant — the 5 regressions are the known self-consistency variance:
the majority vote can settle on a wrong-but-agreeing candidate, and the reflection pass's
adopt-if-it-runs-and-returns-rows gate is weak enough to occasionally overwrite a correct query.
A stronger reflection gate (revise only when the original has a *detected* cardinality/shape
mismatch) would cut the regressions — a concrete next step. The improved-run histogram (61 misses):
wrong_values 37 (60.7%) · wrong_shape **20** (32.8%) · exec_error 3 · empty_result 1 — note
wrong_shape went 18→20, confirming reflection's column-check did NOT reliably fix over-projection.

**Run-reliability caveat:** the full 135-run against `glm-5.2:cloud` **throttled and hung after
~2.5h**; 7 tail instances had to be retried after the endpoint recovered. Operational hardening
(retry/backoff, per-endpoint concurrency cap) is required before any unattended full-suite run, and
consensus+reflect is far slower (~2.5h vs ~25 min single-shot) for a +6.66 pt gain — a real
cost/accuracy trade.

### Failure histogram (real, single-shot run, 70 misses)

| Category | Count | % of misses | Meaning |
|---|---|---|---|
| **wrong_values** | 46 | 65.7% | Runs, right shape, wrong numbers — logic/grain/filter/aggregation |
| **wrong_shape** | 18 | 25.7% | Wrong column set vs gold (extra/missing/reordered) |
| empty_result | 3 | 4.3% | Wrong filter literal |
| exec_error | 3 | 4.3% | Syntax / runaway (cartesian) query |

EX by difficulty (gold-SQL toks): easy 60% (6/10) · medium 50.5% (46/91) · hard 38.2% (13/34).

**`wrong_shape` is mostly over-projection, not bad reasoning.** Inspecting these failures: the model
returns the right values *plus extra context columns* gold doesn't want — e.g. gold wants
`[LONGEST_DISTANCE_KM]` (one scalar) but pred returns `[dep_city, arr_city, distance]`; gold wants
`[Salesperson, Year, Difference]` but pred adds `total_sales, sales_quota` (genuinely useful, scored
0). With `condition_cols=[]` the evaluator demands the exact column set, so extra columns fail. This
is **benchmark conformance**, not a SQL error — it's the reflection pass's column-check lever, and it
is also part of why a "tidy 100%" partly means gaming column projection to match gold exactly rather
than answering well.

**The decisive finding:** the closed-loop execute→repair substrate (the external assessment's
"intervention #1") attacks only the bottom **~8.6%** of misses on SQLite (empty + exec_error). The
dominant **91.4% is semantic correctness** (wrong_values + wrong_shape) — addressed by
self-consistency, grounding (explore), and result-reflection, all of which already exist in the
harness. On the runnable track, *correctness-of-reasoning*, not the execution substrate, is the
gap. The substrate's value is for Snowflake/the product (output contract + native repair), where
it is structurally required.

---

## 4. What is genuinely missing in Aughor to compete (ranked by leverage)

Not "to hit 100%" (impossible) — to reach the top tier.

1. **A first-class, dialect-agnostic closed loop in the product**: execute → observe result →
   repair-on-error → recover-on-empty → (optional) validate-shape. Today this lives only in the
   eval harness for SQLite. Lifting it into the connector/answer path is the highest-leverage,
   most reusable change, and it is what every top-of-board system has.
2. **Output-contract conformance as a product capability**: a real `export_csv(sql, path)` on the
   connector base — column order from the cursor, real NULLs, no row cap, dtype-stable — matching
   `pd.DataFrame(...).to_csv(index=False)`. A correct query scores 0 without this.
3. **Schema linking that scales to 1k–3k-column warehouses**: embeddings + the *provided per-DB
   docs* (currently never read) + FK/sample/`COMMENT` enrichment, with adaptive top-k and a
   full-schema fallback. Today it's keyword morphology with an e-commerce fallback dict and
   `top_k_cols=8`.
4. **Snowflake-aware dialect + repair catalog** (QUALIFY / LATERAL FLATTEN / VARIANT `:`-path /
   ILIKE / ARRAY_AGG), gated on `dialect == "snowflake"`, and *stop* the DuckDB mis-corrections.
   Cheap, low-risk, testable without Snowflake — but only pays off once Snow is unblocked.
5. **Decomposition + self-consistency on the product path** for the 100+-line nested-CTE gold
   queries (the harness has it; the product does not).
6. **Operational hardening**: retry/backoff on queue throttle, statement timeout, connection pool.

---

## 5. This session's build (reusable substrate, validated on Lite-local)

Built on branch `2026-06-28-spider2-lite-substrate` (additive; no behavior change to existing
modes; 14 new unit tests + 222 in the broad SQL/connector sweep all green):

1. **`aughor/sql/closed_loop.py`** — the reusable, *backend-agnostic* execute→observe→repair loop
   as a product primitive (it takes plain callables, so the same code drives SQLite, Snowflake,
   BigQuery, or the eval harness). `execute_with_repair` does real execution, repairs from the
   *actual* error, recovers empty results, and adopts a rewrite only if it executes (correct-but-
   never-regress). `rows_to_csv` is the output-contract conformance: real `None` → empty cell
   (never the literal `"NULL"`), column order from the cursor, **no row cap** — byte-compatible
   with the evaluator's `pd.DataFrame(...).to_csv(index=False)`.
2. **Dialect-aware repair (`writer._make_diagnosis`)** — the DuckDB function-substitution advice
   (`datediff`/`strftime`/`epoch_days`) now fires **only** on `dialect == "duckdb"`. On Snowflake
   it no longer tells the model to remove `TIMESTAMPDIFF`/`TO_CHAR` (both valid there); a Snowflake
   branch handles `invalid identifier` / `unsupported` compilation errors with VARIANT/FLATTEN/
   QUALIFY guidance. The universal branches (binder, ambiguous, GROUP BY) stay dialect-agnostic.
3. **Snowflake dialect rules (`db/dialects.py`)** — added QUALIFY (window filter), LATERAL FLATTEN
   + VARIANT `:`-path, ILIKE, ARRAY_AGG, and an explicit "keep TIMESTAMPDIFF" note.
4. **`SnowflakeConnection.export_csv`** — a CSV path that writes the *raw* cursor (real NULLs, no
   2000-row cap, `STATEMENT_TIMEOUT` set) via `rows_to_csv`. Additive — the UI `execute()` path is
   untouched.

**Validated on Lite-local (real SQLite connection):** `execute_with_repair` repaired a real broken
query (`CustomerIDX` → `CustomerID`) in one round and executed it; `rows_to_csv` exported a real
result with `None` rendered as an empty cell and zero `"NULL"` strings.

**Honest scope note:** on the *runnable* (SQLite) track this substrate moves ~8.6% of misses at
most (the histogram above) — its real payoff is Snowflake and the product, which are structurally
blocked from scoring without it. The needle-mover for Lite-local is the consensus+reflection config
(Section 3), which targets the 91% semantic-correctness bucket.

---

## 6. Anti-overfitting protocol (kept honest)

- Held-out discipline: tune on a small dev slice, report the rest.
- Regression ratchet: record passing instance_ids before each change; any pass→fail flip must be
  explained before merge.
- No SFT on released gold; no `gold-tables` oracle in any number claimed publicly.
- Pin the eval-suite commit SHA for any reported score (the suite has changed twice).

---

## 7. The path to the dominant failure bucket — ambiguity, not SQL skill (SOMA-SQL)

The 60–66% `wrong_values` bucket is the formula/metric core (moving average, percentile, RFM,
regression, running balance). Studying **SOMA-SQL** (Oracle AI, arXiv 2606.11424 — *current #2 on the
live Spider2-Lite leaderboard at 72.02*) confirms these are **ambiguity** failures, not SQL-writing
failures: the model writes *a* plausible formula, not *the* intended one. Their result is the proof
this is the lever — Spider2-Lite: majority-vote 41.1 → judge 46.1 → **judge + ambiguity-probing 61.0**;
hardest instances (our exact bucket): never-correct 0/10 → **30.6%** with probing (82 cases recovered).

**General mechanism (transferable to live DBs, where it matters MORE — no gold exists, so the system
must resolve ambiguity by construction or silently ship a wrong number):**
1. Generate K diverse candidates; **mine their disagreement** to detect the ambiguous dimension
   (window frame? percentile method? grain?) — don't just vote.
2. **Taxonomy-induced probing** surfaces alternatives even when all candidates *agree* — catches the
   convergent default error (all pick a trailing window) that voting can never catch.
3. **Execution-grounded probing**: run small probes against the data to gather evidence, resolve from
   evidence + query-log/business memory.
4. **Minimal, evidence-backed repair** of a seed query.

**Aughor already has the pieces — this is wiring, not new machinery:** probing = `sql_explore.py` (fix
its "observation ≠ action" gap: tie each probe to a *named* dimension and *apply* the resolution);
disagreement = `sql_consensus.py`; resolution memory = trusted-queries / Finding Dossier / Domain
Expertise Packs; metric-definition resolver = metrics catalog / semantic ontology; minimal critique =
`safety.preflight_repair` + reflection pass.

**Two free wins (adopt first — fix this run's histogram directly):**
- **Projection Minimality (Strict)** generation rule (paper G.1): return only explicitly requested
  fields in exact order; single-value question → one scalar column; no helper/intermediate columns →
  attacks the 26% `wrong_shape` over-projection.
- **False-positive-aware critique gate** (paper G.4): edit only on a concrete localizable defect, else
  output the original verbatim → eliminates the −5 reflection regressions (reflection becomes strictly
  additive).

**Cost discipline:** the full SOMA loop is K=10 candidates + 8–9 probes/instance — heavy (our k=3 run
already throttled `glm-5.2:cloud` and hung at 2.5h). Adoption order: the two free prompt wins first,
then ambiguity-probing **scoped to formula/metric questions only** (detect a named analytical concept
with degrees of freedom → probe just that dimension), not on every query.
