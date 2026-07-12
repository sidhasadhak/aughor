# Platform Review & Implementation Program — 2026-07-12

**What this is.** A full external-style review of the platform (six parallel code audits + a live UI
walkthrough + repo metrics), converted into an implementation program. Every finding carries
`file:line` evidence gathered on 2026-07-12 at `main == 911af32`. Work packages (WP-1 … WP-16) are
written so a coding agent can execute them **without re-deriving context**: problem → evidence →
exact change plan → flag policy → tests → live verification → gotchas → definition of done.

**Line-number caveat.** Line anchors were verified on 2026-07-12. If a file has drifted, re-locate
by the **symbol name** given next to each anchor; do not trust raw line numbers over symbols.

**Review method.** Six scoped audits (backend architecture, trust-plane coverage, frontend,
config/persistence, autonomy, tests/CI) + firsthand browser walkthrough of the running app
(api :8000, web :3000, luxexperience connection) + metrics. Scale at review time: ~90k LOC Python
(400 files; 314 endpoints across 31 routers), ~62k LOC TS/TSX, ~37k LOC tests (~2,980 test fns),
17k LOC docs; 950 commits (661 in the last 30 days).

---

## 0 · Read this first: the repo rulebook (binding for every WP)

These are the conventions and *earned* gotchas of this repo. Violating them is how PRs bounce.

### 0.1 Commands & discipline
- Run everything through `uv run <cmd>`. Fast hermetic loop: `uv run pytest tests/unit -q`
  (~90s for the full suite; CI runs `-m "not e2e and not eval"`).
- **Verify the pytest pass-count line, not the pipeline exit code** — `| tail` masks pytest's exit
  status, and a `cd web` that persists across Bash calls once made a suite "pass" by running zero
  tests in the wrong directory.
- `uv run ruff check` must stay at **zero** (blocking CI, pinned `ruff@0.15.20`).
- Ratchets may only go **down**. Current baselines (all in
  `tests/unit/test_kernel_contracts.py`): silent-swallow **214** (`:26`), private-import **22**
  (`:27`), dead-flag **0** (`:108-122`). Web gates (blocking): `lint:tokens` 0, `lint:format` 0,
  `lint:elements` raw-`<button>` baseline **204** (`web/scripts/check-raw-elements.mjs:24`).
- Never write `except: pass` / `except Exception: pass` — the only sanctioned swallow is
  `aughor.kernel.errors.tolerate()` (334 call sites; logs + counts + journals).
- Git: dated branch `YYYY-MM-DD-<topic>`; commit as you go; squash-merge when CI green;
  `Co-Authored-By:` trailer. Read CI with `gh run list --branch <b>` (**not** `gh pr checks` —
  PAT-blocked; and `gh run watch --exit-status` has returned 0 on a FAILED run — always confirm
  via `gh run list`).
- CI is **advisory** (GitHub Free private repo, no branch protection). Green-before-merge is a
  self-enforced invariant. Do not merge red.

### 0.2 Backend conventions
- **New/changed endpoint ⇒ regenerate the typed client**: `cd web && npm run gen:api` and commit
  `web/lib/api.gen.ts` — the CI `codegen` job fails on any drift, even if you only consume the
  endpoint via hand-written wrappers in `web/lib/api.ts`.
- **New SQLite store checklist** (all four or the contract tests fail):
  1) open through `aughor/db/sqlite_util.py` `tune()` (contract test
     `test_every_store_connect_site_is_tuned`);
  2) default path under `data/` resolved via `resolve_db_path` (`sqlite_util.py:44-53`) with an
     `AUGHOR_*_DB` env override;
  3) register that env var in the `tests/conftest.py:13-72` redirect block (hermeticity);
  4) schema evolution via `aughor/db/migrations.py` `run_migrations` (PRAGMA `user_version`,
     additive-only). Migrate columns by **`PRAGMA table_info` probe**, never `try/except-pass`
     ALTER (swallow-ratchet bait).
- Feature flags: one registry — `aughor/kernel/flags.py` `FLAG_ENV` (+ `FLAG_DEFAULT`,
  `FLAG_META`). Any `flag_enabled("literal")` must name a registered flag (dead-flag ratchet).
  New behavior ships **flag-gated, default-off, byte-identical when off**; promote defaults only
  after live verification. Runtime overrides go through `GET/PUT /system/flags`.
- Resolution precedence: ledger-kv override › env › `FLAG_DEFAULT` › False
  (`flags.py:293-298`).
- Model policy: the strong pinned coder model is `glm-5.2:cloud` (note the hyphen — `glm5.2:cloud`
  404s). Runtime config pins coder over the `.env` default.
- Live-data caution: any real app/investigation run writes live stores. For live verification,
  isolate with the `AUGHOR_*` env overrides, then `git status` and revert unintended tracked
  changes before committing. Prefer the seeded fixture (`aughor seed` → `data/aughor.duckdb`,
  scenario in `aughor/samples/scenario.py`) or synthetic DuckDB for deterministic logic.

### 0.3 Web conventions
- Primitives: `<Button>` from `components/ui/button` — **never** raw `<button>` (ratchet).
  Numbers/dates through `@/lib/format` (formatting gate). Status colors through
  `components/brief/StatusChip.tsx` `chipTone()` — hue vocabulary is **blue/red only** (no
  `--green4`/`--amber4` tokens exist).
- Tokens: the live theme layer is `web/aughor-v2/theme/tokens-v2.css` (it **shadows**
  `web/styles/tokens.css` by import order — the v1 file's values are stale/dead; don't read it as
  truth). Tailwind v4 arbitrary values must be `[var(--x)]`, **not** `[--x]` (silently dropped).
  Keep `@import` lines bare — a trailing same-line comment silently drops the import.
- Next 16 holds a **single-instance lock** per directory — you cannot start a second dev server in
  the same working tree; navigate to the running one on :3000. Prod preview: build and serve on
  **:3210** (`aughor-web-prod` launch config; :3001/:3210 are the CORS-allowed prod ports).
- React dev **StrictMode double-fires effects** — before "fixing" a duplicate fetch, confirm it
  reproduces in a prod build (`npm run build && npm start`).
- `uvicorn --reload` can leave an orphaned stale worker holding :8000 (`start.sh` kills by port
  for this reason). If behavior doesn't match code, suspect a stale worker first
  (engineering-principles §3: BUILT ≠ WIRED).

### 0.4 Working state at time of writing
- Dev servers left **running**: api :8000 (serverId in session), web :3000.
- `agents.db` (repo root) is **tracked in git and dirty** — contains 2 demo agents
  (“Luxury Revenue Analyst”, “Customer Analytics Agent”). WP-4 resolves this; until then do not
  commit its churn.
- Demo flags are ON at runtime via ledger overrides — notably `ai_sql` (“In-SQL AI operators”,
  labeled `override` in Settings→System). `capabilities.auto` (Auto-mode master) is ON with 6
  auto-eligible capabilities. Reset these via `PUT /system/flags` when demos end.
- Live connection `luxexperience` (33-table multi-schema) exists in the registry; the workspace
  briefing/insights shown in the UI come from it.

---

## 1 · Verified findings (the evidence base)

### 1.1 Trust plane — coverage audit (core-differentiator claim)

**Claim under test:** “deterministic guards keep fabricated numbers out of *every* answer” and
“all depths share one SQL-safety pipeline (`sql/safety.py preflight_repair`)”.

**Coverage table** (Read-only gate = AST `readonly.is_mutating`/`disallowed_functions` via
`_security_pre` + always-on `_validate` keyword screen; Battery = `preflight_repair` and/or
fanout/grain/join/filter/E1 guards):

| Product path | Executes SQL at | Read-only gate | Correctness battery | Gap |
|---|---|---|---|---|
| Quick/Insight (chat SSE) | `routers/investigations.py:1683` (`db.execute("chat", …)`) | YES | YES — `preflight_repair` @`:1675` + inline fanout/scope/filter/grain/idmath/chasm; caveats → streamed headline @`:1738,1751,1762,1776` + Trust Receipt | none material |
| Deep/ADA | `agent/investigate.py:548` → `sql/executor.py:123` `execute_guarded`; exec @`executor.py:183` | YES | YES — `preflight_harden` @`:152` + live join/filter/grain → retry | live-detected warnings dropped if retry fails (F4) |
| Explorer (Scout background) | `explorer/agent.py:579/630/887` (`__explorer__`, force-audited via `db/connection.py:43`) | YES | **PARTIAL — its own inline battery, NOT `preflight_repair`** | drift (F2) |
| Query Builder | `routers/query.py:100` | YES — `gate_user_sql` @`:48` | NO (raw user SQL by design) | no fanout/grain caveat |
| Saved queries | re-run through query-builder path | YES (inherits) | NO | inherits |
| **Monitors** | `monitors/runner.py:27,60` (`__monitor__`, audited) | YES | **NO — none** | scheduled user `custom_sql`, unguarded numbers (F5) |
| Briefing metric-move | `routers/exploration.py:443` (`__brief_metric_move__`) | **PARTIAL — AST gate skipped** (label not audited) | NO | F8 |
| Custom-agent evaluate | `user_agents/quality.py:142,152` (`__agent_eval_ref__`/`__agent_eval_gen__`) | **PARTIAL — labels not audited → AST gate skipped; generated SQL ungated** | NO | F3 |
| Insight grounding re-exec | `routers/exploration.py:1164` (`__ground__`) | PARTIAL (same label issue) | NO | F8 |
| Program planner (DATA steps) | `agent/program_planner.py:303` `execute_guarded(deterministic-only)` | YES (`gate_user_sql` @`:381`) | PARTIAL — guards run, **caveats dropped** | F4 |
| Semops / prompt() UDF | `routers/query.py:201`; `semops/ai_sql.py` | YES — `gate_user_sql` @`:177` | N/A | call-cap governed |
| Exports / Playbook / Actions | no SQL (actions has SSRF guard @`actions/executor.py:100`) | N/A | N/A | — |
| MCP | `mcp/server.py` proxies REST only — **no raw-SQL tool** | inherited | inherited | strength |

