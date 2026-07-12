# Spice.ai OSS — Deep Study & Aughor Adoption Plan (2026-07-11)

**Status:** STUDY — no code changes in this document. Every recommendation is flag-gated, default-off,
byte-identical-when-off, and follows BUILT→WIRED→TESTED→LEVERAGED.

**Subject:** [spiceai/spiceai](https://github.com/spiceai/spiceai) (`trunk`, v2.1.0-unstable, Apache-2.0, ~75 Rust
crates) — "a SQL query, search, and LLM-inference engine, written in Rust, for data-driven applications and AI
agents." Verified against a full source clone (commit `cb96c9f`), official docs (spiceai.org/docs), and the
Spice 2.0 launch material (Cayenne GA, Ballista distributed query, native CDC, Cedar/RBAC).

**Method:** four parallel source-level deep dives (core runtime, acceleration/CDC, connectors, AI layer) +
one Aughor gap map + docs/blog verification. File evidence cited as `crate/path:line` (Spice) and
`aughor/path` (ours).

---

## TL;DR

Spice is the closest *conceptual* neighbor Aughor has: both bet that **agents fail on data, not models**, and
both answer with deterministic machinery rather than more LLM. But they attack opposite halves of the problem.
Spice built the **data plane** — federation across ~40 sources, sub-second materialized acceleration, CDC
freshness, hybrid search, all in one Rust binary — and kept the intelligence layer deliberately thin (its NSQL
is schema+samples in a prompt; no semantic layer, no guards, no ambiguity handling, no investigation). Aughor
built the **intelligence plane** — grounding, deterministic guards, ontology/glossary/metrics, ambiguity
ledger, closed-loop verdicts, investigation agents — on a thin data plane (per-result TTL cache, no table-level
acceleration, no CDC, no search over data rows).

The strategic read: **complement, don't compete**. Interop with Spice as a substrate (one connector buys their
entire connector fleet + acceleration + CDC), build Python-scale versions of their three highest-leverage
mechanics (dataset acceleration, spans-as-a-table, grounding receipts), mine a dozen design idioms, and
explicitly refuse the Rust-scale infrastructure (Ballista, Cayenne/Vortex, log-based CDC, Flight serving).

Spice also *validates* Aughor's roadmap from the outside: their five-year vision — "close the feedback loop…
insights feed back… the agent learns and gets smarter automatically" (CEO interview, 2.0 launch) — is the loop
Aughor already shipped (`ambiguity_ledger` → `priors` → `verdicts` → `trusted_queries`, flag `closed_loop`).
They are years from it; we are live behind a flag. Conversely their data plane is years ahead of ours, which is
exactly why we interop instead of rebuild.

### Verdict table

| Area of Spice | Verdict | One line |
|---|---|---|
| Spice runtime as data substrate | **INTEROP as client** | Add a `spice` connector (HTTP `/v1/sql`, Postgres-dialect DataFusion); one connector → 40+ sources, acceleration, CDC freshness. Never embed or rebuild. |
| Dataset-level acceleration (refresh modes, readiness, fallback) | **BUILD** (Python-scale) | Aughor's biggest data-plane gap; a DuckDB-file mirror with `full/append` refresh, readiness state, fallback-to-source, staleness receipts. |
| Results-cache tenancy (namespace-folded keys) | **ADOPT** (correctness) | Verified latent leak: `matcache` keys `(conn_id, sql)` *before* RLS injection → cross-principal serving once `rbac.row_policy` activates. |
| Task history as a queryable table | **BUILD** (small) | One `task_history` table (trace/span/parent/input/output/duration/error); evals read *from it*. Unifies ledger/MLflow/episodes exhaust. |
| Grounding-context receipt (`/v1/nsql/context`) | **BUILD** (small) | Expose the exact grounding block the LLM sees; the input-side twin of Aughor's trust receipts. |
| RRF hybrid fusion (+ recency decay, rerank stage) | **ADOPT** | Upgrade `lexical.py`'s α-blend to rank-based RRF (k=60); model-free, no score normalization. |
| Connector-contract idioms (ParameterSpec, `is_retriable`, capability-as-vtable, readiness) | **MINE** | Patterns into `connectors/registry.py` + error taxonomy; no code imported. |
| Spicepod declarative bundle | **MINE** | Validates the nao-ontology + Packs direction; longer-term "aughorpod" workspace export/import. |
| Per-agent data stacks / table allowlists | **MINE** | Thread a table allowlist from user-agent scope through every SQL execution (defense-in-depth). |
| CDC replication (WAL/binlog/oplog) | **DEFER / INTEROP** | Never build log-based CDC in Python; if freshness demand appears, front the source with Spice `changes` mode. |
| Rust engine, Arrow Flight/ADBC serving, Ballista, Cayenne/Vortex, Cedar, local model serving | **REJECT** | Not our lane. Aughor serves *answers*, not record batches. |

