# The 10x + Spider 2.0 Program — scope, evidence, session guide

*Written 2026-07-06 after a full-repo assessment (four parallel code surveys, all claims re-verified
against code) + a deep external study of the Spider 2.0 benchmark and its July-2026 leaderboard
winners. This is the working spec for the upcoming sessions: baseline numbers to measure against,
per-workstream scope with file:line anchors, the Spider 2.0 campaign runbook, and the sequencing.
Companion prior art: [`SPIDER2_PROGRESS_AND_CHALLENGES_2026-06-28.md`](SPIDER2_PROGRESS_AND_CHALLENGES_2026-06-28.md)
(the concluded June campaign — read §14 before touching anything benchmark-related),
[`SPIDER2_REATTEMPT_2026-06-28.md`](SPIDER2_REATTEMPT_2026-06-28.md), [`NL2SQL_WINNING_FORMULA_2026.md`](NL2SQL_WINNING_FORMULA_2026.md).*

**Standing constraints (apply to every workstream):**
1. Don't break the public API (additive routes/flags only).
2. Test suite green at every commit (`uv run pytest -q -m "not e2e and not eval"`).
3. No new runtime dependencies without flagging it first.
4. New behavior ships flag-gated, default-off/byte-identical, then flips via the ledger override (repo convention).
5. Ratchets (silent-swallow / private-import / web gates) only go down.
6. **Never send the Spider2 submission email (or any outward submission) without explicit user permission — draft + show only.**

---

## 0. Baseline (main @ `7d13abe`, measured 2026-07-05 — deltas report against this)

| Metric | Value |
|---|---|
| Full suite | **2,508 passed, 1 skipped, 6 deselected in 97s** (green) |
| Ruff | 0 findings (blocking in CI) |
| Web `tsc --noEmit` | 3.1s clean; 4 blocking web gates (tokens · format · elements · tsc) |
| LOC | backend 82,135 py · web 43,546 ts/tsx (excl. api.gen.ts) · tests 29,281 |
| Ratchet baselines | silent swallows **263** · private imports **22** (`tests/unit/test_kernel_contracts.py:22-23`, both GREEN) |
| Accuracy eval in CI | **none** (harness exists in `evals/`, unwired) |
| Deep-investigation wall-clock | ~8.4 min (womenswear case), dominated by 7–12 *serial* LLM calls |
| Spider2-Lite (135-SQLite slice, glm-5.2, June) | **56.30%** single-shot+ANSWER_SHAPE; oracle ~67% on toughest 15 |
| Churn (6 wk, commits touching) | `explorer/agent.py` 111 · `routers/investigations.py` 95 · `agent/investigate.py` 71 |

**Docs-vs-code drift found (fix in WS4):**
- `web/lib/api.gen.ts` = 12,929 lines, missing the `/rbac`, `/jobs`, `/packs`, `/verify` route
  families entirely; `npm run gen:api` exists (`web/package.json`) but is not a CI gate.
- `FEATURES.md` §13 still claims "the Spider 2.0 NL2SQL harness" in the eval suite — it was
  deliberately removed in the 2026-06-29 consolidation. Fix the doc; do NOT rebuild the old harness
  as-was (WS5 rebuilds a new one deliberately).
- Four flags bypass `kernel/flags.py` (read `os.environ` directly, so no ledger override and no
  Settings-UI toggle): `AUGHOR_CAUSAL_DRILL`, `AUGHOR_PREMISE_CHECK`, `AUGHOR_ASK_CLARIFY`,
  `AUGHOR_CLOSED_LOOP`.

**Claims investigated and REFUTED (do not re-report in future sessions):**
- "Dead feature flags" — false. All four suspects are wired: `capability.pipeline_live`
  ([routers/query.py:512](../aughor/routers/query.py)), `trust.verify_facade` (query.py:458),
  `semantic.contract_live` ([semantic/canonical.py:275](../aughor/semantic/canonical.py)),
  `explorer.synthesis_incremental` ([explorer/agent.py:3621](../aughor/explorer/agent.py)).
- "Silent-swallow ratchet RED on main" — false; 4/4 contract tests pass at baseline 263/22.
- The old memory note "2 TestRatchets RED on main" — stale, corrected 2026-07-05.

---

## 1. WS1 — Fast deep path (performance; biggest latency lever)