**Findings:**
- **F1 — the unified Trust plane is dormant.** `aughor/trust/__init__.py:43` composes
  readonly+E1+preflight+join+grain behind `verify(artifact, scope)`, but every consumer flag
  defaults off: `trust.verify_facade` (`routers/query.py:709`), `trust.verify_live`
  (`sql/executor.py:162`), `capability.pipeline_live` (`capability/pipeline.py:65`).
  `FLAG_DEFAULT` contains only `ask.clarify: True` (`kernel/flags.py:67`). BUILT+WIRED+TESTED but
  not LEVERAGED.
- **F2 — Explorer does not call `preflight_repair`.** `explorer/agent.py:2939` *comments* “the
  same CHESS value-index guard Insight/ADA get via preflight_repair” but implements
  `bind_filter_literals` + `dry_run` + `SqlWriter.fix` inline (`:2941-3005`), `defan` @`:3097`,
  `check_join_value_domains` @`:3029`; it omits the `repair_identifiers` step `sql/safety.py:53`
  runs. Note: the ROADMAP WS2 claim “wired into ALL THREE paths” refers to `agent/explore.py`
  (the deep-graph explore mode); the **Scout** (`explorer/agent.py`) kept its own copy. Both
  statements are true; the parity test covers the three answer paths, not Scout.
- **F3 — custom-agent evaluate bypasses the AST gate.** `user_agents/quality.py:142,152` labels
  are not in `_AUDITED_AGENT_LABELS` (`db/connection.py:42-50`) → `_security_pre` skipped.
  `reference_sql` is `is_mutating`-checked only at golden creation (`routers/agents.py:234`,
  positive-detection-only), generated eval SQL not at all. Backstops: `_validate`
  (`connection.py:431`, keyword regex) + engine read-only — see F6.
- **F4 — caveat-swallow seam.** `QueryResult` (`platform/contracts/execution.py:37-47`) has **no
  caveats field**; `execute_guarded` uses guard findings only to drive the LLM retry and returns
  the raw result dropping them when no fixer is supplied (`sql/executor.py:230-231`) — exactly the
  program-planner deterministic mode and any unaccepted ADA retry. ADA re-derives a caveat via
  `verify_insight` with `conn=None` (`agent/investigate.py:894-897`) — static only, so a **live**
  value-disjoint join detected at execute time surfaces no caveat.
- **F5 — monitors run scheduled user `custom_sql` with zero correctness guards**
  (`monitors/runner.py:39` returns it verbatim; `:27,:60` execute). Read-only is enforced; grain/
  fan-out is not — a wrong-grain SUM silently mis-values a metric and then alerts on it.
- **F6 — engine-level read-only hole:** local DuckDB opens `read_only=True`, Postgres sets
  `default_transaction_read_only=on` (`db/connection.py:663,859`), but **remote DuckDB
  (MotherDuck/S3) opens `read_only=False`** (`connection.py:661-663`). `_validate`'s keyword list
  (`connection.py:423`) misses AST-only vectors (`SELECT … INTO`, `lo_export`, `setval`,
  `pg_read_file`, `version()`), which only `_security_pre` catches — and that is skipped for
  non-audited dunder labels (F3/F8 paths).
- **F7 — E1 `run_trust_checks` (date-boundary / lexicographic / text-vs-numeric footguns) never
  runs on live answers** — only `/query/validate` (`routers/query.py:693`) and the dormant façade
  (`trust/__init__.py:80`).
- **F8 — `__brief_metric_move__` (`exploration.py:443`) and `__ground__` (`exploration.py:1164`)
  re-execute stored SQL with the AST gate skipped** (non-audited labels). Low risk (internal SQL
  provenance) but inconsistent with explorer/monitor treatment.

