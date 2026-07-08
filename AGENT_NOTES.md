# Agent working notes (10x assessment session, started 2026-07-05)

One lesson per entry; one-line summary on top. Delete notes that prove wrong.

## CANONICAL PROGRAM SPEC (read first in every session)
`docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md` — the full 5-workstream program (WS4→WS3→WS5-P0→WS1∥WS5→WS2)
with baseline, file:line anchors, the Spider2 runbook, gates, and a progress log to append to.
ROADMAP §0 (top block) + §3 ("The 10x + Spider 2.0 program") mirror it at-a-glance.
User-confirmed 2026-07-06: glm-5.2 via Ollama Cloud is THE campaign model; Snowflake access ready.

## Compounding-substrate map (2026-07-07, for the paradigm-shift study)
Aughor has FOUR partially-connected compounding stores, none executable/composable:
- `playbook/models.py::PlaybookEntry` — trigger→recommendation TEXT + `historical_success_rate`
  (updated by `outcomes.py::update_playbook_success_rates`) — a proto-skill, advisory only.
- `semantic/trusted_queries.py::TrustedQuery` — flat trusted-SQL strings, token-overlap retrieval top-k 2.
- `ontology/models.py` — the genuinely rich WORLD MODEL (verified ComputedProperty.formula_sql,
  ObjectSet.filter_sql, grain_verified, null_meaning, measure_grain) — verified but declarative-only.
- `semantic/ambiguity_ledger.py` — per-connection resolution priors.
Gap a skill-library idea would fill: parameterized, EXECUTABLE, verified, composable analytical
procedures that accumulate per warehouse — today's stores hold text + SQL strings, not procedures.

## External-source study (2026-07-07) — DocETL · Palimpzest · Hasura/PromptQL · DAB
User redirected mid-session: study Palimpzest, Hasura graphql-engine, PromptQL, + 2 papers
(DocETL 2410.12189, DataAgentBench 2603.20576) and extract iterable features to improve Aughor.
**The four sources CONVERGE on Aughor's own thesis** — a declarative plan separated from
deterministic execution, LLM non-determinism confined to small bounded *validated* ops. So they
validate the direction and hand Aughor specific unbuilt mechanisms. Full briefs captured in the
session; key transfers, ranked:
- **DocETL gleaning** (validate→refine loop, `num_rounds`, append-validator-to-thread) → the text
  semops, which today do single-call fail-open with ZERO validation. ✅ SHIPPED (below).
- **Palimpzest**: `convert(χ)` as a first-class optimizable operator; **champion-model reference-free
  quality estimation** (rank cheap-op output vs a strong model on a sample, no labels); policy-driven
  per-op physical choice (model/code-synth/token-reduction); MAB sentinel sampling → Pareto frontier.
- **Hasura NDC**: capability-negotiated connector contract; **batched foreach remote joins** (dedup keys
  → one keyed request per remote node, N+1-free); cross-source filter → OR-of-equalities pushed to one
  WHERE; declarative row/col perms compiled INTO the predicate.
- **PromptQL**: plan-as-Python-program (run_sql/search/classify/summarize/extract + store_artifact),
  deterministic replay, **artifacts = structured working memory** (never re-feed raw rows to context).
  100% on CRMArena-Pro DB-querying vs ~58% agent-loop; +7pt over ReAct on DAB via the context layer.
- **DAB** (the frontier bench, Gemini-3-Pro 38% pass@1): 4 hard axes by query count — multi-DB 54/54 ·
  **unstructured-text extraction 47/54 (0% on patents, the wedge)** · domain-knowledge 30/54 ·
  ill-formatted join keys 26/54. Failures: plan+impl = 85% (FM2 40 + FM4 45), data-selection only 15%.
  Aughor already owns axis-4 (ontology/metrics) + has the right shape for axis-3 (overlap-probe join
  guards, single-DB today). Aughor already has a THIN `connectors/federated.py` (DuckDB ATTACH/Arrow).
Decision (mine, pending user scope pick on the bigger bets): ship the no-regret wedge first
(guarded extraction = DAB GAP-2), then present the ranked roadmap for the big directional bets
(cross-DBMS federated planner / plan-as-program+artifacts / cross-source key reconciliation).

