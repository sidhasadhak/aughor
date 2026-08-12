# SQL Editor + Client Data Paradigm — Plan of Record (2026-08-12)

**Status:** ✅ DECIDED 2026-08-12 — all three decision points locked (DP-1
CodeMirror 6 · DP-2 antd→TanStack Table · DP-3 TanStack Query yes, scoped).
Real-time co-editing descoped. **Build from:
`docs/SQL_EDITOR_IMPLEMENTATION_ROADMAP_2026-08-12.md`.**
**Scope:** (1) a world-class, Databricks-style SQL editor as a new Data layer;
(2) adoption verdicts for PGlite, Durable Streams, TanStack Query, TanStack DB,
TanStack Router. All claims below were verified live on 2026-08-12 (codebase
sweep + web research); nothing is from memory.

---

## 0. The narrative — what paradigm we are actually buying

Aughor today is **agent-first**: humans ask, agents write and run SQL, humans read
receipts. The platform has no first-class surface where a *human* does data work
directly — the closest thing is the visual Query Builder with a 400-line
hand-rolled textarea editor. The paradigm shift is:

1. **A pro-grade human surface** (the SQL editor) that sits on the *same*
   contract the agents use — same `/query/run`, same guards, same receipts, same
   audit log. Human SQL and agent SQL become peers in one provenance system.
   That is the actual Databricks move, not the syntax highlighting.
2. **A real client data layer** underneath it. The web app currently has *no*
   fetch/cache library — plain `fetch` + `useEffect` + **13 components running
   their own `setInterval` polls**. The editor is the beachhead for fixing that.
3. **Resumable streams** as the transport direction. Aughor is SSE-everywhere
   with one hand-rolled resume cursor. The industry (and now Databricks, via
   the Electric acquisition **announced 2026-08-11**) is converging on
   offset-resumable HTTP streams. We align the pattern now, adopt the protocol
   when it matures.

The five researched technologies slot into that narrative — none of them *is*
the paradigm; two of them (TanStack Query, Durable Streams pattern) build it,
three are watchlist with explicit triggers.

---

## 1. Ground truth (verified 2026-08-12)

### 1.1 What already exists — this is an extension, not a greenfield

| Editor need | Status today |
|---|---|
| Run SQL → rows + columns | ✅ `POST /query/run` (`aughor/routers/query.py:58`) — guards, cache, receipts |
| Saved queries | ✅ full org-scoped CRUD `/saved-queries` (`query.py:836`) |
| Query history | ✅ `audit_log.sql_full` captures every builder run (`security/audit.py:72`), exposed at `GET /security/audit` |
| Server-side validation | ✅ `POST /query/validate` — guard battery + sqlglot parse **in the connection's real dialect** |
| Schema tree | ✅ `GET /catalog/tree`; rich per-connection schema already on the client via `web/lib/schema-context.tsx` |
| Per-table column types | ✅ `GET /connections/{id}/tables/{table}/columns` |
| An editor UI | ⚠️ hand-rolled: `QueryBuilder.tsx:596-634` (textarea + `<pre>` highlighter, manual caret math), plus a *second* independent highlighter in `ChatMessage.tsx:474` |
| Results table | ⚠️ `SqlResultTable` (antd wrapper, `web/components/AugTable.tsx:210`) |
| Split panes, keep-alive layers | ✅ `ResizableSplit.tsx`, `Workspace.tsx` keep-alive (`:130-152`) |

### 1.2 The five contract gaps that block "top-class"

1. **Everything is a string.** All executors do
   `str(v) if v is not None else "NULL"` (`db/connection.py:814`, `:1104`,
   `local_upload.py:1189`). A real NULL and the string `"NULL"` are
   indistinguishable; numerics can't right-align; dates can't format.
   `columns` is `list[str]` — **no types**.
2. **No truncation flag.** Effective cap is 500 rows (three layers:
   `query.py:29` request default, `MAX_ROWS=500` at `connection.py:437`, budget
   10k at `sandbox.py:21`). Truncation is only inferable via
   `row_count > rows.length`, and `row_count` semantics differ by backend
   (DuckDB = true total; Postgres = `cur.rowcount`, often −1).
3. **Dialect is not exposed.** It lives only as Python class attributes
   (`connection.py:483-492`). Critically, **not everything is DuckDB**:
   BigQuery/Snowflake/MySQL/Exasol run user SQL **verbatim** on the remote
   engine (`writes_native_sql=True`); Postgres/SQLite get sqlglot-transpiled
   from DuckDB. A dialect-aware editor cannot be built without this field.
