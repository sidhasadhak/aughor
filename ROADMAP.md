# Aughor — Product Roadmap

**Product:** Aughor — Autonomous Analyst  
**Repo:** https://github.com/sidhasadhak/aughor  
**Stack snapshot:** LangGraph · Ollama (qwen2.5-coder:14b + nomic-embed-text) · FastAPI SSE · Next.js (App Router) · DuckDB + PostgreSQL · SQLGlot · scipy/statsmodels · Qdrant · uv

---

## ✅ Shipped

| Feature | Key files | Notes |
|---|---|---|
| LangGraph investigative loop | `hermes/agent/graph.py`, `nodes.py` | decompose → plan_and_execute → score_evidence → synthesize |
| DuckDB + Postgres connections | `hermes/db/connection.py`, `registry.py` | Fernet-encrypted SQLite credential store |
| SQL self-correction | `hermes/agent/nodes.py`, `prompts.py` | FIX_SQL_PROMPT → retry; pitfalls injected into all subsequent plans |
| Statistical engine | `hermes/tools/stats.py` | STL decomposition, z-score anomaly, Mann-Whitney; auto-attached to every QueryResult |
| FastAPI SSE streaming | `hermes/api.py` | node-level events; frontend consumes with `useInvestigation` reducer |
| Next.js frontend | `web/` | Hypothesis cards, report view, connection manager, history |
| Investigation history + citation pinning | `hermes/db/history.py`, `web/components/HistoryPanel.tsx`, `ReportView.tsx` | SQLite history store; Finding.hypothesis_id links claims → SQL; expandable footnotes in report |
| Semantic Layer 1a — Business Glossary | `hermes/semantic/glossary.py`, `data/glossary.yaml` | YAML glossary injected into every schema context; table descriptions, grain, column definitions, known values, caveats, join hints; `GET/PUT /glossary` API |
| Semantic Layer 1a+ — Auto-Seed Glossary | `hermes/semantic/autoseed.py` | LLM auto-infers descriptions for unannotated tables on first `get_schema()` call; written back with `auto_generated: true`; idempotent (YAML cache); disable via `HERMES_AUTOSEED=false` |
| Direct Query Mode (2e) | `hermes/agent/nodes.py`, `graph.py`, `web/` | `route_question` entry node classifies direct vs investigate; direct skips decompose; Observable Plot chart + KPI cards in report |
| SQL Knowledge Base (2f) | `hermes/semantic/kb_loader.py`, `kb_retriever.py` | 235 SQL patterns and domain knowledge JSONs embedded in Qdrant; injected into PLAN_QUERIES, FIX_SQL, and DECOMPOSE prompts; two tiers: SQL correctness patterns (dialect traps + mistake examples) and domain business knowledge (metrics, causal relationships, diagnostic questions) |
| Thinking Trace (8a) | `web/components/ThinkingTrace.tsx` | Visual progress stepper derived from state; pending/running/done dots; hypothesis verdict colours live |
| KPI Highlight (8b) | `web/components/ReportView.tsx` | Auto-formats single-row scalar results as metric cards; no Tremor dep needed |
| Observable Plot Charts (8c) | `web/components/InvestigationChart.tsx` | Auto-detects timeseries or bar chart from column names + values; @observablehq/plot |
| Routing Classifier v2 (2g) | `hermes/agent/prompts.py`, `nodes.py`, `state.py` | Intent-based routing (retrieval vs diagnosis); confidence scoring; < 0.65 → investigate fallback; reasoning + confidence % surfaced in ThinkingTrace; direct mode bypasses semantic cache and skips Qdrant indexing |
| SQL Knowledge Base (2f) | `hermes/semantic/kb_loader.py`, `kb_retriever.py` | 235 SQL patterns and domain knowledge JSONs embedded in Qdrant; Tier 1: dialect traps + good/bad SQL examples; Tier 2: domain business knowledge (metrics, causal chains, diagnostic questions); injected into PLAN_QUERIES, FIX_SQL, and DECOMPOSE prompts via retrieve_for_* functions |
| Direct Query Graceful Failure | `hermes/agent/nodes.py`, `hermes/api.py` | synthesize_report early-exits without an LLM call when all queries fail in direct mode; returns factual AnalysisReport with SQL errors as DataQualityNotes; dedicated frontend error state (red headline, Execution Error label) |
| Chart Intelligence (8d) | `web/components/InvestigationChart.tsx` | DATE_PATTERN restricted to genuine date columns only (no false-positives on order_year/order_month); SHARE_PATTERN prefers share/pct/percent/rate/ratio columns as value axis; per-category averaging for share columns (not sum); percentage tick formatter for 0-1 range columns |
| Report UX (8e) | `web/components/ReportView.tsx` | Section reorder: Headline → Executive Summary → Chart → KPI → Query Results → collapsibles; CollapsibleSection component wraps DQ Issues / Risks / Recommended Actions / Excluded Causes (all collapsed by default); smart formatCell: share 0-1 → XX.XX%, ordinal integers (year/month/id) → no locale comma, long decimals → 2 dp |
| Metrics Catalog (1e) | `hermes/semantic/metrics.py`, `data/metrics.json`, `hermes/api.py`, `web/components/MetricsPanel.tsx` | Named business KPI formulas stored in JSON; injected as METRICS CATALOG block into every schema context; full CRUD API; two-column UI in Connections tab (list + form); comma-separated array inputs |
| Error Classification & SQL Hardening (2h) | `hermes/tools/error_classifier.py`, `hermes/db/connection.py`, `hermes/agent/nodes.py`, `hermes/tools/ambiguity.py` | 2h-i: 30+ error patterns → targeted diagnostic hints prepended to FIX_SQL_PROMPT as DIAGNOSIS block; 2h-ii: Postgres dialect post-processing (ROUND::numeric, NULLIF timestamp, interval→epoch) before query hits wire; 2h-iii: column ambiguity pre-flight scans SQL for unqualified multi-table refs |
| Schema Intelligence (2i) | `hermes/tools/schema.py`, `hermes/db/schema_cache.py` | 2i-i: Fuzzy join inference via root-normalised column names (8 suffix variants); exact/inferred tiers; NO DIRECT JOIN warnings; join hints appended to schema context and Mermaid diagram; 2i-ii: MD5 schema fingerprinting with 50-entry LRU JSON cache — zero LLM calls on unchanged reconnect |
| KB Pattern Enrichment (2j) | `hermes/semantic/kb_loader.py`, `hermes/semantic/kb_retriever.py`, `data/kb/` | 252 entries indexed (47 Tier 1 SQL patterns, 84 Tier 2 domain knowledge, 121 stubs); talonsight KB (43 files) merged with 15 custom files; two causal_relationship shapes ({symptom, check_in_order, detection_sql} native + {if, then} talonsight); inflation_causes, deflation_causes, cross_metric_signals surfaces in DECOMPOSE and PLAN prompts |
| ER Diagram (Mermaid) | `hermes/tools/schema.py`, `web/components/SchemaPanel.tsx`, `hermes/api.py` | `build_mermaid_er()` generates erDiagram source from schema string; solid lines (exact FK match), dashed lines (fuzzy root match); FK column markers; lazy-loaded via dynamic import; Schema \| ER Diagram sub-tabs in Connections panel |
| Rich Schema Card UI | `hermes/tools/schema.py`, `hermes/api.py`, `web/components/SchemaCards.tsx`, `web/components/SchemaPanel.tsx`, `web/lib/api.ts` | `/schema/rich` endpoint returns structured tables + joins + warnings; gradient table cards with 8-colour cycling palette; column type chips (blue=numeric, green=text, amber=date, violet=bool); FK badges; row counts; join paths grid with exact/inferred badges; SQL Warnings & Modeling Notes section with empty state |
| Quick Chat Mode (M9) | `hermes/api.py`, `hermes/agent/prompts.py`, `web/lib/useChat.ts`, `web/components/ChatPanel.tsx`, `web/components/ChatMessage.tsx`, `web/app/page.tsx` | `POST /chat` SSE endpoint; last-3-turn conversation history injected as context; coder LLM generates SQL + headline + chart_type; one self-correction attempt on error; streams sql → columns → rows → headline → chart_type → done; Chat tab with starter prompts, KPI/chart/table answer bubbles, ✕ to clear |
| Chat Chart Engine (M9-charts) | `hermes/api.py`, `hermes/agent/prompts.py`, `web/components/ChatMessage.tsx`, `web/lib/useChat.ts` | Multi-type inline charts in Chat answer bubbles: bar (vertical default), bar_horizontal, line/area, stacked_bar, pie/donut (d3-shape); chart_type selected by LLM via CHAT_SQL_SYSTEM prompt rules; categories on X axis, measures on Y axis by default; bar_horizontal only on "pivot"/"flip"/"horizontal"/"rotate"; fmtTimestampLabel for ISO→"Mon YYYY" conversion; buildHtmlLegend with 2-col layout >12 items; T10 Tableau-10 palette; resizable charts via drag handle (CSS-only during drag, single re-render on mouseup); all data caps removed (10 000-row backend cap only); deduplication via cancelled-flag pattern |
| Deep Analysis tab + Chat default | `web/app/page.tsx` | Chat is now the default landing tab; Investigate and History tabs merged into a single "Deep Analysis" tab — HistoryPanel on the left, investigation input + thinking trace on the right; investigation history always visible alongside active work |
| Global Analytics Rules (32) | `hermes/rules.py`, `data/global_rules.md` | 102 rules across 14 sections (operating posture → privacy); re-read on every call; `get_rules_block()` (all 14) injected into decompose/plan/synthesize nodes; `get_chat_rules_block()` (§0+§7+§8 only) injected into `/chat` — keeps overhead proportional |
| Hypothesis Expanded Accordion (33) | `web/components/ReportView.tsx`, `web/lib/types.ts`, `hermes/api.py` | Per-hypothesis accordion: chart + compact table (15 rows) + stat callouts + SQL toggle + key finding; `QueryEvidence`, `QueryMiniTable`, `StatCallout`, `KeyFindingCard`, `HypothesisAccordion`, `HypothesisPanel` components; H-palette 5-colour cycling; report order: Verdict → Diagnosis → Key Findings → Hypotheses Tested → collapsibles; `stats` field added to both `report` SSE events; `line-clamp-2` removed from hypothesis descriptions |
| Connection-scoped semantic cache | `hermes/tools/prior_analyses.py`, `hermes/semantic/vector_store.py`, `hermes/agent/state.py`, `hermes/db/history.py`, `hermes/api.py` | `connection_id` stored in Qdrant payload; `find_similar_investigation()` and `search_prior_investigations()` filter via Qdrant `FieldCondition`; `connection_id` added to `AgentState`; forwarded through `complete_investigation()`; same question on a different DB always starts fresh; `/investigations/reindex` backfills existing entries |
| Paren-aware ROUND rewriter | `hermes/db/connection.py` | Replaced three narrow regexes with a character-walking rewriter that tracks paren depth to find the top-level comma in any ROUND(expr, N) — handles arbitrary nesting like `ROUND(100.0 * SUM(a) / NULLIF(SUM(b), 0), 2)`; unconditionally casts first arg to `::numeric` (PostgreSQL has no `ROUND(double precision, integer)` overload) |
| Schema parser dedup | `hermes/tools/schema.py` | `build_rich_schema()` skips re-registering a table already seen — prevents duplicate column entries (and React key collisions in `SchemaCards.tsx`) when glossary/hints re-emit `TABLE:` headers |
| Investigation timeout 600 s | `hermes/api.py` | `HERMES_TIMEOUT_SECONDS` default raised from 300 → 600 |
| History panel scroll fix | `web/components/HistoryDetailPanel.tsx`, `web/app/page.tsx` | `ScrollArea` replaced with `div className="flex-1 overflow-y-auto min-h-0"` throughout; `h-screen overflow-hidden` on root; history panel no longer drives page height |
| UI color pass | `web/components/HistoryPanel.tsx`, `web/components/ThinkingTrace.tsx` | Violet/blue/emerald/amber palette applied; selected item `border-violet-500 bg-violet-500/5`; indexed dot `text-emerald-400`; status chips; ThinkingTrace header `text-violet-400/60 font-mono`, connector `bg-violet-500/20`, running step `bg-amber-500/10` |
| Investigation Quality Hardening (34) | `hermes/agent/nodes.py`, `hermes/agent/prompts.py`, `hermes/agent/verify.py`, `hermes/agent/state.py`, `web/lib/formatCell.ts`, `web/components/ReportView.tsx`, `data/global_rules.md` | Six fixes: (1) evidence-scoped confidence defaults (0.0 no-queries, 0.1 all-errored); (2) post-LLM ceiling caps (1 query→0.60, 2→0.80, 3+→uncapped); (3) pre-synthesis consistency check via coder LLM with confidence downgrade on contradictions; (4) numeric traceability verifier appending unverifiable numbers as DataQualityNotes; (5) threshold drill-down rule in PLAN_QUERIES_PROMPT + global_rules.md §9; (6) column-typed share formatter (buildColumnFormatter scans all column values once, eliminates "21.00% for count=11" defect) |
| Databricks-brand UI (35) | `web/app/globals.css`, `web/app/layout.tsx`, `web/components/*.tsx` | Full palette rewrite: `#1F272E` left panel, `#11171D` canvas, `#EBEFF2` main text, `#8A9BA6` sub-text, `#3B8DBF` accent (replaces purple); Tailwind v4 `:root {}` override (unlayered, always wins); bulk sed pass replacing `text-zinc-600/700` with `text-zinc-500` across all TSX |
| Genie-style Chat UI (36) | `web/components/ChatPanel.tsx` | Empty state centered on page with textarea first; arrow (↑) button embedded inside textarea; Ask/Investigate mode toggle below textarea; plain left-aligned suggestion sentences with ASK/INVESTIGATE badges; "Always review the accuracy of responses." disclaimer; active-chat bottom bar uses arrow button instead of separate Send |
| History popup (37) | `web/app/page.tsx`, `web/components/HistoryPanel.tsx` | History panel removed from persistent left sidebar; floating popup (fixed top-12 right-4, 72vh, click-outside-to-close) triggered by History clock icon in topbar; available across all tabs; selecting a history item navigates to Investigate tab |
| Home page (38) | `web/app/page.tsx` | Databricks-style welcome screen: "Welcome to Aughor" header; active connection card; 3 quick-start cards (Chat, Deep Analysis, Catalog); "Try asking" starter questions; Recent investigations with status badges and relative timestamps; default landing tab |
| Catalog tab (39) | `web/components/CatalogPanel.tsx`, `web/app/page.tsx` | Browse all tables from the connected database; expand/collapse per table to see columns, types, FK flags; row count formatted (1M/500K); connection picker inside panel; filter by table name; "Ask →" button per table jumps to Chat with that connection; nav restructured: Home → Workspace (Chat, Deep Analysis) → Data (Catalog, Connections) |
| Schema-aware suggestions (40) | `hermes/api.py`, `web/components/ChatPanel.tsx` | `GET /suggestions?connection_id=X` fetches schema, calls LLM for 6 schema-specific starter questions tagged ask/investigate; loading shimmer while fetching; falls back to hardcoded starters on error; clears and re-fetches on connection change |
| Suggestions cache in Qdrant (41) | `hermes/semantic/suggestions_cache.py`, `hermes/api.py` | Each suggestion embedded (nomic-embed-text) and stored as a Qdrant point in `schema_suggestions` collection; cache key = (connection_id, structural schema fingerprint); cache hit returns in ~3s vs ~90s LLM generation; `search_similar()` ready for future autocomplete; fingerprint derived from sorted table+column names only (strips row counts/descriptions for stability); graceful fallback if Qdrant unavailable |
| Background Schema Explorer (42) | `aughor/explorer/agent.py`, `store.py`, `episodes.py`, `models.py` | `SchemaExplorer` — 8-phase autonomous background agent; phases 3–7 (structural) run at full DB speed; phase 8 (domain intel) throttles to 1 query / 5 s; persists state to JSON + JSONL; stop/resume/restart; only auto-resumes connections with prior state on server startup |
| Business Ontology auto-build (43) | `aughor/ontology/builder.py`, `enricher.py`, `models.py`, `store.py` | Structural extraction → LLM enrichment → `OntologyGraph` with entities, relationships, metrics, lifecycle states, computed properties, and SQL actions; fingerprint-keyed cache; `OntologyCanvas` interactive graph UI |
| Domain Intelligence Loop (44) | `aughor/explorer/agent.py` `_phase8_*`, `aughor/explorer/store.py` | Adaptive curiosity loop per domain; coverage angles (volume/value/retention/…); novelty decay stopping; open-ended continuation after angles covered; per-domain budget control; live in-memory cap patch on extend; DomainIntelPanel UI with "+5 queries" |
| SqlWriter — centralised SQL (45) | `aughor/sql/writer.py`, `aughor/agent/prompts.py` | Single class for all SQL generation and self-correction; alias resolution; DuckDB candidate bindings extraction; targeted DIAGNOSIS block; "NEVER substitute SUM(0)"; used by chat pipeline, domain intel, and retry endpoint |
| Activity Log UI (46) | `web/components/ActivityLog.tsx`, `aughor/api.py` | Real-time episode feed; stop/resume/restart surviving tab switches; `status.paused` synced from backend on every fetch |
| Exploration State Persistence (47) | `aughor/explorer/store.py`, `episodes.py`, `aughor/api.py` | Per-connection `exploration_{id}.json` + `episodes_{id}.jsonl`; explorer resumes from last position after restart; restart clears both files |
| Per-Phase Rate Limiting (48) | `aughor/explorer/agent.py` | `_RATE_SECONDS_SCHEMA = 0.0`, `_RATE_SECONDS_INTEL = 5.0`; `_gate()` skips sleep for schema phases; `self._rate_seconds` set by `explore()` per phase group |
| Plan-then-SQL Separation (49) | `aughor/agent/nodes.py`, `state.py`, `prompts.py`, `graph.py` | `plan_queries` (pure LLM planning → `QueryPlanV2` with typed `QueryIntent` objects in plain English) + `execute_planned_queries` (SQL generation per intent via `WRITE_SQL_PROMPT`/`SQLOutput` + execution); ontology actions + SQL examples injected only at write stage; `plan_and_execute` kept as backward-compat shim |
| Non-blocking FastAPI event loop (50) | `aughor/api.py` | `_aiter_sync` async generator wraps sync LangGraph `agent.stream()` via `loop.run_in_executor(None, next, it)` — yields control between every node; prevents all other API calls from hanging during active investigations |
| Loading state hardening (51) | `web/components/ActivityLog.tsx`, `DomainIntelPanel.tsx`, `HistoryPanel.tsx`, `ConfigurePanel.tsx` | `useState(false)` init (was `true`) + `AbortController` 8s timeout + silent error handling across all data-panel components; UI always renders immediately and populates when data arrives |
| Home stat card navigation (52) | `web/app/page.tsx` | "Tables in Schema" → Schema tab; "Entities Mapped" → Ontology tab; "Insights discovered" → Intelligence sub-section of Exploration (+ real count from `getDomainInsights`); "Queries executed" → Activity tab; `StatCard` gained `onClick`, hover animation, pointer cursor |
| Schema cache — backend + frontend (53) | `aughor/api.py`, `web/lib/schema-context.tsx`, `SchemaPanel.tsx`, `CatalogPanel.tsx`, `ConfigurePanel.tsx` | Backend: 5-min TTL in-process cache per connection (`_get_schema_cached`) eliminates repeated COUNT(*) + profiling + ontology rebuild on every `/schema` HTTP request; invalidated on delete/rebuild. Frontend: `SchemaProvider` React Context wraps right panel; one fetch per connection switch; `SchemaPanel`, `CatalogPanel`, `DataTab` all consume from context |
| Metric Targets & Health Scorecard (54) | `aughor/ontology/models.py`, `aughor/semantic/metrics.py`, `aughor/agent/prompts_investigate.py`, `aughor/api.py`, `web/components/ProcessHealthPanel.tsx`, `web/components/MetricsPanel.tsx`, `web/lib/api.ts` | `OntologyMetric` + `MetricDefinition` gain `target_value`, `warning_threshold`, `critical_threshold`, `target_period`, `benchmark_source`; `GET /connections/{conn_id}/health-scorecard` executes each metric's SQL and returns green/yellow/red status + variance; `ProcessHealthPanel` renders health grid on home page with "Investigate →" per off-target metric; ADA synthesis receives `{metric_targets_section}` to prioritise controllable root causes above threshold; MetricsPanel form extended with Health Scorecard section |
| Structured Playbook from KB (55) | `aughor/playbook/models.py`, `store.py`, `builder.py`, `retriever.py`, `aughor/agent/investigate.py`, `aughor/agent/prompts_investigate.py`, `aughor/api.py`, `web/components/PlaybookPanel.tsx` | `seed_from_kb()` converts 272 draft `PlaybookEntry` objects from 84 Tier-2 KB causal entries on startup; `retrieve_for_metric_and_phases()` matches investigation context to playbook entries by metric name + tag scoring; `{playbook_section}` injected into `ADA_SYNTHESIZE_PROMPT`; LLM prefers retrieved entries and flags unmatched ones "[unproven]"; full CRUD + seed API; `PlaybookPanel` in Data → Playbook tab with browse/filter/promote/deprecate |
| Outcome Tracking & Feedback Loop (56) | `aughor/playbook/outcomes.py`, `aughor/api.py`, `web/components/ReportView.tsx`, `web/components/RecommendationInbox.tsx` | `RecOutcome` model; per-recommendation "Mark" dropdown (accepted/implemented/verified/rejected/dismissed) in ReportView; `POST /investigations/{inv_id}/recommendations/{rec_index}/outcome` + `GET` outcomes endpoints; `update_playbook_success_rates()` recomputes `historical_success_rate` and auto-promotes drafts with ≥2 outcomes + ≥50% success; `RecommendationInbox` shows cross-investigation pending actions in Data → Inbox tab |
| Document Ingestion — Context Layer (57) | `aughor/knowledge/documents.py`, `aughor/knowledge/indexer.py`, `aughor/agent/investigate.py`, `aughor/agent/prompts_investigate.py`, `aughor/api.py`, `web/components/DocumentUploader.tsx` | Paragraph-aware chunker for PDF/Word/Markdown/TXT; `aughor_documents` Qdrant collection; `{external_context_section}` injected into ADA synthesis; drag-and-drop uploader in Data → Documents tab; optional `[docs]` dep group |
| Business Process Visual Mapper (58) | `aughor/process/models.py`, `aughor/process/mapper.py`, `aughor/api.py`, `web/components/ProcessMapper.tsx`, `web/components/OntologyPanel.tsx` | LAG() SQL transition volumes per `(from_state, to_state)` pair; node counts via GROUP BY; custom SVG swimlane with conversion-rate health colours; SVG-native tooltip; "Investigate →" per node; "Map" tab in entity detail drawer for lifecycle entities |
| Causal Graph — Outcome-Gated (59) | `aughor/process/causal.py`, `aughor/agent/investigate.py`, `aughor/agent/prompts_investigate.py`, `aughor/playbook/outcomes.py`, `aughor/playbook/retriever.py`, `aughor/api.py`, `web/components/OntologyCanvas.tsx`, `web/lib/api.ts` | ADA extracts structured `CausalLinkModel` pairs at synthesis time; saved as proposals keyed by `inv_id`; promoted to `ConfirmedCausalEdge` only when a recommendation is marked verified/implemented; weight +1 per confirmation, -1 per rejection (pruned at 0); backward traversal injects confirmed causal context into future investigations; orange dashed arrows on OntologyCanvas with ×N weight badge |
| Streaming completion fix | `web/lib/useChat.ts` | `ADA_REPORT` and `EXPLORE_REPORT` reducer cases now set `streaming: false` immediately — UI no longer shows "running" while server generates follow-ups and persists investigation |
| Consistent panel background | `web/app/page.tsx`, `web/components/ChatPanel.tsx` | All right panels standardised to `#0d0e11`; main content wrapper sets it as base; ChatPanel root + input bar updated to match |