---

## Part A — What Spice is and how it delivers

### A1 · The shape: one binary, one YAML, four API standards

Two binaries: `spice` (CLI) and `spiced` (the runtime daemon). Everything — datasets, views, models,
embeddings, rerankers, tools, catalogs, secrets, runtime config — is declared in one versioned YAML manifest,
the **spicepod** (`crates/spicepod/src/spec.rs:283`). Pods compose: `dependencies[]` pulls sub-pods whose
components flatten into the root app (`crates/app/src/lib.rs:433`); pods load from local FS *or object store
URLs* (`s3://bucket/spicepod.yaml`). The runtime then exposes four industry-standard surfaces:

1. **SQL**: HTTP `POST /v1/sql`, Arrow Flight, Flight SQL, ODBC/JDBC/ADBC (`crates/runtime/src/http/routes.rs:314`).
2. **OpenAI-compatible AI**: `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`, `/v1/search`, `/v1/nsql`.
3. **Iceberg REST catalog** (Spice *serves* one, so lake tools can read its tables).
4. **MCP** Streamable-HTTP at `/v1/mcp` — both server (its tools) and client (external MCP servers become model tools).

Deployment spans "Raspberry Pi to petabyte cluster" from the same binary: standalone by default; distributed
mode is just `--role scheduler` / `--scheduler-address` flags.

**How the "monster capabilities" are actually delivered — a fork-and-patch supply chain.** Spice's leverage is
~6 strategically forked Apache/LF projects, each pinned to 40-char SHAs with a written patch-audit plan
(`Cargo.toml:186–445`, `plans/df54-fork-patch-audit.md`):

| Dependency | Role | How leveraged |
|---|---|---|
| **Apache DataFusion 54** (fork) | The query engine | Custom analyzer/optimizer rule set, custom UDFs (`ai`, `embed`, vector distances, JSON), custom TableProviders; the SQL unparser renders plans back to per-dialect SQL. |
| **datafusion-federation** (fork) | Cross-source split | Pushes maximal sub-plans down to each source in its own dialect; Spice wraps it with a per-source *function deny-list* so unsupported functions execute locally instead (`crates/data_components/src/federation.rs:44`). |
| **datafusion-table-providers** (fork) | Connector base | `SqlTable` + connection pools + Arrow type mapping for Postgres/MySQL/DuckDB/… — Spice contributed these back upstream. |
| **Apache Arrow 58 / Flight** | Wire + memory format | Everything is streaming `RecordBatch`es; Flight egress is backpressured against the query memory pool. |
| **Apache Ballista** (fork) | Distributed compute | Scheduler/executor split with multi-active schedulers coordinated via **object-store conditional writes — no etcd/ZooKeeper** (`docs/decisions/006`). |
| **DuckDB / SQLite / Turso** | Acceleration engines | Embedded materialization targets, plus… |
| **Vortex** (LF project, fork) | Columnar format for **Cayenne** | Their own lakehouse table format: compute on encoded data, 100× faster random access than Parquet, deletion vectors for CDC mutation. |

The idiom to note: **they didn't build a query engine; they curated one** — and concentrated their original
engineering in exactly two places: acceleration (Cayenne) and the glue that makes federation safe
(deny-lists, statistics propagation, dialect unparsing).

### A2 · Query lifecycle and the runtime discipline

SQL arrives → a `RequestContext` (principal, trace parent, cache control, cancellation token) is scoped
task-locally → read-only gate for read-only principals → DataFusion plans → federation analysis splits the
plan per source → results cache check (plan-hash keyed) → execution streams batches → telemetry.
Noteworthy engineering discipline (all verified in source):

- **Separate Tokio runtimes** for HTTP vs CPU-heavy query vs refresh vs CDC-apply vs compaction, so `/health`
  never starves (`bin/spiced/src/lib.rs:686–740`).
- **Client-disconnect cancellation** via a drop-guard on the response body: client leaves mid-stream → the
  query's cancellation token fires (`crates/runtime/src/http/routes.rs:567–588`).
- **Cache safety**: write-capable plans are never cached; invalidation resolves qualified/unqualified table
  refs to one canonical form; **cache keys fold a `(namespace_tag, namespace_id)` prefix for authenticated
  queries** so per-user results can't cross-serve, while permission-independent results (embeddings) use a raw
  shared key (`crates/cache/src/key.rs:88–135`).
- **No booleans in user-facing config** — behavior-named enums with conservative defaults (`on_zero_results:
  return_empty|use_source`, `on_schema_change: block|append_new_columns|…`), because a bool "can't grow a third
  state and hides which value means on" (`.github/copilot-instructions.md:116`).