4. **No cancel, no timeout.** `sandbox.py:24` documents it: budgets are
   post-hoc audit tags. A cartesian join blocks a threadpool worker until the
   engine finishes. The template for fixing this exists:
   `_investigation_job_streamed` (`routers/investigations.py:4110`) — kernel
   job + SSE relay with real PENDING→…→CANCELLED lifecycle.
5. **Security gaps on the run route.** No RBAC `policy.py` entry for any
   `/query/*` route, and `/query/run` resolves `conn_id` from the body with
   **no org predicate** (`db/registry.py:319`) — org A can run SQL against
   org B's connection in multi-tenant mode. Same gap on `/query/semantic`,
   cross-source-join, federated-answer, text-columns, measure-grains, distinct.
   **This is a prerequisite fix, not a nice-to-have** (flagged as its own task).

Also known: `/query/run` wraps SQL as `SELECT * FROM ({sql}) __q LIMIT n`
(`query.py:125`) ⇒ single statement only, and `_validate` requires a
`Select`/`Union` root ⇒ `DESCRIBE`/`PRAGMA`/`SHOW`/`EXPLAIN` are rejected.
The audit log stores the *rewritten* SQL (post-transpile/RLS), not keystrokes.

### 1.3 Ecosystem facts that changed the stack evaluation

- **Databricks acquired Electric (ElectricSQL) on 2026-08-11** — PGlite, the
  Electric sync engine, Durable Streams, TanStack DB all stay open source;
  **Electric Cloud (managed) is discontinued**. Electric folds into Neon/Lakebase.
  Stated rationale: thousands of disposable local DBs for agents, synced
  centrally — the sync engine, not PGlite, is what Databricks wanted.
- **monaco-sql-languages** (MIT, active): dialects = MySQL, Flink, Spark, Hive,
  Trino, **PostgreSQL**, Impala, GenericSQL. **No DuckDB, no BigQuery, no
  Snowflake.** README: "only guaranteed to work stably on monaco-editor@0.37.1"
  vs current monaco 0.56.0.
- **@monaco-editor/react** loads monaco **from a CDN by default** (jsdelivr);
  self-bundling needs per-worker wiring that has a history of breaking under
  **Turbopack** — and web/ is Next 16.2.6 (Turbopack default), `next.config.ts`
  deliberately bare.
- **glide-data-grid**: MIT, technically excellent, but **no stable release
  since Feb 2024**; React 19 support only in `6.0.4-alpha24+`; requires peer
  `lodash`, `marked`, `react-responsive-carousel`. Web is React **19.2.4
  hard-pinned**. Riskiest maintenance profile in the list.
- **CodeMirror 6 + @codemirror/lang-sql**: MIT, ~98 kB gz for the whole closure
  (~10× lighter than Monaco), **schema-driven autocomplete built in**
  (`sql({schema})`), PostgreSQL dialect (no DuckDB — same as everyone).
  Existence proof: **Outerbase Studio ships exactly
  CM6 + sql-formatter on Next 15 + React 19.** (Repo moved to Marijn's
  self-hosted forge 2026-04; npm publishing continues.)
- **dt-sql-parser** (MIT, active, editor-agnostic): `validate()`,
  `getSuggestionAtCaretPosition()`, `splitSQLByStatement()`, `getAllEntities()`.
  20 MB unpacked, ANTLR — one dialect import only, run in a Web Worker.
- **sql-formatter** (MIT, maintenance mode but stable): supports **both
  postgresql and duckdb**.
- **TanStack Query 5.101** stable/MIT/React-19-green. **TanStack DB 0.6** —
  self-declared **BETA**; its most-matured adapter is the Query-backed
  collection (`@tanstack/query-db-collection` 1.2.1). **TanStack Router/Start**:
  no coexistence pattern with Next.js — replacement or separate SPA only.
- House rules that bind any new component: 5 CI lint gates; Monaco/canvas
  theming must copy the `AugTable.tsx:22-80` computed-token pattern
  (`getComputedStyle` + `MutationObserver` on `data-theme`, literal fallbacks);
  `lint:vars` rejects `var()` inside anything named like a color map; new
  buttons must be `<Button>`; counts/durations must use `@/lib/format`;
  `.npmrc` `min-release-age=7`; CI regenerates `api.gen.ts` and fails on drift.

---

## 2. The SQL editor program

### 2.1 Instantiating the prompt's placeholders

