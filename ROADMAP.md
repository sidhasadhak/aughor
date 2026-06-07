# Aughor — Product Roadmap

**Product:** Aughor — Autonomous Analyst  
**Repo:** https://github.com/sidhasadhak/aughor  
**Stack snapshot:** LangGraph · Ollama / Groq / Together / Anthropic (configurable via `AUGHOR_BACKEND`) · FastAPI SSE · Next.js 16 Turbopack (App Router) · DuckDB + PostgreSQL · SQLGlot · scipy/statsmodels · ChromaDB · uv

---

## 🧩 Latest — Reusable Component Architecture + Exhaustive Test Pass

The same qualified-vs-bare table-name bug was fixed **three** times because there was no shared primitive; the UI carried three chart implementations, six copies of cell-formatting, and three colour palettes. This program rebuilt ERD, Ontology, Charts, and Tables as **single-source-of-truth components on canonical contracts**, backed by shared primitives — so a fix lands once and propagates everywhere — then verified every feature, endpoint, process, and vector collection end-to-end. **~1,500 lines of duplication removed · 0 regressions · 5 bugs fixed.**

| Phase | What shipped | Key files |
|---|---|---|
| **1 — Canonical table-name layer** | One primitive (`bare`/`leaf`/`same_table`/`resolve_in`/`TableRef`) is the only place table names are split, compared, or qualified — backend *and* frontend; 15 backend sites + the Catalog ERD filter migrated; the qualified-vs-bare bug class can't recur | `aughor/tools/table_names.py`, `web/lib/tableName.ts`, `tests/unit/test_table_names.py` |
| **2 — Frontend primitives** | `format.ts` folds 8 large-number + 5 percent + 3 label + 2 date impls into one home; `palette.ts` consolidates 3 palettes; 17 components migrated | `web/lib/{format,palette,tableName}.ts` |
| **3 — One of each component** | Single `<Chart>` engine (16 view types) extracted from a 2,200-line `ChatMessage`; `InvestigationChart` → a thin toggle-wrapper delegating to it; `<ERDiagram>` / `<OntologyGraph>` / `<DataTable>` on canonical contracts | `web/components/{Chart,InvestigationChart,ERDiagram,OntologyCanvas,AugTable}.tsx` |
| **4 — Exhaustive test pass** | `smoke.py` (every GET endpoint + 8 Qdrant collections, baseline-diffed) + `flows.py` (write/background flows); 16 UI surfaces walked (0 console errors); a Deep-Analysis investigation driven to completion; `TEST_REPORT.md` maps all 76 features | `scripts/{smoke,flows}.py`, `TEST_REPORT.md` |
| **Bugs fixed (0 regressions)** | `/ontology/skills`+`/autonomy` 500 (inert `aughor.memory` package), `/canvases/{id}/suggestions` 500 (sync→async `await`), `/monitors` 500→422, `/ontology/rebuild` 500→422, smoke-oracle self-comparison | `aughor/memory/`, `aughor/routers/{canvas,monitors,ontology}.py`, `scripts/smoke.py` |

**Next:** a subtle **motion / animation pass** — tasteful transitions throughout the platform.

---

## 🚀 Latest — `genie-revamp` (Grounded NL2SQL + Eval Suite + Trusted Templates)

A focused effort to make NL2SQL **SOTA and plug-and-play** — correct on real, unseen schemas — measured against real benchmarks at every step.

| Area | What shipped | Key files |
|---|---|---|
| **Grounded generation** | De-hardwired, schema-agnostic schema-linker (safety floor, never empty); MindsDB-style Data Catalog (columns + samples + FK joins); FK & star-schema join grounding (prefixed/fused/surrogate `_sk` keys, fact→dimension routing, FK-neighbour expansion, role-played date dims); temporal/dimension grounding for surrogate date/time keys | `tools/schema_linker.py`, `tools/data_catalog.py`, `tools/schema.py`, `routers/investigations.py` |
| **Dialect & retry** | SQLGlot dialect-aware validation; DuckDB-specific fix hints (`to_char`→strftime, `date_part` on date subtraction) feeding the self-correcting retry | `sql/writer.py`, `db/connection.py` |
| **Trusted query templates** | Databricks-style verified assets: curated SQL patterns injected authoritatively; fixes reasoning gaps (multi-fact **fan-out**, grain) that prompt rules can't; `trusted` SSE provenance | `semantic/trusted_queries.py` |
| **Eval suite** | Full-pipeline harness + real-scale TPC-H (5/7) / TPC-DS (4/5, via temporal lever) / ClickBench (10/10) harnesses (DuckDB-generated, execution-validated) + reference-free real-DB harness (self-consistency + cross-model LLM-judge) | `evals/run_{tpch,tpcds,clickbench,golden,realdb}.py` |
| **Bug fixes found by the eval** | Spurious GROUP-BY rewriter (semantic_validator false positives); cross-connection metric leak (schema-aware filtering); measure-based scorer false-negatives | `tools/semantic_validator.py`, `semantic/metrics.py`, `evals/run_tpch.py` |
| **Platform hardening** | Connection pooling (reuse, TTL, health, opt-out); Google Sheets connector (gviz CSV + cache); Anthropic (Opus) fallback on primary-backend failure; explorer auto-start on new connections; light-mode fix; audit-log noise reduction; batched post-answer LLM calls | `db/pool.py`, `connectors/api/gsheets.py`, `llm/provider.py`, `routers/_shared.py` |
| **Self-validating semantic layer (M24c)** | Ontology validator executes every metric / computed-property / object-set against the live DB (`verified` gate); verified-only injection of object sets + computed properties + unified metric formulas into the generator; catches the $3T product-of-aggregates + hallucinated columns. Connection-scoped no-op elsewhere (ClickBench held 10/10) | `ontology/validator.py`, `ontology/semantic_block.py`, `semantic/metrics.py`, `ontology/models.py` |
| **Fan-out guard (M24d, Cube borrow)** | Conservative **zero-false-positive** detector (sqlglot scope + FK-root cardinality, validated on 121 official TPC-H/TPC-DS queries) → directed pre-aggregate rewrite, adopted only if it re-executes clean. The principled, schema-wide replacement for the trusted-template fan-out band-aid (Cube symmetric aggregates) | `sql/fanout.py`, `routers/investigations.py` |
| **Robust enrichment** | Flat computed-property list + tolerant JSON coercion + temp 0 — fixes the local-model structured-output collapse that intermittently dropped *all* computed properties | `ontology/enricher.py`, `agent/prompts_ontology.py` |
| **Runtime / UI repairs** | Ontology endpoints (read cached graph, not the fast `get_schema`); briefing int-citation coercion (was hanging to timeout); ontology ERD qualified/bare join fix (**0 → 38 relationships**); Workspace multi-schema `search_path` (**~1875 explorer errors → 0**); Catalog ERD bare/qualified name match (**0 → 6 tables**) | `routers/ontology.py`, `knowledge/briefing.py`, `ontology/builder.py`, `connectors/file/local_upload.py`, `web/components/CatalogScreen.tsx` |

**Key insight:** model-invariant failures (qwen vs kimi fail the same queries) → the ceiling is *grounding*, not the model. Fixes target context, and the eval proves each lever's lift. The semantic layer extends this: knowledge is computed once, *validated against the live DB*, and injected verified — borrowing Cube.dev's declarative-layer + symmetric-aggregate model and MindsDB's grounding patterns.

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
| Catalog 3-panel + Sample Data tab (60) | `web/components/CatalogScreen.tsx`, `web/lib/api.ts` | Replaced `CatalogPanel.tsx` with full Databricks-style 3-panel layout: connection sidebar → table list → detail panel; detail panel has Columns tab + Sample tab; `SampleGrid` lazy-loads up to 100 rows on tab click with spinner, null display ("—"), 32-char truncation, row-count footer; `sampleTable(connId, table, limit)` in `api.ts` → `GET /connections/{conn_id}/tables/{table}/sample`; `CatalogScreen` self-fetches connections on mount so panel never shows empty when parent load was slow |
| Phase 8 ontology gate (61) | `aughor/explorer/agent.py` | Prevents the race condition where phases 3–7 finish before the ontology is ready — Phase 8 (domain intelligence) found `load_latest_ontology()` returning None and silently skipped; fix: explicit `self._conn.get_schema()` call before Phase 8 if ontology absent; missing-ontology log upgraded from `info` to `warning`; manual recovery still available via `POST /exploration/{conn_id}/domains/{domain}/extend` |
| Connection persistence hardening (62) | `aughor/.env`, `aughor/.gitignore`, `aughor/api.py` | Three-layer fix for connections being irreversibly lost after restart: (1) `AUGHOR_SECRET_KEY` pinned in `.env` — Fernet key survives `git clean` or file deletion; (2) `data/.aughor_key` added to `.gitignore`; (3) startup `_validate_connections()` event decrypts every DSN at boot so misconfiguration surfaces immediately; `allow_origins` changed from `["http://localhost:3000"]` → `["*"]` to eliminate silent CORS failures |
| Org-Level Ontology Board + `table=entity` gate fix (68, Sprint 52) | `web/components/OntologyCanvas.tsx`, `OntologyOrgCanvas.tsx`, `OntologyPanel.tsx`, `web/lib/useWheelZoom.ts`, `aughor/ontology/builder.py` | Zoomable org board: one box per connection, one sub-box per schema, each holding the real entity cluster (nodes+edges) via extracted `EntityCluster` + `measureCluster`; shared trackpad pinch/⌘-wheel zoom hook. Builder no longer drops PK-less tables — every profiled table is an entity (`grain_verified` becomes a quality flag); beautycommerce went 8→20 entities, 3→52 relationships. Follow-up: profiler still misses some real PKs (e.g. `invoices.order_id`). |
| Canvas creation popup + Canvas-scoped Configure (69, Sprint 53) | `web/components/CanvasCreator.tsx`, `ConfigurePanel.tsx`, `CanvasWorkspace.tsx`, `web/lib/api.ts`, `aughor/routers/canvas.py` | Databricks "Connect your data"-style single-screen create flow: breadcrumb catalog → connection → multi-select table list with "All tables" pseudo-row, removable "Selected:" chips, no name step. Name + one-line description are LLM-inferred from the selected tables' schema via new `POST /canvases/suggest-name` (graceful fallback to connection name, never blocks create). Configure slide-over is now Canvas-scoped, not connection-scoped: About tab edits Canvas name + description (`updateCanvas`) and shows the connection/schema/tables scope; Data tab lists only the Canvas's scoped tables (lenient leaf-name match, empty scope = all); Instructions are per-Canvas via new `GET/PUT /canvases/{id}/instructions` (`data/canvas_instructions.json`) so two Canvases on one connection keep distinct business rules. Also hardened `createCanvas`/`updateCanvas` to send the backend's flat body and parse FastAPI array-shaped `detail` errors (fixes the "[object Object]" create failure). |
| Add Data as full page + new connectors + Workspace uploads (70, Sprint 54) | `web/components/AddDataPanel.tsx`, `CatalogScreen.tsx`, `BrandLogos.tsx`, `aughor/connectors/warehouse/{motherduck,exasol}.py`, `aughor/connectors/api/gsheets.py`, `connectors/file/local_upload.py`, `connectors/registry.py`, `aughor/db/registry.py`, `routers/{connections,catalog,system}.py` | "Add Data" is now a full page (not a slide-in). New connectors: **MotherDuck** (`md:` cloud DuckDB), **Exasol** (pyexasol), **Google Sheets** (CSV-export → DuckDB) with real inline-SVG brand marks. "Create or modify table" is a real **file-upload → Workspace** feature: the built-in **Workspace** (`local_upload`, in-memory DuckDB) gets a 3-phase **Analyze → Configure → Commit** import — `POST /files/analyze` (DESCRIBE + 20-row preview + per-column type-mismatch suggestions via `try_cast`), a review UI (editable table name, **multi-schema** picker + create-schema, per-column type overrides, conflict warning), then typed ingest (`TRY_CAST`) persisted with sidecar `*.import.json`. New per-table `GET /tables/{t}/columns` endpoint makes the Catalog Overview column list as reliable as Sample Data. |
| Workspace = single merged catalog (71, Sprint 54) | `aughor/db/registry.py`, `connectors/file/local_upload.py`, `routers/catalog.py`, `web/components/CatalogScreen.tsx` | The separate read-only "Sample Catalog" is folded into one **Workspace**: the `local_upload` connector materializes the sample `ecommerce` tables read-only (ATTACH seed → CREATE TABLE) alongside user uploads, so `ecommerce.customers` still resolves with a 2-part name (ontology/exploration unchanged). Catalog tree now a single "Catalogs" section; `local_upload` uses the DuckDB introspection path (fixes uploads not appearing). |
| SqlResultTable column-width cap (72, Sprint 54) | `web/components/AugTable.tsx` | Each cell caps at a `maxColWidth` (default 320px) with ellipsis + hover tooltip, so a long-text column no longer pushes the rest off-screen (Catalog Sample Data, chat results, exploration reports). |
| Remove auto-generated Canvases (73, Sprint 55) | `aughor/canvas/store.py`, `aughor/api.py`, `routers/canvas.py`, `web/components/CanvasBrowser.tsx` | Per-connection "legacy" Canvases are no longer created — `migrate_connections_to_legacy_canvases()` is a no-op; new `delete_legacy_canvases()` purges existing ones on startup; the create-canvas endpoint no longer fans out; the "Auto-generated" filter chip is gone. |
| Agentic investigation polish (74, Sprint 55) | `aughor/agent/{state,explore,investigate,prompts_explore}.py`, `web/components/{ThinkingTrace,ChatMessage,ChatPanel,InvestigationChart,VegaChart,ExplorationReport}.tsx`, `web/lib/useChat.ts` | Five upgrades: (1) **Stage coherence** — a shared **analysis ledger** (canonical entity identifiers + metric SQL, decided once and injected into every plan/synthesis prompt) so figures stop drifting between stages (e.g. `customer_id` per-order hash vs `customer_unique_id`); (2) **inline streaming Agent trace** that auto-collapses on completion (retires the right sidebar); (3) **real chart axis labels** (bar charts titled with actual column names, not `label`/`value`); (4) **calmer unified report** — one type scale, neutral palette, charts/tables expanded upfront, SQL the only collapsed detail, Conclusion+narrative merged into Summary; (5) **elapsed time** ("Completed in 12.4s") for every mode incl. Quick. |
| Canvas Data add/remove tables + history item removal (75, Sprint 55) | `web/components/ConfigurePanel.tsx`, `CanvasWorkspace.tsx`, `web/lib/api.ts`, `aughor/db/history.py` | Configure → Data subtab is now a table **manager** — checkbox per table toggles Canvas scope membership with auto-save (empty scope = all); Canvas history rows get a hover trash button (`deleteInvestigation` extended to match `id` OR `session_id` so a whole chat session removes cleanly). |
| History persistence + Canvas-scoped history (76, Sprint 56) | `web/components/CanvasWorkspace.tsx`, `aughor/routers/canvas.py`, `aughor/db/history.py`, `aughor/routers/investigations.py`, `aughor/api.py` | Fixed historical agentic investigations rendering **blank** in a Canvas (the `HistoryDetailPanel` mount was a non-flex block, collapsing its `position:absolute` report to 0px). Canvas history is now scoped strictly by **`canvas_id`** (chat turns persist `canvas_id` end-to-end) and hides report-less items (complete-only). Startup `sweep_stale_running()` marks orphaned `running` investigations as `failed`. |
| Canvas list sort + Recently used + Data Canvas rename (77, Sprint 56) | `aughor/routers/canvas.py`, `aughor/db/history.py`, `web/components/CanvasBrowser.tsx`, `web/lib/api.ts`, plus UI label pass | `/canvases` enriched with `last_activity` (`last_activity_by_canvas()`); browser defaults to **"Latest investigation"** sort and adds a **"Recently used"** strip (top 5 by activity). User-facing **"Canvas" → "Data Canvas"** across nav, browser, workspace, command palette, and Configure (routes/types/ids unchanged). |

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

