# Flag experiment queue — handoff (2026-08-01)

Everything the next session needs to resume the feature-flag experiment queue cold. The
broad strategy is done and merged (#243, `e122fe5`); this is the last open thread of it.

## Where things stand

- **Registry: 89 flags, fully dispositioned, ratchet-enforced.** 57 default-ON · 10 auto ·
  5 intentionally-off · **13 experiment** · 4 performance-profile · 0 migration · 0 queue.
  A new flag that declares no exit fails `tests/unit/test_flag_dispositions.py`.
- **Branch `worktree-flag-experiment-queue`** (off `e122fe5`) holds the batch-D **free tier**,
  **2 commits, UNPUSHED**, both green on a full CI-matching run:
  - `1f18be3` — `snapshot_receipts` GRADUATED (cost measured ~0.2ms median, no grid).
  - `e094603` — `search.rrf` SETTLED OFF on a measured negative (RRF MRR 0.964 < α-blend
    0.977 on the real KB); de-flaked the snapshot cost-bar (median, not p95).
  - **First action: decide push/PR for these two** (needs explicit user permission per the
    standing push rule).

## The 12 remaining flags (all need a real LLM A/B grid, or are coupled decisions)

From the triage in `docs/FLAG_STRATEGY_2026-07-31.md` §D. Ordered cheapest/most-actionable first.

| Flag | Exit question | Grid target / notes |
|---|---|---|
| `plan.program` | does answering fresh /ask auto turns via plan-as-program match quick-path quality? (adopt-or-kill) | single-connection auto questions; ROUTE + 1 plan call |
| `federation.planner` | does auto-federating fresh /ask turns beat the single-source answer? | needs ≥2 connections a question spans; ROUTE + 1 call |
| `closed_loop` | do captured corrections read back improve answers? | **data-gated** — grid only on a fixture WITH correction/verdict rows, else no delta by construction; already measured ~no-op on ~90% of one corpus (ROADMAP) |
| `graph.readback` | does the injected graph slice improve plans enough to pay its prompt cost? | **data-gated** — needs a built graph + prior findings; prior grid: +0.023 vs a 0.182 floor, +44% wall (ROADMAP) — i.e. not attributable |
| `ada.why_where_interaction` | does the WHY×WHERE cross query change conclusions? | cross-sectional "why is X high/low"; +1 call; requires `ada.parallel_lenses` |
| `ada.why_deepen` | do peer-benchmark + drill change the fix target? | "why" investigations; +2 calls |
| `ada.evidence_stubs` | quality effect of dropping rows (cost already measured) | multi-hypothesis runs clearing 12k-char blocks; its own desc forbids graduation before this A/B |
| `explorer.synthesis_incremental` | is mid-run synthesis worth the extra calls? | multi-domain explorations; cost measurable free, quality needs grid |
| `explorer.manifest_driven` | does deterministic coverage match LLM-loop quality? | coverage measurable free; parity A/B vs an LLM-only baseline arm |
| `kinetic.agent_actions` | does the action proposer earn its call? | **data-gated** — needs a fixture ontology WITH declared actions + a proposal grader |
| `semops.champion_validate` | does champion validation catch enough cheap-tier errors? | the one that needs a **labeled** semantic-filter task (ground-truth include/exclude) |
| `explore.route_wide` | do landscape questions answer better via the explore wave? | routing already settled (`evals/route_wide_eval.py`); only the answer-quality A/B remains |

**Not a grid — a coupled decision:** `ada.causal_drill` is inert whenever `ada.parallel_lenses`
is on (its serial twin). Settle it WITH the performance-profile call (delete if the parallel
profile becomes default); don't spend a grid on it.

**Free pre-check before ANY grid** (saved ~850 requests on #241): "does the flag change the
prompt?" and, for data-gated flags, "does the fixture actually carry the data?" — several of
these are byte-identical / no-call unless the fixture has corrections / a built graph / declared
actions, so a grid on a bare fixture measures nothing.

## How to run a grid (E4 harness)

- **Harness:** `aughor/evals/runner.py::run_experiment(suite_id, target_factory, cells, *,
  replicates, iterations, fixture, fixture_tables)`; cells built with
  `aughor/evals/experiments.py::grid({label: {flag: bool}}, model=, temperature=)`. Reference
  usage in `tests/integration/test_evals_perturb_runner.py`. `evals.experiments` is default-ON.
- **Budget math:** `requests = cells × replicates × cases × iterations × requests_per_case`.
  For a flag A/B: 2 cells × 3 replicates × N cases × req_per_case. A quick-/ask flag
  (~1–2 req/case, 20 cases) ≈ 120–240 requests; a deep-investigation flag (dozens req/case)
  blows the **1,000/day** free cap alone → **realistically one expensive grid per day.**
- **Required env for a live grid** (from ROADMAP §0):
  `AUGHOR_EVALS_EXPERIMENTS=1 AUGHOR_FALLBACK_DISABLED=1 AUGHOR_LLM_RPM=16
  AUGHOR_LLM_MAX_CONCURRENCY=2` + `freeze=True` on the run (pins the data version so a cell
  can't be attributed to a moved dataset). `assert_measurable()` refuses to run unless
  `AUGHOR_FALLBACK_DISABLED` is on (else a cell finishes on a different model).
- **Model:** `:free` OpenRouter models only (see `aughor/llm/matrix.py`); user flagged
  `deepseek/deepseek-v4-flash` for fast iteration. Pin temperature (13% run-to-run
  nondeterminism is a platform fact).
- **Graduation gate:** a grid with a baseline needs the `fidelity.compare()` delta passed as
  `delta=` to `evaluate_graduation` — clearing the bar ≠ beating the noise floor. The gate
  refuses a delta the harness won't attribute.

## Discipline / gotchas (paid for this session)

- **A live LLM call from a bare script 401s SILENTLY without the key:**
  `export AUGHOR_SECRET_KEY=$(grep ^AUGHOR_SECRET_KEY= /Users/amitkamlapure/dev/aughor/.env | cut -d= -f2-)`.
  A worktree's `.env` does NOT carry it. (Embeddings are LOCAL Ollama — free, no key.)
- **Match CI from the start:** `uv sync --all-extras --frozen`, then
  `uv run pytest -q -m "not e2e and not eval"` over the WHOLE tree. A `tests/unit`-only run
  cannot catch: `tests/integration` off-state tests, the two whole-tree ratchets
  (`test_no_new_silent_swallows`, `test_no_new_private_cross_imports` — a new eval/script trips
  both easily), or the mlflow whole-tree ordering leak.
- **Any default flip:** simulate `AUGHOR_<VAR>=1 pytest` first; then grep ALL of `tests/`
  (not just `tests/unit`) for `delenv`/ambient-off of the flag's env var and re-point to `=0`.
- **Grids/embeds MUST be `run_in_background` + `python -u`.** Never assert on a p95 wall-clock
  in a receipt suite — it flakes under full-suite load; assert the median.
- **Change a receipt scenario ⇒ re-mint the receipt** and update every id that cites it.
- **`data/` is not test-isolated** — snapshot `git status --short data/` before/after a full
  run; it should stay 0. Findings/dossier writes go there.

## Pointers

- Strategy + all dispositions: `docs/FLAG_STRATEGY_2026-07-31.md` (§D = the queue, §7 = state).
- The honest retrieval eval pattern (reusable for `search.rrf`-like questions):
  `aughor/evals/rrf_retrieval_eval.py` — real corpus, definitional labels, local embeddings.
- The receipt-suite pattern for a construction-decidable settle:
  `aughor/evals/snapshot_receipts_receipt.py`.
- Memory: `flag-strategy-study-2026-07-31.md` carries the full session-by-session log.