---

## Milestone 1 — Semantic Data Layer
**Goal:** Give the agent business context about what columns and tables actually mean, so it writes accurate SQL without guessing. The agent's schema understanding must be richer than any individual analyst's — not just `orders.created_at` but *"this is the Stripe timestamp, not the fulfillment timestamp; use `fulfilled_at` for revenue recognition."* That institutional knowledge is the most defensible moat.

### Phase 1a — Business Glossary (ship first, lightweight)
**What:** A YAML file where you annotate tables and columns with plain-English descriptions, grain, known caveats, and example values. Injected into every `build_schema_context()` call alongside raw DDL.

**Why first:** Zero new infrastructure. Immediate improvement to query quality on every run.

**Files to create/modify:**
- `hermes/semantic/glossary.py` — load/parse YAML; merge annotations into schema context
- `hermes/tools/schema.py` — extend `build_schema_context()` to call `apply_glossary()`
- `data/glossary.yaml` — the annotation file (user-editable)
- `hermes/api.py` — `GET /glossary`, `PUT /glossary/{table}/{column}` for UI editing

**New deps:** none

**Glossary YAML shape:**
```yaml
tables:
  orders:
    description: "One row per customer order. Grain: order_id."
    columns:
      order_status:
        description: "Lifecycle stage. Values: created, approved, invoiced, processing, shipped, delivered, unavailable, canceled"
        caveats: "~3% of rows have NULL status due to legacy import"
      freight_value:
        description: "Shipping cost in BRL charged to customer. Does NOT include seller fees."
```

---

### Phase 1a+ — Auto-Seed Glossary via LLM
**What:** When a connection is first used and a table has no glossary entry, run a one-shot LLM call to infer business descriptions from the column names + a sample of distinct values. Write the result back to `glossary.yaml` marked `auto_generated: true`. User-provided entries always take precedence — this is a fallback, not a replacement.

**Why:** Eliminates the cold-start problem for new databases. The Olist Postgres DB (or any newly connected warehouse) gets instant glossary coverage without manual effort.

**Seeding trigger:** On `DatabaseConnection.get_schema()`, after `apply_glossary()`, check which tables have no glossary entry. Fire the LLM seed job for those tables only — once per table, idempotent.

**LLM prompt shape:**
```
Given this table schema and sample values, infer:
- A one-sentence description of what this table contains
- The grain (what one row represents)
- For each column: a short business definition and known values if categorical

TABLE: orders (99,441 rows)
  order_id  VARCHAR  [sample: abc123, def456]
  order_status  VARCHAR  [sample: delivered, shipped, canceled, processing]
  ...
```

**Output:** structured `GlossaryTableEntry` Pydantic model → serialized to YAML with `auto_generated: true` flag.

**Files to create/modify:**
- `hermes/semantic/autoseed.py` — `seed_missing_tables(schema_str, conn_id) → dict`; calls LLM, writes to glossary
- `hermes/db/connection.py` — call `autoseed.seed_missing_tables()` on first `get_schema()` if any tables are unannotated
- `data/glossary.yaml` — auto-generated entries marked clearly so users know they can override

**New deps:** none (uses existing LLM provider)

**Note:** Auto-generated entries should be visually distinct in the UI glossary editor (greyed out with an "AI-inferred" badge) so users know to validate them.

---

### Phase 1b — dbt Integration ✅
**What:** Use dbt as the authoritative source of truth for metric definitions and business logic. The dbt JSON schema output (`dbt docs generate`) becomes the primary input for the schema registry — so the agent uses the same `MRR` definition that's already audited and correct, rather than re-deriving it.

**Why:** Solves the "three different numbers from three people" problem at the source. Any business logic encoded in dbt models is automatically available to the agent. Also provides a structured, machine-readable format for the vector search index in 1c.

**Shipped:**
- `hermes/semantic/dbt.py` — parses `manifest.json` (models + sources) and optionally `catalog.json`; extracts descriptions and column annotations; ephemeral models skipped; sources don't override models
- `hermes/semantic/glossary.py` — `load_merged_glossary()` implements three-layer precedence: manual YAML > dbt > auto-seed; `_deep_merge()` ensures recursive override semantics
- Three-layer merge verified: dbt overrides auto-seeded entries, manual YAML overrides dbt
- Opt-in via `HERMES_DBT_MANIFEST` env var — entire dbt layer is silently skipped if unset; no new required dependencies
- Optional `HERMES_DBT_CATALOG` for additional column type/comment enrichment

**New deps:** none (dbt manifest is plain JSON)

**Dependency on:** Phase 1a + 1a+ (all three layers must be in place)

---

### Phase 1c — Vector Search over Schema ✅
**What:** Embed table/column descriptions into Qdrant. At query-planning time, retrieve the top-k most relevant tables for the current hypothesis instead of dumping the full schema — avoids blowing the context window on large warehouses.