## ◑ IN PROGRESS — Rec 2 cross-source federation (branch `2026-07-07-guarded-extraction`)
Staged (XL). **Stage 1 ✅ SHIPPED:** `aughor/connectors/remote_join.py` — `batched_foreach_join(left,
left_key, right_conn, right_table, right_key, how=inner|left)`: dedups left keys, one `WHERE right_key IN
(...)` query PER KEY-CHUNK to the right conn (N+1-free, Hasura NDC pattern), hash-join in memory. Bounded
(chunk 1000 / 100k right / 50k out), injection-safe (escaped literals), fail-safe (any error → left result
unchanged). `cross_source_join(...)` = by-connection-id wrapper the planner/API will call. Complements
`federated.py` (DuckDB ATTACH when co-located; batched-foreach for true cross-engine). 7 tests (two real
in-memory DuckDB conns + counting wrapper proving 1 query for 5 rows/2 keys, and 3 queries for 5 keys/chunk 2).
**Stage 2 ✅ SHIPPED:** `POST /query/cross-source-join` (`routers/query.py`, flag `federation.remote_join` /
`AUGHOR_FEDERATION_REMOTE_JOIN`, default off → 404) calls `cross_source_join`; left SQL runs through
`gate_user_sql`. 3 integration tests (404-when-off, end-to-end join across two registered DuckDB files,
field-validation 400). Suite 2708 green. **Stage 2b ✅ SHIPPED:** self-healing keys in `remote_join.py` —
when raw match rate < 0.15 and `reconcile=True`, retry under PAIRED normalizations (Python fn on materialized
left keys + equivalent SQL expr on the right key: digits/strip_prefix/trim_lower/strip_zeros/alnum_lower),
adopt the first reaching ≥0.60 match AND ≥+0.30 gain. Refactored the primitive into `_fetch_right` (projects
`{jk_expr} AS __jk`, one path for raw+normalized) + `_hash_join` + `_try_reconcile`. Endpoint passes
`reconcile=flag_enabled("join.key_reconciliation")` (same flag as Rec 3 — the cross-source twin). 3 tests
(raw misses bid_N↔bref_N, reconcile heals to 3 rows, disjoint C00x↔CMPx doesn't false-reconcile). Suite
**2711 green**. **Stage 3 ✅ SHIPPED:** `aughor/agent/federated_planner.py` — `answer_federated(question, left_id, right_id)`:
ONE LLM call → `FederatedPlan{left/right FederatedSide(sql, join_key), how}` grounded on both `get_schema()`;
`validate_plan` executes each sub-query as `SELECT * FROM (sql) AS _t LIMIT 0` and checks the join_key is an
output column (bad plan → issues, NO execution); then `cross_source_join(..., right_sql=plan.right.sql)`.
Engine extended: `batched_foreach_join`/`cross_source_join` now take `right_table` OR `right_sql` (keyword;
`from_clause` = `(subquery) AS __rt` or quoted table) — the right side can be a grounded sub-query. Endpoint
`POST /query/federated-answer` (flag `federation.planner` / `AUGHOR_FEDERATION_PLANNER`, default off → 404),
returns merged result + the plan (inspectable) + issues. 6 tests (fake planner LLM + 2 real registered DuckDB
sources). Suite 2718 green. v1 = exactly 2 sources, conn_ids[0] drives. N-source/driver-selection/answer-path
integration are follow-ups.
**✅ REVIEW DONE** (fresh-eyes agent, build-wire-test-review): 6 findings, 5 fixed (suite **2719 green**):
#3 numeric cross-type keys (`_canon_key` strips trailing fractional zeros → INT 101 joins DOUBLE 101.0);
#6 right-query error now returns an honest error result, not silent left rows posing as a successful inner
join; #5 `_qident` now escapes embedded quotes (was passthrough); #4 planner's LLM SQL now gated through
`gate_user_sql`; #1/#2 the connector's 500-row `execute()` cap (a deliberate API bound) — surfaced as a
`PARTIAL: left driver capped at N of M rows` note instead of silently truncating (not raised: the global cap
is out of scope to change here). Verified the 5 reconcile Python/SQL transform pairs agree byte-for-byte
(0/60 mismatches on edge keys).
**✅ FOLLOW-UP — per-source 500-row cap LIFTED** (2026-07-08): added `execute_bounded(hyp, sql, max_rows)`
to the connection ABC (default → `execute`, i.e. unchanged/capped for connectors that don't override) with
real overrides on DuckDB (`rows[:max_rows]`) and Postgres (`fetchmany(max_rows)`) — refactored both
`execute` bodies into a shared `_run(hyp, sql, max_rows)`. The federation engine now reads the LEFT driver
(≤`_MAX_OUT_ROWS` 50k) and each keyed right fetch (≤`_MAX_RIGHT_ROWS` 100k) via `execute_bounded`, so joins
are no longer silently truncated at 500 (other connectors still cap → flagged PARTIAL). 2 tests (700-row
right unit + 600-row end-to-end driver). Suite 2721 green. Core-layer change, whole suite unaffected.
**✅ FOLLOW-UP — N-source + driver auto-selection** (2026-07-08): `federated_planner.py` IR generalized to
`FederatedPlan{steps: list[FederatedStep{source:int, sql, join_key, left_key, how}]}`; steps[0]=driver
(no left_key), each later step joins its source onto the assembled result on a key already present.
`answer_federated(question, conn_ids: list)` folds the steps through `batched_foreach_join`; `validate_plan`
tracks assembled columns (left_key must be present) + source-index range. Planner picks step order ⇒ driver
auto-selection falls out. Endpoint `/query/federated-answer` now takes ≥2 conn_ids. 8 tests incl. a real
3-source chain (orders→region→manager). Suite **2723 green**. **ANSWER-PATH INTEGRATION deferred BY DESIGN:**
it needs cross-source connection SELECTION (which connections does an NL question span?) — a genuine new
capability, not plumbing; that's the honest dependency. Rec 2 BACKEND is complete.
SIGNATURE NOTE: `batched_foreach_join` moved `right_table` to keyword-only (was positional) — all callers +
the 11 unit-test calls updated.

## ✅ SHIPPED — Champion cascade on semantic_filter (Rec 5, branch `2026-07-07-guarded-extraction`)
Palimpzest/LOTUS label-free quality estimator. `semops/operators.py`: extracted the filter batch loop into
`_filter_verdicts(rows, ci, pred, provider, batch, indices)`; `semantic_filter` gains `validate_sample=`/
`champion_role=` — runs cheap `fast` tier, re-judges an evenly-spread sample on the strong `coder` champion,
and if sample disagreement > 20% escalates the WHOLE batch to the champion (else trusts cheap). Flag
`semops.champion_validate` / `AUGHOR_SEMOPS_CHAMPION_VALIDATE`, default off = byte-identical (champion branch
skipped). Wired in `routers/query.py` (validate_sample=8 when on). NOTE: Role literal is coder/narrator/fast
(NO "reasoner") — champion = "coder". 3 tests, suite **2698 green**, ruff 0. Follow-on: the full LOTUS
calibrated-threshold cascade with (precision,recall,δ) GUARANTEES is the principled successor (see the deeper
2026-07-08 research pass) — this ships the tractable estimator first.

## ✅ SHIPPED — Ill-formatted key reconciliation (Rec 3, branch `2026-07-07-guarded-extraction`)
DAB GAP-3 (26/54). `aughor/sql/join_guard.py`: when the value-domain guard flags a low-overlap join,
`reconcile_join_keys` tries deterministic DuckDB normalizations (trim+lower/digits/strip-prefix/strip-zeros/
alnum-lower) on both keys, re-probes overlap direction-aware, and if one lifts to ≥0.60 AND ≥+0.30 over raw,
attaches a `KeyReconciliation` to the `JoinDomainWarning` — `to_prompt_text()` then surfaces the exact
`ON regexp_replace(...) = regexp_replace(...)` to join on. Distinguishes bid_123↔bref_123 (reconciles) from
truly disjoint entities (C00x↔CMPx, no transform helps). Flag `join.key_reconciliation` /
`AUGHOR_JOIN_KEY_RECONCILIATION`, default off = byte-identical (recon=None → original message). Only runs when
a mismatch already fired (rare), breaks on first strong hit, fail-open. 6 tests, suite **2695 green**, ruff 0.
NOTE: probe is DuckDB-syntax (USING SAMPLE + regexp_replace) — works on DuckDB + the FederatedConnection
(the cross-source surface), fails-open on other dialects exactly like the base probe.

## ✅ SHIPPED this session — Guarded extraction (branch `2026-07-07-guarded-extraction`, `c07c445`)
DocETL-gleaning on `semops/operators.py::semantic_extract`: infer a type (year/date/email/number) from
each field's name/desc, deterministically validate extracted values, re-extract off-type cells with
targeted feedback for `max_rounds`, surface+keep residuals (never drop — fail-open contract holds).
Flag `semops.guarded_extract` (`AUGHOR_GUARDED_EXTRACT`), default off = byte-identical; wired into both
live callers (`routers/query.py::query_semantic` + `agent/investigate.py` ADA semantic step). 12 tests,
full suite **2690 green**, ruff 0. This is the deterministic-guard-over-LLM answer to the axis where
every frontier model scores 0%.

## Baseline (main @ 879fbee, 2026-07-07 — session 2)
- Full suite `uv run pytest -q -m "not e2e and not eval" -p no:cacheprovider`: **2663 passed, 1 skipped, 6 deselected in 89.2s** (green; grew +155 from the 2508 in the prior baseline).
- Ruff (`uvx ruff@0.15.20 check .`): **0**. LOC: aughor/ 83,386 py · tests/ 31,002.
- Note: `timeout` is not on this macOS — don't wrap pytest in it.

## Baseline (main @ 7d13abe, 2026-07-05)
- Full suite `uv run pytest -q -m "not e2e and not eval"`: **2508 passed, 1 skipped, 6 deselected in 97s** (green — the memory claim "2 TestRatchets RED on main" is STALE).
- Ruff: 0. Web `npx tsc --noEmit`: 3.1s.
- LOC: aughor/ 82,135 py · web/ 43,546 ts(x) excl. api.gen.ts · tests/ 29,281.
- Churn last 6wk (commits touching): explorer/agent.py 111 · routers/investigations.py 95 · agent/investigate.py 71 · routers/exploration.py 38.

## Survey reconciliation (2026-07-05) — verify subagent claims before reporting
- A code-health subagent claimed 4 flags dead (`capability.pipeline_live`, `semantic.contract_live`, `trust.verify_facade`, `explorer.synthesis_incremental`) and the silent-swallow ratchet RED. Both WRONG: all four flags are wired (routers/query.py:512/458, semantic/canonical.py:275, explorer/agent.py:3621) and `tests/unit/test_kernel_contracts.py` passes 4/4 (baselines: swallows 263, private imports 22). Lesson: grep-verify any "dead code"/"red gate" claim myself before it reaches a report.
- Confirmed real drift: `web/lib/api.gen.ts` (12,929 lines) missing /rbac /jobs /packs /verify route families, gen:api not CI-wired; FEATURES.md §13 still claims a "Spider 2.0 NL2SQL harness" that was deliberately removed in the 2026-06-29 consolidation (don't rebuild it — fix the doc).
- Eval assets that DO exist and run: evals/golden_sql_expanded.jsonl (53 pairs), run_golden.py (reference mode = hermetic replay, no LLM; raw/full = live), ratchet.py, ambiguity_eval.py (pure).

## THE NOISE FLOOR (2026-07-06, full-135 candidates run) — read before ANY lever claim
- **±7–10 instances of 135 churn between ANY two runs** on glm-5.2:cloud @ temp 0 (observed 3×: projection 5/7, candidates full 9/10, pure-rerun components). A lever below ~+10 instances CANNOT be proven by single runs — including our own +1 (A-fixes) and +3 (candidates subset), which are directional only. Full-set candidates: 71/134 = 53.0% vs 53.3% baseline, net −1 (9 recovered / 10 regressed). `--candidates` stays opt-in. What survives noise: deterministic monotonic mechanisms (guards, evidence-gated repair), distribution-level changes (model/substrate), amortization plays (Ambiguity Ledger). Reliability banding (reps + McNemar) is the only honest instrument below +10 — at ~5h/run, barely affordable; prefer levers that are monotonic BY CONSTRUCTION.

## Spider2 measurement lessons (2026-07-06 Phase-0)
- **NEVER measure a lever on the failing subset alone.** The projection lever looked like +12/63 on a misses-only re-run, but a controlled same-instance on/off comparison (62 instances) was 33→31 = **net −2** (5 recovered, 7 regressed). A misses-only run is structurally blind to regressions on previously-correct queries. Always compare the SAME instances on vs off.
- temp-0 on glm/qwen cloud is nondeterministic — a ±2 delta at n≈62 is within noise. Don't believe a sub-single-digit lever without a controlled + repeated run. (Reproduces June's "machinery perturbs correct queries" meta-pattern — even a prompt directive does it.)
- **Ollama Cloud throttles hard under sustained load:** after 3 back-to-back 60–135-instance runs it crawled to ~5 instances/hour and stalled the full re-run at 62/135. Budget for it — iterate on the hard subset, full runs sparingly, or get a dedicated endpoint before Phase-1/2 (dozens of calls/question).

## Spider2 campaign facts (2026-07-06 study)
- Local benchmark clone `/Users/amitkamlapure/dev/Spider2` is STALE (last commit 2026-01-30) — `git pull` before any campaign work (gold refreshes landed through 2025-08; auth docs changed).
- Snowflake access = Google form (12h turnaround) + MFA + PAT; the "dead credential" was a template, never a secret. BigQuery = own GCP project (`bigquery-public-data` covers ~70% of BQ instances).
- Prior pipeline NEVER read the per-instance external-knowledge docs (13/135 local instances ship one; more on cloud tracks) — known, unfixed gap.
- `tests/` has an export-CSV↔evaluator byte-parity test; the closed-loop primitive is `aughor/sql/closed_loop.py`. The eval harness itself was deliberately removed — rebuilding it is sanctioned when the campaign restarts.
- Leaderboard submission only by email; NEVER send without explicit user permission (draft + show).

## WS1 measurements (2026-07-06) — profile-first killed two "obvious" optimizations
- unified_metric_grounding on the real `workspace` connection: cold 496ms, warm **15ms** (inner caches already cover a long-running API); load_latest_ontology: 23ms cold / 5ms warm. Both proposed caches are pointless — REFUTED, don't rebuild. The deep path's wall-clock is ~100% phase-serial LLM calls; the wave work is the only real lever.
- **WS1 live A/B (real /investigate on luxexperience, "what drove GMV change last quarter", n=1 each, isolated stores):** serial **373s** vs `ada.parallel_phases` **304s = 1.23×**. BOTH arms: 14 LLM calls, same phase set (intake·baseline·decomposition·dimensional), same MEDIUM confidence → **equal coverage/conclusion, zero quality cost**. But 1.23× ≠ the aspirational 2× — the 3 wave phases are only part of the 14 calls; **intake + synthesis are serial-by-necessity and dominate**. HONEST take: the wave is a real, free win but modest end-to-end; the bigger levers are intake's internal calls + cross-section multilens (already flagged) + synthesis, NOT more phase-level parallelism. Don't overclaim 2×. n=1 = temp-0 cloud noise possible; mechanism is unit-test-proven.

## Build-session lessons (2026-07-06)
- graph.py imports `route_after_wave` from agent/explore — any same-named local import inside `_compile` makes the name function-local for the WHOLE function → UnboundLocalError on every build. Alias phase-wave's router (`as route_after_phase_wave`).
- `uv sync --extra X` makes the venv match EXACTLY that extra set — it silently removed ad-hoc tools (ruff, vulture). Use `uvx ruff@0.15.20 check .` (CI's form) locally; restore with `uv sync --all-extras --frozen`.
- The silent-swallow ratchet counts ANY bare `except: pass` — including deliberately-trailless fail-safes like stats.bump(). Use `return` + a comment for those (the ratchet's AST check counts Pass/Continue bodies only).
- tests/integration/test_golden_reference.py::sql048 flaked ONLY while the machine ran a heavy parallel LLM harness (load-sensitive, likely slow-exec). Passes 3× standalone + full suite when idle. If it flakes in CI (idle machines), investigate for real.
- Ollama `/v1/models` does NOT list cloud models that still WORK (glm-5.2:cloud answered while absent from the list) — don't conclude a model is gone from the listing alone.
- **MODEL RESOLUTION: don't read `.env` and assume.** `.env` says `AUGHOR_CODER_MODEL=qwen3-coder-next:cloud` but the runtime inference-plane config (`provider._cfg()['models']['coder']`) pins **glm-5.2:cloud**, which WINS (layer-1 runtime override > layer-2 env > layer-3 default). ALL WS5 runs + the ratchet baseline used glm-5.2:cloud (confirmed via `get_provider('coder')._model` AND the run banner). I mis-stated it as qwen3-coder-next early on — always verify with `get_provider('coder')._model`, never the env var alone.
- evals scripts must load .env themselves (provider falls back to a hardcoded default model otherwise — spider2.py caught this; run_golden documents the same lesson).

## Repo conventions that matter
- Docs (ROADMAP.md/FEATURES.md) are unusually accurate but verify anyway; the repo's own rule: code > docs on disagreement.
- All stores must honour `AUGHOR_*_DB` env overrides; the suite is hermetic — never point tests at data/.
- Feature work here ships flag-gated, default-byte-identical, then gets flipped via the ledger override. Follow that pattern.
- Test ratchets (silent-swallow count, private-import baseline) may only go DOWN; never raise a baseline.
