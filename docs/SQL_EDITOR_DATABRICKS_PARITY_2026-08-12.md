# Databricks-Parity SQL Editor — Feature Build Plan (2026-08-12)

**Status:** decisions LOCKED 2026-08-12 (CM6 · antd→TanStack Table · TanStack
Query yes) — **build from `docs/SQL_EDITOR_IMPLEMENTATION_ROADMAP_2026-08-12.md`.**
**Companion to:** `docs/SQL_EDITOR_PARADIGM_PLAN_2026-08-12.md` (the strategy,
stack decisions DP-1..3, backend contract Wave SE-0). This doc is the
feature-complete build plan: every capability of Databricks' **new SQL editor**
(blog: databricks.com/blog/introducing-new-sql-editor, Oct 2024 / upd. Aug 2025,
plus a live screenshot of the editor running against our own demo catalogs),
mapped to how aughor delivers it — and where aughor can go *past* parity by
wiring in platform capabilities Databricks doesn't have.

**Reading the verdict column:** ✅ aughor has it already · 🔁 adapt an existing
platform capability · 🔨 build new · ⏸️ deferred with trigger.

---

## 1. Feature inventory (blog + screenshot, exhaustive)

**Execution & results:** Run all / run statement (split button) · last-run
status chip ("✓ 1 minute ago (18s)") · **multiple statement results** (tab per
statement) · **inline execution history** (past results + profiles without
re-running) · row count + runtime footer ("1,465 rows · 17.649s") ·
"See performance" (query profile) · "Checked for improvements" (automatic
query review) · "Refreshed 1m ago" + re-run shortcut · download menu ·
**AI-generated filters** on results (NL, chainable, no re-execution) ·
results search / filter / column controls · long-cell expanders · type icons
in column headers · visualization tabs ("Table ▾" + "+").

**Editor surface:** tabs + new-tab · line numbers, dialect highlighting ·
**split-screen editing** · **code folding** · **command palette** · custom
themes / dark mode · **Add parameter** (named query parameters) · context
pickers (catalog + default schema in toolbar) · ⌘+P global search over data
and queries.

**Catalog panel:** tree to *column* level with type icons · search + filter ·
refresh · insert-on-click · "Tables (N)" counts.

**Assistant (AI):** **Quick Fix** (1–3 s suggested error fixes, keyboard
shortcut) · execute-in-side-panel (test snippets beside the main editor) ·
assistant-generated SQL.

**Collaboration & lifecycle:** real-time co-editing · presence indicators
(green dot) · **inline comments** · share · star/favorite · schedule
(calendar) · save state (unsaved dot) · version history rail · drafts
folder · workspace-files side panel · **Git support for queries** (CI/CD).

---

## 2. Parity matrix

### 2.1 Execution & results

| Databricks feature | Aughor delivery | Verdict | Wave |
|---|---|---|---|
| Run statement / Run all | Client statement-split (dt-sql-parser `splitSQLByStatement`), run statement-under-cursor; "Run all" = sequential loop over statements (server wrap enforces one per call) | 🔨 | SE-1 |
| Last-run status chip | `duration_ms` + timestamp from the run response, per tab | 🔨 | SE-1 |
| Row count + runtime footer | `row_count`, `duration_ms`, `truncated` (SE-0 contract), through `@/lib/format` | 🔨 | SE-1 |
| Multiple statement results | One results tab per executed statement, kept per editor tab | 🔨 | SE-4 |
| Inline execution history | **The audit log already records every run** (`sql_full`, verdict, `row_count`, `duration_ms`, error, `trace_id`) + signed receipts per run. History rail per tab/connection = `GET /security/audit` filtered to the `sql_editor` label; click restores SQL + shows the past result metadata | 🔁 | SE-2 |
| "See performance" (profile) | `EXPLAIN` / `EXPLAIN ANALYZE` via the SE-3 metadata-statement allowlist (today `_validate` rejects non-SELECT roots); render DuckDB/Postgres plans in a profile drawer; receipts already give lineage + input tables | 🔁 | SE-3 |
| "Checked for improvements" | **Guard battery = this feature, no LLM needed.** `/query/validate` + `QueryResult.caveats` (guards that flag silently-wrong-but-executable SQL — currently computed and *dropped* by `/query/run`). Forward caveats in the SE-0 contract; render as the post-run "checked" chip | 🔁 **past parity** | SE-0/SE-2 |
| Download menu | CSV (SE-2) + JSON/TSV/copy-column variants | 🔨 | SE-2/4 |
| AI-generated filters on results | NL → filter chip over the in-memory result set; candidate seam: existing `POST /query/postproc` (`routers/query.py:750`) — evaluate before building new. Chainable client-side, no re-execution (matches Databricks semantics) | 🔁 | SE-4 |
| Results search/filter/columns | Grid-level: client search + per-column filter + hide/show; needs the canvas grid decision (DP-2) for the full version | 🔨 | SE-4 |
| Long-cell expanders, NULL glyphs, type icons | Typed results (SE-0) + `typeColor()` icon mapping already in `CatalogScreen.tsx:64` | 🔨 | SE-1/2 |
| Visualization tab ("+") | **Past parity, cheap:** aughor already has the ECharts builder, viz editor store, and pin-to-dashboard/canvas. "+" on a result = open chart builder on these columns; "Pin" = existing `pinQueryToDashboard` | 🔁 **past parity** | SE-4 |
| Refresh / re-run shortcut | Re-run current statement (⌘↵) + per-tab refresh of last run | 🔨 | SE-1 |