**Shipped:**
- `hermes/semantic/vector_store.py` — thin Qdrant wrapper: `ensure_collection`, `upsert`, `search`, `collection_count`
- `hermes/semantic/embedder.py` — batched embeddings via Ollama `/v1/embeddings` (OpenAI-compat); model `nomic-embed-text`
- `hermes/semantic/retriever.py` — `build_schema_index()` embeds all glossary table+column entries; `retrieve_relevant_schema(hypothesis, full_schema)` returns filtered schema with only relevant tables
- `hermes/tools/schema.py` — calls `build_schema_index()` after every schema load to keep index fresh
- `hermes/agent/nodes.py` — `plan_and_execute` calls `retrieve_relevant_schema()` per hypothesis; full schema passed when ≤ 12 tables
- `docker-compose.yml` — Qdrant service, port 6333, persistent volume
- Threshold-based: retrieval only activates for schemas with > 12 tables; silently falls back to full schema on any failure

**New deps:** `qdrant-client>=1.9.0`  
**Ollama model needed:** `ollama pull nomic-embed-text`  
**Start Qdrant:** `docker compose up -d qdrant`

**Dependency on:** Phase 1a + 1b (needs populated glossary to embed)

---

### Phase 1d — Prior Investigations as Context ✅
**What:** Completed investigations are embedded and indexed in Qdrant. When a new investigation starts, semantically similar past investigations are retrieved and injected into every query-planning prompt — so the agent avoids re-running identical analyses and builds on prior conclusions.

**Shipped:**
- `hermes/tools/prior_analyses.py` — `index_investigation()` (called on completion), `search_prior_investigations()` (called at decompose time); min score threshold 0.65 to avoid noise
- `hermes/db/history.py` — `complete_investigation()` now accepts `question` param and auto-indexes via `index_investigation()`
- `hermes/agent/state.py` — `prior_analyses: list[str]` field added to `AgentState`
- `hermes/agent/nodes.py` — `decompose_question` fetches and stores prior analyses; `plan_and_execute` injects them into prompt
- `hermes/agent/prompts.py` — `PLAN_QUERIES_PROMPT` gains `{prior_analyses_section}` block; agent instructed to skip redundant queries when past investigation already answered the hypothesis
- Disable via: `HERMES_PRIOR_ANALYSES=false`

**Dependency on:** Phase 1c (shared Qdrant instance), Investigation History ✅

---

### Phase 1e — Metrics Catalog ✅
**What:** Named business KPI formulas stored persistently and injected into every schema context — so the LLM uses the *same approved SQL* for MRR, CAC, and LTV that the data team has already validated, rather than re-deriving them from scratch every time.

**Why:** Even with a rich glossary, the agent re-derives metric logic on every run. "MRR" might be computed differently across three investigations, creating inconsistent numbers. The Metrics Catalog is the formula layer above the glossary: tables/columns describe what data exists; metrics describe what to compute from it.

**How this differs from the Business Glossary:**
- Glossary = what things ARE (table/column semantics, grain, caveats)
- Metrics Catalog = what to COMPUTE (KPI formulas, approved SQL, result dimensions)
- Both inject into schema context but in separate blocks

**Integration note (no clash):** If a metric overlaps with a glossary column annotation, the Metrics Catalog takes precedence for formula definitions. Glossary handles column-level semantics; Metrics handles aggregate computation.

**Files to create/modify:**
- `hermes/semantic/metrics.py` — `MetricDefinition` Pydantic model (`name`, `sql`, `dimensions: list[str]`, `filters: list[str]`, `tables: list[str]`, `caveats: str`); `load_metrics()`, `save_metric()`, `list_metrics()`, `delete_metric()`
- `data/metrics.json` — persistent metric definitions (JSON array, append-only)
- `hermes/tools/schema.py` — `build_schema_context()` appends a `METRICS CATALOG` block: "Use these exact SQL expressions: MRR = SUM(amount) WHERE status='active'"
- `hermes/api.py` — `GET /metrics`, `POST /metrics`, `PUT /metrics/{name}`, `DELETE /metrics/{name}`
- `web/components/MetricsPanel.tsx` — browse saved metrics, one-click re-run, edit/delete; accessible from the connection sidebar

**Metric JSON shape:**
```json
{
  "name": "revenue",
  "sql": "SUM(order_amount) - SUM(COALESCE(refund_amount, 0))",
  "dimensions": ["order_date", "country", "category"],
  "tables": ["orders", "refunds"],
  "caveats": "Finance-approved. Excludes test_user_id IS NOT NULL rows."
}
```

**New deps:** none

**Dependency on:** Phase 1a (glossary defines table/column semantics that metrics reference)

---

## Milestone 2 — Agent Infrastructure Hardening
**Goal:** Make the investigative loop production-grade — resumable, human-validated, and capable of routing to the right model for each job.

### Phase 2a — Two-Model Architecture ✅
**What:** Separate the SQL-generation and narrative-synthesis jobs into different models. The coder model is optimized for structured reasoning and SQL; the narrative model is optimized for prose.

**Shipped:**
- `hermes/llm/provider.py` — `get_provider(role: Literal["coder", "narrator"])` returns a role-specific `LLMProvider`; per-role client cache so each role's client is built once per process; `HERMES_MODEL` as universal fallback
- `hermes/agent/nodes.py` — `decompose_question`, `plan_and_execute`, `score_evidence` use `role="coder"`; `synthesize_report` uses `role="narrator"`; SQL self-correction fix also uses coder
- Anthropic backend unaffected — uses one model for both roles (Claude handles both well)

**New deps:** none

**Env vars:**
```
HERMES_CODER_MODEL=qwen2.5-coder:32b    # default
HERMES_NARRATOR_MODEL=llama3.3:70b      # default
HERMES_MODEL=<model>                     # fallback for both if role-specific var unset
```

---

### Phase 2b — Resumable Investigations ✅
**What:** LangGraph checkpointing + hard guardrails so investigations are bounded and survivable.

**Shipped:**
- `hermes/agent/graph.py` — `SqliteSaver` checkpointer at `data/checkpoints.db`; each investigation gets an isolated `thread_id` so state is checkpointed after every node
- `hermes/api.py` — wall-clock timeout (`HERMES_TIMEOUT_SECONDS`, default 300s) checked between every node; client disconnect detection via `request.is_disconnected()`; on timeout → `fail_investigation(status="timed_out")`; on unhandled exception → `fail_investigation(status="failed")`
- `hermes/db/history.py` — `status` column (`running` / `complete` / `timed_out` / `failed`) with safe SQLite migration; new `fail_investigation()` function that explicitly does NOT index in Qdrant; `complete_investigation()` is the only path that indexes
- Frontend — `InvestigationSummary.status` type; HistoryPanel shows `⏱ timed out`, `✕ failed`, `● running` badges

**Guarantees:**
- Every investigation ends in ≤ `HERMES_TIMEOUT_SECONDS` regardless of model speed
- Partial / timed-out investigations are never indexed — only `complete` ones reach Qdrant
- Orphaned server work is killed on client disconnect

**New deps:** `langgraph-checkpoint-sqlite>=3.0.0`

---

### Phase 2c — Human-in-the-Loop Interrupt ✅
**What:** An optional interrupt before `synthesize_report`. The agent pauses, streams its current hypothesis verdicts to the frontend, and waits for the user to approve, add context, or redirect before generating the final report.

**Why:** High-stakes investigations (revenue root cause, compliance) benefit from a human confirming the agent's interpretation of evidence before it commits to a narrative verdict. Also a trust-building feature for early users.

**Files to create/modify:**
- `hermes/agent/graph.py` — add `interrupt_before=["synthesize"]` to `graph.compile()` when HITL mode is enabled
- `hermes/agent/nodes.py` — new `await_feedback` node: streams current state, accepts `human_feedback: str` to inject into synthesis prompt
- `hermes/agent/state.py` — add `human_feedback: Optional[str]` and `hitl_enabled: bool` to `AgentState`
- `hermes/api.py` — new `POST /investigations/{inv_id}/feedback` endpoint to resume a paused graph
- `web/components/FeedbackPrompt.tsx` — UI card that appears when investigation is paused awaiting input

**Dependency on:** Phase 2b (checkpointing required to pause and resume graph state)

---

### Phase 2e — Direct Query Mode
**What:** Skip the hypothesis decomposition step when the question is analytical rather than causal. If the question starts with "what is / show me / how many / calculate / list", route straight to `plan_and_execute` instead of `decompose → plan_and_execute`. The full investigative loop is overkill for direct questions and produces confusing "hypothesis" framing for what is essentially a single SQL answer.

**How to detect:** Add a lightweight classifier in `decompose_question` — either a regex on question prefix or a one-shot LLM call that returns `{"mode": "direct" | "investigate"}`. Direct mode sets a single synthetic hypothesis ("Answer the question directly") and skips to `plan_and_execute`.

**Files to create/modify:**
- `hermes/agent/nodes.py` — `decompose_question` checks mode; if `direct`, inject a single passthrough hypothesis and set `current_hypothesis_idx = 0`
- `hermes/agent/graph.py` — add `route_question` node before `decompose`; conditional edge to `decompose` or directly to `plan_and_execute`
- `hermes/agent/state.py` — add `query_mode: Literal["direct", "investigate"]` to `AgentState`

**New deps:** none

**Why logged:** Observed during Milestone 1a testing — "What is the payment failure rate by region?" correctly generated the right SQL but wrapped it in unnecessary hypothesis framing, which confused the user.

---

### Phase 2d — `lookup_events` Tool Node
**What:** A tool the agent can call during planning to cross-reference a date range against a known events calendar (promotions, outages, releases, holidays). Prevents the agent from flagging a planned promo drop as an anomaly.

**Files to create/modify:**
- `hermes/tools/events.py` — `lookup_events(start: date, end: date) → list[Event]`; reads from a user-maintained `data/events.yaml`
- `hermes/agent/nodes.py` — register `lookup_events` as a callable tool alongside `execute_sql`
- `hermes/agent/state.py` — add `events_context: list[Event]` field
- `data/events.yaml` — user-maintained calendar of promotions, outages, product launches

**Events YAML shape:**
```yaml
events:
  - date: 2025-11-23
    type: outage
    description: "Payment gateway downtime 14:00–18:00 UTC"
  - date: 2025-11-29
    type: promotion
    description: "Black Friday 30% discount — expected revenue spike"
```

**New deps:** none

---

### Phase 2h — Error Classification & SQL Hardening ✅
**What:** Three complementary improvements to how Aughor handles SQL errors and generates correct SQL in the first place — eliminating the most common failure classes before they reach the retry loop.

**Why:** FIX_SQL currently receives raw database error strings (e.g. `"function round(double precision, integer) does not exist"`) and asks the LLM to fix them. LLMs fix raw errors inconsistently. Pre-classifying errors into structured diagnostic hints — "PostgreSQL ROUND requires ::numeric cast; AVG() returns double precision" — dramatically increases first-fix success rate. Proactive dialect transforms catch the predictable error classes before execution entirely.

**Integration note (no clash with 2f SQL KB):** Error classification provides structural, rule-based hints (fast, deterministic). The SQL KB provides semantic pattern examples (embedding lookup). Both inject into FIX_SQL_PROMPT — classification runs first, KB retrieval appends examples. Complementary layers, not competing.

**Phase 2h-i — Error Classification (30+ patterns):**
Extend `plan_and_execute` with a pre-LLM `_classify_sql_error(error, sql, dialect)` function that maps error strings to targeted diagnostic hints before calling FIX_SQL_PROMPT:

| Error pattern | Injected hint |
|---|---|
| `"round" + "does not exist" + "double precision"` | "ROUND() needs ::numeric cast: `ROUND(AVG(col)::numeric, 2)`" |
| `"not in group by"` | "Add to GROUP BY or wrap in aggregate function" |
| `"cannot cast interval to numeric"` | "Use `EXTRACT(EPOCH FROM interval)/86400` for day conversion" |
| `"division by zero"` | "Wrap denominator: `NULLIF(col, 0)`" |
| `"column does not exist" + alias pattern` | "Alias used as schema name; qualify as `schema.table`" |

- `hermes/agent/nodes.py` — `_classify_sql_error(error, sql, dialect) → str` function; called in `plan_and_execute` before FIX_SQL LLM call; result prepended to fix prompt as `DIAGNOSIS:` block
- `hermes/agent/prompts.py` — `FIX_SQL_PROMPT` gains `{error_diagnosis}` placeholder

**Phase 2h-ii — Proactive Dialect Post-Processing:**
Apply three sequential transforms to every PostgreSQL query *before* execution — catch the predictable error classes without a round-trip:

1. **Timestamp safety:** `col::TIMESTAMP` → `NULLIF(col, '')::TIMESTAMP` (handles CSV-loaded empty strings)
2. **ROUND precision:** `ROUND(expr, N)` → `ROUND((expr)::numeric, N)` when expr is AVG/SUM
3. **Interval arithmetic:** `(ts - ts)::numeric` → `EXTRACT(EPOCH FROM (ts - ts))/86400`

Each uses balanced-parenthesis matching to avoid breaking nested expressions.

- `hermes/db/connection.py` — `PostgresConnection._apply_dialect_fixes(sql) → str`; called inside `execute()` before query hits the wire; DuckDB connection has a no-op stub
- Only applied for `dialect="postgres"` — DuckDB and others unaffected

**Phase 2h-iii — Column Ambiguity Pre-flight:**
Scan generated SQL before execution for unqualified column references that exist in multiple joined tables. Zero LLM cost — pure string matching against the schema.

- `hermes/tools/ambiguity.py` — `detect_ambiguous_columns(sql, schema_tables) → list[AmbiguityWarning]`; parses column names from SELECT/WHERE/GROUP BY; cross-references against schema to find multi-table matches
- `hermes/agent/nodes.py` — called in `plan_and_execute` after LLM generates SQL; ambiguity warnings injected into `data_quality_notes` and back into the next FIX_SQL prompt: "Column 'status' exists in orders AND payments — qualify as orders.status"

**New deps:** none

---

### Phase 2i — Schema Intelligence ✅
**What:** Make the schema context injected into every prompt significantly richer — by detecting likely foreign-key relationships via column name analysis, and caching schema metadata to avoid redundant LLM calls when nothing has changed.

**Why:** Aughor currently passes raw DDL to the LLM and relies on it to infer joins. For databases where column naming isn't perfectly consistent (`customer_id` in orders, `cust_id` in customers), the LLM hallucinates JOIN columns or misses the relationship entirely. Explicit join hints prevent this. Schema fingerprinting makes auto-seed and glossary injection idempotent and instant on reconnect.

**Phase 2i-i — Fuzzy Join Inference:**
Detect foreign-key relationships by normalising column names to their "root" — stripping ID suffixes — and matching across tables:

- `_ROOT_SUFFIXES = ["_identifier", "_number", "_pseudonym", "_code", "_num", "_key", "_id"]` (longest first)
- Phase 1 (exact): columns sharing identical normalized name → high-confidence join
- Phase 2 (fuzzy): root within edit distance 1 → inferred join (marked as such)
- Explicit `NO DIRECT JOIN` warnings for table pairs that *look* related but share no column root