**Strengths (don't regress):** chat/ADA guard depth with caveats reaching the SSE headline +
receipt; defense-in-depth read-only with fail-closed `_security_pre` (`connection.py:100-112`);
force-audited background labels; MCP exposing no raw-SQL tool; `gate_user_sql` consistently on
user-SQL endpoints.

### 1.2 Autonomy — reality vs. claim

**Verdict: semi-automatic.** Exploration triggers, exhaustively:
1. Auto **once** on connection create — `create_connection` → `_kickoff_exploration(auto=True)`
   (`routers/connections.py:132`), silently skipped unless Scout is governance-enabled
   (`routers/_shared.py:215-222`) **and** tier grants `Capability.AUTO_EXPLORATION`
   (`licensing/capabilities.py:28`) **and** an event loop is live. Failure → log-only, no user
   signal (`connections.py:130-134`).
2. Boot **crash-resume** only (`api.py:376` `_kernel_boot_recovery`, `api.py:344`
   `_boot_canvas_explorers`).
3. Everything else is a **manual POST** (`/exploration/{id}/start|resume|restart|reset|…`,
   `routers/exploration.py:758,617,675,817,774,560`). `api.py:458` states it plainly: “Fresh
   connection explorations still start manually.”

`explore()` (`explorer/agent.py:667`) is a finite phase pipeline (NULL_MEANING → … → SYNTHESIS →
COMPLETE, `:756-827`) that **never re-arms**; schema fingerprints invalidate profile/ontology
caches but do **not** re-trigger Scout; a budget cancel (charter 200k tokens / 600s,
`kernel/agents.py:64`, heartbeat cancel `kernel/jobs.py:238-259`) marks the run FAILED with
partial findings and **no auto-retry** (`explorer/agent.py:851-859`). The frontier is recomputed
from persisted insights (`explorer/frontier.py:103,113,129`; store `explorer/store.py:33,50`) so
coverage survives restarts — the substrate for continuity exists; the trigger doesn't.

Background loops that DO exist: kernel janitor; hourly **ontology** refresh (`api.py:470`,
per-connection `ontology_refresh_hours` only); monitor cron (`monitors/scheduler.py:27`, APScheduler,
started `api.py:523`); brief cron (`briefs/scheduler.py`, started `api.py:532`, opt-in
subscriptions). Monitor `_job` calls `run_monitor` **directly, not through the kernel**
(`scheduler.py:36-65`) — Watcher/Briefer charters are `reserved=True` (`kernel/agents.py:80-89`),
so monitor/brief warehouse SQL is **unmetered and uncancellable**; metering explicitly excludes
money/bytes-scanned (`kernel/metering.py:15-19`).

Related good bits: anti-flap debounce (`monitors/runner.py:100-112`); global concurrency cap
`AUGHOR_MAX_CONCURRENT_JOBS=8` (`jobs.py:91`); lower-only deployment token ceiling
(`agents.py:181-189`); per-domain query cap ~15 (`explorer/store.py:156-164`); the known
large-workspace budget issue (33-table luxexperience cancels at 600s before briefing-ready —
ROADMAP “Large-workspace exploration budget”).

### 1.3 Backend architecture

- `api.py` (604 LOC) is a clean composition root: 0 inline endpoints, 30 `include_router` calls
  (`api.py:575-604`). The monolith moved down a level: `routers/investigations.py` **3,561 LOC /
  92 defs / 22 endpoints / 191 lazy imports** (chat + HITL + history + outcomes + reindex — the
  god router); `routers/exploration.py` 1,226 LOC / 35 endpoints.
- `agent/investigate.py` **6,321 LOC / 137 defs / 143 lazy imports** — the ADA engine; cohesive
  domain, accreting file. Cohesive-but-huge: `explorer/agent.py` 3,994; `sql/fanout.py` 1,557;
  `tools/profiler.py` 1,536; `agent/nodes.py` 1,535.
- **Cycle debt is masked by function-local imports:** ~1,682 function-local `aughor.*` imports vs
  ~429 module-level. Layering leaks upward: `kernel/jobs.py:389` → `routers._shared` (worst),
  `agent/nodes.py:1259` → `routers._shared`, `sql/writer.py:428` → `agent.prompts`,
  `verify/gate.py:14` → `agent.state` **at module level**.
- The enforced boundary holds: `platform → agent` imports = 0
  (`tests/unit/test_platform_agent_boundary.py`); `QueryResult` contract inverted across 19
  modules. But `HostCapabilities` (`platform/contracts/host.py:9-13`) self-documents as bypassed;
  `capability/registry.py` has 2 consumers, `agent/modes/registry.py` 1.
- Error hygiene: 1,222 `except Exception`, 3 bare `except`; dominant pattern is `tolerate()`
  (334 sites) then plain logging (~253), re-raise rare (~47). ~152 silent `pass`/`continue`
  swallows remain (ratchet baseline 214 counts a superset definition).
- Telemetry is a real single seam (`telemetry.py`: Langfuse/OTel env-activated `:35,:62`; MLflow
  flag-gated per-call `:97-126`; all failures degrade to no-op).

### 1.4 Config & persistence

**Flags:** `FLAG_ENV` = **40 flags**, 1 default-ON (`ask.clarify`), 6 auto-eligible under the
`capabilities.auto` master (`flags.py:242-245`), all UI-surfaced with `FLAG_META` copy; dead-flag
ratchet keeps registry⊇usage. **But** ≥4 parallel mechanisms exist:
1. the registry;
2. **unregistered bare `os.getenv` behavioral toggles, invisible to Settings** — notably
   `AUGHOR_UNIFIED_ASK` **default-ON** (`routers/investigations.py:3153`), `AUGHOR_KB_ENABLED`
   **default-ON** (`semantic/kb_retriever.py:31`), `AUGHOR_AUTOSEED` **default-ON**
   (`semantic/autoseed.py:28`), `AUGHOR_PLAN_GATE` (`investigations.py:2308`),
   `AUGHOR_SOMA_CLARIFY` (`investigations.py:1455`), `AUGHOR_CONTEXT_SURFACE`
   (`investigations.py:2274`), `AUGHOR_DECLARATIVE_MODES` (`agent/modes/registry.py:29`),
   `AUGHOR_ACTION_APPROVAL` (`govern/actions.py:66`), plus `AUGHOR_CONSISTENCY_CHECK`,
   `AUGHOR_UNIFORM_CONVERGENCE`, `AUGHOR_PRIOR_ANALYSES`, `AUGHOR_QUERY_LOG_MINING`;
3. licensing Capabilities (tier);
4. `AUGHOR_REQUIRE_IDENTITY` double-gate with `RBAC_SSO`.
   Phantom docs-only flags (do NOT reference as existing): `obs.task_table`, `ask.context_receipt`.
   Redundant pair: `ada.adversarial_verify` superseded-for-cost by `ada.adversarial_high_stakes`
   (`flags.py:171`); `ada.causal_drill` inert when parallel lenses on (`flags.py:163`).
   **Flag overrides are GLOBAL** — one ledger-kv row (`flags.py:18,290,320-327`), no org scoping.

**Stores:** ~25 runtime stores. Hermetic via `tests/conftest.py:13-72` redirects: system ledger,
registry, history, verdicts, ambiguity_ledger, trusted_programs, evidence, metastore, workspaces,
audit, canvas/artifacts, monitors, orgs, savedquery, volumes, rbac, pack_deltas/bindings,
checkpoints, idempotency, briefs, metrics/glossary (temp copies), fixture/samples, agents.
**Four NOT hermetic (no env override, hardcoded `data/`):**
- matcache — `db/matcache.py:39` (`data/mat_cache.duckdb`, 2.8MB live artifact);
- episodes — `explorer/episodes.py:21,29-30,44` (`data/episodes_{conn}.jsonl`);
- memory — `memory/__init__.py:28`, `memory/skills.py:26,323`, `memory/trust.py:36`
  (`data/agent_runs.json`, `data/learned_actions.json`);
- actions — `actions/store.py:14-15` (`data/action_triggers.json`, `data/action_logs.json`, 99KB live).
  Reachable from 2–5 test files each; **no global “data/ untouched” sentinel** exists
  (`test_store_hermeticity.py` covers only glossary/metrics).

**agents.db:** the only runtime DB tracked in git; default path is bare `"agents.db"` at repo root
(`user_agents/store.py:42`) — escaped the `data/*.db` ignore; a late `/agents.db*` ignore rule
can't untrack it; store uses ad-hoc `PRAGMA table_info` ALTER, not the migrations framework
(`store.py:51-58`); rows carry `owner`, **no `org_id`**.

**Migrations:** framework adopted by 10 stores (ledger, registry, history, verdicts,
ambiguity_ledger, trusted_programs, workspace, metastore, audit, pack_bindings); ad-hoc DDL for
agents, matcache, episodes, evidence_ledger, canvas/artifacts, monitors, idempotency, checkpoints.

**Tenancy:** org-scoped: registry, verdicts, ambiguity_ledger, trusted_programs, history, rbac,
ledger jobs/artifacts/lineage. **Global:** flag overrides, evidence_ledger (0 `org_id` refs),
agents.db, matcache (file-global; tenancy is an **opt-in per-call key fold** —
`matcache.py:17-25,66-71`, default `None` = shared legacy key → a caller that forgets
`tenancy=result_cache_tenancy()` cross-serves principals under `rbac.row_policy`).

### 1.5 Frontend

- Next.js 16 App Router **nominally**: 3 route files; the product is one `"use client"` route
  (`web/app/page.tsx`, 2,308 LOC) swapping ~25 `next/dynamic` panels (`ssr:false`) via local state
  (`page.tsx:32-56`). 99 files under `components/`; `ui/` primitive kit of 9.
- God components: `QueryBuilder.tsx` 2,505; `BriefingPanel.tsx` 2,123; `CatalogScreen.tsx` 1,675;
  `ChatMessage.tsx` 1,309 (disciplined by its registry); `OntologyCanvas.tsx` 1,280;
  `OntologyPanel.tsx` 1,269. `ChatPanel.tsx` is 863 and healthy (delegates to `useChat`).
- **No server-state library**; `lib/api.ts` 3,606 LOC exports **218 fetch fns** consumed via 132
  `useEffect` sites; `react-hooks/set-state-in-effect` downgraded to warn
  (`eslint.config.mjs:19-21`); **ESLint is not run in CI**.
- **SSE robustness inverted:** ledger stream = shared `EventSource`, backoff 1s→30s + last-seq
  resume (`lib/events.ts:4,65-67`); `/ask` = hand-parsed fetch `ReadableStream`
  (`lib/useChat.ts:104`, `lib/investigationStream.ts:379-389`) with **no reconnect/resume**
  (`investigationStream.ts:537` “Stream interrupted”), and **`res.ok` is never checked**
  (`useChat.ts:92-150`) — a non-2xx non-SSE body ends the reader with no `ERROR`/`DONE` → the
  turn spins forever. Abort handling is correct (`useChat.ts:71-73,142-143`;
  `investigationStream.ts:533-535`). `eventsource-parser` is a **dead dependency** (declared,
  never imported).
- **Renderer registry is real and load-bearing:** `TURN_RENDERERS` + `registerTurnRenderer`
  (`ChatMessage.tsx:592-668`), 4 renderers (`dossier`, `ada`, `explore`, `direct`), first-match,
  prepend-override for packs. New shapes went through it.
- Types: `strict: true` (no `noUncheckedIndexedAccess` etc.); ~16 `any`, 14 `as any` all in
  `MonitorsPanel.tsx:483-667` form setters; **zero** `@ts-ignore`. `api.gen.ts` 17,110 LOC
  generated + CI drift gate; `api.ts` still hand-declares 148 interfaces (incremental migration).
- Tokens: two same-name `:root` layers — v1 `styles/tokens.css` (stale Blueprint values) shadowed
  by v2 `aughor-v2/theme/tokens-v2.css` via import order (`app/globals.css:3,5`;
  `tokens-v2.css:12-17`); `components-v2.css` imported separately from `app/layout.tsx:7`.
  2,414 `var(--…)` refs vs **252 hardcoded hex** (concentrations: BrandLogos 45 (legit),
  AugTable 44, SemanticLayerPanel 33, SecurityAuditPanel 21, echarts/theme.ts 16); 2,048
  `style={{` sites across 71/99 files; the token gate only scans `className` (misses hex in style
  objects). `StatusChip` adopted by only 4 components.
- **Zero frontend tests** (no test runner dep at all); CI frontend = tsc + 3 custom gates +
  `next build`. **Zero React error boundaries** (verified: no `ErrorBoundary`/`componentDidCatch`/
  `error.tsx`/`global-error` under `web/`) — one panel throw white-screens the SPA.
- Dead weight: `components/HypothesisCard.tsx` (196 LOC, orphaned), `components/DomainIntelPanel.tsx`
  (667 LOC, orphaned — and `lib/openInBuilder.tsx:7` still claims it's wired),
  `app/chart-lab/page.tsx` (intentional dev harness, unlinked).
- Safe: the single `dangerouslySetInnerHTML` (`QueryBuilder.tsx:608`) escapes via `_escHtml:559`.

### 1.6 Tests & CI

- Layout: `tests/unit/` 280 files, `tests/integration/` 28, `tests/stress/` 3, top-level 16;
  ~2,982 `def test_`. e2e is a **marker**, auto-skipped without `--run-e2e`
  (`tests/conftest.py:105-119`); CI filter `-m "not e2e and not eval"` (`ci.yml:76`).
- CI jobs: backend (uv sync --all-extras --frozen; py3.11 hot path; 3.11/12/13 weekly+dispatch,
  `ci.yml:59-62`), frontend (strict `npm ci`, tsc, 3 gates, `next build` — **no ESLint, no
  tests**), lint (ruff pinned), codegen (offline OpenAPI dump → regen → fail-on-diff,
  `ci.yml:135-163`). `paths-ignore` skips docs/db-only commits. **All advisory** (no branch
  protection).
- Golden gate: `tests/integration/test_golden_reference.py` replays **reference SQL** over all
  golden records (validates the scorer harness, NOT live model accuracy). Live accuracy
  (`evals/run_golden.py --live`, `evals/ratchet.py` full mode) is excluded from CI. Live ratchet
  baseline pinned: mean 0.6551 / exec 1.00 / 420.6k tok on glm-5.2:cloud (protocol
  `evals/README.md`).
- Evals inventory: offline-deterministic = `spider2_probes.py`, `spider2_candidates.py`,
  `interactive.py`, `ambiguity_eval.py`, `mlflow_scorers.py` (needs observability extra to
  import); live-LLM = `model_bakeoff.py`, `its_structural.py`, `ratchet.py` (full), `run_golden.py
  --live`, `ablation_eval.py`, `spider2.py`, `spider2_diag.py`, `sql_accuracy.py`. All imports
  resolve — none stale.
- Blind spots: `routers/approvals.py` and `routers/roles.py` **0** test refs; thin: `catalog.py`
  (1), `knowledge.py` (1), `system.py` (284 LOC, 1); `mcp/` 1 file, `govern/` 1, `process/` 1.
  Well-covered: agent (81 refs), db (66), explorer (41), semantic (38), kernel (35).

### 1.7 Live UI walkthrough (firsthand, 2026-07-12)

Toured: Briefing, Data Canvas, Home, Action Hub, Agents (Overview/Memory), Settings
(Organization/System). Browser console and server error logs clean throughout.

1. **Unstable VERDICT headline.** Two screenshots ~30s apart showed two different headlines
   (“Womenswear Margin Drag Caps Conversion Upside” → “Conversion Collapse Meets Rising
   Concentration Risk”) over the same body text. Server log root cause: **four**
   `POST /exploration/workspace/briefing` per page view — two with `schema=luxexperience`, two
   without — two differently-scoped cached briefs racing; last paint wins. (2× may be dev
   StrictMode; the scoped/unscoped split is real regardless.)
2. **No ask box on Home.** Home = Get-Started cards + stat tiles + recent activity; the composer
   (“Ask anything about your data…”, Auto/Insight/Deep, agent picker) lives only inside a canvas.
   Sidebar has **16 destinations** (Home, Inbox, Data Canvas; Briefing, Investigations, Fleet,
   Agents, Health, Playbook; Catalog, Query Builder, Semantic Layer; Monitors, Action Hub,
   Security & Audit; Settings) — the U5 fold to ~5 workspaces is unfinished. Home empty-state copy
   references a “Metrics panel” that doesn't exist in the nav.
3. **Trust-surface arithmetic.** Agents→Memory shows “ACCEPTANCE **83%** · 3 verdicts”. Backend:
   `GET /verify/verdicts/stats` → `{"counts":{"accept":2,"correct":1,"reject":0},"total":3,
   "acceptance_rate":0.833}` — i.e. `(accept + 0.5·correct)/total`. An unexplained weighted blend
   next to “3 verdicts” reads as an arithmetic error on a trust surface.
4. **Failure states on the happy path:** red “EXPLORER failed · 17q · 89 insights” chip + manual
   Start button as the first element on Briefing (symptom of §1.2 silent auto-kick/budget-cancel);
   the demo agent's only run shows `timed_out` (600s ceiling, §1.2). Honest, but normalized.
5. **Raw numbers in briefing prose:** “906118”, “86966” unformatted (LLM prose bypasses
   `lib/format`); “17q · 89 insights” is insider shorthand; “Synthesized from 8 domains · 88
   findings”.
6. **Perceived performance:** tab switches sit ~3s in a dimmed stale-content state on local
   SQLite-backed queries (fetch-then-render, no optimistic/skeleton swap).
7. **A11y (deferred audit item still fully open):** all 16 sidebar nav buttons expose **no
   accessible name** in the AX tree (`button [ref] → generic "Briefing"` — name not computed);
   keep-alive Workspace panels stay mounted **without `aria-hidden`** (the hidden chat composer
   was fully present in the AX tree behind Action Hub); 204 raw `<button>`s.
8. Nits: “Workspace LOCA” chip truncation (Data Canvas connection column); near-invisible
   low-contrast metadata columns in the Data Canvas table; sidebar footer overlap (avatar/glyph
   overlapping the “Settings” label at ~1280×720); Settings→System “Uptime: 0s” (an artifact of
   `--reload` worker restart re-instantiating `Stats` — `aughor/stats.py:47` — cosmetic, consider
   showing started-at).
9. **Praise (protect these):** Settings→System Capabilities page (tri-state Auto/On/Off, per-
   capability plain-language trigger + active/inactive chips) is excellent; Agent Workspace's
   “MLflow tracing is off — enable `obs.mlflow`…” hint is the right pattern; the disconfirmed-
   hypothesis card (“The hypothesis is disconfirmed: Bologna Interporto has the highest markdown
   exposure at 33.88%…”) is exactly on-brand honesty; the dark MLflow-informed design language is
   coherent across all toured surfaces.

---

## 2 · Work packages

Execution rules for every WP: dated branch; flag-gated default-off unless stated; suite green +
ruff clean + ratchets non-increasing every commit; new/changed endpoints ⇒ `npm run gen:api`;
live verification on the real path with isolated stores; update `ROADMAP.md` §2/§3 when landing.

### Wave 1 — trust correctness (do these first)

---

#### WP-1 · Caveats carried, trust plane promoted, guard coverage extended
**Closes:** F1, F4, F5, F7 (§1.1). **Effort:** 2–4 days. **Priority: #1.**
> **STATUS 2026-07-12: 1a–1e SHIPPED** (branch `2026-07-12-wp1-trust-caveats`, +21 tests,
> live-verified: monitors caveat end-to-end in the UI; create-gate rejected a real bind
> failure). 1c shipped as the TARGETED variant (four labels promoted to
> `_AUDITED_AGENT_LABELS`) — the blanket "gate every internal label" is UNSAFE: platform-
> authored mutations (`alter_column`) are legitimate; see the code comment at the labels
> set.
> **1f SHIPPED (default promotion — the LEVERAGE step)** (branch
> `2026-07-12-wp1f-trust-promotion`). A deterministic live A/B over the real healthy-path
> corpus — 1,837 unique executed statements from the `workspace` + `fixture` connections
> (audit_log, verdict='safe') — replicating exactly what the two flags do live: **0**
> would-be `trust.verify_live` blocks, and after wiring **real column types** into the E1
> live checks (new `connection_column_types`, cached per connection), the only E1 caveat
> the name heuristic raised (a DATE column named `acquired_at` — a false positive)
> disappeared, leaving only a genuine timestamp-boundary footgun. `FLAG_DEFAULT` now
> carries `trust.verify_live` / `trust.e1_live` / `trust.verify_facade` = True (operators
> can still disable via env `=0` or a runtime override). Live-verified on the running server:
> `/query/validate` BLOCKs a DELETE by default; the fixture DATE column raises no E1
> caveat; a real `/ask` answered cleanly with no spurious caveat. **A key fix rode along:**
> the executor keyed the col-types cache on a non-existent `connection_id` attribute
> (`getattr(conn, "connection_id", "")` → always `""`), which would have cross-served one
> connection's types to all others — corrected to `_connection_id`, empty ids skip the
> cache, and a regression test locks the DATE-no-FP / TIMESTAMP-still-fires contract.

**1a — `QueryResult.caveats` (the swallow seam).**
- Add `caveats: list[str] = field(default_factory=list)` (match existing dataclass/pydantic style)
  to `QueryResult` in `platform/contracts/execution.py:37-47`. Additive — 19 importing modules
  unaffected by a defaulted field.
- In `sql/executor.py` `execute_guarded`: where guard findings currently only feed the retry and
  are dropped when no fixer is supplied or the retry is rejected (`executor.py:230-231`), attach
  the human-readable guard messages to `result.caveats` before returning. Keep messages short,
  deterministic, prefixed by guard name (existing note style).
- Consumers to wire:
  - `agent/program_planner.py:303` (deterministic DATA steps): copy `result.caveats` into the
    step receipt/output so plan-program answers carry them.
  - ADA `_execute_safe` path (`agent/investigate.py:548` region): merge live `result.caveats`
    into the finding's `trust_caveat` handling instead of relying solely on the static
    `verify_insight(conn=None)` re-derivation (`investigate.py:894-897`). Live-detected beats
    static re-derivation; do not double-append duplicates.
- Tests: unit — `execute_guarded` deterministic-only mode returns caveats on a synthetic fan-out
  join (temp DuckDB, no LLM); planner DATA step carries the caveat; ADA finding gains
  `trust_caveat` from a live-detected filter-domain mismatch. Extend
  `test_guard_parity_all_three_paths_share_the_hardening` to assert caveat propagation.

**1b — monitors: guard the numbers that alert (flag `monitors.guarded`, default-off).**
- At **create/update** (`routers/monitors.py` create_monitor/update): for `custom_sql`, run
  `gate_user_sql` (parity with query-builder) + a `dry_run` bind check; reject on mutation/bind
  failure with a 422 carrying the reason. (No LLM, no rewriting.)
- At **run** (`monitors/runner.py:27,39,60`): under the flag, run the cheap deterministic probes —
  fan-out/grain check via the existing de-fan detector and, when the monitor targets a governed
  metric, the grain guard — and attach any finding as an `alert.caveat` (new field on the alert
  record + rendered in MonitorsPanel). **Never rewrite user SQL silently**; caveat-and-deliver.
- Migration: alerts store gains a nullable `caveat` column (monitors store is ad-hoc DDL — adopt
  `run_migrations` for this store while touching it; see rulebook 0.2).
- Tests: create-time 422 on mutating custom_sql; run-time caveat on a synthetic chasm-trap
  monitor; anti-flap unaffected. Frontend: caveat renders on the alert row (`MonitorsPanel.tsx` —
  the `as any` form file; keep types clean for the new field).

**1c — audit-by-default for internal labels (close F3/F8 read-only skips).**
- `db/connection.py:42-50`: invert the posture. Split the two concerns:
  - **AST gate (`_security_pre` mutation check): run for ALL labels, always.** It is in-memory
    and cheap; there is no legitimate internal mutation-by-SELECT path.
  - **Audit-log writes: keep the explicit allow-list** (perf/noise: `__ground__` and metric-move
    are chatty) — i.e., decouple “gate” from “audit row” inside `_security_pre` (today skipping
    audit also skips the gate).
- Specifically ensure gated: `__agent_eval_ref__`, `__agent_eval_gen__` (`user_agents/quality.py:
  142,152`), `__brief_metric_move__` (`exploration.py:443`), `__ground__` (`exploration.py:1164`).
- Also fix positive-detection-only at `routers/agents.py:234`: `is_mutating` returning
  parse-failure must **fail closed** for golden `reference_sql` (reject unparseable reference SQL
  with a clear message — goldens are user-authored, a parse failure is a user error).
- Tests: an `INTO`-style AST-only vector under `__agent_eval_gen__` is blocked; existing audited
  paths unchanged (audit-row counts stable); fail-closed golden creation.
- **Gotcha:** `_security_pre` fails closed on gate error (`connection.py:100-112`) — preserve
  that; do not add a tolerate() around the gate.

**1d — remote-DuckDB read-only (F6).**
- `db/connection.py:661-663`: attempt `read_only=True` for remote/MotherDuck attaches; if the
  driver/endpoint rejects it, fall back to read-write **and record a connection-level
  `engine_read_only=False` fact** surfaced in the connection's Security panel row, so the residual
  risk is visible. (With 1c making the AST gate universal, the practical hole closes; this is
  belt-and-suspenders + honesty.)
- Test: connection factory unit test asserting the read_only attempt + recorded fact on fallback.

**1e — E1 checks on live answers (flag `trust.e1_live`, default-off).**
- Call `run_trust_checks` (`sql/trust_checks.py:100`) on the final SQL of the chat path (beside
  the existing caveat assembly at `investigations.py:1738` region) and on ADA phase SQL (inside
  `execute_guarded` under the flag, appending to `result.caveats` from 1a). WARN-only labelled
  caveats, never rewrites (E1 contract).
- Tests: date-literal-boundary and lexicographic-order footguns each produce a labelled caveat on
  the chat path; byte-identical when flag off.

**1f — promotion path (the actual LEVERAGE step).**
- After 1a–1e land: run a live A/B on luxexperience + the seeded fixture (one real /ask quick, one
  deep, one monitor tick with isolated stores), confirm zero false-positive caveats on the healthy
  paths, then flip `FLAG_DEFAULT` for `trust.verify_live` (ADA executor path) and `trust.e1_live`,
  and update FEATURES.md §2 wording. `trust.verify_facade` (the `/query/validate` consumer) can
  flip immediately — additive response field.
- **DoD:** coverage table §1.1 re-audited with every “NO/PARTIAL” in the battery column either
  closed or explicitly accepted-by-design in FEATURES.md; monitors caveat live-verified on a real
  cron tick; suite green; ratchets flat.

---

#### WP-2 · /ask stream robustness + error boundary
**Closes:** §1.5 stream findings. **Effort:** 1–2 days. **Priority: #2.**
> **STATUS 2026-07-12: SHIPPED** (branch `2026-07-12-wp4-wp2-hygiene`). `consumeStream`
> guards `res.ok` + `content-type: text/event-stream` (kills the stuck-spinner-on-error
> class); on a mid-run drop it captures `investigation_id` from the `start` event and
> `recoverAfterDrop` polls `GET /investigations/{id}` to a terminal state (render+DONE /
> ERROR), never a bare "interrupted". New `ErrorBoundary.tsx` (class comp, `<Button>`)
> wraps `ChatMessage` + the five god panels in `page.tsx`. Dead `eventsource-parser`
> removed. **Scout finding:** NO SSE re-attach endpoint exists → poll-for-final-report is
> the correct design (deep runs are kernel-decoupled, so they survive the disconnect).
> **Live-verified:** a real /ask streamed + rendered through the new guard (content-type
> `text/event-stream; charset=utf-8` passes `.includes`), inside the boundary, 0 console/
> server errors. tsc + 3 web gates green. *True in-place re-render of a recovered report
> (vs the current guarded render on drop) can be tightened later; the reconnect-vs-poll
> decision is settled.*

- **`res.ok` check** in `web/lib/useChat.ts` (`:92-150`): before handing to `consumeStream`, if
  `!res.ok` → read `await res.text()` (bounded), dispatch the existing `ERROR` action with
  `HTTP <status>` + first ~200 chars, and end the turn (no infinite spinner). Also guard
  `res.body == null`.
- **Content-type sanity:** if `content-type` isn't `text/event-stream`, treat as error (the
  Next dev overlay/HTML-error case).
- **Error boundary:** new `web/components/ErrorBoundary.tsx` (class component,
  `componentDidCatch`, fallback = compact card with the error message + a “Reload panel” button
  that resets boundary state). Wrap: (a) each lazy panel at the switch in `app/page.tsx:32-56`
  region, (b) the chat turn list (one thrown renderer must not kill the composer). Raw `<button>`
  ratchet: use `<Button>`.
- **Reconnect-or-recover for deep runs:** scout first (~30 min): does an SSE re-attach endpoint
  exist for a running investigation (check `routers/investigations.py` for a stream-by-id GET and
  the `_stream_resume` machinery used by the feedback door)? If yes → on network error while a
  deep run is in flight, re-attach and continue. If no → **recover, don't rebuild**: on drop, poll
  `GET /investigations/{id}` every 5s (bounded ~5 min) and when terminal, fetch the final report
  and render it with a “stream dropped — recovered result” note. Emit an interim “reconnecting…”
  status via the existing `STATUS_TEXT` channel.
- Remove the dead `eventsource-parser` dependency from `web/package.json` (verified unused).
- **Live verification:** start a deep /ask on the fixture; kill the API mid-stream (`start.sh
  --stop` then restart); confirm the turn shows reconnect→recovered (or the error card), never a
  stuck spinner. Then a 500 case: temporarily point the web proxy at a dead port and confirm the
  ERROR path renders.
- **DoD:** no code path lets a turn end without exactly one of DONE/ERROR dispatched; boundary
  catches a deliberately-thrown renderer error in dev without white-screening; gen:api not needed
  (no backend change) unless the scout finds a new endpoint is required.

---

#### WP-3 · Run the P7 bake-off and pin the coder model (decision debt, not code)
**Effort:** hours (mostly wall-clock). **Priority: #3 — unblocks quality everywhere.**
> **STATUS 2026-07-12: DONE.** 3-model 53q run completed: kimi-k2.7-code 63.3% ·
> minimax-m2.5 63.1% · glm-5.2 63.0% exec-acc — statistical tie at n=53 (all 100%
> trust/exec-success). **Decision: keep `glm-5.2:cloud`** (no candidate beats the
> incumbent; a switch would re-pin the live-ratchet baseline for zero proven gain).
> Recorded in ROADMAP §3 P7; raw results `evals/bakeoff_out/*.json`.

- Command (per ROADMAP §0): `uv run --extra observability python -m evals.model_bakeoff --models
  "glm-5.2:cloud,<candidate-1>,<candidate-2>"` — one env-isolated subprocess per model,
  deterministic scorers (golden exec-accuracy + trust battery + exec-success), results to the
  `aughor-bakeoff` MLflow experiment + printed ranking. A previous 3-model run (glm-5.2 vs
  minimax-m2.5:cloud vs kimi-k2.7-code:cloud, 53q) was launched 2026-07-11 — **check
  `evals/bakeoff_out/*.json` for completed results before re-running.**
- Gotchas: model ids need exact hyphens (`glm-5.2:cloud`); providers cache
  `AUGHOR_CODER_MODEL` per process (that's why subprocess arms exist); mlflow-skinny has no
  SQLAlchemy → file store only (`MLFLOW_ALLOW_FILE_STORE=true`), never `sqlite:///`.
- Decision rule: pin the winner on mean golden accuracy, tie-broken by trust-battery pass rate,
  then tokens/q. Apply via the runtime model-role config (the same mechanism WS3 used to pin
  glm-5.2 for the live ratchet), update `evals/README.md` protocol + ROADMAP P7 → ✅, and re-pin
  the live ratchet baseline if the model changes.
- **DoD:** a written ranking table in the PR/commit, the coder role pinned, ROADMAP updated.

---

#### WP-4 · Persistence hygiene: agents.db relocation + the four hermeticity holes
**Closes:** §1.4 store risks 1–2. **Effort:** ~half day. **Priority: #4.**
> **STATUS 2026-07-12: SHIPPED** (branch `2026-07-12-wp4-wp2-hygiene`). agents.db default
> `"agents.db"` → `data/agents.db` + a one-time VACUUM-INTO relocation shim (skips when
> `AUGHOR_AGENTS_DB` is set, so tests never read a repo-root file) + migration-framework
> adoption (v2–4 replacing the probe-ALTER); `git rm --cached agents.db`. Env overrides
> `AUGHOR_MATCACHE_DB` / `AUGHOR_EPISODES_DIR` / `AUGHOR_MEMORY_DIR` / `AUGHOR_ACTIONS_DIR`
> close the four holes; new `aughor/memory/paths.py`; episode readers unified via
> `episodes_dir()`. conftest redirects all four; hermeticity + relocation + migration
> tests added. **Live-verified:** API start relocated the root DB into `data/`, both demo
> agents preserved & served; targeted suite left `data/` byte-identical (md5 match).
> *Note: the redundant per-test matcache monkeypatch was LEFT — it overrides `_conn` (the
> connection object), which is a valid, path-independent hermetic mechanism, not the hole.*

- **agents.db →** `resolve_db_path("agents.db")` (i.e., `data/agents.db`, env `AUGHOR_AGENTS_DB`
  already exists) in `user_agents/store.py:42`. One-time adoption shim at store init: if legacy
  root `./agents.db` exists and the resolved path doesn't → copy it over (preserves the 2 demo
  agents), log once. Then `git rm --cached agents.db` (the `/agents.db*` ignore already exists) —
  **do this in the same commit** so the tree goes clean. Adopt `run_migrations` for this store
  while touching it (replace the ad-hoc `PRAGMA table_info` ALTER block `store.py:51-58` with
  Migration entries; current schema = user_version 1 baseline).
- **Env overrides + conftest registration** (rulebook 0.2 checklist) for:
  - `AUGHOR_MATCACHE_DB` — `db/matcache.py:39` (`_CACHE_PATH` via `resolve_db_path`);
  - `AUGHOR_EPISODES_DIR` — `explorer/episodes.py:21,29-30,44`;
  - `AUGHOR_MEMORY_DIR` — `memory/__init__.py:28`, `memory/skills.py:26,323`, `memory/trust.py:36`;
  - `AUGHOR_ACTIONS_DIR` — `actions/store.py:14-15`.
  Remove the now-redundant per-test monkeypatch in `tests/unit/test_matcache_tenancy.py:36`
  (keep the test, point it at the env override).
- **Sentinel:** extend `tests/unit/test_store_hermeticity.py` with per-store redirect assertions
  for the four new envs (same pattern as glossary/metrics). Do **not** add a whole-`data/`
  mtime-hash sentinel — the dev servers legitimately write `data/` while a local suite runs; the
  per-store pattern is the robust version.
- **Gotcha:** module-level path constants are captured at import (`conftest.py:26-27` comment) —
  the conftest `setdefault` must stay ahead of any app import; follow the existing block's order.
- **DoD:** full suite leaves `data/` byte-identical (spot-check `mat_cache.duckdb` and
  `episodes_*.jsonl` mtimes before/after a local full run); `git status` clean after app use;
  demo agents still listed in the UI after relocation.

---

#### WP-5 · Briefing: one fetch, one scope, stable verdict
**Closes:** §1.7-1. **Effort:** hours. **Priority: #5.**

- Scout `web/components/BriefingPanel.tsx` (2,123 LOC) + its mount in the Intelligence workspace:
  find why one visit issues both `POST /exploration/workspace/briefing?schema=<s>` **and** the
  unscoped variant (two call sites? a scope-default race where the schema select hydrates after
  the first fetch?). Reproduce via `preview_logs` while loading the Briefing tab.
- Fix: single-flight per `(workspace, schema)` — an in-module inflight map keyed by scope in the
  fetch helper (or lift the briefing fetch into one owner component and pass down); **never fire
  the unscoped variant when a schema is selected**; render the scope on the VERDICT card
  (“Briefing · luxexperience” chip) so two scopes can't be confused.
- **StrictMode caveat:** verify the duplicate count in a prod build (`npm run build && npm start`
  on :3210) before attributing — dev double-invoke may account for 2 of the 4 calls. The
  scoped/unscoped split is the real bug either way.
- Backend is already cached per scope_key (`exploration.py:551`) — no backend change expected.
- **DoD:** prod build shows exactly one briefing POST per scope per visit; headline stable across
  reload; scope visible on the card.

### Wave 2 — make the claims true (product integrity)

---

#### WP-6 · Continuous exploration (or honest copy) — the headline claim
**Closes:** §1.2. **Effort:** 2–4 days. Flag `explorer.continuous`, default-off → promote.
> **STATUS 2026-07-12: 6a + 6c + 6d SHIPPED** (branch `2026-07-12-wp6-continuous-exploration`).
> **6a** — `aughor/explorer/continuous.py`: a pure `reexplore_decision()` (schema-fingerprint
> change OR staleness window, with a `None`-stored-fp guard so pre-existing runs don't all
> false-fire on first enable) + `plan_reexplorations()` (sync, executor-safe) + async
> `run_continuous_tick()` (spawns on the loop via `kickoff_exploration(auto=True)`); hourly
> lifespan loop `_continuous_exploration_loop` (flag-gated, default-off = a pure sleep). The
> explorer now stamps a connection-level `schema_fingerprint` at the COMPLETE transition (it
> was only ever read before, so it stayed `None`). **6c** — the on-connect + tick governance
> skip now emits an `exploration.skipped` ledger event (was log-only); a re-arm emits
> `exploration.rearmed`. **6d** — README + FEATURES made honest ("keeps learning" not "never
> stops"; "explores in the background" not "continuously"; continuous mode documented as the
> opt-in that re-explores on schema change). **Live-verified on the real `workspace`
> connection**: the actual planner detected a seeded schema-fingerprint change and selected it
> for re-arm (no POST), and did NOT re-arm when the fingerprint matched — state restored
> non-destructively. +14 tests; ruff clean.
> **DEFERRED (noted, lower value):** **6b** auto-resume-once on budget-cancel — the kernel
> stamps `error="budget exceeded: …"` on the job before cancelling (`jobs.py:257`), which
> distinguishes budget-cancel from user-stop, but threading that marker into the exploration
> state + a resume-count is a clean separable follow-up. **Large-workspace budget** (scale
> Scout `time_budget_s` with catalog size) — needs a per-run budget override on
> `kernel().submit`, distinct from this tick. **Promotion to default-on** gated on WP-7
> (background cost metering) so a big cloud warehouse can't get a surprise re-explore bill.
> Also spun off: a task chip to give `explorer/store.py` an `AUGHOR_EXPLORATION_DIR` override
> (same WP-4 hermeticity hole class).

- **6a — staleness/schema re-arm tick.** A periodic loop beside the hourly ontology refresh
  (`api.py:470` pattern): for each ACTIVE connection where Scout is governance-enabled and the
  tier grants `AUTO_EXPLORATION`, re-kick exploration via the existing `spawn_explorer`
  (`routers/_shared.py:65` — keep the kernel-submitted path so budgets apply) when:
  (i) `schema_fingerprint` changed since the last completed run, OR
  (ii) `is_complete()` (`explorer/store.py:59`) and `last_run_age > AUGHOR_EXPLORER_REFRESH_DAYS`
  (default 7). The frontier recompute (§1.2) already makes re-runs incremental — only uncovered
  cuts rank; do not build a new frontier store.
- **6b — auto-resume-once on budget cancel.** In the budget-cancel path
  (`explorer/agent.py:851-859` + `_cleanup` `routers/_shared.py:132-138`): if cancelled on budget
  and `auto_resume_count == 0`, resubmit once after a cooldown (piggyback the tick) with the same
  budget — the frontier makes the second run pick up where the first stopped. Persist the count on
  the exploration state to cap at one.
- **6c — surface autonomy failures.** The silent skips (`connections.py:130-134`,
  `_shared.py:218-222`) and budget-cancels must emit a ledger event that renders as an Inbox item
  (“Exploration didn't start: Scout disabled for this workspace — enable in Fleet”) and drive the
  existing EXPLORER status chip's tooltip. No new UI surface; reuse Inbox + chip.
- **6d — copy alignment.** If (and only if) 6a–6c ship and the flag is promoted default-ON, keep
  the README claims. Until then, PR the README/FEATURES wording to “learns your warehouse on
  connect, keeps watch with monitors, and re-explores on schema change” — the un-shipped
  “never stops learning” phrasing is the single most falsifiable sentence in the repo.
- Also fold in the known **large-workspace budget** item (ROADMAP): scale Scout's
  `time_budget_s` with catalog size (e.g., +60s per 5 tables, cap 1800s) or fan out per-schema
  with independent budgets — the luxexperience 33-table case currently cancels before briefing.
- Tests: tick spawns on fingerprint change (fake registry + stub spawn); no spawn when disabled
  (governance/licensing gates respected); resume-once cap; Inbox event emitted on skip. Live:
  flag on, touch the fixture schema (add a column), watch the tick re-explore within one period.
- **DoD:** a connection left alone for a schema change re-explores without any POST; a
  budget-cancelled run self-resumes exactly once; every silent skip is user-visible.

---

#### WP-7 · Meter the background: monitors + briefs through the kernel
**Closes:** §1.2 cost gap. **Effort:** 1–2 days. Flag `ops.metered_monitors`, default-off → promote.
> **STATUS 2026-07-13: metering core SHIPPED** (branch `2026-07-13-wp7-metered-background`,
> flag `ops.metered_monitors`, default-off). The Watcher/Briefer charters are non-reserved
> with real budgets (Watcher 50k tok / 120s, Briefer 400k / 300s); the monitor + brief cron
> `_job`s route through `kernel().submit(...)` via a new thread→loop bridge
> `submit_background_tick` (the scheduler runs on an APScheduler thread, the kernel on the main
> loop, captured at startup in `_install_context_executor`). The work runs in the
> context-propagating executor, so the run's metering accumulator + Org binding reach the
> monitor/brief SQL — it is now metered (Fleet/`GET /jobs?kind=monitor`), counted against the
> agent's budget, and heartbeat-supervised. `kernel().submit` gained an explicit `org_id` so a
> cross-thread submit stamps the right tenant. Preserves the schedulers' tenant re-bind; the
> manual "test now" endpoint (`trigger_now`) is unchanged (synchronous, already visible).
> **Live-verified** on the running server: a per-minute fixture monitor ran as a `SUCCEEDED`
> **Watcher** job with `cost={query_count:1, rows_returned:1}`. +4 tests (charter wiring ·
> flag routing · no-loop fallback · end-to-end metering with a real loop). Suite green; ruff
> clean; byte-identical when the flag is off.
> **DEFERRED (noted):** **promotion to default-ON** is gated on a large-workspace A/B (the
> Briefer's 300s budget must not cancel a legitimate wide-workspace brief — the same
> large-workspace-budget thread WP-6 deferred); until then it stays flag-gated. **Per-connection
> caps** (`max_monitor_runs_per_hour` + per-day query budget on connection settings + skip-with-
> Inbox) are a separate slice — the per-run **budget** already caps a runaway tick, and the cron
> already bounds frequency, so the rate-cap is a lower-value follow-up (spun off as a task).

- Route `monitors/scheduler.py:36-65 _job` (and the brief scheduler's run) through
  `kernel().submit(...)` with the Watcher/Briefer charters made non-reserved (define real budgets:
  e.g., Watcher 60s/negligible tokens per tick; Briefer 120s) — heartbeat cancellation + metering
  for free. Preserve the org re-bind (`using_org(get_connection_org(conn_id))`) the schedulers
  already do.
- Add per-connection background caps: `max_monitor_runs_per_hour` and a simple per-day query-count
  budget surfaced on the connection settings; exceeded → skip tick + one Inbox alert (not one per
  skip — reuse anti-flap).
- Explicitly **out of scope:** bytes-scanned/$ metering (`kernel/metering.py:15-19` excludes it by
  design; a real $-meter needs per-dialect scan stats — track as a follow-on, don't fake it).
- Tests: a monitor tick appears in kernel metering; a hung monitor query is cancelled by
  heartbeat; caps enforce + alert once. Live: one real cron tick on the fixture with the flag on.
- **DoD:** `GET` fleet/metering surfaces show monitor/brief spend; no unmetered background SQL
  path remains (§1.2 list re-checked).

---

#### WP-8 · Tenancy: fail-closed matcache + org-scoped stores/flags
**Closes:** §1.4 tenancy. **Effort:** 1–2 days (8a/8b) + 8c scoped separately.

- **8a — matcache fail-closed.** `db/matcache.py:17-25,66-71`: compute
  `tenancy = result_cache_tenancy()` **inside** get/put as the default (parameter only as explicit
  override), so no caller can forget it. When RBAC row-policy is active and tenancy resolution
  fails → **skip the cache** (fail-closed miss), never serve the shared legacy key. Keep the
  legacy shared key only when identity is off (localhost mode) — byte-identical single-user
  behavior. Tests: two principals with different row-filters can't cross-serve; localhost hits the
  legacy key (no perf regression).
- **8b — org columns via migrations** for `evidence_ledger.db` (`evidence/store.py:18` — also
  adopt `run_migrations` while there) and `agents.db` (rides WP-4's migration adoption): additive
  `org_id` default `'default'`, stamped from `current_org_id()` on write, filtered on read where a
  read-path exists. Follow the DATA-06 resolution pattern (resource → connection → org) where the
  row keys by conn_id.
- **8c — org-scoped flag overrides (design-gated, do NOT rush).** Today: one global kv row
  (`flags.py:290,320-327`). Proposal: key overrides `(org_id, flag)` with global fallback;
  `PUT /system/flags` writes the caller's org scope when identity is on, global when off; Settings
  UI unchanged visually. **Blocked on a product decision** (should capabilities differ per org on
  one deployment, or is global-by-operator correct for self-hosted?). Write the decision into
  `docs/PLATFORM_ARCHITECTURE.md` first; implement only if per-org wins.
- **DoD (8a/8b):** cross-tenant matcache test red→green; every store in §1.4's “Global” list
  either org-keyed or explicitly documented as deployment-global by design.

---

#### WP-9 · One config surface: fold shadow env toggles into FLAG_ENV
**Closes:** §1.4 fragmentation. **Effort:** ~half day. **Behavior-preserving.**

- For each unregistered toggle in §1.4 list-item 2: add a `FLAG_ENV` entry (keep the existing env
  var name as the mapped env — backcompat free), set `FLAG_DEFAULT` to preserve today's default
  (`unified_ask`/`kb.enabled`/`autoseed` → **True**), add `FLAG_META` copy, and replace the bare
  `os.getenv` read with `flag_enabled("<name>")`.
- Naming: follow the existing dotted convention (`ask.unified`, `semantic.kb`,
  `semantic.autoseed`, `ada.plan_gate`, `ask.soma_clarify`, `ask.context_surface`,
  `agent.declarative_modes`, `actions.approval`, `ada.consistency_check`,
  `ada.uniform_convergence`, `ask.prior_analyses`, `semantic.query_log_mining`) — confirm each
  toggle's actual semantics at its call site before naming.
- The dead-flag ratchet automatically enforces registration; the Settings→System page picks them
  up from FLAG_META for free. Add the env names to `.env.example` with one-line comments.
- **Must be byte-identical:** default resolution for each = today's behavior (watch the
  default-ON trio). Tests: a table-driven test asserting each new flag's default equals the
  legacy `getenv` default; grep-test that no bare `os.getenv("AUGHOR_` behavioral reads remain
  outside the registry (allowlist infra vars: DB paths, budgets, model config).
- **DoD:** Settings→System lists every behavioral toggle; `PUT /system/flags` can flip each at
  runtime; zero behavior change with a clean env.

---

#### WP-10 · Public Trust Receipt (`GET /receipt/{id}`) — the moat, inspectable
**Source:** ROADMAP §3 “single highest-leverage open bet”. **Effort:** ~1 week.

- **Unify:** per-mode receipt routes exist (`/ada/{conn}/{inv}/receipt`,
  `/chat/{conn}/{turn}/receipt`). Introduce a receipt **id** (the kernel ledger artifact id —
  `_write_answer_receipt` + `kernel/ledger.py` already persist lineage) and one
  `GET /receipt/{receipt_id}` resolving either mode. Response contract (draft):
  `{id, created_at, mode, question, connection{id,name,dialect}, executed_sql[{sql, label,
  duration_ms, row_count}], input_tables[], guards[{name, fired, action, caveat}], caveats[],
  confidence{level, capped_by}, data_trust{window, coverage_notes}, model{role, id},
  signature}` — `signature` = HMAC over the canonical JSON with a server secret (document: this
  proves the server issued it, not third-party non-repudiation).
- **Extend:** stamp receipt ids on the Query Builder path (now gated, so it can carry one) and on
  briefing figures (they already carry `BriefFigure.source` — add `receipt_id`).
- **Frontend:** a “Why this number” affordance on ResultFigure / KPI tiles / briefing figures →
  drawer rendering the unified receipt (SQL with copy button, guard list with fired/quiet state,
  confidence + caps). Reuse StatusChip vocab; numbers through `lib/format`. `npm run gen:api`.
- Tests: receipt round-trips for quick/deep/builder; signature verifies + tamper fails; RBAC —
  receipts respect org visibility (resource→connection→org); 404 on foreign org.
- **DoD:** every answer surface can open a receipt by id; the receipt for a guard-fired answer
  names the guard; FEATURES.md gains the “trustworthy by inspection” section.

---

#### WP-11 · IA: ask-on-Home, finish the U5 fold, a11y pass
**Closes:** §1.7-2/7. **Effort:** 2–3 days.

- **Ask-on-Home:** compose the existing InputBox (ChatPanel's composer with Auto/Insight/Deep +
  agent picker) as Home's hero. Submitting from Home: pick the most-recent Data Canvas (or prompt
  to create one when none), route into it with the question pre-filled/fired. No new backend.
- **U5 fold (finish what PART-2 scoped):** target IA ≈ 5 workspaces: Home · Intelligence
  (Briefing/Investigations/Hub/Ontology/Evidence) · Data (Canvas/Catalog/Builder/Semantic) ·
  Operations (Monitors/Action Hub/Security) · Agents (Overview/Memory/Manage/Fleet — exists).
  Mechanical part: fold remaining top-level panels into `<Workspace>` instances with
  `LEGACY_*_LAYER` deep-link maps (pattern proven twice: Operations, Data rails). Known poor fit:
  `CanvasWorkspace` (richer header/eager-mount — PART-2 says likely defer; keep deferring).
  Fix the Home empty-state copy that points at a nonexistent “Metrics panel” (→ Semantic Layer).
- **A11y (long-deferred audit #12, minimum viable):**
  1) Sidebar nav buttons must expose names — inspect the Sidebar item component for why the label
     text doesn't compute (likely an `aria-hidden` wrapper or the label span outside the button's
     a11y subtree); add explicit `aria-label` + `aria-current="page"` on the active item.
  2) Keep-alive hidden Workspace panels: `aria-hidden="true"` + `inert` on non-active panel
     containers (the AX tree currently exposes several screens at once — §1.7-7).
  3) Chip away raw `<button>` → `<Button>` in every file this WP touches (ratchet only goes down).
