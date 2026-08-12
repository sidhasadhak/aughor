# SQL Editor — Implementation Roadmap (LOCKED 2026-08-12)

**Status:** BUILD-READY, but SEQUENCED BEHIND ARC CI. All decisions locked by
the user 2026-08-12. ⚠️ **Read `PLATFORM_ROADMAP_2026-08-12.md` first** — it is
the combined plan of record and it places **SE-0 first (its org-scope security
fix is a shared prerequisite), then all of Arc CI, and SE-1…SE-5a only after
CI-6.** Do not start SE-1 straight from this doc.
**Companions:** `SQL_EDITOR_PARADIGM_PLAN_2026-08-12.md` (strategy, contract
analysis, §2.6 builder-merge design) · `SQL_EDITOR_DATABRICKS_PARITY_2026-08-12.md`
(feature matrix). This doc is what an implementing session opens first.

## 0. Locked decisions

| # | Decision | Verdict |
|---|---|---|
| DP-1 | Editor engine | **CodeMirror 6** (`@codemirror/lang-sql`) + **dt-sql-parser** in a web worker (statement split + tier-1 diagnostics) + **sql-formatter**. Monaco rejected: CDN-default loader vs local-first posture, Turbopack worker wiring, monaco-sql-languages pinned to monaco 0.37.1. |
| DP-2 | Results grid | **SE-1: existing antd `SqlResultTable`** behind a `ResultsGrid` seam → **SE-3: TanStack Table + TanStack Virtual** for bulk (10k rows). **glide-data-grid rejected** (stable release excludes React 19; alpha-only 2.5 yrs; 3 stray peer deps; canvas a11y). Re-entry condition: a real need for 100k+ *interactive* rows. |
| DP-3 | TanStack Query | **YES, scoped.** Provider mounted once; only `query/` workbench code uses it; no migration of existing components in this program; **supersession note added to `docs/PLATFORM_REVIEW_AND_IMPLEMENTATION_PROGRAM_2026-07-12.md` + `docs/WORLD_CLASS_HARDENING_PLAN.md` in the same PR as the dependency.** |
| — | Builder merge | One **Query workbench**, `Visual \| SQL` modes (paradigm §2.6): SQL canonical, single writer, `linked`/`sql-ahead` states, decompile never destroys SQL. |
| — | Descoped | Real-time co-editing / presence / comments (SE-5b) — user decision. Git-backed queries. TanStack Router. PGlite. |

## 1. Dependencies (all MIT; all releases > 7 days old, so `.npmrc min-release-age=7` passes)

| Package | Version (verified 2026-08-12) | Wave | Notes |
|---|---|---|---|
| `codemirror` meta or `@codemirror/{state,view,language,autocomplete,lint,search,commands}` | 6.x current | SE-1 | prefer explicit packages over meta for tree clarity |
| `@codemirror/lang-sql` | 6.10.0 | SE-1 | dialects: PostgreSQL/MySQL/StandardSQL used |
| `dt-sql-parser` | 4.5.0 | SE-1 | **worker-only import, ONE dialect entry point** (pgsql); 20 MB unpacked if imported wholesale — never import on main thread |
| `sql-formatter` | 15.8.2 | SE-2 | has both `postgresql` and `duckdb` |
| `@tanstack/react-query` | 5.101.4 | SE-1 | React 19 peer ✅ |
| `@codemirror/merge` | current | SE-5a | diff view for Quick Fix (Outerbase precedent) |
| `@tanstack/react-table` + `@tanstack/react-virtual` | current stable | SE-3 | bulk grid |

No other new dependencies without a plan amendment.

---

## 2. Wave SE-0 — backend contract (1 PR, prerequisite)

All in `aughor/routers/query.py`, `aughor/routers/connections.py`,
`aughor/db/connection.py`, `aughor/rbac/policy.py`. Regenerate
`web/lib/api.gen.ts` in the same PR (CI enforces drift).

1. **Org-scope guard (security fix, do first).** Every query-router route that
   takes `conn_id` in the body resolves it with no org predicate
   (`db/registry.py:319`): `/query/run`, `/query/semantic`,
   `/query/cross-source-join`, `/query/federated-answer`,
   `/query/auto-federated-answer`, `/query/semantic/text-columns`, plus
   path-param routes that miss `connections.py`'s owner guard
   (`/connections/{id}/measure-grains`, `/distinct`). Apply the pattern from
   `query.py:853` / `briefs.py:74`. Add `policy.py` entries for `/query/*`.
   **Tests:** per-route cross-org attempt → 403/404.