- `hermes/tools/schema.py` — `infer_joins(schema_tables) → list[JoinHint]`; returns `(table_a, col_a, table_b, col_b, confidence: "exact"|"inferred")`
- `hermes/tools/schema.py` — `build_schema_context()` appends join hints and no-join warnings to the schema block

Prompt output:
```
DETECTED JOINS:
  orders.customer_id → customers.cust_id  [inferred — verify]
  order_items.order_id → orders.order_id  [exact]
NO DIRECT JOIN DETECTED: payments ↔ products (do not hallucinate a JOIN path)
```

**Integration note (no clash with 1c schema vector search):** Join inference enriches the schema string that then gets embedded into Qdrant. Inference runs inside `build_schema_context()` which already runs before `build_schema_index()`. Ordering is preserved.

**Phase 2i-ii — Schema Fingerprinting:**
Cache schema metadata to avoid redundant auto-seed LLM calls and accelerate connection reuse:

- `Fingerprint = MD5(sorted_table_names + column_counts + row_counts_sampled)` — stable across reconnects if schema unchanged
- `hermes/db/schema_cache.py` — 50-entry LRU JSON cache at `data/schema_cache.json`; maps fingerprint → schema metadata (glossary status, join hints, table profiles)
- `hermes/semantic/autoseed.py` — checks fingerprint before running seed LLM calls; skips tables whose fingerprint matches the cache
- `hermes/tools/schema.py` — writes fingerprint to cache after every `build_schema_context()` call

Benefit: On reconnect to an unchanged database, all schema enrichment loads from cache — zero LLM calls, instant.

**New deps:** none

---

### Phase 2j — KB Pattern Enrichment ✅
**What:** Upgrade the existing 235 SQL KB patterns with richer semantic structure — causal chains, metric inflation/deflation detection SQL, and related-pattern cross-links. The KB becomes a domain encyclopedia, not just a code example library.

**Why:** Current patterns help the LLM avoid SQL syntax mistakes. Enriched patterns help the LLM generate better *hypotheses* — understanding that "if monthly revenue drops, check order frequency, then AOV, then refund rate" as a causal chain. This directly improves `decompose_question` output quality.

**Integration note (additive, no clash):** Enrichment changes the JSON structure of existing files in the KB directory. The `kb_loader.py` `_build_embed_text()` function will be updated to include the new fields in the embed text. The Qdrant index will be rebuilt once. No changes to the retrieval API.

**New JSON fields per pattern:**
```json
{
  "causal_relationships": [
    {
      "symptom": "monthly revenue drops",
      "check_in_order": ["order_frequency", "average_order_value", "refund_rate"],
      "detection_sql": "SELECT DATE_TRUNC('month', order_date), COUNT(*), AVG(amount), SUM(refund_amount)/SUM(amount) FROM orders GROUP BY 1"
    }
  ],
  "inflation_causes": [
    {
      "cause": "Cancelled orders included in revenue",
      "detection_sql": "SELECT order_status, SUM(amount) FROM orders GROUP BY 1"
    }
  ],
  "deflation_causes": [...],
  "related_patterns": ["customer_lifetime_value", "refund_rate", "cohort_retention"]
}
```

**Files to modify:**
- `hermes/semantic/kb_loader.py` — extend `_build_embed_text()` to include `causal_relationships` symptoms + check_in_order; extend `_build_payload()` with new fields
- `hermes/agent/prompts.py` — `DECOMPOSE_PROMPT` gains `{kb_causal_chains}` block; agent sees symptom→check sequences before forming hypotheses
- All 235 KB JSON files — enriched with new fields (data work, not code work)

**New deps:** none  
**Dependency on:** Phase 2f (existing KB infrastructure)

---

## Milestone 3 — Query Engine Evolution
**Goal:** Abstract the query layer so the agent runs identically against DuckDB in dev and any production warehouse (BigQuery, Snowflake, Redshift) without SQL rewrites.

### Phase 3a — ibis as Query Abstraction
**What:** Replace raw SQL strings in tool nodes with **ibis** expressions. ibis is a backend-agnostic Python dataframe API that compiles to the target dialect — write once, execute against DuckDB in dev or BigQuery/Snowflake in prod.

**Why:** Currently the agent generates raw SQL strings and relies on SQLGlot transpilation for dialect differences. ibis handles this at the expression level, which is more robust and enables type-safe query construction.

**Files to create/modify:**
- `hermes/tools/executor.py` — add `ibis_execute(expr, conn)` alongside existing SQL executor; keep raw SQL path as fallback
- `hermes/db/connection.py` — expose `ibis_connection()` returning an ibis backend bound to the underlying DB
- `hermes/agent/nodes.py` — `plan_and_execute` can request ibis expressions when schema is ibis-registered

**New deps:**
```
ibis-framework[duckdb,bigquery,snowflake]>=9.0.0
```

---

### Phase 3b — Connector-X for Bulk Reads
**What:** Use **Connector-X** for fast bulk reads from Postgres/MySQL/Snowflake directly into Arrow, bypassing Python row-by-row fetching. Critical for investigations that need to pull large result sets for statistical analysis.

**Files to create/modify:**
- `hermes/db/connection.py` — `PostgresConnection.bulk_read(sql) → pa.Table` using `connectorx.read_sql()`; existing `execute()` path stays for small queries
- `hermes/tools/executor.py` — route to `bulk_read` when `row_count > BULK_THRESHOLD` (default 10k rows)

**New deps:**
```
connectorx>=0.3.3
```

---

### Phase 3c — SQLMesh for Materialization
**What:** Use **SQLMesh** to incrementally materialize expensive investigation sub-queries (e.g., 90-day rolling joins) as cached views. Subsequent investigations reuse them instead of re-computing.

**Files to create/modify:**
- `hermes/semantic/sqlmesh_bridge.py` — register expensive query patterns as SQLMesh models; `get_or_materialize(query) → table_ref`
- `hermes/tools/executor.py` — check SQLMesh cache before executing; invalidate on schema change

**New deps:**
```
sqlmesh>=0.100.0
```

**Dependency on:** Phase 3a (ibis expressions map cleanly to SQLMesh models)

---

## Milestone 4 — Statistical Engine Upgrade
**Goal:** Add time series forecasting so the agent can answer "is this drop unusual *given the trend*?" — not just "is it outside the historical distribution?"

### Phase 4a — Prophet Forecasting
**What:** Add **Prophet** (Meta) to the statistical toolkit. After STL decomposition flags an anomaly, Prophet fits a trend + seasonality model on the 90-day window and computes whether the current value is within the forecast confidence interval.

**Why:** STL + z-score catches point anomalies. Prophet adds the forward-looking context: "this is −8% vs last week, but the trend was already declining, so the underlying problem started 3 weeks ago." That's meaningfully richer than a z-score.

**Files to create/modify:**
- `hermes/tools/stats.py` — `forecast_anomaly(series: pd.Series) → StatResult`; runs Prophet fit + prediction interval; returns `{"type": "forecast", "is_anomaly": bool, "sigma": float, "context": "worst in N weeks"}`
- `hermes/agent/nodes.py` — `_attach_stats()` calls `forecast_anomaly` when series length > 30 data points

**New deps:**
```
prophet>=1.1.5
```

**Note:** Prophet requires `pystan` which has a C++ build step — add to `uv` deps and document the build requirement.

---

## Milestone 5 — LLM Provider Switcher
**Goal:** Claude Sonnet as a cloud fallback when Ollama is unavailable or slow; prompt caching on schema context to cut token costs significantly.

**Files to create/modify:**
- `hermes/llm/provider.py` — extend to support `anthropic` backend; `get_client(role)` returns Anthropic SDK client when `HERMES_BACKEND=anthropic`
- `hermes/llm/cache.py` — wrap schema context in Anthropic cache-control blocks (5-min TTL); schema context is ~2–5k tokens re-sent on every node call — caching gives ~90% cost reduction per investigation
- `.env.example` — add `HERMES_BACKEND=anthropic`, `ANTHROPIC_API_KEY=`

**Cloud model assignments (mirrors local two-model architecture):**
- `coder` role → `claude-sonnet-4-6` (best SQL + structured reasoning in cloud tier)
- `narrator` role → `claude-sonnet-4-6` with extended thinking enabled
- Embeddings stay local (`nomic-embed-text`) — no cloud embedding needed

**New deps:**
```
anthropic>=0.30.0
```

**Env vars:**
```
HERMES_BACKEND=anthropic       # "ollama" | "anthropic"
ANTHROPIC_API_KEY=sk-ant-...
HERMES_CLOUD_MODEL=claude-sonnet-4-6
```

**Dependency on:** Milestone 2a (two-model provider abstraction already in place)

---

## Milestone 6 — Security & Privacy
**Goal:** Make Aughor safe for enterprise data — PII never reaches the LLM, queries are sandboxed, every execution is audited, and credentials are vault-managed.

### Phase 6a — PII Detection with Microsoft Presidio
**What:** Scan every query result through **Microsoft Presidio** before it enters the LLM context. If a result contains emails, SSNs, phone numbers, or other PII, redact the values and inject a note instead: `"[REDACTED: 3 email addresses detected in result]"`.

**Why:** The agent currently forwards raw query results to the LLM. On a production warehouse with a customer table, a query like `SELECT * FROM customers LIMIT 5` would expose real PII in the LLM prompt — unacceptable in enterprise or regulated contexts.

**Files to create/modify:**
- `hermes/security/pii.py` — `scan_and_redact(rows: list[dict]) → (list[dict], list[str])`; uses Presidio `AnalyzerEngine` + `AnonymizerEngine`
- `hermes/tools/executor.py` — call `scan_and_redact()` on every `QueryResult` before returning to agent nodes
- `hermes/agent/state.py` — add `pii_redactions: list[str]` to `AgentState` (for audit trail)

**New deps:**
```
presidio-analyzer>=2.2.0
presidio-anonymizer>=2.2.0
```

---

### Phase 6b — Query Sandboxing & Budget Enforcement
**What:** Hard limits on every LLM-generated query to prevent runaway scans. All limits are configurable per connection.

**Limits (defaults):**
- Max rows scanned: 10M
- Max execution time: 30s
- Max queries per investigation: 50
- Allowed statement types: SELECT only (already enforced via SQLGlot — formalize as config)

**Files to create/modify:**
- `hermes/security/sandbox.py` — `QueryBudget` dataclass; `enforce(sql, conn) → None` raises `BudgetExceeded` before execution
- `hermes/db/connection.py` — wrap `execute()` with `sandbox.enforce()` call
- `hermes/db/registry.py` — store per-connection budget config in `connections.db`
- `hermes/api.py` — expose budget config on `POST /connections` and `PUT /connections/{id}/budget`

**New deps:** none

---

### Phase 6c — Append-Only Audit Trail
**What:** Every query the agent executes is logged append-only with full context. Immutable — rows are never updated or deleted.

**Audit log schema:**
```
(id, tenant_id, user_id, investigation_id, hypothesis_id, sql, row_count, execution_ms, pii_redacted, timestamp)
```

**Files to create/modify:**
- `hermes/security/audit.py` — `AuditLogger`; writes to `data/audit.db` (separate SQLite, append-only enforced via trigger)
- `hermes/tools/executor.py` — call `audit.log()` after every query execution
- `hermes/api.py` — `GET /audit?investigation_id=&limit=` for operators

**New deps:** none

---

### Phase 6e — Gradient Safety Verdict
**What:** Add a `SUSPICIOUS` middle tier between `SAFE` and `BLOCKED` — queries that pass the SELECT-only structural check but show heuristic warning signs get a yellow flag rather than hard-failing or silently executing.

**Why:** Binary SAFE/BLOCKED is too coarse. A query that scans 500M rows, crosses multiple schemas, or references an unexpected combination of sensitive tables deserves a warning to the user — but shouldn't be blocked. The analyst can override with context ("yes, this cross-schema join is intentional"). This is especially useful as a trust signal for new connections.

**Integration note (no clash with SQLGlot allowlist):** SQLGlot enforces the structural SELECT-only rule (layer 1). Gradient safety is a semantic heuristic layer on top (layer 2). They run in sequence: structural block first, then semantic rating.

**Suspicious signals (heuristic):**
- Query scans >3 tables (complex join graph, high blast radius)
- References columns matching PII name patterns (`email`, `ssn`, `phone`, `dob`) without explicit masking
- Full-table scan with no WHERE clause on a large table (>1M rows)
- CROSS JOIN detected

**Files to create/modify:**
- `hermes/security/safety.py` — `SafetyVerdict` enum gains `SUSPICIOUS`; `_score_suspicious(sql, schema) → list[str]` returns human-readable warning reasons
- `hermes/agent/nodes.py` — on SUSPICIOUS verdict: continue execution but inject warnings into `data_quality_notes` and surface in report
- `web/components/ReportView.tsx` — amber "⚠ Flagged Query" badge when `safety_verdict == "suspicious"`

**New deps:** none

---

### Phase 6d — Credential Management Upgrade
**What:** Replace the current Fernet-encrypted SQLite credential store with **HashiCorp Vault** (self-hosted) or **Doppler** for production deployments. Current Fernet store is fine for local dev; enterprise deployments need centralized secret management with rotation and access policies.

**Files to create/modify:**
- `hermes/db/registry.py` — add `VaultBackend` and `DopplerBackend` alongside existing `SQLiteBackend`; `HERMES_SECRET_BACKEND` env var selects the active backend
- `.env.example` — add `HERMES_SECRET_BACKEND=vault`, `VAULT_ADDR=`, `VAULT_TOKEN=`

**New deps:**
```
hvac>=2.1.0         # HashiCorp Vault client
doppler-env>=0.3.0  # Doppler (optional, lighter alternative)
```

**Dependency on:** Phases 6a–6c (complete security picture before credential upgrade)

---

## Milestone 7 — Observability
**Goal:** Full LLM trace per investigation in Langfuse; OpenTelemetry spans for timing across all nodes.

**Files to create/modify:**
- `hermes/agent/nodes.py` — wrap each node with `@observe` (Langfuse decorator); include `hypothesis_id` and `iteration` as trace metadata
- `hermes/llm/provider.py` — pass Langfuse client to instructor so every LLM call is traced with prompt + completion + token count
- `hermes/api.py` — emit `trace_id` in SSE `start` event so frontend can deep-link to the Langfuse trace for that investigation

**New deps:**
```
langfuse>=2.0.0
opentelemetry-sdk>=1.24.0
opentelemetry-exporter-otlp>=1.24.0
```