- **DoD:** first-load Home shows an ask box; nav ≤ ~7 top items; AX tree shows named nav buttons
  and exactly one visible workspace; raw-button baseline lowered.

### Wave 3 — hardening & structure

---

#### WP-12 · Frontend test beachhead + dead-code removal
**Closes:** §1.5/1.6 zero-tests. **Effort:** 1–2 days initial.

- **Playwright smoke** (new `web/e2e/`, `@playwright/test` devDependency): boot API on the seeded
  fixture (`aughor seed`; `AUGHOR_*` envs → temp dirs so e2e never touches live stores) + prod web
  build. Five specs, no LLM dependency:
  1) Home renders, zero console errors (fail the test on any `console.error`);
  2) sidebar → each of the 5 workspaces renders its header (catches lazy-panel crashes);
  3) Data Canvas list → open canvas → composer visible;
  4) Settings→System: toggle a flag → PUT succeeds → chip flips (round-trip through the real API);
  5) `/ask` error path: stub the ask route to 500 via Playwright route interception → the WP-2
     error card appears (locks the res.ok fix).
- CI: a `web-e2e` job (Playwright container or `npx playwright install --with-deps chromium`),
  ~3-4 min; keep it on the hot path — it's the only behavioral net the SPA has.
- **Enable ESLint in CI** (`npm run lint` in the frontend job). First run will surface the
  accumulated `react-hooks` warnings — set `--max-warnings` to the current count as a one-way
  ratchet (mirror the raw-button pattern) rather than fixing all at once.