- **Framework:** React 19 / Next 16 App Router (client-only layer, `ssr:false`).
- **Dialect:** *per-connection*, resolved at runtime. Lingua franca is DuckDB
  (workspace + duckdb-family connectors); Postgres/SQLite transpiled;
  BigQuery/Snowflake/MySQL native. Client dialect mapping: duckdb-family →
  PostgreSQL grammar (closest available in every candidate library),
  postgres → PostgreSQL, mysql → MySQL, everything else → GenericSQL.
- **Backend contract:** `POST /query/run` (extended, §2.3) + existing
  `/catalog/tree`, `/connections/{id}/tables/{t}/columns`, `/query/validate`,
  `/saved-queries`, `/security/audit`.

**Key architecture consequence of the dialect gap:** no client-side parser
covers DuckDB/BigQuery/Snowflake — but the backend already validates in the
*true* dialect via sqlglot. So diagnostics are **two-tier by design**:

- Tier 1 (instant, approximate): client parser in a worker — squiggles as you
  type, best-effort grammar.
- Tier 2 (debounced ~600 ms, authoritative): `POST /query/validate` — the
  connection's real dialect + the guard battery. Server verdicts override
  client ones; guard findings render as warnings, not errors.

This turns the platform's guard battery into a *visible editor feature*
(inline "this query is suspicious because…" before you even run) — something
Databricks does not have.

### 2.2 Decision Point 1 — editor engine ✅ DECIDED: CodeMirror 6 (2026-08-12)

The build prompt named Monaco as the default and said "ask before
substituting"; the ask was made and **CodeMirror 6 was chosen.** The table
below is the decision rationale, kept for the record; the architecture stays
engine-swappable regardless.

| | Monaco + monaco-sql-languages | CodeMirror 6 + lang-sql + dt-sql-parser |
|---|---|---|
| Weight | 97.9 MB pkg, multi-MB shipped + workers | ~98–124 kB gz total, no workers needed for completion |
| Next 16/Turbopack | CDN loader by default (external origin — clashes with local-first posture, `config.ts:5-8`); self-bundle = per-worker wiring with Turbopack history | Bundles like any lib; SSR-safe with `ssr:false`; **proven combo (Outerbase, Next 15 + React 19)** |
| Version risk | monaco-sql-languages "guaranteed stable" only on monaco **0.37.1** vs current 0.56 | lang-sql active; forge moved, npm cadence intact |
| Completion | keyword/snippet OOTB; schema completion is DIY `CompletionService` either way | schema completion **built in** (`sql({schema})`); context-aware slots via dt-sql-parser if we want more |
| Diagnostics | dt-sql-parser via the wrapper | dt-sql-parser directly (same lib, worker) — Tier 2 is the server anyway |
| Theming / lint gates | canvas-ish DOM; `defineTheme` needs **literal hex** via the AugTable computed-token pattern | DOM + CSS — design tokens (`var(--…)`) apply natively; also dodges the unlayered global `textarea` rules that bit QueryBuilder |
| Feel | literal VSCode: minimap, multicursor muscle memory | Databricks *feel* comes from completion/diagnostics/grid/latency — all engine-independent; CM6 powers Outerbase, Replit (formerly), CodePen |