**Dependency on:** none, but most valuable after Milestone 5 (cloud LLM calls have real token costs worth tracing)

---

## Milestone 8 — Frontend Charts & UX ✅
**Goal:** Upgrade the frontend from a text-based evidence browser to a data product with proper charts, KPI cards, and a live thinking trace.

### Phase 8a — Thinking Trace ✅
**What:** Visual progress stepper that replaces the plain text activity log. Shows each LangGraph stage live with a pulsing dot while running and verdict-coloured completion dots.

**Shipped:**
- `web/components/ThinkingTrace.tsx` — steps derived entirely from existing `InvestigationState` (no new state fields); investigate path shows Route → Decompose → H1…HN (verdict + %) → Synthesize; direct path shows Route → Query → Summarize
- `web/app/page.tsx` — replaced activity log `<ScrollArea>` with `<ThinkingTrace state={state} />`; removed now-unused `logEndRef` and `useEffect`

**New deps:** none

---

### Phase 8b — KPI Highlight ✅
**What:** Single-row query results (scalar answers like "What is our MRR?") are surfaced as prominent metric cards above the results table — auto-formatted as `1.24M`, `45.3k`, or `3.14`.

**Shipped:**
- `KPIHighlight` sub-component inside `web/components/ReportView.tsx` — renders 1–3 numeric columns as centred metric cards; skips multi-row results and non-numeric columns automatically; no Tremor dependency needed

**Note:** Implemented without `@tremor/react` — same visual outcome with shadcn/Tailwind primitives, zero extra bundle weight.

---

### Phase 8c — Observable Plot Charts ✅
**What:** Auto-charting for direct query results. Detects whether the result has a time + numeric column (line/area chart) or categorical + numeric column (ranked bar chart) and renders accordingly using Observable Plot.

**Shipped:**
- `web/components/InvestigationChart.tsx` — column-type detection via name heuristics + sample value inspection; time series: emerald line + area fill; bar: horizontal ranked bars top-20; renders `null` if data isn't chartable — no empty frames
- `web/components/ReportView.tsx` — `<InvestigationChart>` rendered below the direct results table
- `@observablehq/plot ^0.6.17` installed; renders via `useEffect` append pattern (browser-safe, SSR-compatible)

---

## Milestone 9 — Quick Chat Mode
**Goal:** A conversational, no-frills mode for fast data retrieval with multi-turn memory. Ask in plain English, get a number or chart immediately — no verdict, no executive summary. Follow-up naturally: "filter by last 90 days", "also show revenue", "compare to last quarter" just works. Designed for power users who need speed over narrative.

**Why separate from Direct Query:** Direct Query is single-shot and wraps every result in the full report shell. Quick Chat is stripped entirely — bare answer in a bubble — and crucially, it carries *conversation history* across turns so each question can reference the previous one.

**How it differs from Direct Query:**
| | Direct Query | Quick Chat |
|---|---|---|
| Result format | Full report shell | Bare number / table / chart bubble |
| Narrative | Executive Summary + bullets | None |
| Follow-ups / multi-turn | No (stateless) | Yes — last 3 turns in context |
| Recommended actions | Yes | No |
| Risks | Yes | No |
| Entry point | `route_question` classifies | User explicitly selects chat tab |

**Core mechanism — Conversation History:**
Each chat session maintains a `conversation_history: list[ChatTurn]` at the session layer (outside `AgentState` — this is session-level state, not investigation-level state). Each `ChatTurn = (question: str, sql: str, headline: str)`. The last 3 turns are injected into every `POST /chat` planning prompt:

```
CONVERSATION HISTORY:
[Turn 1] Q: "Show top 10 customers by revenue"
         SQL: SELECT customer_id, SUM(amount) ... ORDER BY 2 DESC LIMIT 10
[Turn 2] Q: "Filter by last 90 days"
         SQL: SELECT customer_id, SUM(amount) ... WHERE order_date >= NOW() - INTERVAL '90 days' ...
[Current] Q: "Also show their country"
```

This makes "also show X", "filter by Y", "compare to last month" resolve correctly without re-stating the full context.

**Integration note (no clash with AgentState):** `conversation_history` is a session-level list managed in the `POST /chat` endpoint, not stored in `AgentState`. Each chat turn still creates a fresh `plan_and_execute` run with a new `AgentState` — but the history is prepended to its planning prompt. Clean separation of session state (chat) and investigation state (agent).

**Files created/modified:**
- `hermes/api.py` — `POST /chat` endpoint; `_ChatAnswer(sql, headline, chart_type)`; `chart_type` SSE event after headline; `result.rows[:10000]`
- `hermes/agent/prompts.py` — `CHAT_SQL_SYSTEM` with full chart_type selection rules and axis orientation; `CHAT_PROMPT` with bar_horizontal trigger words, stacked_bar column guidance, pie no-LIMIT instruction
- `web/app/page.tsx` — Chat as default tab; Deep Analysis tab combines Investigate + History
- `web/components/ChatPanel.tsx` — Conversational turn list; scrollable bubbles; bottom input; clears on connection change
- `web/components/ChatMessage.tsx` — `InlineChart` component with 5 chart branches (bar, bar_horizontal, line, stacked_bar, pie); `fmtTimestampLabel`; `buildHtmlLegend`; `startDrag` + `userH` resize; `outerRef` + `innerRef` two-ref pattern; `cancelled` dedup flag
- `web/lib/useChat.ts` — `ChatTurn.chartType`; `CHART_TYPE` reducer action; SSE handler for chart_type event

**New deps:** none (d3-shape is a transitive dep of Observable Plot)

**Dependency on:** Direct Query Mode (2e, shipped) — reuses `plan_and_execute` node and result streaming

---

## Milestone 12 — Aughor Ontology Layer
**Goal:** Elevate Aughor's semantic layer from schema-plus-glossary to a full ontology — typed business entities, verified relationships, cardinality-correct joins, lifecycle state machines, and actionable SQL templates that enforce business rules automatically. The planner calls `ACTION: get_active_orders()` instead of re-deriving the correct exclusion filter from scratch on every investigation. Every investigation from Sprint 1 onward writes less buggy SQL.

**Relationship to existing Milestone 1 (Semantic Layer):** The glossary, auto-seed, dbt, and metrics catalog give descriptions and formulas. The ontology adds three things none of those provide: typed entities (a `Customer` object with an identity key and lifecycle), typed relationships (`Customer PLACES Order — cardinality 1:N, verified`), and actions (parameterized SQL templates with business rules baked in). The two layers are complementary; the ontology is built *from* the glossary and schema intelligence already in place.

**Key architectural principle:** The agent should never write raw SQL against raw tables when an ontology action exists. Actions are the verified, rule-enforcing interface. Raw SQL is the escape hatch for things the ontology doesn't cover yet.

---

### Phase 12a — Structural Ontology (Sprint 1 — no LLM, pure extraction)
**What:** Extract typed entities, verified grains, lifecycle states, cardinality-correct relationships, and preliminary default filters from the existing schema + column profiles + glossary — entirely deterministically, no LLM calls.

**Prerequisite:** Column profiles (`build_column_profile()`) must exist before this sprint. Column profiles are not yet built — this is the gating dependency. They need: `grain_verified` (COUNT(*) == COUNT(DISTINCT pk)), `null_rate`, `distinct_count`, `is_low_cardinality`, `semantic_type`, and `row_count` per table/column.

**Files to create:**
- `hermes/ontology/__init__.py`
- `hermes/ontology/models.py` — four Pydantic models: `OntologyEntity`, `OntologyRelationship`, `OntologyMetric`, `OntologyAction`, plus `OntologyGraph` container
- `hermes/ontology/builder.py` — `extract_structural_ontology(schema, join_map, column_profiles, glossary) → OntologyGraph`; entity identification from grain-verified tables; cardinality inference from distinct counts; lifecycle state extraction (one `SELECT DISTINCT status` per entity); default filter extraction from glossary caveats
- `hermes/ontology/store.py` — persist to `data/ontology_cache.json` keyed by schema fingerprint (extends existing `schema_cache.json` pattern)

**Files to modify:**
- `hermes/db/connection.py` — call `build_structural_ontology()` after schema build when fingerprint differs from cached ontology
- `hermes/tools/schema.py` — `build_schema_context()` injects entity grain hints and default filters from ontology (falls back to glossary if ontology not built)

**Core models (abbreviated):**
```python
class OntologyEntity(BaseModel):
    id: str                        # "Customer", "Order", "Product"
    source_tables: list[str]
    identity_key: str              # canonical PK column
    grain_verified: bool           # COUNT(*) == COUNT(DISTINCT identity_key)
    lifecycle_states: list[str]    # from DISTINCT status query
    active_filter: Optional[str]   # SQL fragment for non-terminal rows
    default_filters: list[str]     # auto-applied WHERE clauses

class OntologyRelationship(BaseModel):
    id: str                        # "Customer_PLACES_Order"
    from_entity: str
    to_entity: str
    verb: str                      # "PLACES" — placeholder until Phase 12b
    cardinality: Literal["1:1","1:N","N:1","N:N"]
    join_sql: str
    join_confidence: Literal["exact","inferred","verified"]
    nullable: bool

class OntologyMetric(BaseModel):
    id: str                        # "customer_ltv", "gross_margin"
    entity: str
    formula_sql: str
    grain: str
    known_divergent_calculations: list[str]
    unit: str

class OntologyAction(BaseModel):
    id: str                        # "get_active_orders", "compute_customer_revenue"
    entity: str
    action_type: Literal["filter","compute","traverse","aggregate","validate"]
    sql_template: str              # parameterized SQL
    parameters: dict[str, Any]
    business_rules_enforced: list[str]
    returns: str
```

**Cardinality inference (deterministic, no LLM):**
```python
def _infer_cardinality(join, column_profiles) -> str:
    from_unique = profiles[from_table].columns[from_col].distinct_count == profiles[from_table].row_count
    to_unique   = profiles[to_table].columns[to_col].distinct_count   == profiles[to_table].row_count
    if from_unique and to_unique: return "1:1"
    if to_unique:                 return "N:1"
    if from_unique:               return "1:N"
    return "N:N"
```

**New deps:** none  
**Acceptance:** `GET /ontology/entities` returns Customer, Order, Product, Category with verified grains and lifecycle states against the Superstore fixture. `get_active_orders()` action is present with the correct exclusion filter derived from the glossary caveat on `order_status`.

---

### Phase 12b — Semantic Enrichment + Actions (Sprint 2 — one LLM batch pass)
**What:** Add meaning to the structural ontology — relationship verbs, entity descriptions, action definitions, and canonical metric SQL. Runs **once on initial connection**, cached by schema fingerprint. Zero LLM calls on reconnect to an unchanged database.

**Files to create:**
- `hermes/ontology/enricher.py` — `enrich_ontology_semantics(graph, coder_llm, glossary) → OntologyGraph`; single structured LLM call returning `EnrichmentOutput`; applies verbs, descriptions, actions, and metric formulas back to the graph
- `hermes/ontology/actions.py` — `expand_action(action_id, parameters, ontology) → str`; expands `ACTION: get_active_orders()` tokens to executable SQL before hitting the wire
- `hermes/agent/prompts_ontology.py` — `ENRICH_ONTOLOGY_PROMPT`, `ONTOLOGY_ACTIONS_SECTION` (injected into `PLAN_QUERIES_PROMPT`), `ONTOLOGY_CONTEXT_SECTION` (injected into `DECOMPOSE_PROMPT`)

**Files to modify:**
- `hermes/agent/prompts.py` — `DECOMPOSE_PROMPT` gains `{entity_summary}` + `{relationship_summary}` injection; `PLAN_QUERIES_PROMPT` gains `{ontology_actions_section}`; planner prefers `ACTION:` calls over raw SQL for standard entity operations
- `hermes/agent/nodes.py` — `plan_and_execute` scans generated query strings for `ACTION:` tokens and expands them via `actions.expand_action()` before `execute_query()`
- `hermes/api.py` — `GET /ontology`, `GET /ontology/entities`, `GET /ontology/actions`, `GET /ontology/metrics`, `PUT /ontology/entities/{id}` (human override)

**Enrichment prompt shape:**
```
You are building an ontology for a data warehouse. The structural facts below were
derived automatically from the schema and data. Your job is to add semantic meaning.

STRUCTURAL FACTS: {structural_summary}
GLOSSARY: {glossary_excerpt}

For each relationship, assign a business verb (Customer PLACES Order,
Order CONTAINS LineItem, Product BELONGS_TO Category).
For each entity, write a one-sentence business description.
Define actionable SQL templates that enforce the exclusion rules from the glossary.
For each metric, provide the canonical SQL formula and list divergent calculations.
```

**Entity-aware decomposition (injected into DECOMPOSE_PROMPT):**
The decomposer reasons in terms of entities and relationships — "Revenue drop" maps to the Order entity's `compute_revenue` metric, not the raw `amount` column. Entity-based hypotheses are more testable because they map directly to available actions.

**New deps:** none  
**Acceptance:** Re-running the discount investigation uses `ACTION: get_active_orders()` in at least one query. No canceled orders appear in revenue findings. Enrichment cached — reconnect does not re-run the LLM call.

---

### Phase 12c — Ontology UI + Metric Divergence Detection (Sprint 3)
**What:** A browsable, editable ontology panel in the UI. Metric consistency check catches divergent SQL before synthesis. The user can inspect what the agent knows about their data, override it, and trust it.

**Files to create:**
- `web/components/OntologyPanel.tsx` — entity browser (list + detail), relationship graph (reuse Mermaid ER infra but make nodes clickable), actions list, metrics definitions
- `web/components/EntityCard.tsx` — per-entity detail: identity key, grain badge, lifecycle state machine visualization, default filters, related metrics
- `hermes/ontology/divergence.py` — `check_metric_consistency(report, ontology, query_history) → list[str]`; flags findings whose backing SQL doesn't match the canonical metric formula stored in the ontology

**Files to modify:**
- `hermes/agent/nodes.py` — `check_consistency` calls `check_metric_consistency()` alongside existing LLM-based contradiction detection
- `web/app/page.tsx` — add Ontology tab to nav
- `hermes/api.py` — `PUT /ontology/entities/{id}` + `PUT /ontology/actions/{id}` for user overrides; human corrections applied immediately (no re-generation)