## Milestone 7 — Observability ✅ SHIPPED (Sprint 40)
**Goal:** Full LLM trace per investigation in Langfuse; OpenTelemetry spans for timing across all nodes.

**Shipped:**
- `aughor/telemetry.py` *(new)* — Langfuse client + OTel tracer singletons; lazy init from env vars; `new_trace()`, `span()` context manager, `log_generation()`, `end_trace()`, `node_span()` decorator factory; all functions strict no-ops when unconfigured
- `aughor/agent/state.py` — `trace_id: str` added to `AgentState` TypedDict
- `aughor/agent/nodes.py` — `@node_span` on 6 generic investigation nodes: `route_question`, `decompose`, `plan_queries`, `execute_planned_queries`, `score_evidence`, `synthesize_report`
- `aughor/agent/investigate.py` — `@node_span` on all 6 ADA phase nodes: `ada_intake`, `ada_baseline`, `ada_decompose`, `ada_dimensional`, `ada_behavioral`, `ada_synthesize`
- `aughor/routers/investigations.py` — `new_trace()` called before `start` SSE; `trace_id` in start event payload and `initial_state`; `end_trace()` in `finally` block
- `pyproject.toml` — `observability` optional dep group: `langfuse>=2.0.0`, `opentelemetry-sdk>=1.24.0`, `opentelemetry-exporter-otlp>=1.24.0`
- `tests/unit/test_telemetry.py` *(new)* — 19 unit tests: no-op paths, decorator correctness, metadata extraction, exception propagation, OTel attr types, SSE format contract

**Activation:** set `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` (and optionally `OTEL_EXPORTER_OTLP_ENDPOINT`), then `pip install "aughor[observability]"`.

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

## Milestone 14 — Multi-Source Connector Platform

**Goal:** Expand Aughor from a single-database analyst into a multi-system intelligence hub. Connect every data source the business actually uses — cloud warehouses, S3 data lakes, REST APIs, internal wikis — and enable cross-source SQL JOINs through a DuckDB federation layer. This is what turns Aughor from a "one database" tool into a "your entire data infrastructure" tool.

**Strategic rationale:** The mid-market segment Aughor targets runs on 3–5 data systems simultaneously (Postgres + S3 + Salesforce + Snowflake is a common stack). Aughor's investigative quality is currently bounded by what's in a single connected database. Federation removes that ceiling. This is Palantir's MMDP — built on open-source DuckDB.

**Architecture principle:** The federation namespace model must be designed in Phase 14a (as part of the connector framework) even though the federation layer ships in Phase 14d. Building warehouse + file connectors without this upfront design means retrofitting namespacing later — significantly harder. Design the query router at the start; populate it connector by connector.

**Connector taxonomy:**

| Category | Examples | Query pattern | Pattern |
|---|---|---|---|
| **Warehouse** | BigQuery, Snowflake, Azure SQL, MySQL | Direct SQL | Extend `DatabaseConnection` ABC |
| **File/Object** | S3, Azure Blob, local CSV/Parquet/Excel | Materialize → DuckDB | `read_parquet()` / `read_csv_auto()` views |
| **API/CRM** | Salesforce, HubSpot, Stripe | REST sync → materialize | Incremental sync → DuckDB mirror |
| **Knowledge** | Confluence, Notion | Text extraction → embed | Extends existing M13d doc pipeline |

---

### Phase 14a — Connector Framework (Week 1)

**What:** Unified registry-driven connector factory. All future connectors implement a shared ABC; existing DuckDB and Postgres connections are migrated into it. The federation namespace model is defined here — even though federation ships in 14d.

**Package structure:**
```
aughor/connectors/
├── __init__.py
├── base.py          # Connector ABC — extends DatabaseConnection with connector_category + namespace
├── registry.py      # Maps "bigquery" → BigQueryConnector, "s3" → S3Connector
├── warehouse/       # SQL-speaking cloud warehouses
├── file/            # S3, Azure Blob, local upload
├── api/             # Salesforce, HubSpot, Stripe
└── knowledge/       # Confluence, Notion (feeds document pipeline)
```

**`base.py`** — one new property on the existing ABC:
```python
@property
@abstractmethod
def connector_category(self) -> Literal["warehouse", "file", "api", "knowledge"]: ...

@property
def namespace(self) -> str:
    """Short prefix used to qualify tables in federated queries."""
    return self.connection_id
```

**Namespace model (critical for federation):** Each connector gets a `namespace` prefix. All tables in federated contexts are qualified:
```
samples.ecommerce.orders           — built-in sample catalog
mywarehouse.public.customers       — connected Postgres
bigquery_prod.analytics.events     — BigQuery
s3_marketing.events                — S3 Parquet materialized into DuckDB
salesforce_sync.opportunity        — Salesforce REST sync
```

**Files to create/modify:**
- `aughor/connectors/__init__.py`, `base.py`, `registry.py`
- `aughor/db/registry.py` — `register_connector_type()` routes type string through `connectors/registry.py`
- `aughor/api.py` — `POST /connections` extended with type-routing through connector registry
- `web/components/ConnectionsPanel.tsx` — dropdown extended with all registered connector types; per-type field config (project ID for BigQuery, account for Snowflake, bucket for S3, etc.)

**New deps:** none (framework only; deps added per-connector in subsequent phases)
**Dependency on:** Existing `DatabaseConnection` ABC ✅, connection registry ✅

---

### Phase 14b — Warehouse Connectors (Week 1–2)

**What:** BigQuery, Snowflake, MySQL, Azure SQL — all extend the existing Postgres pattern. Same `execute()` / `get_schema()` / `test()` interface; differ only in auth, schema introspection SQL, and dialect.

**Priority order by demand × effort:**

| Connector | Effort | Auth | Schema source |
|---|---|---|---|
| **BigQuery** | 2 days | Service account JSON / ADC | `INFORMATION_SCHEMA.COLUMNS` per dataset |
| **Snowflake** | 2 days | Account identifier + user/pass or key-pair | `INFORMATION_SCHEMA.COLUMNS` |
| **MySQL / MariaDB** | 1 day | DSN string | `information_schema.columns` |
| **Azure SQL / Synapse** | 2 days | ODBC connection string | `INFORMATION_SCHEMA.COLUMNS` |

**Example: `BigQueryConnection`**
```python
class BigQueryConnection(DatabaseConnection):
    connector_category = "warehouse"
    dialect = "bigquery"
    
    def __init__(self, dsn: str, schema_name: str | None = None, connection_id: str | None = None):
        from google.cloud import bigquery
        self._client = bigquery.Client(project=dsn)
        self._dataset = schema_name
        
    def dry_run(self, sql: str) -> tuple[bool, str]:
        # BigQuery supports native dry_run — zero cost, validates SQL
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        self._client.query(sql, job_config=job_config)
        return True, ""
```

**Files to create:**
- `aughor/connectors/warehouse/bigquery.py`
- `aughor/connectors/warehouse/snowflake.py`
- `aughor/connectors/warehouse/mysql.py`
- `aughor/connectors/warehouse/azure_sql.py`

**Add to `pyproject.toml`:**
```toml
[project.optional-dependencies]
warehouse = [
    "google-cloud-bigquery>=3.0.0",
    "snowflake-connector-python>=3.0.0",
    "pymysql>=1.0.0",
    "pyodbc>=5.0.0",
]
```

**Frontend:** Connection type dropdown gets BigQuery / Snowflake / MySQL / Azure SQL options; form fields change per type (project ID, account identifier, ODBC string, etc.)

**New deps:** All optional — `uv pip install -e ".[warehouse]"`
**Dependency on:** Phase 14a (connector framework + namespace model)

---

### Phase 14c — File/Object Connectors (Week 2)

**What:** S3, Azure Blob, and local CSV/Excel/Parquet upload. These connectors don't implement `execute()` against a remote DB — they materialize files into an in-memory DuckDB connection and serve queries from there. The rest of the pipeline (schema introspection, ontology building, profiling) works unchanged.

**Why local upload first:** Zero-credential onboarding. A user drops a CSV of their sales data and gets an autonomous analyst with zero database setup. This is the fastest path from "download" to "first insight" — critical for early user acquisition.

**Pattern: materialize-into-DuckDB**
```python
class S3Connector(Connector):
    connector_category = "file"
    dialect = "duckdb"     # queries run against the materialized DuckDB
    
    def __init__(self, dsn: str, ...):
        # dsn: "s3://bucket/prefix?region=us-east-1&key=...&secret=..."
        self._duckdb = duckdb.connect(":memory:")
        self._duckdb.execute("INSTALL httpfs; LOAD httpfs;")
        self._duckdb.execute(f"""
            CREATE SECRET (TYPE S3, KEY_ID '{key}', SECRET '{secret}', REGION '{region}')
        """)
        # CREATE VIEW table_name AS SELECT * FROM read_parquet('s3://bucket/prefix/*.parquet')

class LocalUploadConnector(Connector):
    connector_category = "file"
    dialect = "duckdb"
    
    def ingest_file(self, file_path: Path, table_name: str) -> None:
        ext = file_path.suffix.lower()
        if ext == ".csv":
            self._duckdb.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{file_path}')")
        elif ext == ".parquet":
            self._duckdb.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{file_path}')")
        elif ext in (".xlsx", ".xls"):
            self._duckdb.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_excel('{file_path}')")
```

**Files to create:**
- `aughor/connectors/file/s3.py`
- `aughor/connectors/file/azure_blob.py`
- `aughor/connectors/file/local_upload.py`

**Frontend:**
- `local_upload` connection type → drag-and-drop zone in "Add Connection" flow; `POST /connections/{id}/upload` multipart endpoint
- `s3` type → bucket / prefix / region / key / secret fields
- Both display in the catalog tree exactly like any other connection — user sees table list, column types, sample data

**New deps:**
```toml
[project.optional-dependencies]
cloud-storage = ["azure-storage-blob>=12.0.0"]
```
DuckDB `httpfs` handles S3 natively (already bundled). No extra dep for local files.

**Dependency on:** Phase 14a; existing `SampleGrid` in `CatalogScreen.tsx` for display ✅

---

### Phase 14d — Multi-Connector Federation Layer (Week 3)

**What:** Cross-source SQL JOINs in a single query. User connects Postgres (orders) + S3 Parquet (marketing events) + Snowflake (financial data). Aughor generates SQL that JOINs across all three. Uses DuckDB's native `ATTACH`, `postgres_scanner`, and `httpfs` as the federation engine.

**This is the 10x feature.** Every other connector adds one more source. Federation makes every combination of sources queryable together. The investigation "why did Q3 revenue drop?" can now draw on Postgres orders, Salesforce pipeline, and S3 marketing spend in a single analysis.

**Implementation:**
```python
class FederatedConnection(DatabaseConnection):
    """Aggregates multiple connectors into a single DuckDB namespace."""
    connector_category = "warehouse"
    dialect = "duckdb"
    
    def __init__(self, connectors: list[Connector]):
        self._duckdb = duckdb.connect(":memory:")
        for conn in connectors:
            if conn.dialect == "postgres":
                self._duckdb.execute(
                    f"ATTACH '{conn.dsn}' AS {conn.namespace} (TYPE postgres)"
                )
            elif isinstance(conn, S3Connector):
                # Copy S3 DuckDB views into federated namespace
                for view_name, view_sql in conn.list_views():
                    self._duckdb.execute(
                        f"CREATE VIEW {conn.namespace}__{view_name} AS {view_sql}"
                    )
            elif isinstance(conn, (BigQueryConnection, SnowflakeConnection)):
                # Materialize a working set into DuckDB for cross-source JOINs
                for table in conn.list_tables():
                    df = conn.sample(table, limit=500_000)
                    self._duckdb.register(f"{conn.namespace}__{table}", df)
```

**Schema context for federation:** `build_schema_context()` for a `FederatedConnection` emits tables with their namespace prefix and cross-namespace join hints from existing fuzzy join inference (2i ✅):
```
FEDERATED SOURCES (3 active):
  mywarehouse__orders          (Postgres · 2.1M rows)
  s3_marketing__events         (S3 Parquet · 5.4M rows)
  salesforce_sync__opportunity (Salesforce sync · 12k rows)

CROSS-SOURCE JOIN HINT:
  mywarehouse__orders.customer_id ↔ salesforce_sync__opportunity.account_id [inferred]
```

**Query routing logic:**
- Single namespace in query → route to that connector's native `execute()` (faster, dialect-correct)
- Multiple namespaces detected → route to `FederatedConnection._duckdb` (all sources in one DuckDB)

**UI:** "Create Federated View" option in the catalog sidebar — user selects 2+ connections, assigns a name, and a new federated entry appears in the catalog tree. The detail panel shows combined schemas across all participating sources.

**Files to create:**
- `aughor/connectors/federated.py`
- `aughor/api.py` — `POST /connections/federate { connection_ids: list[str], name: str }`, `GET /connections/{id}/federation-members`

**New deps:** none (DuckDB `postgres_scanner` + `httpfs` already bundled)
**Dependency on:** Phases 14a, 14b, 14c (needs at least 2 connectors to federate); join inference (2i ✅) for cross-namespace hints

---

### Phase 14e — API/CRM Connectors (Week 3–4)

**What:** Salesforce, HubSpot, Stripe. Each syncs via REST API and materializes into a local DuckDB mirror. The rest of the pipeline — SQL generation, ontology building, profiling, domain intelligence — works completely unchanged. The user queries Salesforce data the same way they query their Postgres database.

**Architecture note — build a `RestApiSync` base first:** Production API connectors deal with OAuth token refresh, bulk API rate limits (Salesforce has hard per-day limits), incremental sync state (cursor-based, timestamp-based), and custom fields that vary per org. Build a shared `RestApiSync` base class with incremental state management, then implement Salesforce/HubSpot/Stripe on top of it.