Monaco remains the right call **if** VSCode parity itself (minimap,
multi-cursor, find/replace UI, users' muscle memory) is a product requirement.
If chosen: pin monaco to the monaco-sql-languages support matrix, self-host via
`loader.config({ monaco })` (no CDN), and budget a Turbopack worker-wiring
spike *first*.

Either way the modules are: `SqlEditorPane` (the only engine-aware file),
`completion/` (schema source + provider), `diagnostics/` (worker client +
server validate), `ResultsPanel`, `SchemaSidebar`, `HistoryPanel` — engine-blind.

### 2.3 Backend work — Wave SE-0 (prerequisite, thin, high-leverage)

1. **Typed results, opt-in.** `POST /query/run` gains `format: "typed"`:
   `columns: [{name, type}]` (from cursor description + `norm_type`), rows as
   JSON-native values with **real `null`** (fix the `"NULL"` collision), and an
   explicit `truncated: bool`. Legacy path stays byte-identical (agent prompts
   and receipts must not shift). Implementation tactic (param threaded to
   executors vs. a typed sibling of `execute`) left to the build session — the
   invariant is *legacy output unchanged*.
2. **Expose dialect.** Add `dialect` + `writes_native_sql` to
   `GET /connections`. Trivial server-side; unblocks everything client-side.
3. **Security prerequisite.** Org-scope guard on every body-`conn_id` query
   route (the pattern exists at `query.py:853` / `briefs.py:74`) + a
   `policy.py` entry for `/query/run`. Do this *before* giving the editor more
   reach, not after.
4. **Source label.** `gate_user_sql(conn_id, "sql_editor", …)` instead of the
   hardcoded `"query_builder"` so editor history is filterable in the audit log.
5. Regenerate `web/lib/api.gen.ts` in the same PR (CI enforces drift).

### 2.4 Frontend build — Waves SE-1 → SE-3

**SE-1 — the editor lands (usable daily from day one):**
- New Data layer: `DATA_LAYERS` + `NavTab` `"sql"` (`page.tsx:504`, `:93`,
  `:1468`, legacy mapping `:1821`, render branch `:2239`). The Workspace
  keep-alive layers (`Workspace.tsx:130-152`) preserve buffers/results across
  tab switches for free.
- `SqlEditorPane` (CM6 per DP-1): per-connection dialect, `--font-code`,
  token-native theme, ⌘/Ctrl+Enter.
- **Statement-under-cursor:** dt-sql-parser `splitSQLByStatement()` in a
  worker; run the statement containing the cursor, or the selection. (The
  server wrap enforces single-statement — the client does the splitting, which
  is also how multi-statement "Run all" works later: a sequential loop.)
- Completion v1: schema-driven (`sql({schema})`) fed from
  `schema-context.tsx` + `/catalog/tree`; per-table column types lazy-loaded
  on first reference of a table and cached.
- Results: reuse `SqlResultTable` behind a new `ResultsGrid` seam; show
  `row_count`, `duration_ms`, `truncated`, `receipt_id` (link to receipt);
  errors render inline in the panel (never a toast). All numbers through
  `@/lib/format` (lint:format).
- Saved queries (existing CRUD, `spec: {}`), draft persistence in
  `localStorage["aug.sqledit.draft:<connId>"]` (versioned payload, never read
  in a `useState` initializer — hydration rule at `page.tsx:1494-1500`).

**SE-2 — "top-class":**
- Two-tier diagnostics (§2.1) with squiggles + a problems strip.
- Format-on-shortcut via sql-formatter (duckdb/postgresql per connection).
- Schema sidebar: reuse `CatalogScreen` tree idioms (`TreeRow`, expansion-set,
  recents, `typeColor()`), insert-on-click, drag-to-editor.
- History panel: `GET /security/audit` filtered to `sql_editor` +
  connection; click-to-restore. (Server truth = rewritten SQL; the local draft
  ring keeps verbatim keystroke history.)
- Copy cell / copy column / CSV export (client-side from typed rows).
- Collapse the duplicate highlighters: `ChatMessage.tsx` `FormattedSql` and
  QueryBuilder's `SqlEditor` adopt a shared read-only `SqlView` built on the
  same engine; the seven plain-`<textarea>` SQL inputs (Metrics, Monitors,
  EvalSuites, AgenticAgents, FixItForm, SemanticLayer, AddToEvalSuite) migrate
  to a compact single-statement editor input over time.

**SE-3 — execution v2 (backend + frontend):**
- Cancellable runs: kernel-job bridge (the `_investigation_job_streamed`
  pattern) + engine interrupt (DuckDB `interrupt()`, Postgres cancel); real
  timeout enforcement replacing the post-hoc budget tag; Run button becomes
  Run/Cancel with elapsed ticker.
- Bulk mode: raise the editor path toward the 10k budget with the canvas grid
  (DP-2), `use_bulk` where the connector supports it.
- Metadata statements: allowlist `DESCRIBE`/`SHOW`/`EXPLAIN` (read-only) past
  `_validate`'s Select/Union root requirement, unwrapped.

### 2.5 Decision Point 2 — results grid ✅ DECIDED (2026-08-12)

The prompt mandated glide-data-grid; the research showed its stable release
**cannot install against React 19** (alpha-only for 2.5 years, 3 stray peer
deps, canvas a11y/theming caveats). **Decision:** SE-1 ships on the existing
antd `SqlResultTable` behind a `ResultsGrid` seam (500-row cap makes it
fine); SE-3 bulk mode adopts **TanStack Table + TanStack Virtual** (headless,
stable, MIT, DOM-based — tens of thousands of virtualized rows, tokens apply
natively, real DOM cells for a11y/browser-find). glide's 100k+ canvas
superpower solves a problem this product doesn't have (receipts + CSV export
cover big data); its re-entry condition is a real need for 100k+
*interactive* rows. The seam makes any later swap a component change.

