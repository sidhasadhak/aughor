# 🚨 World-Class Hardening — Execution Plan

> **⚠️ SUPERSTRUCTURE UPDATE (2026-06-10, same day):** the user escalated this arc from bug-fixing to
> an architectural rebase — see **`docs/KERNEL_ARCHITECTURE.md`** (the Aughor Kernel: Ledger + Job
> Kernel + Event Spine + Contracts, with measured proof of the gap). That doc's §4 reconciles the two
> plans: **WCH-1 and WCH-2a–c execute now as written; WCH-3–8, 10(contract test), 11, and B-1 are
> ABSORBED by kernel stages K0–K4** (implemented as kernel properties, not patches); WCH-9, 12–17
> execute after K1/K2 as described there. Read the kernel doc first.

**Arc directive (user, 2026-06-10):** take quality + speed to world-class. Reproduce the 3 reported
intermittent bugs, audit wirings, challenge logic, deep stress tests, performance pass, SOTA UI with
real motion. No fake claims — every "works" requires an executed verification.

**Provenance:** this plan synthesizes six parallel deep-scan audits of the codebase (2026-06-10):
ontology-build failure paths, sample-data lifecycle, Briefing→canvas Investigate wiring, full UI↔API
wiring inventory (188 endpoints), UX/motion audit, and performance/stress/test-infrastructure audit.
Every claim below carries file:line evidence from those scans. Line numbers are as-of `correctness-next`
@ `07f49fb` — re-verify before editing.

**Honesty ground rules for whoever executes this:**
1. Every item has a **Verification gate** — the item is NOT done until that gate is executed and passes.
2. Never delete/mutate buggy findings or repro artifacts (standing rule). Quarantine, don't purge.
3. If a root-cause hypothesis turns out wrong when you instrument it, say so and update this doc —
   the scans rank *candidates*, they are not all confirmed.
4. A lesson from the scans themselves: the wiring audit declared the Investigate button "working"
   because it only traced the connection-level path; the canvas-level path was broken. **Audits must
   be scope-aware** — verify each surface (connection / canvas / workspace) separately.

---

## Phase 0 — The Three Reported Bugs (root-caused or candidate-ranked)

### WCH-1 ✅ROOT-CAUSED — Briefing "Investigate" → blank canvas

**Status: deterministic, 100% reproducible, ~15-line fix.**

**Root cause:** `web/components/CanvasWorkspace.tsx:837` defines
`onInvestigate={() => setWsTab("chat")}` — it **discards the `(q, mode)` parameters** that
`IntelligenceWorkspace.tsx:55` declares and `BriefingPanel.tsx:139` passes. ChatPanel's auto-submit
effect (`ChatPanel.tsx:393–403`) requires `initialQuestion` to be truthy; it never is, so the chat tab
opens empty. CanvasWorkspace has `initialOpenInvId`/`initialRestoreSessionId` props but **no
initialQuestion mechanism at all**.

**Why connection-level works:** `web/app/page.tsx:1745` `goToChat(q, mode)` correctly sets
`chatInitialQuestion`/`chatInitialMode` state. Only the canvas-scoped intelligence surfaces are broken.

**Affected entry points (all canvas-scoped):**
- Briefing card "Investigate →" (`BriefingPanel.tsx:806`)
- Signal card Investigate (`BriefingPanel.tsx:855`)
- Pattern row Investigate (`BriefingPanel.tsx:883`)
- Citation chips (`BriefingPanel.tsx:93`)
- EvidencePanel "Re-examine →" (same callback chain — verify)