```python
class RestApiSync(Connector):
    """Base for all REST API connectors. Manages incremental sync state."""
    
    def _load_sync_state(self) -> dict: ...   # reads from data/sync_{conn_id}.json
    def _save_sync_state(self, state: dict) -> None: ...
    def _sync_incremental(self, obj: str, since: datetime) -> list[dict]: ...
    
class SalesforceConnector(RestApiSync):
    connector_category = "api"
    dialect = "duckdb"
    _OBJECTS = ["Account", "Contact", "Opportunity", "Lead", "Case"]
    
    def _sync_incremental(self, obj: str, since: datetime) -> list[dict]:
        soql = f"SELECT Id, Name, ... FROM {obj} WHERE LastModifiedDate > {since.isoformat()}Z"
        return self._sf.query_all(soql)["records"]
```

**Why after Phase 14d:** Salesforce data becomes far more valuable when it can JOIN with warehouse data. Ship the federation layer first so Salesforce + Postgres cross-source queries work on day one.

**Files to create:**
- `aughor/connectors/api/base_sync.py` — `RestApiSync` with incremental state management
- `aughor/connectors/api/salesforce.py`
- `aughor/connectors/api/hubspot.py`
- `aughor/connectors/api/stripe.py`

**Add to `pyproject.toml`:**
```toml
[project.optional-dependencies]
crm = ["simple-salesforce>=1.12.0", "hubspot-api-client>=8.0.0", "stripe>=7.0.0"]
```

**Dependency on:** Phase 14a (framework); Phase 14d (federation — so SFDC JOINs with warehouse immediately)

---

### Phase 14f — Knowledge Connectors (Week 4)

**What:** Confluence and Notion. Unlike database connectors, these don't implement `execute()` — they are knowledge source connectors that feed into the existing `aughor_documents` Qdrant collection built in M13d ✅. The entire document ingestion, chunking, embedding, and synthesis pipeline already handles everything downstream.

**Pattern — extend the existing document pipeline with live API sources:**
```python
class ConfluenceConnector:
    """Extracts Confluence pages and indexes into aughor_documents Qdrant collection."""
    connector_category = "knowledge"
    
    def sync(self, space_key: str, conn_id: str) -> int:
        pages = self._fetch_all_pages(space_key)       # GET /rest/api/content?spaceKey=...
        for page in pages:
            text = html_to_text(page.body_storage)
            chunks = chunk_text(text, size=400, overlap=100)
            index_document(conn_id, doc_id=page.id, chunks=chunks, source=page.url)
        return len(pages)
```

**What changes from file upload (M13d):** The source is a live API (Confluence, Notion) instead of a user-uploaded file. The chunking, embedding, and Qdrant upsert path is identical. The `DocumentUploader.tsx` UI gets a "Connect Confluence" flow alongside the drag-and-drop zone.

**Files to create:**
- `aughor/connectors/knowledge/confluence.py`
- `aughor/connectors/knowledge/notion.py`

**Add to `pyproject.toml`:**
```toml
[project.optional-dependencies]
knowledge-sync = ["atlassian-python-api>=3.41.0", "notion-client>=2.2.0"]
```

**New deps:** optional; the document pipeline itself has no new deps
**Dependency on:** Phase 14a (framework); M13d Document Ingestion ✅ (Qdrant collection, indexer, chunker all in place)

---

## Milestone 15 — Operational Write-Back (Action Hub)

**Goal:** Close the "data-to-decision" gap. When Aughor surfaces a recommendation — "review return policy," "flag seller performance," "increase reorder threshold" — the user can act on it without leaving Aughor: create a Jira ticket, post to Slack, trigger a Zapier workflow, or call any webhook.

**Why this comes last:** The trust layer must be established first. Users will not automate actions on analysis they haven't yet validated. The playbook outcome tracking (M13c ✅) is the prerequisite — it proves recommendation quality over time and gives users the confidence to act. The Action Hub is only useful after users have actioned enough playbook entries to trust the system. Shipping it too early adds automation risk on top of an unvalidated analyst.

**Architecture — lightweight webhook dispatch:** Not full ERP integration. Configurable webhook endpoints that fire when a recommendation is actioned. The user defines integrations (Slack, Jira, Zapier, n8n, custom HTTP); Aughor fires them with recommendation context as the payload.

**Files to create:**
- `aughor/actions/models.py` — `ActionTrigger`: `id`, `name`, `type: Literal["webhook","slack","jira"]`, `url: str`, `headers: dict`, `enabled: bool`; `ActionPayload`: recommendation text, investigation ID, metric name, before/after values
- `aughor/actions/executor.py` — `fire_action(trigger: ActionTrigger, payload: ActionPayload)`: async HTTP POST via `httpx`; logs result to audit trail; handles 4xx/5xx with retry
- `aughor/api.py` — `GET/POST/PUT/DELETE /actions/triggers`; `POST /investigations/{inv_id}/recommendations/{rec_id}/execute { trigger_id }` — fires configured trigger and logs outcome
- `web/components/ActionHubPanel.tsx` — configure webhook integrations (name, URL, headers, test fire); browsable per-recommendation "Execute →" button that appears in `RecommendationCard` alongside "Mark Done"

**What this enables:** User sees "Refund Rate at 14% — recommended: audit top-10 return SKUs." Instead of copying text into Jira, they click "Execute →", pick the Jira trigger, and a ticket is created with the full investigation context as the description. The outcome is auto-logged to M13c.

**New deps:** none (`httpx` already in stack for async HTTP)
**Dependency on:** M13c Outcome Tracking ✅ (trust calibration prerequisite); M14 connectors (so actions can reference federated source context); M6 Audit Trail (so every fired action is logged immutably)

---

## Milestone 16 — Canvas: Curated Analytical Workspaces

**Goal:** Replace the connection as the primary context unit with a **Canvas** — a named, persistent analytical workspace where the user curates exactly the tables (or full schemas) they care about. Investigations, history, recents, intelligence, and exploration are all Canvas-scoped. The agent sees only the tables relevant to the problem domain, not 40 unrelated tables that happen to share a database.

**What changes vs. what doesn't:**

| Changes | Stays the same |
|---|---|
| Primary context unit: `connection_id` → `canvas_id` | Connection credential store |
| Investigations scoped to Canvas | Agent pipeline (decompose / plan / execute / synthesize) |
| Schema context filtered to Canvas tables | Schema format, ontology injection format |
| History, Recents, Suggestions per Canvas | History store structure |
| Intelligence generated per Canvas | Domain intel loop mechanics |
| Explorer runs Canvas-aware (selected tables only) | Qdrant infra (just swap filter field) |
| Landing screen: Canvas browser | Catalog (still shows all; gains "Add to Canvas") |
| Recommendation Inbox: Canvas + role + org levels | Ontology (schema-level, Canvas projects a slice) |

**Design decisions locked:**
- No default Canvas — user creates one before investigating (clean, intentional first-use gesture)
- Granularity: user selects either individual tables OR an entire schema — schema is the coarsest unit
- Canvas is persistent and named; both Quick Chat and Deep Analysis modes work within it
- Explorer is Canvas-aware primarily; full schema-level exploration is a manual opt-in trigger
- Multi-connection Canvas: data model supports it from day one (`scopes: list[CanvasScope]`), API enforces `len(scopes) == 1` until M14d federation lands — lift the constraint then, no migration needed
- Intelligence promotion: manual curation first; automatic confidence-threshold promotion is Sprint 33 (Org Intelligence Layer)

---

### Phase 16a — Canvas Data Model + Backend Migration

**What:** Introduce the Canvas as a first-class entity. Existing connections auto-migrate to legacy Canvases (entire schema scope). No user-visible change. The agent pipeline gains `canvas_id` support alongside `connection_id` for backward compatibility.

**Core models:**
```python
# aughor/canvas/models.py

class CanvasScope(BaseModel):
    """One source within a Canvas."""
    connection_id: str
    schema: str
    tables: list[str] = []     # [] = entire schema in scope

    @property
    def is_full_schema(self) -> bool:
        return len(self.tables) == 0

    def covers(self, schema: str, table: str) -> bool:
        return self.schema == schema and (self.is_full_schema or table in self.tables)


class Canvas(BaseModel):
    canvas_id: str              # UUID — becomes primary context key everywhere
    name: str                   # "Revenue Operations"
    description: str = ""
    created_at: str
    updated_at: str
    last_used_at: Optional[str] = None
    # Multi-connection roadmap: API enforces len==1 until M14d; data model already supports N
    scopes: list[CanvasScope]
    # Denormalized stats for home screen
    investigation_count: int = 0
    exploration_active: bool = False
```

**What gets `canvas_id`:**

| Store | Current key | After |
|---|---|---|
| Investigation history (`data/history.db`) | `connection_id` | `canvas_id` (+ keep `connection_id` for legacy backfill) |
| Qdrant prior analyses payload | `connection_id` | `canvas_id` |
| Qdrant schema suggestions payload | `connection_id` | `canvas_id` |
| Explorer state (`exploration_{id}.json`) | `{connection_id}` | `{canvas_id}` |
| Domain episodes (`episodes_{id}.jsonl`) | `{connection_id}` | `{canvas_id}` |
| Schema cache key | connection fingerprint | canvas fingerprint (table list + connection fingerprints) |
| `AgentState` | `connection_id: str` | `canvas_id: str` + `resolved_connection_id: str` |

**`AgentState` change:**
```python
class AgentState(TypedDict):
    canvas_id: str              # primary context key
    resolved_connection_id: str # set at investigation start; SQL execution path never changes
    canvas_schema_context: str  # pre-built filtered schema — replaces full connection schema
    ...
```
`resolved_connection_id` is what the SQL executor, dialect transforms, and connection objects use — they never need to know about Canvas. The Canvas concern is entirely in the context-building layer.

**Schema context builder:**
```python
# aughor/tools/schema.py
def build_canvas_schema_context(canvas: Canvas, connections: dict) -> str:
    """Returns schema string filtered to only the tables in the Canvas scope."""
    parts = []
    for scope in canvas.scopes:
        conn = connections[scope.connection_id]
        if scope.is_full_schema:
            parts.append(conn.get_schema(schema=scope.schema))
        else:
            parts.append(conn.get_schema_for_tables(scope.schema, scope.tables))
    return "\n\n".join(parts)
```

**Auto-migration on startup:**
```python
def migrate_connections_to_legacy_canvases(registry, canvas_store):
    """Called once at startup. Idempotent."""
    for conn in registry.list_connections():
        legacy_id = f"legacy_{conn.id}"
        if not canvas_store.exists(legacy_id):
            canvas_store.save(Canvas(
                canvas_id=legacy_id,
                name=conn.name,
                scopes=[CanvasScope(
                    connection_id=conn.id,
                    schema=conn.default_schema or "public",
                    tables=[]   # entire schema
                )],
            ))
```

**API additions:**
```
GET    /canvases                        → list all Canvases
POST   /canvases                        → create Canvas
PUT    /canvases/{canvas_id}            → update (rename, add/remove scopes)
DELETE /canvases/{canvas_id}
GET    /canvases/{canvas_id}/schema     → filtered schema context (for UI preview)
```
Existing `POST /investigate` and `POST /chat` accept `canvas_id` OR `connection_id` — if `connection_id` received, look up its legacy Canvas and use that. No breaking changes.

**Files to create:**
- `aughor/canvas/__init__.py`, `models.py`, `store.py`

**Files to modify:**
- `aughor/api.py` — Canvas CRUD endpoints; `_startup` migration; `canvas_id` param on `/investigate` + `/chat`
- `aughor/agent/state.py` — add `canvas_id`, `resolved_connection_id`, `canvas_schema_context`
- `aughor/agent/nodes.py` — `decompose_question` builds `canvas_schema_context` when `canvas_id` present
- `aughor/tools/schema.py` — add `build_canvas_schema_context()`
- `aughor/db/history.py` — add nullable `canvas_id` column; backfill from legacy mapping on migration

**New deps:** none
**Dependency on:** Existing `DatabaseConnection` ABC ✅, connection registry ✅, investigation history ✅

---

### Phase 16b — Canvas Browser + Creation Flow

**What:** The landing screen becomes a Canvas browser. Users create, name, and open Canvases. Investigation, Chat, History, and Recents are all scoped to the active Canvas. Catalog gains an "Add to Canvas" action.

**Canvas browser (landing screen):**
- Card grid of named Canvases — name, table count, connection source, last used, investigation count
- "New Canvas" button → opens creation flow
- No Canvases yet → prompt: "Create your first Canvas to start investigating"
- Legacy Canvases (auto-created from connections) appear as `{Connection Name} — Default` until renamed

**Canvas creation flow:**
```
1. Name your Canvas           ("Revenue Operations")
2. Pick a connection          (connection picker — same registry)
3. Select tables or schemas   (Catalog-style tree with checkboxes)
   ├── ☑ entire schema: public    ← schema-level selection
   ├── □ public
   │     ├── ☑ orders
   │     ├── ☑ customers
   │     └── □ internal_audit_log
   └── Selected: public.orders, public.customers
4. Create → enters Canvas workspace
```

**Canvas workspace (replaces current home page layout):**
```
Canvas workspace
├── Header: Canvas name + table count + connection badge + ⚙ settings
├── Tabs: Chat | Deep Analysis | History | Intelligence | Catalog (filtered)
└── All tabs scoped to this Canvas's tables and investigation history
```

**Catalog within Canvas:** Shows only tables in scope. Full catalog still accessible via "Browse all data" link → CatalogScreen (unchanged global view) with "Add to this Canvas" action per table.

**API additions:**
```
GET    /canvases/{canvas_id}/history      → investigations for this Canvas
GET    /canvases/{canvas_id}/suggestions  → schema-specific starters (Canvas-filtered)
GET    /canvases/{canvas_id}/recents      → last N investigations in this Canvas
```

**Files to create:**
- `web/components/CanvasBrowser.tsx` — landing screen; Canvas cards; "New Canvas" entry point
- `web/components/CanvasCreator.tsx` — creation flow: name → connection → table/schema picker
- `web/components/CanvasWorkspace.tsx` — Canvas-scoped workspace shell; tab nav; header

**Files to modify:**
- `web/app/page.tsx` — root route renders `CanvasBrowser` when no Canvas active; `CanvasWorkspace` when Canvas selected
- `web/components/CatalogScreen.tsx` — gains "Add to Canvas" action per table/schema row
- `web/lib/api.ts` — Canvas CRUD types + fetch functions; Canvas-scoped history/suggestions

**New deps:** none
**Dependency on:** Phase 16a (Canvas store + API)

---

### Phase 16c — Canvas-Aware Explorer + Intelligence Foundation

**What:** The background Schema Explorer runs against Canvas tables only — not the full connection schema. Intelligence discoveries are tagged with `canvas_id`. Manual opt-in trigger for full schema-level exploration. Promotion field added to intelligence entries (consumed by Org Intelligence Layer in Sprint 33).

