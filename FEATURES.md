# Aughor — Feature Reference

**Product:** Aughor — Autonomous Analyst  
**Purpose of this document:** A living record of every major feature — what it does, why it exists, how it works, how it connects to the rest of the system, and what technology powers it. Intended as source material for product pitches, investor demos, and onboarding.

---

## Table of Contents

1. [Autonomous Investigative Loop](#1-autonomous-investigative-loop)
2. [SQL Self-Correction](#2-sql-self-correction)
3. [Statistical Evidence Engine](#3-statistical-evidence-engine)
4. [Multi-Database Connections](#4-multi-database-connections)
5. [Real-Time Streaming (SSE)](#5-real-time-streaming-sse)
6. [Investigation History](#6-investigation-history)
7. [Business Glossary](#7-business-glossary)
8. [Auto-Seed Glossary](#8-auto-seed-glossary)
9. [dbt Integration](#9-dbt-integration)
10. [Vector Search over Schema](#10-vector-search-over-schema)
11. [Prior Investigations RAG](#11-prior-investigations-rag)
12. [Two-Model Architecture](#12-two-model-architecture)
13. [Resumable Investigations](#13-resumable-investigations)
14. [Human-in-the-Loop Interrupt](#14-human-in-the-loop-interrupt)
15. [Frontend — Streaming Investigation UI](#15-frontend--streaming-investigation-ui)
16. [Connection Manager](#16-connection-manager)
17. [Direct Query Mode](#17-direct-query-mode)
18. [Thinking Trace](#18-thinking-trace)
19. [KPI Highlight](#19-kpi-highlight)
20. [Auto-Charting — Observable Plot](#20-auto-charting--observable-plot)
21. [SQL Knowledge Base](#21-sql-knowledge-base)
22. [Direct Query Graceful Failure](#22-direct-query-graceful-failure)
23. [Report UX — Smart Formatting & Collapsible Sections](#23-report-ux--smart-formatting--collapsible-sections)
24. [Metrics Catalog](#24-metrics-catalog)
25. [Error Classification & SQL Hardening](#25-error-classification--sql-hardening)
26. [Schema Intelligence — Join Inference & Fingerprinting](#26-schema-intelligence--join-inference--fingerprinting)
27. [KB Pattern Enrichment](#27-kb-pattern-enrichment)
28. [ER Diagram](#28-er-diagram)
29. [Rich Schema Card UI](#29-rich-schema-card-ui)
30. [Quick Chat Mode](#30-quick-chat-mode)
31. [Chat Chart Engine](#31-chat-chart-engine)
32. [Global Analytics Rules](#32-global-analytics-rules)
33. [Hypothesis Expanded Accordion](#33-hypothesis-expanded-accordion)
34. [Investigation Quality Hardening](#34-investigation-quality-hardening)
35. [Databricks-Brand UI](#35-databricks-brand-ui)
36. [Genie-Style Chat UI](#36-genie-style-chat-ui)
37. [History Popup](#37-history-popup)
38. [Home Page](#38-home-page)
39. [Catalog Tab](#39-catalog-tab)
40. [Schema-Aware Suggestions](#40-schema-aware-suggestions)
41. [Suggestions Cache — Qdrant Semantic Store](#41-suggestions-cache--qdrant-semantic-store)
42. [Background Schema Explorer](#42-background-schema-explorer)
43. [Business Ontology — Auto-Built](#43-business-ontology--auto-built)
44. [Domain Intelligence Loop](#44-domain-intelligence-loop)
45. [SqlWriter — Centralised SQL Writer & Self-Corrector](#45-sqlwriter--centralised-sql-writer--self-corrector)
46. [Activity Log UI](#46-activity-log-ui)
47. [Exploration State Persistence](#47-exploration-state-persistence)
48. [Per-Phase Rate Limiting](#48-per-phase-rate-limiting)
49. [Plan-then-SQL Separation](#49-plan-then-sql-separation)
50. [Non-blocking FastAPI Event Loop](#50-non-blocking-fastapi-event-loop)
51. [Loading State Hardening](#51-loading-state-hardening)
52. [Home Stat Card Navigation](#52-home-stat-card-navigation)
53. [Schema Cache — Backend + Frontend Context](#53-schema-cache--backend--frontend-context)
54. [Metric Targets & Health Scorecard](#54-metric-targets--health-scorecard)
55. [Structured Playbook from KB](#55-structured-playbook-from-kb)
56. [Outcome Tracking & Feedback Loop](#56-outcome-tracking--feedback-loop)
57. [Document Ingestion — Context Layer](#57-document-ingestion--context-layer)
58. [Business Process Visual Mapper](#58-business-process-visual-mapper)
59. [Causal Graph in Ontology — Outcome-Gated](#59-causal-graph-in-ontology--shipped)
60. [Catalog 3-Panel Layout + Sample Data Tab](#60-catalog-3-panel-layout--sample-data-tab)
61. [Phase 8 Ontology Gate](#61-phase-8-ontology-gate)
62. [Connection Persistence Hardening](#62-connection-persistence-hardening)
63. [Design System Consolidation](#63-design-system-consolidation)
64. [Navigation Redesign + Command Palette + Ask Hero](#64-navigation-redesign--command-palette--ask-hero)
65. [Evidence Ledger](#65-evidence-ledger)
66. [Proactive Monitors](#66-proactive-monitors)
67. [History Navigation Fix](#67-history-navigation-fix)
68. [Org-Level Ontology Board + table = entity Gate Fix](#68-org-level-ontology-board--table--entity-gate-fix)
69. [Canvas Creation Popup + Canvas-Scoped Configure](#69-canvas-creation-popup--canvas-scoped-configure)
70. [Add Data, New Connectors & Workspace File Uploads](#70-add-data-new-connectors--workspace-file-uploads)
71. [Agentic Investigation Polish — Coherence, Trace, Report, Timing](#71-agentic-investigation-polish--coherence-trace-report-timing)
72. [Canvas Optimisation — Scope Editing & History Management](#72-canvas-optimisation--scope-editing--history-management)
73. [Data Canvas — List Ranking, Recents & Rename](#73-data-canvas--list-ranking-recents--rename)
74. [Grounded NL2SQL, Trusted Templates & the Eval Suite](#74-grounded-nl2sql-trusted-templates--the-eval-suite)
75. [Self-Validating Semantic Layer, Fan-Out Guard & Multi-Schema Repairs](#75-self-validating-semantic-layer-fan-out-guard--multi-schema-repairs--shipped)
76. [Reusable Component Architecture, Shared Primitives & Exhaustive Test Pass](#76-reusable-component-architecture-shared-primitives--exhaustive-test-pass--shipped)
77. [The Brief — Answer Surface, Agent Reasoning Quality & Data-Shape Intelligence](#77-the-brief--answer-surface-agent-reasoning-quality--data-shape-intelligence--shipped)
78. [Intelligence-Surface Trust — Scope Consistency, Self-Explaining Intelligence & ADA Correctness](#78-intelligence-surface-trust--scope-consistency-self-explaining-intelligence--ada-correctness--shipped)
79. [Adaptive Temporal Scope — Tier 0/1/2 + Anchor Tuning](#79-adaptive-temporal-scope--tier-012--anchor-tuning--shipped)
80. [Finding Actionability & Scheduled Brief Delivery](#80-finding-actionability--scheduled-brief-delivery--shipped)
81. [Evidence Peer Layer & Intelligence-Surface Visuals](#81-evidence-peer-layer--intelligence-surface-visuals--shipped)
82. [Semantic Compiler — Typed Intent IR + Deterministic SQL](#82-semantic-compiler--typed-intent-ir--deterministic-sql--shipped)
83. [Temporal Tier 3 — Query Cost Governor](#83-temporal-tier-3--query-cost-governor--shipped)
84. [Finding Trust Guards — Numeral Grounding & Platform-Generic SQL Robustness](#84-finding-trust-guards--numeral-grounding--platform-generic-sql-robustness--shipped)
85. [Angle-Feasibility Gate & Repair Intent-Preservation](#85-angle-feasibility-gate--repair-intent-preservation--shipped)
86. [Fix-and-Save & Fix-All from the Activity Log](#86-fix-and-save--fix-all-from-the-activity-log--shipped)
87. [Deterministic Fan-out De-fan — Parent + Chasm](#87-deterministic-fan-out-de-fan--parent--chasm--shipped)
88. [Finding-Trust Ladder — Guards, Quarantine & Dismiss-with-Reason](#88-finding-trust-ladder--guards-quarantine--dismiss-with-reason--shipped)
89. [Delivery Polish — Significance Badge, Sparkline/MoM, Pareto](#89-delivery-polish--significance-badge-sparklinemom-pareto--shipped)
90. [Eval Trustworthiness — Pinned State, Metric-Aware Scoring, Noise Control](#90-eval-trustworthiness--pinned-state-metric-aware-scoring-noise-control--shipped)

---

## 1. Autonomous Investigative Loop

### What
Aughor answers a business question by autonomously forming hypotheses, writing and executing SQL to test each one, scoring the evidence, and synthesising a structured narrative report — without any manual query writing.

### Why
Traditional analytics requires an analyst to know what to look for before they start. Aughor inverts this: it generates the hypotheses itself, pursues the most promising ones, and eliminates dead ends. A question like *"Why did revenue drop 8% last week?"* produces a full root-cause investigation in minutes, not hours.

### How
The investigative loop is a cyclic LangGraph `StateGraph` with five nodes:

| Node | Role |
|---|---|
| `route_question` | Classifies the question as `direct` or `investigate`; seeds a synthetic hypothesis for direct mode |
| `decompose` | (investigate mode only) Reads the question + schema and produces 3–5 mutually exclusive, testable hypotheses |
| `plan_and_execute` | For the current hypothesis, writes 1–3 SQL queries, executes them, attaches statistical analysis |
| `score_evidence` | Reads query results and scores the hypothesis (confirmed / refuted / inconclusive, 0–1 confidence) |
| `synthesize` | Reads all scored hypotheses and evidence and writes the final narrative report |

`route_question` is the graph entry point. A conditional edge routes to `decompose` (investigate) or directly to `plan_and_execute` (direct), bypassing hypothesis decomposition entirely for simple factual queries. The loop continues until all hypotheses are tested or the iteration cap (`HERMES_MAX_ITER`, default 6) is hit. A `should_continue` router decides after each score whether to test the next hypothesis or synthesise.

### Component interactions
- `route_question` → LLM classifier; sets `query_mode` in `AgentState`; for direct mode seeds `hypotheses` with one synthetic entry (id `"direct"`) and skips `decompose`
- `decompose` → reads `schema_context` (built by `hermes/tools/schema.py`) and calls the coder LLM
- `plan_and_execute` → calls `DatabaseConnection.execute()` and attaches stats via `hermes/tools/stats.py`
- `score_evidence` → calls the coder LLM with formatted query results
- `synthesize` → calls the narrator LLM with the full evidence log
- All five nodes read/write the shared `AgentState` TypedDict
- Loop is checkpointed after every node via SqliteSaver (see [Resumable Investigations](#13-resumable-investigations))

### Tech / libraries
- **LangGraph 1.2** — cyclic stateful graph; `StateGraph`, `END`, `add_conditional_edges`
- **Pydantic + instructor** — structured LLM outputs (`DecomposeOutput`, `QueryPlan`, `EvidenceScore`, `AnalysisReport`)
- **Ollama** — local LLM inference (qwen2.5-coder:32b for reasoning; llama3.3:70b for narrative)

---

## 2. SQL Self-Correction

### What
When a generated SQL query fails, Aughor automatically rewrites it, retries, and logs what it learned — so the same mistake is never repeated in the same investigation.

### Why
LLMs frequently generate SQL with subtle dialect errors (e.g. Postgres date arithmetic, type casting). Without self-correction, a single bad query kills an entire hypothesis branch. With it, the agent recovers silently and becomes smarter within the session.

### How
1. `plan_and_execute` executes each query via `DatabaseConnection.execute()`
2. If the result has an `error`, a `FIX_SQL_PROMPT` is sent to the coder LLM with the original SQL, the error message, and the schema
3. The LLM returns a `SQLFix` — corrected SQL + one-line explanation + optional data quality note
4. The fixed query is retried. The original/fixed pair is stored as a `Pitfall`
5. All accumulated `Pitfall` objects are injected into **every subsequent** `PLAN_QUERIES_PROMPT` in the same investigation, so the agent avoids repeating the same class of error

### Component interactions
- `Pitfall` objects accumulate via `Annotated[list[Pitfall], operator.add]` in `AgentState` (append-only)
- `format_pitfall_section()` in `hermes/agent/prompts.py` renders them as a warning block
- Data quality issues discovered via pitfalls are surfaced in the final report's `data_quality_notes`

### Tech / libraries
- **SQLGlot** — parse + validate SELECT-only statements before execution; dialect transpilation
- **instructor + Pydantic** — `SQLFix` structured output

---

## 3. Statistical Evidence Engine

### What
Every SQL query result is automatically analysed for anomalies, trends, and statistical significance. A σ (sigma) badge is attached to each finding so the agent — and the user — knows which observations are statistically meaningful vs. noise.

### Why
A revenue number is just a number without context. A 12% drop is very different depending on whether it's a 3σ anomaly or normal weekly variance. Aughor makes this judgment automatically so the narrative report leads with the highest-signal findings.

### How
`hermes/tools/stats.py` runs `analyze_query_result()` on every successful `QueryResult`. It detects the column types and applies:

| Analysis | When applied | Output |
|---|---|---|
| **STL decomposition** | Time series (date + numeric column, ≥14 points) | Trend direction, seasonality strength, residual anomaly |
| **Z-score anomaly detection** | Any numeric series | σ value; flagged as significant if \|z\| > 2.5 |
| **Mann-Whitney U test** | Two-group comparisons (categorical + numeric) | p-value; significant if p < 0.05 |

The results are attached as `stats: list[StatResult]` on the `QueryResult` and streamed to the frontend as σ badges on each hypothesis card.

### Component interactions
- Called in `_attach_stats()` inside `plan_and_execute` — every query result goes through stats before being stored in `query_history`
- `StatResult.sigma` is surfaced in the SSE `queries_executed` event and rendered as a violet badge in `HypothesisCard.tsx`
- Significant stats are logged in the activity panel ("📊 3.2σ — revenue drop concentrated in APAC")
- `synthesize_report` receives the full evidence log including stats context, so the narrative references σ values

### Tech / libraries
- **scipy** — `mannwhitneyu`, `zscore`
- **statsmodels** — `STL` seasonal-trend decomposition

---

## 4. Multi-Database Connections

### What
Aughor connects to any combination of DuckDB (local files) and PostgreSQL databases. Credentials are stored encrypted. Connections can be added, tested, and removed from the UI.

### Why
Data lives everywhere — local analytical files, staging Postgres, production warehouses. Aughor needs to work against any of them without code changes, and without storing credentials in plaintext.

### How
`hermes/db/connection.py` defines a `DatabaseConnection` abstract base with two implementations:
- `DuckDBConnection` — wraps an in-process DuckDB connection; dialect = `duckdb`
- `PostgresConnection` — wraps a `psycopg2` connection pool; dialect = `postgres`

Both expose the same interface: `execute(hypothesis_id, sql) → QueryResult`, `get_schema() → str`, `test() → (bool, str)`, `close()`.

`hermes/db/registry.py` stores connection records in a local SQLite database, with the DSN encrypted using **Fernet** symmetric encryption. The encryption key is derived from a per-install secret stored at `data/.hermes_key`. Two builtin connections are pre-registered:
- `fixture` — local DuckDB demo database (`data/hermes.duckdb`)
- `mydb` — Postgres DSN from `HERMES_DEFAULT_POSTGRES_DSN` env var

### Component interactions
- `build_graph_generic(db)` binds the graph's `plan_and_execute` node to a specific `DatabaseConnection` at construction time
- `get_schema()` triggers Auto-Seed and Glossary injection (see features 7 and 8)
- `dialect` property is passed to `FIX_SQL_PROMPT` and `SQLGlot` for dialect-aware transpilation
- `ConnectionsPanel.tsx` calls `GET /connections`, `POST /connections`, `POST /connections/{id}/test`, `DELETE /connections/{id}`

### Tech / libraries
- **DuckDB** — in-process OLAP engine; zero-latency on local files
- **psycopg2** — PostgreSQL driver
- **cryptography (Fernet)** — symmetric encryption for stored DSNs
- **SQLGlot** — dialect validation and transpilation

---

## 5. Real-Time Streaming (SSE)

### What
The investigation streams live to the browser as it runs — hypothesis formation, query execution, evidence scoring, statistical findings, and the final report all appear progressively rather than after a long wait.

### Why
A typical investigation takes 60–300 seconds. A blank loading screen for that duration is unusable. Streaming turns the wait into a transparent, trust-building experience — users see *exactly* what the agent is doing and why.

### How
`hermes/api.py` exposes `POST /investigate` as a `StreamingResponse` with `media_type="text/event-stream"`. The async generator `_stream_investigation()` iterates `agent.stream()` (LangGraph's node-level streaming) and yields typed SSE events:

| Event | When | Payload |
|---|---|---|
| `start` | Investigation created | question, investigation_id |
| `hypotheses` | After `decompose` node | list of hypothesis objects |
| `queries_executed` | After each `plan_and_execute` node | SQL run, row counts, corrections, stats |
| `score` | After each `score_evidence` node | verdict, confidence, updated hypotheses |
| `paused` | HITL interrupt triggered | hypotheses, scores |
| `report` | After `synthesize` node | full report, query history |
| `error` | Any exception | message |
| `done` | Stream closing | — |

The frontend `useInvestigation.ts` hook parses these events and drives the reducer.

### Component interactions
- Wraps the LangGraph `agent.stream()` iterator
- Timeout guard: checks `time.monotonic()` between every event; yields `error` and calls `fail_investigation()` after `HERMES_TIMEOUT_SECONDS`
- Disconnect guard: checks `request.is_disconnected()` between events; kills work on client drop
- Cache short-circuit: checks `find_similar_investigation()` before starting; returns cached result immediately if score ≥ 0.80

### Tech / libraries
- **FastAPI** — `StreamingResponse`, async generators
- **Server-Sent Events (SSE)** — `data: {...}\n\n` wire format; browser-native, no WebSocket needed

---

## 6. Investigation History

### What
Every completed investigation is persisted — question, hypotheses, all SQL queries, and the full report. The History tab lets you browse, search, and reload any past investigation.

### Why
Root cause investigations are expensive to run (minutes of LLM + SQL time). Storing results means you never re-run a question you've already answered, and analysts can share and compare investigations over time.

### How
`hermes/db/history.py` maintains an `investigations` table in a local SQLite database (`data/history.db`). The lifecycle is:
1. `create_investigation()` — inserts a `running` row at the start
2. `complete_investigation()` — stores report JSON, hypotheses, query history; sets `status = complete`; triggers Qdrant indexing
3. `fail_investigation()` — sets `status = timed_out | failed`; explicitly does **not** index (partial results must not pollute the cache)
4. `pause_investigation()` — sets `status = paused` (HITL flow)

Investigation statuses: `running` / `complete` / `timed_out` / `failed` / `paused`

The frontend History tab is two-column: a list panel (`HistoryPanel.tsx`) and a full detail panel (`HistoryDetailPanel.tsx`). A `◉` dot on the list indicates the investigation is indexed in Qdrant.

### Component interactions
- `complete_investigation()` calls `index_investigation()` in `hermes/tools/prior_analyses.py` — this is the only path that reaches Qdrant
- `list_investigations()` feeds `GET /investigations`; detail loads via `GET /investigations/{id}`
- `loadHistorical()` in `useInvestigation.ts` hydrates the full investigation state client-side

### Tech / libraries
- **SQLite** (stdlib `sqlite3`) — zero-config persistence
- **JSON columns** — report, hypotheses, query history stored as `TEXT` with `json.dumps/loads`

---

## 7. Business Glossary

### What
A YAML file where every table and column in your database can be annotated with plain-English descriptions, grain definitions, known caveats, example values, and join hints. These annotations are injected into every SQL-generation prompt.

### Why
The agent only sees column names and types by default. `order_status VARCHAR` is meaningless without knowing it has 9 possible values, that ~3% are NULL due to a legacy import, and that `canceled` orders should be excluded from revenue calculations. The glossary is the institutional knowledge layer that prevents the agent from writing plausible-but-wrong SQL.

### How
`hermes/semantic/glossary.py` loads `data/glossary.yaml` and merges it with dbt metadata (see [dbt Integration](#9-dbt-integration)). `apply_glossary(schema_str, glossary)` appends annotation blocks to each table's DDL section before the schema is injected into prompts.

YAML shape:
```yaml
tables:
  orders:
    description: "One row per customer order. Grain: order_id."
    grain: "order_id"
    columns:
      order_status:
        description: "Lifecycle stage."
        values: "created, approved, invoiced, processing, shipped, delivered, unavailable, canceled"
        caveats: "~3% of rows have NULL status due to legacy import"
```

The glossary is exposed as a read/write API (`GET /glossary`, `PUT /glossary/{table}`, `PUT /glossary/{table}/{column}`) so it can be edited without touching files directly.

### Component interactions
- `build_schema_context()` in `hermes/tools/schema.py` calls `load_merged_glossary()` then `apply_glossary()` on every schema build
- Three-layer merge precedence: manual YAML > dbt-parsed > auto-seeded (lower layers never overwrite higher ones)
- The enriched schema is passed as `schema_context` in `AgentState` and injected into `DECOMPOSE_PROMPT`, `PLAN_QUERIES_PROMPT`, and `FIX_SQL_PROMPT`

### Tech / libraries
- **PyYAML** — YAML load/dump
- No new infrastructure — pure file-based

---

## 8. Auto-Seed Glossary

### What
When the agent connects to a database that has unannotated tables, it automatically infers business descriptions for those tables using a one-shot LLM call — and writes them back to `glossary.yaml` marked `auto_generated: true`. This happens once per table, on first use.

### Why
Manually annotating every table in a large warehouse is a significant time investment. Auto-seeding solves the cold-start problem: a newly connected database gets instant glossary coverage. Users can override auto-generated entries whenever the inference is wrong.

### How
`hermes/semantic/autoseed.py` runs when `get_schema()` is called and finds tables with no glossary entry. For each unannotated table, it:
1. Fetches the DDL + 5 sample distinct values per column
2. Sends a structured LLM prompt asking for a table description, grain, and per-column definitions
3. Parses the response as a `GlossaryTableEntry` Pydantic model
4. Writes the entry to `data/glossary.yaml` with `auto_generated: true`

The process is idempotent — once a table is seeded, it's never re-seeded unless the entry is manually deleted. Disable entirely with `HERMES_AUTOSEED=false`.

### Component interactions
- Called inside `DatabaseConnection.get_schema()` after `apply_glossary()` — seeding only runs for tables that still have no coverage after glossary merge
- Seeded entries feed into the same three-layer merge as manually written ones (lowest priority)
- The `auto_generated: true` flag is intended to visually distinguish AI-inferred entries in a future glossary editor UI

### Tech / libraries
- Uses the existing coder LLM provider — no new dependencies
- **PyYAML** for writing back to `glossary.yaml`

---

## 9. dbt Integration

### What
If you run `dbt docs generate`, Aughor can read your `manifest.json` and optional `catalog.json` to automatically import all your dbt model descriptions, column definitions, and source metadata into its semantic layer.

### Why
Most data teams have already encoded metric definitions in dbt — `MRR`, `CAC`, `activated_users` are defined once and trusted. Aughor re-using these definitions instead of re-deriving them solves the "three different numbers from three people" problem and prevents hallucinated metric definitions.

### How
`hermes/semantic/dbt.py` parses `manifest.json` to extract model and source nodes, their descriptions, and column-level annotations. It optionally reads `catalog.json` for additional type and comment enrichment. Key rules:
- Ephemeral models are skipped (they don't produce tables)
- Sources don't override model definitions
- The parsed output is converted to the same `GlossaryTableEntry` schema used by the YAML glossary

Enabled via `HERMES_DBT_MANIFEST=/path/to/target/manifest.json`. Silently skipped if unset — no breakage for non-dbt users.

### Component interactions
- `load_merged_glossary()` calls `load_dbt_glossary()` when the env var is set, then merges with both YAML and auto-seeded entries
- Three-layer merge precedence: manual YAML > dbt > auto-seed — dbt entries are the authoritative middle layer
- No new runtime dependencies: dbt artifacts are plain JSON

### Tech / libraries
- Standard library JSON parsing — no dbt Python package required at runtime
- dbt artifacts: `manifest.json` (required), `catalog.json` (optional enrichment)

---

## 10. Vector Search over Schema

### What
For large databases (> 12 tables), Aughor embeds table and column descriptions into a vector store and retrieves only the top-5 most relevant tables for each hypothesis — instead of dumping the full schema into the LLM context window.

### Why
A schema with 50+ tables can easily exceed 8–16k tokens. Dumping it all into every prompt is expensive, slow, and degrades reasoning quality (the LLM pays equal attention to `dim_product_category` and `fact_revenue`). Semantic retrieval focuses the agent on the tables that actually matter for the question being investigated.

### How
`hermes/semantic/retriever.py`:
1. `build_schema_index()` — embeds every table+column description from the merged glossary into Qdrant under the `schema_index` collection (run once per schema load; idempotent)
2. `retrieve_relevant_schema(hypothesis, full_schema)` — embeds the current hypothesis description and queries Qdrant for the top-5 most similar table entries; returns a filtered schema string containing only those tables

The threshold is 12 tables. Schemas below that get full context (no retrieval needed). The feature silently falls back to full schema on any Qdrant error.

### Component interactions
- `build_schema_index()` is called inside `build_schema_context()` in `hermes/tools/schema.py` after glossary merge
- `retrieve_relevant_schema()` is called per hypothesis inside `plan_and_execute` — each hypothesis gets its own tailored schema view
- Uses the same Qdrant instance and `nomic-embed-text` embedder as [Prior Investigations RAG](#11-prior-investigations-rag), in a separate `schema_index` collection
- `hermes/semantic/embedder.py` handles batched embedding via the Ollama `/v1/embeddings` (OpenAI-compatible) endpoint

### Tech / libraries
- **Qdrant** (Docker, port 6333) — self-hosted vector database; persistent volume
- **nomic-embed-text** via Ollama — 768-dimensional embeddings
- **qdrant-client >= 1.10** — uses `client.query_points()` (not deprecated `client.search()`)

---

## 11. Prior Investigations RAG

### What
Every completed investigation is embedded and indexed in Qdrant. When a new investigation starts, semantically similar past investigations are retrieved and injected into the planning prompts — so the agent avoids re-running work it has already done. Questions with a similarity score ≥ 0.80 skip the investigative loop entirely and return the cached result instantly.

### Why
Investigations are expensive. The same question — or a close variant — gets asked repeatedly in any active analytics team ("why is APAC down?" every Monday morning). RAG-backed caching makes repeat investigations instant. Injecting past summaries makes the agent smarter over time: it builds on prior conclusions rather than starting from scratch.

### How
`hermes/tools/prior_analyses.py`:
- `index_investigation(inv_id, question, headline, key_findings)` — creates a vector embedding of the investigation's question + headline + key findings; upserts into Qdrant `investigations` collection; called only by `complete_investigation()` (failed/timed-out runs never pollute the index)
- `search_prior_investigations(question)` — embeds the new question and retrieves the top-3 most similar past investigations (score ≥ 0.65); returns formatted summaries
- `find_similar_investigation(question)` — stricter threshold (score ≥ 0.80); returns the matching `inv_id` for a full cache hit

Cache short-circuit in `api.py`: runs `find_similar_investigation()` before `create_investigation()` — on a cache hit, the full cached report is returned immediately via SSE with a `⚡ Matched a prior investigation` banner. No history row is created for cache hits.

Past investigation summaries are injected into `PLAN_QUERIES_PROMPT` via `{prior_analyses_section}` — the agent is instructed to skip redundant queries when a past investigation already answered the hypothesis.

Backfill endpoint: `POST /investigations/reindex` re-indexes all completed historical investigations.

### Component interactions
- `decompose_question` node calls `search_prior_investigations()` and stores results in `AgentState.prior_analyses`
- `plan_and_execute` reads `prior_analyses` and prepends them to the planning prompt
- Shares the Qdrant instance with [Vector Search over Schema](#10-vector-search-over-schema), in a separate `investigations` collection
- `◉` dot in `HistoryPanel.tsx` reflects Qdrant index status via `GET /investigations/indexed-ids`
- **Connection-scoped cache:** every Qdrant payload stores `connection_id`; both `find_similar_investigation()` and `search_prior_investigations()` accept `connection_id` and apply a `FieldCondition` filter — the same question on a different database always starts a fresh investigation. `connection_id` is added to `AgentState` and forwarded through `complete_investigation()` so all new entries are correctly scoped. Backfill via `POST /investigations/reindex`.

### Tech / libraries
- **Qdrant** — same instance as schema search, separate collection
- **nomic-embed-text** — same embedding model

---

## 12. Two-Model Architecture

### What
Aughor uses two separate LLMs simultaneously: a "coder" model optimised for SQL and structured reasoning, and a "narrator" model optimised for prose. Each node in the investigative loop calls the appropriate model for its job.

### Why
SQL generation and narrative writing are fundamentally different tasks. A model like `qwen2.5-coder:32b` is exceptional at structured reasoning and SQL but produces mediocre prose. `llama3.3:70b` produces excellent narrative but is overkill for schema analysis. Specialising models per job improves both quality and cost.

### How
`hermes/llm/provider.py` exposes `get_provider(role: Literal["coder", "narrator"])` which returns a cached role-specific `LLMProvider`. The client for each role is built once per process.

| Role | Nodes | Default model |
|---|---|---|
| `coder` | `decompose`, `plan_and_execute`, `score_evidence`, SQL self-correction | `qwen2.5-coder:32b` |
| `narrator` | `synthesize_report` | `llama3.3:70b` |

Env vars: `HERMES_CODER_MODEL`, `HERMES_NARRATOR_MODEL`. `HERMES_MODEL` is a universal fallback for both if the role-specific var is unset.

### Component interactions
- All four graph nodes call `get_provider(role)` — the abstraction is invisible to calling code
- The Anthropic backend (Milestone 5, roadmap) will map both roles to `claude-sonnet-4-6` with prompt caching
- Role-specific clients are cached at the module level — no reconnection overhead between nodes

### Tech / libraries
- **Ollama** — local inference server; OpenAI-compatible `/v1/chat/completions` endpoint
- **instructor** — wraps the raw completion for structured Pydantic output

---

## 13. Resumable Investigations

### What
Every investigation is checkpointed after each node. If the process crashes, times out, or the user disconnects, the investigation state is preserved. Hard guardrails ensure every investigation terminates within a configurable deadline.

### Why
LLM inference is slow and non-deterministic. A 5-minute investigation should not leave orphaned state if a network hiccup interrupts it. Checkpointing also enables the Human-in-the-Loop feature (pausing mid-investigation for user input).

### How
`hermes/agent/graph.py` compiles the graph with a `SqliteSaver` checkpointer backed by `data/checkpoints.db`. Each investigation runs under its own `thread_id = inv_id`, so state is isolated per investigation.

Three guardrails in `_stream_investigation()`:

| Guardrail | Mechanism | On trigger |
|---|---|---|
| **Wall-clock timeout** | `time.monotonic()` checked between every node | `fail_investigation(status="timed_out")` |
| **Client disconnect** | `await request.is_disconnected()` between every node | `fail_investigation(status="timed_out")` |
| **Unhandled exception** | `try/except` around the stream loop | `fail_investigation(status="failed")` |

Only `complete_investigation()` indexes in Qdrant — partial results from `timed_out` or `failed` runs never enter the cache.

### Component interactions
- Checkpoint store is shared with the HITL feature (the pause/resume cycle depends on it)
- `status` column in `history.db` reflects the lifecycle: `running → complete | timed_out | failed | paused`
- `HistoryPanel.tsx` renders status badges: `⏱ timed out`, `✕ failed`, `● running`
- Timeout is configurable: `HERMES_TIMEOUT_SECONDS` (default 600)

### Tech / libraries
- **langgraph-checkpoint-sqlite 3.1** — `SqliteSaver(conn)` with `check_same_thread=False`
- **SQLite** — checkpoint storage at `data/checkpoints.db`

---

## 14. Human-in-the-Loop Interrupt

### What
An optional mode where the agent pauses after testing all hypotheses but before writing the final report. The user sees all hypothesis verdicts, can add context or redirect the analysis, and then triggers final synthesis. The analyst's feedback is injected directly into the synthesis prompt.

### Why
For high-stakes investigations — revenue root cause, compliance anomalies, board-deck numbers — an analyst may need to validate the agent's interpretation before it commits to a narrative. They may know that "H3 is wrong because the Nov promo was planned" or "focus on APAC only, EU numbers are expected." This feature makes Aughor a collaborative tool rather than a black box.

### How
**Backend:**
- `build_graph_generic(db, hitl=True)` compiles the graph with `interrupt_before=["synthesize"]`
- When the graph would run `synthesize`, it instead checkpoints and returns an `__interrupt__` event in the stream
- `_stream_investigation()` detects `"__interrupt__" in event` → emits `paused` SSE event with hypothesis verdicts → calls `pause_investigation()` → stream closes
- `POST /investigations/{inv_id}/feedback` is a second SSE endpoint: it seeds `merged` from the checkpoint, calls `agent.update_state(config, {"human_feedback": feedback})`, then resumes with `agent.stream(None, config=config)` — the graph picks up from the checkpoint and runs only `synthesize`
- `synthesize_report` reads `state.get("human_feedback")` and prepends it as an "ANALYST FEEDBACK" block in the synthesis prompt

**Frontend:**
- `FeedbackPrompt.tsx` renders when `state.status === "paused"` — shows hypothesis verdicts with confidence %, a textarea, and a "Generate report →" button
- `submitFeedback()` in `useInvestigation.ts` dispatches `RESUME` (preserves hypotheses, stores `humanFeedback`) instead of resetting state
- After the report arrives, the report section shows a "Hypotheses tested" card and an "Analyst feedback applied" card above the report body

Opt-in toggle: "Review before report" switch in the investigation input panel. Sends `hitl: true` in the `POST /investigate` request.

### Component interactions
- **Requires** [Resumable Investigations](#13-resumable-investigations) — the pause/resume lifecycle depends entirely on SqliteSaver checkpointing
- `human_feedback` and `hitl_enabled` fields added to `AgentState`
- `SYNTHESIZE_PROMPT` gains `{human_feedback_section}` — empty string when not set, so non-HITL synthesis is unaffected
- `InvestigationState.humanFeedback` in the frontend is `null` for non-HITL runs, so the hypothesis and feedback cards only appear when HITL was used

### Tech / libraries
- **LangGraph `interrupt_before`** — native graph pause before a named node
- **LangGraph `agent.update_state()`** — injects feedback into the checkpointed state before resuming
- **LangGraph `agent.get_state()`** — reads the full checkpoint to seed `merged` (so hypotheses survive the resume)

---

## 15. Frontend — Streaming Investigation UI

### What
A dark-mode single-page application with three tabs — Investigate, History, Connections — that streams live investigation progress, shows hypothesis cards with σ badges, and renders a structured report with collapsible SQL citations.

### Why
The quality of the underlying analysis is only valuable if users can read, trust, and act on it. The UI is designed to make the agent's reasoning transparent (every claim links to the SQL that proved it) and to feel like a professional analyst tool, not a chatbot.

### How
**Investigate tab:**
- Left panel: connection selector, question input, HITL toggle, activity log (numbered, live), SQL query + hypothesis counters
- Right panel: streaming hypothesis cards (verdict badge, confidence bar, σ badge for significant findings), `FeedbackPrompt` when paused, `ReportView` on completion
- Cache hits show a `⚡ Matched a prior investigation` banner with the original question

**Report view (`ReportView.tsx`):**
- Headline (Verdict card)
- **Direct mode only:** Raw query results table immediately below the Verdict — scrollable, shows up to 50 rows, SQL collapsible below
- Short Summary (direct) / Diagnosis (investigate) paragraph
- Key findings with expandable SQL footnotes (`QueryCitation` — click to see the SQL that produced the claim)
- Data Quality Issues (if any)
- Watch — forward-looking risks (before Recommended Actions)
- Recommended Actions
- Ruled Out — refuted hypotheses at the bottom (de-emphasised)

**History tab:** Two-column layout — list with status badges + Qdrant index indicator on the left; full investigation detail on the right. Click any past investigation to reload it. Direct query investigations show a "Direct Query" badge and suppress the hypothesis section entirely — only the results table and report are shown.

**Connections tab:** Two-column layout — connection list with test/delete on the left; full-height schema viewer on the right.

### Component interactions
- `useInvestigation.ts` — SSE reducer hook; `investigate()`, `submitFeedback()`, `loadHistorical()`
- All API calls target `http://localhost:8000` (FastAPI backend)
- `InvestigationState` drives all conditional rendering — `idle / running / paused / done / error`

### Tech / libraries
- **Next.js 15** (App Router, RSC)
- **shadcn/ui** — `ScrollArea`, `Separator`, `Badge` and other primitives
- **Tailwind CSS** — utility-first styling; dark zinc palette
- **TypeScript** — full type coverage via `web/lib/types.ts`

---

## 16. Connection Manager

### What
A UI panel for adding, testing, and removing database connections at runtime — no config file edits or restarts required. Each connection is validated against the live database before being saved.

### Why
Aughor is a multi-database tool. The connection manager makes it accessible to non-engineers who shouldn't need to touch `.env` files or restart a service to point the agent at a new database.

### How
`ConnectionsPanel.tsx` provides a form for name + type (DuckDB / Postgres) + DSN. On submit:
1. `POST /connections` — backend calls `open_connection()` + `db.test()` to validate before saving
2. On success, the connection is encrypted and stored in `data/connections.db`
3. The new connection appears in the list and the investigate tab's connection selector

The right column shows a full schema viewer (`SchemaPanel.tsx`) — select any connection to browse all tables and columns with their glossary descriptions.

### Component interactions
- Selecting a connection in the Connections tab sets `selectedConn` in page state, which is passed to `investigate()` on the next run
- `SchemaPanel.tsx` calls `GET /connections/{id}/schema` to fetch the live schema string
- Backend validates with `db.test()` before persisting — users get an immediate error if the DSN is wrong

### Tech / libraries
- **cryptography (Fernet)** — DSN encryption at rest
- **psycopg2** / **DuckDB** — live connection test on save

---

## 17. Direct Query Mode

### What
Aughor automatically detects whether a question needs a full multi-hypothesis investigation or can be answered directly with one or two SQL queries. Factual lookups ("Show me the top 10 customers by revenue") are answered instantly, without decomposition overhead. Diagnostic questions ("Why did revenue drop 8%?") still go through the full investigative loop.

### Why
Not every business question is a mystery to investigate — many are data lookups. Forcing a "What is our MRR this month?" question through 3–5 hypothesis branches, multiple SQL rounds, and evidence scoring is wasteful and produces an unnaturally complex response. Direct mode gives the right answer in the right format: a clean data table + a short summary, without the overhead of an investigation.

### How
`route_question` is a new LangGraph node that runs first on every question — it is now the graph entry point. It calls the coder LLM with a `ROUTE_QUESTION_PROMPT` that classifies the question into one of two modes:

| Mode | Condition | Example |
|---|---|---|
| `direct` | Single SQL pass can answer; factual, lookup, or aggregation | "Show top 10 customers by revenue", "What is our MRR?" |
| `investigate` | Requires root-cause reasoning; asks why, diagnoses a problem | "Why did revenue drop 8%?", "What's causing churn to spike?" |

For `direct` mode:
1. `route_question` seeds `AgentState.hypotheses` with a single synthetic hypothesis (`id="direct"`, `description=question`) and short-circuits `decompose`
2. A conditional edge routes directly to `plan_and_execute`
3. After one SQL pass + scoring, the graph moves to `synthesize` — one full loop iteration
4. The `synthesize_report` node produces a report with a short-form verdict and summary

The classifier result is emitted as a `{ type: "mode", query_mode, route_reasoning, route_confidence }` SSE event immediately after `route_question` runs, so the frontend can adapt its UI before any queries execute.

**Routing v2 (current):** The classifier was upgraded from keyword-matching to intent-based reasoning:
- *Retrieval intent* (can a single SQL pass answer this?) → `direct`
- *Diagnosis intent* (why did X happen? what is causing Y?) → `investigate`
- `RouteDecision` carries a `confidence: float` field (0–1). Confidence < 0.65 forces `investigate` regardless of classification — borderline questions default to the more thorough path
- `route_reasoning` is stored in `AgentState` and surfaced in the `ThinkingTrace` step sublabel alongside a confidence percentage badge
- 8 borderline few-shot examples in `ROUTE_QUESTION_PROMPT` cover ambiguous cases that previously misrouted

**Direct mode cache behaviour:** Direct queries bypass the semantic investigation cache entirely (`_looks_direct()` pre-filter in `api.py`) and are never indexed into Qdrant on completion (`skip_index=True`). This prevents stale cached results when underlying data has changed.

### Component interactions
- `hermes/agent/state.py` — `RouteDecision` Pydantic model (`mode`, `confidence`, `reasoning`); `query_mode`, `route_reasoning`, `route_confidence` fields added to `AgentState`
- `hermes/agent/prompts.py` — `ROUTE_QUESTION_PROMPT` with intent framing, confidence guidance, 8 borderline examples
- `hermes/agent/nodes.py` — `route_question()` stores reasoning + confidence; confidence < 0.65 overrides mode to `investigate`
- `hermes/agent/graph.py` — `route_question` set as entry point; `add_conditional_edges` to `decompose` or `plan_and_execute`
- `hermes/api.py` — `_looks_direct()` regex pre-filter gates cache lookup; emits `mode` SSE event with reasoning + confidence; `complete_investigation(skip_index=True)` for direct mode
- `hermes/db/history.py` — `complete_investigation(skip_index: bool = False)` — skips Qdrant indexing when True
- **Frontend:** `mode` event sets `queryMode`, `routeReasoning`, `routeConfidence` in state; ThinkingTrace shows reasoning + `· NN% confidence` sublabel; `ReportView` shows raw data table + "Executive Summary" label; hypothesis cards hidden in direct mode

### Tech / libraries
- **LangGraph conditional edges** — `route_question` → `decompose` | `plan_and_execute`
- **instructor + Pydantic** — `RouteDecision` structured output
- No new infrastructure — same LLM providers, same graph compilation path

---

## 18. Thinking Trace

### What
A live visual progress stepper in the left panel that replaces the plain numbered text log. Each stage of an investigation is shown as a timeline step with a pulsing dot while running and a verdict-coloured dot on completion — so the user can see exactly where the agent is, which hypothesis it's testing, and what it concluded, all in real time.

### Why
The text log was functional but opaque — a stream of `"H2: ran 3 queries"` lines that required mental effort to parse. The Thinking Trace makes the agent's reasoning legible at a glance: you can see at a line scan that H1 confirmed, H2 refuted, H3 is currently running. This is critical for building user trust and for demo scenarios where a non-technical audience is watching.

### How
`ThinkingTrace.tsx` derives all steps from the existing `InvestigationState` — no new state fields were added. Step derivation logic:

**Investigate mode:** Route (direct/investigate) → Decompose (N hypotheses formed) → one step per hypothesis (verdict + confidence % once scored) → Synthesize (report)

**Direct mode:** Route (Direct Query) → Query executed (N queries) → Summarizing

Each step has three visual states:
- **Pending** — hollow circle, dimmed label
- **Running** — pulsing amber dot (CSS `animate-ping`), amber label
- **Done** — solid dot (emerald for confirmed/route/decompose/synthesize; red for refuted; amber for inconclusive), normal label + sublabel

### Component interactions
- Replaces the `state.log` text log in `page.tsx` — rendered inside a `<ScrollArea>` in the left panel
- Reads `state.queryMode`, `state.hypotheses` (with live verdicts), `state.queriesExecuted`, `state.status`
- Steps update reactively as SSE events are dispatched — no additional wiring needed

### Tech / libraries
- Pure React + Tailwind — no new dependencies
- Derives steps at render time (not stored in reducer) — zero state overhead

---

## 19. KPI Highlight

### What
When a direct query returns a single-row result — a scalar answer like "What is our MRR?" or "How many active subscriptions?" — the numeric values are surfaced as large, centred metric cards above the results table. Values are auto-formatted: `1.24M`, `45.3k`, `3.14`, or `1,234`.

### Why
A single-row table is the worst way to display a scalar answer. `| mrr | 1234567.89 |` is harder to read than a card showing `1.24M · mrr`. This bridges the gap between a raw query result and a dashboard-style answer — the kind of thing a user would screenshot and share in Slack.

### How
`KPIHighlight` is a sub-component of `ReportView`. It runs when `queryMode === "direct"` and the first successful query has exactly one row. It filters to numeric columns (excluding ID-like columns), formats the value, and renders 1–3 cards in a responsive grid.

Format rules: ≥1M → `{n}M` (2dp); ≥1k → `{n}k` (1dp); decimal → 2dp; integer → locale string with commas.

### Component interactions
- Rendered in `ReportView` above `DirectResultTable`, below the Verdict card
- Only appears for direct mode single-row results — invisible in all other cases
- No separate component file — inline function in `ReportView.tsx`

### Tech / libraries
- Pure Tailwind — no Tremor or charting library needed

---

## 20. Auto-Charting — Observable Plot

### What
When a direct query result contains a time column + numeric column, Aughor automatically renders a line/area chart. When it contains a categorical column + numeric column, it renders a horizontal ranked bar chart. Chart type is inferred from column names and sample values — no user configuration required.

### Why
The most common direct queries return either trend data ("MRR by month") or ranked breakdowns ("revenue by customer"). Both are significantly more readable as charts than as tables. Auto-detection means the right chart appears automatically — the user doesn't need to choose a chart type or configure axes.

### How
`InvestigationChart.tsx` runs a two-pass detection:
1. **Column classification** — scans column names with `DATE_PATTERN` regex for date columns; checks first 10 rows for numeric parsability; flags categorical columns by string type
2. **Chart type selection** — date + numeric → time series; categorical + numeric → bar; otherwise → `null` (no chart rendered)

**Time series:** `Plot.lineY` + `Plot.areaY` (emerald, 8% opacity fill) + `Plot.dotY` markers. Dates are parsed with `new Date()` and formatted as `"Mon DD"`. Y-axis auto-formatted with M/k suffixes.

**Bar chart (v2):** `Plot.barX` horizontal layout, per-category aggregation, top 15. Label column on Y axis, value on X. Value column is selected intelligently — a `SHARE_PATTERN` match (`share|pct|percent|rate|ratio|proportion`) is preferred over other numeric columns. Data is aggregated per category using **average** for share columns and **sum** for count/amount columns — prevents the nonsensical 140% result from summing fractional shares across many time periods.

Both charts use a transparent background to sit cleanly on the dark zinc surface. The chart renders via `useEffect` → `Plot.plot()` → `container.append(plot)` pattern — fully browser-safe, no SSR issues.

**Column detection improvements (v2):**
- `DATE_PATTERN` restricted to `/_date$|_at$|_time$|created_at|updated_at|timestamp/i` — no longer misidentifies `order_year` or `order_month` (integer columns) as date axes
- `SHARE_PATTERN` column auto-detects 0–1 fractional values and formats X-axis ticks as percentages (`18.5%` not `0.185`)
- `isPercentageColumn()` checks both the column name and whether all sample values are in [0, 1]

### Component interactions
- Rendered in `ReportView` above the KPI cards and below Executive Summary in direct mode (section order: Headline → Exec Summary → Chart → KPI → Table)
- Receives `columns` and `rows` from `QueryCitation` (both included in `report` SSE event and history API response)
- Returns `null` silently when data is not chartable — no empty chart frames or error states shown

### Tech / libraries
- **`@observablehq/plot ^0.6.17`** — D3-based declarative charting; purpose-built for statistical/analytical charts
- `useEffect` append pattern for browser-safe rendering in Next.js App Router

---

## 21. SQL Knowledge Base

### What
A curated library of 235 SQL patterns embedded in Qdrant and retrieved at query-planning time. The agent looks up relevant patterns before writing SQL — avoiding known dialect traps, applying domain-correct metric definitions, and learning from example good/bad query pairs.

### Why
Even a capable coder model makes systematic SQL errors: wrong date arithmetic for the target dialect, incorrect NULL handling in aggregates, or misunderstood business metrics (e.g. using `order_date` instead of `approved_date` for revenue recognition). The KB encodes these traps once and injects them into every relevant prompt — making the corrections automatic rather than reactive.

### How
`hermes/semantic/kb_loader.py` loads 235 JSON pattern files from the KB directory. Two tiers:

| Tier | Content | When injected |
|---|---|---|
| **Tier 1 — SQL correctness** | Dialect traps, good_sql/bad_sql pairs, common mistake patterns | `FIX_SQL_PROMPT`, `PLAN_QUERIES_PROMPT` |
| **Tier 2 — Domain knowledge** | Business metric definitions, causal relationships, diagnostic questions | `DECOMPOSE_PROMPT`, `PLAN_QUERIES_PROMPT` |

Each entry is embedded via `nomic-embed-text` into Qdrant collection `sql_knowledge_base`. At runtime, three retrieval functions query the collection:
- `retrieve_for_fix_sql(error, sql)` — top-2 dialect traps matching the SQL error; injected into FIX_SQL to guide the correction
- `retrieve_for_planning(hypothesis)` — top-3 SQL patterns + domain knowledge for the current hypothesis; injected into PLAN_QUERIES
- `retrieve_for_decompose(question)` — top-2 Tier 2 domain entries; injected into DECOMPOSE to inform hypothesis generation

All retrieval functions fail silently (`""` on any error) — the KB is additive, not load-bearing.

### Component interactions
- `hermes/semantic/kb_loader.py` — `KBEntry` dataclass; `load_kb_entries(kb_path)` → 235 entries; `_detect_tier()` and `_build_embed_text()` internal helpers
- `hermes/semantic/kb_retriever.py` — `build_kb_index()` for one-time indexing; three `retrieve_for_*` functions called from `nodes.py`
- `hermes/agent/nodes.py` — calls each retrieve function at the right moment; injects `kb_patterns_section` and `kb_domain_section` into prompts
- `hermes/agent/prompts.py` — `{kb_patterns_section}` placeholder in `PLAN_QUERIES_PROMPT` and `FIX_SQL_PROMPT`; `{kb_domain_section}` in `DECOMPOSE_PROMPT`
- Shares the Qdrant instance and `nomic-embed-text` embedder with schema search and prior analyses RAG, in a separate `sql_knowledge_base` collection

### Tech / libraries
- **Qdrant** — same self-hosted instance as schema search and prior analyses
- **nomic-embed-text** — same embedding model, batch size 64
- Tier-specific payload fields enable filtered retrieval (e.g. `retrieve_for_decompose` filters to tier 2 only)

---

## 22. Direct Query Graceful Failure

### What
When a direct query fails (SQL error that self-correction cannot fix), Aughor returns a clean, factual error report immediately — without calling the narrator LLM or producing a confusing "investigation" narrative around a failure.

### Why
Without this, a failed direct query would fall through to `synthesize_report`, which would try to narrate around zero successful results — producing either a hallucinated "no data found" narrative or a confusing empty report with no explanation of what went wrong. The graceful failure path surfaces the actual SQL error clearly and tells the user what was tried.

### How
`synthesize_report` checks two conditions before calling the LLM:
1. `state.get("query_mode") == "direct"`
2. All entries in `query_history` have non-null `.error`

If both are true, it skips the narrator LLM entirely and constructs an `AnalysisReport` directly:
- `headline = "Query execution failed"`
- `verdict = ""` (empty — used as the failure signal in `ReportView`)
- `data_quality_notes` populated with one `DataQualityNote` per failed query, including the original SQL, error message, and suggested fix from the pitfall log

The frontend detects this state via `isQueryFailure = isDirect && !report.verdict && report.headline === "Query execution failed"` and renders a red headline card with "Query Failed" label, "Execution Error" collapsible section, and a description of what was retried.

### Component interactions
- `hermes/agent/nodes.py` — early-exit block at top of `synthesize_report`
- `hermes/agent/state.py` — `Pitfall.retry_error` field captures the post-fix error for failure reporting
- `web/components/ReportView.tsx` — `isQueryFailure` flag drives red styling, label swap, and "Execution Error" section

### Tech / libraries
- No new infrastructure — reuses `AnalysisReport`, `DataQualityNote`, and existing `ReportView` rendering

---

## 23. Report UX — Smart Formatting & Collapsible Sections

### What
Three complementary improvements to how report results are presented in the UI: a smart number formatter, collapsible secondary sections, and a restructured section order that puts the most important content first.

### Why
Raw query results from a business database frequently contain fractional values like `0.18518...` for a column called `category_share` — which a business user reads as nonsense until they recognise it's a proportion. Similarly, secondary sections like Risks and Excluded Causes are often not what a user wants to read first, yet they previously appeared above the chart and data table. And long secondary content (5+ risks, 4+ recommendations) cluttered the report for the many cases where the user just wants the headline answer.

### How

**Smart number formatter (`formatCell`):**
- Columns matching `SHARE_COL_PATTERN` (`share|pct|percent|rate|ratio|proportion`) with values in [0, 1] → rendered as `XX.XX%` (e.g. `18.52%`)
- Columns matching `ORDINAL_COL_PATTERN` (`year|month|day|week|rank|_id|^id$`) → rendered as bare integers, no locale comma (`2016` not `2,016`)
- Other decimals → 2 decimal places
- Other integers → locale string with thousands separator

**Section order:**
1. Headline (Top Insight / Verdict)
2. Executive Summary (was below chart/table — now immediately below headline)
3. Chart (auto-rendered when data is chartable)
4. KPI cards (scalar single-row results)
5. Query Results table
6. ─ separator ─
7. Supportive Evidences (investigate mode only)
8. Data Quality Issues ▾ (collapsible)
9. Risks & Considerations ▾ (collapsible)
10. Recommended Actions ▾ (collapsible)
11. Excluded Causes ▾ (collapsible)

**CollapsibleSection component:** A minimal toggle with an up/down chevron (`▲`/`▼`). Default state is collapsed. Title is clickable as a full-width button. Badge slot for count indicators (e.g. DQ Issues badge).

### Component interactions
- `formatCell(col, val)` — called in `DirectResultTable` cell renderer; replaces the previous `String(cell)` fallback
- `CollapsibleSection` — wraps DQ notes, risks, recommended actions, excluded causes; each manages its own `useState(false)` open state
- KPI formatter (`fmt`) also updated to use `SHARE_COL_PATTERN` check for percentage KPI cards

### Tech / libraries
- Pure React `useState` — no animation library
- Regex constants (`SHARE_COL_PATTERN`, `ORDINAL_COL_PATTERN`) at module scope for reuse across `formatCell` and `KPIHighlight`

---

## 24. Metrics Catalog

### What
Named business KPI formulas stored persistently and injected into every schema context — so the LLM always uses the same approved SQL expression for MRR, CAC, LTV, and other KPIs rather than re-deriving them from scratch on each investigation.

### Why
Even with a rich glossary, the agent re-derives metric logic on every run. "MRR" might be computed differently across three investigations, creating inconsistent numbers. The Metrics Catalog is the formula layer above the glossary: tables/columns describe what data exists; metrics describe what to compute from it.

### How
`hermes/semantic/metrics.py` defines a `MetricDefinition` Pydantic model (`name`, `label`, `sql`, `tables`, `dimensions`, `filters`, `unit`, `caveats`). Metrics are persisted as a JSON array in `data/metrics.json`. `build_metrics_block()` formats all saved metrics as a `METRICS CATALOG` block appended to the schema context string. The full CRUD API (`GET/POST/PUT/DELETE /metrics`) is exposed via FastAPI. The `MetricsPanel.tsx` UI provides a two-column editor (list left, form right) with comma-separated inputs for array fields, accessible as a sub-tab in the Connections panel.

### Component interactions
- `build_schema_context()` calls `build_metrics_block()` — metrics are visible in every LLM prompt that receives the schema context
- `MetricsPanel.tsx` in the Connections tab → right pane sub-tabs (Schema | Metrics Catalog)
- Metrics Catalog takes precedence over glossary column annotations for formula definitions

### Tech / libraries
- **Pydantic** — `MetricDefinition` model with validation
- **JSON** — simple flat file store; no new database needed

---

## 25. Error Classification & SQL Hardening

### What
Three complementary layers that reduce SQL errors before and during execution: structured error diagnosis injected into the fix prompt, proactive dialect post-processing before queries hit the wire, and column ambiguity detection on generated SQL.

### Why
FIX_SQL previously received raw error strings and asked the LLM to interpret them. Pre-classifying errors into targeted diagnostic hints dramatically increases first-fix success rate. Proactive dialect transforms catch the predictable error classes before they even reach the database.

### How
**2h-i Error Classification:** `hermes/tools/error_classifier.py` maps 30+ Postgres error patterns to targeted diagnostic hints. Called in `plan_and_execute` before the FIX_SQL LLM call — result prepended to the fix prompt as a `DIAGNOSIS:` block.

**2h-ii Dialect Post-processing:** `PostgresConnection._apply_dialect_fixes(sql)` applies three sequential transforms to every Postgres query before execution: `ROUND(expr, N)` → `ROUND((expr)::numeric, N)` (paren-aware character walk handles arbitrary nesting — `ROUND(100.0 * SUM(a) / NULLIF(SUM(b), 0), 2)` is correctly rewritten); empty-string-safe timestamp cast; interval → epoch conversion. The ROUND rewriter uses `_ROUND_OPEN` regex to locate each `ROUND(` token, then walks characters tracking paren depth to find the top-level comma — unconditionally casting the first arg to `::numeric` because PostgreSQL has no `ROUND(double precision, integer)` overload at all. DuckDB has a no-op stub.

**2h-iii Column Ambiguity Pre-flight:** `hermes/tools/ambiguity.py` scans generated SQL for unqualified column references that exist in multiple joined tables. Warnings injected into `data_quality_notes` and the next FIX_SQL prompt: `"Column 'status' exists in orders AND payments — qualify as orders.status"`.

### Component interactions
- `_classify_sql_error()` in `nodes.py` → `{error_diagnosis}` placeholder in `FIX_SQL_PROMPT`
- `_apply_dialect_fixes()` called inside `PostgresConnection.execute()` — transparent to calling code
- `detect_ambiguous_columns()` called post-LLM, pre-execution in `plan_and_execute`

### Tech / libraries
- Pure Python regex — no new dependencies

---

## 26. Schema Intelligence — Join Inference & Fingerprinting

### What
Two complementary schema enrichments: automatic detection of likely foreign-key relationships via column-name analysis (injected into prompts and the ER diagram), and MD5-based schema fingerprinting that caches enriched metadata so reconnecting to an unchanged database is instant.

### Why
Without join hints, the LLM infers JOIN columns from raw DDL alone — and misses relationships when naming isn't perfectly consistent (`customer_id` in orders, `cust_id` in customers). Schema fingerprinting eliminates redundant auto-seed LLM calls on every reconnect.

### How
**2i-i Fuzzy Join Inference:** `_col_root()` strips 8 suffix variants (`_id`, `_key`, `_code`, `_num`, `_number`, `_identifier`, `_pseudonym`, `_code`) to get the semantic root of a column. Columns with matching roots across tables form join candidates — classified as `exact` (same column name or both have `_id` suffix) or `inferred` (fuzzy root match). Join hints and `NO DIRECT JOIN DETECTED` warnings are appended to the schema context string, the Mermaid ER diagram, and the new Rich Schema Card UI.

**2i-ii Schema Fingerprinting:** `hermes/db/schema_cache.py` maintains a 50-entry LRU cache in `data/schema_cache.json`, keyed by `MD5(sorted_table_names + column_counts)`. `autoseed.py` checks the fingerprint before running any LLM seed calls — tables whose fingerprint matches the cache are skipped entirely.

### Component interactions
- `infer_joins()` and `_compute_join_map()` in `hermes/tools/schema.py` — called inside `build_schema_context()` and `build_mermaid_er()` and `build_rich_schema()`
- Schema fingerprint written after every `build_schema_context()` call; read by `autoseed.seed_missing_tables()`
- Join confidence levels (`exact` / `inferred`) shown as colour-coded badges in both the ER Diagram and Rich Schema Card join paths grid

### Tech / libraries
- **hashlib** (stdlib) — MD5 fingerprint
- Pure Python regex for column root normalisation

---

## 27. KB Pattern Enrichment

### What
252 SQL and domain knowledge patterns embedded in Qdrant — combining the talonsight knowledge base (43 files, 235 entries) with 15 custom domain files. Patterns include causal relationship chains, metric inflation/deflation detection, cross-metric signals, and diagnostic questions that directly improve hypothesis generation.

### Why
The original KB helped the LLM avoid SQL syntax mistakes. Enriched patterns help it generate better *hypotheses* — understanding that "if monthly revenue drops, check order frequency, then AOV, then refund rate" as a structured causal chain, not just a SQL correctness pattern.

### How
`hermes/semantic/kb_loader.py` handles two JSON schema families: the native Aughor shape (`{symptom, check_in_order, detection_sql}`) and the talonsight shape (`{if, then}`). Both are normalised into the same `KBEntry` embed text. Three tiers: Tier 1 (47 SQL correctness patterns — dialect traps, good/bad SQL pairs), Tier 2 (84 domain knowledge entries — metrics, causal chains, diagnostic questions), Tier 3 (121 stubs). `kb_retriever.py` formatters for `_format_for_decompose()` and `_format_for_planning()` surface causal chains, misconceptions, and inflation signals.

### Component interactions
- 252 entries indexed in Qdrant `sql_knowledge_base` collection at `build_kb_index()` time
- `retrieve_for_decompose()` → Tier 2 only → injected into `DECOMPOSE_PROMPT` before hypothesis generation
- `retrieve_for_planning()` → Tier 1+2 → injected into `PLAN_QUERIES_PROMPT`
- `retrieve_for_fix_sql()` → Tier 1 dialect traps → injected into `FIX_SQL_PROMPT`

### Tech / libraries
- **Qdrant** — same shared instance; `sql_knowledge_base` collection
- **nomic-embed-text** — batch-embedded in chunks of 64

---

## 28. ER Diagram

### What
A Mermaid erDiagram view of the database schema, automatically generated from the live schema — with solid lines for exact FK joins and dashed lines for fuzzy inferred joins. Accessible as a sub-tab alongside the Schema tab in the Connections panel.

### Why
A static table list tells you what columns exist; an ER diagram shows how tables relate. For databases with 5+ tables, the relationship view makes the JOIN structure immediately clear — especially useful when onboarding a new database or debugging why the agent is writing incorrect JOINs.

### How
`build_mermaid_er(schema_str)` in `hermes/tools/schema.py` parses the schema string, runs `_compute_join_map()` for join inference, marks FK candidate columns, and generates Mermaid `erDiagram` syntax. Solid lines (`||--|{`) = exact match; dashed (`||..|{`) = inferred. The `/connections/{id}/schema/mermaid` endpoint returns the diagram source. `SchemaPanel.tsx` lazy-loads mermaid.js via `import("mermaid")` only when the ER Diagram tab is first opened — the 500KB+ library never loads for Schema-only users.

### Component interactions
- `build_mermaid_er()` reuses `_parse_schema_tables()` and `_compute_join_map()` from join inference (2i)
- Mermaid rendered client-side into a `<div ref>` via `mermaid.render()` with dark theme + LR layout
- "Mermaid source" collapsible shows the raw diagram text below the rendered SVG

### Tech / libraries
- **mermaid.js** — dynamically imported; 500KB; lazy-loaded on first tab open
- `GET /connections/{id}/schema/mermaid` FastAPI endpoint

---

## 29. Rich Schema Card UI

### What
A visual, card-based schema browser replacing the plain-text schema dump. Each table gets a gradient-coloured card showing columns with type chips and FK badges, plus a stats bar, a join paths grid, and a SQL Warnings & Modeling Notes section.

### Why
A wall of monospace DDL text requires mental effort to parse. The card view makes a multi-table schema scannable in seconds: colour identifies the table, type chips classify columns at a glance, and the join paths grid makes FK relationships explicit — reducing the chance of analysts writing incorrect JOINs.

### How
`build_rich_schema(schema_str)` in `hermes/tools/schema.py` parses the schema into structured data: `tables` (name, row_count, columns with types and FK flags), `joins` (from join inference), `isolated` tables, and `warnings` (type mismatches on join columns, isolated tables, wide tables). The `/connections/{id}/schema/rich` endpoint returns this JSON. `SchemaCards.tsx` renders:
- **Stats bar** — three `StatChip` pills (N tables · N columns · N join paths) + amber warning chip if issues exist
- **Table cards grid** — 8-colour palette cycling; card header with row count and column count badges; per-column rows with colour-coded type chips and FK badges
- **Join paths section** — one row per join; emerald badge = exact, amber = inferred
- **SQL Warnings & Modeling Notes** — always visible; ✓ green empty state when no issues detected; ⚠ amber rows for type mismatches; ℹ zinc rows for info notes

### Component interactions
- `SchemaPanel.tsx` fetches `/schema/rich` on connection select; renders `<SchemaCards>` in the Schema sub-tab
- Column type chip colours: blue = numeric, green = text, amber = date/time, violet = boolean, zinc = other
- `build_rich_schema()` stops parsing at section headers (DETECTED JOIN, NO DIRECT JOIN, METRICS CATALOG) to avoid join-hint lines being misread as table columns
- **Schema parser dedup:** if the same `TABLE:` header appears more than once in the schema string (e.g. re-emitted by glossary or hints sections), only the first occurrence's columns are registered — prevents duplicate column entries that cause React key collisions in `SchemaCards.tsx`

### Tech / libraries
- Pure Tailwind CSS — no charting library; gradient palette via utility classes
- `GET /connections/{id}/schema/rich` FastAPI endpoint

---

## 30. Quick Chat Mode

### What
A conversational, no-frills mode for fast data retrieval with multi-turn memory. Ask in plain English, get a number or chart immediately — no verdict, no executive summary. Follow up naturally ("filter by last 90 days", "also show revenue") and context carries across turns.

### Why
Direct Query is single-shot and wraps every result in the full report shell. Quick Chat is stripped entirely — bare answer bubbles — and crucially carries *conversation history* across turns so each question can reference the previous one. Designed for power users who need speed over narrative.

### How
`POST /chat` is a lean SSE endpoint that bypasses the full LangGraph investigative loop entirely. On each request:
1. Schema context is built from the active connection
2. The last 3 completed turns are formatted as a `CONVERSATION HISTORY` block (question, SQL, columns, headline per turn)
3. The coder LLM generates a `ChatAnswer` (sql, headline, chart_type) via `CHAT_PROMPT` + `CHAT_SQL_SYSTEM`
4. SQL is executed; one self-correction attempt on error using `FIX_SQL_PROMPT`
5. Results stream back: `sql → columns → rows → headline → chart_type → done`

`useChat.ts` manages a `ChatTurn[]` reducer — each turn tracks `status` (loading / done / error), `sql`, `columns`, `rows`, `headline`, `chartType`, `error`. The `ask()` function auto-builds history from completed turns before sending.

`ChatMessage.tsx` renders each turn as two bubbles: question (right, zinc-800) and answer (left, transparent). The answer bubble adapts to result shape: KPI cards for single-row numeric results, an `InlineChart` for chartable data (≥3 rows or explicit chart type), or a scrollable mini table otherwise. SQL is accessible via a collapsible below the result.

`ChatPanel.tsx` shows starter prompts on empty state, scrolls to the latest turn, and supports ✕ to clear the session. The session clears automatically when the connection changes.

### Component interactions
- Completely separate from the LangGraph graph — `POST /chat` calls `get_provider("coder").complete()` and `db.execute()` directly; no `AgentState`, no history DB writes
- Reuses `CHAT_PROMPT`, `FIX_SQL_PROMPT`, `get_provider()`, `open_connection()`, `get_dsn()`, `_sse()`
- Chat is the default landing tab; Deep Analysis (combined Investigate + History) is the second tab
- Connection selector sidebar in the Chat tab links to the Connections tab for management

### Tech / libraries
- **FastAPI SSE** — same `StreamingResponse` + `_sse()` pattern as investigate endpoint
- **instructor + Pydantic** — `_ChatAnswer(sql, headline, chart_type)` structured output
- **@observablehq/plot** + **d3-shape** — inline charts in answer bubbles (see Feature 31)
- No new dependencies

---

## 31. Chat Chart Engine

### What
A rich, multi-type inline charting system inside Quick Chat answer bubbles. Supports vertical bar, horizontal bar, line/area, stacked bar, and pie/donut charts. Chart type is selected by the LLM based on the question context, with explicit user control via natural language ("pivot", "flip", "pie chart"). Charts are resizable via a drag handle.

### Why
Quick Chat answers span a wide range of result shapes — time series trends, category breakdowns, part-of-whole distributions, dual-dimension comparisons. A single chart type produces misleading or hard-to-read results for most of these. The LLM selecting chart type and the user being able to resize ensures every answer is presented in the most readable form.

### How
**Backend — `chart_type` from LLM:**
`_ChatAnswer` Pydantic model gains `chart_type: str = "auto"` (one of `auto`, `bar`, `bar_horizontal`, `line`, `pie`, `stacked_bar`, `scatter`). After the headline SSE event, the API emits a `chart_type` event. `CHAT_SQL_SYSTEM` and `CHAT_PROMPT` contain explicit orientation rules for the LLM:
- Default: categorical columns on the X axis, measures on the Y axis (vertical bars)
- `bar_horizontal` only when the user says "pivot", "flip", "horizontal", or "rotate"
- `pie` only when the user explicitly asks for a pie or donut chart
- `stacked_bar` when comparing a measure across two categorical dimensions simultaneously
- `line` for time-series trends

**Frontend — `InlineChart` component (`ChatMessage.tsx`):**

Chart type selection cascade: explicit LLM `chartType` → heuristic auto-detect from column names and value types.

| Chart type | Render | Height default |
|---|---|---|
| `pie` | `d3-shape` `pie()` + `arc()` generators; raw SVG donut (innerRadius 44, outerRadius 100); `buildHtmlLegend()` | fixed SVG |
| `stacked_bar` | `Plot.barY` + `Plot.stackY` (vertical stacks, groups on X axis) | `userH ?? 280` |
| `line` | `Plot.lineY` + `Plot.areaY` (8% opacity fill) | `userH ?? 200` |
| `bar` (default) | `Plot.barY`; chartW = `barData.length × 36`; value labels above bars; tickRotate −40° when >10 categories | `userH ?? 260` |
| `bar_horizontal` | `Plot.barX`; value labels right of bars | `userH ?? max(100, n × 26)` |

**Timestamp formatting:** `fmtTimestampLabel(v)` converts ISO timestamp strings ("2024-01-01 00:00:00") to "Jan 2024" for month/week/quarter columns. Time-label columns (`TIME_LABEL_COL = /(month|quarter|week|half|period)/i`) preserve SQL ordering instead of re-sorting.

**Color palette:** Tableau-10 (`T10`) for bar/line charts; 8-color `PIE_COLORS` array for pie/donut segments.

**Legend:** `buildHtmlLegend(items)` renders an imperative HTML legend injected into the chart container. Switches to a 2-column layout when >12 items.

**Resizable charts:** Each chart has a `userH` state (null = natural default). A drag handle below the chart (a thin pill bar) listens for `onMouseDown`. During drag, the container height is updated via `outerRef.current.style.height` (CSS-only, no re-render). On `mouseup`, `setUserH(newH)` triggers a single chart re-render at the new size. `userH` is included in the `useEffect` deps array so charts re-plot at the correct size.

**No data caps:** All slice limits removed — pie, bar, table, and KPI cards render the full dataset returned by the query (up to the 10,000-row backend limit).

**Deduplication:** Async `import()` race condition (chart appended twice on fast connections) eliminated via a `cancelled` flag checked inside the `.then()` callback and a `innerHTML` clear before each append.

**Two-ref pattern:** `outerRef` = scrollable shell (overflow + resize target); `innerRef` = Observable Plot / SVG mount point.

### Component interactions
- `hermes/hermes/agent/prompts.py` — `CHAT_SQL_SYSTEM` and `CHAT_PROMPT` contain `chart_type` instructions and orientation rules
- `hermes/hermes/api.py` — `_ChatAnswer.chart_type` field; `chart_type` SSE event emitted after `headline`; `result.rows[:10000]` row cap
- `web/lib/useChat.ts` — `ChatTurn.chartType`; `CHART_TYPE` reducer action; SSE handler dispatches it
- `web/components/ChatMessage.tsx` — `InlineChart` component; all chart branches; `fmtTimestampLabel`; `buildHtmlLegend`; `startDrag` + `userH` resize

### Tech / libraries
- **@observablehq/plot 0.6.17** — bar, line, stacked bar marks
- **d3-shape** — `pie()` + `arc()` generators for donut chart (Observable Plot has no arc mark in 0.6.x)
- **d3-shape** is already installed as a transitive dependency of Observable Plot — no new install needed

---

## 32. Global Analytics Rules

### What
A human-editable Markdown file (`data/global_rules.md`) containing 102 rules across 14 sections — covering operating posture, time intelligence, metric definitions, statistical rigour, business context, and privacy. Rules are injected into every LLM prompt at call time so they take effect immediately without a restart.

### Why
Even a capable coder model makes systematic analytics mistakes: including cancelled orders in revenue, summing monthly percentages, treating NULLs as zeros, or showing raw timestamps instead of clean date labels. Encoding these rules once and injecting them universally means corrections apply everywhere — not just in sessions where the agent happened to learn from a pitfall.

### How
`hermes/rules.py` re-reads and parses `global_rules.md` on every call (no caching — edits take immediate effect). `_parse(text)` returns `dict[int, tuple[str, list[str]]]` — section number → (title, rules). Lines starting with `#` are comments and ignored.

Two export functions:
- `get_rules_block()` — all 14 sections (~3,360 words) → injected into `decompose_question`, `plan_and_execute`, and `synthesize_report` nodes
- `get_chat_rules_block()` — sections 0, 7, 8 only (~713 words: operating posture, formatting, null handling) → injected into `POST /chat` to keep overhead proportional for simple queries

The block is prepended to each prompt before the schema and question context.

### Rule sections
§0 Operating Posture · §1 Time & Date Intelligence · §2 Metric Definitions · §3 Aggregation & Grouping · §4 Filtering Discipline · §5 Comparative Analysis · §6 Statistical Rigour · §7 Output Formatting · §8 NULL & Missing Data · §9 Causal Language · §10 Scope & Exclusions · §11 Business Context · §12 Performance · §13 Privacy

### Component interactions
- `hermes/rules.py` — `_parse()`, `_format_block()`, `get_rules_block()`, `get_chat_rules_block()`
- `hermes/agent/nodes.py` — `decompose_question`, `plan_and_execute`, `synthesize_report` each call `get_rules_block()` and prepend the result
- `hermes/api.py` — `_stream_chat` calls `get_chat_rules_block()` and prepends to `CHAT_PROMPT`
- `data/global_rules.md` — user-editable; sections delimited by `## §N`; `#` lines are comments

### Tech / libraries
- Pure Python file I/O + regex — no new dependencies
- Re-read on every call — no cache invalidation needed

---

## 33. Hypothesis Expanded Accordion

### What
Each hypothesis card in the Investigation Report has an expandable accordion that shows exactly how that hypothesis was tested — per-query chart, result table (up to 15 rows), statistical callouts, SQL toggle, and a key finding summary — giving business users transparent, traceable evidence for every conclusion.

### Why
The report previously showed only the verdict badge and one-line key finding per hypothesis. Users had no way to see what SQL ran, what the data looked like, or why the agent concluded "confirmed" vs "refuted" without going to the full query history. The accordion surfaces all of that inline, making the report self-contained and auditable.

### How
`HypothesisAccordion` in `ReportView.tsx` renders per hypothesis on click:
- **Key finding card** — claim, confidence dot + bar + %, linked H-chip
- **Query evidence** (`QueryEvidence`) — one block per query: auto-chart (`InvestigationChart`), compact table (`QueryMiniTable`, max 15 rows, violet-tinted headers), statistical callouts (`StatCallout` with type-coloured border: anomaly/trend/comparison/distribution), and a collapsible SQL block
- **Synthesis link** — text note linking the hypothesis result to the overall diagnosis

Report section order in investigate mode: Verdict → Diagnosis + Key Findings → Hypotheses Tested accordion → [separator] → Data Quality / Risks / Actions / Excluded.

`HypothesisPanel` wraps all accordions with a section header showing confirmed/refuted/inconclusive counts. Hypothesis descriptions are no longer line-clamped (`line-clamp-2` removed).

### Component interactions
- `ReportView.tsx` — `HypothesisAccordion`, `HypothesisPanel`, `QueryEvidence`, `QueryMiniTable`, `StatCallout`, `KeyFindingCard` (new components in this file)
- `H_PALETTES` constant — 5-colour palette (violet/blue/emerald/amber/rose) cycled per hypothesis
- `HistoryDetailPanel.tsx` — passes `hypotheses={hypotheses}` to `ReportView`; removed old `HypothesisCard` separate section
- `web/lib/types.ts` — `QueryCitation.stats?: StatResult[]` added
- `hermes/api.py` — `stats` field added to both `report` SSE events (main stream and HITL resume) so accordion can render stat callouts from history

### Tech / libraries
- Pure React `useState` + Tailwind — no new dependencies
- Reuses `InvestigationChart` for per-query charts

---

## 34. Investigation Quality Hardening

### What
Six interconnected fixes to the investigation pipeline that eliminate fabricated confidence scores, cross-hypothesis context leakage, internally contradictory findings, unverifiable numeric claims, unsupported threshold precision, and per-cell share-column formatting errors.

### Why
A Superstore investigation revealed a cluster of quality defects: H1–H3 returned "Refuted" at high confidence despite zero queries being executed; H4 was "Confirmed" at 99% confidence by borrowing evidence from H5's context; key findings contained precise numbers not traceable to any query result; and one KPI was rendered as "21.00%" for a raw count value. These failures erode trust in the agent's output and can mislead business decisions.

### How

**Fix 1 — Evidence-scoped scoring.** `score_evidence` now initialises `confidence=0.0` when no queries ran (was 0.5) and `confidence=0.1` when all queries errored (was 0.5). A deterministic post-LLM cap enforces ceilings: 1 successful query → max 0.60; 2 → max 0.80; 3+ → uncapped.

**Fix 2 — Prompt-level evidence rules.** `SCORE_EVIDENCE_PROMPT` now includes an explicit EVIDENCE STRENGTH RULES block stating the same ceilings. The LLM is instructed not to infer evidence from other hypotheses' context.

**Fix 3 — Consistency check before synthesis.** In investigate mode, `synthesize_report` runs a pre-synthesis consistency check via the coder LLM using `CONSISTENCY_CHECK_PROMPT`. Any contradictions cause the affected hypotheses' confidences to be downgraded by 0.30 (floor 0.20) and tensions are injected into `SYNTHESIZE_PROMPT` as an `UNRESOLVED CONTRADICTIONS` block. Gate: `HERMES_CONSISTENCY_CHECK=false` disables.

**Fix 4 — Numeric traceability verifier.** Post-synthesis, `verify_numeric_claims()` (in `hermes/agent/verify.py`) extracts all numbers from the report text and checks each against query cell values and stat fields (±10%/±15% tolerance). Unverifiable numbers are appended as `DataQualityNote` entries in the report.

**Fix 5 — Threshold drill-down rule.** `PLAN_QUERIES_PROMPT` includes a mandatory THRESHOLD CLAIM RULE: when a prior query shows a metric changing sign or crossing a critical value across coarse bands, a follow-up query at finer granularity within the transition zone is required before any precise threshold can be claimed. `data/global_rules.md` §9 also includes this rule.

**Fix 6 — Column-typed share formatter.** `web/lib/formatCell.ts` provides `isShareColumn(colName, colValues)` (column-scan, not per-cell), `formatCell(col, val, shareCol)`, and `buildColumnFormatter(columns, rows)`. `ReportView.tsx` (`QueryMiniTable`, `DirectResultTable`) now call `buildColumnFormatter` once per table; a column is formatted as XX.XX% only when its name matches the share pattern AND every value in the column is in [0, 1].

### Component interactions
- `hermes/agent/nodes.py` — `score_evidence` confidence defaults + post-LLM caps; `synthesize_report` consistency check + numeric verifier
- `hermes/agent/prompts.py` — `SCORE_EVIDENCE_PROMPT`, `CONSISTENCY_CHECK_PROMPT` (new), `SYNTHESIZE_PROMPT`, `PLAN_QUERIES_PROMPT`
- `hermes/agent/verify.py` — `verify_numeric_claims()` (new file)
- `hermes/agent/state.py` — `unresolved_tensions: list[str]` field added to `AgentState`
- `web/lib/formatCell.ts` — `isShareColumn`, `formatCell`, `buildColumnFormatter` (new file)
- `web/components/ReportView.tsx` — imports `buildColumnFormatter`; removed local `formatCell`
- `data/global_rules.md` — §0, §2, §9 rule additions

### Tech / libraries
- Pydantic structured LLM output (`_Contradiction`, `_ConsistencyReport` models)
- Best-effort pattern — consistency check, numeric verifier, stat attachment all wrapped in `try/except` to never block report production
- Two-model architecture — coder LLM for consistency check, narrator LLM for synthesis

---

## Navigation structure

```
Default tab → Chat  (Quick Chat Mode + Chart Engine)
Second tab  → Deep Analysis  (Investigate left panel + History panel)
Third tab   → Connections  (Schema cards, ER Diagram, Metrics Catalog)
```

---

## How features connect — end-to-end data flow

```
User question
    │
    ▼
Cache check (Prior Investigations RAG)          [skipped for direct-signal questions]
    ├─ hit (score ≥ 0.80) ─────────────────────────────────► SSE: report (cached) ⚡
    │
    └─ miss ──► create_investigation(history.db)
                    │
                    ▼
              route_question                           SSE: mode + reasoning + confidence%
                ├─ LLM classifier → "direct" | "investigate"
                ├─ confidence < 0.65 → force "investigate"
                │
                ├─ direct ──────────────────────────────────────────────┐
                │   (seeds synthetic hypothesis, skips decompose)        │
                │                                                        │
                └─ investigate                                           │
                        │                                                │
                        ▼                                                │
                  decompose_question                                     │
                    ├─ builds schema_context                             │
                    │     ├─ raw DDL (DatabaseConnection.get_schema)     │
                    │     ├─ Auto-Seed Glossary (unannotated tables)     │
                    │     ├─ merge Glossary YAML + dbt + auto-seed       │
                    │     └─ build_schema_index → Qdrant (schema_index)  │
                    └─ fetches prior_analyses (Qdrant investigations)    │
                            │                                            │
                            ▼ (×N hypotheses)  ◄─────────────────────── ┘
                      plan_and_execute
                        ├─ retrieve_relevant_schema (Qdrant, if >12 tables)
                        ├─ retrieve_for_planning (SQL KB — Tier 1+2 patterns)
                        ├─ LLM → QueryPlan (coder model)
                        ├─ DatabaseConnection.execute → QueryResult
                        ├─ SQL self-correction on error
                        │     ├─ retrieve_for_fix_sql (SQL KB — dialect traps)
                        │     └─ Pitfall logged (retry_error captured)
                        └─ attach_stats → STL / z-score / Mann-Whitney
                            │
                            ▼
                      score_evidence
                        └─ LLM → EvidenceScore (coder model)
                            │
                            ▼ (HITL enabled?)
                      ┌─────┴──────┐
                   paused        continue
                      │              │
                 FeedbackPrompt    synthesize_report
                 (user input)       ├─ [direct + all failed] → factual error report (no LLM)
                                    └─ LLM → AnalysisReport (narrator model)
                      │                        │
                      └────────────────────────┘
                                               │
                                      complete_investigation
                                        ├─ history.db ✓
                                        └─ Qdrant index ✓
                                               │
                                               ▼
                                        SSE: report
                                  (includes columns + rows
                                   for direct query table)
```

---

---

## 35. Databricks-Brand UI

### What
Complete visual redesign of the frontend using the exact Databricks brand palette, replacing generic Tailwind zinc defaults with a navy-tinted dark theme.

### Why
Aughor targets data teams who live in Databricks. A UI that feels native to that ecosystem — same surface colors, same text hierarchy, same accent language — reduces cognitive friction and signals product maturity.

### How
All color overrides live in a plain `:root {}` block in `globals.css` (unlayered CSS, always wins over Tailwind's `@layer theme`). Key values:

| Token | Value | Role |
|---|---|---|
| `--color-zinc-900` | `#1F272E` | Left nav / sidebar |
| `--color-zinc-800` | `#11171D` | Main canvas |
| `--color-zinc-500` | `#8A9BA6` | Sub-text, metadata |
| `--color-zinc-300` | `#EBEFF2` | Primary text |
| `--color-violet-600` | `#3B8DBF` | Accent (steel blue replaces purple) |

A bulk sed pass across all TSX files replaced `text-zinc-600` and `text-zinc-700` (which mapped to dark surface colors, rendering text invisible) with `text-zinc-500`.

### Key files
- `web/app/globals.css` — palette override block
- All `web/components/*.tsx`, `web/app/page.tsx` — text color normalization

---

## 36. Genie-Style Chat UI

### What
Redesign of the Chat empty state and input bar, inspired by Databricks Genie Spaces — centered input, embedded arrow button, mode toggle below the textarea, plain-text suggestions, and an accuracy disclaimer.

### Why
The previous layout had the input pinned at the bottom with a card grid of suggestions above. For new users, this felt like a form rather than a conversation. The Genie layout puts the input front and center — the first thing you interact with — and surfaces suggestions as clickable prose beneath it.

### How
**Empty state (no messages):**
1. Full-height flex column centered vertically
2. Title + subtitle
3. Textarea with `rows=3` and an absolute-positioned `ArrowUp` button (bottom-right corner)
4. Ask / Investigate mode toggle pills immediately below the textarea
5. `"Always review the accuracy of responses."` disclaimer
6. Suggestion list — plain `<button>` elements with a small ASK/INVESTIGATE badge prefix; hover underline

**Active chat (messages present):**
- Conversation scrolls above
- Bottom bar: single-row textarea (`rows=1`) + arrow button + mode toggle + Clear link

The Send button is removed entirely. Enter sends; Shift+Enter inserts a newline.

### Key files
- `web/components/ChatPanel.tsx`

---

## 37. History Popup

### What
The investigation history panel moved from a persistent left sidebar (consuming ~224px at all times) to a floating popup triggered by a History clock icon in the topbar.

### Why
The left panel was always visible even when irrelevant, consuming screen real estate on every tab. The popup pattern matches modern productivity tools (Linear, Notion) — history is one click away but zero cost when not needed.

### How
- `showHistory` boolean state in `page.tsx`
- Clock icon button in the topbar right section (visible on all tabs)
- Popup: `fixed top-12 right-4 z-50 w-80 h-[72vh]` with a full-screen transparent backdrop (`fixed inset-0 z-40`) to capture outside clicks
- Selecting a history item sets `selectedHistoryId`, closes the popup, and navigates to the Investigate tab
- `InvestigateLeftPanel` now only shows during active analysis (running/paused) — idle state shows the full canvas width

### Key files
- `web/app/page.tsx` — `showHistory` state, popup render
- `web/components/HistoryPanel.tsx` — unchanged (reused in popup)

---

## 38. Home Page

### What
A Databricks-style welcome screen that serves as the default landing tab, showing the active connection, quick-start actions, sample questions, and recent investigation history.

### Why
Previously the app cold-started on the Chat tab with an empty input. New users had no orientation — no sense of what Aughor can do or where to start. The Home page provides immediate context and one-click entry points to every core workflow.

### How
The page is structured in vertical sections:

1. **Welcome banner** — "Welcome to Aughor" + one-line description
2. **Active connection card** — shows name, type (DuckDB/Postgres), and connected badge
3. **Quick start** — three cards: Chat, Deep Analysis, Catalog; clicking navigates to the respective tab
4. **Try asking** — four domain-specific starter questions as clickable prose links; clicking navigates to Chat
5. **Recent investigations** — last 5 investigations from `GET /investigations`; shows question, relative timestamp ("9h ago"), and status badge (timed out / failed / running)

Data fetched client-side on mount; no SSR needed.

### Key files
- `web/app/page.tsx` — `HomePage` component, `home` NavTab

---

## 39. Catalog Tab

### What
A dedicated browser for the tables and columns in the connected database, accessible from the left nav under Data → Catalog.

### Why
Before running a query or analysis, users need to know what data exists. The Catalog gives a Databricks-style table explorer: row counts, column types, FK relationships — without writing any SQL.

### How
- Fetches `GET /connections/{conn_id}/schema/rich` → returns `{tables: [{name, row_count, columns: [{name, type, is_fk}]}]}`
- Renders as an expandable card list: collapsed = table name + row count + first 4 column name chips; expanded = full column grid (name | type | FK)
- Column types are color-coded: VARCHAR → sky, numeric → violet, DATE/TIME → amber, BOOL → emerald
- Row counts formatted: `6,996,999 → 7.0M`
- **Ask →** button per table: sets `selectedConn` to the table's connection and navigates to Chat
- Connection picker and table name filter in the panel header
- Stats bar shows total tables, total columns, total rows across all tables

### Key files
- `web/components/CatalogPanel.tsx` — new component
- `web/app/page.tsx` — `catalog` NavTab, `onChatWithTable` handler

---

## 40. Schema-Aware Suggestions

### What
The Chat empty state suggestions are generated by an LLM based on the actual schema of the selected connection, not hardcoded. Switching connections triggers a fresh fetch.

### Why
Generic starters ("Show me the top 10 rows") work for demos but feel hollow for real databases. A beautycommerce database should show questions about orders, campaigns, and inventory — not customers and MRR. Schema-aware suggestions immediately signal that Aughor understands your data.

### How
1. `ChatPanel` calls `GET /suggestions?connection_id=X` on mount and whenever `connectionId` changes
2. Backend fetches `db.get_schema()`, sends it to the coder LLM with a structured output prompt asking for exactly 6 questions — 4 `ask` mode, 2 `investigate` mode — specific to the actual table/column names
3. Frontend maps the response into the suggestion list; falls back to `FALLBACK_STARTERS` on any error
4. While loading, 6 pulse shimmer placeholders are shown

### Key files
- `hermes/api.py` — `GET /suggestions` endpoint
- `web/components/ChatPanel.tsx` — `starters` state, fetch on connection change

---

## 41. Suggestions Cache — Qdrant Semantic Store

### What
Suggestions are embedded and cached in Qdrant so subsequent loads return instantly (~3s) instead of triggering a full LLM generation cycle (~90s).

### Why
The suggestions endpoint is called every time a user opens the Chat tab or switches connections. An uncached LLM call on every page load would make the app feel slow and burn local GPU time unnecessarily. By caching in Qdrant — the same vector store already used for schema search and investigation indexing — we get instant reads and a foundation for future semantic features (suggestion autocomplete).

### How

**Cache key:** `(connection_id, structural_schema_fingerprint)`

The fingerprint is computed from sorted table + column names only (not row counts or descriptions), so it's stable across sessions and only invalidates when the actual schema structure changes.

**Write path (cache miss):**
1. LLM generates 6 suggestions
2. `embed(texts)` sends all 6 to `nomic-embed-text` in one batch call
3. Each suggestion upserted as a Qdrant point with payload `{connection_id, fingerprint, text, mode, created_at}` and a deterministic ID `{connection_id}:{fingerprint}:{index}`

**Read path (cache hit):**
1. `collection_count()` fast-path: if collection is empty, skip Qdrant entirely
2. `client.scroll()` with filter `{connection_id: X, fingerprint: Y}` — returns all matching points
3. If ≥ 6 points found: return immediately, no LLM call

**Semantic search (future):**
`search_similar(query, connection_id)` is implemented and ready — embed the user's partial input, search the `schema_suggestions` collection filtered to the active connection, surface the top-3 closest suggestions for autocomplete.

**Graceful degradation:** Both read and write errors are caught silently. If Qdrant is down, the endpoint falls through to LLM generation and returns suggestions without caching.

| Metric | Value |
|---|---|
| Cold (LLM + embed + store) | ~90s (local qwen2.5-coder:14b) |
| Warm (Qdrant scroll) | ~3s |
| Collection | `schema_suggestions` |
| Vector model | `nomic-embed-text` (768 dim) |

### Key files
- `hermes/semantic/suggestions_cache.py` — `schema_fingerprint()`, `get_cached()`, `store()`, `search_similar()`
- `hermes/api.py` — updated `GET /suggestions` with cache-first flow

---

---

## 42. Background Schema Explorer

### What
A background asyncio agent (`SchemaExplorer`) that runs continuously against a connected database, working through a structured sequence of eight exploration phases without any user prompts. Each phase fires queries and records `(think, sql, observation)` episodes to a per-connection JSONL log.

### Why
Schema documentation is always out of date. The only authoritative source of truth about what a column actually means, which joins hold, and what states an entity passes through is the data itself. By running these queries autonomously in the background — not on demand — Aughor builds up this knowledge before the user asks their first question.

### How
Eight phases, each building on the previous:

| Phase | Name | What it learns |
|---|---|---|
| 3 | Null meaning resolution | Distinguishes "event not yet occurred" from data quality gaps for nullable columns |
| 4 | Join verification | Tests inferred FK joins, measures referential integrity |
| 5 | Lifecycle mapping | Extracts state machines from status columns (pending → shipped → delivered) |
| 6 | Distribution profiling | Detects shape, skew, outliers for numeric columns |
| 7 | Cross-table pattern discovery | Finds correlated columns and structural anomalies across tables |
| 8 | Domain intelligence | Adaptive curiosity loop — business questions per domain |

**Rate limiting:** Phases 3–7 run as fast as the DB allows (`_RATE_SECONDS_SCHEMA = 0.0`). Phase 8 self-throttles to one query per 5 seconds (`_RATE_SECONDS_INTEL = 5.0`).

**Stop / Resume / Restart:** The explorer honours a `_stopped` flag checked on every iteration. Stop state is persisted to `status.paused` so it survives frontend tab switches.

**Auto-resume on startup:** Only connections with an existing exploration state file are resumed on server startup. New connections are not auto-started — the user triggers them explicitly.

### Key files
- `aughor/explorer/agent.py` — `SchemaExplorer`, all eight phases
- `aughor/explorer/store.py` — JSON state persistence, `extend_domain_budget()`
- `aughor/explorer/episodes.py` — `EpisodeCollector`, JSONL append writer
- `aughor/explorer/models.py` — `ExplorationPhase`, `ExplorationStatus`

---

## 43. Business Ontology — Auto-Built

### What
Aughor automatically extracts a business ontology from the database schema and exploration findings: entities (Customer, Order, Product), relationships (Customer places Order), metrics (revenue, AOV), lifecycle state machines, computed properties, and deterministic SQL actions.

### Why
A schema tells you tables and columns. An ontology tells you what the business actually is — what entities exist, how they relate, what their lifecycle looks like, and what questions are answerable. This ontology is the context that makes chat and investigation answers domain-aware rather than schema-mechanical.

### How

**Structural extraction (`ontology/builder.py`):**
- Tables → entities via name pattern matching and type inference (transaction, event, dimension, …)
- FK edges and join hints → relationships with inferred cardinality
- Lifecycle columns → state machine extraction with terminal-state detection
- Metrics catalog → `OntologyMetric` nodes with formulas

**LLM enrichment (`ontology/enricher.py`):**
- Entity descriptions, domain assignments (Commerce / Finance / Operations / Marketing)
- Action definitions — natural-language descriptions of what you can ask about each entity
- Computed properties — virtual fields derived from raw columns

**Actions (`ontology/actions.py`):**
- Deterministic SQL templates generated from entity relationships
- Expanded at query time: `@get_orders_for_customer` → full SQL with real table/column names

**Divergence detection (`ontology/divergence.py`):**
- Checks generated SQL against the Metrics Catalog for formula consistency

**Display:** OntologyCanvas (interactive graph), EntityCard (detail panel), OntologyPanel (list view with edit).

### Key files
- `aughor/ontology/builder.py` — `extract_structural_ontology()`
- `aughor/ontology/enricher.py` — `enrich_ontology_semantics()`
- `aughor/ontology/models.py` — `OntologyEntity`, `OntologyRelationship`, `OntologyMetric`, `OntologyAction`, `OntologyGraph`
- `aughor/ontology/store.py` — fingerprint-keyed cache, `get_or_build_ontology()`
- `web/components/OntologyCanvas.tsx`, `EntityCard.tsx`, `OntologyPanel.tsx`

---

## 44. Domain Intelligence Loop

### What
Phase 8 of the background explorer: an adaptive curiosity loop that fires business intelligence queries per domain. It tracks coverage angles, stores findings as structured insights, detects novelty decay, and respects per-domain query budgets that the user can extend from the UI.

### Why
Schema exploration tells you what exists. Domain intelligence tells you what the data means for the business — how many orders are placed per day, which products drive the most revenue, what the retention rate looks like. These are the facts that make the ontology come alive and the chat answers feel grounded in real data.

### How

1. Load ontology → group entities by domain (Commerce, Finance, Operations, Marketing)
2. Per domain, track coverage angles (e.g., Commerce: volume, value, retention, basket_composition, seasonality)
3. Ask LLM for the most valuable next question — schema-grounded (exact column names injected into prompt)
4. Execute SQL — repair loop: run → get real error → fix with SqlWriter → run again (up to 3 attempts)
5. LLM interprets result as a business insight (1–2 sentences, specific numbers, novelty score 1–5)
6. Store insight, mark angle as covered, increment budget counter
7. Stop when: budget exhausted OR novelty decay (avg novelty of last 3 < 2.0)
8. After all named angles covered, continue with open-ended exploration (deeper_analysis, anomalies, cross_domain_patterns, trends)

**Budget extension:** User can click "+5 queries" per domain in the DomainIntelPanel. If the explorer is still running, the in-memory cap is patched live. If it has finished, a fresh explorer restarts with `domain_intel_only=True`.

### Key files
- `aughor/explorer/agent.py` — `_phase8_domain_intelligence()`
- `aughor/explorer/store.py` — `extend_domain_budget()`
- `aughor/api.py` — `POST /exploration/{conn_id}/domains/{domain}/extend`
- `web/components/DomainIntelPanel.tsx` — findings, budget bar, angle chips, "+5 queries" button

---

## 45. SqlWriter — Centralised SQL Writer & Self-Corrector

### What
A single class (`SqlWriter`) that is the one place in the codebase where SQL is generated and corrected — used by the chat pipeline, the Phase 8 domain intelligence loop, and the manual retry endpoint.

### Why
Before this, each caller had its own inline fix logic — slightly different prompts, different error handling, different alias resolution. When DuckDB errors mentioned `Table "im" does not have column "id"`, one path would inject the right column list, another would let the LLM guess and produce `SUM(0)`. Centralising means every fix attempt gets the same quality of diagnosis everywhere.

### How

**`SqlWriter.write(question, extra_context)`** — natural language → SQL
- Schema context injected at construction time (never re-fetched)
- Dialect-aware (`DuckDB` / `postgres`)
- Extra context (domain schema block, ontology entities) prepended per caller

**`SqlWriter.fix(sql, error, hint, max_retries)`** → `FixResult`
1. `_make_diagnosis(error, sql, table_cols)` — classifies the error:
   - DuckDB Binder (`Table "im" does not have a column named "id"`) → resolve alias to real table → look up exact columns
   - Prioritises DuckDB's own "Candidate bindings" (always authoritative) over schema lookup
   - Injects `DIAGNOSIS:` block with exact column list and explicit "NEVER substitute SUM(0)"
2. Format with `FIX_SQL_PROMPT` (shared across all callers)
3. Return `FixResult(ok, sql, explanation, attempts, final_error)`

**`_resolve_aliases(sql)`** — regex over `FROM`/`JOIN` clauses → `{alias_lower: real_table}`

**`_extract_candidate_bindings(error)`** — parses DuckDB's `Candidate bindings: "col1", "col2"` from error text

### Key files
- `aughor/sql/writer.py` — `SqlWriter`, `FixResult`, `_resolve_aliases`, `_make_diagnosis`, `_extract_candidate_bindings`
- `aughor/sql/__init__.py` — re-exports `SqlWriter`, `FixResult`
- `aughor/agent/prompts.py` — `FIX_SQL_PROMPT` (shared prompt used by all fix paths)

---

## 46. Activity Log UI

### What
A real-time feed in the Activity tab showing every exploration query as it fires — thinking trace, SQL, result observation — with stop/resume/restart controls that survive tab switches.

### Why
Exploration runs in the background. Without visibility, users have no way to understand what Aughor is learning, spot a bad query, or trust the resulting insights. The activity log makes the autonomous process transparent and controllable.

### How

- Polls `GET /exploration/{conn_id}/episodes` on a 3-second interval
- Each episode shows: phase badge, think label, SQL block (collapsible), observation preview
- `StatusBar` shows current phase + query count; `stopped` badge when paused
- **Stop:** calls `POST /exploration/{conn_id}/stop`; backend sets `explorer._status.paused = True` (persisted)
- **Resume:** calls `POST /exploration/{conn_id}/resume`; clears `_stopped`, continues from where it left off
- **Restart:** calls `POST /exploration/{conn_id}/restart`; deletes both the state JSON and episodes JSONL; starts fresh

Stop state is synced from `status.paused` on every fetch — survives component remounts (tab switches).

### Key files
- `web/components/ActivityLog.tsx`
- `aughor/api.py` — `POST /exploration/{id}/stop`, `/resume`, `/restart`, `GET /exploration/{id}/episodes`

---

## 47. Exploration State Persistence

### What
Full exploration state is persisted to a per-connection JSON file (`data/exploration_{conn_id}.json`) and episodes to a JSONL file (`data/episodes_{conn_id}.jsonl`). The explorer resumes from its last position after a server restart.

### Why
Schema exploration can take minutes to hours for large databases. If the server restarts mid-run, all findings would be lost without persistence. With persistence, the explorer picks up exactly where it left off — skipping already-explored tables, resuming the domain intelligence loop mid-domain.

### How
- `_store.load()` / `_store.save()` wrap JSON read/write with parent-directory creation
- `self._state` is the in-memory copy; every phase writes back after each finding
- `EpisodeCollector.add()` appends to JSONL atomically (newline-delimited JSON)
- On restart: `self._state` is loaded, completed keys are skipped at the start of each phase
- On `restart` (user-triggered): both files are deleted; fresh state is built from profiler data

**Auto-resume policy:** Only connections with an existing `exploration_{conn_id}.json` are resumed on server startup. Connections that have never been explored are not touched.

### Key files
- `aughor/explorer/store.py` — `load()`, `save()`, state schema
- `aughor/explorer/episodes.py` — `EpisodeCollector`
- `aughor/api.py` — `_start_explorers()` startup hook

---

## 48. Per-Phase Rate Limiting

### What
Schema exploration phases (3–7) run at full DB speed. The domain intelligence phase (8) throttles to one query per 5 seconds.

### Why
Schema phases produce structural knowledge (join maps, lifecycle states, null meanings) that every chat and investigation relies on — they should complete as fast as possible. Domain intelligence queries are expensive LLM-driven operations that stress the DB and could run for a long time. Slowing them down keeps the DB comfortable, allows the user to stop between queries, and gives time to review findings as they come in.

### How
- `_RATE_SECONDS_SCHEMA = 0.0` and `_RATE_SECONDS_INTEL = 5.0` — module-level constants
- `self._rate_seconds` — instance variable set by `explore()` before each phase group
- `_gate()` — async method called before every query: skips sleep if `self._rate_seconds == 0`, otherwise waits for the remaining window
- `explore()` sets `self._rate_seconds = _RATE_SECONDS_SCHEMA` before phases 3–7, then `_RATE_SECONDS_INTEL` before phase 8

### Key files
- `aughor/explorer/agent.py` — `_RATE_SECONDS_SCHEMA`, `_RATE_SECONDS_INTEL`, `_gate()`, `explore()`

---

---

## 49. Plan-then-SQL Separation

### What
The SQL generation stage is split into two distinct LangGraph nodes: `plan_queries` (pure reasoning — what to measure) and `execute_planned_queries` (SQL writing + execution — how to measure it).

### Why
The previous `plan_and_execute` node asked the LLM to simultaneously reason about which business questions to ask AND write correct dialect-specific SQL in one pass. These are different cognitive tasks — the planner thinks in business terms, the SQL writer thinks in database mechanics. Separating them improves both quality (the planner isn't distracted by SQL syntax) and debuggability (you can see the plan before SQL runs).

### How
**`plan_queries`** — pure LLM call with `PLAN_QUERIES_PROMPT`. Returns a `QueryPlanV2` containing a list of `QueryIntent` objects. Each intent describes WHAT to measure in plain English: which tables, what filters, what aggregation — no SQL. The ontology actions section and SQL examples are not injected here (they're not needed for planning).

**`execute_planned_queries`** — reads `current_plan` from state, iterates over each `QueryIntent`, calls `WRITE_SQL_PROMPT`/`SQLOutput` to translate each intent to SQL, runs the pre-flight ambiguity + join checks, executes with self-correction loop. Ontology actions and SQL examples are injected here at the SQL-writing stage.

New Pydantic models in `aughor/agent/state.py`:
- `QueryIntent` — `description`, `tables`, `filters`, `aggregation` (all plain English)
- `QueryPlanV2` — `hypothesis_id`, `tables`, `expected_if_true`, `expected_if_false`, `reasoning`, `query_intents: list[QueryIntent]`
- `SQLOutput` — `sql`, `reasoning`

`plan_and_execute` is kept as a thin shim for backward compatibility.

### Component interactions
- `aughor/agent/graph.py` — routes `plan_queries → execute_planned_queries → score_evidence`; routing edges updated
- `aughor/agent/nodes.py` — `plan_queries(state)` no conn; `execute_planned_queries(state, conn)` reads `current_plan`
- `aughor/agent/prompts.py` — `PLAN_QUERIES_PROMPT` (planning only, no SQL); `WRITE_SQL_PROMPT` (new, SQL per intent)

### Key files
- `aughor/agent/state.py` — `QueryIntent`, `QueryPlanV2`, `SQLOutput`, `current_plan` in `AgentState`
- `aughor/agent/nodes.py` — `plan_queries`, `execute_planned_queries`
- `aughor/agent/prompts.py` — `PLAN_QUERIES_PROMPT`, `WRITE_SQL_PROMPT`
- `aughor/agent/graph.py` — graph wiring

---

## 50. Non-blocking FastAPI Event Loop

### What
The backend event loop no longer blocks during active investigations. History, Ontology, Exploration, and Schema API calls all return normally while an investigation is running.

### Why
LangGraph's `agent.stream()` returns a synchronous iterator. Iterating it directly inside a FastAPI async generator was executing each node on the asyncio event loop thread — preventing all other requests from being handled until the node completed. A 30-second LLM call would freeze every other endpoint for 30 seconds.

### How
`_aiter_sync(sync_iter)` — a new async generator in `aughor/api.py` that wraps any synchronous iterator. Each `next()` call is dispatched to the default `ThreadPoolExecutor` via `loop.run_in_executor(None, next, it)`, returning control to the event loop between nodes. `StopIteration` is caught to end the async iteration cleanly.

Applied to both `_stream_investigation` and `_stream_resume` — every `async for event in agent.stream(...)` is replaced with `async for event in _aiter_sync(agent.stream(...))`.

### Key files
- `aughor/api.py` — `_aiter_sync`, updated `_stream_investigation`, updated `_stream_resume`

---

## 51. Loading State Hardening

### What
All data-panel components render immediately with empty/stale content and populate when the fetch completes — rather than showing a "Loading…" gate that blocks rendering while the server is busy.

### Why
Any in-progress investigation was saturating FastAPI's (then synchronous) event loop, making every other API call hang. Components initialised with `useState(true)` for loading would show a loading state indefinitely. Even after fixing the event loop, the anti-pattern of blocking UI on loading state remained in several components.

### How
Three changes per component:
1. `useState(false)` initial loading state (never blocks initial render)
2. `AbortController` with 8-second timeout on every fetch — calls abort after deadline so the UI never hangs
3. Silent `catch` — existing data stays visible, next poll will retry

Components updated: `ActivityLog`, `DomainIntelPanel`, `HistoryPanel`, `ConfigurePanel.DataTab`.

### Key files
- `web/components/ActivityLog.tsx`
- `web/components/DomainIntelPanel.tsx`
- `web/components/HistoryPanel.tsx`
- `web/components/ConfigurePanel.tsx`

---

## 52. Home Stat Card Navigation

### What
Each stat card on the home page is now a navigation shortcut that deep-links into the relevant tab or sub-section of the Data Sources panel.

### Why
The four stats on the home screen (Tables, Entities, Insights, Queries) correspond directly to tabs already in the app. Clicking through to the right place is a natural expectation — the stat cards were static and didn't act on that signal.

### How
`StatCard` gained an `onClick` prop, hover state (border lightens to the accent color), and pointer cursor. `HomePage` receives an `onGoToData(subTab?, section?)` handler from `page.tsx`.

| Card | Navigates to |
|---|---|
| Tables in Schema | Data Sources → Schema tab |
| Entities Mapped | Data Sources → Ontology tab |
| Insights discovered | Data Sources → Exploration → Intelligence sub-section |
| Queries executed | Data Sources → Activity tab |

**Insights count fix:** The "Insights discovered" count was reading `exploration?.insights_found` from the status endpoint (which returned 0 from persisted state). It now calls `getDomainInsights()` and sums `Object.values(d).reduce((sum, v) => sum + v.insights.length, 0)` — matching the count shown in the Intelligence sub-tab.

### Key files
- `web/app/page.tsx` — `StatCard` onClick, `explorationSection` state, `domainInsightCount`, `onGoToData`
- `web/components/ExplorationPanel.tsx` — `initialSection` prop + `useEffect` to navigate on mount

---

## 53. Schema Cache — Backend + Frontend Context

### What
A two-layer caching system that eliminates repeated schema fetches. The backend caches the schema string per connection for 5 minutes. The frontend shares one fetched `RichSchema` across all three data-panel components via React Context.

### Why
`get_schema()` on a real database runs COUNT(*) per table, cardinality sampling, profile cache lookup, profile build, glossary merge, ontology build, and exploration annotation — a pipeline that takes several seconds per call. Without caching, opening the Schema tab, Data tab, and Catalog tab for the same connection each independently triggered this full pipeline.

### How

**Backend (`aughor/api.py`):**
- `_schema_cache: dict[str, tuple[float, str]]` — maps `conn_id → (monotonic_timestamp, schema_str)`
- `_SCHEMA_CACHE_TTL = 300.0` (5 minutes)
- `_get_schema_cached(conn_id, db)` — returns cached string if fresh; otherwise calls `db.get_schema()`, stores result
- `_invalidate_schema_cache(conn_id)` — called on connection delete and ontology rebuild
- Three schema endpoints (`/schema`, `/schema/rich`, `/schema/mermaid`) all go through the cache

**Frontend (`web/lib/schema-context.tsx`):**
- `SchemaProvider` — React Context provider wrapping the right panel in `page.tsx`; fetches `schema/rich` once per `connId` change with 15s `AbortController` timeout
- `useSchema()` — hook that returns `{ connId, schema, loading, error, refresh }`
- `SchemaPanel` — replaced local `useEffect`/fetch with `useSchema()`
- `ConfigurePanel.DataTab` — replaced local `useEffect`/fetch with `useSchema()`
- `CatalogPanel` — uses context when `selectedConn === ctx.connId` (the common case); falls back to own fetch only when the user switches to a different connection in the catalog dropdown

### Key files
- `aughor/api.py` — `_schema_cache`, `_get_schema_cached`, `_invalidate_schema_cache`
- `web/lib/schema-context.tsx` — `SchemaProvider`, `useSchema`
- `web/components/SchemaPanel.tsx` — consumes context
- `web/components/CatalogPanel.tsx` — consumes context (with own-fetch fallback)
- `web/components/ConfigurePanel.tsx` — `DataTab` consumes context

---

---

## 54. Metric Targets & Health Scorecard

### What
Each tracked metric can now carry a `target_value`, `warning_threshold`, and `critical_threshold`. A `/health-scorecard` endpoint computes the current value for every targeted metric and returns green/yellow/red status with trend direction. A `ProcessHealthPanel` renders this as a proactive health grid — the first thing a user sees when opening the app.

### Why
Aughor previously answered questions. This makes it volunteer problems. "Refund Rate: 12% vs target 8% (red, ↑)" surfaces before the user types anything.

### How
`OntologyMetric` and `MetricDefinition` gain four new optional fields. The scorecard endpoint executes each metric's `formula_sql` against the live DB, computes `(current - target) / target`, and assigns a health band. ADA synthesis receives a `{metric_targets_section}` and is instructed to prioritise controllable root causes above threshold.

### Key files
- `aughor/ontology/models.py` — `OntologyMetric` target fields
- `aughor/semantic/metrics.py` — `MetricDefinition` target fields
- `aughor/api.py` — `GET /connections/{conn_id}/health-scorecard`
- `web/components/ProcessHealthPanel.tsx`

---

## 55. Structured Playbook from KB

### What
The 84 Tier-2 KB causal entries are automatically converted into a persistent, retrievable `PlaybookEntry` library. During ADA synthesis, matched entries replace LLM-generated recommendations. Unmatched root causes fall back to LLM generation but are flagged "unproven — add to playbook?".

### Why
The KB already encodes proven interventions as JSON. They were inaccessible to the synthesis step. Now "if refund_rate > 10%, review the return policy window" is a first-class recommendation that can accumulate a success rate over time.

### How
`aughor/playbook/builder.py` runs `seed_from_kb()` on startup, converting `inflation_causes` / `deflation_causes` / `causal_relationships` KB entries into draft `PlaybookEntry` objects stored in `data/playbook.json`. `playbook/retriever.py` matches root causes by metric name and trigger operator during ADA synthesis.

### Key files
- `aughor/playbook/models.py`, `store.py`, `builder.py`, `retriever.py`
- `aughor/agent/investigate.py` — synthesis integration
- `web/components/PlaybookPanel.tsx`

---

## 56. Outcome Tracking & Feedback Loop ✅ Shipped

### What
Users can mark each recommendation as accepted, implemented, or verified — with before/after metric values. `historical_success_rate` on playbook entries is recomputed after each outcome. Synthesis retrieves and presents entries ranked by success rate.

### Why
Without feedback, the playbook is a static list. With it, the system learns from organisational history. After 10 "reviewed return policy" outcomes, Aughor knows that action has a 70% success rate in 4 weeks.

### How
`aughor/playbook/outcomes.py` stores `RecOutcome` records (SQLite or JSON). A `POST /investigations/{inv_id}/recommendations/{rec_id}/status` endpoint logs outcomes and triggers `update_playbook_success_rates()`. `RecommendationInbox.tsx` surfaces pending recommendations across recent investigations.

### Key files
- `aughor/playbook/outcomes.py`
- `aughor/api.py` — outcomes endpoints
- `web/components/RecommendationInbox.tsx`

---

## 57. Document Ingestion — Context Layer ✅ Shipped

### What
Users can upload PDFs, Word docs, and Markdown files (SOPs, return policies, strategy decks). Chunks are embedded into a new `aughor_documents` Qdrant collection. During ADA synthesis, relevant document snippets are retrieved and injected alongside the KB as `{external_context_section}`.

### Why
Aughor only knew what was in the database schema and the hardcoded KB. It couldn't answer "How does our return rate compare to our stated policy?" because it had never read the return policy. This adds the missing external-context channel.

### How
`aughor/knowledge/documents.py` parses files into ~400-token chunks. `aughor/knowledge/indexer.py` embeds via the existing nomic-embed-text embedder and upserts into a new Qdrant collection, following the same `ensure_collection` + `upsert` + `search` pattern already used by three other collections.

### Key files
- `aughor/knowledge/documents.py`, `indexer.py`
- `aughor/semantic/kb_retriever.py` — extended to include document search
- `aughor/api.py` — document upload/list/delete endpoints
- `web/components/DocumentUploader.tsx`

---

## 58. Business Process Visual Mapper ✅ Shipped

### What
Process flows are extracted from ontology lifecycle states. Transition volumes and average dwell times are computed via SQL (`LAG()` window function). A swimlane diagram renders each lifecycle state as a node coloured green/yellow/red based on drop-off rate vs baseline — click a red step to launch an investigation scoped to that drop-off.

### Why
The ontology already knows Order has states `Pending → Shipped → Delivered / Canceled`. The business question "where are we losing customers in the funnel?" deserves a visual answer before the user formulates it.

### How
`aughor/process/mapper.py` queries the entity's lifecycle column via GROUP BY for node counts, and optionally uses `LAG() OVER (PARTITION BY pk ORDER BY ts)` to compute state transition volumes when a temporal column is available. Falls back to nodes-only mode for snapshot tables (one row per record). `ProcessMapper.tsx` uses a custom SVG layout engine — no @xyflow/react dependency. Health colours: green ≥80%, amber ≥50%, red <50% conversion rate per edge.

### Key files
- `aughor/process/models.py`, `aughor/process/mapper.py`
- `aughor/api.py` — `GET /connections/{conn_id}/process-map/{entity_id}`
- `web/components/ProcessMapper.tsx`
- `web/components/OntologyPanel.tsx` — "Map" tab in entity drawer

---

## 59. Causal Graph in Ontology ✅ Shipped

### What
An outcome-gated causal knowledge graph that accumulates verified cause→effect relationships from ADA investigations. Edges are only promoted to the graph when a human confirms the recommendation was effective (marking it `verified` or `implemented`). Confirmed edges appear as orange dashed arrows on the OntologyCanvas and feed back into future investigation context.

### Why
ADA discovers causal relationships on every investigation — "elevated stockout rate → increased refund rate". Without persisting these as a graph, each investigation starts from scratch. Persisting them turns the system into a compound learner. The outcome-gating prevents wrong investigations from polluting the graph over time — a key quality risk with auto-appended edges.

### How

**Proposal lifecycle:**

1. ADA synthesis extracts `causal_links: list[CausalLinkModel]` alongside the report — structured `(from_signal, to_signal, confidence)` pairs with evidence from the investigation
2. Proposals are saved to `data/causal_proposals.json` keyed by `inv_id` — not yet in the graph
3. When `log_outcome()` is called with `verified` or `implemented`, `promote_on_outcome(inv_id)` runs — weight +1 per confirmation, edge created if new
4. When called with `rejected`, weight -1; edges pruned at weight ≤ 0
5. Confirmed edges are stored in `data/causal_graph.json`

**Graph use:**
- `backward_traverse(target_signal, depth=3)` walks upstream from any signal to find known causes — used in `build_causal_playbook_section()` which is prepended to the playbook section in ADA synthesis
- `GET /connections/{conn_id}/causal-graph` returns all confirmed edges for a connection
- OntologyCanvas fetches and renders confirmed edges as orange dashed arrows with a ×N weight badge for multiply-confirmed edges; "causal" entry added to legend

### Key files
- `aughor/process/causal.py` — `CausalProposal`, `ConfirmedCausalEdge`, `save_proposals()`, `promote_on_outcome()`, `load_causal_graph()`, `backward_traverse()`, `build_causal_context_section()`
- `aughor/agent/prompts_investigate.py` — `CausalLinkModel`, `ADASynthesisModel.causal_links`, causal extraction instruction in synthesis prompt
- `aughor/agent/investigate.py` — saves proposals after synthesis; adds `investigation_id` to state
- `aughor/playbook/outcomes.py` — calls `promote_on_outcome()` on verified/implemented/rejected status
- `aughor/playbook/retriever.py` — `build_causal_playbook_section()` prepends confirmed causal context
- `aughor/agent/state.py` — `investigation_id` field added to `AgentState`
- `aughor/api.py` — `GET /connections/{conn_id}/causal-graph`
- `web/lib/api.ts` — `CausalEdge` type, `getCausalGraph()`
- `web/components/OntologyCanvas.tsx` — `CausalEdges` SVG overlay; `connId` prop; causal legend entry

---

---

## 60. Catalog 3-Panel Layout + Sample Data Tab

### What
The Catalog view is a full 3-panel Databricks-style browser: a connection sidebar on the left, a scrollable table list in the centre, and a detail panel on the right. The detail panel has two tabs — **Columns** (field names, types, FK flags, row count) and **Sample** (live data preview). Sample data loads lazily on first tab click — no network call until the user actually wants to see it.

### Why
The previous `CatalogPanel` was a flat accordion list with no way to inspect actual data values. Adding a sample tab fills the gap: users can immediately verify column contents, catch data quality surprises, and build intuition about the schema before writing questions or triggering investigations.

### How
`CatalogScreen.tsx` replaces `CatalogPanel.tsx` as the catalog entry point. A `SampleGrid` component handles the lazy fetch: on first render of the Sample tab it calls `sampleTable(connId, table, 100)`, shows a spinner, then renders a horizontal-scroll table. Cells display `—` for nulls and truncate at 32 characters with title-tooltip for full values. A row-count footer confirms how many rows were returned. The component self-fetches connections on mount via `getConnections()` so the panel is never empty even when the parent page's load was slow.

### Key files
- `web/components/CatalogScreen.tsx` — 3-panel layout, `SampleGrid`, `TableDetail`, `DetailTab` type
- `web/lib/api.ts` — `sampleTable(connId, table, limit)` → `GET /connections/{conn_id}/tables/{table}/sample`; `TableSample` interface (`columns: string[]`, `rows: (string|null)[][]`)

---

## 61. Phase 8 Ontology Gate

### What
Phase 8 (domain intelligence) now waits for the ontology to be available before it starts. If the ontology isn't in cache when Phase 8 is about to begin, the explorer builds it immediately by calling `get_schema()` — then proceeds. The missing-ontology warning is now logged at `warning` level rather than `info`.

### Why
Phases 3–7 (structural exploration) complete in a few seconds. The ontology was being built asynchronously — often finishing *after* Phase 8 had already been entered and silently exited on `load_latest_ontology()` returning `None`. The result was `insights_found: 0` with no visible error. This gate converts that silent failure into a proactive build with visible log output.

### How
In `explore()`, just before the Phase 8 loop starts, `load_latest_ontology(self.connection_id)` is called. If it returns `None`, `self._conn.get_schema()` is called synchronously — which builds, enriches, and caches the ontology as a side-effect. Any exception during the build is caught and logged; Phase 8 will then log a `warning` and skip gracefully. Manual recovery is still available via `POST /exploration/{conn_id}/domains/{domain}/extend`.

### Key files
- `aughor/explorer/agent.py` — ontology gate in `explore()` before Phase 8 block; `_phase8_domain_intelligence` warning upgrade

---

## 62. Connection Persistence Hardening

### What
A three-layer fix that prevents connections from being irreversibly lost when the server restarts. Connections appeared to disappear because the Fernet encryption key was only stored in an untracked file — if that file was deleted (e.g. by `git clean`) a new key was generated and all stored DSNs became unreadable. This is now impossible.

### Why
The connection registry encrypts DSNs with a Fernet key. The key was read from `data/.aughor_key` — an untracked, gitignored file that could easily be deleted during cleanup. Each deletion silently generated a fresh key, making every saved connection undecryptable. The only symptom was "connections missing" with no error, making the root cause very hard to find.

### How

**Layer 1 — Key pinned to `.env`:** `AUGHOR_SECRET_KEY` is now written into `.env` as the first entry. `aughor/db/registry.py` reads the key from this env var, falling back to the file only if the var is unset. The `.env` file is gitignored but tracked alongside the project, so the key survives `git clean`.

**Layer 2 — File gitignored:** `data/.aughor_key` (previously listed as `data/.hermes_key` — stale from the package rename) is added to `.gitignore`, preventing accidental commit of the raw key.

**Layer 3 — Startup validator:** `_validate_connections()` runs as a FastAPI startup event. It iterates every registered connection, attempts to decrypt its DSN, and logs a clear error for any that fail. Misconfiguration surfaces immediately at server start rather than silently at query time.

**CORS hardening:** `allow_origins` changed from `["http://localhost:3000"]` to `["*"]`. The restricted origin caused silent 4xx failures when the browser used any other origin (different port, IP address, or during local testing), which appeared as "no connections found."

### Key files
- `aughor/.env` — `AUGHOR_SECRET_KEY` pinned as first entry
- `aughor/.gitignore` — `data/.aughor_key` added
- `aughor/api.py` — `_validate_connections()` startup event; `allow_origins=["*"]`

---

---

## 63. Design System Consolidation ✅ Shipped (Sprint 42 — M22)

### What
A single token source of truth (`web/styles/tokens.css`) and type scale (`web/styles/type.css`) replacing scattered inline hex values, Tailwind zinc overrides, and inconsistent radius/font usage across 12 components.

### Why
The UI was using four styling systems simultaneously — `aug-*` CSS custom properties, Tailwind `zinc-*` classes, raw hex values (`#11171d`, `#1c2530`), and inline styles. Components looked polished in isolation but inconsistent together. Visual consistency requires one deliberate pass, not incremental fixes.

### How
- `tokens.css` exports the full Palantir Blueprint palette: `--bg-0..4`, `--b0..3`, `--t1..4`, `--r1..3` (2/4/6px max), intent colours `--blue/grn/amb/red/vio/cyn 1..5`, Tailwind bridge via `--color-zinc-*` aliases, dark + light mode via `[data-theme="light"]`
- `type.css` defines `.aug-text-h1/h2/h3/ui/sm/xs/mono`, `.aug-label` (corrected from 10px to 11px — was a design violation)
- `globals.css` now just imports both files; component classes remain there
- Component audit replaced `rounded-xl/2xl` → `rounded-md` (6px = `--r3`), `text-[9/10px]` → `text-[11px]` (11px floor), inline hex → CSS vars across `ConfigurePanel`, `InvestigationReport`, `ProcessHealthPanel`, `QueryBuilder`, and 8 others

### Key files
- `web/styles/tokens.css` *(new)*
- `web/styles/type.css` *(new)*
- `web/app/globals.css`
- 12 component files — radius + font + hex audit

---

## 64. Navigation Redesign + Command Palette + Ask Hero ✅ Shipped (Sprint 43 — M18)

### What
Five-section intent-based left nav (Ask / Investigations / Intelligence / Data Map / Governance), a global ⌘K command palette with fuse.js fuzzy search, and a new Ask hero screen as the default landing view.

### Why
The previous nav had 12+ items at a flat level — forcing users to know Aughor's internal architecture rather than express their intent. The command palette makes the dense analytical tool keyboard-first. The Ask hero creates a clear "start here" moment.

### How
**Nav restructure:** `NAV_GROUPS` in `page.tsx` reorganised into 5 sections. `"home"` tab removed; `"ask"` becomes default. `HomeScreen` replaced by `AskScreen`.

**`CommandPalette.tsx`:** Global ⌘K shortcut; `Fuse<PaletteItem>` with `threshold: 0.35`, `includeMatches: true`; character-level match highlighting via `Highlighted` component; grouped rendering (Actions / Investigations / Tables); keyboard navigation with `↵` kbd hint on active item; fetches `/investigations` + `/connections/{id}/schema` on open.

**AskScreen:** Centered textarea (680px max-width) with rotating placeholder (6 questions, 3500ms interval); Ask / Investigate mode toggle; connection health chip; stats strip linking to catalog/ontology/intel/activity; inline `ProcessHealthPanel`; 2-column recent investigation grid (now correctly navigates to existing report by ID, not re-submitting question).

### Key files
- `web/components/CommandPalette.tsx` *(new)*
- `web/app/page.tsx` — `AskScreen`, `NAV_GROUPS`, `openInvestigation()` handler

---

## 65. Evidence Ledger ✅ Shipped (Sprint 44 — M19)

### What
Every investigation finding becomes a first-class, auditable `EvidenceClaim` with full provenance: SQL source, metric used, data freshness timestamp, confidence score (0–1), and a human validation loop (Validated / Disputed / Needs Context).

### Why
Aughor previously produced findings as strings in a report. There was no way to answer: "What SQL backed that claim?", "Which metric definition was used?", "Has anyone validated this?" The claim evaporated when the report closed.

### How
`aughor/evidence/` package:
- `models.py` — `EvidenceClaim` (13 fields including `owner_feedback`, `outcome_status`)
- `store.py` — append-only SQLite at `data/evidence_ledger.db`; `INSERT OR IGNORE` idempotency; `update_feedback()` is the only mutation
- `linker.py` — `extract_claims_from_ada_phases()` (preferred, uses per-finding SQL directly) and `extract_claims_from_report()` (fallback, resolves SQL via `hypothesis_id` lookup); `_guess_metric()` regex covers 12 KPI keywords

`ada_synthesize` in `investigate.py` auto-extracts and stores claims at end of every investigation — wrapped in `try/except` so the ledger is never on the critical path.

**API:** `GET /investigations/{id}/evidence` · `POST .../evidence/{claim_id}/feedback`

**UI:** Evidence tab in `HistoryDetailPanel` alongside Report tab; `EvidenceClaimCard` with `ConfidenceBar` (green ≥75% / amber ≥50% / red <50%), SQL toggle, metric badge, feedback buttons.

### Key files
- `aughor/evidence/__init__.py`, `models.py`, `store.py`, `linker.py` *(all new)*
- `aughor/agent/investigate.py` — `ada_synthesize` evidence extraction
- `aughor/routers/investigations.py` — evidence endpoints
- `web/lib/api.ts` — `EvidenceClaim` type + API functions
- `web/components/HistoryDetailPanel.tsx` — Evidence tab + `EvidenceClaimCard`

---

## 66. Proactive Monitors ✅ Shipped (Sprint 45 — M20)

### What
Aughor volunteers problems before users ask questions. Metric monitors run on a cron schedule and fire alerts when values cross thresholds, reverse trends, behave anomalously, drift across segments, or when data tables stop updating. An intelligence digest card on the Ask screen surfaces unacknowledged alerts.

### Why
The health scorecard (M13a) shows metric status on demand. Monitors make that continuous — running in the background and proactively surfacing problems. This is what "always thinking" looks like to the user.

### How
`aughor/monitors/` package:

**`models.py`:** `Monitor` (13 fields, 6 `alert_on` types: `threshold_cross`, `any_change`, `trend_reversal`, `anomaly`, `segment_drift`, `data_freshness`) + `MonitorAlert` (14 fields, 3 severity levels: warning / critical / info).

**`store.py`:** Thread-safe SQLite at `data/monitors.db`. Full CRUD for monitors + append-only alert ledger with acknowledge flow.

**`runner.py`:** Dispatcher + 6 typed runner functions:
- `run_threshold_monitor()` — fires when value crosses `warning_threshold` or `critical_threshold`
- `run_any_change_monitor()` — fires on every non-trivial change; records baseline on first run
- `run_trend_reversal_monitor()` — compares rolling direction of last 3 stored values; fires on sign flip
- `run_anomaly_monitor()` — z-score vs 30-day history; configurable `sigma_threshold` (default 2.5); falls back to scalar SQL + stored alert history when no time-series SQL available
- `run_drift_monitor()` — Chi-squared goodness-of-fit vs uniform baseline across `dimension_column` segments; fires when `p < drift_p_threshold`
- `run_freshness_monitor()` — `MAX(updated_at)` staleness check; fires when gap > `freshness_sla_hours`

All runners are fully safe — exceptions are caught and surfaced as `info` alerts; the scheduler never crashes.

**`scheduler.py`:** `BackgroundScheduler` (APScheduler); `start()` loads all enabled monitors at startup and schedules cron jobs; `reload_monitor()` / `remove_monitor()` stay in sync with CRUD; `trigger_now()` for synchronous on-demand test runs.

**`digest.py`:** `build_digest(conn_id, period)` → `DigestResult` aggregating 5 sections: monitor alerts, exploration insights, top causal edges, open recommendations, evidence review queue. Renders to Markdown via `.to_markdown()`.

**`aughor/routers/monitors.py`:** 10 endpoints — `GET/POST/PUT/DELETE /monitors`, `POST /monitors/{id}/enable|disable|trigger`, `GET /monitors/{id}/alerts`, `GET /alerts`, `POST /alerts/{id}/acknowledge`, `GET /monitors/digest`.

**`aughor/api.py`:** `_start_monitor_scheduler()` startup event wired.

**Frontend:** Unacknowledged alert banner at the bottom of `AskScreen` — shows count + severity (critical/warning), expands to a per-alert list with inline Ack buttons. Auto-loads on `selectedConn` change.

### Key files
- `aughor/monitors/__init__.py`, `models.py`, `store.py`, `runner.py`, `scheduler.py`, `digest.py` *(all new)*
- `aughor/routers/monitors.py` *(new)*
- `aughor/api.py` — startup event + router registration
- `web/lib/api.ts` — `MonitorDef`, `MonitorAlert`, `DigestResult` types + 9 API functions
- `web/app/page.tsx` — `AskScreen` alert banner

---

## 67. History Navigation Fix ✅ Shipped (Sprint 45b)

### What
Clicking any investigation row in the History / Recents / Ask-screen recent cards now opens the existing investigation report directly. Previously, all three surfaces called `onGoToChat(inv.question)` — which started a brand-new chat with the question text and discarded the existing result entirely.

### Why
Navigating to history should show the past result — including the Evidence tab, the full report, and any feedback left — not re-run the question. The old behaviour was confusing and wasteful.

### How
Added `openInvestigation(id, kind)` handler in `page.tsx`:
- `kind === "investigation"` → `setSelectedHistoryInvId(id)` → renders `HistoryDetailPanel` with the full report
- `kind === "chat"` → `setSelectedChatSessionId(id)` → restores the chat session

`onOpenInvestigation` prop added to `AskScreen`, `HomeScreen`, and `RecentsScreen`. Row click handlers updated across all three surfaces to call `onOpenInvestigation(inv.id, kind)` instead of `onGoToChat(inv.question)`.

### Key files
- `web/app/page.tsx` — `openInvestigation()` handler; `AskScreen`, `HomeScreen`, `RecentsScreen` props + click handlers

---

## 68. Org-Level Ontology Board + `table = entity` Gate Fix ✅ Shipped (Sprint 52)

### What
Two connected pieces of work:

1. **Org-level ontology board.** A zoomable canvas that shows the *whole organization's* ontology at once — one bounding box per connection (database), and inside each box one sub-box per schema, each holding the **actual entity cluster** (nodes-and-edges graph: `Customer Order ──placed by──▶ Customer`, etc.) derived from that schema's tables. It is the same node/edge rendering the single-connection canvas uses, just tiled and grouped *connection → schema*. Trackpad pinch / ⌘-scroll zooms the entire board; clicking a connection header drills into its single-connection canvas.

2. **`table = entity` gate fix.** The ontology builder was silently dropping any table for which the profiler couldn't detect a single-column primary key (`grain_column is None`). On beautycommerce that meant only **8 of 20 tables** became entities — the 12 dropped were the biggest, most important commerce tables (orders, payments, invoices, order_items, carts…). The builder now treats *every profiled table* as an entity, honoring the core axiom; a detected grain merely upgrades an entity to `grain_verified` rather than gating its existence.

### Why
- A business user wants to see how the business is modeled *across the org*, not one connection at a time. The board makes the ontology a navigable knowledge map (connection → schema → entity relationships) you can traverse for questions like "why did revenue drop?".
- The gate fix restores the foundational promise: **a table is an entity.** Dropping the commerce backbone left the ontology unable to connect Orders → Payments → Order Items — exactly the traversal a root-cause analysis needs. After the fix beautycommerce went **8 → 20 entities** and **3 → 52 relationships**.

### How
**Reusable cluster (`web/components/OntologyCanvas.tsx`):** Extracted `EntityCluster` — the node/edge renderer (topological-depth `computeLayout` + `FlowEdges` + `CausalEdges` + `EntityNode` + column labels, with its own hover/neighbour-dimming state) drawing into a **local coordinate frame** sized exactly `w × h`. Added a cheap `measureCluster(graph)` size probe for packing. The single-connection `OntologyCanvas` now wraps one `EntityCluster` inside its zoom/scroll shell (behavior unchanged); the org board tiles many.

**Org board (`web/components/OntologyOrgCanvas.tsx`):** Fetches the connection list, then `getOntology(conn.id)` per connection progressively (shells first). Each connection box's width tracks its widest schema cluster; boxes flex-wrap into a near-square grid; one shared `selectedEntityId` highlights across clusters. The schema-group structure (`schemaGroups()`) already returns an array, so multi-schema connections will stack several schema sub-boxes with no further layout work. Reached via the **Org / Connection toggle** in the Ontology panel header (`OntologyPanel.tsx`).

**Trackpad zoom (`web/lib/useWheelZoom.ts`):** Shared hook — trackpad pinch (wheel + `ctrlKey`) and ⌘/Ctrl-wheel zoom-to-cursor; plain two-finger scroll falls through to native pan. Keeps the point under the cursor fixed while scaling. Used by both the single canvas and the org board.

**Builder gate (`aughor/ontology/builder.py`):** Removed the `if tp.grain_column is None: continue` skip in Step 1 (entity identification). Every profiled table now becomes an `OntologyEntity`; `identity_key` is coerced to `""` when no PK was detected, and `grain_verified` carries the quality signal. Relationships, actions, properties, and lifecycle extraction all already tolerate a missing grain.

### Known follow-ups
- The profiler still **misses real PKs** on some large tables (e.g. `invoices.order_id` is provably unique — 2,798,854 distinct = row count — yet returned `None`). Those entities now exist but are flagged unverified. Improving the profiler's uniqueness detection would upgrade them to verified grains and enable verified joins.
- Cross-connection ontology edges are intentionally not drawn (separate architecture).

### Key files
- `web/components/OntologyCanvas.tsx` — `EntityCluster` + `measureCluster` extraction; main canvas consumes the cluster
- `web/components/OntologyOrgCanvas.tsx` *(new)* — org board: connection → schema → `EntityCluster` tiling
- `web/lib/useWheelZoom.ts` *(new)* — shared trackpad pinch / ⌘-wheel zoom-to-cursor hook
- `web/components/OntologyPanel.tsx` — Org / Connection toggle + org-mode branch
- `aughor/ontology/builder.py` — relaxed entity gate (`table = entity`); `identity_key` coercion
- `web/components/QueryBuilder.tsx` — contrast pass (dim `text-zinc-600` → readable `text-zinc-500` per the token bridge)

---

## 69. Canvas Creation Popup + Canvas-Scoped Configure ✅ Shipped (Sprint 53)

### What
Two connected pieces of work that make the **Canvas** — not the raw connection — the unit a user creates and configures:

1. **Databricks-style "Connect your data" create flow.** The old 3-step wizard (Name → Connection → Tables) is replaced with a single-screen picker: a search bar, a breadcrumb (`All connections › <connection>`), a catalog list that drills from connections into their tables, a multi-select table list with an **"All tables"** pseudo-row at the top (auto-includes new tables), and removable **"Selected:"** chips in the footer. There is **no name field** — the user just scopes the data and clicks Create.

2. **Canvas-specific Configure slide-over.** The Configure panel used to operate on the raw `connection_id`. It now takes the `Canvas`: the **About** tab edits the Canvas name + description and shows its scope (connection, type, schema, "All tables" / N selected); the **Data** tab lists only the Canvas's scoped tables; **Instructions** are stored per-Canvas, not per-connection.

### Why
- Removing the name step removes the one piece of busywork in creation. The name should describe *what the data is about* — something the system can infer better than a user typing on a blank field.
- A Canvas is a curated slice of a connection. Configuring "the connection" leaked the wrong mental model and meant two Canvases over the same database shared one set of business rules. Making description, data, and instructions Canvas-scoped matches what the user actually reasons about.

### How
**LLM-inferred name + description (`POST /canvases/suggest-name`, `aughor/routers/canvas.py`):** Reads the schema of the selected tables (or the whole connection when "All tables" is chosen) and asks the `coder` provider for a Title-Case name (2–5 words) plus a one-line description, grounded strictly in the real table/column names. On create the frontend calls `suggestCanvasName()` then `createCanvas()`. The endpoint **falls back to the connection name** on any LLM error so creation never blocks. (e.g. selecting `orders` → "Customer Orders Overview".)

**Per-Canvas instructions (`GET/PUT /canvases/{id}/instructions`):** A small JSON store (`data/canvas_instructions.json`) keyed by `canvas_id`, mirroring the existing connection-level instructions endpoint but scoped to the Canvas — two Canvases on one connection keep distinct rules.

**Canvas-scoped Configure (`web/components/ConfigurePanel.tsx`):** The panel now receives `canvas` + `onCanvasUpdate`. About saves via `updateCanvas`; Data restricts the schema's table list to `canvas.scopes[0].tables` using a lenient leaf-name match (so schema-qualified names like `public.orders` still resolve), with empty scope meaning all tables; Instructions read/write the new Canvas endpoints.

**Request-contract hardening (`web/lib/api.ts`):** `createCanvas`/`updateCanvas` now send the backend's flat body (`connection_id` / `schema_name` / `tables`) instead of a `scopes` array, and a shared `fastApiError()` parses FastAPI's array-shaped `detail` into a readable message — fixing the "[object Object]" error that previously broke Canvas creation through both the table-selection and "All tables" paths.

### Known follow-ups
- The **Docs** tab (document uploader) and the **Instructions → Metrics** sub-tab are still connection/global-level, not Canvas-scoped.

### Key files
- `web/components/CanvasCreator.tsx` — rewritten single-screen Databricks-style picker; no name step; LLM auto-name on create
- `web/components/ConfigurePanel.tsx` — Canvas-scoped About / Data / Instructions
- `web/components/CanvasWorkspace.tsx` — passes `canvas` + `onCanvasUpdate` to Configure
- `web/lib/api.ts` — `suggestCanvasName`, `getCanvasInstructions`, `putCanvasInstructions`; flat-body + `fastApiError` hardening
- `aughor/routers/canvas.py` — `POST /canvases/suggest-name`, `GET/PUT /canvases/{id}/instructions`

---

## 70. Add Data, New Connectors & Workspace File Uploads ✅ Shipped (Sprint 54)

**What it does.** Turns "Add Data" into a real onboarding surface: a full page (not a slide-in) that lists every connector with brand marks, adds three new sources, and makes "Create or modify table" a genuine **file-upload → Workspace** experience with a typed, schema-aware import flow.

**Why it exists.** Users needed to bring their own data without a DBA — both external systems (MotherDuck, Exasol, Google Sheets) and ad-hoc files (CSV/Parquet/Excel/JSON) — and to control how each file lands (table name, schema, column types) instead of a silent best-guess ingest.

**How it works.**
- **New connectors.** `MotherDuckConnection` (cloud DuckDB via `md:`), `ExasolConnection` (pyexasol, `dep_check`-gated), `GoogleSheetsConnector` (public sheet → CSV export → in-memory DuckDB). Each registered in `connectors/registry.py` with form fields + DSN previews and categorised in `routers/system.py`; inline-SVG brand marks + colors in `BrandLogos.tsx`.
- **Workspace.** A built-in `local_upload` connection (in-memory DuckDB) that **folds in the sample `ecommerce` tables read-only** (ATTACH seed → materialize) alongside user uploads, replacing the old separate "Sample Catalog". Multi-schema: each schema is a directory; uploads persist to `data/uploads/workspace/{schema}/` with a sidecar `*.import.json` recording the table name + type overrides so the in-memory DB rebuilds identically every request.
- **Three-phase import.** `POST /connections/{id}/files/analyze` runs `DESCRIBE` + a 20-row preview + per-column **type-mismatch suggestions** (probing `try_cast` to BIGINT/DOUBLE/BOOLEAN/DATE/TIMESTAMP — catches `customer_id` read as text, etc.). The review UI lets the user edit the table name, pick/create a schema, override column types, and see conflict warnings; commit ingests with `TRY_CAST` (bad values → NULL, never a failed import).
- **Reliable columns.** New `GET /connections/{id}/tables/{t}/columns` (information_schema, with `LIMIT 0` fallback) drives the Catalog **Overview** column list so it's as dependable as Sample Data instead of the heavy whole-connection rich schema.
- **Readable tables.** `SqlResultTable` caps each cell at `maxColWidth` (320px) with ellipsis + tooltip so long-text columns don't blow out the layout.

**Key files.** `web/components/AddDataPanel.tsx`, `CatalogScreen.tsx`, `BrandLogos.tsx`, `AugTable.tsx`; `aughor/connectors/warehouse/{motherduck,exasol}.py`, `connectors/api/gsheets.py`, `connectors/file/local_upload.py`, `connectors/registry.py`; `aughor/db/registry.py`; `aughor/routers/{connections,catalog,system}.py`.

---

## 71. Agentic Investigation Polish — Coherence, Trace, Report, Timing ✅ Shipped (Sprint 55)

**What it does.** Makes an investigation read as one coherent chain and feel live: consistent figures across stages, an inline streaming trace, real chart labels, a calmer report with visuals upfront, and an elapsed-time readout.

**Why it exists.** Stages were planning SQL independently, so the same metric (e.g. distinct customers) could differ between the chain and the narrative; the trace lived in a dismissible sidebar; charts showed generic `label`/`value` axes; the report had too many fonts/colours/boxes and hid charts behind a Data toggle.

**How it works.**
- **Analysis ledger.** At the start of a run (explore `decompose_exploration`, investigate `ada_intake`) the planner LLM pins canonical **entity identifiers + metric SQL** (e.g. *unique customer = `customer_unique_id`*, *revenue = SUM(payment_value)*), seeded from the glossary-annotated schema. Stored on `AgentState.analysis_ledger` and injected into every sub-question/phase plan + synthesis prompt with a rule to reuse already-computed figures verbatim — so numbers stop drifting.
- **Inline trace.** `ThinkingTrace` renders at the top of each assistant turn, streaming step-by-step and **auto-collapsing** when the turn completes (shared `turnToTraceState`); the old 280px right sidebar is retired.
- **Real chart labels.** `barSpec` takes `xTitle`/`yTitle`; `InvestigationChart` passes humanised column names so the bar shows e.g. `Payment type` / `Revenue`.
- **Calmer report.** `ExplorationReportView` rebuilt to one body size, neutral palette, thin-border sections, chart + compact table expanded by default (only SQL collapsed), Conclusion + narrative merged into a single **Summary**.
- **Timing.** `ChatTurn` carries `startedAt`/`elapsedMs` (frozen at terminal states in the reducer); a "Completed in 12.4s" line shows for every mode including Quick.

**Key files.** `aughor/agent/{state,explore,investigate,prompts_explore}.py`; `web/components/{ThinkingTrace,ChatMessage,ChatPanel,InvestigationChart,VegaChart,ExplorationReport}.tsx`; `web/lib/useChat.ts`.

---

## 72. Canvas Optimisation — Scope Editing & History Management ✅ Shipped (Sprint 55–56)

**What it does.** Lets users curate a Data Canvas over time — add/remove tables from its scope, remove individual history line items — and fixes historical agentic reports that wouldn't open.

**How it works.**
- **Table management.** Configure → Data subtab lists all connection tables with a membership checkbox; toggling auto-saves the Canvas scope via `updateCanvas` (empty scope = all tables), with Include-all / Clear shortcuts.
- **History removal.** Each history row has a hover trash button; `delete_investigation()` now matches `id` **OR** `session_id`, so removing a chat line item clears the whole session.
- **Open-from-history fix.** `HistoryDetailPanel` was mounted in a non-flex block, collapsing its `position:absolute` report area to 0px (the report was saved but rendered blank). The Canvas mount is now a proper flex column with bounded height.
- **Scoped, clean history.** Canvas history is filtered strictly by **`canvas_id`** (chat turns persist `canvas_id` end-to-end through `/chat` → `save_chat_turn`) and shows only completed investigations + chat. A startup `sweep_stale_running()` marks orphaned `running` rows as `failed` so they stop cluttering the list.

**Key files.** `web/components/ConfigurePanel.tsx`, `CanvasWorkspace.tsx`; `web/lib/api.ts`; `aughor/db/history.py`; `aughor/routers/{canvas,investigations}.py`; `aughor/api.py`.

---

## 73. Data Canvas — List Ranking, Recents & Rename ✅ Shipped (Sprint 56)

**What it does.** Ranks the Canvas list by real usage, surfaces recently-used Canvases, and renames the concept to **Data Canvas** across the UI.

**How it works.**
- **Activity ranking.** `last_activity_by_canvas()` returns the most recent investigation/chat timestamp per canvas; `/canvases` is enriched with `last_activity`; the browser defaults to a new **"Latest investigation"** sort.
- **Recently used.** A card strip below the All Data Canvases table shows the top 5 by activity (connection + relative time), each opening the Canvas.
- **Rename.** User-facing "Canvas"/"Canvases" → "Data Canvas"/"Data Canvases" across nav, browser, workspace header/back/settings, command palette, and Configure. Internal routes (`/canvases`), types, IDs, and the store table are intentionally unchanged.

**Key files.** `aughor/routers/canvas.py`, `aughor/db/history.py`; `web/components/CanvasBrowser.tsx`, `web/lib/api.ts`, plus a UI label pass across `CanvasWorkspace.tsx`, `CommandPalette.tsx`, `ConfigurePanel.tsx`, `web/app/page.tsx`.

---

## 74. Grounded NL2SQL, Trusted Templates & the Eval Suite

**What it does.** Makes natural-language → SQL **correct on real, unseen schemas** — the core of the "plug-and-play data intelligence platform" thesis — and proves it with an execution-validated eval suite rather than vibes.

**Why it exists.** A bare LLM handed a raw schema hallucinates joins, mis-defines metrics, and fans out multi-table aggregations. Aughor competes with the best (Databricks Genie, Palantir Foundry/AIP) by *grounding* generation in structured, verified context and *measuring* every lever against real benchmarks.

**How it works — the grounding pipeline.** Each question flows through:
1. **Schema-linking** (`tools/schema_linker.py`) — narrows the schema to the relevant tables/columns, schema-agnostic (de-hardwired from any one schema), with a safety floor that never returns an empty schema.
2. **Data Catalog** (`tools/data_catalog.py`) — a MindsDB-style structured catalog: exact columns, types, sample rows, and detected foreign-key joins for the linked tables.
3. **Join grounding** (`tools/schema.py`) — FK detection that handles prefixed/fused keys (`c_custkey ↔ o_custkey`), surrogate keys (`ss_item_sk ↔ i_item_sk`), and role-played date dimensions; **star-schema routing** joins facts → dimensions (not fact↔fact); FK-neighbour expansion pulls in bridge tables a question needs only via a join.
4. **Temporal/dimension grounding** — for star schemas, brings `date_dim`/`time_dim` into context and tells the model `*_date_sk` columns are surrogate keys to join, not literals.
5. **Trusted query templates** (`semantic/trusted_queries.py`) — curated, data-team-reviewed verified SQL patterns, injected authoritatively when a question matches; fixes reasoning gaps prompt rules can't (e.g. multi-fact **fan-out** row multiplication). Emits a `trusted` SSE event for provenance / a "Verified" badge.
6. **Dialect normalization + self-correcting retry** (`sql/writer.py`) — SQLGlot transpiles to the target dialect; on error, a diagnosis (DuckDB-specific hints for `to_char`, `date_part`, …) drives a rewrite.

**The eval suite** (`evals/`) — execution-validated on real, unseen schemas:
- `run_tpch.py` — TPC-H (6M rows, joins) vs DuckDB's bundled official queries → **5/7**.
- `run_tpcds.py` — TPC-DS (24-table snowflake) vs `tpcds_queries()` → **4/5** (1/5 → 4/5 via the temporal lever).
- `run_clickbench.py` — ClickBench (105-col wide table) vs verbatim reference → **10/10**.
- `run_golden.py` — the full intelligence-injected pipeline on a golden set, measure-based scoring.
- `run_realdb.py` — **reference-free** on any live connection: auto-generates business questions from the schema, scores by executes-clean + **self-consistency** (two generations agree) + cross-model **LLM-as-judge** — the plug-and-play test and the basis for a per-answer confidence score.

**What the eval found (and fixed).** Model-invariant failures (qwen and kimi fail the *same* queries) proved the ceiling is *grounding*, not the model. Along the way the eval surfaced and fixed real bugs: a spurious-GROUP-BY rewriter (semantic_validator false positives corrupting correct SQL), a cross-connection metric leak (a wrong revenue formula injected into every connection), and a measure-comparator false-negative on large result sets.

**Platform hardening shipped alongside.** Connection pooling, Google Sheets connector, Anthropic (Opus) fallback when the primary LLM backend fails, explorer auto-start on new connections, audit-log noise reduction, and batched post-answer LLM calls.

**Key files.** `aughor/tools/{schema_linker,data_catalog,schema,semantic_validator}.py`, `aughor/semantic/{trusted_queries,metrics}.py`, `aughor/sql/writer.py`, `aughor/llm/provider.py`, `aughor/db/pool.py`, `aughor/routers/investigations.py`; `evals/run_{tpch,tpcds,clickbench,golden,realdb}.py`.

---

## 75. Self-Validating Semantic Layer, Fan-Out Guard & Multi-Schema Repairs ✅ Shipped

**What it does.** Wires the ontology's semantic richness into NL2SQL generation — guaranteed correct by executing every formula against the live DB first — adds a foolproof guard against multi-fact **fan-out** (the #1 model-invariant correctness failure), and repairs the runtime surfacing of Ontology, Briefings, Domain Intelligence, and Schema ERDs.

**Why it exists.** Aughor had a Palantir-grade ontology (entities, metrics, object sets, computed properties) but only ~20% of it reached the generator, and several runtime endpoints were silently broken so the intelligence never surfaced in the UI. Borrowing from **Cube.dev** (declarative semantic layer, symmetric aggregates) and **MindsDB** (knowledge bases, agent loop), this closes the gap between "knowledge computed" and "knowledge used."

**How it works.**
- **Self-validating ontology (Lever B — `ontology/validator.py`).** Executes every metric / computed-property / object-set against the live database and marks each `verified`. Conservative drop rules: SQL error, non-finite / overflow value, or the product-of-aggregates anti-pattern `AGG(...) * AGG(...)` (the `SUM(fp)*SUM(qty)` → $3T class). Runs once per schema fingerprint inside `build_intelligence`, persisted. Caught the $3T formula plus hallucinated column refs across three schemas.
- **Semantic-layer injection (Lever A — `ontology/semantic_block.py`, `semantic/metrics.py`).** Question-scoped, **verified-only** injection of named object sets (NL "active orders" → the verified `WHERE`), computed properties, and unified metric formulas into the chat + eval prompts. Connection-scoped + verified-gated → a literal no-op for any connection without a validated ontology, so the benchmarks are unaffected (ClickBench held 10/10).
- **Fan-out guard (M24d — `sql/fanout.py`).** A conservative, high-precision static detector (sqlglot scope analysis + FK-root cardinality) flags only when ≥2 raw satellite tables of a shared hub are aggregated across a direct join — the campaigns→{clicks, impressions} chasm trap. **Validated to zero false positives across 121 official TPC-H/TPC-DS queries** before wiring. On a hit it drives a directed pre-aggregate rewrite (each satellite in its own CTE), adopted only if it re-executes clean — the principled, schema-wide replacement for the trusted-template fan-out band-aid, borrowed from Cube's primary-key symmetric aggregates.
- **Robust enrichment (`ontology/enricher.py`).** Root-caused the intermittent total loss of computed properties to local models stringifying/malforming a deeply nested structured-output field; flattened it to a list, added tolerant JSON coercion, and ran enrichment at temperature 0. Eliminated the "0 computed properties" collapse (now reliably 7–9 per run).
- **Runtime repairs.** Ontology endpoints 404'd (now read the cached graph rather than the no-longer-building fast `get_schema`); the briefing hung on integer citation refs (coerced to string); the ontology ERD was empty because the join map carried schema-qualified names while `table_to_entity` was bare (**0 → 38 relationships**); the built-in Workspace's multi-schema in-memory DuckDB failed every bare-name query (set `search_path` across all user schemas — **~1875 errors → 0**); the Catalog schema ERD filtered qualified rich-schema names against bare catalog names (now matches on the bare segment scoped to the schema — **0 → 6 tables + 9 joins** on the bakehouse schema).

**Key files.** `aughor/ontology/{validator,semantic_block,enricher,builder,models}.py`, `aughor/semantic/metrics.py`, `aughor/sql/fanout.py`, `aughor/knowledge/briefing.py`, `aughor/routers/{ontology,investigations}.py`, `aughor/connectors/file/local_upload.py`, `evals/run_golden.py`, `web/components/CatalogScreen.tsx`.

**Borrow study.** Cube.dev (declarative semantic layer, PK-keyed symmetric aggregates, measure additivity, pre-aggregations) + MindsDB (KB embed→rerank→threshold, plan→execute→correct agent loop). Top lever = symmetric aggregates for fan-out; the convergence is a stable, declarative, governed semantic layer the LLM *augments*, never regenerates.

---

## 76. Reusable Component Architecture, Shared Primitives & Exhaustive Test Pass ✅ Shipped

**What it does.** Rebuilds ERD, Ontology, Charts, and Tables as **single-source-of-truth components on canonical contracts**, backed by shared primitives, so a fix lands once and propagates everywhere — then verifies every feature, endpoint, background process, and vector collection end-to-end against a regression baseline.

**Why it exists.** The same qualified-vs-bare table-name bug had been fixed **three separate times** (ontology relationships, Workspace `search_path`, Catalog ERD) because there was no shared primitive — 20+ ad-hoc `.split(".")` sites — and the UI carried three chart implementations, six copies of cell-formatting, and three colour palettes. That drift is how platforms rot. This consolidates the duplication into one of each and proves the platform still works everywhere.

**How it works.**
- **Canonical table-name layer (`aughor/tools/table_names.py` + `web/lib/tableName.ts`).** One primitive — `bare` / `leaf` / `schema_of` / `same_table` / `resolve_in` / `TableRef` — is the *only* place table names are split, compared, or qualified, on both backend and frontend. The qualified-vs-bare bug class is now impossible to recur. 15 backend comparison sites + the CatalogScreen ERD filter migrated onto it; pinned by `tests/unit/test_table_names.py`.
- **Frontend shared primitives.** `web/lib/format.ts` is the single formatting home — `compactNumber` / `formatMetricValue` / `formatPercent` / `pct` / `cleanLabel` / `verbLabel` + the full date/granularity suite — folding 8 large-number, 5 percent, 3 label, and 2 date implementations into one. `web/lib/palette.ts` consolidates `AUG_PALETTE` / `TABLE_PALETTES` / `H_PALETTES` (was copy-pasted ×3). 17 components migrated.
- **One of each component.** A single **`<Chart>`** engine (16 view types — bar / line / multi-line / stacked / pie / heatmap / scatter / combo / treemap / matrix / change-metric) extracted from a 2,200-line `ChatMessage`; **`<ERDiagram>`**, **`<OntologyGraph>`**, **`<DataTable>`** each on a canonical contract. `InvestigationChart` became a thin toggle-wrapper that delegates to `<Chart>` — the three-implementation chart sprawl is gone. **~1,500 lines of duplication removed.**
- **Regression oracle + write-flow exerciser (`scripts/smoke.py`, `scripts/flows.py`).** smoke drives every GET endpoint off the live OpenAPI spec + checks the 8 Qdrant collections + diffs against a baseline; flows drives the write/background side (metric validate, monitor create+trigger, knowledge, document upload). Both repeatable and baseline-diffable.
- **Exhaustive verification (`TEST_REPORT.md`).** 16 UI surfaces walked (zero console errors); the four components verified rendering with real data (bakehouse ERD joins, a live Insight chart, the analytics ontology at 20 entities / 38 relationships); a full Deep-Analysis investigation driven to completion (31.5s, a grounded "not measurable" verdict — it hit a real data gap and refused to hallucinate); and the write / Qdrant flows confirmed.

**Bugs found and fixed by the test pass (0 regressions across the whole refactor — 5 fixes).** `/ontology/skills` + `/ontology/autonomy` 500 (a referenced-but-unbuilt `aughor.memory` subsystem → minimal inert package); `/canvases/{id}/suggestions` 500 (a sync handler invoking an async function without `await`); `/monitors` 500→422 (a permissive request model vs the domain model's strict `Literal`s); `/ontology/rebuild` 500→422 (in-memory file uploads can't be re-opened for a rebuild); and a self-defeating bug in the smoke oracle itself (`--out` clobbering the diff baseline before comparison).

**Key files.** `aughor/tools/table_names.py`, `aughor/memory/`, `aughor/routers/{canvas,monitors,ontology}.py`; `web/lib/{format,palette,tableName}.ts`, `web/components/{Chart,InvestigationChart,ERDiagram,OntologyCanvas,AugTable}.tsx` (+ 17 migrated components); `scripts/{smoke,flows}.py`, `tests/unit/test_table_names.py`, `TEST_REPORT.md`.

---

## 77. The Brief — Answer Surface, Agent Reasoning Quality & Data-Shape Intelligence ✅ Shipped

**What it does.** Re-grounds both answer modes in *how the data is actually shaped*, rebuilds them to read like a published analytical brief, and gives the agent a cross-sectional path for "where are we losing money" questions that have no time axis.

**Why it exists.** Insight and Deep Analysis rendered as stacks of cards, badges and banners (the opposite of the Databricks/Palantir reference); the agent forced a temporal frame on every question (wrong metric, an empty comparison window, "HIGH confidence" on zero data), and its profile saw only date min/max — never the distributions, grain, or partial periods needed to reason about the data's shape.

**How it works.**
- **The Brief.** One flat rendering vocabulary (`web/components/brief/`): `Brief` / `BriefHeadline` / `BriefProse` / `BriefSection` / `BriefMetrics` / `BriefFigure` / `BriefDetails`. Prose carries the analysis with real **bold** on key numbers; charts and tables are the only framed blocks; SQL, confidence factors, attribution and data gaps fold into one quiet disclosure. Insight = a short brief, Deep Analysis = a long one. The purple Insight card, trend/confidence pills, anomaly chips, amber banners and accordion-in-accordion are gone.
- **Agent reasoning quality.** A single sign convention (losses negative everywhere) is mandated in the synthesis prompt + model docs + a backend coercion, so no quantity renders +green in one component and −red in another. A deterministic confidence floor forces LOW when no usable data was gathered. Narrative prompts lead with the answer and bold decisive numbers.
- **Data-shape intelligence.** The profiler captures numeric distributions (mean/median/stddev/p25–p75 — DuckDB `SUMMARIZE` already computed them and they were discarded), derives the analytical grain from span + cadence (`_choose_grain`), flags an incomplete trailing period, and intake clamps comparison windows to the real date range (no empty-period comparisons).
- **Cross-sectional diagnostics.** An `_is_diagnostic_question()` trigger (or no date column) routes "where/which is weakest / where are we losing money" to a new `ada_cross_section` node — a dimensional weakness scan that ranks the money metric across each dimension — instead of the temporal baseline.
- **Live trace.** The Deep-Analysis trace renders the real phases with plain-language, present-tense labels and live status.

**Key files.** `web/components/brief/`, `web/components/{ChatMessage,InvestigationReport,ThinkingTrace}.tsx`; `aughor/tools/{profiler,profile_cache}.py`; `aughor/agent/{investigate,graph,prompts_investigate,prompts_explore}.py`, `aughor/routers/investigations.py`; `scripts/answer_sweep.py`.

---

## 78. Intelligence-Surface Trust — Scope Consistency, Self-Explaining Intelligence & ADA Correctness ✅ Shipped

**What it does.** Makes the intelligence surfaces trustworthy: the Briefing scopes consistently across connection / schema / canvas, is **never silently empty** (it explains *why* and offers the fix), the Deep-Analysis (ADA) path grounds every user-facing number in the actual result rows, and worst-case latency is roughly halved.

**Why it exists.** Intelligence *looked missing* even when the platform was working: an empty Briefing said only "No intelligence to brief yet" — never that the connection had simply never been explored, or that exploration finished but Phase-8 domain intelligence was ontology-gated to empty. The Briefing also briefed the whole connection while the Domains panel beside it was canvas-scoped, so the two disagreed. And the ADA path could emit a headline number that contradicted its own chart ("says city, shows country"), build a fan-out metric that read in the billions, or fail outright on a missing-column bind — the opposite of *reassuring users of intelligence quality*.

**How it works.**
- **Scope-consistent Briefing.** A scope-keyed briefing cache (`get_briefing(..., scope_key)`) plus a canvas-scoped endpoint (`POST /exploration/canvas/{id}/briefing`) let the Briefing scope to Workspace → Connection → {Schema | Canvas}. The `canvasId` prop threads `CanvasWorkspace → IntelligenceWorkspace → BriefingPanel`, so a Canvas's **Intelligence** tab briefs *its* curated tables and renders stacked above the canvas Domain panel.
- **Self-explaining empty state.** `BriefingEmpty` is now cause-aware off the explorer lifecycle (`emptyReason(status)`), with four states mapped 1:1 to the explorer phases: *never run* → **Start exploration**; *running* → live phase/query/insight counts + spinner; *failed* → the error + **Restart**; *complete but no domain intelligence* (the silent-empty case — Phase-8 is ontology-gated and can legitimately be 0 after a complete run) → the ontology/sparse-schema *why* + **Generate domain intelligence**. Shared `runExplorer` / `runTriggerIntel` actions back both the control bar and the empty-state CTA, and an auto-reload on phase→complete surfaces fresh intelligence without a manual reload.
- **ADA correctness (cross-sectional path).** Narrator findings bind to their queries by **identity (token overlap), not list index**, killing the position-desync that made a card say "city" while its chart plotted "country"; the chart category axis selects the **metric over the share** and prefers **name columns over id columns**; a per-record / **average lens** is added for cross-sectional questions. Locked by `tests/unit/test_cross_section_binding.py`.
- **ADA grounding (/chat parity).** Headlines are **grounded against the result rows** and replaced only on contradiction (column sums/means accepted); a **SQL self-repair loop** converts a binder "missing column" error into a JOIN hint and retries; a **fan-out metric guard** rejects product-of-aggregates / subquery-in-aggregate (the $3T class) and falls back to a safe `SUM(measure)`; the ADA SQL plan is handed a **join-complete schema** (FK neighbours + temporal-dimension tables + detected join paths) with a strict "use the exact `table.column`, never re-qualify" instruction.
- **Latency.** Three sequential intake validation retries became one combined retry; the narrator is skipped entirely on dead (all-empty / all-failed) phases; an opt-in **fast narrator tier** (`AUGHOR_FAST_NARRATOR_MODEL`, falls back to the narrator) runs per-phase interpretation. Net: synthesis **117s→18s**, interpret **117s→20s**, worst-case early-stop **~278s→~150s** on all-qwen.
- **Trusted data-context glossary.** A curated `data/glossary.yaml` captures table grains, canonical joins, and column semantics for trusted, parameterized generation.

**Verified live.** Empty-state paths confirmed in the running UI — a *complete*-but-zero-insight connection shows "No domain intelligence yet" + Generate CTA, a *pending* connection shows "No exploration has run yet" + Start CTA, and a Canvas's Intelligence tab renders the canvas-scoped Briefing ("…for this canvas's tables…") stacked over its Domain panel. The ADA grounding fix took "why did revenue change recently?" from a total failure ("unknown") to a correct monthly trend with a real z-score. 75 unit tests green.

**Key files.** `web/components/{BriefingPanel,IntelligenceWorkspace,CanvasWorkspace,Chart}.tsx`; `aughor/knowledge/briefing.py`, `aughor/routers/{exploration,investigations}.py`; `aughor/agent/{investigate,graph,prompts_investigate}.py`, `aughor/llm/provider.py`; `data/glossary.yaml`; `tests/unit/{test_cross_section_binding,test_quality_fixes}.py`; `docs/{PIPELINE_QUALITY_ASSESSMENT,INTELLIGENCE_UNIFICATION}.md`.

---

## 79. Adaptive Temporal Scope — Tier 0/1/2 + Anchor Tuning ✅ Shipped

**What it does.** Replaces the naive "last 12 months" window with a system that *discovers when matters* — Aughor's temporal USP. It anchors analysis on the trailing edge of real activity, narrows to the current statistical regime, and juxtaposes that against the full-history long arc.

**Why it exists.** A fixed window anchored on `MAX(any date column)` breaks the moment a schema has a calendar / date-dimension table: those run far into the future (TPC-DS `date_dim` → 2100), dragging the window past the last real fact so every fact filter returns zero rows ("no data" briefings). And a fixed window can't tell "revenue is down this quarter" from "revenue is down within a multi-year climb." The pitch: *we don't ask you when — we discover when matters.*

**How it works.**
- **Tier 0 — role-aware recency (`explorer/agent.py`).** The window's trailing edge is the consensus recency among **measure-bearing activity tables**, not any date column. Calendar/dimension spines are excluded — by zero-measures, by name (`date_dim`/`dim_date`/`calendar`/…), and by **shape** (≥70% of a table's "measure" columns are date-parts like `d_year`/`d_moy`/`d_qoy`, which the profiler mis-tags). Sentinel dates (9999/1900/epoch) are filtered, and the dense `effective_date_range` is preferred. The calendar↔fact gap is surfaced as a data-quality discrepancy.
- **Tier 1 — current-regime narrowing (`explorer/regime.py`).** Queries the activity density series (rows per period at the profiler grain) and runs single-changepoint binary segmentation (minimise within-segment SSE) gated by a significance threshold; narrows the window start to a recent structural break only when it clears a ~90-day floor. Live on beautycommerce: a campaigns regime break narrowed a 12-month window to the active 6 months.
- **Tier 2 — full-span macro context (`explorer/temporal.py`).** One cheap coarse rollup (`GROUP BY year`) over the anchor produces the long arc — growth factor, year-by-year series — gated to ≥3 year-buckets so a partial boundary year can't masquerade as YoY growth. Injected to lead the briefing narrator with a juxtaposition instruction ("activity grew 4× over 8 years, but the current regime is flat"). Live: TPC-H → 7-year arc on `lineitem` ("held roughly flat", `l_quantity` 19.3M→17.5M).
- **Anchor tuning.** On a recency tie the **core fact** (most rows, within a 45-day tolerance) wins, so a 5K-row `campaigns` can't beat a 6.4M-row `order_items` that ends the same day. A measure-column key-name guard skips `SUM(l_orderkey)`-style nonsense in the macro rollup. Validated across beautycommerce / TPC-H / TPC-DS.

**Key files.** `aughor/explorer/{agent,regime,temporal}.py`, `aughor/knowledge/briefing.py`, `aughor/routers/exploration.py`; `tests/unit/{test_temporal_scope,test_regime,test_macro_context}.py`; `docs/ADAPTIVE_TEMPORAL_SCOPE.md`.

---

## 80. Finding Actionability & Scheduled Brief Delivery ✅ Shipped

**What it does.** Turns every passive intelligence finding into something the user can *act on* — and pushes intelligence to them without opening the app.

**Why it exists.** Aughor computed rich findings (Briefing headlines, Hub insights) but they were read-only; the Monitors, Action Hub, and Evidence subsystems all existed but were unwired to the findings. This makes intelligence *reach* the user — "heavy-duty actionable intel."

**How it works.**
- **Finding-level actions (`web/components/{BriefingPanel,IntelligenceHub}.tsx`).** A compact toolbar on every Briefing card and expanded Hub insight: **Create Monitor** (builds an anomaly monitor from the finding's own SQL), **Promote to Org** (connection- *and* canvas-scoped — connection-level findings had no promotion path before), **Share** (fires the finding through a configured Slack/webhook/Jira Action Hub trigger), and **Evidence** (a drill-through drawer showing the source query + confidence/novelty/freshness behind the claim).
- **Connection-scoped promote (`explorer/store.py`, `routers/exploration.py`).** `promote_insight_conn` + `POST /exploration/{conn}/insights/{id}/promote`, the counterpart to the canvas promote, pushing the finding into the org-intelligence vector store.
- **Share to trigger (`routers/actions.py`).** `POST /actions/triggers/{id}/send` fires an arbitrary finding through the existing delivery + retry + logging path.
- **Scheduled brief delivery (new `aughor/briefs/` subsystem).** A `BriefSubscription` (connection, cron, delivery trigger) persisted to JSON; an APScheduler job (mirroring the monitors scheduler) builds the Intelligence Digest on schedule and delivers it through an Action Hub trigger; `/briefs/subscriptions` CRUD + `/test`. Delivery is decoupled from channel mechanics by reusing triggers as the transport.

**Key files.** `aughor/briefs/{models,store,delivery,scheduler}.py`, `aughor/routers/{briefs,actions,exploration}.py`, `aughor/explorer/store.py`; `web/components/{BriefingPanel,IntelligenceHub}.tsx`, `web/lib/api.ts`; `tests/unit/{test_actionability,test_briefs}.py`.

---

## 81. Evidence Peer Layer & Intelligence-Surface Visuals ✅ Shipped

**What it does.** Makes the Evidence Ledger a first-class intelligence layer with a human validate/dispute loop, and makes the Deep-Analysis trace and the Briefing genuinely visual.

**Why it exists.** Every Deep-Analysis claim was already logged with its source SQL and confidence (the Evidence Ledger, feature #65), but only reachable per-investigation — there was no way to see "what has Aughor claimed about this connection lately, and does it hold up?" And two surfaces leaned too hard on text: the agent trace was a static list, and the Briefing was a wall of prose.

**How it works.**
- **Evidence peer layer (`web/components/{EvidencePanel,IntelligenceWorkspace}.tsx`).** A new "Evidence" layer beside Briefing/Hub/Domains. Because the ledger keys only by `investigation_id`, scope resolves through `history.list_investigation_ids(conn, canvas)` → `evidence.get_recent_claims_for_investigations(ids, limit)`, exposed as `GET /investigations/evidence/recent` (registered before `/{inv_id}/evidence` so the literal segment can't be captured as an id). Each claim shows confidence, metric, freshness, an expandable source query, and **Validated / Disputed / Needs-context** feedback that persists — teaching Aughor which findings hold up. Live-verified: feedback round-trips to the ledger and the layer scopes correctly to a canvas.
- **Deep-Analysis live stepper (`web/components/ThinkingTrace.tsx`, `app/globals.css`).** The agent trace renders as an animated stepper: a violet→emerald progress bar, a checkmark-pop as each step completes, a pulsing dot on the active step, a flowing connector rail, and staggered entry — with a `prefers-reduced-motion` guard. Rendering-only (the step derivation is untouched).
- **Visual Briefing (`web/components/BriefingPanel.tsx`).** The Briefing leads with a domain-coverage bar chart (findings per domain, opacity by novelty) and per-finding novelty meters on the headline and signal cards, replacing single-number summaries.

**Key files.** `aughor/{routers/investigations,evidence/store,db/history}.py`; `web/components/{EvidencePanel,IntelligenceWorkspace,ThinkingTrace,BriefingPanel}.tsx`, `web/app/globals.css`, `web/lib/api.ts`; `tests/unit/test_evidence_scope.py`.

---

## 82. Semantic Compiler — Typed Intent IR + Deterministic SQL ✅ Shipped

**What it does.** For the safe, common analytical shapes, the LLM fills a small *typed intent* instead of hand-writing SQL — and the SQL is **assembled deterministically** from the verified ontology. "The LLM augments a declarative layer rather than regenerating SQL."

**Why it exists.** Free-form LLM SQL hallucinates columns and fans out joins (a real finding in this codebase referenced four non-existent columns). For the shapes that map 1:1 to a grounded template, generation should be *compilation*, not guessing — the strategic endpoint of the metric-unification + ontology work.

**How it works.** `aughor/semantic/compiler.py`:
- **`QueryIntent`** — a typed IR: `intent_type` (scalar / timeseries / breakdown / ranking), entity/table, a named `metric` OR an `agg` over a measure column, dimension, time grain, object set, window, order/limit — all *symbolic* references.
- **`synthesize_sql(intent, ontology, dialect)`** — resolves every reference against the verified ontology (measure/dimension columns, object-set filters, the canonical metric resolver), assembles a single-table SQL template, and dialect-transpiles with sqlglot. **Coverage-gated:** an unresolved reference, a multi-table metric, a `SUM` over a non-measure column, an unverified object set, or an unsupported intent → returns `None` and the caller falls back to the LLM path. Single-table only (joins are where free-form generation fans out, so they stay on the fallback path). It never guesses.
- **`parse_intent` / `compile_question`** — one structured LLM call maps a question to a grounded intent (choosing only from a strict catalog of real names); `compile_question` runs the full NL → intent → SQL path.
- **Chat fast-path** — `_stream_chat` injects the compiled SQL as a VERIFIED block and forces it as the executed query (gated `AUGHOR_COMPILER`, fully fallback-safe).

**Verified.** End-to-end on beautycommerce: *"how many attributions"* → `scalar/count` → `COUNT(*)` → 6.9M; *"total weight by touchpoint type"* → `breakdown`; *"top 3 touchpoint types by weight"* → `ranking` — each parsed to a grounded intent and executed clean. 24 unit tests (grounding + every gate).

**Key files.** `aughor/semantic/compiler.py`, `aughor/routers/investigations.py`; `tests/unit/test_compiler.py`.

---

## 83. Temporal Tier 3 — Query Cost Governor ✅ Shipped

**What it does.** Lets intelligence build "without breaking sweat" against TB-scale warehouses, via two safe, high-value levers plus an incremental re-exploration watermark.

**Why it exists.** Completes the Adaptive Temporal Scope arc (Tier 0/1/2). The curiosity loop leans on high-cardinality `COUNT(DISTINCT)` and full-table scans; at scale those need cost governance without throwing away correctness.

**How it works.** `aughor/sql/cost.py`:
- **`approximate_aggregates`** — `COUNT(DISTINCT x)` → `approx_count_distinct(x)`, median/quantile → `approx_quantile` (DuckDB; a no-op elsewhere). HLL is ~1–3% off for orders of magnitude less work (live: 2.88M vs exact 2.80M on a 6.9M-row table).
- **`sample_aggregates`** — for a single-table scan, `USING SAMPLE p%` + scale `COUNT`/`SUM` by `100/p` (`AVG`/`MIN`/`MAX` unscaled). **Refuses joins and any distinct count** — sampling a distinct undercounts (a bug this caught: `approx_count_distinct` on a 10% sample reads 10× low). Live: 7.1M / 10.16 vs exact 7.0M / 10.0.
- **`govern`** — approx on by default (safe); sampling opt-in + row-threshold gated; flags every approximation in a provenance note.
- **`aughor/explorer/watermark.py`** — per-(connection, table) activity high-water mark + `delta_clause`, so a recurring re-run can scan only rows since last time (a Monday brief on a 10-yr warehouse scans last week).
- **Explorer wiring** — detects a large connection (any table ≥ 5M rows) and applies the approx governor to the Phase-8 loop; records the anchor watermark each run. Live: beautycommerce → `cost_large=True` (carts 10M / attribution 6.9M), watermark `order_items` @ 2026-05-17.

**Rollout note.** Sampling stays opt-in (scaled estimates in user-facing numbers want a per-surface decision) and the watermark-driven incremental re-run *mode* is captured but not yet used to skip partitions.

**Key files.** `aughor/sql/cost.py`, `aughor/explorer/{watermark,agent}.py`; `tests/unit/{test_cost,test_watermark}.py`.

---

## 84. Finding Trust Guards — Numeral Grounding & Platform-Generic SQL Robustness ✅ Shipped

**What it does.** Keeps *wrong numbers* out of the intelligence layer. A finding is only as good as the figure it reports; this is the set of deterministic guards that make Aughor's numbers trustworthy, not just plausible.

**Why it exists.** A from-scratch rebuild watch over six connections surfaced trust bugs the eye misses: a finding that read "2.49M attribution credit" when the real cell was 2.49 (off 1e6, fabricated "M"), and recurring SQL failures that wasted the curiosity budget. Every fix is driven by the database engine's own error text / profiled types — no schema or connection specifics — so the learning transfers across DuckDB, Postgres and any connection.

**How it works.**
- **Numeral grounding** (`aughor/explorer/grounding.py`) — extracts every magnitude-bearing number a finding claims and verifies it against the actual result cells (rounding-window + 2% tolerance). A fabricated magnitude/unit is dropped or one corrective re-grounding pass is attempted; degenerate (all-NULL) results never become findings. Live: isolates exactly the fabricated `2.49M` while real cells pass.
- **Timestamp typing** (`aughor/tools/profiler.py`) — `_select_timestamp_cols` excludes numeric-typed columns from the name-based primary-timestamp fallback (ClickBench `EventDate::USMALLINT` is epoch-days, not a date); `_NUMERIC_TYPES` broadened to DuckDB unsigned ints.
- **Dead-reference memory** (`aughor/explorer/agent.py`) — harvests nonexistent column/table names from engine errors into a per-run set, fed back to the question generator so it stops re-proposing hallucinated columns. Live: workspace fix-failures 29→5 (−83%), repeated `region` hallucinations 4→0.
- **Repair-diagnosis branches** (`aughor/sql/writer.py`, shared with chat/ADA) — missing-table → add-join/drop-ref; unexposed-column → select-out/qualify; ambiguous-ref → qualify-with-alias; non-inner-join-on-subquery → INNER/CTE rewrite. Live on beautycommerce: yield 18→27.

**Key files.** `aughor/explorer/grounding.py`, `aughor/tools/profiler.py`, `aughor/explorer/agent.py`, `aughor/sql/writer.py`; `tests/unit/{test_grounding,test_profiler_timestamp,test_sql_repair_learnings}.py`.

---

## 85. Angle-Feasibility Gate & Repair Intent-Preservation ✅ Shipped

**What it does.** Stops the autonomous explorer from asking a *time-based question of a table with no time*, and from silently *changing the meaning* of a question while repairing it.

**Why it exists.** A live finding proposed "outstanding receivables by invoice age over the last 12 months" against an `invoices` table with no date column. The LLM invented `invoice_date`; the repair made it run by swapping in `invoice_delay_days` — but that is payment *delay*, not invoice *age*. A query that runs and answers a different question is more dangerous than one that fails.

**How it works.**
- **Angle-feasibility gate** — each domain table's `primary_timestamp` is computed; a dateless domain drops temporal coverage angles and gets a "NO TEMPORAL DATA" instruction, while a mixed domain names its dateless tables ("never apply dates/aging/windows to these"). Live: Finance now writes honest "invoice delay distribution" findings instead of inventing a date column; 0 misleading age/aging findings stored.
- **Intent-preservation guard** — a repair that *substituted columns* and **de-temporalised** a query (the original computed over time, the repair no longer does) is dropped (explorer) or flagged unverified (user fix). A first attempt using an LLM faithfulness check **failed verification** (the model rated the drift "faithful"), so it is deterministic. A second drift mode — `DATE_DIFF(CURRENT_DATE, CURRENT_DATE)` faking a constant-0 "age" while keeping temporal SQL — is caught by a dedicated **vacuous-temporal** detector.

**Key files.** `aughor/explorer/agent.py` (`_is_temporal_angle`, `_query_columns`, `_has_temporal_sql`, `_has_vacuous_temporal`); `tests/unit/test_phase8_feasibility.py`.

---

## 86. Fix-and-Save & Fix-All from the Activity Log ✅ Shipped

**What it does.** Turns the Activity log's per-row "Run fix" from a disposable preview into a durable action — a successful repair is saved like any successful query — and adds a filter-scoped "Fix all" to clear a batch of errors at once.

**Why it exists.** When a user makes the effort to fix an errored explorer query and it works, that result should be reflected and referenced, not thrown away on close. At the same time a bulk fixer must be safe — it must never trigger a fresh crawl of new questions.

**How it works.** `aughor/explorer/fix_persist.py` → `persist_fixed_finding()`: repairs the query and on a clean run (1) **heals the episode** (appends a resolved turn — append-only, no history rewrite) and (2) for domain-intelligence queries **interprets + stores a finding** into Briefing/Hub/Domains, through the *same* Phase-8 guards (degenerate / grounding / de-temporalisation / vacuous-temporal). A guard-tripping fix is still stored but flagged **`unverified`** (low confidence, never auto-promotable) with a note; non-domain phases heal only.
- **Endpoints** — `POST /exploration/{conn}/fix-episode` (one) and `/fix-all` (a batch). Fix-all repairs **only** the episodes the client sends — exactly the errored set visible under its current filter (all/today/yesterday/week) — so it never re-derives "all errors", never starts the explorer, and never generates new questions. Returns a per-batch summary.
- **Frontend** (`web/components/ActivityLog.tsx`) — "Run fix" keeps its preview plus a "Save as finding" button with clear feedback; "Fix all (N)" sits in the toolbar scoped to the visible filter. Threaded through connection + canvas scope.

**Key files.** `aughor/explorer/fix_persist.py`, `aughor/routers/exploration.py`, `web/{lib/api.ts,components/ActivityLog.tsx}`; `tests/unit/test_fix_persist.py`.

---

## 87. Deterministic Fan-out De-fan — Parent + Chasm ✅ Shipped

### What
A `SUM`/`COUNT` over a one-to-many join silently over-counts (the "fan-out" / join-amplification / chasm trap) — the platform's #1 model-invariant correctness failure. Aughor now **detects and deterministically rewrites** the query so each value is counted once, before the number ever reaches the user.

### Why
On TPC-H, `SUM(orders.o_totalprice)` joined to `lineitem` returns **$1,134B instead of $226.8B (5.0×)**; on ecommerce, 2.4×. The prior fix detected the fan-out and asked the LLM to rewrite it — measured at **1/5 reliable**, with the failures returning plausible CTEs that *still* double-count ("looks fixed but isn't"). Correctness can't be probabilistic, so the rewrite is now deterministic and exact.

### How
1. `detect_fanout` (existing, high-precision) classifies the shape: `parent_fanout` (one parent measure across a detail join) or `chasm` (≥2 satellites of one hub aggregated across a star join).
2. `build_parent_fanout_rewrite` wraps the source in a `DISTINCT(parent-join-key, measure)` subquery, then re-aggregates — exact and filter-preserving.
3. `build_chasm_fanout_rewrite` pre-aggregates **each satellite** to its hub key in its own CTE, then joins the CTEs to the hub 1:1.
4. A `defan()` dispatcher routes by kind; the caller **dry-runs** the rewrite and adopts it only if it executes clean. High-precision: both rewriters bail to `None` on any shape they can't prove (child-level `GROUP BY`, `AVG`/`COUNT(*)`, a satellite `WHERE`, an outer join, a hub-column agg mixed in).
5. Wired into **all three SQL-executing surfaces**: chat (`investigations._stream_chat`, pre-execution), explorer Phase-8 (`agent.py`, before a finding is interpreted), and Deep Analysis (`investigate._execute_safe`).

### Component interactions
- Verified against the DB oracle across 6+ query shapes × 2 schemas; every surface verified end-to-end (fanned → corrected number) on real data.
- Supersedes the prompt-only fan-out guard; the LLM hint remains the fallback for shapes the deterministic rewriter declines.

### Tech / libraries
- **SQLGlot** — parse, clone, and reconstruct the rewrite (CTEs via `.with_()`, join surgery).

**Key files.** `aughor/sql/fanout.py`, `aughor/routers/investigations.py`, `aughor/explorer/agent.py`, `aughor/agent/investigate.py`; `tests/unit/test_fanout_rewrite.py`.

---

## 88. Finding-Trust Ladder — Guards, Quarantine & Dismiss-with-Reason ✅ Shipped

### What
A layered defense against autonomous-explorer hallucinations: prevent bad findings at the source, guard them at generation, systematically remediate the ones already stored (without ever deleting them), and let the user dismiss-with-reason — feeding corrections back into the guards.

### Why
A live Evidence card claimed *"the 'Unknown' acquisition channel, the only channel represented…"* with `NOVELTY 77568/10` and 95% confidence. Root cause: the explorer pursued a coverage angle (acquisition channel) whose column doesn't exist, so the model stubbed `'Unknown' AS signup_source`; and the LLM echoed the revenue magnitude (77568) into the 1–5 novelty score, pinning confidence and letting junk own the Briefing.

### How
1. **Angle-feasibility gate** — don't pursue a coverage angle whose required column class is absent; plus a pre-execution skip of any free-proposed question that fabricates a constant dimension (`_has_fabricated_dimension`).
2. **Generation guards** — drop fabricated-dimension findings, clamp runaway novelty to [1,5], drop per-grain mislabels (line-item `AVG` narrated as a per-order metric — the $467-vs-$1108 case), and flag semantic metric drift (a repair swapping revenue↔cost).
3. **Re-validation / quarantine pass** (`revalidate.py` + `scripts/revalidate_findings.py`) — re-checks *stored* findings, flags the bad ones `invalid` (hidden from intel via the store read-filter, **kept in the store, reversible — never deleted**), and repairs in-place a real finding whose only flaw is a bad score. Dry-run by default.
4. **Dismiss-with-reason** — a "Dismiss" action on every finding card; the reason is logged to `finding_dismissals.jsonl` so user corrections become systematic signal for new guards/eval fixtures. Dismissed cards vanish instantly.

### Component interactions
- Quality-sweep harness gained `FABRICATED` + `AOV` detectors (reusing the same guards) so the platform self-grades for these classes.
- Standing rule encoded: bad findings are preserved as reproductions, never deleted, because they drive systematic platform fixes.

### Tech / libraries
- **SQLGlot** — constant-dimension / per-grain detection; **regex** semantic-group matching for metric drift.

**Key files.** `aughor/explorer/{agent,fix_persist,revalidate,store}.py`, `aughor/routers/exploration.py`, `web/components/{BriefingPanel,IntelligenceHub}.tsx`, `scripts/{quality_sweep,revalidate_findings}.py`; `tests/unit/test_{degenerate_finding,angle_feasibility,revalidate,dismiss,metric_guards}.py`.

---

## 89. Delivery Polish — Significance Badge, Sparkline/MoM, Pareto ✅ Shipped

### What
The answer surface caught up to the reasoning: a glanceable "within-noise" significance badge, a sparkline + month-over-month delta on time-series findings, and a Pareto (80/20) chart that surfaces concentration.

### Why
"Reasoning outruns presentation" — the analysis was already computing significance (`is_significant`) and concentration, but the UI only showed raw prose. These are the last-mile-of-trust cues a reader scans for.

### How
1. **Significance badge** (`brief/StatBadge.tsx`) — surfaces `is_significant` as a quiet "Significant" / "Within noise" marker (the value was computed but only shown as raw stat-note text).
2. **Sparkline + MoM%** (`brief/Sparkline.tsx`) — pure-SVG sparkline + a `seriesTrend()` helper that computes period-over-period % and labels MoM/WoW/YoY by granularity.
3. **Pareto** (`Chart.tsx`) — sorted bars + cumulative-% line + 80% rule. Because the model emits a share column for 80/20 questions but tags `chart_type:auto`, a deterministic backend rule (`_maybe_pareto`) forces Pareto when the question signals concentration and the result is a category ranking; the renderer also auto-detects a `*_share`/cumulative column.

### Component interactions
- All three plug into the ADA report's `EvidenceBlock` (and the Pareto into any `<Chart>` surface). `EvidenceBlock` now passes the finding's `chart_type` through (it was computed then ignored).

### Tech / libraries
- **Vega-Lite** (Pareto spec, dual-axis), pure-SVG (sparkline/badge).

**Key files.** `web/components/brief/{StatBadge,Sparkline}.tsx`, `web/components/{Chart,InvestigationReport}.tsx`, `aughor/routers/investigations.py`, `aughor/agent/prompts*.py`.

---

## 90. Eval Trustworthiness — Pinned State, Metric-Aware Scoring, Noise Control ✅ Shipped

### What
The golden NL2SQL eval can now be *trusted* to measure the real capability lift of the intelligence-injected pipeline (FULL) over raw generation (RAW) — three levers that close the confounds that made earlier A/B runs unreadable, plus a deep-test that overturned a surface "−8 regression" into "no regression."

### Why
Running the full-pipeline eval (#13) had shown FULL *losing* to RAW — but the result was confounded (it ran on an *explored* connection whose drifting insights steered the metric choice, on top of LLM run-to-run noise). Without a trustworthy eval, every correctness/capability claim downstream is guesswork. This is the force-multiplier that makes measured work possible.

### How
1. **Pinned connection + frozen-state guard** (`run_golden.py`) — FULL runs default to `samples` and **abort** if the connection carries volatile exploration insights (verified: `workspace`'s 7549 bytes → hard abort). Each run prints a provenance block (model / temperature / exploration-state / ontology) and disables the silent Anthropic fallback so the model is pinned. The #13 confound can't recur silently.
2. **Metric-aware multi-reference scoring** (`sql_accuracy.py`) — a record may carry `accept_sql`, equally-valid alternative ground truth; the answer is scored against the BEST of `{reference} ∪ accept_sql`, so a *different-but-canonical* metric definition isn't penalised — without becoming permissive to wrong answers (`tests/unit/test_eval_scoring.py`, 5 cases).
3. **Noise control** — `--temperature` (default 0.0) threaded through both generators and the `SqlWriter` retry path; `--runs N` reports the per-question score band; `runs_detail` caches each run's SQL so a batch can be **re-scored offline with zero new LLM calls**.

### Deep-test (the finding)
Pinned `samples`, temp-0, N=3, `qwen3-coder-next:cloud`. Two results overturned the headline: **(A)** temp-0 is *not* deterministic on cloud (RAW 21/53 unstable, band 0.175 → N-averaging is mandatory); **(B)** most of FULL's −8 pass gap is the **ex-cancelled revenue convention** (22/53 queries add `WHERE status NOT IN ('cancelled', …)`), not capability — convention-neutral (MAX-of-definitions estimator), **RAW 28 / FULL 26 (Δ−2, within noise)**; the convention explains +6 of the −8, and FULL posts 5 clean wins where injected context rescues a query RAW fails outright (sql009 0.00→0.85, sql034 0.00→0.85). The binding constraint on measuring lift is **metric unification** (golden refs ↔ injected definition), now quantified and made measurable.

### Component interactions
- Reuses the production building blocks (`_stream_chat`'s schema-linker / catalog / metrics / semantic-layer / retry) so the eval reflects real platform behaviour, not a re-implementation. The `defan()` de-fan path is mirrored so fan-out correctness is in-scope.

### Tech / libraries
- **SQLGlot** (the convention-isolation probe strips the status predicate via AST), DuckDB (`samples`), pytest.

**Key files.** `evals/run_golden.py`, `evals/sql_accuracy.py`, `evals/_add_accept_sql.py`, `evals/_probe_convention.py`, `evals/_analyze_13b.py`, `evals/FINDINGS_full_pipeline.md`, `tests/unit/test_eval_scoring.py`, `aughor/sql/writer.py`.

---

## 91. Product Robustness Program — Fail Graceful by Contract ✅ Shipped

### What
A test-locked guarantee that the platform fails *gracefully* under every adverse condition: bad inputs, dead dependencies, and crashes produce a clean error or a recovery — never a 500, a hang, or a silent-wrong success.

### Why
"Near-flawless & fool-proof before enterprise rollout." A fragility scan was reassuring, so the work was to *lock* the good behaviour and restore the safety net, not clean up a mess.

### How
1. **Failure-path contract** (`tests/integration/test_failure_paths.py`) — unknown resources → 4xx never 500; invalid SQL → a *surfaced* error, never silent-empty; the security boundary stays closed to stacked / comment-hidden / case-mixed `DROP`/`TRUNCATE`/`UPDATE`/`DELETE` and neutralises DDL-via-query-run.
2. **Hot-path fault injection** (`tests/integration/test_fault_injection.py`) — when the LLM provider throws mid-request, `/chat` emits one error event and the process survives; `SqlWriter.fix()` fails *soft* (the contract the explorer relies on to drop one angle, not crash the run); the investigate salvage path never raises.
3. **Crash recovery** — `scripts/chaos_drill.py` SIGKILLs the server mid-exploration and asserts orphans are FAILED-with-reason, checkpoints resume, the journal narrates it, **and** the recovered server actually serves a query (invariant I4).
4. **Lifespan migration** — the 11 deprecated `@app.on_event("startup")` handlers became one `@asynccontextmanager` lifespan (behaviour byte-for-byte preserved).
5. **Regression locks for the 3 original reported bugs** (`tests/integration/test_original_bugs_regression.py`) — a source-contract tripwire for the blank-canvas wiring, a real backend contract for sample-error surfacing, and an existence check for the temporal coverage suites.

### Tech / libraries
- FastAPI `TestClient`, pytest (`--run-e2e` opt-in for live-LLM cases), the K1 job kernel's `boot_recovery`.

**Key files.** `tests/integration/test_failure_paths.py`, `test_fault_injection.py`, `test_original_bugs_regression.py`, `scripts/chaos_drill.py`, `aughor/api.py`.

---

## 92. Correctness-Guard Expansion — Binder Repair, Chasm `COUNT(*)`, Narration Inversion ✅ Shipped

### What
Three new deterministic guards in the trust layer, each born from a real wrong-number observed live.

### Why
The explorer kept dropping analytical angles to un-diagnosable DuckDB Binder errors, the fan-out guard ignored bare `COUNT(*)` chasms, and the narrator could universalise a per-group value into a confident falsehood.

### How
1. **Phase-8 Binder repair** (`aughor/sql/writer.py`) — reproduced the real DuckDB error strings, then added diagnosis branches for the GROUP-BY-completeness class and `EXTRACT(EPOCH FROM (date−date))`, plus prevention rules in the dialect prompt; the previously-dropped error classes now repair to executable SQL.
2. **Chasm `COUNT(*)` lint** (`aughor/sql/fanout.py::count_star_chasm_fanout`) — flags `COUNT(*)` over ≥2 satellites of the same hub (the `campaigns ⋈ clicks ⋈ impressions` cross-product) that `detect_fanout` deliberately skips; silent on single joins, `COUNT(DISTINCT)`, and the pre-aggregated-CTE correct form.
3. **Narration-inversion guard** (`aughor/agent/verify.py::inverted_universal_claim`) — fires only when prose makes an "all/every/each ⟨entity⟩ have/has ⟨N⟩" claim that the result distribution contradicts; the explorer **drops** the finding, chat/ADA **caveat** it (inline note + Trust-Receipt flag / `DataQualityNote`).

### Component interactions
- All three are wired and **runtime-proven** firing on the real path (explorer Phase-8 loop, `/chat`, `synthesize_report`), not inferred from sibling guards.

**Key files.** `aughor/sql/writer.py`, `aughor/sql/fanout.py`, `aughor/agent/verify.py`, `aughor/agent/nodes.py`, `aughor/routers/investigations.py`.

---

## 93. Metric Unification Hardening — Stop the Cross-Connection Leak ✅ Shipped

### What
Closed two holes in the global-metric machinery that let a wrong canonical formula reach (or a right one miss) the generator's prompt — surfaced by a beautycommerce sweep where "revenue" was being computed three ways and intermittently under-counted ~50% ($252M vs the correct $503M).

### Why
A metric authored for one connection must never inject its column-mismatched formula into another's prompt, and a curated, Finance-approved formula must not be silently stripped by an unverified ontology template.

### How
1. **Formula-column schema filter** (`aughor/semantic/metrics.py::_metric_matches_schema`) — the filter checked a metric's tables + dimensions but **not the columns in its formula**, so `revenue = SUM(total_amount)` injected into a connection with no `total_amount`. Now every formula column must exist in the schema (sqlglot extraction; conservative — an unparseable formula adds no constraint).
2. **Ontology-overlay catalog-keep** — the overlay dropped a curated catalog metric whenever the ontology had an *unverified same-name* metric, even a *different* failed template. Now it only drops when the failed ontology formula **matches** the catalog (preserving the product-of-sums protection); otherwise the Finance-approved catalog wins.
3. **Registration** — beautycommerce's gross-line revenue / AOV registered in `data/metrics.json`, verified end-to-end (revenue $503M, AOV $179.82, deterministic across re-runs).

**Key files.** `aughor/semantic/metrics.py`, `data/metrics.json`, `tests/unit/test_metric_schema_filter.py`.

---

## 94. Measure-Additivity Layer — Per-Unit vs Per-Line Grain ✅ Shipped (increment 1)

### What
The platform now learns each measure's **additive grain from the data**: a per-UNIT measure (a unit price → the additive line value is `price × quantity`) vs a per-LINE measure (an already-totalled margin → `SUM(margin)` is correct). It already modelled column semantic-type, entity grain, and joins — this adds the missing piece needed to aggregate a measure *correctly*.

### Why
Two measures can live in the same table at different grains (`final_price_usd` per-unit, `gross_margin_usd` per-line). Treating them identically produced both the revenue under-count *and* a margin double-count (−$20,882 vs the correct −$8,712). Per-connection metric registration was a band-aid that could even over-generalise; detecting grain from the data retires the class generally.

### How
1. **Detection signal** (`aughor/semantic/measure_grain.py`) — bucket rows by the quantity column and read `AVG(measure)`: flat (ratio ≈1) → per-unit; scales (ratio ≈k) → per-line. Verified on real data before building; conservative `unknown` unless the fit is clean. One cheap `GROUP BY` probe, cached per connection (0.1s on 2.7M rows).
2. **Misuse guard** — `SUM(per_line × quantity)` = double-count; `SUM(per_unit)` without `× quantity` = under-count; correct forms silent. Wired into the explorer drop path; runtime-proven dropping the real gross-margin double-count on the live connection.

### Component interactions
- Next increments (tracked): inject a "measure grains" PREVENTION block into the generator; persist grain on the ColumnProfile/ontology during profiling; cross-surface caveat in chat/ADA.

### Tech / libraries
- DuckDB (the AVG-by-quantity probe), SQLGlot (the guard's AST), pytest.

**Key files.** `aughor/semantic/measure_grain.py`, `aughor/explorer/agent.py`, `tests/unit/test_measure_grain.py`.

---

## 95. Query Builder — Schema-Qualified Correctness + Bounded Preview ✅ Shipped

### What
A correctness pass on the visual Query Builder that also unblocked it on real connections: it was effectively **unusable on any schema-qualified connection** — the rich schema returns dotted names (`analytics.order_items`) that were quoted as a *single* identifier (`"analytics.order_items"` → "table does not exist"), and the catalog tree's bare names never key-matched, so columns never loaded.

### Why
The headline demo connection (beautycommerce) couldn't run a single query in the builder and showed "No columns available". A fresh `SELECT *` also defaulted to **no LIMIT** — a footgun on million-row tables.

### How
1. One `quoteTable()` helper (replacing three drifting copies) quotes **each dotted segment** → `"analytics"."order_items"`.
2. Phase-2 ingestion **canonicalizes** rich dotted names to the bare catalog key (cross-schema collision-guarded) and records the schema, so columns/joins attach and SQL re-qualifies at build time.
3. LIMIT defaults to a bounded `1000` (blank/0 stays an explicit opt-out); `tableSchemas` added to the auto-SQL dependency path.

**Key files.** `web/components/QueryBuilder.tsx`.

---

## 96. Query Builder — Saved Queries (Persistence) ✅ Shipped

### What
The builder was a dead-end — build, run, lose it on reload. Now **connection-scoped saved queries** persist both the SQL *and* the full visual spec (primary table, joins, dimensions, measures, filters, time, HAVING, order/limit), so loading one restores the **builder**, not just a SQL dump. A header "Saved" dropdown lists/loads/deletes; "Save" creates (with a suggested name) or updates in place.

### Why
Turns a scratchpad into a workflow loop — the foundation every other improvement compounds on.

### How
SQLite store mirroring the Canvas pattern (`aughor/savedquery/{models,store}.py`, idempotent schema, newest-first list, partial updates; `spec` is opaque JSON owned by the frontend), REST CRUD on `query.py`, `api.ts` client, and the header UI. Runtime-proven: save → reload → load restores table+dims+measures+SQL → runs; in-place update doesn't duplicate.

**Key files.** `aughor/savedquery/`, `aughor/routers/query.py`, `web/lib/api.ts`, `web/components/QueryBuilder.tsx`, `tests/unit/test_saved_query_store.py`.

---

## 97. Query Builder — First-Class Time Range & Grain ✅ Shipped

### What
Time — the most-used control in real BI — is now first-class instead of a buried per-dimension dropdown: a date-column picker, **relative presets** (Last 7/30/90 days, This/Last month, This quarter, This year, Year-to-date) plus a **custom from/to** range compiling to `WHERE`, and a **time-grain** selector (hour…year) compiling to a leading `DATE_TRUNC` dimension + `GROUP BY`.

### Why
You couldn't scope a query to "last 30 days" or roll up by month without hand-editing SQL.

### How
A pure `timePredicate()` (DuckDB/ANSI `INTERVAL`) + a `TimeSpec` threaded into `buildSql`; time state persists in the saved-query spec. Proven: `This year` → 5 rows; custom range compiles correctly.

**Key files.** `web/components/QueryBuilder.tsx`.

---

## 98. Query Builder — Grain-Misuse Warnings on Metric Chips ✅ Shipped

### What
The measure-additivity (grain) layer now surfaces **directly on the metric chips**: sum a per-unit price without `× quantity` (under-count) or a per-line total `× quantity` (double-count) and the chip lights amber with a ⚠ explanation and a **one-click fix**. The differentiated trust feature no generic BI tool has.

### Why
A wrong number should be flagged the moment it's built — at authoring time, on the surface where people build queries — not just inside an investigation.

### How
New `GET /connections/{id}/measure-grains` (ontology-stamped grains first, else a cached live probe; `cached_connection_grains()` makes hits ~16ms vs ~19s cold; close via kernel `tolerate()`), reusing `aughor/semantic/measure_grain.py`. Frontend `grainWarning()` mirrors `measure_grain_misuse` at the chip level; "fix" rewrites `SUM(col)` → `SUM(col × quantity)`. Runtime-proven: the suggester's own `SUM final_price_usd` flags → fix → **$503.30M (the correct revenue), not the $252M undercount**.

**Key files.** `aughor/routers/query.py`, `aughor/semantic/measure_grain.py`, `web/lib/api.ts`, `web/components/QueryBuilder.tsx`.

---

## 99. Query Builder — HAVING, Distinct-Value Picker & CSV Export ✅ Shipped

### What
Closes the "real BI tool" checklist: **HAVING** (filter on an aggregated metric → `HAVING <expr> <op> <val>`), a **distinct-value filter picker** (a column's distinct values offered as a datalist, formatted as valid SQL literals — quoted for text columns), and client-side **CSV export** of results.

### Why
You couldn't filter on a `SUM`, had to hand-type (and correctly quote) filter values, and couldn't export.

### How
HAVING items compile from their referenced measure's expression and persist in the spec; `GET /connections/{id}/distinct` backs the picker (`_quote_ident` mirrors the frontend per-segment quoting; close via `tolerate()`); CSV is RFC-4180-escaped in the browser. Proven: `WHERE traffic_source='Organic'` (picked) + `GROUP BY` + `HAVING SUM > 1e6` compose & run; CSV captured.

**Key files.** `aughor/routers/query.py`, `web/lib/api.ts`, `web/components/QueryBuilder.tsx`.

---

## 100. Query Builder — Real SQL Editor (Highlighting + Format) ✅ Shipped

### What
The plain monospace textarea becomes a real editor: **syntax highlighting** (keywords/functions/strings/numbers/comments/identifiers) and a **Format** button — with **no new dependency**.

### Why
A SQL surface should look and behave like one; pasted/hand-written SQL deserves one-click cleanup.

### How
A small SQL **tokenizer** (strings & quoted identifiers tokenized first) is shared by the highlighter (a transparent-`<textarea>`-over-highlighted-`<pre>` overlay, scroll-synced) and the formatter (uppercases **only** keyword/function tokens and newlines major clauses — strings/identifiers untouched, so the result is semantically identical). The theme's unlayered global `<textarea>` rules were beating Tailwind classes and drifting the caret; fixed by driving every metric inline on both elements. Proven: metrics match, no doubled text, live highlight, autocomplete intact, Format keeps `'Organic'` and `"analytics"."order_items"` literal.

**Key files.** `web/components/QueryBuilder.tsx`.

---

## 101. Query Builder — Explore Layout (chart hero + Data/Customize panel) ✅ Shipped

### What
The builder was reorganised into an Apache Superset–style Explore surface, then refined per use to a
**vertical** layout: the chart is the **hero on top**, and a **DATA / CUSTOMIZE** control panel docks
at the **bottom** — draggable to resize and a chevron to **fully collapse** (chart takes the whole
height). The catalog field list stays on the left.

### Why
The old builder was a long single scroll with the chart buried under the controls. Leading with the
chart and tucking the controls into a tabbed, collapsible panel makes the result the focus and the
authoring controls a deliberate, organised space.

### How
A `flex-col` right pane with CSS `order` (chart `order-1`, divider `order-2`, panel `order-3`); the
panel has a resizable height (drag the divider) and a collapse toggle. All existing controls (chart
type, time, dimensions, metrics, filters, HAVING, sort, limit, SQL) live in the DATA tab.

**Key files.** `web/components/QueryBuilder.tsx`.

---

## 102. Query Builder — Chart Type Gallery + Customize Tab ✅ Shipped

### What
A **Chart Type** gallery (Auto + the inferred-shape's available types) and a **CUSTOMIZE** tab that
styles the chart: title, data labels, **color scheme**, **number format**, **legend position**, and
**X/Y axis titles**.

### Why
Charts were inferred-only with no styling — the biggest gap vs. a real BI explore view.

### How
`InvestigationChart` gained a backward-compatible controlled mode (type / labels / title) so the rail
owns them; the shared `<Chart>` engine gained an optional `custom` prop applied as a generic
post-pass over the built Vega-Lite spec (`applyCustom` walks single + layered specs to set axis
format/title, color-scale scheme, legend orient). A null custom is a no-op, so chat / reports /
explorer charts are unaffected. All chart config persists in the saved-query spec.

### Tech / libraries
- Vega-Lite (the spec post-pass), the shared `Chart` engine + `chartTypeInference`.

**Key files.** `web/components/{QueryBuilder,InvestigationChart,Chart}.tsx`, `web/components/charts/chartTypeInference.ts`.

---

## 103. Query Builder — Compact DATA Tab, Folded Time, Catalog Tree & Canvas-Nav Fix ✅ Shipped

### What
Polish pass making the rail compact and fixing real defects: removed the Suggested + standalone Time
sections; **folded the relative time range onto the date-dimension chip** (grain + range inline);
single-line drop zones that grow with content; SQL and Resolved-Joins collapse by default; tightened
spacing; **indented catalog columns** under their table (connection→schema→table→column tree); fixed
dimension chips overflowing their box; gave the chart the full width (no x-axis clipping); and **fixed
Start Canvas** — it navigated via `window.location.href="/?canvas=id"` (never read → landed on Home),
now routed through the app's canvas handler with create-then-navigate (LLM name upgraded in background).

### Why
The control rail was tall and redundant, the catalog hierarchy was ambiguous, and Start Canvas was
broken (silently went to Home).

**Key files.** `web/components/QueryBuilder.tsx`, `web/app/page.tsx`.

---

## 104. Chart Engine — Nice Y-Axis Headroom ✅ Shipped

### What
A `withYHeadroom()` post-pass over every built Vega-Lite spec sets the quantitative Y-axis
`domainMax` to a *nice* value ~5% above the data peak (a 9.9M peak → an 11M ceiling) so the series
no longer kisses the top frame. Skips axes that already pin a domain (combo/pareto), stacked axes
(segment max ≠ stack total) and non-positive/diverging data. Y-only by design — horizontal bars
already pad their measure axis.

### Why
The axis pinned its max to the data peak, so a line/area touched the top gridline with no breathing
room and no sense of range. Applies to **every** `<Chart>` surface (chat / reports / explorer / builder).

**Key files.** `web/components/Chart.tsx`.

---

## 105. Query Builder — One Display Dropdown + Full Chart-Type Set ✅ Shipped

### What
Folds the chart-type gallery **and** the Chart/Table toggle into a single **Display** dropdown in the
DATA tab (Chart group + Data group), with **Table** as an option alongside the chart types. A new
`availableChartTypes(columns, rows)` keys off the column classification and offers the full set the
data shape can actually render — line, area, bar, **combo, pie, heatmap, treemap, scatter, stacked** —
never a type that would render blank. A stale pick is clamped to Auto when the result shape changes.

### Why
Two separate controls for "how to show the result" was redundant, and the old swap-list under-offered
(a line only offered line/bar). One home, more types.

**Key files.** `web/components/QueryBuilder.tsx`, `web/components/charts/chartTypeInference.ts`.

---

## 106. Chart Engine — Customize Knobs Actually Apply + No Label Overlap ✅ Shipped

### What
Fixed a silent no-op: `applyCustom` looped `spec.layer ?? [spec]`, but the engine's single-line and
bar specs keep x/y at the **shared top-level encoding** — so number-format and axis-titles never
reached an axis. Rewrote it over a `forEachEncoding` walker that visits the top-level encoding *and*
nested layers; number format now lands on whichever positional axis is the measure (x for horizontal
bars), and color scheme is guarded to categorical channels (can't corrupt a heatmap's scale). Data
labels: skip specs that already self-label (bars), label each measure once (kills the area+line
double-stamp), and thin dense line/area series to ~10 labels so a 13/50-point trend reads.

### Why
"Customize" looked broken on the most common chart, and toggling data labels smeared overlapping
numbers across the line.

**Key files.** `web/components/Chart.tsx`, `web/components/VegaChart.tsx`.

---

## 107. Query Builder — Pivot Display Mode ✅ Shipped

### What
A **Pivot** option in the Display dropdown renders a client-side cross-tab of the already-fetched
rows (no round-trip): pick Rows, an optional Columns field, a Values field and an aggregation
(SUM/COUNT/AVG/MIN/MAX), with row/column/grand totals. Every aggregate — including the totals — is
computed from the underlying rows, so an AVG total is a true mean, not an average of cell averages.

### Why
A pivot is table-stakes for ad-hoc analysis; doing it client-side keeps it instant.

**Key files.** `web/components/PivotTable.tsx`, `web/components/QueryBuilder.tsx`.

---

## 108. Query Builder — Open in Query Builder (from Insights + Deep Analysis) ✅ Shipped

### What
An **Open in Query Builder** action on Insight cards (`DomainIntelPanel`) and Deep Analysis findings
(`InvestigationReport`). It hands the generated query off to the builder, which loads the SQL into the
manual editor, switches to its connection, and runs it — so the grain (`DATE_TRUNC`), aggregation,
`GROUP BY` and `HAVING` all ride along inside the SQL and the result renders as a chart/table you can
re-chart, customize, pivot, and export. Wired through a small app-wide `OpenInBuilderProvider` context
rather than prop-drilling through every layer; the builder shows an "imported query · edit SQL below"
chip in place of the onboarding prompt.

### Why
Closes the loop the other way: intelligence surfaces produced a query, but you couldn't keep working
with it. (Carries the SQL faithfully; does not yet reverse-compile it back into dimension/metric chips.)

**Key files.** `web/lib/openInBuilder.tsx`, `web/components/QueryBuilder.tsx`, `web/app/page.tsx`, `web/components/DomainIntelPanel.tsx`, `web/components/InvestigationReport.tsx`.

---

## 109. Chart/Table — Sub-Day Grain on the Axis + Clean Date Cells ✅ Shipped

### What
Two grain-display fixes: (1) the `Gran` type only ran day→year, so a `DATE_TRUNC('minute')` column
was misread as "day" and the axis dropped the time — picking Minute looked identical to Day. Now
`minute`/`hour` are detected from the time-of-day component (before the spacing heuristic, so sparse
minute data isn't misread) and the axis formats `%b %d %H:%M`. (2) Tables showed the raw
`2025-04-01 00:00:00` for a quarter/month/day grain — a new `displayCellValue()` collapses a midnight
timestamp to its date, wired into `AugTable` cells and the pivot headers.

### Why
A selected grain that doesn't change what you see is a broken control; and the trailing `00:00:00` was
noise in every grain-truncated table.

**Key files.** `web/lib/format.ts`, `web/components/AugTable.tsx`, `web/components/PivotTable.tsx`, `web/components/brief/Sparkline.tsx`.

---

## 110. Query Builder — Dimensions + Metrics Side by Side, Taller Chart ✅ Shipped

### What
The DATA-tab Dimensions and Metrics drop zones move from stacked to **side by side**, and the default
control-panel height drops (360 → 300) so the **chart hero is taller** by default (still drag-resizable).

### Why
Better use of the wide control rail and more room for the chart, which is the point of an Explore layout.

**Key files.** `web/components/QueryBuilder.tsx`.

---

## 111. Time-to-First-Insight — Instrumented KPI + Progressive Exploration ✅ Shipped (T2)

### What
The connect→first-insight funnel is now a **measured product KPI** instead of an all-or-nothing wait. The
explorer stamps a `first_insight_at` milestone on the **first** insight of a run (from any phase), emits an
`exploration.first_insight` event carrying elapsed seconds, surfaces `first_insight_seconds` on the
exploration status, and exposes an aggregate endpoint `GET /exploration/kpi/time-to-first-insight`
(p50/p90/min/max). The Exploration panel shows "⏱ first insight in 47s".

### Why
"Today exploration is all-or-nothing for 8–15 min" (B-6). You can't optimize what you can't measure —
this makes the funnel queryable and holds the product to it, like the metric-enforcement rate.

### How
A single `_emit_insight()` seam now handles **both** Phase 7 (cross-table) and Phase 8 (domain-intel)
findings. Previously Phase 7 insights bumped counters but emitted **no** live event and wrote **no**
Trust-Receipt artifact — so the *earliest* findings never surfaced live (only on the 60s fallback poll or
at completion). Routing both phases through one seam fixes that built-not-wired gap and stamps the TTFI
milestone once (idempotent across restart/resume).

**Key files.** `aughor/explorer/agent.py` (`_emit_insight`, `_record_first_insight`),
`aughor/explorer/models.py` (`first_insight_at`, `elapsed_seconds`), `aughor/routers/exploration.py`
(KPI endpoint), `web/components/ExplorationPanel.tsx`.

---

## 112. Investigations on the Kernel Event Spine + Boot Reconciliation ✅ Shipped (T3)

### What
Investigation lifecycle transitions now journal `investigation.created / completed / failed / paused`
events onto the kernel event spine (the same journal the explorer uses), so any surface sees a run
start/finish/fail live. The investigation **History panel** refreshes live off these events. On boot, every
orphaned `running` row (left by a prior crash/restart) is **reconciled immediately** — failed + journaled —
instead of lingering until the periodic 60-min supervisor sweep; the periodic sweep now journals per-row too.

### Why
Investigations were invisible to the kernel (only the explorer emitted), and a crashed run showed as
"running" long after the server that owned it was gone. T3 closes the "every substrate serves one consumer"
gap for investigations.

A real bug surfaced while proving this end-to-end: a **client disconnect** makes Starlette cancel the SSE
coroutine with `asyncio.CancelledError` — a `BaseException` that bypasses every `except Exception`
salvage/fail handler, so the investigation orphaned in `running` with no terminal event. Fixed with an
**orphan-reconcile in `finally`** (both `_stream_investigation` and `_stream_resume`): any row still
`running` is failed there, journaling the transition. Verified live (disconnect → `failed` +
`investigation.failed` in ~12s).

### How
Events are emitted at the **single point** every transition flows through — the `history.db` lifecycle
functions (`create/complete/fail/pause_investigation`, `reconcile_orphaned_investigations`,
`sweep_stale_running`) — so all callers (including resume + future ones) journal automatically.

**Key files.** `aughor/db/history.py` (`_emit_lifecycle`, `reconcile_orphaned_investigations`),
`aughor/api.py` (boot reconciliation), `aughor/routers/investigations.py` (`finally` orphan-reconcile),
`web/components/HistoryPanel.tsx`.

---

## 113. Monitors & Briefs on the Event Spine ✅ Shipped (T3)

### What
A fired monitor alert emits `monitor.alert` and a delivered brief emits `brief.delivered` onto the kernel
journal — the scheduled subsystems are now observable (including delivery failures) on the same spine the
explorer uses, rather than living only in their own stores.

**Key files.** `aughor/monitors/store.py` (`append_alert`), `aughor/briefs/delivery.py`
(`deliver_subscription`).

---

## 114. AVG-over-Chasm Fan-out Linter + Wider Wiring Contract ✅ Shipped (T6)

### What
Two correctness/hygiene closes. **(1)** A new high-precision linter `avg_over_chasm_fanout` drops a Phase-8
finding when an `AVG(x)` is computed over a **chasm** join (≥2 satellites of one hub) — the mean is silently
**biased** by the cross-product (each value weighted by the other satellite's fan-out). It mirrors the proven
`count_star_chasm_fanout` and correctly leaves MIN/MAX (unaffected by duplication) and windowed/DISTINCT/
pre-aggregated-CTE forms alone. **(2)** The K4 wiring contract now scans `web/components` (not just
`web/lib`) and matches the `${BASE_API}` alias — closing the blank-canvas-class hole where a component fetch
to a removed route went uncaught.

**Key files.** `aughor/sql/fanout.py` (`avg_over_chasm_fanout`, shared `_chasm_roots`),
`aughor/explorer/agent.py` (drop chain), `tests/integration/test_api_contract.py`.

---

## 115. Investigations as First-Class Kernel Jobs ✅ Shipped (T3)

### What
A live investigation now runs as a **supervised kernel job**, the same as the explorer: a `job.state`
PENDING→RUNNING→SUCCEEDED|FAILED|CANCELLED lifecycle on the event spine, a heartbeat (orphan detection), and
its artifacts auto-stamped with `created_by_job`. A new `POST /investigations/{inv_id}/cancel` cancels an
in-flight run via the kernel (job → CANCELLED, the row reconciled to failed).

### Why
Investigations were the last major long-running operation outside the kernel — reconciled only by
side-channels. Making them jobs gives unified status, heartbeats, kernel-driven cancel, and artifact lineage.

### How
`_stream_investigation` is left **completely unchanged**; a thin wrapper (`_investigation_job_streamed`) runs
it inside the job's task and bridges its SSE events to the client over an in-process queue (latency unchanged,
zero risk to the 360-line streaming path). Verified live: job PENDING→RUNNING→SUCCEEDED with the report still
streamed; in-flight cancel → CANCELLED + reconcile.

**Key files.** `aughor/routers/investigations.py` (`_investigation_job_streamed`, cancel route).

---

## 116. Investigation Crash-Recovery (Boot Salvage) ✅ Shipped (T3)

### What
After a hard crash, an investigation orphaned mid-run is **recovered, not just failed**: on boot a supervised
salvage job reads its LangGraph checkpoint (persistent `SqliteSaver`, keyed by inv_id) and runs the proven
`_try_salvage` to synthesize a **partial report** from the evidence (ADA phases / explore answers) gathered
before the crash — marking it `complete` (flagged `_partial`) where possible, failing it only when there is
nothing to recover.

### Why
"crash-RESUME vs sweep-to-failed" — don't throw away minutes of gathered investigation work because the
process died. Reuses the battle-tested salvage path rather than a risky full graph re-run.

### How
`_recover_orphaned_investigations` runs inside `_kernel_boot_recovery` (AFTER the kernel's job sweep, so the
salvage jobs aren't swept themselves) and submits one salvage job per orphaned `running` row. **Verified with
a kill -9 chaos test**: a hard-killed mid-ADA investigation came back `complete` with a real partial headline.

**Key files.** `aughor/routers/investigations.py` (`salvage_orphaned_investigation`), `aughor/api.py`
(`_recover_orphaned_investigations`), `aughor/db/history.py` (`list_orphaned_running_investigations`).

---

## 117. Shared SQL-Analysis Facade (`analyze()`) ✅ Shipped

### What
One place — `aughor/sql/analyze.py` `analyze(sql) -> SqlFacts` — that parses SQL once (sqlglot) and exposes
the reusable semantic facts: tables (CTEs excluded), columns, aggregates (func / arg / distinct / windowed),
GROUP BY, and the `product_of_aggregates` predicate. Pure static analysis; never raises (unparseable →
`ok=False`, empty facts).

### Why
sqlglot was already load-bearing (fanout / lint / measure_grain parse the AST), yet several trust-critical
checks still **string-munged** the SQL, each fragile in its own way. The facade lets them share one rigorous
extraction. The headline fix: the ontology validator's product-of-aggregates detector was a regex
(`AGG(...)\s*\*\s*AGG(`) that **silently missed any nested-paren argument** — e.g.
`SUM(COALESCE(price,0)) * SUM(quantity)` slipped through as *verified*, injecting a $3T-class formula into the
NL2SQL prompt with authority. The AST predicate catches it (a multiply whose **both** operands contain an
aggregate, and which is not itself inside one — so `SUM(a*b)` stays correct).

### How (first two consumers retargeted)
- `ontology/validator.py` — product-of-aggregates regex → `analyze().product_of_aggregates`. **Runtime-proven**:
  the nested case is now demoted to unverified on the real `validate_semantics` path.
- `investigations._extract_tables` — regex → `analyze().tables` (AST-correct on aliases/subqueries), with a
  regex fallback for the multi-statement blobs some call sites pass.

Remaining string holdouts (`sql_consistency`, `lint` NOT-IN, `measure_grain` dedup) are follow-ups; the
chips reverse-compile (Layer 3) stays out of scope by design.

**Key files.** `aughor/sql/analyze.py`, `aughor/ontology/validator.py`, `aughor/routers/investigations.py`.

---

## 118. BeautyCommerce Demo Workspace Seed ✅ Shipped

### What
`python -m aughor.samples.beautycommerce` (idempotent) builds a complete, lived-in demo: a registered `BeautyCommerce` DuckDB connection over a 6-table beauty/cosmetics dataset (products 120 / customers 600 / campaigns 12 / orders 6k / order_items 15k / reviews 3.5k — FKs consistent, 0 orphans), 5 governed `beauty_*` metrics, a Canvas with insights + a deep-analysis report, 4 saved Query-Builder entries, and a Slack trigger (disabled).

### How
Built on the existing create-fns (`add_connection`, `save_metric`, `create_canvas`/`create_artifact`, `create_saved_query`, `save_trigger`); metrics namespaced `beauty_*` so they don't clobber the global store; item prices derived from the product via a join so category-revenue insights are real. Data is runtime (gitignored).

**Key files.** `aughor/samples/beautycommerce.py`, `tests/unit/test_beautycommerce_seed.py`. (#25)

---

## 119. Onboarding First-Run Funnel ✅ Shipped

### What
A "Welcome — get started in three steps" panel atop Home (`HomeScreen`) while the user has no investigations: (1) Connect data → the AddConnection modal; (2) Explore the demo → drops into the seeded BeautyCommerce workspace; (3) Ask a question → chat. Auto-hides once history exists. Composes with the seed (#118).

**Key files.** `web/app/page.tsx` (`HomeScreen`). (#26)

---

## 120. Briefing Live Dashboard ✅ Shipped

### What
The Briefing tab renders a live chart + KPI dashboard above the prose: it runs each top finding's own `.sql` through the Query-Builder authority (`runDirectQuery` → `/query/run`, matcache-backed) and renders with the deployed Vega stack — single-series trend/scalar → a KPI tile (value + Sparkline + Δ), categorical/multi-series → an auto-typed chart figure, non-chartable/errored → dropped (fail-safe). Each figure keeps `FindingActions`. **Zero backend change.**

### How
`BriefingDashboard` reads the panel's selected findings and classifies with `charts/chartTypeInference.ts`. Live-path bug fixed: a `lastKey` ref guard defeated React StrictMode's double-invoke → all results discarded; removed (the `[runKey]` dep gates re-runs).

**Key files.** `web/components/brief/BriefingDashboard.tsx`. (#28)

---

## 121. PDF / PowerPoint Report Export ✅ Shipped

### What
Download any **Insight** (chat answer) or **Deep-Analysis** report as a polished PDF or PowerPoint. `GET /investigations/{id}/export?format=pdf|pptx[&narrate=true]` (`narrate` = a best-effort LLM executive summary). Buttons in the saved-report header (`HistoryDetailPanel`) and on every chat response (`ChatMessage`).

### How
`aughor/export/`: parse `report_json` → a format-agnostic `ExportDoc` (typed blocks) → PDF (reportlab) / PPTX (python-pptx). Charts render server-side with **matplotlib** (Agg, headless) honouring the stored `chart_type` — no client inference, no browser; non-chartable → table fallback; a render failure never breaks the doc. `**markdown bold**` → real bold in both. New deps: reportlab, python-pptx, matplotlib.

**Key files.** `aughor/export/{charts,document,pdf,slides}.py`, `web/components/ExportButton.tsx`, `tests/unit/test_export.py`. (#30, #31)

---

## 122. Runtime LLM Provider Switching ✅ Shipped

### What
Choose & change the inference backend / models / API keys **at runtime** — no `.env` edit, no restart. Settings → Inference: provider dropdown (Ollama / LM Studio / Groq / Together / Anthropic), per-role models, base URLs, write-only API keys, a **Test connection** button (a real tiny completion).

### How
`provider.py` gained a config layer (precedence: `data/llm_config.json` → env → default); `get_provider(role)` is unchanged for its **34 callers** but rebuilds its cache on a config version bump (model AND backend changes take effect). Keys secretvault-encrypted; `current_config()` is secret-free (set/not-set). `GET/POST /llm/config` + `POST /llm/config/test`.

**Key files.** `aughor/llm/provider.py`, `aughor/routers/llm.py`, `web/components/InferencePanel.tsx`, `tests/unit/test_llm_config.py`. (#33)

---

## 123. Workspace Data-Path Tenancy Isolation ✅ Shipped

### What
A workspace now actually scopes what you see. Every connection-tied surface is filtered to the active workspace's connections: the connection pickers (Briefing/Hub/Domains, Semantic Layer, Query Builder), `/canvases`, `/investigations` (Recents), the Recommendation Inbox, and the Catalog tree. An **empty workspace shows none of another's data**.

### Why
The `Workspace` model owned `connection_ids` and promised scoping but enforced it nowhere — an empty workspace leaked another's data (reported bug). Even the UI-scoped surfaces only filtered the picker; the backend was global.

### How
One fail-closed gate — `workspace_connection_ids(workspace_id)`: `None` when unscoped (management flows stay global), the workspace's ids when known, an **EMPTY set for an unknown workspace**. Applied server-side to `/canvases`, `/investigations`, `/catalog/tree`; the frontend passes the active workspace + refetches on switch, and the pickers use `wsConnections`. **Both layers — real isolation, not UI-only.** Shared resources (metrics catalog, action triggers, org-intelligence) are global by design. Remaining for full tenancy: connection-registry ownership + platform auth/RBAC (#12).

**Key files.** `aughor/workspace/store.py`, `aughor/routers/{canvas,investigations,catalog}.py`, `web/app/page.tsx`, `web/components/{CanvasBrowser,RecommendationInbox,CatalogScreen,QueryBuilder}.tsx`. (#38, #39, #41, #42)

---

## 124. Workspace Tenancy — Monitors/Alerts + Home-Dashboard Flash ✅ Shipped

### What
The last two surfaces that still leaked across workspaces are closed. Opening **Monitors** in an empty workspace no longer lists every workspace's monitors/alerts, and the **Home dashboard** no longer briefly flashes another connection's tables/queries/insights on first load.

### Why
Two residual leaks of the same class as the original tenancy bug: `MonitorsPanel` fired `GET /monitors` + `/alerts` with no filter when no connection was selected (→ all workspaces), and `selectedConn` was restored from `localStorage` before the workspace boundary resolved (→ the Home stats fetched the builtin connection for a beat, then self-corrected).

### How
`/monitors` + `/alerts` now accept `?workspace_id=` and apply the same fail-closed `workspace_connection_ids` gate; the panel passes the active workspace. And `selectedConn` is now **derived** and clamped to the active workspace (fail-closed until it resolves) instead of stored-then-corrected — fixing the whole class of connection-scoped consumers at once. A 6-test regression guard locks the gate.

**Key files.** `aughor/routers/monitors.py`, `web/components/MonitorsPanel.tsx`, `web/app/page.tsx`, `web/lib/api.ts`, `tests/unit/test_monitor_workspace_scope.py`. (#45)

---

## 125. Licensing Extension + 402 → Upsell ✅ Shipped

### What
The capability gate now covers the platform's expensive/autonomous surfaces, and a locked capability raises a real **upgrade modal** instead of a silent error.

### Why
`gate()` was wired only on actions/briefs/metrics/monitors; the core autonomous + edit surfaces (investigations, exploration, ontology, semantic) had zero gates, and the frontend had no `402` handling at all.

### How
25 gates added across investigations / exploration / ontology / semantic (mutations only — reads/deletes stay open), each mapping to the right capability (`DEEP_ANALYSIS`, `AUTO_EXPLORATION`, `ONTOLOGY_EDIT`, `SEMANTIC_EDIT`, …). A one-time `window.fetch` interceptor screens every response for `402 capability_locked` and raises an app-wide `UpgradeModal` — covering all current *and future* gates with no change to the ~100 API call sites. Verified live: free tier → 402; default enterprise tier → transparent.

**Key files.** `aughor/routers/{investigations,exploration,ontology,semantic}.py`, `web/lib/upsell.ts`, `web/components/UpgradeModal.tsx`, `tests/integration/test_licensing_enforcement.py`. (#46)

---

## 126. Model-Cascade Core (Adaptive Inference) — ⊘ Built (#49), then Removed

> **Tombstone, kept as record.** The cascade was built and merged (#49), then **removed from the
> codebase entirely** (2026-06-15) as not worth its weight. The entry stays so the idea isn't
> re-attempted blindly.

### What it was
Infrastructure for cost-bounded LLM inference with an accuracy guarantee: a cheap proxy model answers the easy cases and only the ambiguous ones escalate to the expensive "oracle," with a *proven* recall/precision bound (`aughor/llm/cascade.py` — Hoeffding threshold learner), plus `get_proxy_provider` and an opt-in cascade on hypothesis scoring (`AUGHOR_CASCADE_HYPOTHESIS`, fail-safe to the oracle).

### Why it was removed
Every accessible *cheap* proxy proved **miscalibrated** — self-reported confidence clusters at 0.6–0.8 regardless of the evidence — so the cascade had to escalate ~85% of the time, yielding only a **~15% best-case call saving**, and only if a cheap+calibrated model existed (none does on any reachable backend; the well-calibrated ones are slow/costly, the cheap+calibrated candidate is access-gated). A ~15% contingent saving isn't worth a permanent second provider, an env flag, a thresholds file, and a calibration harness in the live agent path. **The accuracy guarantee always held (recall 1.0)** — the math was never the problem, the available models were. The ~150-line core is trivially reconstructable from git (#49) + the plan doc's Part VII if a cheap+calibrated proxy ever lands. Calibration harness (PR #50) closed unmerged. Plan + full post-mortem: [`docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md`](docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md) Part VII.

---

## 127. Semantic Operators over SQL — Phase 1 (filter + extract) ✅ Shipped

### What
LLM operators that run over the **text** columns of a SQL result set — the unstructured residue SQL can't reason over (support tickets, reviews, notes, incident write-ups). Phase 1 ships two operators: **`filter`** (keep rows whose text satisfies a natural-language predicate) and **`extract`** (pull named structured fields out of free text into new columns).

### Why
SQL handles the structured 99% — filtering, aggregation, joins — but can't answer "which of these tickets describe a billing problem?" or "pull the root-cause and component out of each incident note." Semantic operators fill that gap **without** giving up grounding or efficiency: the warehouse does the push-down first, and the LLM only ever touches the small text residue.

### How
`aughor/semops/operators.py` implements the operators as pure `QueryResult → SemanticOpResult` functions. Rows arrive stringified with no dtypes, so text columns are detected from the **values** (`detect_text_columns` — mostly non-numeric, non-date, non-id). **Cost is bounded by push-down + an explicit per-operator row cap** (default 200; refuses above it with a surfaced message pushing the caller to add SQL `WHERE`/`LIMIT`, never a silent truncation) and by batching rows per LLM call (role `fast`). Every operator is **fail-open**: an LLM/parse failure keeps the row (filter) or leaves fields blank (extract) and is recorded in `notes` — it never raises into the query path. `POST /query/semantic` and `POST /query/semantic/text-columns` re-run the SQL server-side (authoritative — never trusts client-sent rows), then apply the operator; both gated by the new Pro **`SEMANTIC_OPERATORS`** capability.

**Key files.** `aughor/semops/operators.py`, `aughor/semops/__init__.py`, `aughor/routers/query.py`, `aughor/licensing/capabilities.py`, `tests/unit/test_semops.py`, `tests/integration/test_query_semantic.py`. Plan: [`docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md`](docs/ADAPTIVE_INFERENCE_AND_SEMANTIC_OPERATORS.md) §4. **Next (Phase 2):** `top_k` + `aggregate`, the Query Builder "semantic step" UI.

---

## 128. Semantic Operators in the ADA Investigation Agent ✅ Shipped

### What
The autonomous ADA investigation can now reason over **text** columns mid-investigation. Any ADA phase-plan query may carry an opt-in **semantic step** (`filter`/`extract`); after the SQL runs, the operator transforms that query's result so the phase interpreter reasons over text-derived evidence — e.g. filter support tickets to the ones describing a billing problem, then let the phase narrate over those.

### Why
Phase 1 made semantic operators callable over a SQL result; this puts them on the agent's real path. ADA investigations could measure the structured signal but were blind to the free-text columns (tickets, reviews, notes) that often explain *why* a metric moved. Now a phase can pull that explanation into evidence.

### How
`PhaseQueryPlan` gains an optional `semantic: SemanticStep` field; its own description teaches the planner when to attach one (free-text columns only) — **no phase-prompt edits**, the instructor schema surfaces it. Applied at the single shared seam `run_analysis_phase` (so **every** phase — baseline/decompose/dimensional/behavioral — gets it at once) via `_apply_semantic_steps`, right after parallel execution and before interpretation. The integration is **opt-in** (a no-op unless the planner emits a step), **guarded** (`detect_text_columns` skips a step misattached to a numeric/missing column, so it can never corrupt structured evidence), and **fail-open** (any operator error leaves the raw result via `tolerate(...)`). Reuses Phase 1's operators through a shared `apply_step` dispatcher.

**Key files.** `aughor/agent/prompts_investigate.py` (`SemanticStep`/`SemanticField`/`PhaseQueryPlan.semantic`), `aughor/agent/investigate.py` (`_apply_semantic_steps` + the `run_analysis_phase` wiring), `aughor/semops/operators.py` (`apply_step`), `tests/unit/test_ada_semantic_steps.py`.

---

## 129. Semantic Operators — `top_k` + `aggregate` (the four-operator set) ✅ Shipped

### What
The two operators that complete the semantic set, over a result's free-**text** column: **`top_k`** (rank rows by a natural-language criterion and keep the best *k* — e.g. the 5 most severe incident notes) and **`aggregate`** (synthesize many text rows into ONE answer — e.g. summarize the recurring complaint themes into a single row).

### Why
`filter`/`extract` reshape a result row-by-row; `top_k` and `aggregate` are the *reducing* operators — rank-and-cut, and many-rows-to-one. Together the four cover the LLM analogues of `ORDER BY … LIMIT` and `GROUP BY`-style synthesis over text that SQL can't express.

### How
`semantic_top_k` scores every row in [0,1] (batched), then stable-sorts by score and keeps the top *k*; a failed batch scores rows **neutral** (0.5) so nothing is unfairly buried — fail-open. `semantic_aggregate` makes one synthesis call over the (capped) text values and returns a **1-row** result in an `answer` column; on failure it leaves the raw result untouched. Both honor the same push-down + row-cap discipline. They're wired everywhere `filter`/`extract` already were — the shared `apply_step` dispatcher, `POST /query/semantic` (with `criterion`/`k` and `instruction`/`out_column` params), and the ADA `SemanticStep` — so the agent gains them too.

**Key files.** `aughor/semops/operators.py` (`semantic_top_k`, `semantic_aggregate`, `apply_step`), `aughor/routers/query.py`, `aughor/agent/prompts_investigate.py` (`SemanticStep`), `tests/unit/test_semops.py`, `tests/integration/test_query_semantic.py`, `tests/unit/test_ada_semantic_steps.py`.

---

## 130. Query Builder "Semantic step" UI ✅ Shipped

### What
The user-facing surface for semantic operators: a collapsible **"Semantic step"** panel under any Query Builder result. Pick an operator (filter / extract / top-k / aggregate), pick a text column, fill the operator's params, and **Apply** — the result table transforms in place, with the operator's notes surfaced and a one-click **Revert**.

### Why
The semantic operators were reachable by API and by the ADA agent (#127–#129) but not by a person in the product. This closes the loop: the analyst running ad-hoc SQL can now reason over the free-text columns (reviews, tickets, notes) right where the result lands — the *visible* leverage proof of the whole borrow.

### How
`ResultsPane` holds a local `semResult` overlay (`view = semResult ?? result`) so applying an operator swaps the displayed table while the base result stays available to revert; a new query resets it. **Text columns are detected client-side** (`detectTextColumnsLocal`, mirroring the backend heuristic) from the already-fetched rows — no extra round-trip — and the column picker defaults to the first text column, flagging others "(not text?)". `runSemanticOp` calls `POST /query/semantic`; the panel shows `input → output rows · N calls`, the surfaced `notes` (incl. a refuse-over-cap message), and any error. Licensing 402s are caught by the global upsell interceptor. **Verified end-to-end in the browser** on real review data: an 8-row result filtered to 6 "positive" reviews in one LLM call, then reverted.

**Key files.** `web/components/QueryBuilder.tsx` (`SemanticStepPanel`, `ResultsPane` overlay, `detectTextColumnsLocal`), `web/lib/api.ts` (`runSemanticOp`, `SemanticOpRequest`, `SemanticOpResult`). Completes **Borrow 3** (semantic operators over SQL) — both the user and agent surfaces are now wired.

---

## 131. Hierarchical tree-reduce synthesis (Borrow 4) ✅ Shipped

### What
A reusable map-reduce-over-context-windows primitive for synthesizing from **many** items, wired into the Briefing so the executive narrative reflects *every* finding — not just the cited top-8.

### Why
Briefing synthesis was single-prompt: `generate_narrative` hard-capped at the top-8 findings (breadth-first) and **dropped the rest**, and `ada_synthesize` truncates evidence to 6 000 chars. With many findings, the synthesis silently lost the long tail. Stuffing everything into one prompt is lossy too (the model loses the middle). Tree-reduce folds the full set in bounded batches instead.

### How
`aughor/llm/reduce.py` is a **pure** primitive — `hierarchical_reduce(items, summarize, combine, fanout, max_depth)` (≤fanout → one `summarize`; else map each batch then fold the summaries with `combine`, depth-bounded) and `partitioned_reduce` (summarize each group independently, never blending). It takes callables and never touches an LLM, so it's trivially testable. In the briefing, `_coverage_digest` (`aughor/knowledge/briefing.py`) detects when findings were dropped and folds **all** of them into a per-domain digest — tree-reduced *within* each domain, **partition-aware** across domains, on the cheap `fast` role — injected as a "FULL COVERAGE" context block (not citable; the top-8 stay the citation anchors). **Fail-open**: any digest error falls back to the original top-8 prompt.

**Key files.** `aughor/llm/reduce.py` (`hierarchical_reduce`, `partitioned_reduce`), `aughor/knowledge/briefing.py` (`_coverage_digest`, `_build_user_prompt`), `tests/unit/test_reduce.py`, `tests/unit/test_briefing_coverage.py`.

**Also leveraged in `ada_synthesize`** (`aughor/agent/investigate.py`): the investigation report's evidence log no longer truncates at 6 000 chars — `_phases_evidence_budgeted` keeps phases **verbatim** up to the budget (exact numbers preserved for grounding) and folds **overflow** phases into a number-preserving per-phase digest (`partitioned_reduce`) rather than dropping them. Fail-open to the old truncation; if nothing fits verbatim it truncates (never digest-only — verbatim numbers must remain to ground on). Tests: `tests/unit/test_phase_evidence_budget.py`.

---

## 132. Embedding entity dedup — duplicate detection (Borrow 5) ✅ Shipped

### What
Surfaces **near-duplicate ontology entities** (e.g. `Customer` vs `Client`, `Order` vs `SalesOrder`) as merge *suggestions*, via an embedding self-similarity join + connected-components clustering. Read-only — it never merges anything.

### Why
Ontology entity extraction is name/structural only — two tables with semantically similar but differently-spelled names stay separate entities, cluttering the board. Embeddings catch the semantic near-duplicates string matching can't. **Detection, not auto-merge:** a wrong merge would corrupt the ontology (and every query built on it), so collapsing entities must stay an explicit, user-confirmed action — this just finds the candidates.

### How
`aughor/ontology/dedup.py`: `cluster_by_similarity` is a **pure** connected-components clustering over the cosine-similarity graph (any pair ≥ threshold is an edge; transitive, so A~B~C cluster even if A and C aren't directly similar) — testable with hand-made vectors, no model. `detect_duplicate_entities` embeds each entity's name+description+source-tables (via `aughor/semantic/embedder.py`), clusters at a conservative 0.85 default, and returns `{entities, similarity}` suggestions (weakest-link similarity, strongest first). **Fail-open**: no Ollama / embed model → no suggestions, never a crash. Exposed at `GET /ontology/duplicate-entities` (a read; stays open).

**Key files.** `aughor/ontology/dedup.py`, `aughor/routers/ontology.py` (`/ontology/duplicate-entities`), `tests/unit/test_dedup.py`, `tests/integration/test_ontology_duplicates.py`. *(The list's other half — logprob-calibrated confidence — stays blocked: the provider layer doesn't expose `top_logprobs`, the same wall that removed the cascade.)*

**Apply-merge (the confirm step) — backend shipped:** `merge_entities` is a pure, deterministic rewrite that collapses a cluster into a canonical entity and **repoints every cross-reference** — relationships (regenerated ids, self-loops dropped, deduped), interfaces' `implementing_entities`, metrics'/actions' `entity`, and the three reverse maps (`entity_to_tables` / `table_to_entity` / `relationship_index`) — leaving the original graph untouched; `store.apply_entity_merge` persists. Exposed at **`POST /ontology/entities/merge`** (gated `ONTOLOGY_EDIT`; validates ≥2 distinct entities + canonical-in-cluster). **Explicit and user-confirmed, never automatic** — a wrong merge would corrupt the ontology.

**Ontology-board UI:** a **"Find duplicates"** action in the `OntologyPanel` header opens a drawer (`web/components/OntologyPanel.tsx`, `web/lib/api.ts` `getDuplicateEntities`/`mergeOntologyEntities`) that lists each near-duplicate cluster (entities + source tables + similarity %) and lets the user pick which entity each cluster **merges into**, then reloads the graph. Detection verified live in-browser on `beautycommerce` — it clusters the three Order-* entities (Order Line / Customer Order / Purchase Order) at 0.82. Borrow 5 fully landed (detect → suggest → confirm → merge), both backend and UI.

---

## 133. Value-domain join guard ("fool-proof joins") ✅ Shipped

### What
Catches **wrong joins that every other safeguard misses** — a join whose two keys share a name-shape and type but hold values from different entities (`orders.customer_id` = `C00127` joined to `campaigns.campaign_id` = `CMP11`; both `VARCHAR` ids, 0% value overlap). The guard samples both sides of each explicit `JOIN … ON` condition, and when the value overlap is below 15% it treats the result as unreliable and **regenerates the query once**, keeping the rewrite only if it executes *and* clears the mismatch.

### Why
Aughor's existing join safety — explorer study, tightened rules, ontology FK edges, the Phase-8 binder, fan-out de-fan, the `detect_invalid_joins` / `check_entity_column_alignment` pre-flight — all reason about column **names / types / semantics**. Those can all be fooled by surrogate ids that look alike but belong to different entities; the **value domain is the one signal that can't**. A value-disjoint join executes cleanly (0 rows on an inner join, all-NULL right side on an outer) and would otherwise be reported as a real (garbage) number — a silent correctness failure.

### How
`aughor/sql/join_guard.py`: `_extract_join_conditions` (sqlglot parse + alias resolution → real table names) · `_probe_overlap` (one DuckDB `USING SAMPLE` containment query per pair; **int-coerces the stringified `COUNT`** — the connection stringifies all result values) · `check_join_value_domains` (orchestrates, caps at 4 probes, `<15%` → `JoinDomainWarning` with a `.to_prompt_text()` matching the other pre-flight warnings). **Entirely fail-open** via `kernel.errors.tolerate` — a parse error, probe failure, or unavailable connection emits no warning and never blocks the query. **Active repair wired on all three SQL-execution surfaces**: direct (`execute_planned_queries`), ADA investigate (`_execute_safe`), and explore (`plan_and_execute_subq`) — the latter two previously had **no join pre-flight at all**. Each regenerates via `FIX_SQL_PROMPT` with the mismatch as the diagnosis and **adopts the rewrite only if it executes and re-probes clean** (never replaces a query with one that still joins on disjoint keys — prevention > recovery). Proven live on `beautycommerce`: a wrong join → the LLM regenerates the correct FK (`campaign_id = campaign_id`) → 3 real rows. *Verification also fixed a latent `FIX_SQL_PROMPT.format()` `metrics_section` `KeyError` that had silently disabled all ADA self-correction and would have crashed the explore node on any errored query.*

**Key files.** `aughor/sql/join_guard.py`, `aughor/agent/nodes.py` (direct repair), `aughor/agent/investigate.py` (`_execute_safe`), `aughor/agent/explore.py` (`plan_and_execute_subq`), `tests/unit/test_join_value_domain.py` (+ real-connection regressions), `tests/unit/test_join_guard_repair.py` (ADA), `tests/unit/test_join_guard_explore.py` (explore). PR #65. *Follow-up (ROADMAP): promote to **prevention** via precomputed `joinable_with` ontology edges.*

---

## 134. First-class SQLite connector ✅ Shipped

### What
A genuine **SQLite database connector** (`dialect = "sqlite"`), alongside DuckDB and Postgres. The agent can now connect to and read `.sqlite`/`.db` files end-to-end on the real engine — schema introspection, query execution, self-correction, and the profile/ontology intelligence — selectable from the connection form like any other backend.

### Why
SQLite support surfaced as a real capability gap while standing up the Spider 2.0-Lite benchmark (135 local SQLite databases). Rather than coerce SQLite through a DuckDB-attach shim in the benchmark harness (which measures the shim, not the product), the durable move is to support SQLite as a proper connector so Aughor's *real* path runs on the *real* engine. The benchmark then points at a registered `sqlite` connection.

### How
`aughor/connectors/file/sqlite.py`: `SQLiteConnection(Connector)` over stdlib `sqlite3`. **Read-only by construction** — opens `file:…?mode=ro` and **never creates a database for a missing path** (a reader must not materialise empty files; `test()`/`get_schema()` report a missing file cleanly). Introspects via `sqlite_master` + `PRAGMA table_info` → the house `TABLE: x (n rows) / col type` format. Mirrors DuckDB's **two-tier schema**: fast `get_schema()` (structure + glossary + join inference + exploration) on the hot path, heavy `build_intelligence()` (value profiles + structural/semantic ontology) for the background. Validates with `EXPLAIN` (catches bad table/column names), transpiles DuckDB-flavoured SQL → SQLite via sqlglot in `translate()`, and supports `make_reader()` for parallel reads, `is_healthy()`, `test()`, `close()`. Gated through the security interface like every connector. **Wired everywhere**: registered in the connector registry with `FORM_FIELDS` + `DSN_PREVIEWS`, surfaced under the `file` category by `/connectors/types`. To import the **public interface instead of module internals** (keeping the kernel-contracts private-import ratchet green without raising its baseline), added public forwarders `security_pre`/`security_post` (`db/connection.py`) and `compute_join_map` (`tools/schema.py`, companion to the existing public `parse_schema_tables`).

**Key files.** `aughor/connectors/file/sqlite.py`, `aughor/connectors/registry.py`, `aughor/db/connection.py` (public security forwarders), `aughor/tools/schema.py` (`compute_join_map`), `aughor/routers/system.py` (file category), `tests/unit/test_sqlite_connector.py` (17 — factory dispatch, introspection, execute/join, read-only write rejection, `dry_run`, dialect translation, parallel reader, DSN normalisation, registry wiring). PR #66.

---

## 135. Industry-aware intelligence — BusinessProfile + per-industry metric KB ✅ Shipped

### What
The platform now **detects a dataset's industry/vertical** and adapts which metrics and questions matter. An airline gets load-factor / on-time-performance / fleet-utilization; a DTC beauty retailer gets AOV / contribution-margin / repeat-rate / inventory-turnover — instead of one generic Commerce/Finance/Marketing lens. Each metric carries a build-time **audited** SQL so the Briefing computes it correctly and reproducibly.

### Why
The explorer was ecommerce-biased (hardcoded angles, generic KB) with no industry detection, so it asked the wrong questions of a non-ecommerce dataset and computed rates at the wrong grain (a "conversion rate" of 1.36 — impossible). What matters is the *right* industry assessment, the *right* metrics, and *correct* SQL — not clamping messy data.

### How
- **`aughor/profile/`** — `BusinessProfile` (industry + business-model + 6–8 north-star metrics + key questions), LLM-inferred from schema + glossary and **grounded to real columns**; persisted per connection (`data/business_profile_{conn}.json`). Inferred on every `/ontology/rebuild` and exposed at `GET/POST /business-profile[/rebuild]`.
- **Per-industry metric KB** — `data/kb/industry/{retail,airline,saas,logistics,food_delivery,manufacturing}.json` (~50 recipes): each metric's **formula, grain, anti-patterns, sane range**. `aughor/profile/metric_kb.py` resolves curated-preferred + a single batched LLM fallback. The recipe is injected into Phase-8 as authoritative "COMPUTATION RECIPES" so generated SQL gets the grain right (cart-to-order conversion fixed 1.36 → ~18%).
- **Audited metric SQL at build time** — each metric gets a scalar `value_sql` (the KPI strip's current value), a series `chart_sql` (a trend or top-N breakdown explainer), and each key-question gets a `key_question_sql`; all routed through the same authorities (`aughor/profile/validate.py`: dry-run + the fan-out/grain guards + join value-domain + a range/shape check) and, for metrics with a recipe, **regenerated recipe-grounded** when a draft fails — so a wrong number is dropped or fixed, not shown.
- **Wired into Phase-8** — the profile derives the per-domain coverage angles and a **pinned key-questions pass** asks the curated questions deterministically every run (each through the full guard chain) so the high-value findings are reproducible, not left to LLM chance.

**Key files.** `aughor/profile/{models,infer,store,metric_kb,validate}.py`, `data/kb/industry/*.json`, `aughor/explorer/agent.py` (Phase-8 steering + pinned pass), `aughor/routers/profile.py`, `web/components/brief/IndustryKpiStrip.tsx`.

---

## 136. Briefing trust hardening — SQL-trust guards + multi-tier dedup + metric-explainer charts ✅ Shipped

### What
A pass of correctness + de-duplication + UX work that makes the Briefing show **right, non-redundant** numbers: new fan-out/range guards close the SQL classes that reached the page as confident artifacts, three dedup tiers collapse repeats, and the dashboard's charts now **explain the industry's key metrics** while findings read as text.

### Why
Live review of real briefings surfaced confident-but-wrong cards — a $48T ROAS (fan-out), a 100% / 141% conversion (broken denominator / declared-range violation), a −149% gross margin (CTE grain-mismatch fan-out), plus the *same* finding repeated under several domains. Each is a number a CEO would act on; each is a query bug, not the data.

### How
- **SUM-over-chasm fan-out DROP** (`aughor/sql/fanout.py::sum_over_chasm_fanout`) — the SUM analogue of the existing COUNT/AVG-over-chasm drops; closes the case where `detect_fanout` flagged a chasm but `defan()` couldn't rewrite it, so the over-counting SUM proceeded ($48T ROAS).
- **Grain-mismatch-join fan-out DROP** (`cte_grain_mismatch_fanout`) — the chasm guards exclude CTE sources by design, so two CTEs joined on only the *coarser* one's grain (a strict subset of the finer's) with a non-distinct SUM/AVG that **accumulates** the coarse measure slipped past. High-precision: requires the coarse measure to be unambiguous and exempts a per-row *divisor* (`SUM(rev/total)` cancels; `SUM(rev-cogs)` doesn't). Caught the −149% margin.
- **Declared-range degenerate gate** (`agent._is_degenerate_result` + `profile.validate.profile_metric_ranges`) — extends the all-NULL/all-zero drop to a bounded rate **out of its profile-declared range** (conversion 1.41, or pinned at 100% across every segment), while an *unbounded* metric (ROAS) is exempt (2.3 is fine). Uses what the profile *knows*, not a text guess.
- **Three dedup tiers** — structural (`is_redundant_insight`, same grain+measures), **semantic/token** (`is_semantically_redundant`, same claim different SQL — Jaccard + shared anchor), and **embedding/paraphrase** (`aughor/semantic/finding_dedup.py`, cosine ≥ 0.85 via the existing `nomic-embed-text` infra; calibrated so paraphrase dupes 0.87–0.93 drop and distinct-but-related ≤0.78 survive; fail-open).
- **Briefing UX** — AI synthesis pinned top → live **Industry KPI strip** → **top-3 key-metric explainer charts** (`chart_sql` trends/breakdowns, the right Vega-Lite mark per shape) → impact-ranked **finding text cards**; "when-to-use" chart selection (`scoreDualAxis`, combo only for dual-unit); the redundant citation list and the Domain-Coverage / Org-Intelligence sections removed.

**Key files.** `aughor/sql/fanout.py`, `aughor/sql/shape.py`, `aughor/semantic/finding_dedup.py`, `aughor/explorer/agent.py` (degenerate gate, dedup gates, pinned pass), `aughor/profile/validate.py`, `web/components/brief/{BriefingDashboard,IndustryKpiStrip}.tsx`, `web/components/BriefingPanel.tsx`, `web/components/charts/chartTypeInference.ts`. Tests across `tests/unit/test_explorer_grain_lint.py`, `test_degenerate_finding.py`, `test_query_shape.py`, `test_finding_dedup.py`, `test_profile_value_sql_audit.py`.

---

## 137. Design Language v2 + conclusion-first Briefing + section polish ✅ Shipped

### What
A token-first visual re-skin of the whole app (deeper surfaces, real elevation, rounded panels, theme-aware charts) plus three UX upgrades adopted from an external "Aughor v2" design mockup: a **conclusion-first Briefing** (Verdict Hero), a **nav information-architecture** change, and **real-count summary rows** across the list screens.

### Why
The mockup proposed a bolder design language and a conclusion-first hierarchy. Auditing it against the codebase showed its *features* (Investigations, hypotheses, Action Hub triggers, Monitors, Playbook, Semantic Layer, Catalog, Query Builder) **already existed and were richer** than the hardcoded comp — so the real value was presentation + information hierarchy, not new capabilities. We adopted the design language and the genuinely-better UX patterns, and deliberately skipped the mockup's fake controls (a period segmented control that filtered nothing; a fabricated "$1.2M Tracked ARR" stat — recommendations are free-text, there is no structured impact field).

### How
- **Design language (3 tiers, additive `web/aughor-v2/`):** Tier 1 = a primitive **token override layer** (`theme/tokens-v2.css` + `elevation-motion.css`) imported after `styles/tokens.css`, so every Tailwind/shadcn bridge and `.aug-*` class inherits the new look via `var()` with no markup changes. Tier 2 = `components-v2.css` re-skins `.aug-*` (gradient primary, lifted cards, pill tags, focus rings) — loaded in `layout.tsx` *after* `globals.css` so it wins the cascade over the inline base rules. Tier 3 = the existing Vega engine themed centrally in `VegaChart.tsx`: `vegaV2Config()` merged at the one spec chokepoint (token-driven axes/grid/palette/rounded bars), a `remapLegacyColors()` deep-walk swapping the legacy hardcoded mark hexes → `--chart-*`/`--bg-2` tokens (no per-builder edits), and a `MutationObserver` on `data-theme` re-embedding charts on dark/light flip; PNG export bg reads `--bg-2`.
- **Conclusion-first Briefing** (`BriefingPanel.tsx`): a new `VerdictHero` leads with the synthesized verdict (`narrative.headline_theme`), the top finding as lead, proof-stat tiles (domains / findings / lead-confidence), and the primary action (Investigate + the existing `FindingActions` menu). Falls back to the deterministic top finding when no AI narrative exists. A `SupportingSignals` 3-up confidence-meter row renders the strongest `briefing.signals` beneath it; the full prose + interactive citations move below under "Full synthesis" (`NarrativeCard` gains `hideHeadline`).
- **Nav IA** (`page.tsx`): default landing changed to the Briefing; **Investigations** promoted into the Intelligence nav, pointing at the existing Recents/investigations history.
- **Section summary rows + QB badge:** new shared `components/ui/MiniStat.tsx`; **real-count** `MiniStatRow`s on Inbox (Open / Implemented / Verified / Total — from outcomes), Investigations (Total / Investigations / Completed), and Monitors (Total / Active / Unacked — guarded to only show when monitors exist). Query Builder gains a `valid`/`error` SQL badge in the Run toolbar (the exec-time chip already existed at the result meta line).

### Key files
- `web/aughor-v2/` *(new — token/chart package + handoff docs)*, `web/app/globals.css`, `web/app/layout.tsx`
- `web/components/VegaChart.tsx`, `web/components/Chart.tsx`
- `web/components/BriefingPanel.tsx`
- `web/app/page.tsx`, `web/components/ui/MiniStat.tsx` *(new)*, `web/components/RecommendationInbox.tsx`, `web/components/MonitorsPanel.tsx`, `web/components/QueryBuilder.tsx`

### Note on the Tailwind v4 pipeline
Two non-obvious wiring facts surfaced: a CSS `@import` with a trailing **same-line comment** is silently dropped by the Tailwind v4 (`@tailwindcss/postcss`) bundler — keep import lines bare; and Lightning CSS strips the unprefixed `backdrop-filter` (keeps only `-webkit-`), so the glass topbar degrades to its background tint in Chrome.

---

## 138. Human-Editable, Version-Controlled Ontology Overrides ✅ Shipped

### What
The auto-built business ontology (entities, metrics, relationships) is no longer a black box the explorer alone owns. It is now a **human-editable YAML tree** that lives in version control, and **human edits win** over the machine's inference — an "override-wins" merge, Nao-inspired.

### Why
Auto-inference is a strong first draft, never gospel. Domain experts know things the data can't show (a column is deprecated, two tables are the *same* entity under a rename, a metric should exclude internal accounts). Before this, the only way to correct the ontology was to fight the inference. Two confirmed real-world drifts were traced to the machine overruling a correct human view. The fix: make the ontology a reviewable artifact, and let a checked-in human override always take precedence over re-inference.

### How
- The ontology is serialized to a YAML tree that a human can open, diff, and edit in a PR.
- On every re-inference, machine output is **merged under** the human overrides — fields a human has set are preserved verbatim; everything else re-infers freely.
- Because it is version-controlled, the ontology gets the same review/rollback story as code: drift is visible in a diff, not silently overwritten.

### Key files
- `aughor/explorer/store.py`, `aughor/explorer/agent.py` (override-aware load/merge)
- ontology YAML under `data/`

---

## 139. Pre-Emission Insight Verification Gate ✅ Shipped

### What
A **last-line-of-defense gate** that every candidate finding must pass *before* it is allowed into a briefing. It re-checks the claim against live SQL and kills insights that are tautological, fan-out-inflated, boundary-saturation artifacts, part-greater-than-whole, or not actually grounded in the result it cites.

### Why
A SOTA analytics platform cannot emit a confident-sounding number that is secretly nonsense. The BeautyCommerce cold-trace surfaced several classes of "plausible trap" the pipeline would otherwise ship: a ratio of a column against itself (always 100%), a SUM inflated by a one-to-many join fan-out, a "max" that is really a saturated boundary, a part exceeding its whole. Structure alone didn't catch these — they had to be screened claim-by-claim.

### How
- **Self-ratio tautology** — flags `X / X`-shaped ratios that are 1.0 by construction.
- **Fan-out detection** — `detect_fanout` + a **live cardinality oracle** (`make_uniqueness_oracle`: `COUNT(*) = COUNT(DISTINCT key)` probed on the real connection) re-run on CTE bodies, with a normalized-weight carve-out so legitimate weighted attribution survives.
- **Scale-robust boundary saturation** — distinguishes a real extremum from a clamped/saturated boundary.
- **Part > whole** and **claim-grounding** — the cited number must actually exist in the cited result set.
- Wired at all three `verify_insight` call sites in the explorer; covered by `tests/unit/test_insight_gate.py`.

### Key files
- `aughor/explorer/agent.py` (`verify_insight` + helpers), `aughor/sql/fanout.py` (`self_ratio_tautology`, cardinality-aware chasm roots), `aughor/sql/validate.py` (`make_uniqueness_oracle`)
- `tests/unit/test_insight_gate.py`

---

## 140. Briefing-Trust Round 2 — BeautyCommerce Cold-Trace Learnings ✅ Shipped

### What
A bundle of trust + grounding fixes (the **F1–F10** findings) distilled from a deliberate experiment: approaching a rich BeautyCommerce warehouse *cold* (as an analyst would) and diffing that against what Aughor's live pipeline produced, then closing every gap.

### Why
The cold-trace exposed where the pipeline under-performed a careful human: it gave up after one failed SQL attempt, inflated SUMs across chasm joins, hallucinated a business model the data didn't support, mis-declared metric ranges, treated high-null columns as uniformly meaningless, and lacked mid-run observability.

### How
- **F1 — per-question SQL retry:** each key question now retries its own SQL independently (1/8 → 8/8 answered on the trace).
- **F2 — cardinality-aware chasm guard:** SUM-over-fan-out drops use the live uniqueness oracle, not a heuristic.
- **F3 — structural-vs-noise NULL classification:** high-null columns are classified (structural / noise / dead) instead of blanket-ignored.
- **F6 — glossary keyed per connection + column-fingerprint:** auto-seed re-seeds on schema drift with no cross-warehouse contamination.
- **F7 — evidence-cited business model:** the inferred model must cite data evidence or it's dropped.
- **F4 — range calibration** from the audited value; **F5 — cross-domain + key-questions seeding**; **F8 — direction-aware join guard** (child ⊂ parent is valid).
- **Observability:** `_save_state()` mirrors the live phase to disk mid-run; a shared semaphore (`AUGHOR_MAX_CONCURRENT_EXPLORERS`) caps concurrent explorers.

### Key files
- `aughor/explorer/agent.py`, `aughor/profile/infer.py`, `aughor/autoseed/*`, `aughor/sql/fanout.py`
- `tests/unit/test_explorer_phase_persist.py`, `tests/unit/test_explorer_grain_lint.py`

---

## 141. Per-Schema Intelligence — True Multi-Schema Isolation ✅ Shipped

### What
The unit of intelligence is now **(connection × schema)**, not the connection. A multi-schema connection like `workspace` (ecommerce, missimi, bakehouse, netflix) gets a **fully isolated** profile, ontology, exploration state, and briefing per schema — plus an **"All schemas"** aggregate view — instead of one blended, leaky profile.

### Why
A single connection routinely hosts several unrelated businesses. Before this, exploring `workspace` produced one profile that bled the dominant schema's identity onto the others (a bakery schema was described as "Missimi-focused"), and schema selection in Briefings was cosmetic — certain cards/charts ignored it. Isolation has to be real, not labeled.

### How
- **Schema-scoped everything:** profile store writes `business_profile_{conn}__{schema}.json`; exploration/ontology stores key by `{conn}__{schema}`; `_gather_context` opens the connection via `open_connection_for_with_schema` so inference only ever sees one schema.
- **Per-schema fan-out:** `kickoff_exploration(conn, schema=None)` fans out across `schemas_of_connection`, each schema running the proven single-schema pipeline once.
- **Schema-qualified isolation:** findings are matched on `schema.table` (not bare names), and a `_leaks_schema` guard drops any finding whose SQL references a *different* schema — because a schema-scoped DuckDB can still physically execute another schema's tables.
- **Aggregate view:** `load_aggregate` / `get_aggregate_domain_insights` compose an "All schemas" rollup.
- **Full-stack wiring:** `/start?schema=` and `/status?schema=` (returns `per_schema`); `getBusinessProfile/getExplorerStatus/startExplorer(connectionId, schema?)`; `BriefingPanel` threads `schema` into the KPI strip, dashboard, and status poll.
- **Live-verified:** a clean fan-out re-run produced four distinct, correctly-grounded profiles (e-commerce / beauty / bakery / SVOD streaming) with zero cross-contamination.

### Key files
- `aughor/profile/store.py`, `aughor/profile/infer.py`, `aughor/explorer/store.py`, `aughor/explorer/agent.py`
- `aughor/routers/_shared.py`, `aughor/routers/exploration.py`
- `web/lib/api.ts`, `web/components/BriefingPanel.tsx`
- `tests/unit/test_schema_isolation.py`, `tests/unit/test_explorer_phase_persist.py`

---

## 142. CEO-Grade Briefing Triage — Impact-Ranked Lead, Trust Gate & Currency ✅ Shipped

### What
The daily Briefing was reframed from "what's true in the data" to "what changed, what's it worth, what to decide." The synthesis now **leads with the biggest business move** (impact-ranked, not novelty/recency), **never presents an impossible number or an anti-causal correlation as fact** (a trust gate suppresses/demotes them with an auditable reason), surfaces **north-star metric *trends*** (gross margin 50%→34%, AOV €75→€56) as first-class candidates, and reports every figure in the **business's own currency** (€, not $). The same triage authority governs every finding surface — the AI synthesis, the supporting-signals + key-questions cards, and the dashboard cards — and ADA/deep-analysis carries advisory trust caveats.

### Why
Stress-testing the missimi brief (a €30M DTC beauty co) exposed a brief no CEO would trust: it led with a noise-level ROAS split (4.42 vs 4.46) while gross margin and AOV both slid unmentioned, printed an **impossible inventory turnover of 96,295×** (a grain-broken `SUM(units_sold)/AVG(units_on_hand)`) as a confident finding, presented an **anti-causal correlation** ("stockouts fall as lead time rises") as insight, and showed **`$`** for a euro business. A daily executive brief has to triage by materiality and plausibility, in money, or it gets ignored by Thursday.

### How
- **Impact ranking** (`aughor/knowledge/triage.py`) — `impact_score` = magnitude-of-change × north-star membership × confidence, with a **risk tilt** so a *decline* in a down-is-bad metric (margin/revenue/AOV/retention) leads over an equal-magnitude gain ("lead with the fire") — a much larger gain still wins. Replaces top-by-novelty, which buried the lede.
- **Plausibility trust gate** — `plausibility()` SUPPRESSES impossible magnitudes via an **operating-band KB** for open-ended metrics the bounded-rate guard can't catch (inventory turnover > ~100×) and DEMOTES anti-causal inverse-monotonic correlations to a flagged hypothesis. Both checks are **lifted to the emission gate** (`verify_insight`, one shared band KB) so they protect every consumer, not just the brief. A **vacuous-CASE guard** rejects a `CASE` that collapses entirely into its `ELSE` default (the missimi bug: hardcoded brand names matched no rows → all 3,500 products fell to `'unknown'`, ignoring a real `brand_tier` column).
- **Metric-moves** (`aughor/knowledge/metric_moves.py`) — each north-star metric's `chart_sql` trend is run (cache-miss only, matcache-first), its first→last move synthesised into a finding that competes through the same impact ranking; near-zero-base moves dropped (the "0%→1% (+40%)" artifact).
- **Currency** — `BusinessProfile.currency_code` (LLM-inferred); the narrator prompt + a synthesis-authority normalisation (`$<num>`→symbol) + currency-aware KPI cards make a €-business render € everywhere.
- **Every surface** — a `held_back` audit strip under the synthesis; `/domains` stamps each insight with `impact`+`plausibility` so the dashboard cards **and** the panel's deterministic synthesis builder (headline + supporting signals + key-questions) drop only the impossible and rank by impact; ADA's `_assemble_phase_findings` attaches a non-blocking `trust_caveat`.
- **Live-verified on missimi:** headline "Growth Levers and Operational Efficiency" → **"Margin Erosion Demands Channel Optimization"**; lead = margin 50%→34% then AOV €75→€56; turnover suppressed into the held-back strip; € throughout; cards/signals drop the implausible finding. 1045 backend tests green; FE typecheck clean.

### Key files
- `aughor/knowledge/triage.py`, `aughor/knowledge/metric_moves.py`, `aughor/knowledge/briefing.py`
- `aughor/explorer/agent.py` (vacuous-CASE + emission-lifted plausibility), `aughor/profile/models.py` (`currency_code`)
- `aughor/routers/exploration.py`, `aughor/agent/investigate.py`, `aughor/agent/state.py` (ADA advisory)
- `web/components/BriefingPanel.tsx`, `web/components/brief/BriefingDashboard.tsx`, `web/components/brief/IndustryKpiStrip.tsx`, `web/components/InvestigationReport.tsx`, `web/lib/api.ts`
- `tests/unit/test_triage.py`, `test_metric_moves.py`, `test_briefing_triage.py`, `test_vacuous_case.py`

---

## 143. Interactive Briefings — Interrogate the Brief in Place ✅ Shipped

### What
The Briefing is no longer a document you read — it's a surface you interrogate. Every element is a live handle into the engine, with one model: **Explain / Drill / Ask**.
- **A · Pull the thread** — click any finding or citation → an ADA investigation streams **in place** below it, seeded with that finding's exact SQL.
- **B · Drill-down charts** — click a bar/point → "Why is it the outlier?" (ADA decompose on that slice) or "Filter chart" to that value.
- **C · Show the receipt** — click any magnitude number → re-runs the cited query live and shows the exact grounding cell + SQL (KPI tiles and narrative numerals alike).
- **D · Steer the lens** — a trailing time-window (30d/90d/1y/All) re-scopes the trend charts client-side.
- **E · Living brief** — a persistent "Ask this briefing" box spawns investigation cards seeded with the brief's own context.

### Why
The hardest parts already existed (ADA over SSE, `/query/run`, numeral grounding); the brief just couldn't reach them. Making each number/finding/bar a handle turns a static digest into a workspace — and, as a side effect, makes any upstream contradiction immediately visible (which is what surfaced the trust gaps closed in #144).

### How
- Shared SSE machinery extracted to `investigationStream.ts`; `useInvestigationThread` owns **one AbortController per instance** so many inline threads stream concurrently; `InlineInvestigationThread` reuses the chat `ChatMessage` renderer.
- `InvestigateRequest` gains `schema` / `seed_sql` / `seed_context`; the seed lands in `scan_context`, which `ada_intake` already reads — **zero graph change**.
- `grounding.ground_numerals` + `POST /exploration/{conn}/briefing/ground` re-run a cited finding's query and back a specific number; it tries **all** citations so a synthesized number is proven against its true source, never falsely flagged.
- Vega `View` click → `onSelect` threaded `VegaChart → Chart → InvestigationChart → ChartCard` (no spec change).

### Key files
- `web/lib/investigationStream.ts`, `web/lib/useInvestigationThread.ts`, `web/components/brief/{InlineInvestigationThread,GroundedNumber,BriefAskBox}.tsx`, `web/components/brief/BriefingDashboard.tsx`, `web/components/VegaChart.tsx`
- `aughor/explorer/grounding.py`, `aughor/routers/investigations.py`, `aughor/routers/exploration.py` *(commit `994bc71`)*

---

## 144. Briefing Intelligence Trust — Gate on Governed Metrics + Live Re-Validation ✅ Shipped

### What
A parallel hardening pass (alongside #142) that closes six root causes of fabricated / self-contradictory briefings (a 96,295× inventory turnover headlining, a "gross margin 50%→34%" decline in no data, ADA rewriting a governed formula into a broken one, confident attribution built from failed queries, "Top Return Reason 0.4%", cross-business blending, "47% critically low"). Root insight: the guards mostly existed — they just weren't **wired** into the paths that generate/surface findings, and the explorer/ADA free-formed metric formulas instead of binding to the governed layer.

### How
- **RC1 — feasibility gate:** `unsupported_metric_gap` wired into Phase-8 question generation (scoped to the question's own tables) and `ada_intake`, so a margin question against a cost-less schema is dropped/caveated instead of fabricating `COGS = price·qty·0.5` → a constant 50%.
- **RC2 — bind to the governed formula:** `resolve_canonical_metrics` now injects the connection's `BusinessProfile.north_star_metrics` (source `profile_governed`, above the ontology) + a hard intake BINDING RULE → ADA runs `SUM(unit_price-unit_cost)/SUM(unit_price)` with no invented `quantity`.
- **RC4 — implausible-ratio guard** in `verify_insight`: a turnover/ratio/×-multiplier in the thousands is a grain bug; tightly bound to the ratio's own number so a nearby revenue figure isn't false-flagged (complements #142's operating-band + vacuous-CASE guards).
- **RC5a** — ADA suppresses the fabricated waterfall + recommendations and writes an honest "data unavailable" verdict when no usable data was gathered; **RC5b** — `revalidate_live` re-runs the top-N findings before a brief refresh, re-applies `verify_insight` + grounding, and flags failures `invalid` (reversible) so they drop from both `/domains` and `/briefing`.
- **RC3 — name↔SQL coherence:** a category/label-named metric ("Top Return Reason", "distribution") declared as a scalar percent is dropped at build-time + serve-time.
- **RC6 — cross-schema separation:** the aggregate brief tags each finding `source_schema` and switches to a synthesis prompt that forbids cross-business connection-drawing.
- **Severity grounding** — explorer + ADA prompts: "lowest in a ranking ≠ weak"; no absolute superlatives without a benchmark.
- **Stale removal:** `restart`/`reset` now purge **per-schema** state (not just connection-level) and fan the re-run out per schema; aggregate React keys are composite (`source_schema::id`).

### Why
The interactive surface (#143) made every contradiction clickable, exposing that the underlying intelligence was untrustworthy. A brief that headlines fabricated numbers is worse than no brief.

### Verified
A full from-scratch re-run of the `workspace` connection regenerated all four schemas with **zero garbage** (bakehouse has no gross-margin finding; missimi reproduces its real ROAS/margin); the fresh "All schemas" brief reads per-business ("Revenue Quality and Efficiency Risks Across Sectors"). 1020 unit tests pass (+16 new guard/coherence tests).

### Key files
- `aughor/explorer/agent.py`, `aughor/agent/investigate.py`, `aughor/agent/prompts_investigate.py`, `aughor/semantic/canonical.py`, `aughor/profile/validate.py`, `aughor/routers/profile.py`, `aughor/routers/exploration.py`, `aughor/explorer/revalidate_live.py`, `aughor/knowledge/briefing.py`, `aughor/explorer/store.py`
- `tests/unit/test_intel_guards.py`, `tests/unit/test_grounding.py` *(commits `7860ea1`, `4bce086`, `20dedb8`, `e649f06`)*

---

## 145. Finding Dossier — Drill-Down Is a Read, Not a Second Analysis ✅ Shipped

### What
When the explorer produces a briefing finding it has *already* done the deep analysis — asked a question, run SQL, grounded every magnitude, and mapped the structural facts the claim stands on. That derivation used to be discarded, so when a CEO drilled into a finding to understand it, **Investigate cold-started a full ADA run to reconstruct what was already known**. The Finding Dossier captures that derivation **once, at emit**, and serves it as the trace — so understanding a finding is a **$0 read**, and only a genuinely new follow-up spends a fresh analysis.

### Why
The hardest work (the analysis behind a finding) was thrown away and re-paid on every drill; the semantic cache missed because the drill question became `"Investigate: <finding>"`. Capitalising on work already done is cheaper *and* more trustworthy — the trace is the real derivation, not a plausible re-derivation.

### How
- **Capture (P1)** — at the Phase-8 emit (`_emit_insight`), `build_dossier()` bundles the question asked, the SQL, the interpreter's **rationale** (previously discarded), the grounded result cells, and the Phase 3-7 structural facts (verified joins/cardinality, NULL meanings, lifecycle, distributions) scoped to the finding's tables. It rides **inside the finding's K3 ledger-artifact payload** (not `state["insights"]`, so the panel stays lean). A live-path bug — `_tables_in_sql` returns schema-qualified names while structural facts are keyed bare — was caught by verification and fixed with a `_bare()` normaliser.
- **Evidence drawer (P2)** — renders the full trace from the existing **read-only receipt** endpoint at **$0** (why-it-matters, grounded figures, structural ground, SQL, Trust Receipt); no new endpoint.
- **Investigate re-route (P3)** — a **Tier-0 short-circuit**: drilling a known finding serves the dossier by insight id (`AGENT TRACE · 0 steps · 10ms`, no ADA/SQL/LLM); **"Investigate deeper"** escalates to ADA seeded with the dossier.
- **Living freshness (P4)** — `revalidate_finding()` re-runs the stored SQL once (no LLM), re-grounds the claim → `confirmed | drifted | error`, re-stamps "as of"; `update_dossier()` writes a new artifact version (supersede-not-delete).
- **Per-finding narrative (P5)** — the briefing narrator pass attributes each cited `[N]` sentence back to its finding's dossier — no new LLM call.
- **Unified seed + first-class `origin_finding`** — the dossier drill and the briefing "pull the thread" both originate an investigation from a known finding; unified onto **one structured `origin_finding`** in `AgentState` (a plain channel, never overwritten) that the ADA branch consumes directly: `ada_intake` **anchors its metric/tables/window/filters on the finding** instead of re-deriving, downstream phases inherit it via `_ada_intake`, and `origin_insight_id` is stamped on the report + persisted on the investigation row (finding → investigation → report is queryable lineage). This also fixed a **latent no-op** — the former `scan_context` seed was overwritten by `exploratory_scan` before `ada_intake` ever read it.

### Verified
Live on `workspace`: a real `_emit_insight` → dossier round-trips through the live receipt endpoint; the Evidence drawer renders the full trace (incl. a real `order_items→reviews` **9,600-orphan** join warning); Re-validate → "✓ Confirmed" + freshness re-stamp; Investigate drill = **0 steps / 10ms** vs "deeper" = a real seeded ADA run (1 step / 53s); a real deep run persisted `origin_insight_id` on its row. Web `tsc` clean.

### Key files
- `aughor/explorer/dossier.py` (new), `aughor/explorer/agent.py`, `aughor/explorer/revalidate.py`, `aughor/knowledge/briefing.py`
- `aughor/routers/investigations.py` (Tier-0 + `_build_origin_finding`), `aughor/routers/exploration.py` (revalidate endpoint), `aughor/agent/{investigate.py,state.py,nodes.py,prompts_investigate.py}` (`origin_finding`), `aughor/db/history.py` (`origin_insight_id`)
- `web/components/BriefingPanel.tsx` (`DossierTrace`/`RevalidateRow`), `web/components/ChatMessage.tsx` (`DossierReportView`), `web/lib/{api,useChat,investigationStream,useInvestigationThread}.ts`, `web/app/page.tsx`, `web/components/{CanvasWorkspace,IntelligenceWorkspace}.tsx`, `web/components/brief/BriefingDashboard.tsx` *(PR #72)*

---

## 146. ADA Grounding & Driver-Question Routing — Found by a 10-Question Real Test ✅ Shipped

### What
A from-scratch Deep-Analysis stress test on the 13-table `missimi` warehouse (1.5M orders): fresh explore → ground truth from direct SQL → **10 hard questions** (clear signals + flat-signal traps + confounders) → **every claimed number verified against the DB**. It scored **8/10 grounded-correct** — held all flat-signal traps (invented no fake winner) and avoided the stockout confounder — and surfaced two real defects, both fixed and re-verified.

### How
- **Q1 — synthesis share grounding:** ADA fabricated an *uncomputed* share ("gift_sets contributes **4.6%** of total gross margin"; real **0.95%**). The numeric guard exempts percentages, and `ADA_SYNTHESIZE_PROMPT` said "bold the share" without requiring it be computed. Added a GROUNDING rule: **state a share/proportion only if a query returned it; never divide two numbers to manufacture a percentage.** Re-run: fabrication gone; fully grounded (gift_sets 36.34% vs strongest makeup_lips 52.32%, lag 15.98pt).
- **Q4 — driver/segment routing:** "Do late deliveries lower review scores?" routed as a **temporal trend** (review score over weeks) → "no effect" — structurally blind, since ~70% of orders are late in *every* week; the signal is per-order. Added **driver/relationship detection** to `ada_intake` (`IntakeOutput.comparison_segment_sql`/`label`): such questions now set `cross_sectional`, and `ada_cross_section` compares the metric **across the derived segment** (`order_delivered_ts > order_estimated_delivery`) as the primary query. Re-run: late **4.23** vs on-time **4.45** (−0.22), n=949,789 / 413,466 — matching ground truth exactly.
- Both prompt changes are **additive** (no segment / no computed share → behaviour byte-for-byte unchanged).

### Key files
- `aughor/agent/prompts_investigate.py` (synthesis grounding rule, intake driver rule, `IntakeOutput` segment fields, cross-section primary-comparison hook), `aughor/agent/investigate.py` (`ada_cross_section` segment seeding + intake override) *(PR #72)*

---

## 147. Ratio-Aware Cross-Sectional Scan — Stop Summing a Percentage ✅ Shipped

### What
A real freight-cost Deep Analysis rated **3/10** exposed a semantic bug the numeric guard can't catch: for a **ratio** metric (`SUM(freight)/SUM(order_value)*100`), the cross-sectional weakness scan used an **additive-SUM** SQL template, so the coder silently **dropped the denominator**, reported `SUM(freight)/COUNT(*)` (avg-$/order), and synthesis labeled **$1.48/order as "1.48%"** — overwriting a *correct* origin finding (Germany 2.17%) at *High confidence*. It slips past `verify_finding` because $1.48 *is* a real cell (a unit error, not a fabricated magnitude).

### How
- **Deterministic gate** `_metric_is_ratio(metric_sql, metric_label)` in `investigate.py` — fires on `*100`, a `/` between ≥2 aggregates, a bare `AVG`/`MEAN`/`MEDIAN`, or a %/rate/ratio/average label — ORed with intake's new `IntakeOutput.metric_is_ratio` flag (the deterministic detector is the authority; the intake flag is a hint).
- **`ada_cross_section` branches by metric kind.** Ratio → `CROSS_SECTION_RATIO_BLOCK`: compute `{metric_sql} AS metric_total` **verbatim** (`SUM(num)/SUM(den)` re-aggregates correctly per group), also SELECT `numerator_total`/`denominator_total`/`n` for audit, **no** `avg_per_record`, **no** `pct_of_total`, order by the ratio. Additive → `CROSS_SECTION_ADDITIVE_BLOCK` = byte-for-byte the historical steps.
- **Direction-aware interpretation** (`CROSS_SECTION_RATIO_INTERPRET_PROMPT` + ratio synthesis note): a **low** cost/freight/defect ratio is **good**, not "weakest" — the report now pushes back on a false "which is weakest" premise. Chart helper `_chart_ratio_primary` plots the ratio, not the big dollar aggregates.
- **Bonus wiring fix:** `ada_cross_section` added to the `phase_complete` SSE tuple — the cross-section phase now **streams live** to the UI (was silent, surfaced only in the final report).

### Verified
Live HTTP `/investigate` (deep) on `missimi`: "which country has the weakest freight cost efficiency relative to order value, and why?" → SQL keeps `…/NULLIF(SUM(order_value),0)`; rows **DE 2.17%** (lowest), others **4.25–4.34%** — match direct-SQL ground truth to the decimal; headline *"Germany has the **strongest** freight cost efficiency at 2.17% of order value, **not the weakest**."* A live additive run (revenue-by-category) still emits `metric_total`/`avg_per_record`/`pct_of_total`, weakest-first — additive path unchanged.

### Key files
- `aughor/agent/prompts_investigate.py` (`CROSS_SECTION_ADDITIVE_BLOCK`/`CROSS_SECTION_RATIO_BLOCK`/`CROSS_SECTION_RATIO_INTERPRET_PROMPT`, `{metric_computation_block}` hook, `IntakeOutput.metric_is_ratio` + intake METRIC KIND rule), `aughor/agent/investigate.py` (`_metric_is_ratio`, `_chart_ratio_primary`, `ada_cross_section` branch + synthesis ratio note), `aughor/routers/investigations.py` (cross-section phase SSE streaming)

---

*Last updated: 2026-06-20 · 147 active features (#147 ratio-aware cross-sectional scan — `ada_cross_section` branches RATIO vs additive: a ratio metric is computed `SUM(num)/SUM(den)` per group (denominator kept, never SUM'd or ÷COUNT), with direction-aware interpretation (a low cost-ratio is a strength) + ratio chart + cross-section phase SSE streaming; additive path byte-for-byte unchanged; freight-% reproduces Germany 2.17% lowest exactly on missimi, fixing a 3/10 result that had mislabeled $1.48/order as "1.48%"; #146 ADA grounding & driver-question routing — synthesis share-grounding (never manufacture a percentage) + driver/segment intake routing (compare a metric across a derived condition, not a blind trend), found by a 10-question missimi real test scoring 8/10 grounded; #145 Finding Dossier — capture the explorer's derivation so drill-down is a $0 read not a second ADA run: Tier-0 trace, live re-validate, per-finding narrative, and one first-class `origin_finding` seed anchoring `ada_intake` + carrying provenance into the report; #144 briefing intelligence trust — gate explorer/ADA on governed metrics, implausible-ratio guard, live re-validation, name↔SQL coherence, cross-schema separation, benchmark-grounded severity, per-schema stale-removal; #143 interactive briefings — pull-thread/drill-charts/show-the-receipt/time-lens/living-brief over one inline-investigation surface; #142 CEO-grade briefing triage — impact-ranked headline (magnitude-of-change × north-star × confidence) + risk-tilt "lead with the fire"; plausibility trust gate lifted to the emission gate (suppress impossible-magnitude via operating bands, demote anti-causal confounds) + a vacuous-CASE guard; north-star metric-moves as first-class candidates; currency-correct € figures end-to-end; live-verified on missimi; #141 per-schema intelligence — connection×schema unit: isolated profile/ontology/exploration/briefing per schema + "All schemas" aggregate + schema-qualified `_leaks_schema` guard, live-verified 4 distinct profiles; #140 briefing-trust round 2 — BeautyCommerce cold-trace F1–F10: per-question SQL retry, cardinality-aware chasm guard, structural-vs-noise NULL, evidence-cited business model, mid-run phase observability + concurrency cap; #139 pre-emission insight verification gate — self-ratio tautology, fan-out cardinality oracle, boundary-saturation, part>whole, claim-grounding screens before emission; #138 human-editable version-controlled ontology overrides — YAML tree, override-wins merge; #137 design language v2 — token override + `.aug-*` re-skin + central Vega theming/reactivity, conclusion-first Briefing Verdict Hero + supporting signals, Briefing-as-home nav IA, real-count MiniStat rows + QB validity badge; #136 briefing trust hardening — SUM-over-chasm + grain-mismatch-CTE fan-out drops, profile-declared-range degenerate gate, 3-tier dedup incl. embedding paraphrase, metric-explainer charts; #135 industry-aware intelligence — BusinessProfile keystone + per-industry metric KB + build-time audited value_sql/chart_sql/key_question_sql + pinned key-questions; #134 first-class SQLite connector — PR #66; #133 value-domain join guard — PR #65; #132 embedding entity dedup — Borrow 5; #131 hierarchical tree-reduce — Borrow 4; #130 Query Builder semantic-step UI; #127–#129 semantic operators; #126 model-cascade tombstone). **Adaptive-inference list worked through** (B5b logprob-confidence blocked); next up = external NL2SQL benchmarking (Spider 2.0 — SQLite reader in place) + promoting the join guard to prevention (`joinable_with` edges). See `ROADMAP.md`.*