2. **Typed results, opt-in.** `_QueryRunRequest` (+`format: "typed"`);
   response adds `columns_typed: [{name, type}]` (cursor description +
   `norm_type` + `apply_overrides`), rows JSON-native with **real `null`**
   (kills the `"NULL"` collision at `connection.py:814`/`:1104`/
   `local_upload.py:1189`), and `truncated: bool` (from the pre-slice count).
   **Invariant: the legacy (non-typed) path stays byte-identical** — agent
   prompts and receipts must not shift. **Tests:** golden legacy snapshot;
   typed test distinguishing SQL NULL from the string `'NULL'`; truncation
   flag at limit boundary.
3. **Dialect exposure.** `GET /connections` adds `dialect` +
   `writes_native_sql` (the class attributes at `connection.py:483-492`).
4. **Caveats forwarded.** `/query/run` response gains
   `caveats: list[str]` (already computed in `QueryResult`, currently
   dropped) — this is the "Checked for improvements" chip's data.
5. **Source label.** Run route accepts `source: "query_workbench"` label into
   `gate_user_sql` (today hardcoded `"query_builder"`, `query.py:72`) so
   editor history is filterable. Add `label`/`connection_id` filter params to
   `GET /security/audit` if absent (`routers/security.py:10`).

**Gate:** ratchet battery (`pytest -k "ratchet or boundary or swallow or
private"`) + targeted tests + `uvx ruff@0.15.20 check .`.

---

## 3. Wave SE-1 — workbench shell + editor core (2 PRs)

### PR A — nav + workbench scaffold (Stage A of the builder merge)
- `web/app/page.tsx`: `NavTab` + `"query"` (`:93`), `VALID_TABS` (`:1468`),
  `DATA_LAYERS` → `catalog | query | semantic` (`:504`), `LEGACY_DATA_LAYER`
  `builder → query` (`:1821`), render branch (`:2239`); URL contract
  `?tab=query&mode=visual|sql` (History-API sync, same as existing tabs).
- `web/components/query/QueryWorkbench.tsx`: mode toggle, connection picker,
  default-schema selector, run bar. **Visual mode = existing `QueryBuilder`
  embedded unchanged** (no surgery yet). Lazy via `next/dynamic`
  `{ssr:false}`; state survives via Workspace keep-alive layers.
- Mount `QueryClientProvider` here (DP-3 scope) + **write the supersession
  notes** in the two July docs.

### PR B — the SQL editor
- `web/components/query/modes/SqlMode.tsx` — mode container: editor +
  results split (`ResizableSplit storageKey="sqlmode"`).
- `web/components/query/editor/SqlEditorPane.tsx` — CM6 assembly:
  `sql({schema, defaultSchema, dialect})`, `autocompletion`, `history`,
  `search`, keymap (⌘/Ctrl+Enter → run, ⌘K passthrough), placeholder.
- `web/components/query/editor/theme.ts` — token-native theme: CM6 takes
  `var(--…)` directly (no computed-style plumbing); `--font-code`;
  explicit font-family/size (the unlayered `globals.css:97` input rules);
  light/dark follows `data-theme` automatically.
- `web/lib/query/dialect.ts` — `conn_type`/`dialect` (SE-0 field) → CM6
  dialect (duckdb-family + postgres → `PostgreSQL`, mysql → `MySQL`, else
  `StandardSQL`) and sql-formatter language (`duckdb`/`postgresql`/…).
- `web/lib/query/parserWorker.ts` — standard `new Worker(new URL(…))`
  (Turbopack-supported); imports **only** dt-sql-parser's pgsql entry;
  API: `split(sql) → StatementRange[]`, `validate(sql) → SyntaxError[]`.
- **Statement-under-cursor run:** selection if any, else the `split()` range
  containing the cursor → `POST /query/run {format:"typed",
  source:"query_workbench"}`.
- Completion source: `schema-context.tsx` tables + lazy per-table columns via
  TanStack Query (`['columns', connId, schema, table]`, staleTime ~5 min,
  invalidated by the existing schema-refresh seam).