### A3 · Acceleration: datasets, not results

The core product concept: a **dataset** declares `acceleration` with an engine
(`arrow|duckdb|sqlite|postgres|cayenne`), a mode (`memory|file`), and a **refresh mode**
(`full|append|changes|caching|snapshot`) (`crates/runtime-acceleration/src/acceleration.rs:132–199`).
Orchestration (`crates/runtime/src/accelerated_table/`):

- **Full/append** refresh on interval or cron, with jitter, Fibonacci-backoff retry, and
  **transient-vs-permanent error classing** (a missing timestamp column never retries;
  `refresh_task.rs:591–611`). Append mode = accelerator's max `time_column` + `WHERE time_col > max` + a
  configurable **overlap window** for late arrivals, plus a "source unchanged → skip fetch" probe.
- **Readiness gate**: queries are rejected with `AccelerationNotReady` until the source emits a readiness
  envelope — *mandatory even on a quiet source* (zero-row ready signal; `crates/data_components/src/cdc.rs:64–84`).
- **Fallback**: `on_zero_results: use_source` transparently re-runs against the federated origin when the
  accelerator returns nothing (`accelerated_table/mod.rs:1387–1643`).
- **Retention** with an explicitly documented footgun: `time_col < cutoff` is NULL-false, so NULL-timestamp
  rows never evict (`retention.rs:144–166`).
- **Changes (CDC)**: every source (Postgres WAL, MySQL binlog, Mongo change streams, DynamoDB Streams,
  Debezium/Kafka) is normalized into **one connector-agnostic Arrow envelope** `{op, primary_keys, data}`
  (`cdc.rs:410–553`) feeding one apply path; source-offset acks are deferred until the accelerator checkpoint
  is durable, with PK-idempotent replay giving exactly-once (`refresh_task/changes.rs:103–165`).

**Cayenne** (GA in 2.0, fully OSS in-tree) is their answer to DuckDB's >1 TB ceiling: Vortex columnar files +
a SQLite/Turso transactional metastore + an LSM level-0 tier inside the metastore. Visibility is a single
atomic pointer flip (`current_snapshot_id`) under a fence held only microseconds; the expensive work (encode,
catalog I/O) runs off-fence; readers get wait-free `ArcSwap` state. Claims: 1.5× faster than DuckDB at 3×
less memory (TPC-H SF100), 2-second end-to-end CDC freshness under continuous ingest.

### A4 · The AI layer: an OpenAI gateway welded to the query engine

This is the part closest to Aughor's lane, and it is deliberately *minimal*:

- **Tool loop, not agent graph.** `ToolUsingChat` wraps any provider: inject Spice tools → run tool calls
  locally → recurse with a hard `tool_recursion_limit` → summed token accounting
  (`crates/runtime/src/model/tool_use.rs:289–351`). No planner, no multi-agent, no orchestration DSL.