**Thesis (verified):** on `/investigate` the SQL already runs in parallel
(`_parallel_execute_safe`, cap 4); wall-clock is the *serial chain of per-phase LLM calls*
(intake → baseline → decompose → dimensional → behavioral → cross-section → synthesis, each a
plan-LLM → SQL → interpret-LLM loop that blocks the next phase). The wave executor is already
built and proven (explore waves 1.5×, PR #109; `ada.parallel_lenses`).

Scope, in order:
1. **P-A continuation — wave-parallelize the ADA phase flow** (`aughor/agent/investigate.py`;
   phase entry points ~2179 intake / ~2781 baseline / ~3048 decompose / ~3145 dimensional /
   ~3251 behavioral / ~4715 multilens). Independent phases run concurrently through
   `ContextThreadPoolExecutor` (NOT LangGraph `Send` — Send drops metering/budget contextvars,
   proven 2026-07-02). Synthesis stays last (true dependency). Flag: extend `explore.parallel_subq`
   pattern with a new `ada.parallel_phases` flag, default off.
2. **P-B — parallelize the deep path's pre-flight retrievals.** The quick path already
   `asyncio.gather`s 8 concurrent fetches ([routers/investigations.py:989-1000](../aughor/routers/investigations.py));
   the deep intake does its consultations serially. Near-free, deterministic.
3. **Caching:** memoize `unified_metric_grounding` output by (connection_id, schema-fingerprint,
   scope_schema) ~10-min TTL; pre-load/cache `load_latest_ontology` per connection; consider KB
   embedding cache keyed by (question-fingerprint, KB version). All invalidate on mutation.
4. **LLM concurrency cap:** default 4 per endpoint ([llm/provider.py:322](../aughor/llm/provider.py)) —
   queues the parallel lenses. First check WHY 4 (throttle history: the Ollama Cloud endpoint hung
   after ~2.5h sustained load in June — resilience was added since). Make per-role configurable;
   raise only after a live A/B.

**Acceptance:** live A/B on a real investigation (luxexperience/womenswear canonical case) showing
≥2× wall-clock (target 8.4 min → ≤4 min) at equal-or-better finding quality; flags default-off
byte-identical; suite green. Measure like PR #109 (decompose A/B + executor A/B, flip analysis).

## 2. WS2 — One SQL executor (correctness + maintainability; deepest structural fix)

**The finding:** three divergent ~200–300-line implementations of "execute generated SQL with
guard battery + repair":
- `agent/investigate.py:556` `_execute_safe` (+ `_parallel_execute_safe`)
- `agent/explore.py:504` `_execute_one_subq`
- `agent/nodes.py:574` `execute_planned_queries`

The join/filter/fanout guard blocks appear near-verbatim in each; guard fixes must land 3×; drift
is why grain-prevention and honesty caveats run deep-only while the quick path lacks them (the
guard-parity gap). The `aughor/trust` façade (AL-01, `trust.verify_live`) is the natural home.

Scope: extract one shared guard-battery/repair runner; repoint ONE path per commit (each green);
add a **guard-parity conformance test** (a guard registered once provably fires on all three
paths); port grain-prevention (`measure_grains_block`) + honesty caveats to the quick path behind
the same seam. Future direction (from the Spider2 study, QUVI): invert guards from post-filter to
*vocabulary* — generation composes from dry-run/compiler-verified identifiers ("EXPLAIN is the
universal binder" doctrine, generation-side).

**Acceptance:** one runner, three thin call sites; parity test green; no behavior change off-flag
(golden-eval reference mode + full suite as the regression net); ratchets neutral or down.

## 3. WS3 — Accuracy measurement discipline (do BEFORE WS1/WS5 changes land)

Nothing gates accuracy at merge time today. What exists and runs (verified):
`evals/golden_sql_expanded.jsonl` (53 pairs) · `evals/run_golden.py` (`--mode reference` =
hermetic replay, no LLM; `raw`/`full` = live glm-5.2) · `evals/ratchet.py` (baseline + check,
tolerances 2% acc / 15% tokens) · `evals/ambiguity_eval.py` (pure, no LLM/DB).

Scope:
1. Wire the **hermetic** pieces into CI: reference-mode golden replay + ambiguity eval (seconds,
   no credentials; catches harness/fixture/guard regressions).
2. Record a **live full-pipeline ratchet baseline** with glm-5.2
   (`python evals/ratchet.py run --mode full --set-baseline main`) and document
   `ratchet.py check` as the mandatory local pre-merge step for answer-path changes.
3. **Guard observability:** fire/success counters on fanout de-fan, filter-literal binding, join
   repair (they already feed the trust receipt — add `stats.inc` counters + surface totals).
   June evidence: guards fired on 20.7% of real predictions (grain), so the counters have signal.

**Acceptance:** CI runs the hermetic evals; a committed baseline file; counters visible in the
receipt/stats; documented protocol in `evals/README.md`.

## 4. WS4 — Hygiene batch (small, do FIRST)

1. Regenerate `web/lib/api.gen.ts` (`npm run gen:api` against a running API) + add a CI
   codegen-drift gate (generate in CI, diff against committed file). ROADMAP queued item.
2. Move the 4 bypass flags into `FLAG_ENV` (ledger override + Settings UI parity). Keep env-var
   compatibility.
3. Convert bare `except: pass` in the hot files to `tolerate(exc, reason, counter=...)`:
   `routers/investigations.py` (~9: lines 46, 57, 139, 596, 690, 1094, 1114, 1135, 1138) and
   `agent/investigate.py` (~19: incl. 312, 327, 395, 587, 598, 664, 758). Lower
   `SILENT_SWALLOW_BASELINE` accordingly (only down).
4. Docs drift: fix FEATURES.md §13 (Spider harness claim → describe what exists), ROADMAP's stale
   api.gen.ts size claim; note the four-flag two-tier system wherever flags are documented.

**Acceptance:** codegen gate green in CI; baseline lowered; suite green; docs match code.

---

## 5. WS5 — Spider 2.0 top-3 campaign

**Target: top-3 on Spider2-Lite (≥ ~72; current spread 73.13 / 72.02 / 71.84 — 1.3 pts, within
gold-noise). Stretch: Spider2-Snow ≥ 90 from the same pipeline (top-3 there is 94.15+). Model:
glm-5.2:cloud via Ollama Cloud (user-confirmed; NOTE the honest caveat: June measured a ~56%
single-shot ceiling on the easy slice — the campaign bets on §5.4 finding #1 to lift past it, and
Phase 0 measures that bet before scaling). Snowflake access: user-confirmed ready.**

### 5.1 Benchmark mechanics (verified July 2026 — sources in the session memory `spider2-top3-study-2026-07`)

- **Tracks:** Snow 547 (all Snowflake, free shared account, queued) · Lite 547 (per current
  `spider2-lite.jsonl`: ~205 BigQuery + ~207 Snowflake-hosted + 135 local SQLite) · DBT 68.
  Snow and Lite are substantially the **same questions** (bq→sf_bq migrations); one campaign
  feeds both boards.
- **Eval (`spider2-lite/evaluation_suite/evaluate.py`):** execution-based, **column-vector
  containment** — every gold column (restricted to `condition_cols` if set) must exactly match
  *some* predicted column; **extra predicted columns are FREE**; `math.isclose(abs_tol=1e-2)`;
  `ignore_order` sorts within columns; **multiple acceptable gold CSVs** per instance
  (`{id}_a.csv`, `_b.csv`, …). Score over attempted + "Real score" over 547.
- **Gold:** answers (result CSVs) fully public since 2024-12 → complete self-scoring before any
  submission. Gold SQL only partially public. No hidden test set.
- **Submission:** email to lfy79001@gmail.com — folders of `{instance_id}.sql` +
  `{instance_id}.csv` + **a per-instance reasoning-trace file** (any text format, timestamped
  logs recommended) + brief method description. Validation by maintainers; leaderboard updates
  every ~1–3 weeks. **Rules:** one final answer per question chosen AUTONOMOUSLY (manual
  cherry-picking = exclusion); fine-tuning on released gold discouraged; `gold-tables` oracle
  excluded from ranking.
- **Access:** Snow = Google form in `assets/Snowflake_Guideline.md` → account on shared
  `RSRSBDK-YDB67606` (~12h), now REQUIRES MFA (Authenticator app) + Programmatic Access Token
  (post-2025-11-06 policy — this is why the June credential "looked dead"; the repo's
  credential JSONs are templates, there was never a bundled secret). Issues → email maintainer
  (12h SLA). **Self-hosting option:** email your Snowflake account id (AWS **us-west-2**) → they
  grant a Secure Data Share (`SPIDER2_MERGED_250922`, tooling in `lfy79001/spider2-data-share`);
  18 non-`sf_` instances stay on the public account. BigQuery = own GCP project, no form; ~70%
  of BQ instances hit `bigquery-public-data`; gate every query with dryRun + maximumBytesBilled.
- **Gold state:** refreshes through 2025-08-06 (update-log Google Doc); 2025-07-13 Snow ambiguity
  rewrite; 2025-10-29 eval fix + re-score; **no 2026 refresh**. CIDR 2026 (Jin et al.) found
  **~66% of Snow open-gold contains annotation errors** → practical Lite ceiling ~75–85; the
  top-3 cluster is already near it.

### 5.2 Leaderboard + winning formulas (July 2026)

| Track | Top 3 |
|---|---|
| Snow | Genloop Sentinel v2 Pro **96.70** · Native mini **96.53** · QUVI-3+Gemini-3-pro **94.15** |
| Lite | DivSkill-SQL **73.13** · SOMA-SQL **72.02** · DecisionX **71.84** |
| DBT | SignalPilot **65.6** · Databao (JetBrains) **60.29** · Shadowfax+GPT-5 **41.18** |

**Snow 90%+ formula:** (1) a curated per-database knowledge substrate between LLM and schema —
THE separator (raw-schema agent harnesses cap 36–60: ReFoRCE 35.8, APEX-SQL 53.0, ProSPy 60.5);
(2) deterministic machinery wrapping the reasoner (QUVI: YAML semantic models + deterministic SMQ
compiler, **only compiler-verified identifiers may appear in executed SQL**, ≤20 iterations, ONE
terminal execution, NO ensemble/voting); (3) frontier *thinking* model worth ~8 pts on an identical
harness (QUVI: Gemini-3-pro 94.15 vs Opus-4.6 86.28); (4) compounding loops (Genloop
83.4→88.5→96.7 across versions). Goodhart caveat (QUVI admits in print): hand-curated per-DB
descriptions can encode expected answers — Aughor competes with an AUTO-derived substrate instead
(AT&T proved auto-profiling ≥ SME descriptions; their KG entry = 86.3 on open models).

**Lite top-3 formula:** frontier reasoner (~half the gap at equal method) + agentic schema
exploration + heavy live execution-in-loop (SOMA ~50–60 LLM calls + 8–9 live probes/question;
DivSkill 8 skill-conditioned agents × ≤20 executions) + engineered candidate diversity +
**disagreement-as-evidence selection** (SOMA: +9.0 over majority voting) + offline-compiled
knowledge assets. SOMA repairs only assumptions traceable to probe outputs; Databao (JetBrains)
found single-trajectory discipline beats ensembles — both independently confirm the repo's
deterministic-first thesis.

### 5.3 Aughor position

**Assets (verified in code):** the auto-built semantic substrate (ontology w/ value-verified join
edges · metric contracts · glossary · profiling · YAML overrides · query-log miner) = the winners'
"context graph," derived honestly from the DB; the guard battery (grain/fanout · join value-domain
· filter-literal binding + CHESS value index · trust_checks) — fired on 20.7% of June's own
predictions, and its #1 target (fanout w/o DISTINCT) is the benchmark's #1 gold-error class;
`sql/closed_loop.py` (execute→observe→repair primitive) · `SnowflakeConnection.export_csv` +
byte-parity test vs the evaluator · Snowflake dialect rules (QUALIFY/FLATTEN/VARIANT — built,
NEVER live-tested) · schema compression · provider resilience · the deterministic complexity
router (`agent/complexity.py`) as the probe-triggering seam · trust receipts = the submission's
required reasoning traces, natively.

**Gaps:** no harness (removed 2026-06-29; rebuild is sanctioned — "the design is the durable
artifact"); the substrate has never been pointed at the benchmark DBs; per-instance
external-knowledge docs never read by the old pipeline; Snowflake semi-structured handling never
exercised live (QUVI's worst origin = native-sf 55.6% — where positions are won); local Spider2
clone stale (last pull 2026-01-30 — `git pull /Users/amitkamlapure/dev/Spider2` first).

### 5.4 The six NEW findings (beyond prior repo knowledge — fold into design)

1. **Execution-grounded machinery lifts past the sampling ceiling.** June's "machinery doesn't
   help strong models" tested *ungrounded* machinery (self-consistency, reflection). SOMA's
   ablation: disagreement-driven live probing **+9.0 over majority vote, +30.6 EX on instances
   where ZERO candidates were correct**. This is the bet that makes glm-5.2-only viable; Phase 0
   measures it.
2. **Extra columns are free** (containment eval) → **superset projection**: on ambiguous
   interpretations emit alternatives as additional columns in ONE query (rounded+raw,
   fraction+percent, name+id). Legal (one SQL, autonomous). Harness-side tactic, NOT a product
   feature. Complements (does not replace) the ANSWER_SHAPE rule.
3. **QUVI's verified-identifiers-only discipline** → generation composes from dry-run/compiler-
   verified building blocks (guards as vocabulary, not post-filter). Product-aligned; seed it in
   WS2's runner design.
4. **Self-host the Snow data via Secure Data Share** (us-west-2) → kills the shared-warehouse
   queue that limited June to ~2.5h sessions. Request EARLY in Phase 0.
5. **Traces are a submission requirement — Aughor's receipts already are that.** Run the harness
   THROUGH the receipt path; the submission package falls out of the product.
6. **DivSkill's "residual skill optimization" ≈ Aughor's dormant `aughor/memory` skills +
   playbook subsystem**: a small set of learned prompt policies optimized only on residual
   failures, selected by execution-equivalence + pairwise judge. Adapt using Aughor's OWN golden
   set + mined logs (NOT Spider gold — stays clean of the fine-tuning rule).

### 5.5 Phased plan (gates before spend)

- **Phase 0 — Unblock + measure the bet (≈1 wk).** `git pull` the Spider2 clone; MFA+PAT auth
  flow (access confirmed ready); request the Secure Data Share (draft email for user approval);
  GCP project DEFERRABLE (Snow + SQLite + sf-hosted Lite cover most of both boards). Rebuild the
  minimal harness in `evals/` (generate → execute → `rows_to_csv` → `evaluate.py` + receipt-backed
  trace logging). **The prior resume-brief's highest-ROI hour:** verify the CSV contract against a
  LIVE Snowflake cursor on 5–10 gold instances (NUMBER/FLOAT rounding, VARIANT-as-JSON, tz), then
  a 10–20 instance closed-loop smoke. **GATE:** hard-subset (50) A/B on glm-5.2 — baseline vs
  substrate-grounded vs substrate+probing. If grounding doesn't move the hard subset materially,
  stop and reassess (model swap or descope to "respectable listing").
- **Phase 1 — The substrate play (wks 2–4).** Run Aughor's explorer/profiler/ontology over the
  benchmark DBs (this is also a product stress-test on 150+ real schemas); ingest per-instance
  external-knowledge docs via the document-context layer; ground generation in the resulting
  SemanticContext. Iterate ONLY on the hard/failing subset (memory `spider2-test-hard-only`) with
  flip-level regression analysis.
- **Phase 2 — The budgeted loop (wks 4–6).** Wire `closed_loop` into the harness path; full guard
  battery on every candidate; ANSWER_SHAPE + `condition_cols`-aware output shaping + superset
  projection (finding #2); SOMA-style disagreement probing gated on the complexity router's
  low-confidence tier (finding #1; probe budget ≤ ~8/question, single round, repairs only
  probe-traceable); VARIANT/FLATTEN/QUALIFY live hardening on native-sf instances.
- **Phase 3 — Climb + submit (wks 6–10).** Full-547 self-scored runs under the reliability-banding
  protocol; iterate; at internal ≥72 Lite prepare the package (SQL + CSVs + receipt-traces +
  method description); **draft the submission email and SHOW it — never send without explicit
  permission.** Then assess Snow trajectory vs ≥90.

### 5.6 Pitfalls (plan around, don't rediscover)

Broken gold (~66% Snow open-gold — expect a plateau where correct answers score 0; do NOT tune to
wrong gold / no per-instance prompt tuning — June's integrity guardrails stand); shared-warehouse
queueing (mitigated by the data share); temp-0 cloud nondeterminism swamps sub-2-pt effects (use
`evals`' reliability-banding + flip analysis; June: ±flip churn at n=135); the leaderboard moves
every 1–3 weeks (top-3 is a moving target; Native calls the bench near-saturated); per-question
budgets are heavy at the top (SOMA ~50–60 calls/q ⇒ full runs are tens of millions of tokens —
iterate on the hard subset, full runs sparingly); Ollama Cloud endpoint throttling under sustained
load (provider resilience shipped since June — verify it holds on a long run).

---

## 6. Sequencing + session-start checklist

**Order: WS4 → WS3 → WS5-Phase-0 (gated) → WS1 ∥ WS5-Phases-1–3 → WS2.**
Rationale: hygiene de-risks; the measurement floor (WS3) must exist before WS1/WS5 change the
answer path; WS5-P0's gate decides campaign scale; WS2 lands last because it touches the most
sensitive path and benefits from WS3's regression net (and its runner design should absorb
finding #3).

Each session, before working:
1. `git pull` + read this doc's relevant WS section + `AGENT_NOTES.md`.
2. Confirm suite green + ratchets at baseline before and after (`uv run pytest -q -m "not e2e and not eval"`).
3. Measure against §0's baseline; record deltas here (append a dated progress log below).
4. Update this doc + ROADMAP §0 when a WS item ships or its status changes.

## Progress log

- *2026-07-06 — program written; no execution started. Snowflake access + glm-5.2 (Ollama Cloud) confirmed by user. Next: WS4.*
- **2026-07-06 — build session (branch `2026-07-06-10x-program`, 12 commits). WS4, WS3, WS2 COMPLETE; WS1 code done (A/B pending); WS5-P0 harness + full run done, scored.**
  - **WS4 (4 commits):** api.gen.ts regen 12,929→16,128 + offline `scripts/dump_openapi.py` + CI `codegen` drift gate · the 4 bypass flags (`ada.premise_check`/`ada.causal_drill`/`ask.clarify`/`closed_loop`) registered in `FLAG_ENV` w/ `FLAG_DEFAULT` preserving ask-clarify default-ON · 47 silent swallows → `tolerate()`, `SILENT_SWALLOW_BASELINE` 263→214 · FEATURES.md drift fixed.
  - **WS3 (2 commits + baseline):** `tests/integration/test_golden_reference.py` hermetic CI gate (53/53) — standing it up fixed real scorer bugs (empty-result + unordered-row false docks) and 6 tie-nondeterministic golden records (sql024 scored 0.653 vs its OWN sql) · guard fire/repair counters (`aughor.stats.bump`, `guard.*` on defan/grain/join/filter/trust) · **live full-pipeline ratchet baseline pinned: mean 0.6551, exec 1.00, 420.6k tok** (model `qwen3-coder-next:cloud` per .env) · protocol in `evals/README.md`.
  - **WS2 (3 commits) — COMPLETE, with a scope judgement:** the three execute-with-guards paths were NOT force-unified — their POST-execute repair loops are legitimately divergent (ADA: id-arith + trust gate; explore: R3 + KB + triangulation + pitfalls; quick: B-7 + consistency + pitfalls), and merging them would degrade explore/quick. What WAS genuinely duplicated AND missing-in-parity is the PRE-execute deterministic hardening (de-fan → preflight-repair). Extracted to `aughor/sql/executor.py` (`execute_guarded` verbatim from ADA `_execute_safe` + the shared `preflight_harden`), wired into all three paths (explore + quick each GAINED de-fan + preflight they never had), enforced by `test_guard_parity_all_three_paths_share_the_hardening`. Import-boundary test keeps the runner below `aughor/agent`. +16 tests.
  - **WS1 — SHIPPED + live-measured (1.23×, honest):** `ada.parallel_phases` wave (`aughor/agent/phase_waves.py`) runs baseline∥decompose∥dimensional concurrently with serial early-stop semantics applied post-hoc; behavioral stays serial (hard dep). 6 tests. Profiling REFUTED the metric-block/ontology caches (15ms/5ms warm) — not built. **Live A/B (real /investigate, luxexperience, n=1 each, isolated stores): serial 373s → wave 304s = 1.23×; both 14 LLM calls, same phase set + MEDIUM confidence = equal quality.** Below the 2× aspiration — the 3 parallelized phases are only part of the 14 calls; intake + synthesis are serial-by-necessity and dominate. A real, quality-neutral win but modest end-to-end; phase-level parallelism is not the dominant lever here (intake-internal + multilens + synthesis are). n=1 (temp-0 cloud noise possible); mechanism unit-test-proven.
  - **WS5-P0 — harness + full run done (scoring, NOT submission):** `evals/spider2.py` (product prompt + guards + closed-loop + external-knowledge docs + timestamped traces). Full 135 local SQLite: **135/135 exec-success; official evaluate.py 72/135 = 53.3%** (June ref 56.3% w/ glm-5.2 + ANSWER_SHAPE; this run = product prompt on qwen3-coder-next). Data-Share request DRAFTED (`docs/spider2-data-share-request-DRAFT.md`), NOT sent.
  - Suite 2588 green throughout; ruff 0; ratchets only-down. **Next: WS1 live A/B; then WS5 Phase-0 grounding-lift A/B + fail-analysis of the 63 misses.**