- `web/components/query/ResultsPanel.tsx` + `ResultsGrid.tsx` (seam wrapping
  `SqlResultTable`): typed rendering (right-aligned numerics, `∅` null glyph,
  long-cell expander), footer `row_count`/`duration_ms`/`truncated`/receipt
  link — all through `@/lib/format` (lint:format). **Errors inline in the
  panel, never a toast.**
- Drafts: `localStorage["aug.sqledit.draft:<connId>"]` versioned
  `{v, sql, cursor}`; try/catch; never read in a `useState` initializer
  (hydration rule, `page.tsx:1494-1500`).
- ⌘K registrations: `query-run`, `query-format` (pattern:
  `QueryBuilder.tsx:1632`).

**Acceptance (SE-1):** against demo Superstore — completion offers real
tables/columns; ⌘↵ runs the statement under cursor; typed results render with
real nulls and a truncation notice; draft survives layer switch *and* reload;
`?tab=builder` deep-links land in Query/Visual; five frontend gates +
`npm run build` green.

---

## 4. Wave SE-2 — pro surface + workbench extraction (3 PRs)

### PR C — diagnostics + format
- `web/components/query/editor/diagnostics.ts` — CM6 `linter()`, two tiers:
  worker `validate()` at ~300 ms debounce (squiggles, approximate grammar);
  `POST /query/validate` at ~600 ms (authoritative, real dialect + guard
  battery). Server verdicts override; guard findings render as warnings with
  the caveat text. Post-run: caveats chip ("Checked — N notes").
- Format: sql-formatter with `dialect.ts` mapping; button + ⌘⇧F; formats
  selection or statement-under-cursor.
- `foldGutter` + fold keymap.

### PR D — sidebar, tabs, history, saved
- `web/components/query/SchemaSidebar.tsx` — reuse `CatalogScreen` idioms
  (`TreeRow` pattern, expansion `Set`, recents in
  `localStorage["aug.catalog.recents"]`, `typeColor()` for column types);
  lazy column nodes share the TanStack Query columns cache with completion;
  **click inserts qualified name at cursor; drag-to-editor**; fuse.js search.
- `web/components/query/TabsBar.tsx` — tabs
  `{id, name, sql, savedQueryId?}` in `localStorage["aug.sqledit.tabs:<connId>"]`
  (cap 20, LRU); per-tab last-run status chip.
- `web/components/query/HistoryRail.tsx` — `GET /security/audit` filtered
  `connection_id` + `label=query_workbench`; click restores SQL into a new
  tab; shows verdict/duration/rows from the audit row.
- Saved queries: reuse `/saved-queries` CRUD; `spec: null` for SQL-only;
  star flag; "Drafts" group from the local ring.

### PR E — extraction (Stage B of the builder merge)
- Extract from `QueryBuilder.tsx` into the workbench shell: results panel,
  saved-query dropdown, catalog rail. Both modes now share one results
  pane, one history, one saved surface.
- New shared `web/components/query/SqlView.tsx` (read-only CM6, no
  gutter) replaces QueryBuilder's textarea highlighter (`:596-634`) *and*
  `ChatMessage.tsx`'s `FormattedSql` (`:474`) — the two duplicate
  highlighters collapse.
- Chat↔editor: generalize `openInBuilder.tsx` → `openInQuery({sql, mode})`;
  chat's "Open in Query Builder" → "Open in Query".
- CSV export + copy-cell/copy-column on the results panel.

**Acceptance (SE-2):** intentionally broken SQL shows squiggles in <1 s and
the server's dialect-true error after; a BigQuery-only function passes tier 1
and is caught by tier 2; sidebar click inserts at cursor; history restores a
three-day-old query; both modes share one results panel; gates green.

---

## 5. Wave SE-3 — execution v2 (2 PRs, backend-heavy)

### PR F — cancel + timeout
- `POST /query/submit` → `{job_id}` via the kernel-job bridge pattern
  (`routers/investigations.py:4110` `_investigation_job_streamed`): submit to
  `kernel()`, relay status over the existing job surface (`routers/jobs.py`);
  cancel = existing `POST /jobs/{id}/cancel` + engine interrupt
  (DuckDB `conn.interrupt()`; Postgres backend cancel). Enforce
  `QueryBudget.max_time_ms` for real (today audit-only, `sandbox.py:24`).
- Frontend: Run ↔ Cancel button with elapsed ticker; falls back to plain
  `/query/run` for sub-second statements.