**Explorer adaptation:**
```python
# aughor/explorer/agent.py

class SchemaExplorer:
    def explore(self, canvas: Canvas, ...):
        # Phases 3–7: run against canvas.scopes[0].tables only (or full schema if is_full_schema)
        # Phase 8 (domain intel): curiosity loop scoped to Canvas tables
        # State file: exploration_{canvas.canvas_id}.json
        ...
```

Explorer state file changes from `exploration_{connection_id}.json` → `exploration_{canvas_id}.json`. Legacy explorers (connection-scoped) continue running for legacy Canvases unchanged.

**Manual schema-level exploration:**
- "Explore full schema" button in Canvas settings (⚙)
- Triggers a one-off connection-level exploration pass, writes to `exploration_full_{connection_id}.json`
- Results surfaced as "Schema-level insights" separately from Canvas intelligence

**Intelligence entries gain provenance fields:**
```python
class IntelligenceEntry(BaseModel):
    ...
    canvas_id: str              # which Canvas generated this
    promoted_to_org: bool = False  # manual flag — consumed by Sprint 33
    promotion_confidence: float = 0.0  # for future auto-promotion threshold
```

**UI change:** Intelligence tab within Canvas shows only that Canvas's domain findings. A "Promote to Org →" button appears on each entry (stores `promoted_to_org=True`, does nothing else yet — Sprint 33 builds the Org Intelligence collection).

**Files to modify:**
- `aughor/explorer/agent.py` — accept `Canvas` instead of `connection_id`; state file keyed by `canvas_id`
- `aughor/explorer/store.py` — `ExplorationStatus.canvas_id` field; lookup by `canvas_id`
- `aughor/api.py` — `/exploration/{canvas_id}/...` routes (alongside existing `/{conn_id}/...` for backward compat)
- `web/components/DomainIntelPanel.tsx` — scoped to active Canvas; shows `promoted_to_org` badge; "Promote to Org →" button
- `web/components/ActivityLog.tsx` — episode feed filtered by active Canvas

**New deps:** none
**Dependency on:** Phases 16a + 16b; existing Explorer infrastructure ✅

---

### Phase 16d — Multi-Connection Canvas *(roadmap — unlocks with M14d)*

**What:** Lift the `len(scopes) == 1` API constraint. A Canvas can draw tables from multiple connections — e.g., `postgres_prod.public.orders` + `snowflake_dw.analytics.campaigns`. The `resolved_connection_id` in `AgentState` becomes a `FederatedConnection` id when multiple scopes are present.

**What changes from Phase 16a:**
- API: remove `if len(canvas.scopes) > 1: raise HTTPException(400, "Multi-connection Canvas not yet supported")`
- `build_canvas_schema_context()`: already handles `list[CanvasScope]` — no change needed
- `resolve_canvas_connection(canvas)`: if `len(scopes) == 1` → return single connection; if `len(scopes) > 1` → build `FederatedConnection` from scopes (M14d)
- Canvas creation UI: connection picker becomes multi-connection (add a second connection source)

**Dependency on:** Phase 16a (data model already correct) + M14d (FederatedConnection executor) — no earlier phase is blocked

---

### Phase 16e — Org Intelligence Layer *(roadmap — Sprint 33)*

**What:** Verified Canvas intelligence gets promoted to a shared Org-level collection visible to all users regardless of which Canvas they work in. Org intelligence becomes the accumulated institutional memory of the organisation — built bottom-up from Canvas investigations, curated by human promotion.

**Promotion pipeline:**
```
Canvas investigation → domain insight generated
  → analyst reviews, clicks "Promote to Org →"
    → org_intelligence collection in Qdrant
      → visible in new "Org Intelligence" tab to all users
        → injected into ADA synthesis across all Canvases (as {org_intelligence_section})
```

**Future: automatic promotion** when N Canvas investigations (across M different Canvases) confirm the same pattern with confidence > threshold. Manual curation first; auto-promotion in a later sprint.

**Dependency on:** Phase 16c (promoted_to_org field + Qdrant infrastructure); M6 RBAC (only analysts with sufficient role can promote to Org)

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
| **14 — BI Layer: Health** ✅ | M13a (Metric Targets + Health Scorecard) | Aughor shows process health proactively on open; reactive Q&A → proactive monitoring |
| **15 — BI Layer: Playbook** ✅ | M13b (Playbook from KB) | KB causal chains become reusable, retrievable interventions; recommendations stop being hallucinated |
| **16 — BI Layer: Feedback** ✅ | M13c (Outcome Tracking) | Recommendations get a success rate; system learns from organisational history |
| **17 — BI Layer: Context** ✅ | M13d (Document Ingestion) | SOPs, return policies, strategy docs feed into synthesis; Qdrant infra already ready |
| **18 — BI Layer: Process Map** ✅ | M13e (Business Process Visual Mapper) | Swimlane health diagram; click red step → ADA investigation |
| **19 — BI Layer: Causal Twin** | M13f (Causal Graph in Ontology) | ADA waterfalls write causal edges; algorithmic root-cause traversal |
| **20 — Catalog UX + Hardening** ✅ | Catalog 3-panel (60) + Phase 8 gate (61) + Connection persistence (62) | Databricks-style catalog; domain intel always has ontology; connections survive restart |
| **21 — Canvas: Data model + pipeline** | M16a (CanvasScope + Canvas models + store; auto-migration; canvas_id in AgentState + schema context builder; history backfill) | Non-breaking foundation; all existing workflows via legacy Canvases; agent can run Canvas-scoped immediately |
| **22 — Canvas: Browser + workspace UI** | M16b (CanvasBrowser landing; CanvasCreator flow; CanvasWorkspace shell; Catalog "Add to Canvas"; scoped history/suggestions/recents) | User-visible Canvas; first-use creation gesture; no Canvas until user creates one |
| **23 — Canvas: Explorer + intelligence** | M16c (Explorer Canvas-aware; exploration state by canvas_id; manual schema-level trigger; promoted_to_org field; "Promote to Org →" button) | Intelligence scoped to Canvas; provenance field ready for Sprint 33 |
| **24 — Security baseline** | M6 partial (Gradient Safety 6e + PII 6a + Audit 6c + Budget 6b) | Audit trail scoped to Canvas; PII never reaches LLM; must land before connector sprints |
| **25 — Connector Framework** | M14a (base ABC + registry + namespace model) | Foundation all future connectors build on; namespace designed now for M16d multi-connection Canvas |
| **26 — Warehouse connectors** | M14b (BigQuery + Snowflake + MySQL + Azure SQL) | Highest-demand cloud warehouses; same investigation quality anywhere |
| **27 — File connectors** | M14c (S3 + local upload) | Data lake analytics; zero-credential onboarding via CSV/Excel drop |
| **28 — Federation + multi-connection Canvas** | M14d + M16d (FederatedConnection; lift Canvas scopes==1 constraint; Canvas spans Postgres + S3 + Snowflake) | Cross-source JOINs; Canvas becomes multi-system workspace |
| **29 — API connectors** | M14e (Salesforce + HubSpot + Stripe) | After federation — SFDC JOINs with warehouse in same Canvas |
| **30 — Knowledge connectors** | M14f (Confluence + Notion) | Live wiki sync → existing document pipeline; Canvas gains institutional context |
| **31 — Enterprise Security** | M6 full (SSO/OIDC + RBAC + Vault; Canvas ownership + sharing; Inbox role-scoping) | Enterprise procurement gate; Canvas shared across team; Inbox scoped by role |
| **32 — Action Hub** | M15 (webhook write-back + Slack/Jira triggers) | Data-to-decision loop; trust established via outcome history |
| **33 — Org Intelligence Layer** | M16e (Qdrant org_intelligence collection; promotion pipeline; {org_intelligence_section} in ADA synthesis; Org Intelligence tab) | Canvas insights accumulate into org-wide institutional memory |
| **34 — Analytical depth** | M4 (Prophet forecasting) + M2d (Events Calendar) | "Is this drop unusual *given the trend*?" |
| **35 — Quality gates** | M10 (Evals — Braintrust) + M7 (Observability) | CI regression testing on verdict quality; Langfuse traces on real costs |

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

DatabaseConnection ABC ✅ + Connection registry ✅
    └── M14a: Connector Framework  ←  base ABC + registry + namespace model; federation namespace designed here
            └── M14b: Warehouse connectors  ←  BigQuery / Snowflake / MySQL / Azure SQL; same DatabaseConnection interface
            └── M14c: File connectors  ←  S3 + Azure Blob + local upload; materialize-into-DuckDB pattern
            │       └── M14d: Federation layer  ←  FederatedConnection + query router; DuckDB ATTACH + postgres_scanner
            │               └── M14e: API connectors  ←  Salesforce + HubSpot + Stripe; ship AFTER federation so cross-source JOINs work on day one
            └── M14f: Knowledge connectors  ←  Confluence + Notion; extends M13d doc pipeline (Qdrant + indexer already in place)

M13c: Outcome Tracking ✅ + M14: Connector Platform + M6: Audit Trail
    └── M15: Action Hub  ←  webhook write-back; trust earned via outcome history; audit every fired action; richest when multiple sources connected

Join Inference (2i) ✅
    └── M14d: Federation layer  ←  cross-namespace join hints reuse fuzzy join inference from 2i

Security baseline (M6 partial) → must land before Sprint 26 (API connectors) when CRM credentials enter the registry
    └── M6 full (SSO/OIDC + RBAC + Vault)  ←  enterprise procurement gate; after connectors are proven
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
| Federation engine | **DuckDB ATTACH + postgres_scanner + httpfs** | Cross-source JOINs: Postgres + S3 + Snowflake in one query (M14d) |
| Warehouse connectors | **BigQuery, Snowflake, MySQL, Azure SQL** | All implement `DatabaseConnection` ABC; optional `[warehouse]` dep group (M14b) |
| File connectors | **S3, Azure Blob, local CSV/Parquet/Excel** | Materialize via `read_parquet()` / `read_csv_auto()` into DuckDB; zero-credential onboarding (M14c) |
| API connectors | **Salesforce, HubSpot, Stripe** | REST sync → DuckDB mirror; `RestApiSync` base + incremental state; optional `[crm]` group (M14e) |
| Knowledge connectors | **Confluence, Notion** | Live API → existing `aughor_documents` Qdrant pipeline; optional `[knowledge-sync]` group (M14f) |
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

**Shipped:** M1 (Semantic Layer), M2a–2c + 2e–2j (Agent hardening, HITL, Direct Query, Routing v2, SQL KB, Error Classification, Schema Intelligence, KB Enrichment), M8 (Frontend Charts, Chart Intelligence, Report UX), M9 (Quick Chat + Chart Engine + Deep Analysis tab), 1e (Metrics Catalog), ER Diagram, Rich Schema Card UI, Global Analytics Rules (32), Hypothesis Expanded Accordion (33), Connection-scoped semantic cache, Paren-aware ROUND rewriter, Schema parser dedup, Timeout 600 s, UI color pass, **M12 Background Schema Explorer + Business Ontology + Domain Intelligence + SqlWriter (48 features total)**, Plan-then-SQL Separation (49), Non-blocking event loop (50), Loading state hardening (51), Home stat card navigation (52), Schema cache backend + frontend (53), **M13a–13e: Metric Targets + Health Scorecard (54), Structured Playbook from KB (55), Outcome Tracking & Feedback Loop (56), Document Ingestion (57), Process Visual Mapper (58)**, **R1 Reliability Baseline + R3 Feature Reachability + R2 Test Infrastructure (Sprints 36–38)**, **M17 API Router Refactor — 3,375-line api.py → 12 domain routers (Sprint 39)**, **M7 Observability — Langfuse + OTel spans on 12 nodes, trace_id in SSE, 45 tests (Sprint 40)**, **M10 LLM Evals (Sprint 41)**, **M22 Design System Consolidation — tokens.css + type.css + 12-component audit (Sprint 42)**, **M18 Navigation + Command Palette + Ask Hero — 5-section nav, ⌘K palette, AskScreen (Sprint 43)**, **M19 Evidence Ledger — append-only SQLite claims, provenance, feedback loop (Sprint 44)**, **M20 Proactive Monitors — 6 monitor types, APScheduler, digest endpoint, alert banner (Sprint 45)**

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

**Sprint 20 — Infrastructure hardening + Catalog UX ✅ SHIPPED:**
- Catalog 3-panel layout (60): `CatalogScreen.tsx` replaces `CatalogPanel.tsx`; Databricks-style connection sidebar → table list → detail with Columns/Sample tabs; `SampleGrid` lazy-loads up to 100 rows; component self-fetches connections on mount
- Phase 8 ontology gate (61): `aughor/explorer/agent.py` — `get_schema()` called before Phase 8 if ontology absent; ensures domain intelligence loop always has ontology available; eliminates 0-insight silent skips
- Connection persistence hardening (62): Fernet key pinned to `.env` as `AUGHOR_SECRET_KEY`; `data/.aughor_key` gitignored; `_validate_connections()` startup event; CORS opened to `allow_origins=["*"]`
- `python-multipart` added to `pyproject.toml` (was runtime-missing, crashed document upload endpoint)
- Recovery runbook documented in project memory: kill all → `rm -rf web/.next` → `./start.sh` → hard-refresh browser

**After M13:** Canvas (M16) → M6 Security baseline → Connector Platform (M14) → M15 (Action Hub) → M6 Enterprise Security full → Org Intelligence (M16e) → M4 (Prophet) + M2d (Events) → M10 (Evals) + M7 (Observability)

**Deferred:** M5 Provider Switcher (Anthropic backend) — moved to near-end; M6 Security must land before any multi-tenant or enterprise deployment

**Sprint 19 — M13f: Causal Graph in Ontology (next):**
- `aughor/ontology/models.py` — `CausalEdge(BaseModel)`: `id`, `source_metric`, `target_metric`, `relationship` (drives/inhibits/correlates_with), `evidence_strength`, `contribution_pct`, `typical_lag`, `source_investigations`; `causal_edges: dict[str, CausalEdge]` added to `OntologyGraph`
- `aughor/ontology/store.py` — `append_causal_edge()` upserts into persisted graph
- `aughor/agent/investigate.py` — after ADA synthesis, parse `attribution_waterfall` entries and call `store.append_causal_edge()` for each contribution with `contribution_pct > 5%`; evidence_strength = "strong" (>20%), "moderate" (10–20%), "weak" (<10%)
- `aughor/playbook/retriever.py` — `traverse_causal_graph(off_target_metric, ontology, max_depth=3)`: BFS backward from `target_metric` through causal edges; returns list of upstream source_metrics; `retrieve_for_root_cause` gains a causal traversal pass before direct metric lookup
- `aughor/api.py` — `GET /ontology/causal-edges`, `GET /ontology/causal-edges/{metric}`
- `web/components/OntologyCanvas.tsx` — render `causal_edges` as dashed arrows (orange=drives, red=inhibits, zinc=correlates_with); `contribution_pct` + source investigation link on click