### 2.6 Combining the SQL editor and the Query Builder — one workbench, two modes

Shipping the editor as a *sibling* layer to the builder would fork the UX:
two results panels, two saved-query surfaces, two catalog rails, two run
pipelines. Instead: **one "Query" workbench layer with a Visual | SQL mode
toggle** (the Metabase/Looker pattern), built on three facts already in the
code: the builder compiles chips→SQL deterministically
(`buildSql`, `QueryBuilder.tsx:419-500`), the reverse path exists
(`importSqlToBuilder` → `POST /query/decompile`, which honestly returns
`{ok:false, reason}` for CTEs/set-ops), and **saved queries already persist
both representations** (`{sql, spec}`).

**Principles (the part that prevents the classic two-representations mess):**
1. **SQL is canonical; the spec is a projection.** Every run — either mode —
   executes SQL through the same pipeline (same guards, receipts, audit).
2. **Single writer.** The active mode is the only writer; the other renders a
   read-only preview (visual mode shows live compiled SQL via the shared
   `SqlView`; SQL mode shows chips only when linked).
3. **Lossy transitions are explicit, never silent.** Visual→SQL always works
   (compile). SQL→visual attempts decompile: success → `linked`; failure →
   **`sql-ahead`** state — the visual tab shows "this query isn't
   representable in the builder (reason)" with an explicit, confirmed option
   to restore the last linked spec (discarding SQL edits). Decompile never
   destructively re-imports over user SQL.
