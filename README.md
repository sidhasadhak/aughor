<div align="center">
  <img src="web/public/aughor-logo.jpeg" width="120" alt="Aughor" />
  <h1>Aughor</h1>
  <p><strong>Autonomous Intelligence Platform</strong></p>
  <p><em>Your warehouse, always thinking.</em></p>
</div>

---

Aughor connects to your database and never stops learning from it. It builds a living map of your business — entities, relationships, metrics, lifecycles — explores the data on its own, and answers hard analytical questions in plain English with **evidence, citations, and statistical confidence**.

No dashboards to maintain. No SQL to write. No analyst backlog.

## Why Aughor

Most AI data tools are query wrappers — you ask, they translate. Aughor explores **continuously in the background**, forms a business ontology, surfaces domain insights, and is engineered so the numbers it reports are **trustworthy, not just plausible**.

| | SQL Copilots | BI Tools | **Aughor** |
|---|---|---|---|
| Understands the schema automatically | ⚠️ Partial | ❌ Manual | ✅ |
| Explores data on its own to learn your business | ❌ | ❌ | ✅ |
| Answers business questions with evidence + citations | ❌ | ❌ | ✅ |
| Builds a living ontology from real data | ❌ | ❌ | ✅ |
| Deterministic guards against wrong numbers | ❌ | ❌ | ✅ |
| Discovers *when matters* (adaptive time window) | ❌ | ❌ | ✅ |
| Runs fully local | ⚠️ Some | ❌ | ✅ |

## Major capabilities

### 🔭 Autonomous background exploration
The moment you connect, Aughor starts exploring — no prompts — through structured phases: **null-meaning resolution** (event-not-yet vs data gap), **join verification**, **lifecycle mapping** (state machines per entity), **distribution profiling** (catalog stats, no full scans), **cross-table patterns**, and a per-domain **domain-intelligence** curiosity loop with novelty decay. Everything is visible and cancellable in the Activity log.

### 🧠 Auto-built business ontology
A queryable ontology built from your data, not docs you write: **entities** (mapped to tables, with grain + domain), **relationships** (inferred cardinality + join paths), **metrics** (formulas with governance: owner, SLA, quality tests, lineage), **lifecycle states** (terminal vs active, false-positive-guarded), and deterministic **actions**. Rendered as an interactive canvas that refreshes automatically.

### 🕰 Adaptive Temporal Scope — the USP
*We don't ask you when — we discover when matters.* Aughor anchors the analytical window to the data itself, in four tiers:
- **Tier 0** — recency on the trailing edge of *activity* (measure-bearing facts), so a calendar/date-dimension running to 2100 can't drag the window past the last real fact.
- **Tier 1** — narrows to the *current regime* via changepoint detection on the activity-density series.
- **Tier 2** — a cheap full-span macro rollup juxtaposed with the regime window ("up 4× over 8 yrs, now flat").
- **Tier 3** — a cost governor (approximate aggregates + sampling-with-scaling + incremental watermark) for TB-scale warehouses.

### 💬 Grounded NL2SQL + Semantic Compiler
Aughor doesn't hand the raw schema to an LLM and hope. Every question runs a grounding pipeline — **schema-linking**, a MindsDB-style **Data Catalog**, **FK / star-schema join grounding** (prefixed/fused/surrogate keys, fact→dimension routing), **trusted query templates** (data-team-verified, injected authoritatively, marked **Verified**), the **metrics catalog**, and **dialect-aware self-correcting retry**. For the safest intent shapes a **Semantic Compiler** assembles SQL *deterministically* from the verified ontology (typed Intent IR → `synthesize_sql`), bypassing the model entirely.

### 🧱 Query Builder — visual + SQL, one trust-native surface
A drag-to-build query surface that auto-resolves **multi-hop joins** along the studied schema and reconciles catalog/rich-schema names so it works on schema-qualified connections. It's a real **workflow loop**, not a dead-end: **saved queries** persist the full visual spec (table, joins, dimensions, measures, filters, time, HAVING) and reload the *builder*, not just the SQL. First-class **time range + grain** controls (relative presets + custom → `WHERE`; grain → `DATE_TRUNC` + `GROUP BY`), **HAVING** on aggregates, a **distinct-value filter picker** (values inserted as valid SQL literals), and **CSV export**. The SQL pane is a real editor — syntax highlighting + a tokenizer-aware **Format** that never touches strings/identifiers. Laid out as an **Explore** surface — the chart is the hero, with a collapsible **DATA / CUSTOMIZE** control panel (chart-type gallery, color scheme, number format, legend, axis titles) — and the relative time range folds onto the date-dimension chip. The differentiator: the **measure-additivity grain layer surfaces on the metric chips** — sum a per-unit price without `× quantity` and the chip warns with a one-click fix (the same guard that turns a $252M under-count into the correct $503M). Results pin to a **Canvas** for AI investigation.

### 🔬 Deep Analysis — evidence-based answers
For "why did revenue drop 8%?" Aughor runs a LangGraph investigative loop: **decompose → plan & execute → score evidence → synthesise**, producing a ranked-hypothesis brief. Resumable mid-run. Vague, time-less questions ("where are we losing money?") trigger a **cross-sectional weakness scan** instead of a forced temporal frame. Every claim lands in the **Evidence Ledger** (confidence, source SQL, freshness, validate/dispute feedback).