**Sprint 20 — Schema Self-Awareness (autonomous schema quirk detection):**
- `aughor/tools/profiler.py` — `detect_schema_quirks(table_profiles, column_profiles)`: cross-table cardinality analysis; detects per-transaction ID columns (distinct == row_count) that have stable alternatives in the same table (same stem, lower cardinality); emits `⚠ SCHEMA QUIRK` block prepended to `scan_context` automatically — no LLM, pure arithmetic
- `render_profile_annotations()` calls `detect_schema_quirks()` before the per-table stats; quirk block flows into `{scan_context}` in `INTAKE_PROMPT` and `BASELINE_PLAN_PROMPT`
- `data/glossary.yaml` — correct `customer` + `orders` table entries for olist: `customer_id` marked per-order hash, `customer_unique_id` marked as stable identifier with repeat-count annotation
- `aughor/agent/state.py` — `DataQualityNote` fields defaulted to empty string (LLMs omit them); `ExplorationReport.data_quality_notes` validator strips malformed entries; `ReasoningOutput.new_sub_question` validator coerces JSON-stringified objects (models return nested objects as strings)
- **Explorer → KB write loop (M20b — Sprint 20b):** after `synthesize_exploration`, extract data quality discoveries from `data_quality_notes` + narrative anomalies; write connection-scoped caveats back to `glossary.yaml` via `update_column()` / `update_table()` — closes the learning loop so Explorer findings persist across sessions

**Sprint 21 — M16a: Canvas Data Model + Backend Migration ✅ SHIPPED:**
- `aughor/canvas/__init__.py`, `models.py`, `store.py` — `CanvasScope` + `Canvas` models; `canvas_store` SQLite-backed; `migrate_connections_to_legacy_canvases()` runs once on startup (idempotent)
- `aughor/agent/state.py` — `canvas_id: str`, `resolved_connection_id: str`, `canvas_schema_context: str` added to `AgentState`
- `aughor/agent/nodes.py` — `decompose_question` builds `canvas_schema_context` via `build_canvas_schema_context()` when `canvas_id` present
- `aughor/tools/schema.py` — `build_canvas_schema_context(canvas, connections)`: filters full schema to Canvas-scoped tables only; `get_schema_for_tables(schema, tables)` on connection objects
- `aughor/db/history.py` — nullable `canvas_id` column; backfill from legacy mapping on migration
- `aughor/api.py` — `GET/POST/PUT/DELETE /canvases`; `GET /canvases/{id}/schema`; Canvas CRUD + startup migration; `POST /investigate` + `POST /chat` accept `canvas_id` OR `connection_id` (legacy Canvases used as fallback)
- API enforces `len(scopes) == 1` until M14d federation lands; data model already supports N scopes

**Sprint 22 — M16b: Canvas Browser + Workspace UI:**
- `web/components/CanvasBrowser.tsx` — landing screen: Canvas card grid (name, table count, connection badge, last used, investigation count); "New Canvas" entry; "No Canvases yet" empty state prompt
- `web/components/CanvasCreator.tsx` — 3-step creation flow: name → connection picker → table/schema tree with checkboxes (schema-level or individual table selection)
- `web/components/CanvasWorkspace.tsx` — Canvas-scoped workspace shell: header (name + table count + connection badge + ⚙ settings), tab nav (Chat / Deep Analysis / History / Intelligence / Catalog filtered)
- `web/app/page.tsx` — root route renders `CanvasBrowser` when no Canvas active; `CanvasWorkspace` when Canvas selected
- `web/components/CatalogScreen.tsx` — gains "Add to Canvas" action per table/schema row
- `web/lib/api.ts` — Canvas CRUD types + fetch functions; Canvas-scoped history/suggestions/recents
- `GET /canvases/{id}/history`, `GET /canvases/{id}/suggestions`, `GET /canvases/{id}/recents` API routes

**Sprint 23 — M16c: Canvas-Aware Explorer + Intelligence Foundation ✅ SHIPPED:**
- `aughor/explorer/agent.py` — `explore()` accepts `Canvas` instead of `connection_id`; phases 3–7 run against `canvas.scopes[0].tables` only (or full schema if `is_full_schema`); state file keyed by `canvas_id`
- `aughor/explorer/store.py` — `ExplorationStatus.canvas_id` field; lookup by `canvas_id`; legacy explorers (connection-scoped) continue unchanged
- `aughor/api.py` — `/exploration/{canvas_id}/...` routes alongside existing `/{conn_id}/...` for backward compat; "Explore full schema" one-off trigger writes to `exploration_full_{connection_id}.json`
- `IntelligenceEntry` gains `canvas_id: str`, `promoted_to_org: bool = False`, `promotion_confidence: float = 0.0`
- `web/components/DomainIntelPanel.tsx` — scoped to active Canvas; "Promote to Org →" button per entry (stores flag, builds foundation for Sprint 33)
- `web/components/ActivityLog.tsx` — episode feed filtered by active Canvas

**Sprint 40 — M7 Observability ✅ SHIPPED:**
- `aughor/telemetry.py` *(new)* — `_langfuse()` lazy Langfuse client (reads `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`); `_otel()` lazy OTel tracer (reads `OTEL_EXPORTER_OTLP_ENDPOINT`); `new_trace(inv_id, question, conn_id)` → creates Langfuse trace keyed by `investigation_id`, returns `trace_id`; `span(trace_id, name, metadata)` context manager creates Langfuse + OTel spans; `log_generation(...)` logs LLM call to trace; `end_trace(trace_id)` finalises + flushes; `node_span(name)` decorator factory works for both `(state,)` and `(state, conn)` signatures
- `aughor/agent/state.py` — `trace_id: str` field added to `AgentState` TypedDict
- `aughor/agent/nodes.py` — `@node_span` applied to 6 nodes: `route_question`, `decompose`, `plan_queries`, `execute_planned_queries`, `score_evidence`, `synthesize_report`; each span carries `iteration`, `hypothesis_idx`, `hypothesis_id` metadata
- `aughor/agent/investigate.py` — `@node_span` applied to all 6 ADA nodes: `ada_intake`, `ada_baseline`, `ada_decompose`, `ada_dimensional`, `ada_behavioral`, `ada_synthesize`
- `aughor/routers/investigations.py` — `new_trace()` called immediately before `start` SSE; `trace_id` included in start event payload (deep-link to Langfuse trace) and in `initial_state`; `end_trace()` in `finally` block to flush on completion or error
- `aughor/agent/graph.py` — `"trace_id": ""` added to CLI `initial_state`
- `pyproject.toml` — `observability` optional dep group: `langfuse>=2.0.0`, `opentelemetry-sdk>=1.24.0`, `opentelemetry-exporter-otlp>=1.24.0`
- `tests/unit/test_telemetry.py` *(new, 19 tests)* — covers no-op paths, decorator pass-through, hypothesis metadata extraction, exception propagation, OTel attr type safety, SSE format contract
- **Test suite: 26 → 45 passing (all non-e2e)**

**Sprint 24 — M6 Security baseline:**
- `aughor/security/safety.py` — `SafetyVerdict` gains `SUSPICIOUS`; `_score_suspicious()` heuristic layer on top of existing SQLGlot structural check; amber "⚠ Flagged Query" badge in `ReportView.tsx` on suspicious verdict
- `aughor/security/pii.py` — `scan_and_redact()` via Microsoft Presidio; called on every `QueryResult` before LLM sees rows
- `aughor/security/audit.py` — `AuditLogger`; append-only `data/audit.db`; `(canvas_id, investigation_id, sql, row_count, pii_redacted, timestamp)` per execution
- `aughor/security/sandbox.py` — `QueryBudget`; per-connection configurable row/time/query limits; enforced inside `execute()` before query hits wire
- Must land before Sprint 25 (connector framework) — every new connector's queries go through audit from day one

**Sprint 25 — M14a: Connector Framework:**
- `aughor/connectors/` package: `base.py` (Connector ABC + `connector_category` + `namespace`), `registry.py` (type-string → class mapping)
- Namespace model locked in here — critical for federation: `mywarehouse.public.orders`, `s3_marketing.events`, `salesforce_sync.opportunity`
- `aughor/db/registry.py` — routes `conn_type` through connector registry; existing DuckDB + Postgres migrated to new framework
- Frontend: connection type dropdown extended; per-type field config component (project ID for BigQuery, account for Snowflake, bucket for S3, etc.)

**Sprint 26 — M14b: Warehouse connectors:**
- BigQuery: `google-cloud-bigquery`; `INFORMATION_SCHEMA.COLUMNS` per dataset; native `dry_run` (zero cost SQL validation)
- Snowflake: `snowflake-connector-python`; account identifier + user/pass or key-pair auth
- MySQL: `pymysql`; same pattern as Postgres; `information_schema.columns`
- Azure SQL: `pyodbc`; T-SQL dialect via SQLGlot
- All optional under `[warehouse]` dep group: `uv pip install -e ".[warehouse]"`

**Sprint 27 — M14c: File connectors:**
- Local upload: drag-and-drop in "Add Connection"; `POST /connections/{id}/upload` multipart; CSV/Parquet/Excel via DuckDB native `read_csv_auto()` / `read_parquet()` / `read_excel()`
- S3: bucket/prefix/region/key/secret fields; DuckDB `httpfs` + `CREATE SECRET`; auto-discovers Parquet files as views
- Azure Blob: `azure-storage-blob` + DuckDB `httpfs` Azure path support
- Both display in catalog tree exactly like any other connection (table list, column types, sample data)

**Sprint 28 — M14d: Federation layer + M16d: Multi-connection Canvas:**
- `aughor/connectors/federated.py` — `FederatedConnection`: DuckDB `ATTACH` for Postgres; view-copy for S3/file connectors; materialized working sets for BigQuery/Snowflake
- Schema context emits namespaced tables + cross-namespace join hints (reuses 2i fuzzy join inference)
- Query router: single-namespace → native connector; multi-namespace → federated DuckDB
- `POST /connections/federate` API + "Create Federated View" in catalog UI
- M16d: lift `len(scopes) == 1` constraint; `resolve_canvas_connection()` returns `FederatedConnection` when multiple scopes present; Canvas creation UI becomes multi-connection

**Sprint 29 — M14e: API connectors:**
- `aughor/connectors/api/base_sync.py` — `RestApiSync` base: incremental state in `data/sync_{id}.json`, OAuth token refresh, bulk API rate limiting, cursor pagination
- Salesforce: SOQL bulk query; Account/Contact/Opportunity/Lead/Case; custom fields via `describe()`
- HubSpot: CRM objects API v3; contacts/companies/deals
- Stripe: Events + Charges + Customers; cursor-based pagination
- All under optional `[crm]` dep group: `uv pip install -e ".[crm]"`

**Sprint 30 — M14f: Knowledge connectors:**
- `aughor/connectors/knowledge/confluence.py` — space sync via Confluence REST API; HTML-to-text; feeds existing `aughor_documents` Qdrant collection (M13d infrastructure unchanged)
- `aughor/connectors/knowledge/notion.py` — page/database export via Notion API v1; block-to-text
- `DocumentUploader.tsx` extended with "Connect Confluence / Notion" live sync option
- Optional `[knowledge-sync]` dep group

**Sprint 31 — M6 Enterprise Security (full):**
- FastAPI OAuth2/OIDC middleware (`python-jose` + `authlib`); `user_id` scoping on investigations, connections, Canvas (row-level in SQLite stores)
- RBAC: viewer / analyst / admin roles; connection-level + Canvas-level permissions; Inbox role-scoping
- `VaultBackend` in `aughor/db/registry.py` — HashiCorp Vault credential backend for production deployments
- Canvas ownership + sharing: `owner_user_id`, `shared_with: list[str]` on `Canvas` model

**Sprint 32 — M15: Action Hub:**
- `aughor/actions/models.py` + `executor.py` — `ActionTrigger` model; async `httpx` webhook dispatch with retry; logs result to audit trail
- `GET/POST/PUT/DELETE /actions/triggers` + `POST /investigations/{inv_id}/recommendations/{rec_id}/execute { trigger_id }`
- `web/components/ActionHubPanel.tsx` — configure webhook integrations (Slack / Jira / Zapier / custom HTTP); "Execute →" button in `RecommendationCard` alongside "Mark Done"

**Sprint 33 — M16e: Org Intelligence Layer:**
- `org_intelligence` Qdrant collection; promotion pipeline: `promoted_to_org=True` → embed + upsert to org collection
- "Org Intelligence" tab visible to all users; `{org_intelligence_section}` injected into ADA synthesis across all Canvases
- Auto-promotion threshold (N Canvas investigations confirming same pattern with confidence > threshold) — deferred to follow-on sprint

**Sprint 34 — Analytical depth:**
- M4 Prophet forecasting: `forecast_anomaly()` in `aughor/tools/stats.py`; trend context in ADA synthesis ("underlying problem started 3 weeks ago"); activates when series length > 30 points
- M2d Events Calendar: `data/events.yaml`; `lookup_events(start, end)` tool node in agent; prevents promo drops flagged as anomalies

**Sprint 35 — Quality gates:**
- M10 LLM Evals (Braintrust): 50-question golden dataset from investigation history; `verdict_accuracy`, `query_efficiency`, `hallucination_rate` scorers; CI gate on every PR touching `aughor/agent/`
- M7 Observability (Langfuse + OpenTelemetry): trace per investigation with `hypothesis_id` metadata; `trace_id` in SSE start event; most valuable now that cloud LLM calls have real token costs

---

## External Audit — Findings & Roadmap Response

*Source: independent LLM audit of the full repo (May 2026). Summary: architecture and ambition are strong; reliability guardrails are not yet proportionate to the surface area. Every concrete finding below is confirmed.*

---

## Milestone R — Reliability Baseline ⚡ IMMEDIATE PRIORITY

**Do this before any new feature work.** These are confirmed bugs and hygiene issues that degrade trust in the platform and block deployment.

**Sprint R1 — Bugs + hardening:**

### R1a — Fix Explorer Recursion Bug
**Finding:** `aughor/explorer/agent.py` calls `self._save_state()` inside itself for non-canvas explorers instead of `_store.save(...)`. This means every save in a non-canvas context silently re-enters the method — potential infinite recursion or state corruption on large schemas.

**Fix:**
- `aughor/explorer/agent.py` — audit all `self._save_state()` calls; replace non-canvas invocations with the correct `_store.save(conn_id, state)` call pattern used by canvas explorers
- Add a unit test: `test_save_state_does_not_recurse()` — monkeypatch `_store.save` and assert it is called exactly once per `_save_state()` invocation

**Files:** `aughor/explorer/agent.py`, `tests/test_explorer.py` (new)

---

### R1b — Replace Hardcoded localhost:8000
**Finding:** `const BASE = "http://localhost:8000"` appears in at least 6 component files — `RecommendationInbox.tsx`, `ActionHubPanel.tsx`, `CatalogScreen.tsx`, and others. This makes the frontend non-deployable without a code change.