- **Delete dead weight:** `components/HypothesisCard.tsx`, `components/DomainIntelPanel.tsx`
  (verify no import first — audit says orphaned), fix the stale claim in `lib/openInBuilder.tsx:7`;
  drop `eventsource-parser` from package.json (WP-2 may have done it).
- **DoD:** red Playwright run on a deliberately-broken panel proves the net works; ESLint ratchet
  wired; ~860 LOC dead code gone.

---

#### WP-13 · UI polish batch (one PR of small fixes)
**Closes:** §1.7 nits 3/5/8. **Effort:** ~1 day.

1. **Acceptance display** (`AgentWorkspace`/Memory panel): replace the blended “83%” with the
   counts — “2 accepted · 1 corrected · 0 rejected” — or keep the % and add the formula tooltip
   (“corrected counts half”). The backend
   (`/verify/verdicts/stats` → `acceptance_rate=(accept+0.5*correct)/total`) stays as-is; this is
   a display decision. A trust surface must not show an unreconcilable number.
2. **Format numbers in briefing/signal prose:** deterministic render-time pass (frontend, beside
   the existing prose helpers): standalone integers ≥ 10,000 in briefing/signal card text get
   locale thousands-grouping **unless** adjacent to an id-ish token (`#`, `id`, code font) —
   mirror the backend's `round_long_decimals` conservatism. Do NOT mutate LLM prose server-side.