**UI hierarchy:**
```
OntologyPanel (new tab)
├── Entities
│   ├── Customer — identity: customer_id (verified) · lifecycle: created → active → churned
│   ├── Order    — identity: order_id (verified) · lifecycle: created → shipped → delivered / canceled
│   └── ...
├── Relationships (interactive graph)
│   ├── Customer PLACES Order  (1:N, verified)
│   ├── Order CONTAINS LineItem (1:N, exact)
│   └── ...
├── Actions (callable, copyable)
│   ├── get_active_orders() — excludes canceled, deleted
│   └── compute_customer_revenue(start, end)
└── Metrics (canonical SQL definitions)
    ├── gross_margin = (revenue - cost) / revenue
    └── ...
```

**New deps:** none  
**Acceptance:** Metric divergence is flagged in the synthesis step when a finding references revenue using a non-canonical formula. OntologyPanel renders entities, relationships, and actions for the Superstore fixture.

---

### Ontology dependency notes
- Phase 12a requires **column profiles** (not yet built) as a prerequisite — this is the gating piece
- Phase 12a builds on: Schema Intelligence (2i) join map + schema fingerprint; Glossary (1a) caveats and filters
- Phase 12b builds on: Phase 12a structural graph + Glossary (1a) + Two-Model arch (2a) for enrichment LLM call
- Phase 12c builds on: Phase 12b + ER Diagram infrastructure (Mermaid reuse)
- Actions in Phase 12b are the prerequisite for entity-aware routing (Phase 3.3 in the design doc) — deferred to future sprint

---

## Milestone 10 — LLM Evals
**Goal:** Braintrust golden dataset; regression testing on agent verdict quality so model upgrades can be validated before deploying.

**Target dataset:** 50 business questions with known correct root causes against the fixture DuckDB warehouse. Sourced from confirmed investigations in history.

**Files to create/modify:**
- `evals/dataset.py` — golden Q&A pairs with expected verdicts; loaded from `evals/golden.jsonl`
- `evals/run.py` — Braintrust experiment runner; runs each question through the full agent loop; scores all three metrics
- `evals/scorers.py` — three custom scorers:
  - `verdict_accuracy` — does the agent's top confirmed hypothesis match the expected root cause?
  - `query_efficiency` — did the agent reach a confident verdict in ≤ 8 queries? (target: 80% of runs)
  - `hallucination_rate` — does every claim in `key_findings` have a non-null `hypothesis_id` that maps to a real query? (target: 0% uncited claims)

**CI gate:** run evals on every PR that touches `hermes/agent/`. A regression of >5% on any metric is a blocking failure.

**New deps:**
```
braintrust>=0.0.150
autoevals>=0.0.70
```

**Dependency on:** Investigation History ✅ (golden dataset sourced from saved runs), Milestone 2a (stable two-model arch to eval against)

---

## Milestone 11 — Visual Query Builder
**Goal:** A point-and-click query builder that generates correct SQL without any LLM involvement — for users who know exactly what they want and need deterministic, instant results. Complements the agent rather than replacing it.

**Why separate from Direct Query / Quick Chat:** Both of those use LLMs to interpret intent. The Visual Builder is a no-LLM path: the SQL it produces is exactly what the user specified. No hallucination risk, zero latency. Covers the 20% of queries that are simple enough to click together but currently get routed through expensive LLM inference.

**Integration note (no clash with agent pipeline):** The builder is a parallel path that bypasses the entire agent loop. It calls `execute_sql()` directly, bypasses `route_question`, `decompose`, `plan_and_execute`, and `synthesize`. The result renders in the same `DirectResultTable` + `InvestigationChart` components as a successful Direct Query — reusing the existing display layer.

**How:**

*Step 1 — Table Selection:* Pick a connection + table from a dropdown (populated from `GET /connections/{id}/schema`).

*Step 2 — Field Configuration:*
- **Dimensions** (GROUP BY): non-numeric columns from the selected table; drag to add
- **Measures**: numeric columns + aggregation (SUM / AVG / COUNT / COUNT DISTINCT / MIN / MAX)
- **Filters**: column + operator (= / ≠ / > / < / ≥ / ≤ / LIKE / IN / IS NULL) + value
- **Sort**: column + ASC/DESC + LIMIT (default 500)

*Step 3 — SQL Preview:* As fields are added, the generated SQL is shown live (read-only, but copyable).

*Step 4 — Run:* Executes via `POST /query/run` → same result rendering as Direct Query (table + chart + KPI cards).

**Metrics Catalog integration:** If a Metric is defined that uses the selected table, it appears as a pre-built measure option ("Add MRR as a measure"). One click adds the approved formula.

**Files to create/modify:**
- `web/components/QueryBuilder.tsx` — Field palette, dimension/measure/filter configuration; live SQL preview
- `hermes/api.py` — `POST /query/run { sql, connection_id }` — safety-validates and executes; returns `columns`, `rows`, `row_count`, `sql`; reuses existing `execute_sql()` + `_validate_sql()` path
- `web/app/page.tsx` — "Build" tab renders `<QueryBuilder>`

**New deps:** none  
**Dependency on:** M1e (Metrics Catalog — to show metrics as measure options), Phase 2h-iii (ambiguity detection on builder-generated SQL as a free safety check)

---

## Milestone 13 — Business Intelligence Layer
**Goal:** Transform Aughor from a reactive analyst into a proactive operating system for the business. Six phases in priority order — each buildable on top of what's already shipped. Together they close the loop between data, diagnosis, and action.

**Foundation already in place:** OntologyMetric with formula_sql (M12b ✅), 84 Tier-2 KB causal chains with `inflation_causes`/`deflation_causes` (2j ✅), ADA attribution waterfall with `controllable` flag (investigate.py ✅), Qdrant running with 3 collections + nomic-embed-text embedder (1c ✅), ontology lifecycle states extracted per entity (M12a ✅), `recommended_actions: list[str]` already in `AnalysisReport` (state.py ✅).

---

### Phase 13a — Metric Targets & Health Scorecard

**What:** Add target values and alert thresholds to metrics. Build a `/health-scorecard` endpoint and a `ProcessHealthPanel` that shows green/yellow/red status for every tracked metric — before the user asks a single question.

**Why first:** The smallest code change with the largest product transformation. Aughor currently answers questions; this makes it volunteer problems. A user opening the app should see "Refund Rate: 12% vs target 8% (red, ↑ trend)" in 2 seconds.

**Files to modify:**
- `aughor/ontology/models.py` — extend `OntologyMetric`: add `target_value: Optional[float]`, `warning_threshold: Optional[float]`, `critical_threshold: Optional[float]`, `target_period: Optional[str]`, `benchmark_source: Optional[str]`
- `aughor/semantic/metrics.py` — extend `MetricDefinition` with same target fields; `load_metrics()` / `save_metric()` updated
- `aughor/agent/prompts_investigate.py` — `ADA_SYNTHESIZE_PROMPT` gains instruction: "Compare findings against `{metric_targets_section}`. Prioritize controllable root causes where current value exceeds warning_threshold."
- `aughor/api.py` — new `GET /connections/{conn_id}/health-scorecard` endpoint: for each metric with a target, execute its `formula_sql`, compute variance + trend, return `{metric, current, target, variance, status: green|yellow|red, trend: up|down|flat}` array
- `web/lib/api.ts` — `getHealthScorecard(connId)` + TypeScript types
- `web/components/MetricsPanel.tsx` — add target/threshold fields to the metrics form

**Files to create:**
- `web/components/ProcessHealthPanel.tsx` — grid of metric health cards; color-coded status; "Investigate" button per red/yellow metric that launches an ADA investigation pre-scoped to that metric; sparkline trend (last 7 data points via existing stats engine)

**New deps:** none  
**Acceptance:** Opening ProcessHealthPanel on the Olist dataset shows at least 3 metrics with color-coded status. Clicking "Investigate" on a red metric launches an ADA investigation with that metric as the hypothesis seed. Target fields appear in the metrics form and persist across restart.

---

### Phase 13b — Structured Playbook from KB

**What:** Convert the 84 Tier-2 KB entries into a persistent, retrievable playbook of proven interventions. During ADA synthesis, recommendations are retrieved from the playbook rather than hallucinated. If no playbook entry matches, the LLM generates one but flags it "unproven".

**Why:** The KB already encodes "if refund_rate > 10%, check return policy window" — it just isn't stored as a reusable recommendation with a success rate. This is 80% a data transformation problem, not a new capability problem.

**Files to create:**
- `aughor/playbook/__init__.py`
- `aughor/playbook/models.py` — `PlaybookEntry(BaseModel)`: `id`, `trigger_metric: str`, `trigger_operator: Literal["gt","lt","eq"]`, `trigger_value: float`, `trigger_condition: str`, `recommendation: str`, `expected_impact: str`, `typical_timeline: str`, `owner_role: str`, `evidence_sources: list[str]`, `historical_success_rate: float`, `status: Literal["active","deprecated","draft"]`
- `aughor/playbook/store.py` — `load_playbook()`, `save_entry()`, `list_entries()`, `get_by_metric(metric: str)` → `list[PlaybookEntry]`; persists to `data/playbook.json`
- `aughor/playbook/builder.py` — `seed_from_kb(kb_entries) → list[PlaybookEntry]`; converts each `inflation_causes` / `deflation_causes` / `causal_relationships` KB entry into draft `PlaybookEntry` objects; run once on startup if `data/playbook.json` is empty
- `aughor/playbook/retriever.py` — `retrieve_for_root_cause(metric_name: str, direction: Literal["up","down"], ontology: OntologyGraph) → list[PlaybookEntry]`; returns matching entries sorted by `historical_success_rate`

**Files to modify:**
- `aughor/agent/investigate.py` — after ADA root-cause identification, call `playbook_retriever.retrieve_for_root_cause()` and inject matched entries into `recommendations`; unmatched root causes fall back to LLM with `"[unproven — add to playbook?]"` suffix in the recommendation text
- `aughor/api.py` — `GET /playbook`, `GET /playbook/{id}`, `POST /playbook`, `PUT /playbook/{id}`, `DELETE /playbook/{id}`

**Files to create (web):**
- `web/components/PlaybookPanel.tsx` — browse entries by metric/trigger; edit recommendation text and owner_role; approve drafts; "Add to Playbook" button surfaces in investigation reports when an LLM-generated recommendation has no playbook match

**New deps:** none  
**Acceptance:** After `seed_from_kb()` runs, `GET /playbook` returns ≥ 20 draft entries from the Olist KB. An ADA investigation that identifies refund rate as a root cause includes at least one playbook-sourced recommendation.

---

### Phase 13c — Outcome Tracking & Feedback Loop

**What:** Allow users to mark recommendations as accepted, implemented, or done. Track before/after metric values. Over time, `historical_success_rate` on playbook entries reflects real organisational history.

**Why:** Without this, the playbook is a static list. With it, the system learns. After 10 "reviewed return policy" outcomes, Aughor knows that action has a 70% success rate in 4 weeks — and surfaces it first for new refund-rate spikes.

**Files to create:**
- `aughor/playbook/outcomes.py` — `RecOutcome(BaseModel)`: `id`, `inv_id`, `rec_id`, `action_text`, `metric_name`, `metric_before: Optional[float]`, `metric_after: Optional[float]`, `status: Literal["accepted","rejected","implemented","verified"]`, `implemented_at: Optional[str]`, `verified_at: Optional[str]`; `log_outcome()`, `load_outcomes_for_inv(inv_id)`, `update_playbook_success_rates()` (recomputes `historical_success_rate` from outcomes table)

**Files to modify:**
- `aughor/agent/state.py` — assign stable IDs to each item in `recommended_actions` (change `list[str]` to `list[RecommendationItem]` with `id` + `text` fields)
- `aughor/api.py` — `POST /investigations/{inv_id}/recommendations/{rec_id}/status` with body `{status, metric_before?, metric_after?}`; calls `outcomes.log_outcome()` + triggers `update_playbook_success_rates()`; `GET /investigations/{inv_id}/recommendations` lists current statuses
- `aughor/agent/investigate.py` — `ADA_SYNTHESIZE_PROMPT` gains `{playbook_evidence_section}`: "These recommendations have prior outcome data: [entry.recommendation — tried N times, success rate X%]"; retriever now sorts by `historical_success_rate` descending

**Files to create (web):**
- `web/components/RecommendationInbox.tsx` — shows all pending recommendations from recent investigations; each card: action text, expected impact, evidence link, "Mark Done" button, metric before/after input fields; accessible from the home page and from individual investigation reports

**New deps:** none  
**Acceptance:** Marking a recommendation "verified" with before/after values triggers `update_playbook_success_rates()`. The next ADA investigation on the same metric receives a prompt section showing the historical success rate.

---

### Phase 13d — Document Ingestion (Context Layer)

**What:** Allow users to upload PDFs, Word docs, and Markdown files (SOPs, return policies, strategy decks). Chunks are embedded into a new Qdrant collection. During ADA synthesis, relevant document snippets are retrieved and injected as external context alongside the KB.

**Why:** Aughor currently only knows what's in the database schema and the hardcoded KB. It cannot answer "How does our return rate compare to our stated policy?" because it has never read the return policy document. This adds the missing external-context channel.

**Files to create:**
- `aughor/knowledge/__init__.py`
- `aughor/knowledge/documents.py` — `parse_document(path: str) → list[str]` (chunked text, ~400 tokens/chunk); handles `.pdf` (PyPDF2), `.docx` (python-docx), `.md` and `.txt` (direct split); returns chunks with `{chunk_text, source_file, chunk_index}`
- `aughor/knowledge/indexer.py` — `index_document(conn_id, doc_id, chunks)`: embeds each chunk via existing `embedder.py`, upserts into new `aughor_documents` Qdrant collection with payload `{conn_id, doc_id, source_file, chunk_index, text}`; `search_documents(conn_id, query, k=5) → list[str]`; `delete_document(conn_id, doc_id)`

**Files to modify:**
- `aughor/semantic/kb_retriever.py` — `retrieve_for_synthesis(conn_id, question) → str`: after existing KB retrieval, also calls `indexer.search_documents(conn_id, question)`; returns combined block with `## KNOWLEDGE BASE` and `## UPLOADED DOCUMENTS` sections
- `aughor/agent/prompts_investigate.py` — `ADA_SYNTHESIZE_PROMPT` gains `{external_context_section}` placeholder; prompt instructs: "If UPLOADED DOCUMENTS contains policy or benchmark data relevant to the finding, cite it explicitly."
- `aughor/api.py` — `POST /connections/{conn_id}/documents` (multipart upload); `GET /connections/{conn_id}/documents` (list); `DELETE /connections/{conn_id}/documents/{doc_id}`

**Files to create (web):**
- `web/components/DocumentUploader.tsx` — drag-and-drop upload in the Configure panel (Data tab); shows uploaded document list with delete; file type badge (PDF/Word/Markdown)

**New deps:**
```
PyPDF2>=3.0.0
python-docx>=1.0.0
```

