# 🧠 Aughor — Autonomous Data Analyst

> *Your warehouse, always thinking.*

Aughor is an **autonomous data analyst** that connects to your database and never stops learning from it. It builds a living map of your business — entities, relationships, metrics, lifecycles — and uses that map to answer hard analytical questions in plain English.

No dashboards to maintain. No SQL to write. No analyst backlog.

---

## ✨ What makes Aughor different

Most AI data tools are query wrappers — you ask, they translate. Aughor goes further: it **explores your data continuously in the background**, forming a business ontology, surfacing domain insights, and staying ready to answer any question with full evidence and citations.

| | SQL Copilots | BI Tools | **Aughor** |
|---|---|---|---|
| Understands your schema automatically | ⚠️ Partial | ❌ Manual | ✅ |
| Runs queries on its own to learn your data | ❌ | ❌ | ✅ |
| Answers business questions with evidence | ❌ | ❌ | ✅ |
| Knows entity lifecycles & business rules | ❌ | ❌ | ✅ |
| Fixes its own SQL errors | ❌ | ❌ | ✅ |
| Runs fully local | ⚠️ Some | ❌ | ✅ |

---

## 🚀 Features

### 🤖 Autonomous Background Exploration

The moment you connect a database, Aughor starts exploring — silently, in the background, without any prompts from you. It works through a structured sequence of phases:

- **Null meaning resolution** — distinguishes "event not yet occurred" from "data quality gap" for every nullable column
- **Join verification** — validates FK relationships and measures their referential integrity
- **Lifecycle mapping** — extracts state machines for entity tables (orders: pending → shipped → delivered → returned)
- **Distribution profiling** — detects skew, outliers, and shape for numeric columns
- **Cross-table pattern discovery** — finds correlated columns, shared value sets, and structural anomalies across tables
- **Domain intelligence** — an adaptive curiosity loop that fires business questions per domain (Commerce, Finance, Operations, Marketing) and records findings as structured insights

Schema phases fire as fast as the DB allows. The domain intel phase self-throttles (one query per 5 seconds) to keep the DB comfortable and give you time to stop between queries.

### 🧩 Business Ontology — Auto-Built

Aughor builds a **queryable business ontology** from your schema, not from documentation you write:

- **Entities** — `Customer`, `Order`, `Product`, `Inventory` — mapped to source tables with descriptions, primary keys, grain, and domain assignment
- **Relationships** — `Customer places Order` (one-to-many), `Order contains Product` (many-to-many) — with inferred cardinality and join paths
- **Metrics** — revenue, AOV, retention rate — extracted from schema patterns and enriched with business definitions
- **Lifecycle states** — terminal vs. active states per entity, extracted from real data distributions
- **Actions** — `get_orders_for_customer`, `get_revenue_trend` — deterministic SQL templates generated from entity relationships and auto-expanded at query time

The ontology is displayed as an interactive canvas and refreshes automatically as the schema evolves.

### 💬 Chat — Answer First, Explain Later

Ask anything in plain English. Aughor writes SQL, runs it, interprets the result, and streams back a structured answer with:

- **Auto-charts** (Observable Plot) — time series, bar charts, scatter plots — chosen automatically based on result shape
- **Thinking trace** — see every reasoning step, SQL draft, and correction
- **Statistical layer** — STL decomposition, z-score anomaly detection, Mann-Whitney significance tests auto-attached to every result
- **Self-correction** — if the SQL fails, Aughor reads the actual error (including DuckDB's candidate column bindings), resolves table aliases, and retries with a targeted fix
- **Citation pinning** — every claim in the answer is linked to the exact SQL that produced it

Chat sessions are persisted and fully restorable.

### 🔍 Investigative Mode — Evidence-Based Answers

For complex questions ("Why did revenue drop 8% last month?"), Aughor runs a full **LangGraph investigative loop**:

1. **Decompose** — break the question into sub-hypotheses
2. **Plan & Execute** — write and run SQL for each hypothesis
3. **Score Evidence** — weight findings by statistical confidence and sample size
4. **Synthesise** — produce a structured report with ranked hypotheses, supporting data, and caveats

Investigations are resumable — pause mid-run, switch tabs, come back later.

### 📊 Domain Intelligence Panel

Per-domain insight tracking with budget control:

- Findings grouped by business domain (Commerce, Finance, Operations, Marketing)
- Coverage angle tracking — volume, value, retention, basket composition, seasonality
- Budget bar showing queries used vs. cap
- **+5 queries** button to extend exploration for a domain after the base budget is spent
- Novelty decay detection — stops automatically when new queries produce diminishing information

### 🗄️ Multi-Database Support

- **DuckDB** — local files, in-memory, remote S3 via `duckdb://`
- **PostgreSQL** — any Postgres-compatible database
- Credentials encrypted at rest with Fernet symmetric encryption (key auto-generated and stored in `data/.hermes_key`, or via `HERMES_SECRET_KEY` env var)
- Per-connection schema name scoping
- All connections deletable — no locked-in defaults

### 🧠 Two-Model Architecture

Aughor uses two separate LLM roles, independently configurable:

| Role | Default | Purpose |
|---|---|---|
| **Analyst** | `qwen2.5-coder:14b` (Ollama) | Reasoning, hypothesis generation, synthesis |
| **Coder** | `qwen2.5-coder:14b` (Ollama) | SQL generation and error correction |

Supports: **Ollama**, **LM Studio**, **OpenAI**, any OpenAI-compatible endpoint. Switch models in `.env` without touching code.

### 📚 Semantic Layer

- **Business Glossary** — YAML file (`data/glossary.yaml`) with table descriptions, grain, column definitions, known values, join hints, and caveats — injected into every LLM context
- **Auto-Seed** — LLM auto-generates descriptions for unannotated tables on first schema load; results written back to YAML (idempotent, disable with `HERMES_AUTOSEED=false`)
- **dbt Integration** — reads `manifest.json` to pull model descriptions, column-level metadata, and source documentation
- **Metrics Catalog** — named business metrics with formulas, definitions, and consistency checks
- **SQL Knowledge Base** — curated pattern library (`data/kb/`) injected as context for SQL generation

### 🔎 Schema Intelligence

- **Join inference** — infers FK relationships from column name patterns, cardinality analysis, and value overlap; stores confidence scores
- **Schema fingerprinting** — detects schema drift between runs
- **Vector search** — Qdrant-powered semantic search over table and column descriptions
- **ER diagram** — auto-generated Mermaid diagram of your schema with join paths

### 🕐 Activity Log

Real-time feed of every exploration query:

- Thinking trace → SQL → result observation per episode
- Phase labels (null_meaning, join_verification, domain_intel, …)
- Stop / Resume / Restart controls that survive tab switches
- JSONL episode log per connection (`data/episodes_{id}.jsonl`) — every query is a training-quality `(think, sql, observation)` tuple

### 🔒 Privacy First — Runs Fully Local

Aughor is built to run **entirely on your machine**:

- Ollama or LM Studio for local LLM inference — no data leaves your network
- DuckDB for embedded analytics — no external query engine
- SQLite for state, history, and credential storage — no cloud database
- All data stays in the `data/` directory

Cloud LLM endpoints (OpenAI etc.) are opt-in via `.env`.

---

## 🛠️ Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, LangGraph |
| Frontend | Next.js (App Router), TypeScript |
| Analytics | DuckDB, PostgreSQL |
| LLM Runtime | Ollama / LM Studio / OpenAI-compatible |
| Statistics | scipy, statsmodels, numpy |
| SQL Parsing | SQLGlot |
| Vector Search | Qdrant |
| State | SQLite (LangGraph checkpoints, history, registry) |
| Packaging | uv |

---

## ⚡ Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Node.js 18+ and npm
- [Ollama](https://ollama.com/) with `qwen2.5-coder:14b` and `nomic-embed-text` pulled

```bash
# Pull models
ollama pull qwen2.5-coder:14b
ollama pull nomic-embed-text
```

### 1. Clone & install

```bash
git clone https://github.com/sidhasadhak/hypothesis-engine.git
cd hypothesis-engine

# Install Python deps
uv sync

# Install frontend deps
cd web && npm install && cd ..
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set ANALYST_BASE_URL, CODER_BASE_URL, model names
```

Minimal `.env` for local Ollama:

```env
ANALYST_BASE_URL=http://localhost:11434/v1
ANALYST_MODEL=qwen2.5-coder:14b
CODER_BASE_URL=http://localhost:11434/v1
CODER_MODEL=qwen2.5-coder:14b
EMBEDDER_BASE_URL=http://localhost:11434/v1
EMBEDDER_MODEL=nomic-embed-text
```

### 3. Start

```bash
./start.sh
```

Or separately:

```bash
# Backend
uv run uvicorn aughor.api:app --reload --port 8000

# Frontend
cd web && npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 4. Connect your database

Click **+ Add** in the sidebar → paste a DuckDB file path or PostgreSQL connection string → Save. Aughor starts exploring immediately.

---

## 📁 Project Structure

```
aughor/
├── aughor/
│   ├── agent/          # LangGraph investigative loop (investigate, explore, verify)
│   ├── db/             # DatabaseConnection, registry, schema cache
│   ├── explorer/       # Background schema exploration agent (phases 3–8)
│   ├── llm/            # LLM provider abstraction (Ollama / OpenAI)
│   ├── ontology/       # Ontology builder, enricher, models, store
│   ├── semantic/       # Glossary, dbt, embedder, KB loader
│   ├── sql/            # SqlWriter — centralised SQL generation & self-correction
│   ├── tools/          # Stats, profiler, schema, prior analyses, materializer
│   └── api.py          # FastAPI app — all REST + SSE endpoints
├── web/
│   ├── app/            # Next.js App Router pages
│   └── components/     # ActivityLog, ChatPanel, OntologyCanvas, DomainIntelPanel, …
└── data/               # Persisted state (connections, history, episodes, ontology cache)
```

---

## 🗺️ Roadmap

### ✅ Shipped

| Feature | Notes |
|---|---|
| LangGraph investigative loop | Decompose → plan → score evidence → synthesise |
| SQL self-correction (SqlWriter) | Alias resolution, DuckDB candidate bindings, multi-attempt repair |
| Statistical evidence engine | STL decomposition, z-score, Mann-Whitney |
| Multi-database connections | DuckDB + PostgreSQL, Fernet-encrypted at rest |
| FastAPI SSE streaming | Node-level events, frontend reducer |
| Two-model architecture | Analyst + Coder LLMs, independently configurable |
| Business Glossary + Auto-Seed | YAML semantic layer, LLM-generated descriptions |
| dbt integration | Reads manifest.json for descriptions and metadata |
| Metrics Catalog | Named metrics with formulas and divergence detection |
| Vector search over schema | Qdrant-powered semantic table/column search |
| Investigation history | SQLite, citation pinning, fully restorable sessions |
| Schema intelligence | Join inference, fingerprinting, ER diagram |
| Business Ontology | Entities, relationships, metrics, lifecycle states, actions — auto-built |
| Background Schema Explorer | Phases 3–8: null meanings → joins → lifecycle → distributions → patterns → domain intel |
| Domain Intelligence Panel | Per-domain findings, budget control, novelty decay |
| Activity Log | Real-time episode feed, stop/resume/restart, JSONL logging |
| Chat with sessions | Streaming chat, auto-charts (Observable Plot), session restore |
| Local-first inference | Full Ollama / LM Studio support — no cloud required |

### 🔜 Coming Next

| Feature | Why |
|---|---|
| **Column-level lineage** | Trace any value back to its source via SQLGlot parse trees |
| **dbt DAG traversal** | Downstream impact analysis — "what breaks if this source changes?" |
| **Drift detection** | Alert when schema, freshness, or value distributions shift |
| **Multi-source federation** | Register multiple databases under one logical organisation view |
| **Structural question mode** | Answer graph-traversal questions ("show me the full order lifecycle") |
| **Scheduled ontology refresh** | Keep the business map current on a user-defined cadence |
| **Export to dbt / Lightdash** | Push enriched ontology back to your semantic layer |
| **Slack / webhook alerts** | Surface anomalies and drift events outside the UI |

---

## 🤝 Contributing

Issues and PRs welcome. The codebase is structured to make adding new exploration phases, LLM providers, or database adapters straightforward — each is an isolated module with a clear interface.

---

## 📄 License

MIT