3. **“17q · 89 insights” →** “17 queries · 89 insights” (ExplorerStatusChip copy).
4. **“Workspace LOCA” truncation** (Data Canvas connection chip): let the badge text width fit
   (`max-w` bump or tooltip on truncate).
5. **Data Canvas metadata contrast:** the row description/modified/connection columns are
   near-invisible — raise from the disabled-tier token to the muted-tier (`--text-3`-class token,
   whatever `tokens-v2.css` names it). Screenshot before/after.
6. **Sidebar footer overlap:** the avatar/glyph overlaps the “Settings” label at 1280×720 —
   inspect the footer layout (absolute positioning at small heights) and fix stacking/spacing.
7. **Uptime display:** show “started HH:MM” alongside/instead of the 0s-prone uptime counter
   (`SystemPanel.tsx:24,125`; backend `stats.py:47` is per-process — fine, label honestly).
8. **Dim-state transitions (~3s):** find the polling interval behind workspace panel loads (likely
   a slow default poll or serial fetch chain); render skeletons instead of dimming stale content,
   and parallelize the panel's initial fetches (`Promise.all` the independent GETs).
- **DoD:** screenshots of each fix in the PR; zero new raw buttons/hex (gates enforce).

---

#### WP-14 · Structural refactors (schedule when the hot files are next touched)
**Closes:** §1.3. **Effort:** incremental; do NOT big-bang.