**Acceptance:** Uploading a return-policy PDF and running an investigation that touches refund rate includes a synthesis note citing the uploaded document. `GET /connections/{conn_id}/documents` lists the file. Deleting it removes the Qdrant vectors.

---

### Phase 13e — Business Process Visual Mapper

**What:** Extract process flows from the ontology's lifecycle states. Compute transition volumes and dwell times per step via SQL. Render as a colour-coded swimlane diagram — each step green/yellow/red based on drop-off rate vs baseline.

**Why:** The CEO can open Aughor, see the Order-to-Cash flow, spot that "Payment Authorization" has a 40% drop-off vs industry 15%, and click through to an investigation. This is the "show me the map" entry point before the user knows what question to ask.

**Files to create:**
- `aughor/process/__init__.py`
- `aughor/process/models.py` — `ProcessStep(BaseModel)`: `id`, `entity_id`, `state_name`, `volume: int`, `entry_rate: float`, `drop_off_rate: float`, `avg_dwell_seconds: Optional[float]`, `health_status: Literal["green","yellow","red"]`; `ProcessFlow(BaseModel)`: `entity_id`, `steps: list[ProcessStep]`, `transitions: list[StepTransition]`; `StepTransition`: `from_state`, `to_state`, `volume`, `rate`
- `aughor/process/mapper.py` — `build_process_flow(conn_id, entity: OntologyEntity, db) → ProcessFlow`: (1) queries `SELECT {status_col}, COUNT(*) FROM {source_table} GROUP BY 1` to get volumes per state; (2) queries transition pairs via `LAG(status)` window function where available; (3) computes drop-off = 1 - (volume_next / volume_current); (4) flags step red if drop-off > 2 standard deviations above mean across all steps

**Files to modify:**
- `aughor/api.py` — `GET /connections/{conn_id}/process-flows` returns all entity flows; `GET /connections/{conn_id}/process-flows/{entity_id}` returns single flow

**Files to create (web):**
- `web/components/ProcessMapper.tsx` — horizontal swimlane using `@xyflow/react` (already in deps from OntologyCanvas); nodes = lifecycle states with volume badge and red/yellow/green ring; edges = transitions with volume label; click node → `onChatWithStep` callback launches investigation scoped to that step's drop-off

**New deps:** none (`@xyflow/react` already installed)  
**Acceptance:** `GET /connections/{conn_id}/process-flows` returns at least one flow for the Olist dataset with the Order entity's 7 lifecycle states. Clicking a red step in the ProcessMapper launches an ADA investigation.

---

### Phase 13f — Causal Graph in the Ontology

**What:** Store causal edges in the ontology graph — extracted from ADA attribution waterfalls and domain intelligence episodes. Enable backward traversal: given an off-target metric, algorithmically trace upstream causal drivers and surface matching playbook actions without an LLM call.

**Why:** The ADA waterfall already produces "discount_depth contributed 42% to revenue decline" — that is a causal edge sitting in prose. Extracting it and persisting it makes the ontology a true digital twin: not just what exists, but what drives what.

**Files to modify:**
- `aughor/ontology/models.py` — add `CausalEdge(BaseModel)`: `id`, `source_metric: str`, `target_metric: str`, `relationship: Literal["drives","inhibits","correlates_with"]`, `evidence_strength: Literal["strong","moderate","weak","hypothesized"]`, `contribution_pct: Optional[float]`, `typical_lag: Optional[str]`, `source_investigations: list[str]`; add `causal_edges: dict[str, CausalEdge]` to `OntologyGraph`
- `aughor/ontology/store.py` — `append_causal_edge(conn_id, edge: CausalEdge)` upserts into persisted graph
- `aughor/agent/investigate.py` — after ADA synthesis, parse `attribution_waterfall` entries and call `store.append_causal_edge()` for each contribution with `contribution_pct > 5%`; `evidence_strength` = "strong" if pct > 20%, "moderate" if 10–20%, "weak" otherwise
- `aughor/playbook/retriever.py` — add `traverse_causal_graph(off_target_metric, ontology, max_depth=3) → list[str]`: BFS backward from `target_metric` through causal edges; returns list of upstream `source_metric` names; `retrieve_for_root_cause` gains a causal traversal pass before the direct metric lookup
- `aughor/api.py` — `GET /ontology/causal-edges` returns all edges; `GET /ontology/causal-edges/{metric}` returns edges where `target_metric == metric`

**Files to modify (web):**
- `web/components/OntologyCanvas.tsx` — render `causal_edges` as dashed arrows (`strokeDasharray: "4 2"`) with `relationship` label; edge colour: drives=amber, inhibits=red, correlates_with=zinc; click causal edge → show `contribution_pct` and source investigation link

**New deps:** none  
**Acceptance:** After 3 ADA investigations on the Olist dataset, `GET /ontology/causal-edges` returns ≥ 5 edges. OntologyCanvas shows dashed causal arrows alongside solid structural edges. `traverse_causal_graph("revenue")` returns upstream drivers that map to playbook entries.

---

## Build Sequence & Dependency Graph

**Recommended sprint order — each sprint compounds on the last:**

| Sprint | Milestone(s) | Key unlock |
|---|---|---|
| **1 — SQL Hardening** ✅ | 2h (Error Classification + Dialect Transforms + Column Ambiguity) + 2i (Join Inference + Fingerprinting) | Every query gets smarter; no new infra needed |
| **2 — Semantic Depth** ✅ | 1e (Metrics Catalog) + 2j (KB Pattern Enrichment) | Agent understands business KPIs and causal chains |
| **3 — Conversational** ✅ | M9 (Quick Chat + multi-turn history + Chart Engine + Deep Analysis tab) | Analyst-feel experience; session memory; rich inline charts; resizable |
| **5 — Ontology (structural)** ✅ | M12a (entity/relationship extraction — no LLM) | Grain-verified entities, lifecycle states, cardinality joins; ENTITY MODEL in every prompt |
| **6 — Ontology (semantic)** ✅ | M12b (LLM enrichment + ACTION: tokens) | Planner calls actions; business rules enforced automatically |
| **7 — Production Safety** | M6 (Security: Gradient Safety + PII + Audit + Budget) + M7 (Observability) | Enterprise-ready; Langfuse traces |
| **8 — Analytical Depth** | M4 (Prophet forecasting) + M2d (Events Calendar) | "Is this drop unusual *given the trend*?" |
| **9 — LLM-free Path** | M11 (Visual Query Builder) | Deterministic queries; power user UX |
| **10 — Ontology UI** ✅ | M12c (OntologyPanel + metric divergence detection) | Browsable semantic layer; divergent metric flagging |
| **11 — Infra Evolution** ✅ | M3 (ibis + Connector-X + Materializer) | ibis optional backend; connectorx bulk_read; sidecar DuckDB query cache |
| **12 — Provider Flexibility** | M5 (Anthropic backend + prompt caching) | Cloud deployment fallback when Ollama unavailable |
| **13 — Infrastructure polish** ✅ | Plan-then-SQL (49) + Non-blocking event loop (50) + Loading hardening (51) + Stat cards (52) + Schema cache (53) | Clean two-stage planner; zero-blocking API; instant panel renders |
| **14 — BI Layer: Health** | M13a (Metric Targets + Health Scorecard) | Aughor shows process health proactively on open; reactive Q&A → proactive monitoring |
| **15 — BI Layer: Playbook** | M13b (Playbook from KB) | KB causal chains become reusable, retrievable interventions; recommendations stop being hallucinated |
| **16 — BI Layer: Feedback** | M13c (Outcome Tracking) | Recommendations get a success rate; system learns from organisational history |
| **17 — BI Layer: Context** | M13d (Document Ingestion) | SOPs, return policies, strategy docs feed into synthesis; Qdrant infra already ready |
| **18 — BI Layer: Process Map** | M13e (Business Process Visual Mapper) | Swimlane health diagram; click red step → ADA investigation |
| **19 — BI Layer: Causal Twin** | M13f (Causal Graph in Ontology) | ADA waterfalls write causal edges; algorithmic root-cause traversal |
| **20 — Quality Gates** | M10 (Evals — Braintrust) | CI regression testing on verdict quality |

```
History ✅
    └── Prior Analyses RAG (1d) ✅
    └── Evals (M10)

Glossary (1a) ✅
    └── dbt Integration (1b) ✅
            └── Vector Search (1c) ✅
                    └── Prior Analyses RAG (1d) ✅
    └── Metrics Catalog (1e)  ←  parallel; uses glossary table context
            └── Visual Query Builder (M11)

SQL KB (2f) ✅
    └── KB Pattern Enrichment (2j)  ←  enriches existing patterns

Schema Context (1a–1c) ✅
    └── Join Inference + Fingerprinting (2i)  ←  enriches schema string before indexing

plan_and_execute ✅
    └── Error Classification (2h-i)  ←  pre-LLM error hint injection
    └── Dialect Post-processing (2h-ii)  ←  runs before execution (Postgres only)
    └── Column Ambiguity Pre-flight (2h-iii)  ←  post-generation, pre-execution scan

Two-Model Arch (2a) ✅
    └── Checkpointing (2b) ✅
            └── HITL (2c) ✅
    └── Provider Switcher (M5)  ←  builds on 2a abstraction
            └── Observability (M7)  ←  most valuable with real cloud token costs

Direct Query (2e) ✅
    └── Quick Chat (M9) ✅  ←  reuses plan_and_execute; adds session-layer history
            └── Chat Chart Engine (M9-charts) ✅  ←  LLM chart_type selection; 5 chart types; resizable

Global Analytics Rules (32) ✅  ←  independent; editable without restart; split full/chat blocks
Prior Analyses RAG (1d) ✅
    └── Connection-scoped cache ✅  ←  Qdrant FieldCondition filter; connection_id in payload + AgentState
Hypothesis Accordion (33) ✅  ←  builds on query_history + stats SSE data already in place

Query Engine (3a ibis)
    └── SQLMesh (3c)

Security (M6)  ←  independent; land before any multi-tenant deployment
    Gradient Safety (6e) → no clash with SQLGlot structural check; runs as second layer

Column Profiles (prerequisite for M12)  ←  grain_verified, null_rate, distinct_count, is_low_cardinality per column
    └── Ontology Structural (M12a)  ←  entities + relationships + lifecycle states; no LLM
            └── Ontology Semantic (M12b)  ←  LLM enrichment (one batch, cached by fingerprint); action templates
                    └── plan_and_execute ACTION: expansion  ←  business rules auto-enforced
                    └── Ontology UI (M12c)  ←  OntologyPanel + metric divergence detection
                            └── check_consistency  ←  adds formula-level consistency check alongside existing LLM check

Schema Intelligence (2i) ✅  ←  join map + fingerprint feed directly into M12a builder
Glossary (1a) ✅             ←  caveats + filters feed into entity.default_filters in M12a
ER Diagram ✅                ←  Mermaid infra reused (made interactive) in M12c
Metrics Catalog (1e) ✅      ←  metric formulas become OntologyMetric.formula_sql in M12a/12b

Evals (M10)  ←  needs History ✅ + stable Two-Model Arch (2a) ✅

Ontology Semantic (M12b) ✅ + KB Pattern Enrichment (2j) ✅ + ADA waterfall (investigate.py) ✅
    └── M13a: Metric Targets + Health Scorecard  ←  add target/threshold fields to OntologyMetric; scorecard API reads metric formula_sql; ProcessHealthPanel
            └── M13b: Playbook from KB  ←  KB inflation/deflation/causal entries → PlaybookEntry objects; ADA synthesis retrieves instead of hallucinating
                    └── M13c: Outcome Tracking  ←  accept/reject/done per recommendation; success rate updates playbook entries
                            └── M13b v2: ranked retrieval by historical_success_rate

Qdrant (1c) ✅ + Embedder (1c) ✅ + kb_retriever.py ✅
    └── M13d: Document Ingestion  ←  new aughor_documents collection; same upsert/search pattern; {external_context_section} in ADA synthesis

Ontology lifecycle states (M12a) ✅ + Explorer join verification (42) ✅ + OntologyCanvas (@xyflow/react) ✅
    └── M13e: Process Visual Mapper  ←  lifecycle states → swimlane nodes; LAG() transition volumes; drop-off rate health colours
            └── M13d: "Compare to Industry" overlay  ←  depends on uploaded benchmark documents

ADA attribution waterfall (investigate.py) ✅ + OntologyGraph (M12b) ✅ + Playbook (M13b)
    └── M13f: Causal Graph  ←  extract causal edges from ADA waterfalls after each investigation; BFS backward traversal root cause → playbook action
            └── OntologyCanvas: dashed causal arrows alongside solid structural edges
```

---

## Stack Reference

| Layer | Choice | Why |
|---|---|---|
| Agent framework | **LangGraph** | Cyclic stateful graph for investigative loops |
| LLM — SQL/reasoning | **qwen2.5-coder:32b** via Ollama | Best SQL reasoning, fully local; fallback: 14b |
| LLM — narrative | **llama3.3:70b** via Ollama | Prose quality at Q4 quantization, fully local |
| LLM — cloud fallback | **Claude Sonnet 4.6** (Anthropic) | With prompt caching on schema context |
| Structured output | **instructor + Pydantic** | Eliminates hallucination in tool calls |
| SQL safety | **SQLGlot** | Parse + transpile; SELECT-only allowlist |
| Query abstraction | **ibis** (roadmap) | Backend-agnostic; same code → DuckDB/BigQuery/Snowflake |
| Query engine | **DuckDB** | In-process OLAP, Arrow-native, zero-latency |
| Bulk reads | **Connector-X** (roadmap) | Fast Arrow reads from Postgres/Snowflake |
| Materialization | **QueryMaterializer** (sidecar DuckDB) | 24-hour soft TTL; upsert cache; `hermes_mat.duckdb`; SQLMesh deferred |
| Semantic layer | **dbt** | Single source of truth for metric definitions |
| Ontology layer | **Aughor Ontology (M12)** | Typed entities, verified relationships, actionable SQL templates with business-rule enforcement; built from schema + glossary + column profiles |
| Schema search | **Qdrant + nomic-embed-text** | Self-hosted, fast vector search |
| DataFrames | **Polars** | 10–100x faster than pandas on aggregations |
| Stats | **scipy + statsmodels + Prophet** | Anomaly detection, STL decomp, forecasting |
| PII protection | **Microsoft Presidio** (roadmap) | Scan + redact before LLM sees query results |
| Credentials | **Fernet SQLite → Vault/Doppler** | MVP → production credential management |
| Scheduling | **Prefect** | Proactive monitoring flows, retry handling |
| API | **FastAPI + SSE** | Async streaming of agent node events |
| Frontend | **Next.js 15 + shadcn/ui** | App Router, RSC, accessible primitives |
| KPI charts | **Tremor** (roadmap) | Purpose-built data product components |
| Investigative charts | **Observable Plot** (roadmap) | D3 power, declarative API for time series |
| Streaming | **Vercel AI SDK** (consider) | Native SSE/RSC integration; alternative to custom hook |
| Observability | **Langfuse + OpenTelemetry** | LLM traces + distributed tracing per investigation |
| Evals | **Braintrust** | Regression testing for agent verdict quality |

