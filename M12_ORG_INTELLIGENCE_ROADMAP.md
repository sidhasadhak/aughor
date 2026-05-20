# Milestone 12 — The Organisation Intelligence Layer

**Proposal for: `sidhasadhak/hypothesis-engine` (Aughor / `hermes/`)**
**Author intent:** turn Aughor from an **autonomous analyst** into an **organisation intelligence engine** — a continuously-running, queryable model of how the business actually operates as told by its data.

This document has two parts:

1. **The Roadmap** — what to build, why, how it integrates with the 29 shipped features, the file-level architecture, and the sprint sequencing.
2. **The Coding-Agent Prompt** — a single, copy-pasteable prompt you can hand to a frontier coding agent (Claude Code, Cursor, Devin, etc.) that already has the repo cloned and the existing roadmap in context.

---

## Part 1 — The Roadmap

### 1.1 Why this milestone exists

Aughor today is a brilliant **per-question** analytical engine. You ask "why did revenue drop 8%?", it forms hypotheses, writes SQL, scores evidence, synthesises a report. It has a rich semantic layer (glossary + dbt + metrics catalog + 252 KB patterns) and a schema-intelligence layer (join inference + fingerprinting + ER diagram).

What it does **not** have yet is a persistent, continuously-updated **map of the organisation itself**. The kind of map that lets you ask:

- *"What happens to a customer record after they place their first order?"* — an **entity-lifecycle walk**
- *"Which dashboards break if the `vendor_invoices` source stops loading?"* — a **downstream-impact walk**
- *"Show me every place where we calculate gross margin and how they differ."* — a **calculation-divergence diff**
- *"What changed in the warehouse this week and what depends on those changes?"* — a **drift-and-impact report**
- *"Which tables exist that nobody actually queries?"* — a **zombie-table audit**

These are not investigative questions (no hypotheses, no root cause) and they are not direct queries (no single SQL pass answers them). They are **structural** questions answered by traversing a knowledge graph of the organisation's data systems.

This milestone builds that graph, keeps it current, and exposes it to the agent as a fourth question class — **structural mode** — alongside Direct (M2e), Investigate (M1), and Quick Chat (M9).

### 1.2 What's already there vs. what's missing

| Capability | Status | Gap |
|---|---|---|
| Schema metadata ingestion | ✅ via `DatabaseConnection.get_schema()` | Single-connection only; no cross-warehouse view |
| Glossary / dbt descriptions | ✅ M1a, M1a+, M1b | dbt **descriptions** are read; dbt **model→model dependencies** are not |
| Schema vector search | ✅ M1c | Per-table; no relational/graph traversal |
| Metrics Catalog | ✅ M1e | Formulas stored; no detection of *divergent* formulas across SQL in the wild |
| Join inference | ✅ M2i-i | Static FK graph; not a queryable structure |
| Schema fingerprinting | ✅ M2i-ii | Used for cache; not used as a drift-signal source |
| ER diagram | ✅ M2g (Mermaid) | Visual only; not traversable as a graph |
| SQL self-correction | ✅ | Per-query; doesn't extract column-level lineage from the SQL it generates |
| **Column-level lineage** | ❌ | Missing |
| **dbt DAG ingestion (model→model)** | ❌ | Missing |
| **Entity lifecycle state machines** | ❌ | Missing |
| **Data profiling (nulls, cardinality, freshness, distributions)** | ❌ | Missing |
| **Drift detection (schema, freshness, distribution)** | ❌ | Missing |
| **Graph-traversal tool layer for the LLM** | ❌ | Missing |
| **Structural question router** | ❌ | Missing |
| **Cross-source entity resolution** | ❌ | Missing |

The good news: **everything that's missing builds on top of what exists**. No teardown. The new milestone is additive.

### 1.3 The five layers of M12

```
                          ┌──────────────────────────────────────────┐
                          │   M12e — Structural Question Router      │
                          │   ("flow" / "impact" / "definition"      │
                          │    / "drift" / "calculation-diff")       │
                          └──────────────────┬───────────────────────┘
                                             │
                          ┌──────────────────▼───────────────────────┐
                          │   M12d — Graph-Traversal Tool Layer      │
                          │   trace_downstream_impact(),             │
                          │   get_entity_lifecycle(),                │
                          │   compare_calculations(),                │
                          │   find_business_rule(),                  │
                          │   describe_change_since(date)            │
                          └──────────────────┬───────────────────────┘
                                             │
                          ┌──────────────────▼───────────────────────┐
                          │   M12c — Organisation Knowledge Graph    │
                          │   tables, columns, lineage edges,        │
                          │   entity lifecycles, calculation sites,  │
                          │   domain assignments, drift events       │
                          └──────────────────┬───────────────────────┘
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              │                              │                              │
   ┌──────────▼─────────┐         ┌──────────▼─────────┐         ┌──────────▼─────────┐
   │ M12a — Lineage     │         │ M12b — Profiler &  │         │ M12a — Multi-Source│
   │ Ingestor           │         │ Drift Sentinel     │         │ Federation         │
   │ dbt manifest +     │         │ scheduled scans:   │         │ register multiple  │
   │ SQLGlot column-    │         │ nulls, cardinality,│         │ connections under  │
   │ level lineage      │         │ freshness, value-  │         │ one logical org    │
   │ from query history │         │ distributions      │         │ ("Prod warehouse", │
   │                    │         │                    │         │  "CRM", "Stripe")  │
   └────────────────────┘         └────────────────────┘         └────────────────────┘
```

Each layer is shippable independently and provides value on its own.

### 1.4 The layers in detail

#### M12a — Lineage Ingestor + Multi-Source Federation

**Goal:** Build the edges of the graph. Where does data come from, where does it go, and how is it transformed along the way?

**Two sub-features, shipped together because they share the lineage extractor:**

**M12a-i — dbt DAG ingestion (model→model + column-level via `compiled_sql`).** The existing `hermes/semantic/dbt.py` parses `manifest.json` for *descriptions only*. Extend it to also extract:

- The `depends_on.nodes` list per model → `LineageEdge(parent_model, child_model, edge_type="dbt_ref")`
- The `compiled_sql` (or `raw_sql` as fallback) of every model → run through **SQLGlot's lineage API** (`sqlglot.lineage.lineage`) to produce `LineageEdge(parent_table.column → child_table.column, edge_type="sql_derive", transform_expr=…)`
- Source nodes (`source.x.y`) → `LineageEdge(source_table → model, edge_type="dbt_source")`

**M12a-ii — Query-history lineage.** Every SQL Aughor itself executes (already logged in `query_history` per investigation) goes through the same SQLGlot lineage extractor. This means even without dbt, the graph populates organically as the agent runs. Hand-written analytical SQL that doesn't live in dbt still contributes lineage edges.

**M12a-iii — Multi-source federation.** Today a `DatabaseConnection` is per-investigation. Introduce a `DataSource` abstraction one level up:

- A `Workspace` (default: `"default"`) contains many `DataSource`s
- Each `DataSource` has a `kind` (`postgres`, `duckdb`, `bigquery`, `snowflake`, `csv-folder`, `dbt-project`)
- A single investigation can reference multiple sources by namespacing: `crm.customers`, `erp.invoices`, `commerce.orders`

The existing `DatabaseConnection`/`registry` work continues to function — a `DataSource` of kind `postgres`/`duckdb` simply wraps an existing connection. New kinds (`dbt-project` is metadata-only, no live queries) extend the abstraction without breaking it.

**Files to create:**
- `hermes/org/__init__.py`
- `hermes/org/lineage.py` — SQLGlot-based extractor; `extract_from_dbt(manifest_path) → list[LineageEdge]`, `extract_from_sql(sql, default_schema, dialect) → list[LineageEdge]`
- `hermes/org/sources.py` — `DataSource`, `Workspace`, `register_source()`, `list_sources()`
- `hermes/org/models.py` — Pydantic models: `LineageEdge`, `NodeRef`, `DataSource`, `Workspace`

**Files to modify:**
- `hermes/semantic/dbt.py` — call the new lineage extractor after the existing description parser; keep description behaviour unchanged
- `hermes/db/connection.py` — `execute()` after success calls `lineage.extract_from_sql(sql)` and persists edges (fire-and-forget; failures are silent)
- `hermes/db/registry.py` — add `workspace_id` column to connections table (migration-safe, defaults to `"default"`)

**New deps:** none — `sqlglot` is already in the project.

**API:**
```
GET  /workspaces                       # list workspaces
GET  /workspaces/{id}/sources          # list registered data sources
POST /workspaces/{id}/sources          # register a new source
GET  /lineage/{node_ref}/upstream      # full upstream lineage walk
GET  /lineage/{node_ref}/downstream    # full downstream lineage walk
```

`node_ref` format: `{workspace}.{source}.{schema}.{table}.{column?}` — column suffix optional for table-level walks.

#### M12b — Profiler & Drift Sentinel

**Goal:** Statistical fingerprint of every table/column, versioned over time, so "what changed?" has a real answer.

**What it computes per table per scan:**

- `row_count` (exact for small tables, HyperLogLog estimate for billions)
- Per-column: `null_rate`, `distinct_count` (HLL for high-cardinality), `min`, `max`, `top_5_values` for low-cardinality
- Per-table: `freshness_ts = MAX(<best timestamp column>)` — picks the most plausible timestamp column via heuristic (prefer `updated_at` > `created_at` > `*_ts` > `*_date`)

**How it scales to billions of rows:** approximate algorithms at the database level. DuckDB has `approx_count_distinct()` natively. Postgres has it via `tdigest` or `hll` extensions, and falls back to `COUNT(DISTINCT)` with `TABLESAMPLE BERNOULLI(1)` when extensions aren't available.

**Scheduling:** Prefect flow `profile_workspace(workspace_id)` runs on a configurable cadence per source. High-change tables (detected via row-count delta) get hourly profiling; stable dimensions get weekly. No external scheduler dependency — Prefect runs in-process for OSS deployment; can be promoted to Prefect Cloud for production.

**Drift detection:** Each scan compares to the previous and emits `DriftEvent`s:

- `schema_drift` — column added / removed / renamed / type changed
- `freshness_drift` — `freshness_ts` did not advance as expected (configurable SLA per source)
- `distribution_drift` — top-5 values changed by >X%, null rate jumped >Y pp, distinct count moved >Z%
- `volume_drift` — row count delta exceeds rolling-stddev threshold

Drift events become *first-class queryable nodes in the graph* — `describe_change_since(date)` returns them with their impact paths pre-computed.

**Files to create:**
- `hermes/org/profiler.py` — `profile_table(source, table) → TableProfile`; uses backend-specific approximate functions
- `hermes/org/drift.py` — `compare_profiles(prev, curr) → list[DriftEvent]`
- `hermes/org/flows.py` — Prefect flows: `profile_workspace`, `detect_drift`, scheduled triggers
- `hermes/org/models.py` — `TableProfile`, `ColumnProfile`, `DriftEvent` (extends file from M12a)

**Storage:**
- `data/org_graph.duckdb` — DuckDB analytical store for the graph and profile history (DuckDB is already a project dep; HLL sketches store natively)
- Tables: `org_nodes`, `org_edges`, `table_profiles`, `column_profiles`, `drift_events`

**New deps:** `prefect>=3.0` (already in the roadmap stack reference, just not yet imported).

#### M12c — The Organisation Knowledge Graph

**Goal:** Wire M12a edges and M12b profiles into a single queryable graph layer with a stable schema.

**Decision: graph-in-DuckDB, not a graph DB.** Neo4j is overkill for the read patterns here (mostly traversals 1–4 hops deep over <100k nodes). DuckDB's recursive CTEs handle this fine, integrate with everything else, and add zero deployment complexity. The graph is *modelled* relationally but *exposed* via a `Graph` API that hides the SQL — so future swap to Neo4j/Memgraph is a single-module change.