- **Split the god router** `routers/investigations.py` (3,561/92 defs) by concern into a package:
  `investigations/{chat,stream,feedback,history,outcomes}.py` re-exported through the existing
  router include — **route paths and OpenAPI operation ids must not change** (codegen gate will
  catch drift; regen anyway). Mechanical; do it before the next feature lands in that file.
- **Fix the two worst layering inversions:** move the shared helpers that `kernel/jobs.py:389`
  and `agent/nodes.py:1259` reach into (`routers._shared`) down into `aughor/kernel/` or a neutral
  `aughor/util/` module (spawn/exploration kickoff helpers are agent-layer, not router-layer —
  follow the Pattern-C resolver-registry precedent from DATA-06). Make `verify/gate.py:14`'s
  `agent.state` import type-only/function-local.
- **`agent/investigate.py` (6,321):** split per phase only when a phase is next modified
  (extract-on-touch rule) — target `investigate/{intake,scan,synthesis,guards}.py`. Do not
  reformat-only-move (kills blame).
- Add an import-boundary test for `kernel → routers` = 0 (mirror
  `test_platform_agent_boundary.py`) once the inversion is fixed, so it can't come back.
- **HostCapabilities:** decide — either route ≥1 real call site through it per the ROADMAP
  follow-on, or delete the aspirational Protocol + docstring (a documented-but-bypassed boundary
  is worse than none). Recommend: delete unless the two-package split gets a driver.
