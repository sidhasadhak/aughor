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
- Timeout is configurable: `HERMES_TIMEOUT_SECONDS` (default 300)

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

The classifier result is emitted as a `{ type: "mode", query_mode }` SSE event immediately after `route_question` runs, so the frontend can adapt its UI before any queries execute.

### Component interactions
- `hermes/agent/state.py` — `RouteDecision` Pydantic model (`mode`, `reasoning`); `query_mode: Optional[Literal["direct", "investigate"]]` added to `AgentState`
- `hermes/agent/prompts.py` — `ROUTE_QUESTION_PROMPT` with concrete direct/investigate examples
- `hermes/agent/nodes.py` — `route_question()` node; `route_after_classify()` router function
- `hermes/agent/graph.py` — `route_question` set as entry point; `add_conditional_edges` to `decompose` or `plan_and_execute`
- `hermes/api.py` — emits `mode` SSE event; includes `query_mode` in the `report` event; passes `columns`/`rows` (up to 50) in `query_history` so the frontend can render the results table
- **Frontend:** `mode` event sets `queryMode` in state; `ReportView` shows raw data table + "Short Summary" label; hypothesis cards and "Hypotheses" counter hidden in direct mode; `HistoryDetailPanel` detects direct mode via `hypothesis.id === "direct"` and suppresses the hypothesis section

### Tech / libraries
- **LangGraph conditional edges** — `route_question` → `decompose` | `plan_and_execute`
- **instructor + Pydantic** — `RouteDecision` structured output
- No new infrastructure — same LLM providers, same graph compilation path

---

## How features connect — end-to-end data flow

```
User question
    │
    ▼
Cache check (Prior Investigations RAG)
    ├─ hit (score ≥ 0.80) ─────────────────────────────────► SSE: report (cached) ⚡
    │
    └─ miss ──► create_investigation(history.db)
                    │
                    ▼
              route_question                           SSE: mode
                ├─ LLM classifier → "direct" | "investigate"
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
                        ├─ LLM → QueryPlan (coder model)
                        ├─ DatabaseConnection.execute → QueryResult
                        ├─ SQL self-correction on error → Pitfall logged
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
                 (user input)       └─ LLM → AnalysisReport (narrator model)
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

*Last updated: 2026-05-15 · 17 features. See `ROADMAP.md` for upcoming features.*