### PR G — metadata statements + bulk grid
- Allowlist `DESCRIBE`/`SHOW`/`EXPLAIN` (read-only, unwrapped) past
  `_validate`'s Select/Union root requirement (`connection.py:440-459`) and
  the subquery wrap (`query.py:125`).
- "See performance": profile drawer rendering DuckDB JSON plans + Postgres
  text plans; hide for connectors without EXPLAIN.
- `ResultsGrid` v2: TanStack Table + Virtual (sticky header, column resize,
  sort, virtualized rows); editor limit raised toward the 10k budget via the
  bounded-execution path (`execute_bounded`, `connection.py:587`).

**Acceptance (SE-3):** a deliberate cartesian join cancels within ~1 s and
frees the worker; 10k rows scroll at 60 fps; EXPLAIN renders for
DuckDB + Postgres and degrades gracefully for BigQuery.

---

## 6. Wave SE-4 — authoring & results parity (3 PRs)

### PR H — multi-statement + params
- "Run all": sequential loop over `split()` ranges; **one results tab per
  statement**, retained results capped (LRU 5 per editor tab).
- Parameters: worker detects `:name`; chips UI above the editor; backend
  `params: dict` on `/query/run` executed as **real bind values** (never
  interpolated — guard review required); typed inputs from param usage.
- Split-screen: second CM6 view in a `ResizableSplit`.
- Download menu: CSV/TSV/JSON/clipboard.

### PR I — results intelligence + viz
- NL result filters: plain-English → client-side filter chips over the
  in-memory result (chainable, no re-run). **Evaluate the existing
  `POST /query/postproc` (`query.py:750`) seam before building new.**
- Viz tab: "+" on results → ECharts builder seeded with the result columns;
  "Pin" via existing `pinQueryToDashboard` (`api.ts:1782`).
- Schedule → prefilled custom-SQL monitor (MonitorsPanel seam). Share =
  `?tab=query&conn=…&query=<savedId>` deep link.

### PR J — versions + specSync (Stage C of the builder merge)
- Saved-query versioning: append version rows on update (small store
  migration + endpoints); version rail + `@codemirror/merge` diff view.
- Full `specSync` state machine: auto-decompile on mode switch,
  `linked`/`sql-ahead` chip, explicit confirmed restore; palette commands
  renamed `qb-*` → `query-*`; retire the transitional embed — VisualMode is
  now the extracted chips UI.

**Acceptance (SE-4):** the Databricks screenshot's visible surface is
reproducible end-to-end minus presence/comments (descoped): multi-statement
tabs, params, viz tab, versions, schedule, share.

---

## 7. Wave SE-5a — Quick Fix (1 PR)

- `POST /query/quickfix {conn_id, sql, error}` → `{proposed_sql, rationale}`
  using the existing repair machinery (`sql/executor.py:142` fix-prompt path,
  `provider_factory`). **Never executes, never auto-applies.**
- Frontend: on run error, "Quick fix" affordance → `@codemirror/merge` diff
  (yours vs proposed) → Apply / Reject. Target latency 1–3 s.

---

## 8. Cross-cutting rules (every PR)

- Five frontend gates (`rm -rf .next/dev/types` + `tsc --noEmit`,
  `lint:vars`, `lint:tokens`, `lint:format`, `lint:elements`) + `npm run
  build`; new buttons are `<Button>`; numbers via `@/lib/format`.
- `npm run gen:api` whenever a route changes; commit the regenerated file.
- Ratchet battery on your own diff; backend gate `uvx ruff@0.15.20 check .`.
- Legacy `/query/run` output stays byte-identical (golden test from SE-0).
- Push once per branch; squash-merge; one PR at a time.
- Adversarially review the diff before calling any wave done; prove SE-1+
  live against the demo connection, not just via tests.

## 9. Sequence & sizing

```
SE-0 (PR 1)            backend contract + security      S–M   ← start here
SE-1 (PRs A,B)         workbench + editor core          M+M
SE-2 (PRs C,D,E)       diagnostics/sidebar/extraction   M+M+M
SE-3 (PRs F,G)         cancel/timeout + bulk grid       M+M
SE-4 (PRs H,I,J)       parity: params/viz/versions/sync M+M+M
SE-5a (PR 11)          Quick Fix                        S–M
```
Daily-driver quality lands at SE-2; screenshot parity (minus descoped
collaboration) at SE-4. DX-2 (resumable chat streams) remains a separate,
independent program — see the paradigm plan §3.2.