### 🛡 Trust guards — numbers you can act on
The layer that separates Aughor from a plausible-sounding demo. Deterministic, engine-driven guards keep wrong numbers out of the intelligence:
- **Numeral grounding** — every magnitude-bearing figure in a finding is verified against the actual result cells (catches the "2.49M" for a 2.49 cell, the `$3T` product-of-aggregates).
- **Measure-additivity (grain) awareness** — detects from the data whether a measure is *per-unit* (a unit price → `SUM(price × quantity)`) or *per-line* (an already-totalled margin → `SUM(margin)`), so a SUM aggregates at the right grain. Catches the ~50% revenue under-count *and* the margin double-count that come from treating the two the same.
- **Fan-out / symmetric-aggregate guard** (incl. chasm `COUNT(*)` and integer-division-of-aggregates lints), **dataset isolation** (no cross-dataset hallucinated joins), **timestamp typing** (a date-named integer can't pose as a date), **dead-reference memory** (stops re-proposing hallucinated columns), shared **repair-diagnosis branches**.
- **Metric unification** — one canonical, governance-approved formula per metric, schema-filtered so a metric authored for one connection can never leak its (column-mismatched) formula into another's prompt.
- **Narration-inversion guard** — drops/caveats a claim that over-generalises a per-group value into a universal one ("3 orders × 1 item" narrated as "all orders have 3 items").
- **Angle-feasibility + intent-preservation** — won't ask a time-based question of a dateless table, and drops/flags a repair that silently changed the question's meaning.
- **Graceful by contract** — bad inputs, dead dependencies, and crashes surface an error or recover; never a 500, a hang, or a silent-wrong success (locked by a failure-path + fault-injection + crash-recovery test suite).

### 📡 Intelligence surfaces + actionability
One corpus at three altitudes — **Briefing → Hub → Domains** — plus the **Evidence** layer. Findings are actionable: **Monitor**, **Promote to Org**, **Share** (Slack/webhook/Jira), and scheduled **Brief delivery**. From the Activity log, a successful **Run fix** is *saved* as a finding (through the same guards), and **Fix all** repairs the errored set visible under your current filter — never starting a fresh crawl.

### 🔌 Connectors & federation
DuckDB · PostgreSQL · BigQuery · Snowflake · MySQL · local upload (CSV/Parquet/Excel) · S3 · Google Sheets · Stripe / HubSpot / Salesforce · Confluence / Notion. Connections are **pooled** and credentials **Fernet-encrypted at rest**; a virtual **federation** layer joins across sources.

### 📊 Eval suite — measured on real, unseen schemas
NL2SQL quality validated against ground truth, not vibes: TPC-H (5/7), TPC-DS (4/5), ClickBench (10/10), a 53-question golden set, and a **reference-free** real-DB harness (executes-clean + self-consistency + cross-model LLM-as-judge). Generated SQL runs through the *full* pipeline, so the number reflects the product. Model-agnostic via `AUGHOR_CODER_MODEL`.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, LangGraph |
| Frontend | Next.js 16 (App Router, Turbopack), TypeScript, Tailwind |
| Analytics | DuckDB, PostgreSQL |
| LLM runtime | Ollama / Groq / Together / Anthropic (configurable) |
| Statistics · SQL | scipy, statsmodels, numpy · SQLGlot |
| Vector · Observability | Qdrant + ChromaDB · Langfuse, OpenTelemetry |
| State · Packaging | SQLite (history, registry, evidence, audit) · uv |

## Quick start

```bash
git clone https://github.com/sidhasadhak/aughor.git && cd aughor
uv sync                          # Python deps
cd web && npm install && cd ..   # frontend deps
cp .env.example .env             # set your LLM backend + model names
./start.sh                       # → http://localhost:3000
```

Minimal local `.env` (Ollama):

```env
AUGHOR_BACKEND=ollama
AUGHOR_CODER_MODEL=qwen2.5-coder:14b
AUGHOR_NARRATOR_MODEL=qwen2.5-coder:14b
EMBEDDER_BASE_URL=http://localhost:11434/v1
EMBEDDER_MODEL=nomic-embed-text
```

Then click **+ Add** in the sidebar → paste a DuckDB path or PostgreSQL DSN → Aughor starts exploring immediately.

## Project structure

```
aughor/
├── aughor/
│   ├── agent/        # LangGraph investigative loop + ADA phase prompts
│   ├── connectors/   # DuckDB, Postgres, Snowflake, BigQuery, Stripe, Salesforce, …
│   ├── db/           # DatabaseConnection, registry, schema/mat cache
│   ├── evidence/     # Evidence ledger — claims, confidence, feedback
│   ├── explorer/     # Background exploration agent, grounding, fix-persist, cost/watermark
│   ├── knowledge/    # Doc indexer, Confluence/Notion sync, briefing, org intelligence
│   ├── ontology/     # Ontology builder, enricher, validator, store
│   ├── routers/      # FastAPI domain routers (async, SSE)
│   ├── security/     # Safety checker, PII scanner, audit log, query budget
│   ├── semantic/     # Glossary, metrics, compiler, canonical resolver, measure-grain, KB
│   ├── sql/          # SqlWriter, cost governor, fan-out + grain guards
│   └── tools/        # schema-linker, data catalog, profiler, stats
├── evals/            # run_tpch / run_tpcds / run_clickbench / run_golden / run_realdb
├── web/              # Next.js App Router — components, lib (api.ts), design tokens
├── docs/             # Adaptive-temporal-scope, intelligence-unification, rebuild/audit
└── tests/            # pytest suite (600+ unit + integration; failure-path / fault-injection / chaos)
```

## Roadmap & features

- **[ROADMAP.md](ROADMAP.md)** — prioritized backlog, shipped milestones, what's next.
- **[FEATURES.md](FEATURES.md)** — a living reference of every major feature (90+ and counting), how it works, and the files behind it.

## License

MIT
