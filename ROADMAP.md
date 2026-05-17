# Aughor — Product Roadmap

**Product:** Aughor — Autonomous Analyst  
**Repo:** https://github.com/sidhasadhak/hypothesis-engine  
**Stack snapshot:** LangGraph · Ollama (qwen3-coder-next:cloud) · FastAPI SSE · Next.js (App Router) · DuckDB + PostgreSQL · SQLGlot · scipy/statsmodels · uv

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

## Build Sequence & Dependency Graph

**Recommended sprint order — each sprint compounds on the last:**

| Sprint | Milestone(s) | Key unlock |
|---|---|---|
| **1 — SQL Hardening** ✅ | 2h (Error Classification + Dialect Transforms + Column Ambiguity) + 2i (Join Inference + Fingerprinting) | Every query gets smarter; no new infra needed |
| **2 — Semantic Depth** ✅ | 1e (Metrics Catalog) + 2j (KB Pattern Enrichment) | Agent understands business KPIs and causal chains |
| **3 — Conversational** ✅ | M9 (Quick Chat + multi-turn history + Chart Engine + Deep Analysis tab) | Analyst-feel experience; session memory; rich inline charts; resizable |
| **4 — Provider Flexibility** | M5 (Anthropic backend) | Cloud deployment; prompt caching cuts costs |
| **5 — Production Safety** | M6 (Security: Gradient Safety + PII + Audit + Budget) + M7 (Observability) | Enterprise-ready; Langfuse traces |
| **6 — Analytical Depth** | M4 (Prophet forecasting) + M2d (Events Calendar) | "Is this drop unusual *given the trend*?" |
| **7 — LLM-free Path** | M11 (Visual Query Builder) | Deterministic queries; power user UX |
| **8 — Infra Evolution** | M3 (ibis + Connector-X + SQLMesh) | Multi-warehouse; BigQuery/Snowflake |
| **9 — Quality Gates** | M10 (Evals — Braintrust) | CI regression testing on verdict quality |

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

Evals (M10)  ←  needs History ✅ + stable Two-Model Arch (2a) ✅
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
| Materialization | **SQLMesh** (roadmap) | Incremental cache of expensive joins |
| Semantic layer | **dbt** | Single source of truth for metric definitions |
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

**Shipped:** M1 (Semantic Layer), M2a–2c + 2e–2j (Agent hardening, HITL, Direct Query, Routing v2, SQL KB, Error Classification, Schema Intelligence, KB Enrichment), M8 (Frontend Charts, Chart Intelligence, Report UX), M9 (Quick Chat + Chart Engine + Deep Analysis tab), 1e (Metrics Catalog), ER Diagram, Rich Schema Card UI, Global Analytics Rules (32), Hypothesis Expanded Accordion (33), Connection-scoped semantic cache, Paren-aware ROUND rewriter, Schema parser dedup, Timeout 600 s, UI color pass

**Next — Sprint 4 — Provider Flexibility:**
- **M5** Anthropic backend — Claude Sonnet 4.6 as cloud fallback; prompt caching on schema context

**Sprint 5 onward:** M6 + M7 (Security + Observability) → M4 (Prophet) → M11 (Visual Builder) → M3 (Query Engine) → M10 (Evals)

**Deferred:** M6 Security must land before any multi-tenant or enterprise deployment