**Fix (in CanvasWorkspace.tsx):**
1. Add state: `chatInitialQuestion` / `chatInitialMode` (`useState`).
2. Change line 837 to `onInvestigate={(q, mode) => { setChatInitialQuestion(q); setChatInitialMode(mode); setChatKey(k => k + 1); setWsTab("chat"); }}`
   (the `chatKey` bump forces ChatPanel remount so the auto-submit effect re-fires; clear the state
   after consumption so a later manual tab-switch doesn't re-submit).
3. Pass `initialQuestion={chatInitialQuestion}` `initialMode={chatInitialMode}` to ChatPanel (~line 766).

**Verification gate:** in the running app, open a canvas → Intelligence → Briefing → click
Investigate on a real (non-degenerate) card → chat tab opens **with the question auto-submitted and a
streaming answer**. Repeat for pattern row + citation chip + EvidencePanel Re-examine. Also verify
connection-level Briefing still works (no regression). Effort: **S**.

---

### WCH-2 — Sample data goes missing intermittently

**Status: 6 ranked candidates; top 3 are near-certain contributors. The theme is a silent-failure
chain: seed materialization swallows all errors, the sample endpoint has no error field, and the UI
renders "fetch failed" and "table empty" identically.**

Lifecycle: `samples.duckdb` seeded at API startup (`aughor/api.py:61–68`, failure logged + swallowed) →
each Workspace connection ATTACHes it read-only and materializes tables into in-memory DuckDB
(`aughor/connectors/file/local_upload.py:164–176`) → served by
`GET /connections/{id}/tables/{t}/sample` (`aughor/routers/connections.py:310–340`) → rendered by
`SampleGrid` (`web/components/CatalogScreen.tsx:460–498`).

**Ranked candidates:**
1. **Seed materialization silent failure** (`local_upload.py:177–182`): bare `except Exception` around
   the whole ATTACH→enumerate→CREATE→DETACH block — if ATTACH blocks (file locked by another session/
   profiler), enumeration returns empty, or one CREATE fails, the user gets a Workspace with the schema
   visible but tables missing, **zero log signal**.
2. **UI cannot distinguish error/empty/no-data** (`CatalogScreen.tsx:484`): seed-failed-but-schema-exists
   returns 200 + 0 rows → renders the same "No rows returned" as a genuinely empty table.
3. **Concurrent ATTACH/DETACH race**: every Workspace session ATTACHes the same `samples.duckdb` with
   no synchronization (`local_upload.py:115`, registry spawns fresh sessions `aughor/db/registry.py:152–157`).
4. **Stale in-memory copies after re-seed/reset**: `ensure_samples_db` re-runs on API restart while old
   sessions hold materialized copies; the `data/_reset_backup_*` dirs show resets happen regularly.
5. Type-serialization failure on exotic columns (`connections.py:331` `str(v)` per cell; an exception
   yields an empty QueryResult via `db/connection.py:705–706`).
6. WAL/lock corruption of `samples.duckdb` after a crash mid-seed.

**Fix package (do all — they're each small):**
- **2a Instrument the seed path**: per-table try/except with `logger.error(..., exc_info=True)`,
  log table count on success, set a `_seed_failed` flag on the connection (per scan FIX #1).
- **2b Error field in the sample endpoint**: propagate `result.error` into the JSON
  (`{"columns", "rows", "row_count", "error"}`) instead of returning a bare empty payload.
- **2c Three-state UI**: SampleGrid renders distinct error (red, with the message) / "table is empty" /
  data states; never a silent blank.
- **2d Module-level lock** around `_seed_from_duckdb()` (threading.RLock) to serialize ATTACH/DETACH.
- **2e Startup validation**: after `ensure_samples_db()`, open read-only and assert the ecommerce
  table count > 0; log loudly if not.
- **2f Health probe**: `_seed_health_check()` (SELECT 1 from a seeded table) exposed on the connection,
  surfaced in the catalog UI when samples are missing ("Seed failed — restart workspace" affordance).

**Verification gate:** (i) deterministic repro first — hold a write lock on `samples.duckdb` from a
DuckDB CLI while creating a Workspace connection; confirm today's blank-tables behavior, then confirm
the fix surfaces a visible error + log line; (ii) concurrency — open 3 Workspace sessions simultaneously,
all show full sample tables; (iii) unit tests for 2a/2b; UI states screenshot-verified. Effort: **M**.

---

### WCH-3 — Ontology sometimes does not build up

**Status: 8 ranked candidates across the 4-stage build pipeline (profiling → structural →
LLM-enrichment → validation, `aughor/db/connection.py:732–853`). The pipeline is resilience-by-
swallowing: nearly every stage can fail without the UI ever knowing.**

Build triggers: explicit `POST /ontology/rebuild` (`aughor/routers/ontology.py:317–350`), auto during
exploration Phase 8 (`aughor/explorer/agent.py:886–908`), lazy on first `/ontology/*` GET. Cache:
`data/ontology_cache.json`, key `{conn}:{schema}:{fingerprint}`, LRU 20.

**Ranked candidates:**
1. **Enrichment LLM failure half-surfaced** (`db/connection.py:807–820`): exception recorded in
   `last_build` but flagged `"ok": True`; no retry, no timeout param; a *partial* LLM success can save
   `enrichment_version=5` with missing fields → **never re-enriches** (the "rebuild doesn't help" smell).
2. **Non-atomic JSON store, no locks** (`aughor/util/json_store.py:36–54`): load→mutate→save with zero
   locking; concurrent rebuild + Phase-8 auto-build = last-write-wins cache corruption. Same store
   class backs 17+ caches.
3. **Empty structural graph saved as success** (`ontology/builder.py:970–982`, `ontology/store.py:253`):
   if profiling soft-fails (per-table exceptions → `col_counts[t]=0`, `profile_cache.py:138`), the
   builder loops over nothing and persists a 0-entity graph; UI shows "no ontology" while the system
   thinks it built one. (Phase 8 does report "built but produced no entities", `explorer/agent.py:1526–1530`.)
4. **JSON-coercion silently drops enrichment fields** (`ontology/enricher.py:20–35, 113–126`): local
   models stringify nested fields; failed coercion → Pydantic drops the field → 0 computed properties,
   no signal. (Known history: ENRICHMENT_VERSION=5 fixed one variant; the drop path remains unlogged.)
5. **Validation failures fully silent** (`db/connection.py:829–834`): bare `pass`, not even `last_build`.
6. Profile-cache corruption returns None without invalidating the corrupt entry (`profile_cache.py:64–89`).
7. Fingerprint collision across structurally-identical schemas (`ontology/store.py:207–257`).
8. **Exploration never resumes after server restart** (see WCH-6) — Phase 8 is the auto-build trigger,
   so a restart mid-exploration = ontology never builds, which *presents* as this bug.

**Fix package:**
- **3a Build-status truthfulness**: a structured `last_build` with per-stage `{stage, ok, error, at}`;
  validation failures recorded like enrichment ones; expose via `GET /ontology/build-status` and render
  in the Ontology panel (build stepper: profiling → structure → enrichment → validation, with the
  failing stage and a Retry button). This converts "intermittent mystery" into "visible failed stage".
- **3b Lock `KeyedJsonStore`**: in-process `threading.Lock` around put/save (+ optional fcntl file lock);
  applies to ontology, profile, and all sibling caches at once.
- **3c Reject/flag empty graphs**: 0-entity structural result → don't persist as a success; record
  `last_build` error naming the table count seen.
- **3d Enrichment robustness**: version-rollback on exception; log + counter on every coercion failure
  and dropped computed-prop; explicit timeout on the LLM call; retry ×1.
- **3e Profile-cache self-heal**: invalidate corrupt entries on deserialization failure.

**Verification gate:** (i) repro — kill the LLM backend, hit rebuild, confirm UI shows "enrichment
failed" with retry (today: silent); (ii) concurrent rebuild test — two simultaneous `POST /ontology/rebuild`,
assert the cache is consistent and both report a coherent status; (iii) empty-schema test — connect a
0-table schema, assert explicit "no entities" status not a phantom build; (iv) unit tests for the store
lock + version rollback. Effort: **M**.

---

### WCH-DS — Data-shape-aware temporal planning (user-reported 2026-06-10, fixed same day)

**Repro:** bakehouse holds **17 days** of data (2024-05-01→17) beside ecommerce's 24 months on the
same `workspace` connection. The explorer framed findings as "the last 12 months"; ADA ran a
12-month observation vs an empty prior-12-month comparison and reported a wall of NULLs ("honest"
but useless). The analysis playbook never consulted the data's measured shape.

**Root causes (all confirmed):**
1. `_role_aware_time_window` computed `start = max − 365d` with **no clamp to the first fact**
   (`explorer/agent.py`), and the Phase-8 prompt hardcoded "last 12 months" phrasing.
2. The window was **global per connection** — a domain living in a 17-day dataset inherited the
   window anchored by the sibling 24-month dataset.
3. ADA's window validator was **dead code**: `scan_context` is initialized `""` on both ADA entry
   points and never populated before intake, so `_extract_data_date_range` had nothing to parse —
   and even when it fires, enforcement was a polite LLM retry, not a clamp.

**Fixes (shipped + tested):** start-clamp to earliest activity fact in `_role_aware_time_window`;
per-domain/dataset `_window_for_tables`; coverage-aware Phase-8 prompt ("this domain's data spans
only ~N days … NEVER frame as 'last 12 months'; no MoM under 2 months, no YoY under 13");
`_measure_date_span` DB probe (MIN/MAX of the metric table's date column) as the authoritative
intake source; `_clamp_intake_to_coverage` deterministic enforcement (clip observation, collapse
empty comparison to "no prior period exists", relabel short history as "Available history (~N
days)" + planner note). 14 regression tests in `tests/unit/test_coverage_clamp.py`.

**Follow-up (open):** narration-inversion guard — the same briefing card read `order_count=3,
total_items=3, avg_items_per_order=1.0` (3 orders averaging ONE item) and narrated "all orders
contained exactly 3 items". Magnitude grounding passes (the numbers exist as cells); the *semantic
binding* of number→meaning is wrong. Candidate guard: per-grain/per-entity claim checker comparing
narrated "per-X" phrasing against the aggregate's actual grain; pairs with the small-n qualifier
(findings built on n<30 entities must carry the n). The stored repro finding is preserved
(never delete) and will regenerate under the corrected pipeline on the next explore/refresh.

---

## Phase 1 — Orphaned-State & Lifecycle Correctness (the "intermittent" engine)

> **✅ ABSORBED BY K1 (2026-06-10, commit `82c5b4d`)** — the Job Kernel made these structural:
> WCH-4 = the supervisor's paused-explorer backstop (note: the finally-block this item asked for
> already existed at `investigations.py:1408` — the audit claim was stale; pause-tagging added so the
> backstop never overrides a user pause); WCH-5 = the supervisor loop (30s sweep + 5-min
> investigation sweep); WCH-6 = boot recovery (live-verified: kill -9 mid-exploration → restart →
> orphan FAILED + auto-resume from checkpoint); WCH-7 = cancel-on-delete for canvas + connection
> scopes; WCH-8 = partially (ledger transactions cover the JSON-cache races; the .duckdb write
> coordination remains open — see K1 follow-ups in the kernel doc).

The perf/stress audit found a *class* of lifecycle bugs that manufacture intermittent behavior
platform-wide. These likely co-cause all three reported bugs and are individually small fixes.

### WCH-4 — Paused explorers never resumed (CRITICAL)
`aughor/routers/investigations.py:1157–1162` pauses every explorer on the connection when an
investigation starts; there is **no finally-block** — on stream drop, exception (`:1377–1390`), tab
close, or LLM failure, explorers stay paused forever. Fix: wrap the investigation stream in
try/finally that resumes `_paused_explorers`; resume in all failure handlers.
**Gate:** kill an investigation mid-stream (close SSE), assert explorers return to running within seconds. **S.**

### WCH-5 — Periodic sweep + auto-resume
`sweep_stale_running()` runs only once at startup (`aughor/api.py:72–81`). Add a periodic background
task (5 min): mark stale-running investigations failed, resume orphaned paused explorers.
**Gate:** simulate a stuck "running" investigation; assert it's swept within one cycle. **S.**

### WCH-6 — Exploration resume after restart
Canvas explorers are rebooted at startup (`api.py:189–234`) but connection explorers are deliberately
not (`api.py:226` comment) — checkpoint files become dead weight and users see "pending" forever
(and Phase-8 ontology never builds → feeds WCH-3). Fix: either auto-resume from checkpoint at boot
(guarded: only if phase < complete and state file is fresh) or surface a one-click "Resume exploration
(was at phase 5)" affordance in the UI. Recommend: auto-resume + UI notice.
**Gate:** start exploration, restart the server mid-phase-5, assert it resumes and completes (ontology built). **M.**

### WCH-7 — Task cancellation on delete
Canvas deletion doesn't cancel its explorer task; `_canvas_explorer_tasks` grows forever (`api.py:216`);
connection deletion likewise never cancels `_explorer_tasks[conn_id]`. Fix: cancel + pop in both delete
paths. **Gate:** 5× canvas create/delete loop, assert task dict size returns to baseline. **S.**

### WCH-8 — DuckDB / state-store write coordination
DuckDB is single-writer; explorer `_save_state()`, profile rebuilds, and ontology builds can contend
with no queue/timeout (`explorer/store.py`, `db/connection.py:596–620`). Fix: per-connection write
lock (asyncio.Lock keyed by conn_id) around state persists + build_intelligence; batch `_save_state`
writes (debounce ~2s). Note WCH-3b's KeyedJsonStore lock covers the JSON caches; this covers the .duckdb
files and exploration state.
**Gate:** stress scenario 1 & 3 below pass (two concurrent explorations / introspection during build
complete without deadlock or corruption). **M.**

---

## Phase 2 — Stress-Test Suite + Wiring Contract Tests

### WCH-9 — Stress suite (`tests/stress/`)
Implement the 10 scenarios from the audit as automated tests where feasible, scripted harnesses where
not (mark which is which honestly — some need a live LLM and are `@pytest.mark.live`):
1. Concurrent explorations, same connection (breaks today: store write contention).
2. SSE drop mid-investigation (breaks today: stuck "running" + paused explorers — fixed by WCH-4/5).
3. Concurrent schema introspection during a build (DuckDB lock contention).
4. Simultaneous ontology builds (manual + Phase-8 auto) — cache race (fixed by WCH-3b).
5. Poll storm: 3 tabs × all polling panels for 5 min — pool thrash, payload cost (informs WCH-11).
6. Unicode/exotic column names + 10K-char values through phases 3–7.
7. Empty database / all-0-row tables end-to-end (explore → briefing → ontology).
8. Repeated canvas create/delete (task leaks — fixed by WCH-7).
9. LLM timeout/hang mid-synthesis (today: worker thread hangs; add per-call timeout enforcement).
10. Server restart mid-exploration (fixed by WCH-6).

**Gate:** suite runs in CI-ish mode (`pytest tests/stress -m "not live"`); each scenario's expected
behavior documented in the test docstring; failures filed as findings, not silently skipped. **L.**

> **✅ DONE (2026-06-10).** Two layers shipped: (a) `tests/stress/` — LLM-free invariant tests for
> scenarios **1, 4, 8** (kernel storm: racing idempotent submits collapse to one job, distinct scopes
> don't, create/cancel churn ×20 leaks nothing, supervisor sweep stays correct amid live jobs) +
> **6, 7** (degenerate data: empty DB aborts gracefully, all-0-row tables profile without divide-by-
> zero, unicode/emoji/reserved-word/10K-char columns survive discovery). (b)
> `scripts/chaos_drill.py` — the **crash-anywhere** invariant as an executable drill: random `kill -9`
> mid-exploration, restart, assert no orphan left RUNNING (I1: failed-with-reason), incomplete
> checkpoints resumed (I2), journal narrates it (I3). **Ran 3× → ALL RECOVERED**, journal confirms
> 4 jobs caught mid-flight and recovered (not vacuous). Scenarios **2, 5, 9** (SSE-drop, poll-storm,
> LLM-hang) are structurally covered by K1/K2 already and deferred to a live harness; **3, 10** are
> the chaos drill's domain. 438 unit+stress tests green.

### WCH-10 — Wiring contract tests + dead-endpoint triage
The wiring audit found the 188-endpoint surface largely sound but ~25 endpoints with no frontend
caller (ontology skills ×5, security budget ×3, glossary ×3, query-cache ×2, suggestions, autonomy,
schemas/interfaces, action logs…). For each: decide **wire it / keep as CLI-API / delete** — record the
decision in a table in this doc. Add a contract test that walks `web/lib/api.ts` call signatures
against the FastAPI route table (method+path+params) so a future mismatch fails CI. Add scope-aware
button smoke tests (the WCH-1 lesson): for each Investigate/Monitor/Promote/Share/Dismiss affordance,
a test or scripted check per surface (connection-level AND canvas-level).
**Gate:** contract test green; triage table filled with a decision per endpoint. **M.**

---

## Phase 3 — Performance

Ordered by win/effort from the audit:

### WCH-11 — Kill the poll storm (S, big win)
- ChatPanel polls every 500ms during an investigation (`web/components/ChatPanel.tsx:231`) ≈ 1,200
  requests per 10-min run while SSE is already streaming. Fix: SSE `done` event stops polling; polling
  only as fallback when SSE silent >30s.
- Exploration findings endpoint serializes the full state (50KB+) per poll (`routers/exploration.py:141–174`).
  Add `GET /exploration/{id}/findings-summary` (phase, counts, updated_at) for the pollers; full payload
  fetched on demand.
- Dedupe cross-panel polling with a tiny shared fetch cache (SWR-style) so Briefing (3s) /
  DomainIntel (10s) / Badge (10s) share one request.
**Gate:** network tab during a live investigation shows >70% fewer requests; payload per poll <2KB. 

### WCH-12 — Schema introspection cache (S)
Every `/investigate` re-walks information_schema (`routers/investigations.py:1166`). Add a
connection-keyed TTL cache (60s) with explicit invalidation on connection edit.
**Gate:** 10 back-to-back investigations trigger 1 introspection (log counter). 

### WCH-13 — Parallelize agent-graph LLM calls (M, 30–50% latency)
`agent/nodes.py` runs route→decompose→per-hypothesis execute+score→synthesize strictly sequentially
(lines 74–1092). Parallelize evidence scoring across hypotheses with `asyncio.gather`; batch the
inconsistency checks; keep synthesis last. Also enforce a per-LLM-call timeout (provider read timeout
exists at 300s, `llm/provider.py:76`, but the graph has no per-call wrapper — scenario 9).
**Gate:** measure a fixed Deep-Analysis question before/after (N=3 runs, same model): wall-clock −30%
or better, identical report structure. 

### WCH-14 — Explorer phase parallelism (L, optional)
Phases 3–7 sequential (`explorer/agent.py:863–884`); parallelize across independent tables within a
phase first (lower risk than cross-phase). Defer if WCH-11..13 already get Deep Analysis + exploration
into acceptable range. **Gate:** exploration wall-clock on the beautycommerce connection −20% with
identical findings counts. 

---

## Phase 4 — SOTA UI: Motion System + Felt Quality

The audit's verdict: ThinkingTrace is the gold standard (staggered entry, multi-state dots, gradient
progress, reduced-motion support) — everything else snaps. No motion library needed (and don't add
framer-motion); CSS + tokens suffice.

### WCH-15 — Motion foundation (S–M)
- Motion tokens in `web/styles/tokens.css`: `--dur-fast 100ms / --dur-norm 200ms / --dur-slow 400ms /
  --dur-breath 700ms` + `--ease-out / --ease-pop / --ease-flow`.
- Keyframes + utilities in `globals.css`: `anim-fade-in / anim-slide-up / anim-scale-pop / skeleton shimmer`
  (consolidate the 3 duplicate `spin` definitions).
- Primitives in `web/lib/ui/motion.tsx`: `<Spinner size>`, `<SkeletonRow>`, `<FadeIn>`, `<StaggerList>`,
  `<AsyncButton pending>` (consolidates ~10 hand-rolled pending buttons incl. BriefingPanel ActionButton's
  text-only "…").
- All animations respect `prefers-reduced-motion`.
**Gate:** tsc clean; one screenshot per primitive; grep shows zero remaining inline `@keyframes spin`. 

### WCH-16 — Rollout to the clunkiest surfaces (M)
Ranked worst-first by the audit:
1. **ExplorationPanel** (`ExplorationPanel.tsx:358–387`): static "Loading exploration data…" during a
   multi-minute run → PhaseBar immediately + skeleton rows + pulsing poll dot + "updated Xs ago".
2. **Screen/panel swaps** (`page.tsx` screen switch, CommandPalette, CanvasCreator, SemanticLayerPanel
   modals): instant mount → `anim-scale-pop` + backdrop fade.
3. **Async buttons** (BriefingPanel Monitor/Promote/Share, SecurityAuditPanel save): → `<AsyncButton>`
   with spinner + state colors.
4. **Tab content swaps** (ExplorationPanel sections, IntelligenceWorkspace layers): keyed `anim-fade-in`,
   staggered children on lists.
5. **Expand/collapse** (ExplorationReport SQL toggle and friends): grid-rows or max-height transition.
6. **Toasts/empty/error states**: slide-up in, fade out; empty states get icon + fade.
**Gate:** before/after screen recordings of items 1–3; no layout shift introduced (CLS spot-check);
reduced-motion verified. 

### WCH-17 — Structural felt-quality (S each)
- Scroll-position memory across screen switches (audit: catalog scroll lost on tab away/back).
- Hardcoded-color sweep → tokens (BriefingPanel, SecurityAuditPanel etc.; the light theme depends on it).
- Standardize transition durations onto the tokens (today: 0.1s/0.12s/0.3s/700ms ad-hoc).
- #14 backlog remnants fold in here: ontology legends-at-top, canvas History-tab empty bug,
  Recents-includes-Quick-chats.
**Gate:** light-theme screenshot sweep of touched components; History-tab bug has a repro + fix + regression test. 

---

## Phase 5 — Business / USP Roadmap (what data teams actually buy)

Positioning: Aughor's defensible wedge is **trustworthy autonomy** — competitors demo autonomous
insights; almost nobody can show *why a number is right*. Everything below sharpens that wedge.

| # | Item | Why it sells | Builds on |
|---|---|---|---|
| B-1 | **Trust Receipts** — every surfaced number carries a one-click provenance chip (source SQL, validation status, fan-out-guard applied, freshness, grounding check) rendered as a compact badge row | The CFO question is "can I put this in a board deck?" Evidence layer exists; productize it as a visible receipt, not a drawer | Evidence layer, validator, grounding |
| B-2 | ✅ **UNIFY — metric unification** (DONE `3c97559`) — one registered metric, schema-scoped injection, leak fixed, convention-neutral eval | "Revenue means one thing" is the #1 enterprise semantic-layer ask; the first brick of the K5 Semantic Governance Plane | #13b ✅ |
| B-3 | **Slack-first delivery** — scheduled briefs + monitor alerts with finding cards and an Investigate deep-link back into the app | Data teams live in Slack; push is how intelligence reaches non-analysts. Subsystem exists (briefs/, triggers); needs real-creds E2E + deep links | #4 ✅ |
| B-4 | **Data-health monitor pack** — one-click freshness/volume/schema-drift monitors per connection, auto-proposed from the ontology | Cheapest "always-on value" — the platform notices breakage before the user does; classic land-and-expand | monitors, watermark (Tier 3) |
| B-5 | **#12 Enterprise hardening** (OAuth2/OIDC, RBAC, tenancy, query cancel, secrets) | Gates every real deployment; **also the identity substrate K5 governance needs** — "Finance owns the definition" requires a "Finance"; licensing foundation already dark-launched | licensing/ |
| B-6 | **Time-to-first-insight < 5 min** — instrument and optimize the connect→first-briefing funnel as a product KPI (sample data, progressive exploration: first findings surface while later phases run) | The eval for "wow"; today exploration is all-or-nothing for 8–15 min | WCH-11..14 |

### Phase 5b — The Semantic Governance Plane (K5 / SOTA trust wedge)

The Ledger + Contracts applied to **meaning** (see `KERNEL_ARCHITECTURE.md` Pillar 4). This is the
Palantir/Databricks-tier differentiator: a metric is a governed, owned, approved object, and the AI is
*forbidden* from acting outside the governed set. UNIFY (B-2) laid the first brick.

| # | Item | Why it sells | Builds on |
|---|---|---|---|
| **B-7** | **AI use-only-registered metrics (enforcement contract)** — when a metric is governed, the SQL path MUST use that exact formula; when it isn't, the agent offers to define it instead of free-handing one. Measured *enforcement rate*. | The single biggest trust differentiator — "the AI can't improvise the numbers." This is what lets a CFO trust an autonomous answer. | UNIFY registry ✅, canonical injection, fan-out/grain/drift guards |
| **B-8** | **Metric governance workflow** — propose → review → approve → enforce, versioned with an audit trail, in the UI. Metrics become Ledger artifacts with `owner`/`approved_by`. | "Revenue is owned by Finance, versioned, audited" — the enterprise semantic-layer table-stakes (Cube/dbt-metrics/Unity Catalog parity). | K0 Ledger (artifacts), K3 lineage, #12 identity |
| **B-9** | **Receipts default-visible** — the K3 provenance shown *inline* on every figure (hover → definition + owner + SQL + validation + freshness), not behind a drawer click. | The visible proof of B-7; turns "trust me" into "here's why." | K3 lineage ✅ (drawer built) |
| **B-10** | **Deterministic, harder benchmark** — a larger real-warehouse eval with deterministic decode so a real lift is *visible*, not drowned in cloud noise (UNIFY made it unconfounded but small). | Makes every governance/capability claim *provable*, not asserted — the honesty infrastructure. | UNIFY eval ✅, `runs_detail` zero-LLM re-score ✅ |

Sequencing recommendation after this arc: **B-7 enforce → B-9 receipts-visible → B-8 governance workflow
→ #12 identity → B-10 benchmark** (the 5-step criticality plan below).

---

## Recommended execution order

| Step | Items | Effort | Why first |
|---|---|---|---|
| 1 | WCH-1 (blank canvas) | S | Root-caused, user-visible, 15 lines |
| 2 | WCH-4, WCH-5, WCH-7 (orphan fixes) | S×3 | Tiny, kill the intermittence engine |
| 3 | WCH-2 (sample data package) | M | Repro → fix → verify chain ready |
| 4 | WCH-3 (ontology truthfulness) | M | Depends conceptually on WCH-6 finding |
| 5 | WCH-6, WCH-8 (resume + write coordination) | M | Completes lifecycle correctness |
| 6 | WCH-9 (stress suite) | L | Locks in 1–5; finds what the scans missed |
| 7 | WCH-11, WCH-12 (poll storm + schema cache) | S×2 | Big wins, small diffs |
| 8 | WCH-15, WCH-16 (motion system + rollout) | M | The "feels SOTA" deliverable |
| 9 | WCH-13 (LLM parallelism) | M | Measured before/after |
| 10 | WCH-10, WCH-17, WCH-14 | M | Contract tests, felt-quality, optional parallelism |

Then: UNIFY → B-1 → B-3 → #12 (see Phase 5).

---

## ▶ NEXT 5 STEPS — by criticality (2026-06-10, post-UNIFY)

The wedge is **trustworthy autonomy**. With the kernel (K0–K4), motion, proof harness, and UNIFY
done, the highest-criticality moves all sharpen that wedge — the Semantic Governance Plane (K5) —
then secure deployment. Ordered by impact × unblocks, constrained by dependency.

| # | Step | Why it's #N (criticality) | Effort | Depends on |
|---|---|---|---|---|
| **1** | **B-7 — Lock the AI to registered metrics** (use-only-registered enforcement contract + measured enforcement rate) | THE trust differentiator and the cheapest big win: the registry exists (UNIFY), the guards exist — compose them into a hard gate. "The AI can't improvise the numbers" is the wedge a CFO buys. | M | UNIFY ✅ |
| **2** | **B-9 — Trust Receipts default-visible** (K3 lineage surfaced inline on every figure, not a drawer) | Makes step 1 *provable at a glance* — "net revenue, defined by Finance, this SQL, validated." Mostly built (K3); the delta is default-visible. Steps 1+2 together = the demo that wins enterprise. | S–M | K3 ✅ |
| **3** | **B-8 — Metric governance workflow** (propose → approve → version → audit; metrics become governed Ledger artifacts) | Turns the registry from a file I edit into an object Finance owns. The enterprise semantic-layer table-stake. Heavier, and it needs identity → why #12 is #4. | L | K0/K3, partial on #12 |
| **4** | **#12 — Enterprise identity** (OAuth2/OIDC + RBAC + tenancy + query cancel + secrets) | The substrate that makes "ownership/approval" real (no "Finance" without identity) AND gates every real deployment. Licensing foundation already dark-launched. | L | licensing/ ✅ |
| **5** | **B-10 — Deterministic, harder benchmark** | Makes every claim above measurable instead of asserted — the honesty infrastructure. Lower user-facing criticality, high engineering-trust value; can run in parallel. | M | UNIFY eval ✅ |

**One-liner:** *teach the AI it may only use governed definitions (1), show the receipt by default (2),
let Finance govern those definitions (3) under real identity (4), and prove it all on an honest
benchmark (5).* That is the path from "good demo" to "platform a Fortune-500 data team trusts."

Smaller correctness items run alongside as they surface: the **narration-inversion guard** (the
"3 orders × 1 item" → "all orders have 3 items" bug), **WCH-8** .duckdb write coordination, and the
remaining **K4 follow-ups** (generated TS client, domain interfaces, god-file splits).

---

## Dead-endpoint triage table (WCH-10 — fill during execution)

| Endpoint | Decision (wire / CLI-keep / delete) | Notes |
|---|---|---|
| GET/POST/DELETE /ontology/skills* (5) | TBD | Skills subsystem — wire to UI or fold into actions |
| GET/PUT /security/budget* (3) | TBD | Cost governor UI candidate |
| GET/PUT /glossary* (3) | TBD | Semantic-layer curation UI candidate (Databricks-synonym borrow) |
| GET /query/cache/stats, DELETE /query/cache/{id} | TBD | Dev-tools panel? |
| GET /suggestions | TBD | Starter questions — wire to empty chat state |
| GET /ontology/autonomy, /schemas, /interfaces | TBD | OE backlog overlap |
| GET /actions/logs | TBD | Action Hub history view |