---

## Current focus

**Shipped:** M1 (Semantic Layer), M2a–2c + 2e–2j (Agent hardening, HITL, Direct Query, Routing v2, SQL KB, Error Classification, Schema Intelligence, KB Enrichment), M8 (Frontend Charts, Chart Intelligence, Report UX), M9 (Quick Chat + Chart Engine + Deep Analysis tab), 1e (Metrics Catalog), ER Diagram, Rich Schema Card UI, Global Analytics Rules (32), Hypothesis Expanded Accordion (33), Connection-scoped semantic cache, Paren-aware ROUND rewriter, Schema parser dedup, Timeout 600 s, UI color pass, **M12 Background Schema Explorer + Business Ontology + Domain Intelligence + SqlWriter (48 features total)**, Plan-then-SQL Separation (49), Non-blocking event loop (50), Loading state hardening (51), Home stat card navigation (52), Schema cache backend + frontend (53), **M13a–13e: Metric Targets + Health Scorecard (54), Structured Playbook from KB (55), Outcome Tracking & Feedback Loop (56), Document Ingestion (57), Process Visual Mapper (58)**

**Sprint 12 — Background Explorer + Domain Intelligence ✅ SHIPPED:**
- `aughor/explorer/agent.py` — `SchemaExplorer` with 8 phases: null meanings (3), join verification (4), lifecycle mapping (5), distribution profiling (6), cross-table patterns (7), domain intel loop (8)
- `aughor/explorer/episodes.py` — `EpisodeCollector` JSONL append writer; `(think, sql, observation)` training tuples
- `aughor/explorer/store.py` — JSON state persistence; `extend_domain_budget()` returns new cap
- `aughor/explorer/models.py` — `ExplorationPhase` enum, `ExplorationStatus`
- `aughor/sql/writer.py` — `SqlWriter` + `FixResult`; centralised SQL generation and self-correction for all callers (chat, domain intel, retry endpoint); alias resolution + DuckDB candidate bindings extraction; "NEVER substitute SUM(0)" hardening
- `aughor/sql/__init__.py` — re-exports
- Per-phase rate limiting: schema phases at full speed, intel phase at 1 query / 5 s
- Domain intelligence: adaptive curiosity loop per domain, coverage angles, novelty decay stop, open-ended continuation after all angles covered, budget extension patched live into running explorer
- `web/components/ActivityLog.tsx` — real-time episode feed; stop/resume/restart surviving tab switches
- `web/components/DomainIntelPanel.tsx` — per-domain findings, budget bar, angle chips, "+5 queries"
- `web/components/ExplorationBadge.tsx` — live phase badge in sidebar
- `web/components/OntologyCanvas.tsx` — interactive ontology graph
- `aughor/api.py` — full REST surface: stop/resume/restart/episodes/domains/extend; `_start_explorers()` only resumes connections with existing state

**Current — Sprint 5 — Ontology Structural (M12a) ✅ SHIPPED:**
- Column profiles already fully built (`hermes/tools/profiler.py`, `profile_cache.py`) — prerequisite was done
- `hermes/ontology/models.py` — `OntologyEntity`, `OntologyRelationship`, `OntologyMetric`, `OntologyAction`, `OntologyGraph`
- `hermes/ontology/builder.py` — `extract_structural_ontology()` + `render_ontology_annotations()` — no LLM
- `hermes/ontology/store.py` — JSON cache at `data/ontology_cache.json`, keyed by `{connection_id}:{fingerprint}`
- `hermes/db/connection.py` — both DuckDB + Postgres connections build ontology during `get_schema()`; `get_ontology()` method on base class
- `hermes/api.py` — `GET /ontology`, `/ontology/entities`, `/ontology/relationships`, `/ontology/actions`, `/ontology/metrics`, `PUT /ontology/entities/{id}`
- Schema context now includes `ENTITY MODEL` block: grain verification, lifecycle states, terminal states, active_filter rules, ACTION names

**Sprint 6 — Ontology Semantic (M12b ✅ SHIPPED):**
- `hermes/ontology/enricher.py` — `enrich_ontology_semantics()`: one LLM batch call populating relationship verbs, entity descriptions, compute/traverse actions, canonical metric SQL; cached via `graph.enriched = True`; triggered lazily in `get_schema()`, best-effort
- `hermes/ontology/actions.py` — `expand_actions()`: substitutes `ACTION:name()` tokens with full SQL templates before execution; `build_actions_prompt_section()`: injects available actions into `PLAN_QUERIES_PROMPT`
- `hermes/agent/prompts_ontology.py` — `ENRICH_ONTOLOGY_PROMPT` for the enrichment LLM call
- `hermes/agent/prompts.py` — `{ontology_actions_section}` placeholder added to `PLAN_QUERIES_PROMPT`
- `hermes/agent/nodes.py` — `plan_and_execute` now builds the actions section, passes it to the planner, and expands `ACTION:` tokens before SQL execution
- `hermes/db/connection.py` — both DuckDB and Postgres `get_schema()` trigger enrichment after structural build when `graph.enriched == False`

**Sprint 7 — M12c ✅ SHIPPED (Ontology UI + Metric Divergence):**
- `hermes/ontology/divergence.py` — `check_metric_consistency()`: deterministic heuristic check comparing hypothesis SQL against canonical metric formulas; returns warning strings injected into unresolved_tensions
- `hermes/ontology/store.py` — `load_latest_ontology()` + `patch_action()` added
- `hermes/agent/nodes.py` — metric divergence wired into `synthesize_report` after LLM consistency check
- `hermes/api.py` — `PUT /ontology/actions/{action_id}` override endpoint
- `web/components/EntityCard.tsx` — per-entity detail: grain badge, inline-editable description, lifecycle state chain, active filter rule, related actions + metrics
- `web/components/OntologyPanel.tsx` — four-tab panel (Entities/Relationships/Actions/Metrics); entity list + detail split; inline action description editing; enrichment status badge
- `web/app/page.tsx` — Ontology nav tab with NodeIcon; breadcrumb + tab content wired
- `web/lib/api.ts` — full ontology TypeScript types + `getOntology()`, `patchOntologyEntity()`, `patchOntologyAction()` added

**Sprint 11 — M3 Query Engine Evolution ✅ SHIPPED:**
- `pyproject.toml` — optional `warehouse` dep group: `ibis-framework[duckdb,postgres]>=9.0.0`, `connectorx>=0.3.3`; install with `uv pip install -e ".[warehouse]"`
- `hermes/db/connection.py` — `DatabaseConnection.ibis_connection()` base stub (returns None); `DuckDBConnection.ibis_connection()` → `ibis.duckdb.connect(path, read_only=True)`; `PostgresConnection.ibis_connection()` → `ibis.connect(dsn)`; `PostgresConnection.bulk_read(hypothesis_id, sql)` — connectorx Arrow path, graceful fallback to `execute()` when connectorx not installed
- `hermes/tools/materializer.py` — NEW: `QueryMaterializer` backed by sidecar `data/hermes_mat.duckdb`; `get(connection_id, sql, hypothesis_id) → Optional[QueryResult]`; `put(connection_id, result)`; `invalidate_connection(connection_id)`; `purge_expired()`; 24-hour soft TTL; upsert via `ON CONFLICT`; errors never cached
- `hermes/tools/executor.py` — `ibis_execute(ibis_backend, hypothesis_id, sql) → QueryResult`; uses `backend.sql(sql).limit(MAX_ROWS).execute()`; pandas NaT → "NULL"; graceful error `QueryResult` on any exception

**M2e Direct Query Mode UX ✅ SHIPPED (polish pass):**
- `web/components/ChatMessage.tsx` — `defaultStatusText()` helper: once `queryMode === "direct"` arrives via SSE the loading text switches from "Investigating…" to "Running query…"; "Exploring…" for explore mode; `showStreamingBody` gate now also excludes `queryMode === "direct"` so ADA phase stream never appears for direct-routed queries

**Recent (Sprint 13 — Infrastructure polish ✅ SHIPPED):**
- Plan-then-SQL separation (49): clean two-stage graph — `plan_queries` reasons about WHAT to measure, `execute_planned_queries` writes dialect-specific SQL per intent
- Non-blocking event loop (50): `_aiter_sync` wraps LangGraph's sync stream via thread pool; History, Ontology, Exploration APIs no longer hang during active investigations
- Loading state hardening (51): all data-panel components render immediately with `loading=false` init + 8s `AbortController` timeout; no more "Loading…" dead states when backend is busy
- Home stat card navigation (52): every stat card on the home page now deep-links to the relevant tab (Schema / Ontology / Intelligence / Activity); Insights count uses real domain intelligence count
- Schema cache — backend + frontend (53): eliminates 3–6 redundant `get_schema()` calls per panel interaction; backend 5-min TTL cache + frontend React Context share one fetch across SchemaPanel, CatalogPanel, and DataTab

**Sprint 14 — M13a: Metric Targets & Health Scorecard ✅ SHIPPED:**
- `OntologyMetric` + `MetricDefinition` extended with `target_value`, `warning_threshold`, `critical_threshold`, `target_period`, `benchmark_source`
- `GET /connections/{conn_id}/health-scorecard` executes each metric's `sql` and returns green/yellow/red + variance
- `ProcessHealthPanel.tsx` — health grid on home page; red/yellow cards show "Investigate →" button; sorted by urgency
- `ADA_SYNTHESIZE_PROMPT` gains `{metric_targets_section}`; synthesis prioritises controllable root causes above threshold
- `MetricsPanel.tsx` — Health Scorecard section in form with target/threshold/period/benchmark fields

**Sprint 15 — M13b: Structured Playbook from KB ✅ SHIPPED:**
- `aughor/playbook/` — `models.py`, `store.py`, `builder.py`, `retriever.py`
- `seed_from_kb()` converts 272 draft `PlaybookEntry` objects from 84 Tier-2 KB causal entries on first startup; `force=True` replaces KB entries while preserving user-created ones
- ADA synthesis: `{playbook_section}` injected into `ADA_SYNTHESIZE_PROMPT`; retriever matches investigation labels against `trigger_metric` + tags; LLM instructed to prefer playbook entries and flag unmatched ones "[unproven — consider adding to playbook]"
- `GET/POST/PUT/DELETE /playbook` + `POST /playbook/seed` API routes
- `web/components/PlaybookPanel.tsx` — browse/filter/promote/deprecate entries; "Re-seed from KB" button; accessible via Data → Playbook tab

**Sprint 16 — M13c: Outcome Tracking ✅ SHIPPED:**
- `aughor/playbook/outcomes.py` — `RecOutcome` model; `log_outcome()` upserts to `data/recommendation_outcomes.json`; `update_playbook_success_rates()` recomputes `historical_success_rate` and auto-promotes drafts with ≥2 outcomes + ≥50% success to active
- `POST /investigations/{inv_id}/recommendations/{rec_index}/outcome` + `GET /investigations/{inv_id}/outcomes` API routes; triggers `update_playbook_success_rates()` on terminal status
- `ReportView.tsx` — per-recommendation `RecommendationCard` with "Mark" dropdown (accepted / implemented / verified / rejected / dismissed); existing outcomes loaded on mount; status chip replaces button when actioned
- `web/components/RecommendationInbox.tsx` — cross-investigation inbox; loads recent complete investigations, aggregates pending recommendations, "View →" deep-links to chat; pending/all filter toggle
- Data panel "Inbox" tab wires inbox into the main layout

**Sprint 17 — M13d: Document Ingestion ✅ SHIPPED:**
- `aughor/knowledge/documents.py` — `extract_text()` for PDF/Word/Markdown/TXT; paragraph-aware chunker (~400 tokens / ~200 token overlap); `chunk_file()` returns `DocumentChunk` objects
- `aughor/knowledge/indexer.py` — `index_file()` embeds chunks into `aughor_documents` Qdrant collection; `search_documents()` semantic retrieval; `build_external_context_section()` for prompt injection; `data/documents.json` metadata registry; `delete_document()` removes both registry + Qdrant chunks
- `ADA_SYNTHESIZE_PROMPT` gains `{external_context_section}`; `_ada_synthesize()` retrieves top-4 document snippets against the investigation question and injects them before synthesis
- `POST /documents/upload` (multipart), `GET /documents`, `DELETE /documents/{doc_id}`, `POST /documents/search` API routes
- `web/components/DocumentUploader.tsx` — drag-and-drop zone, multi-file upload, per-doc chunk count + age, remove button; accessible via Data → Documents tab
- **New deps:** `python-multipart>=0.0.9` (core); `PyPDF2>=3.0.0`, `python-docx>=1.0.0` (optional `[docs]` group)

**Sprint 18 — M13e: Process Visual Mapper ✅ SHIPPED:**
- `aughor/process/models.py` — `ProcessNode`, `ProcessEdge`, `ProcessMap` Pydantic models
- `aughor/process/mapper.py` — `build_process_map()`: GROUP BY for node counts; LAG() SQL over `created_at_col` + `identity_key` for transition edges; graceful fallback to nodes-only when no temporal column; terminal state detection; ontology-order-preserving node sort
- `GET /connections/{conn_id}/process-map/{entity_id}` API endpoint
- `web/components/ProcessMapper.tsx` — custom SVG swimlane (no extra dep); nodes coloured by minimum outbound conversion rate (green ≥80% / amber ≥50% / red <50%); edge arcs with stroke-width scaled to volume + rate % labels; SVG-native tooltip; "Investigate →" click per node
- Wired into `EntityDetailDrawer` in `OntologyPanel.tsx` as a new "Map" tab (only shown for entities with `has_lifecycle: true`)

**Sprint 19 — M13f: Causal Graph:**
- `CausalEdge` model in `ontology/models.py`; appended to OntologyGraph after each ADA investigation
- Backward traversal in `playbook/retriever.py`; dashed causal arrows in OntologyCanvas

**After M13:** M6 + M7 (Security + Observability) → M4 (Prophet) + M2d (Events Calendar) → M11 (Visual Builder) → M10 (Evals)

**Deferred:** M5 Provider Switcher (Anthropic backend) — moved to near-end; M6 Security must land before any multi-tenant or enterprise deployment
