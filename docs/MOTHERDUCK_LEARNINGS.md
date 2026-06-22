# MotherDuck — Study & Synthesis for Aughor

**Date:** 2026-06-21 · **Status:** research + synthesis, **no code change yet** · **Companion to** [`AGENTIC_ARCHITECTURE.md`](AGENTIC_ARCHITECTURE.md)

We deep-studied MotherDuck's docs (AI Data Analysis, How-to Guides, Dives, Concepts/Hypertenancy/
Architecture, Cookbooks, the Custom-AI-Agent guide, the MCP reference, DuckLake, and 2025–26 release
notes), then **verified every load-bearing claim about Aughor against the actual code** so the
recommendations sit on facts, not guesses. This doc is the durable record of *what MotherDuck built*,
*how*, *where Aughor already stands*, and *what to borrow* — and it feeds the backlog in
[`../ROADMAP.md`](../ROADMAP.md) §3 and the phases in [`AGENTIC_ARCHITECTURE.md`](AGENTIC_ARCHITECTURE.md) §6–7.

> **Framing.** MotherDuck and Aughor are converging on the same destination — **agentic analytics you
> can trust** — from opposite ends. MotherDuck is an *engine* company building **up** into agents: thin
> agents (text-to-SQL + viz), deep infra (per-user DuckDB compute, a 28-tool MCP server, a DuckLake
> catalog). Aughor is an *intelligence* company building **down** into a fleet: deep agents (governed
> metrics, multi-step root-cause ADA, autonomous Explorer, Briefings) on infra it already mostly has
> (JobKernel + event journal + Trust Receipts). The play is **not** to "become MotherDuck" — it's to
> borrow the two surfaces that make a fleet legible and addressable (the MCP tool contract and the
> Flights job-API shape), and to take their published evidence as validation of Aughor's moat.

---

## 0 · The one finding that matters most

**MotherDuck's own benchmark says the governed semantic layer is what wins — which is Aughor's entire bet.**

On their **DABstep** payment-analytics benchmark, an agent over raw tables improved only incrementally
with column comments, climbed to ~**93.2%** with hand-built table macros named as the answers, and
reached **100% only when domain knowledge moved *out* of the warehouse into a governed semantic layer**
over raw tables. dbt's independent 2026 benchmark corroborates the direction (text-to-SQL ~84–90% vs
semantic-layer ~98–100%), with the decisive qualitative point:

> **A semantic-layer failure is an error message. A text-to-SQL failure is a plausible wrong answer.**

That is the exact thesis behind Aughor's metrics catalog + ontology + additivity/fan-out/chasm guards +
Trust Receipts. An *engine* company — one that would prefer the answer to be "just call our `prompt_sql`"
— published evidence that you need the governed layer anyway. Two consequences:

1. Aughor is **ahead on the very axis MotherDuck is marketing toward** ("every AI answer shows its SQL" =
   Aughor's Trust Receipts, except Aughor adds provenance, re-validate, and the Finding Dossier).
2. Aughor should **prove this with a scored ablation** (governed-layer vs raw NL2SQL on its own DBs) —
   see Recommendation R4. It is the cheapest way to make the moat measurable.

*(Sourcing caveat: the exact DABstep percentages are from MotherDuck-owned search snippets — their blog
pages 500 on automated fetch. Directionally solid; re-verify the precise tier numbers before quoting
externally.)*

---

## 1 · What MotherDuck built (the parts that matter to us)

### 1.1 AI as a SQL primitive, not an orchestration layer
MotherDuck embeds the LLM **inside the query engine** as Azure-OpenAI-backed scalar functions:

- **`prompt(text, model, temperature, reasoning_effort, return_type, struct, struct_descr, json_schema)`**
  — runs the model **once per row**; three mutually-exclusive structured-output modes (`return_type` |
  `struct` | `json_schema`); **NULL-on-failure** so one bad row never tanks a batch query. Default
  `gpt-4o-mini`/temp 0.1; GPT-5 family uses `reasoning_effort` instead of temperature.
- **`embedding(text, model := 'text-embedding-3-small')`** → `FLOAT[512]` (or `-large` → `FLOAT[1024]`),
  max 2048 chars, **not cached** (you materialize it). Semantic search = `embedding()` +
  `array_cosine_similarity()`; **no ANN index** (DuckDB VSS/HNSW is unsupported in MD cloud), so it's an
  exact brute-force cosine scan — which is why their cookbooks lead with **hybrid BM25-prefilter → cosine-rerank**.
- **SQL-Assistant family** — `prompt_sql` (NL→SQL text), `prompt_query` (NL→SQL **and executes**,
  read-only), `prompt_fixup` (whole-query repair), `prompt_fix_line` (single-line repair), `prompt_explain`,
  `prompt_schema` (sampled prose schema digest). All scope schema context via `include_tables`.
- **In-UI**: **Edit** (NL→SQL on a selection) and **FixIt** (inline error repair, auto-re-executes).
  Notably, **Instant SQL** (live results-as-you-type) is **DuckDB-Wasm + AST parsing, zero LLM** — a
  deliberate "not everything fast needs an LLM" stance.

### 1.2 Their agent-building doctrine is deliberately anti-framework
From the *Custom AI Agent Builder's Guide*:

- **One `query` tool + heavy schema grounding + a tight validate-before-execute loop.** The linchpin is
  **`try_bind(sql)`** → returns a typed **`{ok | parser | binder}`** (`parser` = syntax, `binder` =
  missing object) without executing; feed the typed error back into ≤3 repair attempts.
- **Grounding** = `COMMENT ON TABLE/COLUMN` (business semantics in the catalog) + a `prompt_schema`
  prose digest + **top-5 retrieved function docs** (semantic search over a shipped `function_docs.jsonl`)
  + an embedded `query_guide.md` of DuckDB idioms.
- **Eval** = fixed question buckets (simple / complex / edge-cases) scored on correctness + accuracy +
  perf, with a **failure-mode → fix table**.
- **Guardrails** = connection-level read-only (read-scaling tokens that physically can't write),
  per-tenant **service accounts** via shares, and **zero-copy clones** for safe write-sandboxing.

### 1.3 The whole 2025–26 arc is "agent-native"
- **MCP server** (`https://api.motherduck.com/mcp`) — **28 tools**: catalog (`search_catalog`,
  `list_tables`, `list_columns`), `query` / `query_rw` (read-only by *excluding* `query_rw`),
  `ask_docs_question`, plus full CRUD for Dives and Flights. The agent *client* (Claude Desktop/Code,
  ChatGPT, Cursor) owns the loop.
- **Dives** — agent-built, **versioned, live-querying, embeddable** React data-apps authored
  conversationally ("add a filter," "switch to bar chart"); query live data on each load.
- **Flights** — agent-built **scheduled Python ETL** with run history + logs + cancel
  (`run_flight`/`list_flight_runs`/`get_flight_run_logs`/`cancel_flight_run`). Dives + Flights = an agent
  that ingests → transforms → visualizes with no separate BI/orchestration tool.
- **Agent Skills** — an open-source, **progressive-disclosure** context catalog (utility → workflow →
  use-case) that teaches a coding agent *judgment* (dialect, safety, orchestration), kept **separate from
  MCP's live tools**.

### 1.4 The infra that makes per-agent autonomy cheap
- **Hypertenancy** — every user / tenant / **agent** gets a dedicated single-node DuckDB ("Duckling,"
  ~100ms–1s cold start for small sizes, 5 sizes Pulse→Giga, scale-to-zero). Isolation is *structural*, so
  **cost is attributable per tenant/agent for free**, and a runaway agent query "can't blow up your bill
  or take down your warehouse." *(Exact vCPU/RAM per size is not published; the 1/4/8/20/60 ratio is
  inferred from the dollar rates.)*
- **Dual execution** — routes query stages between in-browser/local DuckDB and cloud.
- **DuckLake** — keeps **all catalog metadata in a SQL DB** (vs Iceberg's metadata files) → ms-latency
  metadata, **atomic multi-table commits**, cheap snapshots + **time-travel (`AT VERSION => N`)**.
- **Customer-facing analytics** — per-tenant service-account + DB + Duckling; **read-scaling tokens**
  (SELECT-only) + `session_name` cache affinity to serve many concurrent end users.

---

## 2 · Where Aughor already stands (grounded in code)

The sub-agents' first guesses about Aughor were wrong in three important places; the code says:

| Capability | MotherDuck | **Aughor today (verified)** | Verdict |
|---|---|---|---|
| Governed semantic layer | views + macros; no fan-out/additivity guards | metrics catalog + ontology + north-star + additivity/fan-out/chasm guards + `unified_metric_grounding` | **Aughor ahead** (MD's data validates the bet) |
| Trust / provenance | "shows its SQL" | per-run **Trust Receipts** + re-validate + Finding Dossier (`kernel/ledger.py:receipt`) | **Aughor ahead** |
| Multi-step reasoning | text-to-SQL + viz (thin) | ADA: intake→plan→query→**score-evidence**→synthesize; autonomous Explorer | **Aughor ahead** |
| Validate-before-execute | `try_bind` → typed `{ok\|parser\|binder}` | `dry_run()` = EXPLAIN/sqlglot (≡ try_bind) + **regex** error classification + DuckDB candidate-bindings → repair (`sql/writer.py`, `tools/error_classifier.py`) | **Even** — Aughor has the behavior; MD has a cleaner *typed* signal |
| Embeddings / retrieval | `embedding()` in-SQL; no ANN; hybrid recipe | **Qdrant + `nomic-embed-text` (768-d)**, per-conn KB + org intelligence, cosine top-k (`semantic/connection_kb.py`, `semantic/embedder.py`) | **Even** — Aughor has a layer; MD has sharper recipes (hybrid/rerank/HyDE) |
| Scored eval harness | DABstep/ACME ×N, accuracy %, failure-mode table | live small-n missimi eval; Spider 2.0/LiveSQLBench **planned** | **MD ahead on rigor** |
| External agent surface (MCP) | 28-tool MCP, multi-client | **none** — LangGraph-internal only; MCP item **deferred** in ROADMAP | **MD ahead — recognized gap** |
| Job kernel exposed as tools | Flights: `run`/`list_runs`/`get_run_logs`/`cancel` | kernel API **exists** (`submit`/`cancel`/`jobs_where`/`events`/`receipt`) but **no `/jobs` REST surface** (only `/events/stream` SSE) | **MD ahead on surface; Aughor has the engine** |
| Per-tenant compute isolation + cost | structural (Duckling per tenant/agent) | shared-warehouse; `DuckDBConnection` **already speaks `md:`/S3/GCS** (`db/connection.py`); **no cost/token metering** anywhere | **MD ahead** |
| Interactive artifacts | Dives (versioned, embeddable, live) | briefings + validated `chart_config` (server-gen) | **MD ahead on format; Aughor ahead on trust** |

**Net:** Aughor is ahead on *what MotherDuck explicitly says you need but doesn't fully build* — a
governed semantic layer with trust guards, per-run provenance, and a multi-step root-causing agent. Aughor
is behind on infra/distribution surfaces — MCP, eval rigor, compute isolation + cost — **all of which are
cheap to close because the substrate already exists.**

---

## 3 · Recommendations

Tiered. Each names the MotherDuck learning, what Aughor *already* has (so we build the delta), and the
Agentic-roadmap phase it serves. Backlog entries land in [`../ROADMAP.md`](../ROADMAP.md) §3.

### Tier 1 — sharpen the already-planned Phase 0 + 1

- **R1 · Cost/compute metering in the Trust Receipt + job row** *(NEW; Agentic Phase 0)* — confirmed
  absent (`stats.py`/`connection.py` log query duration only; no token/cost anywhere). Stamp every
  job/agent-run with LLM tokens (per node) + warehouse rows/bytes scanned + wall-time, into
  `kernel/ledger.py`'s receipt + job row. **You cannot enforce the per-agent budgets the charter calls for
  without this**, so it's a Phase-0 prerequisite, not a nice-to-have. MotherDuck makes cost *structural*
  (CU-seconds/Duckling); Aughor makes it *provenance*.

- **R2 · A `/jobs` REST + tool surface over the existing ledger API** *(Agentic Phase 1)* — the kernel
  already exposes `jobs_where`/`job_get`/`cancel`/`events`/`receipt`; only the HTTP/tool surface is missing
  (today just `/events/stream` SSE). Add `list`/`get`/`logs`/`cancel` named like MotherDuck's **Flight**
  tools. **This one thin layer is simultaneously the Phase-1 Fleet view backend AND the future MCP job
  tools (R5).**

- **R3 · Typed SQL-error taxonomy in the repair loop** *(Agentic Phase 2; enriches the existing
  "error-registry enrichment" backlog item)* — Aughor's `_make_diagnosis` already classifies ~10 patterns
  by regex and there's a `tools/error_classifier.py`; promote that to a typed enum
  (`parser | binder | semantic | runtime`, à la MD's `try_bind`) and **route repair by type**: `parser`→
  regen; `binder`→ re-run schema-linking + `_rescope_sql_to_schema` (already exists); `semantic`→ re-plan.
  Surface error-type + attempt count in the receipt. This is the natural job of the **Verifier** when ADA's
  nodes split into SQL-Engineer ⇄ Verifier.

- **R4 · A semantic-layer *ablation* eval** *(complements the planned Spider 2.0 / LiveSQLBench + the
  missimi eval)* — replicate MotherDuck's "raw NL2SQL → governed-layer" curve on Aughor's own DBs and show
  the additivity/fan-out guards buy the last points **safely** (their macros have no fan-out protection →
  "plausible wrong answer"; Aughor's guards turn that into a caught error). This is distinct from the
  execution-match Spider work — it's the study that **makes the moat measurable**.

### Tier 2 — the missing external surface

- **R5 · An MCP server that exposes *governed intelligence* tools, not raw SQL** *(enriches the existing
  "⬜ MCP server (deferred)" backlog item)* — MD's entire distribution strategy is MCP; Aughor has none.
  The **+1 / leapfrog**: where MD exposes `query`/`list_tables`, Aughor exposes `ask` (NL→grounded answer
  **+ receipt**), `deep_analysis` (kick off ADA), `get_metric` (governed value), `list_findings`,
  `get_briefing`, `explore`, plus the `jobs` tools from R2. MotherDuck makes the *client* smart; **Aughor
  makes the *tool* smart**, and the Trust Receipt rides along inside any agent client. The Superset study
  already specced the plumbing (FastMCP + per-tool Pydantic + layered auth + streaming) — this adds the
  *tool-surface design*.

### Tier 3 — architecture & product directions

- **R6 · Per-workspace compute isolation + an embedded DuckDB lane** *(complements `#12` tenancy)* — the
  hypertenancy lesson: a heavy Explorer/Briefing run shouldn't starve another workspace's interactive
  query. `DuckDBConnection` already speaks `md:`, S3/GCS, and local federated execution, so: (a) make
  **MotherDuck a first-class connector** (read-scaling/`session_name` aware) as an optional isolated serving
  backend; (b) run high-frequency low-volume queries (KPI tiles, governed-metric lookups, briefing tiles)
  **in-process via DuckDB** (dual-execution style) instead of round-tripping a remote warehouse.

- **R7 · Sharpen the existing Qdrant layer with MD's retrieval recipes** *(complements the noted
  "re-index industry KB into Qdrant" follow-up)* — add **hybrid BM25-prefilter → cosine-rerank** (better
  recall than pure top-k cosine), **LLM-as-judge rerank** for Explorer finding/triage ranking, and **HyDE**
  to seed the Explorer's `generate_hypotheses` step (memory notes it's un-wired). Ensure metric/ontology
  *definitions* + past findings are embedded so the metric-consistency (UNIFY) path retrieves the canonical
  metric before re-deriving.

- **R8 · Leapfrog ideas to keep on the board** —
  - **AI-as-a-governed-SQL-operator**: emit `prompt()`/`embedding()` inside generated SQL on DuckDB/MD
    targets for row-wise classification the warehouse can't do, but **wrapped in a receipt, model-pinned,
    `json_schema` + temp-0 for reproducibility, cost-gated** → "AI columns with provenance" (a leapfrog over
    MD's ungoverned per-call functions).
  - **Governed Dives**: conversational, immutably-versioned (à la DuckLake `AT VERSION`), embeddable
    briefings **bound to the semantic layer + receipt** — "Dives that obey your metric definitions and show
    their receipt."
  - **Agent-Skills packaging**: formalize per-specialist context (Scout/Curator/Analyst) + the existing
    industry-KB steering as progressive-disclosure skills.
  - **DuckLake snapshot-pinned receipts**: pin every Briefing/Finding to a catalog snapshot id so
    drill-down/re-validate is a $0 metadata read against an immutable version (turns the Finding Dossier
    into a true time-machine).

---

## 4 · What we deliberately do NOT need from MotherDuck

- **We don't need to become a warehouse.** Aughor's warehouse-agnosticism (Postgres/BigQuery/SQLite/DuckDB)
  is a feature MD can't match — it serves customers who won't move off their warehouse. MD-as-backend is an
  *optional serving tier* (R6), not the foundation.
- **AI-as-a-SQL-primitive is optional, not core.** It's a useful row-wise tool on DuckDB targets (R8), but
  Aughor's intelligence lives in the agent + semantic layer, not in a columnar `prompt()`.
- **The Instant-SQL lesson, kept:** MD made their fastest-feedback feature with **zero AI** (Wasm + AST).
  Aughor's AST-level validation/preview (`sql/readonly.py`, `dry_run`) should likewise pre-empt repair
  loops deterministically and for free before reaching for the LLM.

---

## 5 · Sourcing & uncertainty

- All `motherduck.com/blog/*` pages **500 on automated fetch** (bot-blocking). Blog-derived specifics
  (DABstep tier percentages, "your data model is the semantic layer," Flights) are **snippet-sourced** from
  MotherDuck-owned search results — directionally reliable; re-verify exact numbers before external use.
- Duckling **vCPU/RAM per size** and explicit CU multipliers are **not published**; the 1/4/8/20/60 ratio
  is inferred from the dollar rates. **Cold-start** figures are inconsistent across pages (~1s vs ~100ms vs
  "a few minutes" for Mega/Giga) — reconcile as small≈100ms–1s, large≈minutes.
- The agent-builder guidance is MotherDuck's **advisory how-to**, not a guarantee of their internals.
  `try_bind`/`prompt_schema`/chunking macros are DuckDB/MD-specific — Aughor would re-implement equivalents
  per dialect (Postgres `EXPLAIN`/`PREPARE`; pgvector/BigQuery `VECTOR_SEARCH`). The *patterns* port; the
  *functions* don't.

### Citations (primary docs fetched)
- AI functions: `…/sql-reference/motherduck-sql-reference/ai-functions/` (`prompt`, `embedding`,
  `sql-assistant/*`)
- Agent building: `…/key-tasks/ai-and-motherduck/building-analytics-agents/`
- MCP reference (28 tools): `…/sql-reference/mcp/` · getting-started: `…/getting-started/mcp-getting-started/`
- Dives: `…/key-tasks/ai-and-motherduck/dives/` · Agent Skills: `…/agent-skills/` +
  `github.com/motherduckdb/agent-skills`
- Concepts: `…/concepts/hypertenancy/`, `…/concepts/architecture-and-capabilities/`,
  `…/about-motherduck/billing/duckling-sizes/`
- Platform: `…/getting-started/data-warehouse/`, `…/getting-started/customer-facing-analytics/`,
  `…/key-tasks/customer-facing-analytics/3-tier-cfa-guide/`, `…/integrations/file-formats/ducklake/`,
  `…/about-motherduck/release-notes/`
- Cookbooks/how-to: `…/key-tasks/ai-and-motherduck/text-search-in-motherduck/`, `…/mcp-workflows/`,
  `…/key-tasks/flights/build-daily-briefing-flight-and-dive/`
- Third-party corroboration: `docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026`,
  `siliconangle.com` (2026-06-10, Flights)