**Schema (DuckDB):**
```sql
CREATE TABLE org_nodes (
  node_id        VARCHAR PRIMARY KEY,    -- e.g. workspace.source.schema.table.column
  kind           VARCHAR,                -- 'workspace' | 'source' | 'schema' | 'table' | 'column'
                                         -- | 'entity' | 'metric' | 'transformation'
                                         -- | 'lifecycle_state' | 'drift_event'
  domain         VARCHAR,                -- inferred business domain (orders, customers, finance, …)
  display_name   VARCHAR,
  attributes     JSON,                   -- type, nullable, freshness, profile_id, sample values, …
  created_at     TIMESTAMP,
  updated_at     TIMESTAMP
);

CREATE TABLE org_edges (
  edge_id        VARCHAR PRIMARY KEY,
  from_node      VARCHAR,
  to_node        VARCHAR,
  edge_kind      VARCHAR,                -- 'fk_exact' | 'fk_inferred'
                                         -- | 'dbt_ref' | 'dbt_source' | 'sql_derive'
                                         -- | 'transition' (lifecycle)
                                         -- | 'computed_by' (metric → tables)
                                         -- | 'affects' (drift_event → downstream nodes)
  attributes     JSON,                   -- transform_expr, source_sql, confidence, observed_at, …
  observed_at    TIMESTAMP,
  evidence_count INTEGER                 -- how many times this edge was observed in SQL/dbt
);
```

**Synthesised nodes the graph adds beyond raw tables/columns:**

- **Entity nodes** — clusters of tables that share an entity key (e.g. all tables joining on `customer_id` → `entity:customer`). Computed from the join graph + glossary grain annotations.
- **Lifecycle state nodes** — extracted from status columns. For `orders.order_status` with values `created, approved, invoiced, shipped, delivered, canceled`, six `lifecycle_state` nodes get created and connected by `transition` edges inferred from timestamp ordering (`approved_at` follows `created_at`, etc.).
- **Transformation nodes** — one per dbt model or per recurring SQL pattern, owning its `sql_derive` edges.
- **Calculation-site nodes** — every distinct SQL expression that computes the same conceptual metric. E.g. `SUM(amount - refund_amount)` in one model and `SUM(amount) - SUM(refunds.amount)` in another both become `calculation_site` nodes attached to the `metric:gross_revenue` node. The `compare_calculations()` tool reads these.
- **Drift event nodes** — from M12b.

**Domain inference (the "what the org cares about" layer):**
A periodic batch job uses the coder LLM to classify every newly-discovered table into one of the workspace's domains (e.g. `orders`, `customers`, `finance`, `inventory`, `marketing`). Inputs: table name, columns, join graph neighbours, sample values, existing glossary. Output: `domain` attribute on the node + confidence. User can override; overrides stick (same pattern as glossary precedence).

**Files to create:**
- `hermes/org/graph.py` — `Graph` API: `add_node()`, `add_edge()`, `upstream(node_id, max_depth)`, `downstream(node_id, max_depth)`, `find_nodes_by_kind()`, `domains_of(node_id)`
- `hermes/org/entities.py` — entity clustering from join graph + grain hints
- `hermes/org/lifecycle.py` — state-machine inference from status + timestamp columns
- `hermes/org/calc_sites.py` — extracts calculation sites from SQL via SQLGlot AST walk; clusters expressions by semantic equivalence (constant-folded + normalised)
- `hermes/org/domains.py` — LLM-backed domain classifier, batch-friendly

**API:**
```
GET  /org/graph/stats                          # node/edge counts by kind
GET  /org/nodes/{node_id}                      # full node with neighbours
GET  /org/entities                             # all detected entities
GET  /org/entities/{entity_id}/lifecycle       # state machine
GET  /org/calculations                         # all metrics with their calculation sites
GET  /org/calculations/{metric_id}/divergence  # diff across sites
GET  /org/drift?since={iso_ts}                 # drift events since timestamp
```

#### M12d — Graph-Traversal Tool Layer

**Goal:** Expose the graph to the agent as a set of LLM-callable tools, not as a SQL surface. The agent reasons about *what to ask*; the tools handle *how to traverse*.

These plug into the existing LangGraph nodes (`plan_and_execute`, `synthesize_report`) as **additional Pydantic-modelled tools**, registered alongside `execute_sql`. The two-model architecture stays: the coder model calls tools and reasons; the narrator model writes prose.

**The five canonical structural tools:**

| Tool | Signature | What it returns |
|---|---|---|
| `trace_downstream_impact` | `(node_id: str, max_depth: int = 5) → ImpactReport` | All downstream nodes affected if this node fails / changes, grouped by domain, with `evidence_count` per edge |
| `get_entity_lifecycle` | `(entity_id: str) → LifecycleGraph` | State machine + transition triggers + tables that record each transition |
| `compare_calculations` | `(metric_id: str) → DivergenceReport` | Every SQL site computing this metric, their normalised expressions, observed value differences if profile data exists |
| `find_business_rule` | `(domain: str, concept: str) → list[RuleHit]` | Searches glossary caveats + metric formulas + SQL `WHERE` clauses across the graph for the concept; returns the rule + its source |
| `describe_change_since` | `(since: date) → ChangeReport` | All drift events since date, plus their downstream impact paths |

Each is a **deterministic graph traversal** with structured output — the LLM does not see raw SQL or raw rows from the graph store. It sees Pydantic models. This keeps token usage tight and prevents the LLM from confusing graph metadata with warehouse data.

**Files to create:**
- `hermes/agent/tools/structural.py` — five tool functions, each with a Pydantic input/output schema
- `hermes/agent/tools/__init__.py` — tool registry that the LangGraph nodes import from

**Files to modify:**
- `hermes/agent/nodes.py` — `plan_and_execute` now branches: SQL question → existing path; structural question → call structural tools. A node sees its `query_mode` from M12e and dispatches accordingly.
- `hermes/agent/prompts.py` — new `STRUCTURAL_TOOLS_PROMPT` block listing the tools and when to use which; injected into the planning prompt when mode is `structural`
- `hermes/agent/state.py` — extend `AgentState` with `structural_tool_results: list[StructuralToolResult]`

#### M12e — Structural Question Router

**Goal:** Extend the existing `route_question` node (M2e Routing v2) to recognise a third mode.