- **The toolbelt is data-shaped**: `list_datasets` (discovery-first, returns capability flags like
  `can_search_documents`), `table_schema`, `sql`, three sampling tools, `search` (hybrid), datetime,
  readiness, and table-backed `store_memory`/`load_memory`. Tool *descriptions* teach the workflow ("call
  list_datasets first", "avoid SELECT *").
- **Tool-count scaling**: above ~20 tools, the runtime advertises only `tool_search` (embedding similarity
  over tool descriptions) + `tool_invoke` instead of every schema (`tools/registry.rs:49–232`).
- **Per-model table allowlist** threaded into every tool from the model's declared `datasets[]`
  (`model/chat.rs:117–136`) — the "sandboxed data stack per agent" enforced at execution, not prompt, level.
- **NSQL grounding is deterministic context assembly**: engine descriptor, per-dataset schemas with
  **per-column capability flags and exact search-syntax hints** (`vector_search(...)` call syntax per
  searchable column), UDF list, optional capped samples — and `/v1/nsql/context` returns the *exact block the
  model sees* as JSON/markdown for inspection (`model/nsql.rs`, `http/v1/nsql.rs:264–297`). Failed SQL
  attempts are fed back as `{attempted_query, error_message}` on retry.
- **Search = SQL primitives**: `vector_search()`, `text_search()` (Tantivy BM25), `rrf()` (k=60, rank
  weights, exponential recency decay), `rerank()` (cross-encoder or any chat model, listwise) — nestable:
  `rerank(rrf(vector_search(...), text_search(...)))` (`runtime-search/src/{udtf,rrf,rerank}.rs`). Two vector
  storage models behind one trait: co-located (DuckDB VSS/HNSW) vs external-store+join (S3 Vectors with
  sharded spill indexes, Elasticsearch).
- **Observability is a SQL table.** Every AI call, tool call, SQL query, refresh, and search lands in
  `runtime.task_history` (`trace_id, span_id, parent_span_id, task, input, captured_output, start/end,
  duration_ms, error_message, labels`) via tracing spans (`task_history/mod.rs:141–184`). Their **text-to-SQL
  eval harness recovers generated SQL by querying task_history** — the observability table *is* the eval
  substrate (`test-framework/src/spicetest/text_to_sql/task_history.rs:49–137`).

### A5 · Distributed + multi-tenancy (context for the 10,000-agents story)

Ballista scheduler/executor with Spice's extensions: **multi-active schedulers** registered via ETag
conditional writes to object store (no coordination service), bidirectional control streams for push
scheduling, fault-tolerant shuffle (disk/memory/object-store, Vortex-encoded), greedy set-cover executor
selection over partition assignments, async query API because sync requests can't survive scheduler death.
Multi-tenancy comes in four documented tiers: query-time filters → per-tenant dataset entries → **one
spicepod/runtime per tenant** (the 10k-agents pattern) → hybrid. The economics: a Spice instance is cheap
enough that "10,000 warehouses" becomes "10,000 processes."

---

## Part B — Head-to-head: Aughor vs Spice

| Dimension | Spice | Aughor | Read |
|---|---|---|---|
| Data plane (federation breadth, speed) | ~40 connectors, plan-level pushdown, Arrow streaming | ~15 connectors; DuckDB-ATTACH federation + batched cross-source joins (flags off); non-native sources copied via Arrow | **Behind** — interop, don't rebuild |
| Freshness | CDC 2-sec freshness; append/full refresh; readiness/fallback | APScheduler polling, explorer watermarks, API-sync cursors | **Behind** — build Python-scale acceleration; interop for CDC |
| Search over data rows | Hybrid vector+BM25+RRF+rerank as SQL primitives | Trigram value-index for literal binding only; hybrid search over *metadata/KB* | **Behind/different** — mine RRF; row-search only where it serves answers |
| NL2SQL grounding | Schema + samples + syntax hints in prompt; retry-on-error | Ontology, glossary, governed metrics, value domains, measure grain, dialect contracts, 20+ deterministic guards, ambiguity ledger, clarify gates | **Ahead — this is the moat.** Spice has no semantic layer, no guards, no ambiguity handling. |
| Answer trust | None (returns model output) | Trust plane: verify gates, receipts, adversarial refuter, verdicts, premise checks | **Ahead** |
| Investigation / analysis depth | None (single tool loop) | ADA multi-lens decomposition, explorer, briefings, monitors | **Ahead** |
| Closed feedback loop | Their explicit *five-year vision* | Shipped behind `closed_loop`: ledger→priors→verdicts→trusted queries | **Ahead** — their roadmap validates ours |
| Observability of the agent | `task_history` queryable table; evals read from it | MLflow/Langfuse/OTel + ledger + episodes + audit.db — richer but **scattered**, not queryable as one table | **Different** — unify (Rec 3) |
| Config/packaging | One versioned spicepod YAML; single binary | Python service + Next.js + Qdrant + optional MLflow; workspace state across many stores | **Behind on ops ergonomics** — mine the pattern |
| Isolation per agent | Per-model table allowlists; per-tenant runtimes | User-agent connection/schema/doc scoping (prompt+store level) | **Mine** execution-level allowlists |
| RBAC/tenancy in caching | Namespace-folded cache keys | `(conn_id, sql)` keys — verified latent RLS leak | **Fix** (Rec 5) |

What Spice deliberately does NOT do (verified): no agent graph/planner, no semantic layer, no
metric governance, no ambiguity machinery, no answer verification, no investigation, no trust receipts, no
human-verdict loop. Every one of those is Aughor's product. The corollary cuts both ways: none of our guards
help if the data underneath is slow, stale, or unreachable — which is exactly the half Spice solved.

---

## Part C — Mined learnings (L1–L15)

Each: the idiom, evidence, and the Aughor mapping.

- **L1 — Acceleration is a dataset-level contract, not a cache.** Declared engine/mode/refresh with
  readiness, fallback, retention, staleness. (`runtime-acceleration/src/acceleration.rs`) → Aughor's matcache
  is per-result TTL; the missing concept is *the table mirror that stays fresh*. Basis of Rec 2.
- **L2 — Fold the principal namespace into result-cache keys; keep a raw key only for permission-independent
  results.** (`cache/src/key.rs:88–135`) → direct fix for `matcache` (Rec 5).
- **L3 — The observability table is the eval substrate.** One spans table, evals SELECT from it.
  (`task_history/mod.rs`, `text_to_sql/task_history.rs`) → unify ledger/MLflow exhaust (Rec 3).
- **L4 — Grounding must be an inspectable artifact.** `/v1/nsql/context` returns exactly what the model sees.
  (`http/v1/nsql.rs:264–297`) → input-side trust receipt (Rec 4).
- **L5 — RRF (k=60) with rank weights + recency decay beats score-blend fusion**; rerank as a separate,
  optional stage. (`runtime-search/src/rrf.rs:81–173`) → upgrade `aughor/semantic/lexical.py` (Rec 6).
- **L6 — Capabilities as overridable methods, not config flags.** A connector opts into write/CDC/append by
  overriding a default-None method; the runtime reads the vtable. (`dataconnector/mod.rs:597–720`) → Aughor's
  `DatabaseConnection` already has the shape; formalize + surface in `/capabilities` per connection (Rec 7).
- **L7 — Declarative ParameterSpec drives validation, secrets, docs, and "did you mean?" typo hints from one
  const array.** (`runtime-parameter-spec/src/lib.rs:30–155`) → upgrade `connectors/registry.py` FORM_FIELDS
  (Rec 7).
- **L8 — One `is_retriable()` classifier on the error taxonomy**; connectors translate driver errors at the
  boundary into actionable, link-bearing variants. (`dataconnector/mod.rs:410–434`) → Aughor guards classify
  SQL errors but connector/transport errors lack a taxonomy (Rec 7).
- **L9 — Readiness must be explicit, even for empty sources.** Zero-row ready envelope; queries fail-fast with
  "not ready" instead of silently reading a half-built mirror. (`cdc.rs:64–84`) → API-sync mirrors and the
  acceleration layer need a ready-state (Rec 2/7).
- **L10 — Push down by default; deny-list what can't travel.** Don't enumerate what a source *can* do —
  federate everything and surgically un-federate plans containing engine-incompatible functions.
  (`data_components/src/federation.rs`) → mirrors Aughor's `DialectCapabilities.avoid_line` philosophy;
  extend it to the federation ATTACH path when sources support live attach.
- **L11 — Discovery-first toolbelt with capability flags in tool output**, and tool descriptions that teach
  the workflow order. (`builtin/list_datasets.rs:139–141`) → Aughor's MCP tools + user-agent tools should
  return capability flags (has_metrics, has_ontology, searchable) the same way.
- **L12 — Per-agent table allowlist enforced at execution.** (`model/chat.rs:117–136`) → thread user-agent
  scope into `security_pre` as an allowlist, not just prompt scoping (Rec 8).
- **L13 — Tool-count scaling via `tool_search` meta-tool above ~20 tools.** (`tools/registry.rs:49`) → future
  concern for packs + user agents; noted, deferred.
- **L14 — The whole stack in one versioned manifest.** Spicepods validate the nao-ontology/Packs thesis:
  declarative, version-controlled, composable, override-wins. → "aughorpod" export/import (Rec 9).
- **L15 — Behavior-named enums over booleans in user-facing dataset config**; and the retention NULL-timestamp
  footgun (NULL rows never evict a `< cutoff` predicate) — audit our watermark/eviction logic for the same
  hole. → apply within Rec 2's config surface.

Also two *validations* (no action): the deterministic tool loop with a hard recursion cap confirms
"deterministic guards > LLM machinery" at industrial scale; and their failed-SQL-retry loop is something
Aughor already ships (per-question SQL retry, F1).

---

## Part D — Ranked adoption plan

All recommendations flag-gated, default-off, byte-identical when off. Ordering = leverage ÷ (effort × risk).

| # | Recommendation | Source (Spice) | Gap it closes | Dimension | Leverage | Effort | Risk | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Fix matcache tenancy: fold principal/policy into cache key | `cache/src/key.rs` | Verified latent RLS cache leak | Correctness | High | XS | None | PLANNED |
| 2 | `spice` connector (INTEROP as client) | `/v1/sql` HTTP, Postgres dialect | Data-plane breadth, freshness, acceleration — for free | Reach | Very high | S | Low | PLANNED |
| 3 | Accelerated datasets (table mirrors w/ refresh modes) | `accelerated_table/*` | No table-level acceleration; briefings/monitors/explorer re-query sources | Performance/freshness | Very high | L | Med | PLANNED |
| 4 | `task_history` spans-as-a-table + evals read from it | `task_history/mod.rs` | Observability exhaust scattered, not queryable | Observability/evals | High | M | Low | PLANNED |
| 5 | Grounding-context receipt endpoint | `http/v1/nsql.rs` | Grounding not inspectable pre-answer | Trust/debuggability | High | S | Low | PLANNED |
| 6 | RRF fusion (+ optional recency decay) in `lexical.py` | `runtime-search/src/rrf.rs` | α-blend fusion is score-scale sensitive | Retrieval quality | Med | XS | Low | PLANNED |
| 7 | Connector-contract hardening (ParameterSpec / `is_retriable` / readiness) | `runtime-parameter-spec`, error taxonomy | Param validation UX, retry policy, mirror readiness | Robustness | Med | M | Low | PLANNED |
| 8 | Per-agent table allowlist at execution level | `model/chat.rs:117` | Agent scoping is prompt/store-level only | Security/isolation | Med | S | Low | PLANNED |
| 9 | "Aughorpod" workspace bundle (export/import, versioned YAML) | spicepod | Workspace state scattered across stores | Ops/portability | Med | L | Med | DEFERRED (behind ontology arc) |
| 10 | MCP client tools for user-defined agents | `tools/mcp/*` | User agents limited to built-in tools | Extensibility | Med | M | Med | DEFERRED |

### Rec 1 — Matcache tenancy fix (correctness; do first)

**Finding (verified this session):** `aughor/db/matcache.py:56` keys on `(conn_id, sha256(sql))`;
`aughor/routers/query.py:62` checks the cache *before* `db.execute()` runs `enforce_row_policy`, and
`put_cache` at `:108` stores post-RLS rows under the pre-RLS key. With `rbac.row_policy` ON, principal A's
filtered (or unfiltered) rows get served to principal B. Inert today (row policy ships empty, triple-gated) —
but it converts a security flag flip into a data leak.

**Fix:** derive the key as `(conn_id, org_id, role_or_principal_fingerprint, row_policy_version, sha256(sql))`
whenever `rbac.row_policy` resolves active for the connection; keep the legacy key when inactive so behavior
is byte-identical for current users. Add a paired test: two roles, same SQL, different policies → distinct
entries; policy edit → old entries not served (version bump). Also audit the other cached surfaces
(`schema_cache`, exploration metric-move at `routers/exploration.py:430`) for the same pattern.
**No flag needed** — this is a guard on an existing flag's activation path. ~½ day.

### Rec 2 — `spice` connector: INTEROP as client

**What:** a new warehouse connector `spice` in `aughor/connectors/warehouse/spice.py`, registered in
`registry.py`, speaking `POST /v1/sql` (JSON accept; Arrow via ADBC/Flight as an optional extra later).
Auth = API key header. `writes_native_sql=True` with a DataFusion rules block (PostgreSQL-style dialect;
reuse most of the Postgres `_DIALECT_RULES`, add DataFusion quirks: no `QUALIFY`, `arrow_typeof`, UDTFs).
`get_schema` via `/v1/datasets` + `table_schema`-style introspection (`SHOW TABLES` / `information_schema`
works on DataFusion). `dry_run` via `EXPLAIN` (the universal binder — phase-8 principle holds).

**Why this is the highest-leverage reach move:** one connector transitively delivers every Spice source
(Iceberg, Delta, Kafka, Mongo, Dremio, SharePoint, even IMAP), plus *someone else's* acceleration and CDC.
The customer story: "already run Spice for your agents' data plane? Point Aughor at it and get a governed
analyst on top." It also gives us a lab substrate: a local `spiced` with TPC-H/TPC-DS spicepods becomes a
performance/freshness test bed for our own eval suites (Spider2 wide-schema practice included).

**Phases:** P1 connector + schema + guards battery green against local `spiced` (their quickstart runs in
2 minutes); P2 capability contract entry (`DialectCapabilities` for DataFusion) + `avoid_line`; P3 optional
Arrow transport (`adbc_driver_flightsql`) behind extra `spice`; P4 docs + live-verify vs a spicepod with an
accelerated Postgres dataset. Flag `connectors.spice`. Tests: hermetic via recorded HTTP fixtures + one
gated live e2e. ~2–3 days.

### Rec 3 — Accelerated datasets (the one real BUILD)

**What:** `aughor/acceleration/` — a dataset-level mirror service, Python-scale, no CDC:

- **Model:** `AcceleratedDataset{conn_id, table (or refresh_sql), engine: duckdb_file, refresh_mode:
  full|append, interval_or_cron, time_column?, append_overlap?, retention_period?, ready_state, last_refresh,
  last_error}` — behavior-named enums, not booleans (L15). Store: SQLite alongside existing stores.
- **Refresh orchestration:** APScheduler jobs (reuse `monitors/scheduler.py` patterns) with jitter, bounded
  retry, and **transient/permanent error classing** (L8): schema errors never retry; network errors
  Fibonacci-backoff. Append mode reuses the explorer **watermark** mechanics
  (`aughor/explorer/watermark.py`) — max(time_column) + overlap window; full mode = swap-on-success (write
  to a temp table, atomic rename — the Python-scale version of Cayenne's pointer flip, L1).
- **Readiness + fallback:** queries against a mirror that is `not ready` fall through to the source
  transparently (Spice's `on_zero_results: use_source`, inverted: we default to source and *opt into* the
  mirror when fresh). Every answer that used a mirror carries a **staleness receipt** ("data as of
  {last_refresh}") — this composes with the existing trust-receipt plane and the metrics `freshness SLA`
  contract field.
- **Wiring seam:** `DatabaseConnection.execute` already has the audited spine; acceleration slots in as a
  routing decision *above* it (resolve `(conn, table)` → mirror connection if fresh), not as a new execution
  path. The `FederatedConnection._materialise` Arrow path is the reusable copy primitive.
- **Who benefits day one:** briefings (re-query the same tables every run), monitors (interval evaluation
  hits sources today), explorer (frontier re-scans), demo fixture, and API mirrors (which already are
  mirrors — unify them under this model).

**Explicit non-goals:** CDC (`changes` mode) — that is Spice's lane; if a user needs 2-second freshness we
document the Spice-in-front pattern (Rec 2 makes it seamless). No memory-mode mirrors (DuckDB file only).
**Phases:** P1 model+store+manual refresh; P2 scheduler + append/watermark + retention (audit NULL-timestamp
eviction, L15); P3 routing seam + fallback + readiness; P4 staleness receipts in answers + UI surface
(connection page: "Accelerated tables" panel). Flag `accel.datasets`. ~1.5–2 weeks, each phase shippable.

### Rec 4 — `task_history`: spans-as-a-table

**What:** one append-only DuckDB/SQLite table with Spice's exact shape — `trace_id, span_id, parent_span_id,
task, input, captured_output, start_time, end_time, duration_ms, error_message, labels(JSON)` — written from
the kernel ledger's existing `node.span` events (`aughor/kernel/ledger.py` already emits these
unconditionally; this is a *sink*, not new instrumentation). Task taxonomy mirrors ours: `ask`, `ada.node.*`,
`tool.sql`, `tool.search`, `clarify`, `briefing.run`, `monitor.eval`, `agent.{name}`.

**Then leverage it twice:**
1. **Evals read from it** (L3): `evals/model_bakeoff.py` and the ADA ground-truth gate recover generated SQL
   and per-node latency by querying the table instead of parsing logs/MLflow — one substrate for "what did
   the agent actually do."
2. **Register it as a queryable connection** ("Aughor on Aughor"): the fixture gains an `aughor_ops` schema
   so Deep Analysis can investigate its own behavior — "why were yesterday's briefings slow?" is just an
   investigation. This is a demo-able differentiator Spice cannot match (they can query task_history; they
   don't have an investigator to point at it).

Flag `obs.task_table`. MLflow/Langfuse remain the rich-trace backends; this is the queryable spine. ~3–4 days.

### Rec 5 — Grounding-context receipt

**What:** `GET /ask/context?connection=...&question=...` (+ a "Show grounding" affordance in the answer UI)
returning the exact assembled grounding block: schema slice chosen, glossary entries, governed-metric
bindings, ambiguity-ledger priors applied, value-index literal bindings, dialect rules block, and which pack
bindings are active — as JSON and rendered markdown. Implementation is mostly *extraction*: the assembly
already happens inside plan/generate nodes; factor it into a pure `build_grounding_context()` that both the
agent and the endpoint call (single source of truth, no drift).

**Why:** it is the input-side twin of the trust receipt; it makes Spider2/eval iteration dramatically faster
(inspect grounding without running the model); and it de-mystifies answers for users ("what did it know when
it answered?"). Flag `ask.context_receipt`. ~2 days.

### Rec 6 — RRF fusion in retrieval

Swap `hybrid_rerank`'s min-max α-blend (`aughor/semantic/lexical.py`) for Reciprocal Rank Fusion (k=60,
rank weights, 4× candidate pool), optional exponential recency decay for episode/prior-analysis retrieval.
Rank-based fusion is robust to score-scale mismatch between Qdrant cosine and BM25 — the exact failure mode
α-blending has. Keep α-blend behind the old path; flag `search.rrf`; A/B on the KB-retrieval evals before
flipping. ~½ day.

### Rec 7 — Connector-contract hardening (MINE bundle)

Three small idioms into the existing contract, one PR:
1. **ParameterSpec-style registry entries** (L7): extend `FORM_FIELDS` with `required/default/one_of/secret/
   deprecated/help_link`, validate on create with Levenshtein "did you mean" for unknown params.
2. **`is_retriable` error taxonomy** (L8): a `ConnectorError` classification (auth/config/name = permanent;
   network/timeout/not-ready = transient) consumed by API-sync retries, monitors, and Rec 3's refresher.
3. **Readiness semantics** (L9): API-sync mirrors and accelerated datasets expose
   `ready_state ∈ {ready, refreshing, error, empty_but_ready}`; `/capabilities` and the connection UI show it.
Flag not needed for 1–2 (additive validation); `accel` flags cover 3. ~3 days.

### Rec 8 — Per-agent table allowlist at execution level

User-defined agents declare connection/schema scope today, enforced at prompt/store level. Thread an
explicit table allowlist (from agent scope ∩ RBAC ceiling) into `security_pre` so an agent's SQL that
references an out-of-scope table is *blocked at execution*, mirroring Spice's `create_table_allowlist`
(L12). Composes with the existing dunder-label audit trail (every query already carries agent identity).
Flag `agents.table_allowlist`. ~2 days.

### Rec 9 / Rec 10 — Deferred

- **Aughorpod** (L14): export/import the workspace (connections sans secrets, ontology YAML, glossary,
  metrics, packs, user agents) as one versioned folder. Defer until the nao-inspired editable-ontology arc
  lands its YAML tree — the bundle should be *that* tree plus siblings, not a second format.
- **MCP client tools for user agents** (L13): `tools: [mcp:{url}]` on a user agent, governed + traced.
  Defer until user-defined agents graduate their flag; needs a permission story (external tool calls are an
  egress surface).

### Sequencing

Wave 1 (correctness + reach): Rec 1 → Rec 6 → Rec 2.
Wave 2 (substance): Rec 3 (phased) with Rec 7 riding along.
Wave 3 (trust + evals): Rec 4 → Rec 5 → Rec 8.
Deferred: Rec 9, Rec 10.

---

## Part E — Closing

### Deliberately NOT ported (grounded findings)

- **Rust runtime / single binary** — Aughor's value is the intelligence plane; a rewrite buys latency we
  don't need at answer-granularity. Ops ergonomics improve via Rec 9 instead.
- **Arrow Flight / FlightSQL / ADBC serving** — Aughor serves answers and receipts, not record batches.
  (Consuming ADBC in the Spice connector is different and in-plan.)
- **Ballista distributed compute, Cayenne, Vortex** — petabyte compute is a substrate concern; that's what
  Rec 2 outsources. The pointer-flip/off-fence *idioms* were mined (L1) at Python scale.
- **Log-based CDC** — the highest-engineering-cost subsystem in Spice (deferred acks, exactly-once replay,
  slot management). Python + APScheduler cannot credibly replicate it; fronting with Spice can.
- **Cedar policy engine** — Aughor's RBAC + declarative row-policy covers the need; Cedar adds a language,
  not a capability, at our scale. Revisit only if customers bring existing Cedar policies.
- **Local model serving (mistral.rs/Candle), embedding servers** — we already externalize models by design
  (P7 is an ops decision, not a serving-stack decision).
- **LLM tool loop as the agent architecture** — Spice's loop is admirable minimalism for *their* product;
  Aughor's LangGraph investigation graph with interrupt gates IS the product. No convergence.

### Residual uncertainties

- Spice Enterprise vs OSS boundary: Cedar/PII masking/K8s operator appear enterprise-side; OSS tree contains
  Cayenne + cluster crates. If we lean on Rec 2 for CDC-grade freshness, verify which refresh modes are OSS
  at the version we pin (the `changes` code paths are in-tree today).
- DataFusion dialect quirks for the `spice` connector guard rules need empirical collection in P1 (sqlglot
  has a `datafusion`-adjacent story via `postgres`, but UDTFs like `text_search` won't transpile — native
  rules block required).
- `/v1/sql` JSON row limits / pagination behavior at large results — check `Accept: application/vnd.apache.arrow.stream`
  support before deciding P3's transport priority.
- Their task_history retention defaults (accelerated + retention-bounded) — pick our own retention for
  `obs.task_table` deliberately (audit.db precedent: append-only WAL + explicit eviction).

### Key sources

- Source clone: `github.com/spiceai/spiceai` @ `cb96c9f` (trunk, 2.1.0-unstable) — crates cited inline.
- Docs: spiceai.org/docs (components, MCP, deployment), spiceai.org/docs/features/large-language-models/mcp.
- Spice 2.0 announcement: spice.ai/blog/spice-2-0-is-now-available (Cayenne GA, Ballista GA, CDC ~170× vs
  Debezium-based, CH-BenCHmark HTAP numbers).
- Engineering posts: spice.ai/blog/apache-ballista-at-spice-ai (multi-active schedulers, OCC via ETag,
  set-cover partition placement); spice.ai/blog/vortex-at-spice-ai… (compute-on-encoded-data, deletion
  vectors); spice.ai/blog/multi-tenancy-for-ai-agents-without-pipelines (four isolation tiers).
- Founder interview (2.0 launch, "CV Deep Dive" w/ Luke Kim): the 10,000-isolated-engines project; Barracuda
  100× faster at 50% lower cost; "the model was never the hard part"; five-year vision = closing the
  feedback loop.