**Fix:**
- Add `NEXT_PUBLIC_API_URL` to `web/.env.local.example` (default: `http://localhost:8000`)
- Create `web/lib/config.ts` — `export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"`
- Global find-and-replace: `const BASE = "http://localhost:8000"` → `import { API_BASE } from "@/lib/config"` + use `API_BASE`
- Add `NEXT_PUBLIC_API_URL` to `start.sh` and deployment docs

**Files:** `web/lib/config.ts` (new), all components with hardcoded BASE, `web/.env.local.example`

---

### R1c — Fix Lint Errors (42 errors, 52 warnings)
**Finding:** `npm run lint` produces 42 errors. This signals accumulated technical debt and makes the codebase harder to reason about — particularly dangerous for a codebase this size.

**Fix:** Run `npm run lint 2>&1 | head -100` to triage. Priority order:
1. `no-unused-vars` / `@typescript-eslint/no-unused-vars` — delete dead imports
2. `react-hooks/exhaustive-deps` — add missing deps or `// eslint-disable-line` with justification
3. `@typescript-eslint/no-explicit-any` — replace top offenders with proper types
4. Remaining warnings — convert to proper patterns or explicitly suppress with reason

**Files:** Various `web/components/*.tsx` and `web/app/*.tsx`

---

### R1d — Configurable CORS
**Finding:** `allow_origins=["*"]` is wide open. Fine for local dev; a security gap for any shared or multi-tenant deployment.

**Fix:**
- Add `AUGHOR_CORS_ORIGINS` env var (comma-separated, default `*` for backward compat)
- `aughor/api.py` — parse `AUGHOR_CORS_ORIGINS`; if set and not `*`, use explicit list
- Document in `.env.example`: `AUGHOR_CORS_ORIGINS=http://localhost:3000,https://your-domain.com`

**Files:** `aughor/api.py`, `.env.example`

---

### R1e — Minimal Bearer Token Auth
**Finding:** No auth visible anywhere. Any endpoint is callable by anyone who can reach port 8000.

**Fix (lightweight, not full RBAC):**
- Add `AUGHOR_API_KEY` to `.env.example`
- FastAPI dependency `verify_api_key(x_api_key: str = Header(...))` — if `AUGHOR_API_KEY` is set in env, all non-GET endpoints require the matching header; if unset, auth is skipped (maintains local dev ergonomics)
- Frontend: `web/lib/config.ts` — `API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? ""`; all `fetch()` calls include `X-Api-Key` header when non-empty

**Files:** `aughor/api.py`, `web/lib/config.ts`, `.env.example`

---

### R1f — Fix Stale hermes/* References
**Finding:** Docs and some env var names still reference the old `hermes/` path and `HERMES_*` env var prefix. The code now uses `aughor/` and `AUGHOR_*`.

**Fix:**
- Grep for `hermes/`, `HERMES_`, `hypothesis-engine` in `*.md`, `*.txt`, `.env.example`
- Replace with `aughor/`, `AUGHOR_*`, `aughor`
- Update `ROADMAP.md` shipped items table (lines 11–79) where `hermes/*.py` is cited

**Files:** `README.md`, `ROADMAP.md`, `.env.example`, any other docs

---

## Milestone R3 — Feature Reachability

**Finding:** A systematic audit of `web/components/` revealed that 9 components are fully built and functional but are either completely unreachable from any nav item, or buried so deep (4–5 clicks) that they are functionally invisible. These are not planned features — they are **shipped features that deliver no value because users cannot reach them.** Fixing this is the highest-ROI sprint in the roadmap: no backend work, no new code, just wiring existing components into the render tree.

**Why this sprint comes before R2 (tests):** Tests protect against regression. But if features are already unreachable, there is nothing to protect. Reachability first; then add tests to guard what you just unlocked.

---

### R3a — Investigation Transparency (ThinkingTrace + HypothesisCard + FeedbackPrompt)

**The problem:** `useInvestigation.ts` streams real-time agent state — hypotheses forming, SQL queries running, evidence scoring, verdict assignment. This state is tracked in full (`hypotheses[]`, `statsPerHypothesis`, phase events). Three components are built to render it. None are mounted.

- **`ThinkingTrace.tsx`** — Renders the full `InvestigationState`: phases completed, hypotheses being tested, reasoning log. Shows the agent "thinking" in real time. Takes `{ state: InvestigationState }` — state already exists in `ChatPanel`'s `useInvestigation` hook.
- **`HypothesisCard.tsx`** — Visual card per hypothesis: text, confidence bar, verdict badge. Renders from `state.hypotheses[]` which populates on every SSE `hypotheses` event.
- **`FeedbackPrompt.tsx`** — After the final report renders, lets users mark each hypothesis as confirmed / refuted / needs context. Calls `POST /investigations/{id}/feedback` which is already wired in `useInvestigation.ts` line 289.

**Files to modify:**
- `web/components/ChatPanel.tsx` — add `<ThinkingTrace state={state} />` inside the streaming phase block (collapsible, expanded while streaming); add `<HypothesisCard>` rendering per `state.hypotheses` entry; add `<FeedbackPrompt>` at the end of the last turn when `state.streaming === false && state.hypotheses.length > 0`

**What unlocks:** Users see the agent reasoning. They see hypotheses form and resolve. They can validate or dispute conclusions. This is the transparency layer that makes Aughor an auditable analyst rather than a black box.

---

### R3b — Metrics Panel Standalone Route

**The problem:** Metrics are a top-level platform concept — the metric catalog is what makes Aughor's SQL semantically governed rather than ad-hoc. But `MetricsPanel.tsx` is only reachable via: Canvases → open a canvas → Configure → Instructions tab → Metrics sub-tab. Five steps, canvas-only. A user who doesn't use canvases cannot access metrics at all.

**Fix:** Add a `"metrics"` tab to `NavTab` and `NAV_GROUPS`. Mount `<MetricsPanel />` at `tab === "metrics"`. The component takes no required props.

**Files to modify:**
- `web/app/page.tsx` — add `"metrics"` to `NavTab` type; add `{ id: "metrics", icon: "metric", label: "Metrics", group: null }` to `NAV_GROUPS`; add render block `{tab === "metrics" && <MetricsPanel />}`; add `metric` icon path to `ICON_PATHS`

**What unlocks:** Users can define, browse, and edit metric definitions from the main nav. Every investigation that references a metric now has a governed formula behind it.

---

### R3c — Document Upload Outside Canvas

**The problem:** `DocumentUploader.tsx` handles PDF/CSV knowledge uploads — this is how Aughor learns institutional knowledge beyond the schema. Currently it's only reachable via `CanvasWorkspace → Configure → Data tab`. There is no path to document upload from the main chat view.

**Fix:** Add a "Knowledge" tab to the `ConnectionsScreen`. Documents are per-connection (a PDF about your e-commerce schema belongs with that connection), so this placement is semantically correct.

**Files to modify:**
- `web/app/page.tsx` → `ConnectionsScreen` — add a `"knowledge"` sub-tab to the right panel alongside the existing connection detail view; mount `<DocumentUploader />` when that sub-tab is active
- `web/components/DocumentUploader.tsx` — verify it accepts an optional `connId` prop for scoping uploads (add if missing)

**What unlocks:** Any user can upload a document from the Connections screen in 2 clicks. Aughor's knowledge augmentation becomes a first-class feature rather than a canvas-only secret.

---

### R3d — ERD and Schema Panel in Catalog

**The problem:** `ERDiagram.tsx` renders an interactive entity-relationship diagram for a connection's schema. `SchemaPanel.tsx` wraps it in a full browser with column types and row counts. Neither is reachable from any nav item. The Catalog screen shows tables and columns in list form — the ERD view would be the most useful visual for understanding a new database.

**Fix:** Add a "ERD" view toggle to `CatalogScreen` — a button that switches the right panel from the list view to `<SchemaPanel connId={selectedConn} />`. `SchemaPanel` already imports and renders `ERDiagram`.

**Files to modify:**
- `web/components/CatalogScreen.tsx` — add view toggle (`List | ERD`); import `SchemaPanel`; render `<SchemaPanel connId={selectedConn} connName={sel.name} />` when ERD view is active

**What unlocks:** One-click ERD view of any connected database from the Catalog tab. Essential for data exploration and onboarding new connections.

---

### R3e — Configure Panel from Main Chat

**The problem:** `ConfigurePanel.tsx` has four tabs: About (connection metadata), Data (document upload), Instructions (system prompt for the agent), Docs. It is only mounted in `CanvasWorkspace`. Users in the main chat view cannot set a system instruction, upload a document, or see connection metadata without first creating a canvas.

**Fix:** Add a "Configure" icon button to the main `ChatPanel` header. It opens `ConfigurePanel` as a slide-over (same pattern as `CanvasWorkspace`). Pass the current `selectedConn` as `connectionId`.

**Files to modify:**
- `web/components/ChatPanel.tsx` — add configure button to header; add `showConfigure` state; render `<ConfigurePanel connectionId={connectionId} ... onClose={() => setShowConfigure(false)} />` when active

**What unlocks:** System instructions, document upload, and connection metadata are accessible from the primary product surface. Any chat session can be configured without knowing what a canvas is.

---

### R3f — Cleanup: Orphaned Components and Nav Duplication

**Orphaned components to delete** (confirmed superseded, safe to remove):
- `web/components/ConnectionsPanel.tsx` — predates `ConnectionsScreen` in `page.tsx`; same functionality, different implementation
- `web/components/CatalogPanel.tsx` — predates `CatalogScreen`; if `CatalogScreen` covers all use cases, delete
- `web/components/SchemaCards.tsx` — commented out inside `SchemaPanel`; was superseded by `ERDiagram`

**Nav duplication:**
- `RecentsScreen` (Recents nav tab) and `HistoryPanel` (slide-over from topbar clock) both fetch `GET /investigations` and render history. Consolidate: keep `HistoryPanel` as the primary surface (it has richer detail); have the Recents nav tab mount `HistoryPanel` directly rather than `RecentsScreen`.

**Nav icon duplication:**
- "Health" and "Activity Log" both use the `activity` icon (`M22 12h-4l-3 9...`). Add a distinct icon for Health — a heartbeat/pulse or a shield — so they're visually distinguishable.

**Files to modify:**
- `web/app/page.tsx` — update Recents to mount `HistoryPanel`; add distinct `health` icon path
- Delete: `ConnectionsPanel.tsx`, `CatalogPanel.tsx`, `SchemaCards.tsx` (after verifying no other references)

---

**New deps:** None — all fixes use existing components and hooks.
**Dependency on:** R1 (hardcoded URLs should be fixed first so components that fetch data work correctly after mounting)
**Sprint:** 37 — immediately after R1

---

## Milestone R2 — Test Infrastructure

**No test files exist in the repo.** This is the single biggest compounding risk: every sprint adds surface area with no regression protection. Tests don't need to be comprehensive to add value — even 20 smoke tests catch the worst class of regressions.

**Sprint R2 — Smoke tests:**

### R2a — Backend Smoke Tests (pytest)

**Files to create:**
- `tests/__init__.py`
- `tests/conftest.py` — shared fixtures: test DuckDB path, test connection ID, FastAPI `TestClient`
- `tests/test_api_smoke.py` — 10 tests:
  - `test_health_endpoint_returns_200()`
  - `test_list_connections_returns_list()`
  - `test_get_schema_for_builtin_connection()`
  - `test_post_query_run_executes_select()`
  - `test_post_investigations_creates_record()`
  - `test_get_metrics_returns_list()`
  - `test_get_ontology_returns_graph()`
  - `test_security_check_blocks_drop()`
  - `test_security_check_allows_select()`
  - `test_exploration_status_returns_phase()`
- `tests/test_explorer.py` — recursion fix verification (R1a), state save isolation
- `tests/test_connection.py` — DuckDB/Postgres execute, `_validate()`, `bulk_read()` fallback