### 2.2 Editor surface

| Databricks feature | Aughor delivery | Verdict | Wave |
|---|---|---|---|
| Query tabs | Tab bar per connection; each tab = draft (versioned localStorage ring) or saved query; Workspace keep-alive layer preserves all tab state | 🔨 | SE-2 |
| Dialect highlighting, line numbers | Engine (DP-1) + per-connection dialect from SE-0 `dialect` field | 🔨 | SE-1 |
| Code folding | CM6 `foldGutter` (or Monaco built-in) — near-free | 🔨 | SE-2 |
| Split-screen editing | Two editor views over one or two docs inside `ResizableSplit` (house component); CM6 multi-view makes this cheap | 🔨 | SE-4 |
| Command palette | **Exists** — ⌘K palette + `commandRegistry` (QueryBuilder already registers `qb-run`/`qb-pin` while mounted); editor registers its commands the same way | ✅/🔁 | SE-1 |
| ⌘+P global search | Existing palette + fuse.js already searches; add editor tabs/saved queries/tables as sources | 🔁 | SE-2 |
| Custom themes / dark mode | Token-native theme (light/dark via `data-theme`) at SE-1; *user-selectable* editor themes deferred | 🔨/⏸️ | SE-1 / later |
| Add parameter | `:name` parameters: client detects + renders param chips; **backend needs a `params` field on `/query/run` with real bind values** (safer than today's string SQL — params never enter the SQL string, shrinking injection surface) | 🔨 | SE-4 |
| Context pickers (catalog + default schema) | Connection picker (exists app-wide) + default-schema selector feeding completion + unqualified-name resolution | 🔨 | SE-1 |

### 2.3 Catalog panel

| Databricks feature | Aughor delivery | Verdict | Wave |
|---|---|---|---|
| Tree to column level, type icons | `CatalogScreen` tree idioms exist to table level; extend with lazy column nodes via `/connections/{id}/tables/{t}/columns` + `typeColor()` | 🔁 | SE-2 |
| Search + filter in tree | Reuse CatalogScreen patterns + fuse.js | 🔁 | SE-2 |
| Insert-on-click / drag | New (CatalogScreen only offers "chat with table" today) — insert qualified name at cursor; drag-to-editor | 🔨 | SE-2 |
| Refresh | Existing `/schema/refresh` + cache invalidation seam (`_shared.py:38`) | ✅ | SE-2 |

### 2.4 Assistant / AI — aughor's home turf

| Databricks feature | Aughor delivery | Verdict | Wave |
|---|---|---|---|
| Quick Fix (suggested error fixes) | **Repurpose the agent's repair machinery** (`sql/executor.py:142` fix-prompt path) as an explicit endpoint: on run error, a "Quick fix" affordance requests a proposed rewrite, shown as a **diff the user applies or rejects — never auto-applied** (paradigm-plan rule: humans get errors verbatim). The machinery exists; the endpoint + diff UI are new | 🔁 | SE-5a |
| Execute in side panel | Aughor's chat panel *is* the assistant side panel, and the `openInBuilder` seam already crosses SQL between chat and builder; add editor↔chat handoffs both ways ("send to chat", "insert from answer") | 🔁 **past parity** | SE-2 |
| Assistant-generated SQL | The entire platform (ask/investigate → SQL with receipts) — Databricks parity is trivially exceeded; the editor just needs the handoff | ✅ | — |
| NL result filters | See §2.1 | 🔁 | SE-4 |

### 2.5 Collaboration & lifecycle

| Databricks feature | Aughor delivery | Verdict | Wave |
|---|---|---|---|
| Save / unsaved dot / drafts | Saved-query CRUD exists; drafts = localStorage ring surfaced as a "Drafts" group in the saved dropdown | 🔁 | SE-2 |
| Star/favorite | `is_starred` on saved queries (small migration) or a `spec` flag — trivial | 🔨 | SE-2 |
| Schedule (calendar) | **Map to monitors** — MonitorsPanel already supports **Custom SQL** metrics on a schedule; "Schedule" on an editor query = create-monitor prefilled with this SQL. Genuine parity via an existing subsystem | 🔁 **past parity** | SE-4 |
| Share | Org-scoped saved queries exist; link = `?tab=sql&conn=…&query=<id>` deep link. Per-user ACLs deferred to RBAC phase 2 | 🔁/⏸️ | SE-4 / RBAC |
| Version history | Append-only versions on saved-query update (store keeps prior `sql` rows); rail lists versions + diff view. (Full doc-level undo history = collab wave) | 🔨 | SE-4 |
| Inline comments | Anchored comments on line ranges, stored with the saved query | 🔨 | SE-5b |
| Real-time co-editing + presence | **The trigger the paradigm plan predicted:** shared mutable doc state across clients. Build on Yjs — and note **Durable Streams shipped a Yjs provider (Mar 2026)**, making DX-2's protocol alignment the transport for collab. This is where Durable Streams/Electric stop being "future" and earn adoption | ⏸️→🔨 | SE-5b |
| Git support for queries | Export/import saved queries as `.sql` files (repo-relative dir); true git-backed CI/CD flow deferred | ⏸️ | later |
| Workspace-files side panel | N/A — aughor has no user file tree; nearest analog is the catalog + saved/drafts rails, both in scope | — | — |

---

## 3. The build sequence (extends the paradigm plan's waves)

```
SE-0  contract: typed results + NULLs + truncated + dialect + CAVEATS FORWARDED
      + org guard + RBAC entry + sql_editor audit label            [backend, small]
SE-1  editor core INSIDE the unified Query workbench (paradigm plan §2.6
      Stage A): DATA_LAYERS → catalog|query|semantic, Visual|SQL mode toggle
      (visual = existing QueryBuilder embedded unchanged; `builder` legacy-
      mapped) · engine + dialect · statement-under-cursor run · schema
      completion v1 · results v1 (typed, expanders, footer) · ⌘K cmds ·
      connection + default-schema pickers · draft persistence
SE-2  pro surface + workbench extraction (§2.6 Stage B: shared results/saved/
      history/catalog shell; both modes inside it; highlighters collapse into
      SqlView): two-tier diagnostics · format · catalog sidebar w/ columns +
      insert/drag · query tabs · history rail (audit) · saved/drafts/star ·
      folding · CSV · chat↔editor handoff · caveats chip ("checked")
SE-3  execution v2: cancel (kernel job bridge + interrupt) · timeout · EXPLAIN/
      profile drawer · metadata statements · bulk rows + grid decision (DP-2)
SE-4  results & authoring parity + §2.6 Stage C (full specSync bidirectional
      flow, sql-ahead UX, openInQuery handoff): per-statement result tabs ·
      NL result filters · viz tab + pin · params (:name + backend binds) ·
      split-screen · versions · schedule→monitor · share deep-links · download
SE-5a assistant: Quick Fix endpoint + diff UI (repair machinery, never auto-apply)
SE-5b collaboration: ❌ DESCOPED by user decision 2026-08-12 — real-time
      co-editing is not needed. §6 kept as a design record only; presence +
      edit-control (stage i) remains a cheap optional add if ever wanted.
```

**Parity scoreboard (est. of the §1 inventory):** after SE-2 ≈ 55% + the
platform's own AI answering already past Databricks on generation; after SE-4
≈ 85% (everything visible in the screenshot except co-editing/comments);
after SE-5 ≈ full parity minus git-backed queries (explicitly deferred).

## 4. Where aughor lands *past* Databricks

1. **Receipts + guards as first-class UX.** Every run already produces a
   signed receipt with lineage, and the guard battery computes caveats that
   Databricks' "Checked for improvements" approximates with AI. Surfacing what
   the platform already computes is parity with negative marginal cost.
2. **The assistant isn't a side feature.** Databricks bolts an assistant onto
   an editor; aughor bolts an editor onto an agent platform. Editor↔chat
   handoffs (both directions, already half-built via `openInBuilder`) are the
   differentiator to invest in.
3. **Schedule = monitors.** Databricks schedules a query; aughor turns a query
   into a monitored metric with alerting — a strictly stronger primitive,
   already shipped.
4. **Viz tab = the chart builder.** ECharts builder + pin-to-canvas already
   exist; Databricks' viz tabs are a thin wrapper by comparison.

## 5. Honest deltas & risks

- **Real-time co-editing is the only genuinely hard feature** in the
  inventory (CRDT state, auth on doc channels, persistence). It is *last* on
  purpose, and it is exactly the feature that finally justifies the Durable
  Streams/Electric investment — do not build a bespoke websocket layer for it.
- **Parameters change the execution contract** (bind values on `/query/run`);
  guard review required (params must be bound, never interpolated).
- **Per-statement results multiply state**: results tabs × editor tabs ×
  keep-alive layers — memory-bound; cap retained result sets (e.g. last N per
  tab, LRU) from day one.
- **Profile rendering is engine-specific** (DuckDB JSON plans vs Postgres text
  vs BigQuery absent) — ship DuckDB+Postgres first, degrade gracefully.
- Everything else in the matrix is composition of things that exist.

## 6. SE-5b design sketch — collaboration (❌ DESCOPED 2026-08-12; kept as design record)

Why it's categorically different: every other feature is request/response
over single-owner state; co-editing makes the SQL buffer **shared mutable
state with concurrent writers across network delay**. Sub-features are not
equally hard, so SE-5b stages internally:

- **(i) Presence + edit control** — ephemeral per-doc heartbeat (TTL key,
  2–5 s poll) → green dot + "Alex is editing — request control". Note the
  Databricks screenshot itself shows an "Edit" gate next to the presence dot.
  Days of work, zero new infra, most of the perceived value for small teams.
- **(ii) True co-editing** — **Yjs** (de facto CRDT standard): local edits
  apply instantly, updates are commutative binary deltas (any arrival order
  converges), state vectors give late-join catch-up, cursors/selections ride
  the ephemeral *awareness* protocol (never in doc history). Editor binding:
  `y-codemirror.next` (Yjs-team-maintained, remote cursors) — `y-monaco` is
  patchier, an extra point for DP-1 = CM6.
- **(iii) Inline comments** — anchored with Yjs `RelativePosition` (survives
  concurrent edits). Line/column anchors rot; this is *why* comments are
  sequenced with the CRDT wave, not before it.

**Transport:** Yjs solves merging, not delivery. Conventional answer is a
stateful y-websocket server — exactly what aughor doesn't have (SSE
everywhere, no websockets, serverless prod). **Durable Streams is the fit:**
each doc = one addressable append-only stream; clients POST Yjs updates and
tail from their last offset (catch-up → live); the official **Yjs provider
(Mar 2026)** implements exactly this. Refresh/reconnect/multi-tab are free —
"resume from offset" is the protocol's native verb. Economic argument: DX-2
(resumable chat) alone can stay bespoke over the kernel journal; co-editing
is the **second consumer** of the same append-log primitive, and the one that
can't be faked — that's when standardizing on the protocol shape pays.

**Costs, named:** Durable Streams is Beta and self-host-only post-acquisition
(Caddy plugin / Node server, or implement PROTOCOL.md in FastAPI — the DX-2
design already points there). Alternative pattern: Yjs updates as Postgres
rows synced via Electric shapes — but every variant has the same structural
consequence: **SE-5b is where aughor pays for its first always-on component
since the Vercel-native migration.** Pay it once, share it (chat resume +
collab docs).

**Production-grade extras (not optional):** snapshot/compaction of Yjs logs ·
save flow derives `saved_queries.sql` from the CRDT doc (same dual-rep
discipline as §2.6 specSync) · **per-doc-channel org auth on subscribe AND
append** — day one, given the `/query/run` cross-tenant lesson.

**Sizing:** stage (i) days · stages (ii)+(iii) weeks — the largest single
feature in the program and the only one requiring new infrastructure.