4. **Persistence encodes the state:** `spec` present ⇔ linked; `spec` absent
   ⇔ SQL-only. (Replaces today's convention of `spec: {}`.)

**Code plan** — a staged refactor of `QueryBuilder.tsx` (2,600 lines):
```
web/components/query/QueryWorkbench.tsx   shell: connection + default-schema
                                          pickers, mode toggle, run/cancel,
                                          tabs, ResultsPanel, history rail,
                                          saved/drafts, palette commands
web/components/query/modes/SqlMode.tsx    the SE-1 editor module
web/components/query/modes/VisualMode.tsx the chips UI, extracted
web/lib/query/spec.ts                     spec type + buildSql moved out of the
                                          component (pure, unit-testable)
web/lib/query/specSync.ts                 linked/sql-ahead state machine +
                                          decompile client
```
- **Stage A (SE-1):** mount `QueryWorkbench` as the new layer with the mode
  toggle; Visual mode initially *embeds the existing QueryBuilder unchanged*,
  SQL mode is the new editor. Nav changes once, not twice:
  `DATA_LAYERS` becomes `catalog | query | semantic`, URL is
  `?tab=query&mode=visual|sql`, and `LEGACY_DATA_LAYER` (`page.tsx:1821`)
  maps `builder → query(visual)` so old links keep working.
- **Stage B (SE-2):** extract the shared shell — results, saved queries,
  history, catalog rail move from QueryBuilder into the workbench; both modes
  render inside it; the builder's embedded textarea editor and
  `ChatMessage`'s second highlighter both collapse into the shared `SqlView`.
- **Stage C (SE-4):** full `specSync` bidirectional flow (auto-decompile on
  mode switch, sql-ahead UX, linked-state chip), palette commands renamed
  `qb-*` → `query-*`, and the `openInBuilder` seam generalized to
  `openInQuery({sql, mode: "auto"})` — chat's "Open in Query Builder" becomes
  "Open in Query", landing in visual mode when the SQL decompiles and SQL
  mode when it doesn't.

**What each mode uniquely keeps:** statement-under-cursor, diagnostics,
folding, format — SQL mode only. Chip ergonomics, guided joins,
`build-sql` assistance — visual mode only. Everything else (run, results,
receipts, caveats, history, saved, schedule→monitor, share) is workbench
chrome and mode-blind. Audit label: one `query_workbench` label for both
modes (keeps history unified; the receipt already records the SQL).

---

## 3. The five technologies — verdicts

| Tech | Verdict | One-line rationale |
|---|---|---|
| TanStack Query | **ADOPT (scoped beachhead)** — DP-3 | The app has no fetch layer and 13 hand-rolled polls; stable, MIT, React-19-green |
| Durable Streams | **ALIGN NOW, ADOPT PROTOCOL LATER** | Beta (8 mo) but exactly aughor's SSE-resume pain; Databricks gravity de-risks the spec |
| PGlite | **PARK, WATCH** | Postgres-flavored where aughor's lingua franca is DuckDB; the *sync engine* is the strategic piece |
| TanStack DB | **SPIKE LATER (after Query)** | Self-declared beta; QueryCollection path is the safe entry once Query is in |
| Electric Postgres Sync | **FUTURE BACKBONE (explicit trigger)** | GA + Supabase-compatible and fits our read/write split exactly — but requires an always-on service, which breaks the serverless-only posture |
| TanStack Router/Start | **N/A (explicit trigger)** | No coexistence with Next.js; only relevant if a separate SPA ever exists |

### 3.1 TanStack Query — Decision Point 3 ✅ DECIDED: ADOPT, SCOPED (2026-08-12)

**Conflict to resolve honestly:** `docs/PLATFORM_REVIEW_AND_IMPLEMENTATION_PROGRAM_2026-07-12.md:1038`
says "no SWR-React-Query rewrite," and `docs/WORLD_CLASS_HARDENING_PLAN.md:314`
prescribes a tiny in-house SWR-style cache instead. Those decisions predate
this program and were about not *rewriting* the app mid-unification.

**Decision: adopt, scoped, and write the supersession note** (in the same PR
that adds the dependency — roadmap PR A). Rationale:
(a) the editor is a *new* surface — no rewrite involved; (b) the roadmap here
(live schema cache, history invalidation, later TanStack DB collections) is
exactly what Query is for, and TanStack DB — which we expect to spike within
two quarters — *layers on Query*; hand-building a cache now means building the
foundation twice; (c) 5.101.4, MIT, React 19 peer — zero compat risk.
Scope discipline: `QueryClientProvider` mounted at the SQL-editor layer (or
app-root with usage confined to new code); **no migration of existing
components** until the editor proves the pattern; the 13-poll cleanup becomes
opportunistic follow-up, not a wave.
If the call is to honor the July docs instead: build the tiny cache for SE-1
(schema + columns memoization is genuinely small) and revisit at the DB spike.

### 3.2 Durable Streams — the pattern now, the protocol when it lands

Aughor is SSE-everywhere (no websockets anywhere), with exactly one resumable
stream: `/events/stream` with a `since_seq` cursor (`routers/events.py:46-84`)
— a hand-rolled proto-durable-stream over the kernel journal. Chat and
investigations are **not resumable**: refresh mid-investigation and the SSE is
gone (the kernel job survives; the byte stream doesn't — that's why the job
bridge and the poll fallbacks exist).

- **Now (Wave DX-2):** make `/chat` / `/investigate` / `/ask` streams
  offset-resumable over the kernel journal — client sends last-seen offset on
  reconnect, server replays from there. This is a pure-FastAPI change using
  infrastructure that already exists, and it fixes a real UX hole (refresh
  mid-answer). Design the frame/offset semantics to be Durable Streams
  PROTOCOL.md-shaped (addressable stream URL, offset param, catch-up then
  live), so a later swap to the real protocol is a transport change.
- **Later:** adopt the protocol proper (MIT; Caddy plugin or Node reference
  server; Python + TS clients exist) when it exits Beta — with the note that
  its hosted offering died with Electric Cloud, so self-host is the only path.
  The March 2026 durable-transport adapters (Vercel AI SDK, TanStack AI) are
  the sign this is becoming the standard AI-streaming substrate.

### 3.3 PGlite — the acquisition matters more than the library (for us)

PGlite is a real embedded WASM **Postgres** (<3 MB gz, Apache-2.0, 13M
weekly downloads, pre-1.0). Aughor's in-browser twin would more naturally be
**DuckDB-WASM** — same dialect as the platform's lingua franca. Concrete
aughor fits, none urgent:
- **In-browser demo/playground:** the SQL editor running fully client-side
  against a WASM engine + Superstore — zero backend, instant trial. If built,
  prefer DuckDB-WASM (dialect-true); PGlite only if we want Postgres-semantics
  demos. PARK until the editor exists.
- **Hermetic Postgres for tests:** `py-pglite` is third-party, a Node
  subprocess wrapper, dormant ~11 months, single-connection. Current 17s-reseed
  suite is better. NO.
- **Zero-dep local install** (replace Postgres for single-user local mode):
  attractive posture-wise, but PGlite is single-connection by design vs. 19
  stores × threads. NO for now.
- **The real signal:** Databricks bought the *sync engine* to give agents
  thousands of disposable synced DBs. Aughor's analog already exists (DuckDB
  workspaces per connection); the missing half is *sync/multi-device*, which is
  the Electric engine + TanStack DB story — revisit when local-first
  multi-device becomes a product goal.