Current router (M2e/2g) classifies as `direct` or `investigate` with a confidence score. Add a third class: `structural`. The prompt gains a third intent definition and a handful of borderline examples:

| Mode | Trigger language |
|---|---|
| `direct` | "show me", "what is", "list", "how many", scalar / aggregate lookups |
| `investigate` | "why", "what's causing", "root cause", "diagnose" |
| **`structural`** | "what happens when", "what breaks if", "where else is X calculated", "what changed", "trace", "how does data get from X to Y", "what depends on", "show me the flow", "lifecycle", "audit", "drift" |

A confidence < 0.65 still falls back to `investigate` (the most thorough path) — consistent with the existing routing philosophy.

Structural mode bypasses `decompose` (no hypotheses) and `score_evidence` (no statistical scoring of structural answers). It runs:

```
route_question  →  plan_and_execute_structural  →  synthesize_structural
```

`plan_and_execute_structural` calls the M12d tools and accumulates their outputs. `synthesize_structural` uses the **narrator model** to write a prose answer with the structural results inlined — same `AnalysisReport` Pydantic schema, but with new `structural_findings: list[StructuralFinding]` and section variants in the frontend.

**Frontend (`web/`):**
- `ReportView.tsx` gains a structural variant: a graph-walk visualisation block (Observable Plot's network/graph layout or a small inline d3 if the team prefers) showing the actual nodes/edges traversed
- `ThinkingTrace.tsx` adds structural steps: `Route → Traverse(X tools) → Synthesise`
- A new `StructuralCard.tsx` renders impact reports / lifecycle diagrams / calculation divergence tables

### 1.5 How M12 plays with the existing milestones

| Existing milestone | Interaction with M12 |
|---|---|
| M1a Glossary / M1a+ Auto-seed | Domain inference (M12c) **reads** glossary; domain classifications **write back** to glossary as `auto_generated_domain` annotations. No clash with manual-YAML precedence. |
| M1b dbt Integration | M12a extends `hermes/semantic/dbt.py` to also extract lineage edges. Description parsing is unchanged. Three-layer merge precedence still holds. |
| M1c Vector Search | The graph adds a **new Qdrant collection** `org_nodes_index`. Entity, lifecycle, calculation-site, and drift-event nodes get embedded with rich descriptions. Structural questions retrieve from this collection. Schema-index collection unaffected. |
| M1d Prior Analyses | Structural investigations are indexed in the existing `investigations` collection with `mode="structural"` so they participate in cache hits. |
| M1e Metrics Catalog | Metric definitions get linked into the graph as `metric` nodes with `computed_by` edges to their referenced tables. `compare_calculations()` cross-checks observed SQL against the catalog's approved formula and flags divergences. |
| M2a Two-Model Arch | Structural tools use the **coder** model for orchestration (which tools to call, in what order). Synthesis uses the **narrator** model. Same pattern. |
| M2b Resumable Investigations | Structural mode uses the same SqliteSaver checkpointer. No changes needed. |
| M2c HITL | Structural mode can pause before synthesis just like investigative mode. Useful when a calculation-divergence answer needs analyst confirmation of which site is "the truth". |
| M2e Routing v2 / M2g | Extended, not replaced. Third class `structural` added; existing two classes unchanged in behaviour. |
| M2f SQL KB | Untouched. KB injects into SQL prompts; structural mode skips SQL planning entirely. |
| M2h Error Classification | Untouched. |
| M2i-i Join Inference | The join graph it produces is now **persisted as edges** in the org graph, with `edge_kind = fk_exact | fk_inferred`. M2i-i continues to run; M12c just stores the output durably. |
| M2i-ii Fingerprinting | The fingerprint becomes a **drift signal source** for M12b. A changed fingerprint triggers a re-profile. |
| M2j KB Pattern Enrichment | Causal-relationship patterns become candidate `transition` edges in lifecycle inference — a sanity-check signal, not the primary one. |
| M3 ibis / Connector-X / SQLMesh | M12 doesn't require any of these. When M3 ships, the profiler (M12b) can use Connector-X for fast Arrow-native scans, but the default path uses native SQL via the existing connection layer. |
| M4 Prophet | Drift detection (M12b) can call `forecast_anomaly()` when M4 ships to upgrade `volume_drift` from rolling-stddev to forecast-interval anomaly. Optional dependency. |
| M5 Anthropic backend | Structural prompts respect the existing `coder`/`narrator` role mapping. With prompt caching, the graph context (which is large and stable) becomes the canonical "cache this" block — massive cost win. |
| M6 Security | All structural tools respect the same `SafetyVerdict`. Multi-source federation requires per-source RBAC: the `Workspace` abstraction is the natural place to attach it (M6 work). PII redaction (6a) applies to any profile sample values surfaced. |
| M7 Observability | Each structural tool call is a Langfuse span. Drift events are first-class trace attributes. |
| M8 Frontend | New components (StructuralCard, graph-walk viz) live alongside existing ReportView; no replacements. |
| M9 Quick Chat | Quick Chat can call structural tools too — "what tables depend on `orders`?" answered in a chat bubble. The router classifies the chat turn just like a full investigation. |
| M10 Evals | New golden-question set for structural mode: ~30 questions with known correct downstream-impact / lifecycle / divergence answers. Three new scorers: `traversal_completeness`, `lineage_precision`, `drift_attribution_accuracy`. |
| M11 Visual Query Builder | Can read `entity` nodes and offer "browse by entity" as an alternative to "browse by table" — entity-first UX. |
| Nous Integration | M12 adds three new MCP tools: `hermes_trace_impact`, `hermes_get_lifecycle`, `hermes_describe_change_since`. Org agent uses these in its Sunday memory-refinement sweep — instead of guessing which investigations are still relevant, it queries the graph for what actually changed and recompresses around real changes. |

### 1.6 Sprint sequencing — six sprints, ~10 weeks

| Sprint | Scope | Duration | Why this order |
|---|---|---|---|
| **S1** | M12a-i + M12a-ii (lineage ingestion: dbt + query-history; SQLGlot extractor; `org_graph.duckdb` schema; lineage edges populated) | 2 wks | Foundation. No graph traversal yet, but every SQL the agent runs now leaves a permanent trace. Demonstrably valuable on day one. |
| **S2** | M12c base (graph API + entity clustering + lifecycle inference); minimum M12a-iii (multi-source federation, single-workspace) | 2 wks | Turn raw edges into a queryable structure with synthesised nodes. |
| **S3** | M12b (profiler + drift sentinel + Prefect flows) | 1.5 wks | Statistical fingerprinting; drift becomes a real signal. Runs nightly initially, optimised later. |
| **S4** | M12d (five structural tools, Pydantic-typed, registered in nodes); M12e (router extension + structural mode wiring) | 1.5 wks | Agent can now answer structural questions end-to-end. The integration moment. |
| **S5** | Frontend: StructuralCard, graph-walk viz in ReportView, ThinkingTrace structural steps; **Calculation-site clustering** (M12c second pass — the divergence detector) | 2 wks | The UX that makes the graph legible. Calculation-site clustering benefits from having lineage data accumulated over ~5 weeks at this point. |
| **S6** | Evals (M10 extension for structural); Nous MCP tools; **Domain inference** classifier batch run + glossary write-back | 1 wk | Quality gates + swarm integration + the LLM batch enrichment pass over the now-populated graph. |

**Why this order works:** Sprint 1 ships lineage extraction without any new UI or new agent behaviour — it's pure infrastructure that piggy-backs on every existing investigation. By Sprint 4, when structural mode lights up, the graph has 4+ weeks of accumulated lineage from real usage. The agent isn't asked to traverse an empty graph.

### 1.7 What changes for the user

After M12 ships, the user sees three new things in the UI:

1. **A new "Org Map" tab** alongside Investigate / History / Connections. Shows the live graph: entities, their lifecycles, current drift events, calculation sites. Browsable. Click any node → see its upstream/downstream, who depends on it, what changed recently.
2. **Structural answers in the existing chat/investigate flow.** Asking "what breaks if `vendor_invoices` stops loading?" no longer returns "I don't have enough information" or a fabricated SQL attempt — it returns a real, traversed impact map.
3. **Drift digests.** Every Monday morning (via Nous org agent or a plain cron), a "What changed in the warehouse this week, and what depends on those changes" report lands in Slack.

And one thing they don't see but matters more than any of the above: **every investigation Aughor runs from week six onward is informed by an actual model of how their data flows.**

---

## Part 2 — The Coding-Agent Prompt

The prompt below is designed to be handed to a frontier coding agent (Claude Code, Cursor agent mode, Devin, Codex CLI, etc.) that has already cloned `sidhasadhak/hypothesis-engine` and has the repo plus the existing `ROADMAP.md` / `FEATURES.md` / `NOUS_INTEGRATION.md` in its context. The agent will execute the milestone over multiple sessions; the prompt is structured so each session can pick up the right sprint.

Copy from the line below all the way through the end of the file.

---

````markdown
# Coding-Agent Brief — Implement Milestone 12 (Organisation Intelligence Layer) in `hermes/`

## 1. Who you are, what this is

You are a senior staff engineer working on Aughor (`sidhasadhak/hypothesis-engine`, internal codename `hermes/`). The product is an autonomous data analyst that investigates business questions over a connected data warehouse. The current state of the system is documented in `ROADMAP.md` (the canonical "what shipped, what's next") and `FEATURES.md` (per-feature reference). You have both in your context. **Read them before you write any code.** When in doubt about an interaction, prefer the patterns already used in the codebase over inventing new ones.

Your task is to ship **Milestone 12 — The Organisation Intelligence Layer (M12)** as specified in the roadmap document `M12_ORG_INTELLIGENCE_ROADMAP.md` (which you also have). M12 turns Aughor from a per-question analytical engine into a continuously-running model of how the organisation's data systems work, queryable via five new structural agent tools and a new routing mode (`structural`) alongside the existing `direct` and `investigate` modes.

M12 has five layers (M12a through M12e) and is sequenced across six sprints (S1–S6). **You execute one sprint per work session.** At the start of each session, identify the current sprint from `data/m12_state.json` (a small ledger file you maintain). At the end of each session, update it.

## 2. Non-negotiable invariants

These come from the existing codebase. Violating any of them counts as a regression, even if tests pass.

1. **No teardown of existing milestones.** Glossary precedence (manual YAML > dbt > auto-seed), two-model architecture (coder/narrator), prior-analyses cache short-circuit, HITL pause/resume, SqliteSaver checkpointing, SSE event shapes — all unchanged. Additive only.
2. **`AgentState` is a TypedDict; new fields go in, existing fields stay.** Where you need accumulating state, use `Annotated[list[T], operator.add]` consistent with `Pitfall` and other accumulators.
3. **Structured outputs only.** Every LLM call returns a Pydantic model via `instructor`. No string parsing of model output.
4. **Silent fallback on Qdrant / Prefect / lineage extraction failure.** The existing pattern is that semantic-layer infrastructure is *additive, not load-bearing* — if the new graph store is unreachable, investigations still run, just without structural mode. Match this.
5. **No new heavyweight runtime deps without a flag.** Anything beyond `sqlglot`, `qdrant-client`, `pydantic`, `instructor`, `prefect`, and the existing connection drivers needs to be opt-in via env var.
6. **Tests live next to code.** `hermes/org/lineage.py` → `tests/org/test_lineage.py`. Fixtures use the existing Olist DuckDB at `data/hermes.duckdb` where possible.
7. **Frontend changes are additive components**; never rewrite `ReportView.tsx` from scratch. Add variants, don't replace.
8. **SSE event shapes are stable.** New event types (e.g. `structural_step`) are additive. Existing consumers (`useInvestigation.ts` reducer) must not break.
9. **The router's existing `direct`/`investigate` behaviour is unchanged.** You are adding a third class, not modifying the existing two.

## 3. Files you will create / modify, organised by sprint

You don't have to follow this listing line-for-line, but you should produce code that fits this skeleton — the architecture review will check that key responsibilities live in the right module.

### Sprint 1 — Lineage extraction (M12a-i, M12a-ii)

**Create:**
- `hermes/org/__init__.py` — package marker
- `hermes/org/models.py` — Pydantic: `NodeRef` (`workspace`, `source`, `schema`, `table`, `column` optional), `LineageEdge` (`from_ref`, `to_ref`, `edge_kind`, `transform_expr` optional, `confidence` 0–1, `observed_at`, `evidence_count`), `TableProfile`/`ColumnProfile` stubs for S3 to fill
- `hermes/org/lineage.py` — two public functions:
  - `extract_from_dbt(manifest_path: Path, default_workspace: str) → list[LineageEdge]` — reads `manifest.json`, walks every model node, emits `dbt_ref` and `dbt_source` table-level edges; if `compiled_sql` is present, runs SQLGlot's lineage API to also emit column-level `sql_derive` edges
  - `extract_from_sql(sql: str, default_schema: str | None, dialect: str, workspace: str, source: str) → list[LineageEdge]` — uses `sqlglot.parse_one(sql, dialect=dialect)` plus `sqlglot.lineage.lineage()` for each output column; returns column-level `sql_derive` edges
- `hermes/org/store.py` — DuckDB-backed graph store. Creates / migrates `data/org_graph.duckdb`. Provides `upsert_edges(edges: list[LineageEdge]) → None` with deduplication on `(from_ref, to_ref, edge_kind)` and `evidence_count` increment.

**Modify:**
- `hermes/semantic/dbt.py` — after the existing description parsing, call `lineage.extract_from_dbt(...)` and `store.upsert_edges(...)`. Gate behind `HERMES_LINEAGE=true` (default true; set to false to disable).
- `hermes/db/connection.py` — at the end of `execute()` on successful queries (only), call `lineage.extract_from_sql(...)` and `store.upsert_edges(...)` inside a `try/except` that logs but never raises. Use the connection's `dialect` attribute. Default source is the connection name.

**Migration safety:** the new `data/org_graph.duckdb` is created on first use; no schema migration needed for existing `history.db`, `checkpoints.db`, `connections.db`.

**Acceptance criteria for S1:**
- Running the existing Olist demo investigation populates `data/org_graph.duckdb` with at least 10 `sql_derive` edges
- If `HERMES_DBT_MANIFEST` is set, dbt-ref and dbt-source edges appear
- Setting `HERMES_LINEAGE=false` makes lineage extraction a complete no-op (no DB writes, no new DuckDB file created)
- Lineage extraction failure on a single bad SQL does not break the parent investigation
- New unit tests: 6 minimum, covering successful extraction, malformed SQL, unsupported dialect fallback, dedup, and the env-var gates

### Sprint 2 — Graph API + entity clustering + lifecycle inference + multi-source

**Create:**
- `hermes/org/sources.py` — `Workspace`, `DataSource` Pydantic models; `register_source()`, `list_sources()`, `get_source(id)` backed by a new SQLite table in `data/connections.db` (additive — same DB, new table)
- `hermes/org/graph.py` — `Graph` class wrapping `store.py`. Methods: `add_node`, `upsert_node`, `add_edge`, `upstream(node_id, max_depth=5) → list[NodeWithPath]`, `downstream(node_id, max_depth=5) → list[NodeWithPath]`, `find_nodes_by_kind(kind) → list[Node]`, `find_path(from, to, max_depth=8) → list[Path]`. All traversals are DuckDB recursive CTEs internally; the public API never returns SQL.
- `hermes/org/entities.py` — `cluster_entities(graph: Graph) → list[Entity]`. Algorithm: group tables by shared join keys (via existing M2i-i join-inference output, now persisted as `fk_exact`/`fk_inferred` edges); attach `grain` from glossary; emit `entity` nodes and `member_of` edges.
- `hermes/org/lifecycle.py` — `infer_lifecycle(graph: Graph, entity: Entity) → LifecycleGraph`. For each member table, find status-like columns (heuristic: low-cardinality VARCHAR with no nulls or low-null-rate, name matches `*_status|state|stage|phase`). Cross-reference with timestamp columns named after status values (e.g. `approved_at` if status has `approved`). Emit `lifecycle_state` nodes and `transition` edges.

**Modify:**
- `hermes/db/registry.py` — add `workspace_id` column to the connections table with safe migration (`ALTER TABLE … ADD COLUMN workspace_id VARCHAR DEFAULT 'default'`); update read/write paths
- `hermes/api.py` — add endpoints:
  - `GET /workspaces`, `POST /workspaces`, `GET /workspaces/{id}/sources`, `POST /workspaces/{id}/sources`
  - `GET /org/graph/stats`, `GET /org/nodes/{node_id}`
  - `GET /org/entities`, `GET /org/entities/{entity_id}/lifecycle`
  - `GET /lineage/{node_ref:path}/upstream`, `GET /lineage/{node_ref:path}/downstream`

**Acceptance:**
- After running ≥3 investigations against the Olist fixture, `GET /org/entities` returns at least `customer`, `order`, `product`
- `GET /org/entities/order/lifecycle` returns at least 5 lifecycle states (created, approved, invoiced, shipped, delivered, plus canceled if present)
- `upstream`/`downstream` traversals correctly walk through dbt models when dbt manifest is configured
- A query with a workspace it doesn't belong to returns 404, not 500

### Sprint 3 — Profiler + Drift Sentinel

**Create:**
- `hermes/org/profiler.py` — `profile_table(source: DataSource, table: str) → TableProfile`. Backend-aware: uses DuckDB `approx_count_distinct()`, Postgres `tdigest`/`hll` if available else `TABLESAMPLE BERNOULLI`. Always cheap by default; budget enforced.
- `hermes/org/drift.py` — `compare_profiles(prev: TableProfile, curr: TableProfile) → list[DriftEvent]`. Four drift kinds as in the roadmap.
- `hermes/org/flows.py` — Prefect flows:
  - `profile_workspace(workspace_id)` — fan-out over sources, fan-out over tables, deadline-bounded per table
  - `detect_drift(workspace_id)` — reads last two profiles per table from the store, diffs, writes drift events to the graph
  - Both schedulable via `prefect.deploy()`; in-process runner for OSS deployment
- `hermes/org/cli.py` — `python -m hermes.org.cli profile <workspace>` and `python -m hermes.org.cli drift <workspace>` for manual triggering and CI use

**Modify:**
- `hermes/db/connection.py` — add `bulk_sample(table, n) → list[dict]` helper used by the profiler. Postgres uses `TABLESAMPLE`; DuckDB uses `USING SAMPLE`.
- `hermes/api.py` — `GET /org/drift?since={iso_ts}`, `POST /org/profile/{workspace_id}/run` (manual trigger)

**Acceptance:**
- `python -m hermes.org.cli profile default` completes on the Olist fixture in < 90s and writes profiles for all tables
- A second run with no DB changes produces zero drift events
- Manually altering a column type and re-running produces a `schema_drift` event
- Profile failure on one table does not stop the flow for the others
- New Pydantic models in `models.py`: `TableProfile`, `ColumnProfile`, `DriftEvent` with strict validation

### Sprint 4 — Structural tools + router

**Create:**
- `hermes/agent/tools/__init__.py` — tool registry
- `hermes/agent/tools/structural.py` — five tools, each with `*Input` and `*Output` Pydantic models. The functions read from `Graph` only; they never call the LLM and never touch the warehouse:
  - `trace_downstream_impact(node_id, max_depth=5) → ImpactReport`
  - `get_entity_lifecycle(entity_id) → LifecycleGraph`
  - `compare_calculations(metric_id) → DivergenceReport` (stub: returns empty divergence in S4; full implementation lands in S5 when calc-site clustering ships)
  - `find_business_rule(domain, concept) → list[RuleHit]`
  - `describe_change_since(since: date) → ChangeReport`
- `hermes/agent/nodes_structural.py` — new nodes:
  - `plan_and_execute_structural` — calls a `structural_tool_selection` LLM step (coder model, structured output: `list[StructuralToolCall]`), executes the tools, accumulates results in `AgentState.structural_tool_results`
  - `synthesize_structural` — narrator model, takes accumulated structural results and writes the prose `AnalysisReport` variant

**Modify:**
- `hermes/agent/prompts.py` — extend `ROUTE_QUESTION_PROMPT` to add `structural` as a third class with 6 borderline examples; new `STRUCTURAL_TOOL_SELECTION_PROMPT` (which tools to call given the question + a structured graph stats summary); new `SYNTHESIZE_STRUCTURAL_PROMPT`. Existing prompts untouched.
- `hermes/agent/state.py` — add `query_mode: Literal["direct","investigate","structural"]` (Literal extended), `structural_tool_results: Annotated[list[StructuralToolResult], operator.add]`
- `hermes/agent/nodes.py` — `route_question` already exists from M2e/2g; just extend its prompt and validate the third class lands
- `hermes/agent/graph.py` — `route_question` now has a third conditional edge: `structural` → `plan_and_execute_structural` → `synthesize_structural` → `END`. The `interrupt_before=["synthesize"]` HITL flag remains; mirror it for `synthesize_structural` so HITL works in structural mode too.
- `hermes/api.py` — SSE event additions: `structural_step` (per tool invocation), `structural_result` (per completed tool). Update the docstring of `/investigate` to enumerate new events.

**Acceptance:**
- "What happens when a customer is deleted from the customers table?" routes to `structural` with confidence ≥ 0.7 and produces a coherent downstream-impact answer
- "Why did revenue drop last week?" still routes to `investigate` (regression test)
- "Show me MRR" still routes to `direct` (regression test)
- HITL pause works in structural mode (regression test against the existing pause/resume API)
- New SSE events appear in the stream and are consumed by a small test client without breaking the existing reducer

### Sprint 5 — Frontend + calculation-site clustering

**Create:**
- `web/components/StructuralCard.tsx` — renders one structural tool result (impact map / lifecycle graph / divergence table / rule hits / change report)
- `web/components/GraphWalkViz.tsx` — small inline graph visualisation; Observable Plot's `Plot.dot` + `Plot.link` for nodes+edges OR a tiny d3 force layout if the visual is much better — your call, but document the choice in a comment
- `web/components/OrgMapTab.tsx` — new top-level tab; browsable graph view backed by `/org/*` endpoints; shows entities + lifecycles + recent drift events + calculation divergences
- `hermes/org/calc_sites.py` — calculation-site clustering. For each SQL the agent has executed, run SQLGlot to extract the AST of each top-level SELECT expression. Normalise (constant-fold, alias-strip, canonical column order). Hash the normalised AST. Cluster expressions with the same hash. Compare clusters that produce values for the same conceptual metric (linked via M1e metrics catalog references) — emit `calculation_site` nodes and `divergence` edges with the actual differing SQL stored as an attribute.

**Modify:**
- `web/components/ReportView.tsx` — when `report.query_mode === "structural"`, render a stack of `StructuralCard`s instead of (not in addition to) the investigate/direct variants. The headline/summary/recommendations sections still render — they're shared.
- `web/components/ThinkingTrace.tsx` — `structural` path: `Route → Traverse(N tools, with running tool name + result count) → Synthesise`
- `web/app/page.tsx` — add the Org Map tab to the tab list
- `web/lib/types.ts` — add types for structural events, structural findings, org-graph API responses
- `web/lib/useInvestigation.ts` — extend reducer to handle `structural_step` and `structural_result` SSE events. **Existing event handling unchanged.**
- `hermes/agent/tools/structural.py` — flesh out `compare_calculations()` now that calc-sites are populated; return real divergences

**Acceptance:**
- Org Map tab renders a navigable graph; clicking a node shows its neighbours and recent drift
- "Show me every place where we compute gross margin" returns a real divergence report with at least two sites if the agent has run SQL touching multiple gross-margin expressions
- Frontend test: structural report renders without crashing on an empty `structural_tool_results` list
- The existing `direct` and `investigate` report renders are byte-identical to before this sprint (visual regression check)

### Sprint 6 — Evals + Nous MCP tools + domain inference + RC polish

**Create:**
- `evals/structural_dataset.py` + `evals/golden_structural.jsonl` — 30 questions with expected structural answers (entities touched, lifecycle states named, drift events found, divergent calc sites detected)
- `evals/structural_scorers.py` — three Braintrust scorers: `traversal_completeness`, `lineage_precision`, `drift_attribution_accuracy`
- `hermes/mcp/org_tools.py` — three new MCP tool definitions exposing `trace_downstream_impact`, `get_entity_lifecycle`, `describe_change_since` over the existing MCP server scaffold (referenced in `NOUS_INTEGRATION.md`). If `mcp_server.py` doesn't exist yet, create it with just the org tools and a TODO comment for the rest of the surface — that's the Nous-integration team's scope.
- `hermes/org/domains.py` — LLM-backed domain classifier. Takes a batch of unclassified nodes; produces structured `DomainAssignment(node_id, domain, confidence, reasoning)` outputs via coder model + instructor. Writes back to glossary as `auto_generated_domain` per the precedence rules in M1a (auto-generated never overrides manual or dbt).
- `hermes/org/cli.py` — add `python -m hermes.org.cli classify-domains <workspace>` subcommand

**Modify:**
- `evals/run.py` — extend to load and run the structural dataset alongside the existing one; CI gate update: structural metrics regression > 5% blocks the PR
- `ROADMAP.md` — mark M12 features as shipped at the appropriate granularity; **do not rewrite the rest of the file**
- `FEATURES.md` — append a new feature entry per shipped M12 layer; same structure as the existing 29

**Acceptance:**
- Eval suite runs in CI and reports the three new scorers
- `python -m hermes.org.cli classify-domains default` classifies every unclassified table in the Olist fixture
- Manual or dbt-provided domain assignments survive a domain-classification run
- MCP tools callable via `mcp_hermes_trace_impact` from any MCP-aware client

## 4. Patterns to follow

These are the codebase's conventions. Match them exactly.

- **Pydantic for everything that crosses a boundary.** No dict-shuffling between modules.
- **`instructor`-wrapped LLM calls.** Pattern in `hermes/agent/nodes.py::decompose_question` is canonical.
- **Three-layer merge precedence for any user-overridable inference** (manual > dbt > auto-generated). Match `hermes/semantic/glossary.py::load_merged_glossary`.
- **Fail closed on the semantic layer.** Silent fallback to "feature disabled" on any infra error. Match `hermes/semantic/retriever.py::retrieve_relevant_schema` behaviour.
- **SSE events are typed JSON.** New events follow the existing shape `{ "type": "...", ...payload }`.
- **Tests use the Olist DuckDB fixture** at `data/hermes.duckdb` for integration tests; pure-Python unit tests have no DB dependency.
- **Frontend reducer pattern**: never replace, extend the `useInvestigation` reducer with new event handlers; existing handlers untouched.
- **Two-model provider abstraction.** Coder model for tool selection and SQL/structural reasoning; narrator model for prose. Use `get_provider(role="coder"|"narrator")`. **Never hardcode a model name.**

## 5. Anti-patterns — do not

- Do not introduce a new graph database. The graph lives in DuckDB. If a future sprint genuinely needs Neo4j, that's a separate proposal.
- Do not modify the `decompose` node or `score_evidence` node. Structural mode bypasses them.
- Do not put structural traversal logic inside `plan_and_execute` (the SQL-planning node). Use the new `plan_and_execute_structural` node. Keep the SQL path clean.
- Do not change the existing `direct` vs `investigate` routing behaviour. Routing v2 (M2g) is unchanged in classification rules; only the third class is added.
- Do not call the warehouse from inside a structural tool. The graph is the source of truth for structural answers. Tools read the graph store, not the live database.
- Do not let LLM calls into the structural tools themselves. The tools are deterministic; the LLM orchestrates which tools to call, what arguments to pass, and how to narrate the result.
- Do not break the cache short-circuit (`find_similar_investigation`) for direct or investigate modes. Structural mode can participate in cache; it must not damage existing cache behaviour.
- Do not write to `glossary.yaml` from inside the lineage extractor. Glossary changes go through the existing autoseed / API paths only.

## 6. Working agreement for each session

1. **Start by reading `data/m12_state.json`** — a JSON file you maintain at the repo root containing `{ "current_sprint": "S1"|...|"S6", "completed_sprints": [...], "blocked": null | "...", "last_session_ended_at": "..." }`. If the file doesn't exist, create it with `current_sprint: "S1"`.
2. **At the start of every session**, write a 5–10 line summary in chat of what you will do this session and what acceptance criteria you will hit.
3. **Run the full test suite at the end of every session.** If anything red, fix it before stopping or document the failure in `data/m12_state.json::blocked` and stop.
4. **Update `ROADMAP.md` only at the end of a sprint, in the same minimal style as existing entries.** No prose rewrites of unrelated sections.
5. **Commit at the end of each session with a structured message**: `M12-Sx: <one-line summary>` body containing the acceptance criteria you hit.
6. **If you discover the roadmap is wrong** (e.g. a proposed file structure doesn't actually fit the codebase you encounter), do not silently deviate — write a short ADR-style comment at the top of the affected new file explaining the deviation and continue.
7. **Bias to small, vertical slices.** A working `trace_downstream_impact` end-to-end with no UI is more valuable than five half-built tools.

## 7. Sprint S1 — start now

Your first session is Sprint 1. Plan: read `ROADMAP.md`, `FEATURES.md`, `NOUS_INTEGRATION.md`, and `M12_ORG_INTELLIGENCE_ROADMAP.md` in that order. Inspect `hermes/semantic/dbt.py`, `hermes/db/connection.py`, and `hermes/agent/nodes.py` to ground the lineage hooks in the actual code paths. Then implement S1 per Section 3 above. The acceptance test "running the existing Olist demo investigation populates `data/org_graph.duckdb` with at least 10 `sql_derive` edges" is your stopping point. Update `data/m12_state.json`, commit, and report back.

Pace yourself — six sprints is the budget. Don't try to land all five tools in week one. The graph has to fill up with real lineage first; that's why S1 is intentionally narrow.

Start.
````

---

*End of file. The fenced block above is the prompt to hand to the coding agent. Everything before it is for human review of the milestone proposal.*