- **DoD per slice:** ratchets flat or down; private-import baseline (22) not raised; codegen green.

---

#### WP-15 · Explorer ↔ preflight parity (close the drift)
**Closes:** F2. **Effort:** ~1 day. Flag `explorer.preflight_parity`, default-off → promote.

- Converge the Scout's inline pre-execute chain (`explorer/agent.py:2941-3005` + defan `:3097` +
  join-domain `:3029`) onto `sql/executor.py execute_guarded` / `preflight_harden` — the same move
  WS2 made for the three answer paths. **Keep** Scout's post-execute R3/KB/triangulation logic
  untouched (WS2's scope judgement: post-execute loops are legitimately divergent).
- Delta to reconcile: Scout currently uses `unresolved_identifiers` detect-and-skip where
  `safety.py:53` runs `repair_identifiers` — under the flag, adopt the repair (it strictly
  improves; dry-run-gated) but keep the skip as fallback on repair failure (Scout must never
  wedge on one bad probe).
- Extend the guard-parity test to include the Scout path (fourth arm of
  `test_guard_parity_all_three_paths_share_the_hardening`).
- Live: one Scout run on the fixture with the flag on; compare finding counts/probe failures vs a
  flag-off run (should be ≥, never <, successful probes).
- **DoD:** `explorer/agent.py` has no private copy of the pre-execute chain; the misleading
  comment at `:2939` is gone; parity test covers 4 paths.

---

#### WP-16 · CI upgrades (needs user decisions — do not implement unprompted)
- **Nightly live-accuracy run:** a `workflow_dispatch`+`schedule` job running
  `evals/run_golden.py --live` (pinned model, ~53q) + `evals/ratchet.py` compare against the
  pinned baseline (mean 0.6551/exec 1.00), posting the delta as a run summary. **Blockers:** an
  LLM API key as a repo secret + token spend per night + Actions minutes (Free tier ~2,000
  min/mo, currently ~17 min/run on the hot path). Decide cadence (weekly?) with the user first.
- **Branch protection:** arrives free if/when the repo flips public. Until then CI stays advisory
  — nothing to implement; noted so nobody “fixes” it locally.
- **py-matrix drift:** already weekly; acceptable. No action.

---

## 3 · Sequencing & dependencies

```
Wave 1 (parallel-safe): WP-1 │ WP-2 │ WP-3 │ WP-4 │ WP-5
   WP-1a before WP-1e (caveats field is the carrier)
   WP-4 before WP-8b (agents.db migration adoption rides WP-4)
Wave 2: WP-6 → (copy change 6d only if 6a-c don't promote) │ WP-7 │ WP-8a/8b │ WP-9 │ WP-10 │ WP-11
   WP-7 reuses WP-6c's Inbox-event pattern — land 6c first or coordinate
   WP-10 consumes WP-1a caveats in the receipt guard list
Wave 3: WP-12 (locks WP-2's fix) │ WP-13 │ WP-14 │ WP-15 (after WP-1 settles executor surface) │ WP-16 (decision-gated)
```

One-PR-per-WP; keep WPs unbundled (the repo's squash-merge history works because arcs stay
reviewable). Suggested first week: WP-3 (hours) + WP-4 (half day) + WP-5 (hours) + WP-2 (1–2d) +
WP-1 (rest of week). That week alone moves the platform from “impressive with asterisks” to
“defensible under audit”.

## 4 · Explicitly NOT in scope (do not build)

- **No rebuilds of removed machinery:** the old eval harness / probe-repair / formula-grounding
  were deliberately removed (nl2sql-scientific-benchmarking conclusion) — don't reintroduce.
- **Do not force-merge the three post-execute repair loops** (ADA id-arith+trust · explore
  R3+KB+triangulation · quick B-7+consistency) — WS2's scope judgement stands; only pre-execute
  hardening is shared.
- **No new frontend frameworks / no SWR-React-Query rewrite** — the ui-ux-uplift decision is
  unify-and-finish; WP-2/12 are surgical.
- **No $-/bytes-scanned metering fake** — `kernel/metering.py` excludes it by design; a real
  implementation needs per-dialect scan stats (follow-on, not WP-7).
- **No multi-tenant Postgres/S3-vending/IdP build-out** — Phase 4/5 stays deferred until a SaaS
  driver (PLATFORM_ARCHITECTURE §12).
- **No Spider2 work** — user-deferred (“spider later”); WS5 P0 harness exists when it resumes.
- **Phantom flags** `obs.task_table` / `ask.context_receipt` are roadmap names, not code — create
  them only when their arcs (Wave-2 obs / Rec-5 grounding receipt) actually build.

## 5 · Claim-alignment checklist (re-audit after Waves 1–2)

| README/FEATURES claim | Becomes true when |
|---|---|
| “guards … out of every answer” | WP-1 DoD (coverage table all-green or documented-by-design) |
| “one SQL-safety pipeline” | WP-15 DoD (4-path parity test) |
| “explores continuously / never stops learning” | WP-6 promoted default-ON — else reword (6d) |
| “multi-tenant … config flip” | WP-8a/8b + the WP-8c decision recorded |
| “trustworthy, not just plausible” (inspectable) | WP-10 receipt live on every surface |
