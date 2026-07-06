# Agent working notes (10x assessment session, started 2026-07-05)

One lesson per entry; one-line summary on top. Delete notes that prove wrong.

## CANONICAL PROGRAM SPEC (read first in every session)
`docs/10X_AND_SPIDER2_PROGRAM_2026-07-06.md` — the full 5-workstream program (WS4→WS3→WS5-P0→WS1∥WS5→WS2)
with baseline, file:line anchors, the Spider2 runbook, gates, and a progress log to append to.
ROADMAP §0 (top block) + §3 ("The 10x + Spider 2.0 program") mirror it at-a-glance.
User-confirmed 2026-07-06: glm-5.2 via Ollama Cloud is THE campaign model; Snowflake access ready.

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