### 3.4 TanStack DB — after Query, behind a seam, non-core first

Reactive collections + differential-dataflow live queries + optimistic
mutations. Beta (0.6 core / react-db 0.1.x), MIT. The fit is real — catalog
tree, connections, monitors, briefing feeds are all poll-refreshed collections
today — but the stability posture says: **spike on one non-core surface**
(e.g., the editor's history panel or the catalog tree) using the
**QueryCollection** adapter (its most mature, 1.2.1, no sync server needed),
only after Query is in. ElectricCollection (real Postgres sync) is the local-first future — see §3.5
for the full Electric feasibility read and its trigger condition.

### 3.5 Electric Postgres Sync — studied (electric.ax/sync/postgres-sync, 2026-08-12)

**What it is:** the read-path sync engine for Postgres — "partial replication,
data delivery and fan-out." Clients subscribe to **shapes** (a SQL query:
table + WHERE + column projection); the engine consumes Postgres logical
replication and fans the shape log out over plain HTTP/JSON that CDNs cache
(same log, same ordering, to every subscriber). Client live queries narrow
within a shape ("query-driven sync"). GA (1.0 in Mar 2025, now 1.7.x),
Apache-2.0, Elixir service. **Read-path only by design** — writes stay in your
API, with TanStack DB optimistic mutations as the optional client layer.
Integrations listed first-class: **Supabase**, Neon, TanStack DB, PGlite,
React/Next.js.

**Aughor feasibility read:**
- **The fit is unusually clean.** Aughor's client-visible state (connections,
  insights, briefings, monitors, exploration status — the stuff behind the 13
  polls) already lives in Supabase Postgres `store_*` schemas, and all writes
  already go through FastAPI. That is *exactly* Electric's architecture:
  reads sync down via shapes, writes go up via your existing API. No data
  model change required.
- **The blockers are operational, not architectural.** (1) Electric is an
  always-on Elixir service with persistent disk for shape logs — it cannot run
  on Vercel; adopting it re-introduces a second runtime (Fly/Render/Supabase
  compute) after the Vercel-native arc deliberately got rid of always-on
  infra. (2) It needs a **direct, non-pooled** Postgres connection with a
  REPLICATION role — aughor's Supabase usage is pooler-centric (and the
  Catalog form still mishandles pooler DSNs, `db/connection.py:984`); a
  replication slot on the Supabase primary is new operational surface.
  (3) Multi-tenancy: shapes are WHERE-clause-scoped, so org isolation must be
  encoded in every shape definition — same class of guard as the RLS work,
  and the same place a mistake becomes a cross-tenant leak.
- **Verdict: FUTURE BACKBONE, not a current wave.** When real-time,
  multi-client sync becomes a product goal (shared dashboards updating live,
  local-first multi-device, the DX-3 ElectricCollection spike), Electric is
  the engine — GA, production-proven (Trigger.dev), Databricks-backed, and
  aligned with the TanStack DB adapter we'd already be using. Until then,
  DX-2's resumable streams over the kernel journal deliver the visible UX win
  (mid-answer refresh survival) without a new always-on service.
  **Trigger:** the first feature that needs *server-pushed state shared
  across clients* (not per-request streams) — that's the moment to stand up
  one Electric instance against a replica/branch and spike an
  ElectricCollection on a single table (e.g. `insights`).

### 3.6 Ontos (databrickslabs/ontos) — studied 2026-08-12

**What it is:** Databricks Labs' "Business Semantics for Unity Catalog" — a
governance layer that sits *on top of* a catalog: **data products** (group
tables/views/models/dashboards into owned, lifecycle-managed products, ODPS),
**data contracts** (schema + quality rules + SLOs + semantic meaning, **ODCS
v3.1.0**), a **business glossary / knowledge graph** linking technical assets
to business concepts (RDF), a **declarative compliance DSL** (policies →
automated checks → tag/notify/enforce), **steward review workflows** with
AI-assisted analysis and audit trails, six-role RBAC, and — notably — the
whole platform **exposed to AI assistants via MCP**. Stack: React + Tailwind
+ shadcn / FastAPI + SQLAlchemy / Postgres, prod on **Lakebase** (Neon), runs
as a Databricks App. ~200 stars, active, Labs-tier (not a supported product).
**License: Databricks License — source-available. Reference its patterns;
never vendor its code.** The standards it implements (ODCS/ODPS, Bitol under
the Linux Foundation) are open and freely implementable.