**New deps:**
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0.0", "httpx>=0.27.0", "pytest-anyio>=0.0.0"]
```

**CI gate:** `uv run pytest tests/ -x -q` must pass on every PR.

---

### R2b — Frontend Component Tests (Vitest)

**Files to create:**
- `web/src/test/setup.ts` — Vitest + Testing Library setup
- `web/src/test/QueryBuilder.test.tsx` — buildSql() pure function tests (no render required); 8 cases: single table, multi-table with JOIN, GROUP BY, filters, ORDER BY, COUNT DISTINCT, custom expression, no measures → `SELECT *`
- `web/src/test/api.test.ts` — mock `fetch`; assert `runDirectQuery` serializes body correctly; assert `buildQuerySql` posts correct params

**New deps:**
```json
"devDependencies": {
  "vitest": "^1.0.0",
  "@testing-library/react": "^14.0.0",
  "@testing-library/user-event": "^14.0.0"
}
```

---

## Milestone M17 — API Router Refactor

**Problem:** `aughor/api.py` is 3,200+ lines and growing every sprint. It owns chat, investigations, canvases, connections, documents, ontology, actions, security, sync, query builder, and more in a single file. This makes it hard to reason about, test, and eventually extract into services.

**Goal:** Split into `aughor/routers/` without any behavior changes. This is pure organizational refactoring — no new functionality.

**Target structure:**
```
aughor/routers/
├── __init__.py
├── connections.py     # GET/POST/DELETE /connections, /schema, /sample, /freshness
├── investigations.py  # POST /investigate, /chat, GET /investigations, outcomes
├── canvas.py          # CRUD /canvases, /canvases/{id}/history|schema|suggestions
├── query.py           # POST /query/run, /query/build-sql, /query/cache
├── exploration.py     # /exploration/{conn_id}/status|findings|domains|episodes|retry
├── ontology.py        # GET/PUT /ontology, /entities, /relationships, /actions, /metrics
├── knowledge.py       # /documents/upload|list|delete, /connections/{id}/knowledge-sync
├── actions.py         # /actions/triggers CRUD, /recommendations/execute, /logs
├── security.py        # /security/audit|budget|check
├── metrics.py         # /metrics CRUD, /health-scorecard
├── catalog.py         # /catalog/tree
└── system.py          # /health, /dev/stats, /suggestions, /connectors/types
```

**Files to create/modify:**
- `aughor/routers/` — 12 router files, each a `fastapi.APIRouter` with `prefix` and `tags`
- `aughor/api.py` — reduced to app initialization, middleware, startup events, and `include_router()` for each module; target < 200 lines
- No endpoint paths change; no client-side changes needed

**Migration strategy:** Extract one router at a time, run smoke tests after each, merge when green.

**Dependency on:** R2a smoke tests (to catch regressions during refactor)

---

## Milestone M18 — Navigation Redesign ✅ SHIPPED (Sprint 43)

**Problem:** The current left nav has 12+ items at a flat level — Canvases, Recents, Ontology, Domain Intel, Inbox, Activity, Health, Playbook, Query Builder, Action Hub, Catalog, Settings. This is an expert console, not a product. It forces users to know Aughor's internal architecture rather than expressing their intent.

**Goal:** Reorganize into 5 intent-based sections that answer: *"What does Aughor know, why does it believe it, and what should I do next?"*

**Target navigation structure:**

| Section | Items | User intent |
|---|---|---|
| **Ask** | Chat, Canvases | "I want to ask a question or work in a scoped context" |
| **Investigations** | History, Rec. Inbox | "I want to see what Aughor has found and act on it" |
| **Intelligence** | Domain Intel, Ontology, Health, Playbook | "I want to understand what Aughor knows about my data" |
| **Data Map** | Catalog, Query Builder | "I want to explore or query my data directly" |
| **Governance** | Connections, Action Hub, Security/Audit, Settings | "I want to configure, control, and govern the platform" |

**Files to modify:**
- `web/app/page.tsx` — `NAV_GROUPS` restructured into 5 groups with `group` labels; `NavTab` type updated; group headers rendered with separators
- Recents removed as a standalone item — surfaced within Ask (recent canvases) and Investigations (recent history)
- Activity Log moved under Governance (it's an audit/ops concern, not a user-facing intelligence surface)

**UX principles:**
- Every section header answers a question, not a system noun
- Depth is hidden behind the primary surface — Ontology is a detail under Intelligence, not a nav peer of Chat
- The home screen defaults to **Ask** with the investigation-input centered, health scorecard inline, and recent investigations below

---

### Phase M18b — Ask Screen as Hero Workflow

**Problem today:** The chat input is a small centered widget. The primary workflow of the product — asking a question and getting an investigation — feels like a secondary panel, not a hero surface.

**Redesign:**
- Investigation input becomes full-width, prominent, vertically centered in the viewport when empty
- Placeholder text rotates through task-oriented prompts: "What drove revenue decline in Q3?", "Compare refund rates by region", "Which customers are at churn risk?"
- Health scorecard renders inline below the input (not in a separate tab) — the executive always sees the current state of the business alongside the prompt
- Recent investigations listed as cards immediately below with claim snippets and outcome badges
- Suggested follow-up actions surface as chips when an investigation exists ("Explore by segment", "Set a monitor", "Export to canvas")

**Files to modify:**
- `web/app/page.tsx` — Ask tab content: `<AskHeroInput>` replacing current compact input; `<InlineHealthScorecard>` component; `<RecentInvestigationCards>` list
- `web/components/AskHeroInput.tsx` (NEW) — full-width textarea with rotating placeholder, inline connection selector, submit button; keyboard shortcut (Enter to submit, Shift+Enter for newline)

---

### Phase M18c — Command Palette (⌘K)

**Why it belongs in M18:** The command palette is the interaction layer that makes the 5-section navigation feel fast. Users in a dense analytical tool stop navigating menus and start commanding. Without it, the nav redesign is structural but not behavioral.

**What it does:**
- Global ⌘K / Ctrl+K keyboard shortcut opens a full-screen overlay
- Before typing: shows recent items grouped by type (recent investigations, recent tables, pinned metrics)
- While typing: fuzzy-matches across:
  - **Tables** — from all connected schemas (shows connection name + row count)
  - **Metrics** — from metric catalog (shows formula snippet)
  - **Investigations** — recent history (shows claim snippet + outcome badge)
  - **Canvases** — open canvases
  - **Actions** — nav destinations ("Go to Governance", "Open Catalog", "New Canvas")
- Arrow keys navigate, Enter activates, Escape closes
- Results grouped with section headers and type icons
- Match highlights the typed characters in results

**Files to create:**
- `web/components/CommandPalette.tsx` — modal overlay; `useFuse(items, query)` hook for fuzzy search; keyboard navigation with `useEffect` listener; grouped result renderer with type icons
- `web/hooks/useCommandPalette.ts` — global state: `open`, `query`, `setOpen`, `setQuery`; provides `useCommandPalette()` hook

**Files to modify:**
- `web/app/page.tsx` — mount `<CommandPalette>` at root; attach `useEffect(() => { window.addEventListener("keydown", ...) })` for ⌘K; pass schema/metrics/history as props

**New deps:**
```json
"fuse.js": "^7.0.0"
```

**Dependency on:** M18a (nav structure), M22 (design system — palette uses design tokens for styling)

---

## Milestone M22 — Design System Consolidation ✅ SHIPPED (Sprint 42)

**Files changed (7):**
- `web/styles/tokens.css` *(new)* — all CSS custom properties extracted; dark + light mode; Tailwind bridge
- `web/styles/type.css` *(new)* — `.aug-text-h1/h2/h3/ui/sm/xs/mono`; `.aug-label` corrected to 11px
- `web/app/globals.css` — imports new files; structural classes remain; nav-group font fixed 10→11px
- `web/components/ConfigurePanel.tsx` — full zinc→token migration; `aug-input`/`aug-btn`/`aug-label` applied
- `web/components/InvestigationReport.tsx` — inline hex → CSS vars; rounded-xl → rounded-md
- `web/components/EntityCard.tsx` + `HistoryPanel.tsx` + `ExplorationReport.tsx` + `DocumentUploader.tsx` + `ProcessHealthPanel.tsx` + `CatalogScreen.tsx` + `ActivityLog.tsx` + `PlaybookPanel.tsx` + `ExplorationPanel.tsx` — radius + font + hex audit

**Problem (solved):** The current UI uses at least four styling systems simultaneously — `aug-*` CSS tokens, Tailwind `zinc-*` classes, hardcoded hex values (`#11171d`, `#1c2530`, etc.), and inline styles. Individual components can look polished; together they look like multiple products stitched together. Visual consistency cannot be achieved incrementally — it requires a single, deliberate pass.

**Goal achieved:** One token file. One type scale. One radius vocabulary. No font below 11px. Inline hex replaced by CSS vars.

---

### Phase M22a — Token File & CSS Custom Properties

**Create `web/styles/tokens.css`** as the single source of truth, replacing all hardcoded values:

```css
:root {
  /* Backgrounds — 3 elevation levels */
  --bg-base:    #0d1117;   /* page background */
  --bg-surface: #161b22;   /* panels, sidebars */
  --bg-raised:  #1c2128;   /* cards, dropdowns */
  --bg-overlay: #21262d;   /* tooltips, modals */

  /* Text */
  --text-primary:   #e6edf3;   /* headings, values */
  --text-secondary: #8b949e;   /* labels, metadata */
  --text-muted:     #6e7681;   /* timestamps, hints */
  --text-disabled:  #484f58;

  /* Borders */
  --border-default:  #30363d;
  --border-muted:    #21262d;
  --border-emphasis: #6e7681;

  /* Accent — one intelligence blue */
  --accent:         #388bfd;
  --accent-subtle:  #1f3a6b;
  --accent-muted:   #0d2a5e;

  /* Status — meaning only, never decoration */
  --status-green:   #3fb950;
  --status-amber:   #d29922;
  --status-red:     #f85149;
  --status-green-subtle: #0f2a1b;
  --status-amber-subtle: #2f1e05;
  --status-red-subtle:   #2d0c0c;

  /* Type scale */
  --t-page:    24px;   /* page titles */
  --t-section: 16px;   /* section headers */
  --t-body:    13px;   /* primary reading size */
  --t-cell:    12px;   /* tables, list items */
  --t-meta:    11px;   /* timestamps, counts, badges — minimum */

  /* Radius */
  --r-control: 4px;    /* chips, badges, table rows, buttons */
  --r-panel:   6px;    /* cards, panels, dropdowns */
  --r-modal:   10px;   /* modals, overlays only */

  /* Spacing — standard 4-based scale */
  --space-1:  4px;
  --space-2:  8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  /* Font */
  --font-ui:   'Geist', 'Inter', system-ui, sans-serif;
  --font-mono: 'Geist Mono', 'JetBrains Mono', ui-monospace, monospace;
}
```

**Rule:** Monospace (`--font-mono`) applies only to SQL editors, query output values, connection IDs, timestamps in code contexts. All other text uses `--font-ui`.

**Files to create:**
- `web/styles/tokens.css` — all variables above
- `web/styles/type.css` — utility classes: `.t-page`, `.t-section`, `.t-body`, `.t-cell`, `.t-meta` with correct `font-size`, `line-height`, `font-weight` per level

**Files to modify:**
- `web/app/layout.tsx` — import `tokens.css` and `type.css` at root
- `web/tailwind.config.ts` — extend `theme.colors`, `theme.borderRadius`, `theme.fontSize`, `theme.fontFamily` to reference the CSS variables so Tailwind utilities like `text-accent`, `bg-surface`, `rounded-panel` work alongside raw CSS

---

### Phase M22b — Component Audit & Token Migration

**Scope:** Every component file in `web/components/` audited and migrated. Priority order (highest visual impact first):

1. `page.tsx` — navigation sidebar, tab rendering, global layout shell
2. `QueryBuilder.tsx` — most recently written; already partially uses tokens
3. `HistoryDetailPanel.tsx`, `CatalogScreen.tsx`, `OntologyGraph.tsx`
4. All remaining components

**Migration rules enforced:**
- No `#xxxxxx` hex values in component files
- No `rgba(...)` outside `tokens.css`
- No font sizes below `--t-meta` (11px)
- No `border-radius` values other than `var(--r-control)`, `var(--r-panel)`, `var(--r-modal)`
- No `rounded-xl`, `rounded-2xl` (Tailwind classes that exceed the vocabulary)
- `zinc-*` Tailwind classes replaced with semantic equivalents (`bg-surface`, `text-secondary`, etc.)

**Lint enforcement:** Add an ESLint rule or a simple grep-based CI check that fails on hardcoded hex in component files.

---

### Phase M22c — Typography Enforcement

**Type scale applied globally:**

| Context | Token | Size | Weight |
|---|---|---|---|
| Page title | `--t-page` | 24px | 600 |
| Section / panel header | `--t-section` | 16px | 600 |
| Body copy, descriptions | `--t-body` | 13px | 400 |
| Table cells, list items | `--t-cell` | 12px | 400 |
| Metadata (timestamps, counts, badges) | `--t-meta` | 11px | 400 |

**What gets removed:** The current 9px, 9.5px, 10px, 10.5px, 10.75px, 11.5px sizes. Anything that used sub-11px moves to `--t-meta`. Anything unclear goes to `--t-cell`.

**Files to modify:** Global pass on all components — replace inline `fontSize` and `text-[Npx]` Tailwind classes with `.t-*` utility classes.

---

**New deps:**
```json
"geist": "^1.3.0"
```
(or rely on system `Inter` — decision at sprint start)

**Dependency on:** R1c (lint pass reduces noise before token audit); should land in Sprint 41, **before** M18b/M18c so those components are built on the design system from the start.

---

## Milestone M19 — Evidence Ledger ✅ SHIPPED (Sprint 44)

**Goal:** Make every claim Aughor produces a first-class, inspectable object with full provenance. This transforms Aughor from an "answer generator" into an "auditable intelligence memory."

**The problem today:** Aughor produces findings as strings in a report. There is no way to answer: "What SQL backed that claim?", "Which metric definition was used?", "How fresh was the data?", "Has anyone validated this?". The claim evaporates when the investigation report closes.

**Evidence Ledger model:**

```python
class EvidenceClaim(BaseModel):
    id: str
    investigation_id: str
    hypothesis_id: Optional[str]
    claim_text: str                          # "Revenue declined 12% in Q3"
    sql_source: Optional[str]               # The exact SQL that produced this number
    metric_used: Optional[str]              # Metric catalog name if applicable
    data_freshness: Optional[str]           # ISO timestamp of latest data point used
    confidence: float                        # 0.0–1.0 from scoring node
    created_at: str
    # Feedback loop
    owner_feedback: Optional[Literal["validated","disputed","needs_context"]]
    feedback_note: Optional[str]
    # Downstream
    downstream_recommendations: list[str]   # rec IDs derived from this claim
    outcome_status: Optional[Literal["acted_on","superseded","archived"]]
```

**Files to create:**
- `aughor/evidence/__init__.py`
- `aughor/evidence/models.py` — `EvidenceClaim` model
- `aughor/evidence/store.py` — `append_claim()`, `get_claims_for_investigation()`, `get_claims_for_metric()`, persists to `data/evidence_ledger.db` (SQLite, append-only)
- `aughor/evidence/linker.py` — `extract_claims_from_report(report, investigation_id) → list[EvidenceClaim]`; parses `key_findings` and `recommended_actions` from `AnalysisReport`; links to `hypothesis_id` and SQL via `QueryResult` history

**Files to modify:**
- `aughor/agent/investigate.py` — after synthesis, call `extract_claims_from_report()` + `store.append_claim()` for each finding
- `aughor/api.py` (or `aughor/routers/investigations.py`) — `GET /investigations/{id}/evidence` returns all claims; `POST /investigations/{id}/evidence/{claim_id}/feedback` accepts owner validation
- `web/lib/api.ts` — `getEvidenceClaims(invId)`, `submitClaimFeedback(invId, claimId, feedback)`
- `web/components/HistoryDetailPanel.tsx` — "Evidence" tab alongside existing Summary tab; shows claim cards with SQL toggle, metric badge, freshness timestamp, and Validate/Dispute buttons

**Why this is the right next data model:** Every other Aughor capability (playbook, causal graph, outcome tracking, monitors) becomes more powerful when grounded in verifiable evidence. The playbook entry "review return policy" is more credible when it cites `EvidenceClaim#42: refund_rate=14.2%, source: SELECT...`. The causal edge `discount_depth → revenue` carries more weight when 3 evidence claims back it.

---

## Milestone M20 — Proactive Monitors ✅ SHIPPED (Sprint 45)

**Goal:** Aughor should volunteer problems before users ask questions. The health scorecard (M13a ✅) shows current metric status on demand. Monitors make that continuous — running on a schedule and alerting when something changes.

**This is what "always thinking" looks like to the user:** "Aughor noticed your refund rate crossed 10% for the first time since March. Here's what changed."

### Phase M20a — Metric Monitors (cron-based)

**What:** Schedule health scorecard checks on a configurable cadence. Compare current value to previous run. Alert when a metric crosses a threshold or the trend reverses.

**Files to create:**
- `aughor/monitors/__init__.py`
- `aughor/monitors/models.py` — `Monitor(BaseModel)`: `id`, `conn_id`, `metric_name`, `check_cron: str` (cron expression), `alert_on: Literal["threshold_cross","trend_reversal","any_change"]`, `notification_channel: str`, `enabled: bool`; `MonitorAlert`: `monitor_id`, `triggered_at`, `metric_name`, `current_value`, `previous_value`, `threshold`, `message`
- `aughor/monitors/runner.py` — `run_monitor(monitor: Monitor, db) → MonitorAlert | None`; executes metric SQL, compares to last stored value, evaluates alert condition
- `aughor/monitors/scheduler.py` — APScheduler-backed job runner; loads enabled monitors on startup; fires `run_monitor()` per cron schedule; persists results to `data/monitor_alerts.db`

**Files to modify:**
- `aughor/api.py` / `aughor/routers/monitors.py` — `GET/POST/PUT/DELETE /monitors`, `GET /monitors/{id}/alerts`
- `aughor/api.py` startup event — load and schedule enabled monitors via `scheduler.start()`

**New deps:**
```toml
apscheduler>=3.10.0
```

---

### Phase M20b — Anomaly & Drift Monitors

**What:** Beyond threshold crossing — detect statistical anomalies and distribution shifts without the user configuring explicit thresholds.

**Monitor types:**
- **Anomaly monitor:** z-score + STL on 30-day metric history; alert when current value is > 2σ from seasonal trend (reuses existing `stats.py` infrastructure ✅)
- **Segment drift monitor:** detect when a metric's distribution across a dimension (region, category, cohort) shifts significantly; uses Chi-squared test on distribution buckets
- **Data freshness monitor:** alert when `MAX(updated_at)` on a key table hasn't advanced within the expected SLA window

**Files to modify:**
- `aughor/monitors/runner.py` — `run_anomaly_monitor()`, `run_drift_monitor()`, `run_freshness_monitor()` as specializations of the base runner
- `aughor/tools/stats.py` — `detect_segment_drift(current_dist, baseline_dist) → DriftResult`; wraps Chi-squared test

---

### Phase M20c — Overnight Intelligence Digest

**What:** A scheduled weekly (or daily) summary of what the background explorer discovered, what causal edges were confirmed, and which metrics moved. The "things Aughor learned overnight" experience.

**Format:**
```
Aughor Weekly Intelligence Brief — week of May 26

📊 Metric changes this week:
  • Refund Rate: 14.2% → 9.8% (↓ improving, below warning threshold)
  • Order Volume: flat (within ±2% of 7-day baseline)

🔍 New domain insights:
  • Discovered that orders with freight_value > 50 have 3× higher return rate
  • New causal edge confirmed: shipping_delay → review_score (3 evidence points)

⚠ Active monitors:
  • Revenue (beautycommerce): GREEN — no anomalies
  • Customer Churn (olist): YELLOW — above warning threshold for 3 days

💡 Top open recommendations:
  • "Review return policy window for high-value orders" — 5 days pending
```

**Files to create:**
- `aughor/monitors/digest.py` — `build_weekly_digest(conn_id, db) → str` (Markdown); aggregates monitor alerts, new exploration insights, new causal edges, open recommendations
- `aughor/api.py` — `GET /monitors/digest?conn_id=&period=week` returns digest text

**Files to modify (web):**
- `web/app/page.tsx` home screen — "Latest from Aughor" card renders the most recent digest; refreshes on mount; collapsible

---

## Milestone M21 — Metrics as Semantic Contracts

**Goal:** Elevate metrics from SQL formulas to governed semantic contracts — the layer where Aughor definitively beats generic agents. A governed metric doesn't just have a formula; it has an owner, a freshness SLA, quality tests, lineage, and documented caveats about when it's wrong.

**The difference this makes:** An investigation that references `refund_rate` should know: (a) the approved formula, (b) that it excludes marketplace returns, (c) that it's only reliable after day+3 due to processing lag, (d) that Finance uses a different definition that includes pending disputes. Aughor should surface all of this automatically — not derive it from scratch.

**Extended `MetricDefinition` model:**

```python
class MetricDefinition(BaseModel):
    # Existing fields
    name: str
    label: str
    sql: str
    tables: list[str]
    dimensions: list[str]
    filters: list[str]
    unit: Optional[str]
    caveats: Optional[str]
    # Health scorecard (M13a ✅)
    target_value: Optional[float]
    warning_threshold: Optional[float]
    critical_threshold: Optional[float]
    target_period: Optional[str]
    benchmark_source: Optional[str]
    # NEW — governance fields
    owner: Optional[str]                    # "Revenue team" or "alice@company.com"
    freshness_sla: Optional[str]            # "daily by 6am UTC" — description
    freshness_check_sql: Optional[str]      # SQL that returns the latest data timestamp
    quality_tests: list[str]                # SQL assertions; fail = metric flagged unreliable
    lineage: list[str]                      # Source tables + transformation descriptions
    wrong_usage_examples: list[str]         # Anti-patterns with explanations
    approved_by: Optional[str]              # Finance sign-off, etc.
    approved_at: Optional[str]
```

**Files to modify:**
- `aughor/semantic/metrics.py` — extend `MetricDefinition` with governance fields; `validate_metric(metric, conn) → list[str]` runs `quality_tests` SQL assertions; `check_freshness(metric, conn) → FreshnessResult`
- `aughor/api.py` / `aughor/routers/metrics.py` — `POST /metrics/{name}/validate` runs quality tests; `GET /metrics/{name}/freshness` returns last data timestamp vs SLA
- `web/components/MetricsPanel.tsx` — governance section in metric form: owner, freshness SLA, quality tests (textarea, one assertion per line), lineage, wrong usage examples; "Validate now" button runs quality tests inline
- `aughor/agent/prompts.py` / `CHAT_SQL_SYSTEM` — inject `wrong_usage_examples` for the referenced metric as "never compute X as Y" rules; inject `lineage` as context for table selection

**Schema injection update:**
When building schema context for a metric, the injected block expands to:
```
METRIC: refund_rate (Finance-approved)
  Formula: SUM(refund_amount) / SUM(order_amount) WHERE status != 'pending'
  Owner: Revenue team
  Freshness: reliable after day+3 (processing lag)
  ⚠ Excludes marketplace returns (use gross_refund_rate for total)
  ✗ NEVER: COUNT(refunds) / COUNT(orders) — ignores refund amounts
```

**Why this matters:** Any LLM agent can write SQL. Only Aughor can write *governed* SQL with the institutional knowledge baked in. This is the defensible moat.

**New deps:** none
**Dependency on:** M13a Health Scorecard ✅, M17 API Router (metrics now their own router)

---

## Milestone M23 — Charts & Data Visualization Layer

**Problem:** Charts in Aughor currently render when data exists and show nothing when it doesn't. The visual design is inconsistent across chart types, loading and error states are absent, chart colors don't follow any system, and axes are whatever the charting library defaults to. This makes the charts feel like implementation details rather than analytical surfaces.

**Goal:** Every chart in Aughor — in health scorecard, investigation reports, the query builder results pane, and ontology summaries — should feel analytically credible and visually deliberate.

**Dependency on:** M22 (design tokens — chart colors must come from the token system, not be hardcoded separately)

---

### Phase M23a — Unified Chart Wrapper

**Problem:** Each chart component handles its own loading, empty, and error states differently (or not at all).

**Create `web/components/charts/ChartWrapper.tsx`** — a layout shell that all charts render inside:

```typescript
interface ChartWrapperProps {
  title?: string
  subtitle?: string       // metric name, time range, etc.
  loading?: boolean
  error?: string | null
  empty?: boolean         // true when query returned 0 rows
  emptyMessage?: string
  height?: number         // default: 240
  actions?: ReactNode     // top-right corner slot (download, expand, type toggle)
  children: ReactNode
}
```

- **Loading state:** animated skeleton bars (not spinner) — matches the chart's expected shape (line skeleton for time series, bar skeleton for categoricals)
- **Empty state:** centered icon + "No data for this period" + optional suggestion link
- **Error state:** red-bordered panel with the error message and a "Retry" button
- **Title/subtitle:** standardized position, font sizes using `--t-cell` / `--t-meta`, `--text-secondary` color

**Files to create:**
- `web/components/charts/ChartWrapper.tsx`
- `web/components/charts/ChartSkeleton.tsx` — loading skeleton variants (line, bar, number)

---

### Phase M23b — Chart Color System

**Problem:** Chart series colors are hardcoded or pulled from a charting library's default palette (usually garish blues/greens/reds). They clash with Aughor's dark neutral palette.

**Aughor chart palette** (defined in `tokens.css`):

```css
:root {
  /* Primary series palette — calm, distinguishable on dark backgrounds */
  --chart-1: #388bfd;   /* intelligence blue — primary metric */
  --chart-2: #56d364;   /* green — positive comparison */
  --chart-3: #e3b341;   /* amber — secondary metric */
  --chart-4: #bc8cff;   /* violet — tertiary */
  --chart-5: #ff7b72;   /* coral — warning/negative */
  --chart-6: #79c0ff;   /* light blue — additional series */

  /* Threshold / reference lines */
  --chart-threshold-warn:   #d29922;
  --chart-threshold-crit:   #f85149;
  --chart-threshold-target: #3fb950;

  /* Axis and grid */
  --chart-axis:     #30363d;   /* axis lines */
  --chart-grid:     #21262d;   /* gridlines — subtle */
  --chart-tick:     #6e7681;   /* tick labels */
}
```

**Rule:** Chart components never hardcode colors. They reference `--chart-N` variables. The first series is always `--chart-1`; the comparison series is always `--chart-2`. Status lines use the threshold variables.

**Files to modify:**
- `web/styles/tokens.css` — add chart palette section
- All chart components — replace hardcoded colors with CSS variable references

---

### Phase M23c — Axis & Grid Styling

**Standardized axis treatment:**

| Element | Style |
|---|---|
| Axis lines | 1px solid `--chart-axis` |
| Gridlines | 1px solid `--chart-grid` (subtle — don't compete with data) |
| Tick labels | `--t-meta` (11px), `--chart-tick` color |
| Axis label | `--t-cell` (12px), `--text-secondary` |
| Value formatting | K/M/B suffixes for large numbers; 1 decimal for rates; no trailing zeros |
| X-axis density | Maximum 6 ticks on time axis; rotate 45° if labels overlap |

**Legend positioning:**
- Time series: legend above the chart, left-aligned, horizontal
- Bar/categorical: legend below, centered
- Pie/donut: legend right, vertical (only when ≤ 6 slices; else top-N + "Other")
- No legend when chart has only one series

**Files to modify:**
- All chart components — apply axis config object and legend placement rules

---

### Phase M23d — Chart Type Intelligence

**Problem:** Chart type is currently hardcoded per component. A metric's visualization type shouldn't be a deployment-time decision.

**Logic:** When rendering a `QueryResult`, the chart type selector evaluates:

```typescript
function inferChartType(columns: Column[], rows: Row[]): ChartType {
  const hasTimeCol = columns.some(c => c.type.includes("date") || c.type.includes("timestamp"))
  const hasCategoryCol = columns.some(c => c.type === "string" || c.type === "varchar")
  const numericCols = columns.filter(c => ["int","float","double","decimal"].some(t => c.type.includes(t)))

  if (hasTimeCol && numericCols.length >= 1) return "line"          // time series → line
  if (hasCategoryCol && numericCols.length === 1) return "bar"       // categorical → bar
  if (hasCategoryCol && numericCols.length >= 2) return "grouped-bar"
  if (numericCols.length === 2 && rows.length >= 10) return "scatter" // outlier detection
  return "table"  // fallback — always safe
}
```

**UI:** Small chart type toggle in the `ChartWrapper` actions slot — user can override inference. Persists per query result (not persisted to backend — session only).

**Files to create:**
- `web/components/charts/chartTypeInference.ts` — `inferChartType()` pure function
- `web/components/charts/ChartTypeToggle.tsx` — icon button group (line / bar / scatter / table)

**Files to modify:**
- `web/components/QueryBuilder.tsx` — `ResultsTable` becomes `ResultsPane` with `ChartWrapper` wrapping both chart and table views
- Investigation report chart rendering — add chart type inference + wrapper

---

**New deps:** None if staying with the current charting library. If switching: `recharts` or `visx` (decision at sprint start — do not change until this milestone).

**Sprint:** 46 (after M21 — metrics governance gives chart data the semantic richness to display confidently)

---

## Revised Sprint Sequence (Sprints 36–47)

| Sprint | Milestone | What ships |
|---|---|---|
| **36** | **R1 — Reliability Baseline** ✅ | Explorer recursion fix, hardcoded URLs → env var, 42 lint errors, CORS config, minimal bearer token auth, stale docs cleanup |
| **37** | **R3 — Feature Reachability** ✅ | ThinkingTrace + HypothesisCard + FeedbackPrompt in ChatPanel; MetricsPanel standalone nav route; DocumentUploader from Connections; ERD in Catalog; ConfigurePanel from main chat; orphaned component cleanup |
| **38** | **R2 — Test Infrastructure** ✅ | Backend pytest smoke tests (26 cases), frontend Vitest (QueryBuilder buildSql, API fetch), CI gate |
| **39** | **M17 — API Router Refactor** ✅ | `aughor/api.py` split into 12 routers; no behavior change; smoke tests validate nothing broke |
| **40** | **M7 — Observability** ✅ | `aughor/telemetry.py` (new); `@node_span` on 12 nodes; `trace_id` in SSE start event + `AgentState`; 45 tests passing |
| **41** | **M10 — LLM Evals** ✅ | `evals/` package; golden JSONL (15 Q&A); `verdict_accuracy`, `query_efficiency`, `hallucination_rate` scorers; CLI runner; 45 tests passing |
| **42** | **M22 — Design System Consolidation** ✅ | `web/styles/tokens.css` (single token source); `web/styles/type.css` (aug-text-h1..xs, 11px floor); component audit: rounded-xl→md, text-[9/10px]→[11px], inline hex→CSS vars across 12 components |
| **43** | **M18 — Navigation + Command Palette + Ask Hero** ✅ | 5-section nav (Ask / Investigations / Intelligence / Data Map / Governance); `CommandPalette.tsx` with fuse.js fuzzy search + keyboard nav + match highlighting; `AskScreen` hero with rotating placeholder, mode toggle, inline health scorecard, recent investigation cards |
| **44** | **M19 — Evidence Ledger** ✅ | `aughor/evidence/` package (models, store, linker); append-only SQLite ledger; `ada_synthesize` auto-extracts claims; `GET /investigations/{id}/evidence` + `POST .../feedback`; Evidence tab in HistoryDetailPanel with confidence bar, SQL toggle, Validate/Dispute/Needs Context buttons |
| **45** | **M20 — Proactive Monitors** ✅ | `aughor/monitors/` package (models, store, runner, scheduler, digest); 6 monitor types (threshold, any_change, trend_reversal, anomaly z-score, segment drift Chi-squared, data freshness); APScheduler background thread; 10 REST endpoints; unack alert banner on AskScreen |
| **45b** | **History wiring fix** ✅ | `openInvestigation(id, kind)` handler; AskScreen / RecentsScreen / HomeScreen row clicks now open existing report by ID instead of re-submitting question as new chat |
| **46** | **M21 — Metrics as Semantic Contracts** | Governance fields on MetricDefinition, quality tests runner, freshness checker, extended schema injection |
| **47** | **M23 — Charts & Data Visualization** | Unified `ChartWrapper` with loading/empty/error states; chart color system from tokens; axis/grid/legend standards; chart type inference (line/bar/scatter/table) |
| **48** | **Enterprise Hardening** | Full OAuth2/OIDC auth (replaces R1e static token), RBAC (viewer/analyst/admin), workspace tenancy, pre-execution query cancellation, secrets manager |