**Why it matters to aughor — three take-aways:**
1. **Strategic validation.** Databricks is assembling exactly aughor's shape:
   catalog (UC) + business semantics (Ontos) + Postgres (Neon/Lakebase) +
   sync (Electric) + a first-class SQL editor. Aughor has all five in
   miniature — plus the piece Ontos lacks entirely: an agent that *answers
   questions* with the semantics, not just governs them. The ontology→agent
   loop is the moat; keep investing there.
2. **ODCS data contracts are the adoptable piece.** Aughor already has
   informal schema pinning — and the currency-VARCHAR incident proved an
   informal contract + an ingest transform = silent data loss on reload. A
   formal ODCS-shaped contract per connection/table (schema + quality rules +
   expectations, checked at ingest/reload, violations surfaced as findings)
   is the systematized fix, and it slots into existing machinery (guards,
   monitors, briefs). Candidate future wave; not part of the editor program.
3. **The concept↔asset model is the formalization target for aughor's
   ontology.** Ontos's glossary-terms-linked-to-tables/columns knowledge
   graph is what ground-first resolution needs (resolve business entity →
   table/column *before* SQL generation). Aughor's context graph + glossary +
   ontology_overrides already hold the raw material; Ontos is the reference
   for the linking model. Also worth stealing as a *direction*: *aughor as an
   MCP server* — exposing catalog/ontology/insights so external assistants
   (Claude, IDEs) can consume aughor as a context provider.

**Verdict: STUDY-AND-ADOPT-STANDARDS** — implement ODCS-shaped contracts and
the concept-linking model on aughor's own machinery when prioritized; treat
the repo as a same-stack (React/shadcn/FastAPI) design reference only.

### 3.7 TanStack Router / Start — trigger condition only

Verified: no documented pattern for Router inside an existing Next.js app;
Start is RC and Vite-only. **Trigger to revisit:** if "apps natively on the
app" (user-authored mini-apps hosted by aughor) or a standalone editor SPA
ever becomes real, a Vite + Router SPA is the right shell for *that* — not for
web/.

---

## 4. Sequencing

```
SE-0  backend contract (typed results, dialect, security, label)   ← prerequisite
SE-1  editor lands (new layer, CM6*, completion v1, run, results, saved)
SE-2  top-class (2-tier diagnostics, format, sidebar, history, export, unify highlighters)
SE-3  execution v2 (cancel/timeout via kernel jobs, bulk + canvas grid*, metadata stmts)
DX-1  TanStack Query scoped adoption* + supersession note          ← parallel to SE-2
DX-2  resumable chat/investigate streams (Durable-Streams-shaped)  ← independent
DX-3  watchlist spikes: TanStack DB (QueryCollection), DuckDB-WASM playground
        * = pending Decision Points 1–3
```

SE-0+SE-1 is one shippable PR-pair; each later wave is independently mergeable.
Ratchet hygiene per house rules: run the ratchet/boundary tests on each diff;
frontend five gates + regenerated `api.gen.ts` in any PR touching routes.

## 5. Risks

- **Engine pick regret** — mitigated by the engine-blind module boundary; only
  `SqlEditorPane` knows the engine.
- **Dialect illusion** — client grammar says valid, real engine disagrees
  (esp. BigQuery/Snowflake verbatim connectors). Mitigated by Tier-2 server
  validation being authoritative and visually distinct.
- **Typed-results regression** — the stringify change must be opt-in;
  invariant: legacy path byte-identical (agent prompts/receipts).
- **glide-data-grid abandonment** — decision deferred to SE-3; seam makes the
  headless-table fallback cheap.
- **Doc conflict on Query** — resolved by writing the supersession note in the
  same PR that adds the dependency, not by silently contradicting the July doc.
- **Beta churn (TanStack DB / Durable Streams)** — both gated behind explicit
  later spikes; nothing in SE-0..SE-3 depends on either.

## 6. Explicitly not doing

- No TanStack Router/Start in web/ (no coexistence path with Next).
- No PGlite in product paths now; no py-pglite in CI.
- No global React-Query migration of existing components in this program.
- No agent-path `execute_guarded` for the editor — humans get their errors
  verbatim, never a silently self-corrected query (`sql/executor.py:142` is
  for agents).
- No raising of `MAX_ROWS`/budget caps outside the SE-3 bulk design.
