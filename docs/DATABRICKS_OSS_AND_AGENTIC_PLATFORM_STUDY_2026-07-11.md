# Databricks OSS Stack × Aughor — Integration Study & the Agentic Platform Direction

*Date: 2026-07-11. A two-part study: (A) every open-source project on
[databricks.com/product/open-source](https://www.databricks.com/product/open-source) assessed for
integration into Aughor — roadmap, rationale, advantages per project; (B) the follow-on direction it
unlocked: turning Aughor from a data-intelligence platform into an **agentic data-intelligence
platform** (user-created, domain-specific agents — "Gems on governed data"), with MLflow as the
lifecycle plane.*

*Build status (2026-07-11, branch `2026-07-11-obs-mlflow-tracing`): **A1-P1 shipped** (`obs.mlflow`
tracing — telemetry-seam third backend, mlflow-skinny); **A1-P2 shipped** (`evals/model_bakeoff.py`
— P7 through `mlflow.genai.evaluate` with deterministic scorers, live-verified); **B4-P1 slices 1–5
shipped** (`agents.user_defined` — the Agent entity + /ask binding + builder UI + deep path
(persona persisted in checkpointed state with resume re-activation, brief on the synthesis
prompt, agent-scoped deep doc retrieval) + schema scoping & pack-preference bindings + measured
agents (per-agent golden questions, deterministic evaluate, "n/m passing" chip — B Phase 3);
live-verified). Remaining: auto-eval-on-edit, the PDF exit-criterion run, per-agent ledger
crystallization (deliberately deferred — see ROADMAP §0), A1-P3, Part-A connectors
(UC/lakehouse/Redash patterns), per Part C sequencing. **2026-07-11 post-merge: Part E added**
— the six-point platform critique + second assessment (MLflow-underneath Agent Workspace ·
open-swe learnings · adaptive capabilities · learning visibility · wired-vs-surfaced audit),
with the revised next-wave sequencing in E6.*

*Build status (2026-07-11, branch `2026-07-11-mlflow-agent-workspace`): **E6 item (1) —
the MLflow-underneath Agent Workspace — shipped** across five slices. **Slice 1**: `agent_id`
is now a first-class column on the `investigations` run row (additive Migration(3), persisted
from the active-persona contextvar), so per-agent run history is joinable (the E1/E5 schema
fix). **Slice 2**: MLflow traces are attributed with `mlflow.trace.session` /
`mlflow.trace.user` (via `update_current_trace`'s dedicated kwargs) + an `agent_id` tag — all
ambient from request-scoped contextvars (new `session` contextvar in `org/context.py`, pinned
by an `/ask` stream wrapper), so MLflow's Sessions / user / per-agent / cost views populate
with no threading through the graph. **Slice 4a**: `GET /agents/custom/{id}/observability` —
per-agent run history + optional MLflow trace stats (`telemetry.agent_trace_stats`, filtered by
the `agent_id` tag), degrading to history-only when tracing is off (B3's one-directional rule).
**Slice 4b**: the **Agent Workspace** (`web/components/AgentWorkspace.tsx`) — one
perspective-switched surface (an instance of the `<Workspace>` shell) with **Overview** (native
cards over the observability endpoint — MLflow stays backend-only, the "native cards first"
decision over embedded iframes), **Manage** (the existing builder), and **Fleet** (the built-in
fleet, folded in as the operations layer; the Agents + Fleet rail items are now two deep-links
into one workspace). **Deferred by the native-cards decision**: slice 3 (per-agent MLflow
experiments — feasible via `set_destination(context_local=True)`, only needed for iframe
deep-linking) and slice 5 (embedded iframe views — E1's no-per-user-auth caveat). Live-verified
end-to-end (both/all-three layers render, real endpoint data with MLflow-off degradation, clean
switching, zero console errors); full unit suite green; all flag-gated / default-off. **NEXT
per E6**: (2) Learning Receipt + Memory layer (E4), (3) Capabilities Auto-mode (E3), (4)
double-texting + reviewer-loop (E2); the Part-A lakehouse connector family remains queued in
parallel.*

*Method: five parallel research passes (Unity Catalog OSS · Redash · MLflow 3.x GenAI · the
Delta/Iceberg/Delta-Sharing lakehouse stack · an Aughor repo seam-map), each grounded against primary
sources (GitHub APIs, official docs, release notes) current as of 2026-07-11, then cross-checked
against the actual Aughor code. Every named Aughor seam in this doc was verified in the repo, not
recalled. This is a **direction document** — nothing here is built; everything proposed follows the
house rules: deterministic-first, flag-gated default-off, BUILT→WIRED→TESTED→LEVERAGED.*

---

## TL;DR

**Part A verdicts** (all 14 projects on the page):

| Project | Verdict | One line |
|---|---|---|
| **MLflow 3.x** | **ADOPT** — highest leverage on the page | The agent-engineering substrate Aughor lacks: tracing, evals, prompt/agent versioning, cost — all fully OSS as of 3.13/3.14 |
| **Unity Catalog** | **INTEROP as client** — never embed | Small stable REST read surface reaches both OSS and Databricks-hosted UC; OSS UC's governance is *weaker* than Aughor's own RBAC |
| **Delta Lake · Iceberg · Delta Sharing** | **BUILD one "Connect to Lakehouse" connector family** | DuckDB's `delta`/`iceberg`/`uc_catalog` extensions went stable May 2026 — zero-JVM reach into the open lakehouse |
| **Redash** | **MINE 4 patterns**, adopt no code | Alive-but-maintenance-mode; not importable; four workflow patterns transfer directly |
| **Apache Spark** | SKIP | Producer-side tool; DuckDB is right-sized for a read-mostly single-node platform |
| scikit-learn · XGBoost | LATER, evidence-gated | Anomaly detectors for monitors; feature-importance as a WHY-lens *candidate ranker* |
| TensorFlow · PyTorch · Keras · RStudio | SKIP | No deep-learning surface in scope |
| Terraform | LATER | Self-hosting module, post-public-flip nicety |

**The two-plane thesis.** The stack offers Aughor two complementary planes it does not have, and they
compound: a **data-facing plane** (UC/Iceberg/Delta/Sharing connectors → the open lakehouse estate
where enterprise data actually lives) and an **agent-facing plane** (MLflow → observability, evals,
versioning, cost for the investigation agents). Combined positioning: *Aughor is the
investigation-intelligence layer over the open lakehouse, run with MLflow-grade agent-engineering
discipline.*

**Part B thesis.** The agentic-platform vision ("users create domain agents; uploaded documents become
persistent context — Gemini-Gem-like, but on live governed data") is ~70% substrate-complete in the
repo today: Packs already bundle expertise docs + entities + metrics + **their own evals**; Volumes
already do artifact upload; `kernel/agents.py` already models charters + budgets + governance + spend.
**The missing piece is "Agent" as a first-class product entity** binding
{instructions + documents + packs + scope + governance}, plus the MLflow lifecycle loop that makes
user-created agents *measured* instead of vibes. The differentiator vs Gems/Custom GPTs: an Aughor
agent is **governed** (fail-closed RBAC scope), **grounded** (deterministic guards + trust receipts),
and **measured** (per-agent golden questions, eval-on-edit, rollback).

---

# Part A — The Databricks open-source stack, project by project

## A1 · MLflow 3.x — the AI Engineering Platform (ADOPT)

### A1.1 State of the project (verified 2026-07-11)

- Latest **3.14.0 (2026-06-17)**; MLflow 3.0 (2025-06-11) repositioned the project as an "open source
  AI engineering platform." Apache-2.0, Linux Foundation, ~monthly minors, ~30–35M monthly downloads.
- The 2026 releases matter most: 3.9 (judge builder + online scoring) · **3.10 (automatic dollar-cost
  tracking per trace, multi-workspace)** · 3.11 (native OTel GenAI semantic conventions, gateway
  budget limits) · 3.12 (multimodal tracing, gateway guardrails) · **3.13 (RBAC + Admin UI in OSS,
  trace retention/auto-archival to object storage, official Helm charts)** · **3.14
  (`mlflow agent setup`, Review Queues for structured human feedback, `@mlflow.test` pytest CI
  gates, LLM Playground)**.
- **The OSS/managed boundary, precisely** (this was the make-or-break check — it passed):
  - *Fully OSS:* tracing incl. OTLP ingest at `/v1/traces`, `search_traces`, `mlflow.genai.evaluate`
    + all built-in LLM judges (judge model pluggable via LiteLLM URIs — Anthropic/local work),
    custom `@scorer`s, eval datasets, online scoring loop, Review Queues,
    `log_feedback`/`log_expectation`, Prompt Registry, `LoggedModel` versioning, AI Gateway
    (budgets/guardrails/playground), cost tracking, RBAC, workspaces, archival, `@mlflow.test`.
  - *Databricks-managed only:* the polished Review App / expert-labeling UI, fully managed
    production monitoring (serverless scheduled judges), UC governance over traces, notebook-inline
    trace UX, managed agent deployment.
- vs LangSmith/Langfuse/Phoenix: those are tracing-first; MLflow is the only Apache-2.0 option
  covering the full wishlist (traces + evals + prompts + versions + cost + gateway) in one
  self-hosted system, with LangChain autolog that natively understands **LangGraph** node structure.

### A1.2 Why it fits Aughor (rationale)

Aughor's Deep Analysis agent is a LangGraph graph
(`aughor/agent/graph.py`) fanning out parallel explore waves with dozens of LLM calls + SQL
executions per investigation — and it has **no observability backend**. The verdicts/evidence/
ambiguity stores are the *product* trust substrate (user-facing); there is no *engineering* substrate
(engineer-facing traces, cross-run comparison, cost accounting, regression gates beyond homegrown
scripts). `docs/INTERACTIVE_DATA_AGENT_VISION_2030.md` names this exact gap: *"Measure interaction
skill: ❌ we measure single-turn EX only."*

**The decisive technical fit:** MLflow trace-context propagation is contextvars-based; its prescribed
thread fan-out pattern is `ctx = contextvars.copy_context(); executor.submit(ctx.run, …)` — which is
**exactly what `aughor/kernel/concurrency.py::ContextThreadPoolExecutor` already does** (and it is
installed as the app-default executor in `api.py`). Parallel explore waves should nest under a parent
investigation trace with near-zero integration work. (Verify empirically in Phase 1 — the docs
pattern is manual `ctx.run`; ours is structural.)

### A1.3 Advantages, mapped to queued work

1. **P7 becomes evidence-based.** The #1 queued item (ROADMAP §0: pin a frontier `coder` model) turns
   into a scored bake-off: `mlflow.genai.evaluate` over a dataset built from
   `tests/integration/test_ada_ground_truth.py` + golden sets, per candidate model, with automatic
   cost/latency per run → quality × $/investigation × latency, defensible and repeatable.
2. **Deterministic guards become scorers.** `@scorer` wraps arbitrary Python returning `Feedback` —
   grain guard, join guard, window guards, coherence checks become first-class eval metrics with no
   LLM judge. Deterministic-first expressed *inside* their harness, not replaced by it.
3. **Prompt Registry + `LoggedModel`** = investigation-agent versioning: every trace and eval run
   links to an agent version (git SHA + pinned prompts); regressions become UI diffs.
4. **`@mlflow.test`** turns the hermetic answer-quality gate into CI enforcement across model/prompt
   changes.
5. **Fleet observability** for the parallel-agents future: per-investigation trace trees
   (plan gate → waves → per-subquestion SQL → guards → refutation), session grouping,
   `search_traces` filtering by tag/user/status/latency, dollar totals per investigation.

### A1.4 Integration roadmap (each phase flag-gated, default-off)

1. **Phase 1 — Tracing** (~days): `mlflow` service in `docker-compose.yml`; flag `obs.mlflow` in
   `aughor/kernel/flags.py`; at startup `mlflow.langchain.autolog()` + provider autolog;
   `@mlflow.trace(span_type="AGENT")` on the investigation entrypoint
   (`aughor/routers/investigations.py`); TOOL spans around `aughor/sql/executor.py` and the guard
   gate so non-LLM steps appear in the tree. **Exit criterion:** one live Deep run renders as a
   complete trace tree with per-wave nesting.
2. **Phase 2 — Evals + P7 bake-off** (~1–2 weeks): guards as scorers; ground-truth suite as an eval
   dataset; run the model bake-off; `@mlflow.test` in CI.
3. **Phase 3 — Lifecycle**: planner/synthesizer prompts into the registry; `set_active_model`
   versioning; cost dashboards reconciled with `kernel/metering.py::RunMetrics`.
4. **Phase 4 — Feedback loop**: Review Queues ↔ verdicts-store bridge. **Boundary rule:** MLflow is
   the engineer-facing plane; evidence ledger + Trust Receipt remain the user-facing product. Keep
   them separate; bridge, don't merge.

### A1.5 Sharp edges (from research; all manageable)

- Pin **≥3.13/3.14** (OSS RBAC/workspaces/archival are ≤6 months old; a real Postgres+S3
  trace-consistency bug lived in 3.9.0, fixed).
- Async trace logging queue (default 1000) **silently discards on overflow** — tune
  `MLFLOW_ASYNC_TRACE_LOGGING_MAX_QUEUE_SIZE`/workers for parallel waves; load-test.
- The slim `mlflow-tracing` package **cannot coexist** with full `mlflow` in one env — use the full
  package everywhere (the eval harness needs it anyway).
- LangChain autolog + `ainvoke()` may need `run_tracer_inline=True`; can merge sequential
  invocations unexpectedly.
- Server is FastAPI + SQL, not a columnar trace store — at volume: Postgres backend, span offload to
  artifact store, 3.13 archival.

---

## A2 · Unity Catalog — interop as a client; never embed (INTEROP)

### A2.1 State of the project (verified 2026-07-11)

- OSS server **v0.5.0 (2026-06-18)**; Apache-2.0; donated to LF AI & Data June 2024 and **still
  Sandbox tier** (contrast: Apache Polaris graduated to ASF Top-Level Project 2026-02-18). ~3.45k
  stars; committers overwhelmingly Databricks; cadence tightened to ~2 months in 2026 but still
  pre-1.0 after two years. v0.4.1 fixed a JWT issuer-validation bypass (CVE-2026-27478).
- **What's in the OSS server:** 3-level namespace (`catalog.schema.asset`); tables (Delta primary,
  Iceberg, external Parquet/CSV/JSON), volumes, functions, ML models, experimental **metric views**
  (0.5.0); credential vending (`/temporary-table-credentials` etc., S3/GCS/ADLS temp creds);
  Iceberg REST endpoint; flat per-securable grants + OAuth/OIDC/SCIM2 (authorization **opt-in**,
  default open).
- **What's NOT in OSS** (proprietary-only): lineage, audit logging, discovery/search, tags, ABAC,
  RBAC roles, row/column security, Delta Sharing integration. The OSS server is a
  reimplementation, not what Databricks runs; the roadmap marks governance features "?".
- **Client compatibility:** the REST shape is the same against OSS and Databricks-hosted UC
  (`/api/2.1/unity-catalog/...`) — one read client covers both. Two gotchas: Databricks-hosted
  requires the metastore "external data access" toggle **plus** the `EXTERNAL USE SCHEMA` privilege
  (never implied by ALL PRIVILEGES); and the Iceberg REST path differs (OSS `/iceberg/`, hosted
  `/iceberg-rest`). Official PyPI SDK: `unitycatalog-client` 0.5.0; `unitycatalog-ai` 0.4.0 exposes
  UC *functions* as LLM/agent tools.
- Ecosystem chose the client role: DuckDB (`uc_catalog` + `delta` extensions, stable per DuckDB's
  2026-05-07 post, reads + INSERT against both OSS and hosted UC), Trino, Daft. Nobody embeds the
  server.

### A2.2 Verdict & rationale

**Embed: no.** A Java-17 sidecar, Sandbox maturity, pre-1.0 churn — to obtain a flat grant model
*weaker* than `aughor/rbac/` already is (roles + row policies + fail-closed RLS compiled into the
WHERE at every connector's execution gate, `sql/rls.py`). Its experimental metric views would collide
with the editable ontology rather than power it.

**Client: yes, cheap and strategic.** One connector reaches every Databricks enterprise account plus
the OSS/self-hosted world. And the *differentiating* move is not querying — it's harvesting UC
metadata (table/column comments, metric-view YAML) into Aughor's grounding substrate with
provenance: the schema linker, glossary, and ambiguity ledger get a head start on every UC-governed
warehouse. Grounding-first is the house thesis.

### A2.3 Roadmap

1. **UC connector** (~1–2 weeks): new connector under `aughor/connectors/warehouse/` implementing the
   `connectors/base.py` contract. Two layers: DuckDB `uc_catalog`+`delta` `ATTACH` for querying;
   `unitycatalog-client` for metadata (`GET /catalogs`, `/schemas?catalog_name=`,
   `/tables/{full_name}` with column comments). Auth PAT / OAuth service principal. Encode both
   gotchas in `db/capabilities.py` (the connector-capability contract exists for exactly this).
2. **Metadata harvest → substrate**: pipe comments/metric-views through `aughor/metastore/sync.py`
   into ontology/glossary as seed material with provenance.
3. **Later — `unitycatalog-ai`**: customer's governed UC functions as pack-declared agent tools
   (feeds Part B Phase 4). Evidence-gate.

What we deliberately don't get from OSS UC (lineage, audit) Aughor already captures itself at query
time (audit.db, evidence ledger).

---

## A3 · Delta Lake + Apache Iceberg + Delta Sharing — one "Connect to Lakehouse" connector family (BUILD)

### A3.1 The 2026 state that makes this timely (verified)

- **DuckDB extensions exited experimental May 2026** (blog 2026-05-07 "Delta Grows Up"; pin
  **DuckDB ≥1.5.3**): `delta` — reads with deletion-vector support, filter/projection pushdown, time
  travel, writes = blind `INSERT` appends only (no UPDATE/MERGE/DELETE/DDL); `iceberg` — full
  read/WRITE via REST-catalog `ATTACH` (MERGE INTO, schema evolution, Iceberg v3 incl. deletion
  vectors, 1.5.3 / May 2026); `uc_catalog` — attaches OSS and hosted UC.
- **Iceberg REST Catalog = the neutral catalog API of 2026**: Polaris (ASF TLP), Lakekeeper, Glue
  REST, S3 Tables, R2, Snowflake Open Catalog, and UC all speak it. Credential vending (short-lived
  table-scoped storage tokens) is standard across Polaris/Lakekeeper/UC/Snowflake — **Aughor never
  holds the customer's raw S3 keys**. Exception: Glue REST does **not** vend credentials.
- **Python-native (no JVM/Spark):** `deltalake` (delta-rs) 1.6.2 (2026-07-08) for Delta
  metadata/maintenance; PyIceberg 0.11.1 for catalog/metadata ops.
- **Delta Sharing:** recipient needs only a **profile file** (endpoint + bearer token JSON) + the
  `delta-sharing` pip client — no Databricks infrastructure or account, verified. Reads incl.
  DV/column-mapped tables via the delta-kernel wrapper (`responseFormat=delta`; some third-party
  servers, e.g. Microsoft Fabric's, don't support it). Read-only by design. 2026-06-10: protocol
  moved to the Linux Foundation as **"OpenSharing"** — superset covering data + *models/agents/
  skills*, Iceberg support, external catalogs; existing clients keep working.
- **Spark: not needed.** Residual Spark-only jobs are producer-side (creating UC-managed tables,
  UniForm enablement, large distributed writes). Spark Connect thins the client but still requires a
  JVM cluster — irrelevant for a read-mostly DuckDB platform.

### A3.2 Roadmap (priority order)

1. **Iceberg-REST-catalog connector** — `ATTACH (TYPE iceberg, ENDPOINT …, SECRET …)`; OAuth2
   client-credentials or SigV4 via DuckDB Secrets. One connector covers the whole open-catalog
   estate incl. UC's Iceberg endpoint (UniForm Delta tables appear here too). Catalog discovery
   (namespaces/tables) replaces "paste a table URI." PyIceberg in the Python layer for catalog
   flavors DuckDB lacks (Hive/SQL-catalog).
2. **Delta path connector** — `delta_scan`/`ATTACH` for raw S3/GCS/Azure Delta (Databricks-native
   customers); `deltalake` for history/metadata. Read-mostly is fine (DV reads solved everywhere).
3. **Delta Sharing connector** — profile JSON as a registry secret (`db/registry.py`, Fernet);
   `SharingClient` for share/schema/table discovery; Arrow → DuckDB for reads. "Investigate the data
   your vendor/partner shares with you" as a connector type. Watch OpenSharing for agent/skill
   sharing (ties into Part B Phase 4 distribution).

### A3.3 Sharp edges → capability-contract entries (`db/capabilities.py`)

- One credential type per DuckDB secret (multi-source credential-chain resolution is flaky).
- Glue REST vends no credentials → separate storage creds there.
- Column mapping: mandatory on UniForm/common on Databricks tables; DuckDB-delta support was
  historically partial — **test against a real Databricks column-mapped table before GA**.
- Delta Sharing pushdown (`jsonPredicateHints`) is best-effort server-side — always re-filter
  locally.
- Extension upgrades are tested events (kernel-pin lag history); pin DuckDB ≥1.5.3.

---

## A4 · Redash — mine four patterns; adopt no code (MINE)

### A4.1 State (verified — corrects the common "dead project" narrative)

- **Alive, community-maintained, maintenance-plus mode.** BSD-2. Post-acquisition freeze
  (v10, 2021) → community reboot (2023, founder as BDFL) → CalVer releases **v25.1.0 → v25.8.0 →
  v26.3.0 (2026-03)**; repo pushed 2026-07-09; ~96 commits in 2025. Work = security/deps/small
  fixes; no ambitious roadmap. Frontend debt: React 16 + AntD 4 + d3 v3 (Plotly kept current).
- **Not consumable as a dependency:** not on PyPI; the ~70 query runners import the monolith's
  settings/models/permissions; `requires-python ==3.13.*` with ~60 exact pins. Embedding surface is
  its weakest part: unsigned iframe embeds, viewer-mutable params — docs themselves say wrong tool
  for untrusted-audience embedding. Permission model (group-based, two levels, no RLS) is thinner
  than Aughor's RBAC.
- 2026 alternatives comparison: Superset/Metabase/Grafana/Lightdash all have stronger trajectories;
  "pick Redash only if you already run it" is directionally right for new BI deployments.

### A4.2 The four patterns that transfer (and where they land)

1. **QRDS — Query Results as a Data Source** (`query_runner/query_results.py`): SQL over cached
   prior results in in-memory SQLite, with per-source permission re-checks. Aughor's version is
   strictly stronger: **DuckDB-native SQL over the artifacts store + trusted queries + prior
   investigation findings** → *investigations become data sources* (a follow-up agent queries prior
   findings). Directly serves the BIRD-INTERACT "state-dependent follow-ups" gap and makes the
   evidence ledger compound. Seams: `artifacts.db`, `semantic/trusted_queries.py`,
   `db/matcache.py`.
2. **Typed "safe parameters":** free-text params banned from published/embedded contexts; only typed
   (number/date/enum/query-backed dropdown) parameters cross the trust boundary. Adopt verbatim for
   parameterized trusted queries and shared canvases.
3. **Per-query API key + `max_age` cached results:** scoped programmatic access to one trusted
   query's results without a full user token — the cheap, safe "embed an Aughor answer in your
   wiki/app" surface, with Aughor RBAC/RLS underneath (which Redash's own embeds lack).
4. **Alert-destinations catalog + `annotate_query`:** thirteen ~100-line destination modules
   (Slack/Teams/PagerDuty/webhook/…) → replicate for `briefs/delivery.py` + monitors;
   `annotate_query` (inject `/* user, investigation_id */` into generated SQL) → warehouse-side
   audit attribution for near-zero effort.

Bonus benchmark when next touching connectors: `BaseQueryRunner`'s JSON-schema-driven connection
forms + `noop_query` test-connection + sqlparse auto-LIMIT — a good UX bar for `connectors/base.py`.

---

## A5 · The rest of the page (short verdicts)

- **scikit-learn** — LATER: only when a specific detector is needed (IsolationForest/changepoint for
  `aughor/monitors/` anti-flap + anomaly triage). Aughor already ships scipy/statsmodels.
- **XGBoost** — LATER, evidence-gated: gradient-boosted feature importance as a **WHY-lens candidate
  ranker** (rank which dimensions explain a metric shift; every candidate is then
  execution-verified with grounded SQL). Fits deterministic-first only as a hypothesis ranker —
  same discipline as the deferred deeper-WHY-lenses rework.
- **TensorFlow / PyTorch / Keras / RStudio** — SKIP: no deep-learning surface; embeddings come via
  LLM providers + Qdrant.
- **Terraform** — LATER: a self-hosting module once the repo flips public; docker-compose covers the
  near term.
- **Apache Spark** — SKIP (see A3.1).

---

# Part B — The Agentic Data Intelligence Platform

*The vision (user-stated): users create agents for multiple use cases — domain-specific agents,
Gemini-Gem-like: upload documents/artifacts that become the agent's persistent context on every run.
Aughor becomes a true agentic data-intelligence platform.*

## B1 · The framing that makes it defensible

"Users can create agents" is table stakes — Gemini Gems, Custom GPTs, Copilot Studio all do it. The
defensible version is what only Aughor's substrate enables: **a governed, grounded, measured agent.**

| | Gem / Custom GPT | Aughor Agent |
|---|---|---|
| Context | files stapled to a prompt | documents + packs + ontology + ledger priors, retrieved per-run |
| Data access | none / plugins | live governed connections, fail-closed RBAC + row policies |
| Answer trust | vibes | deterministic guards + evidence ledger + Trust Receipt on every answer |
| Quality over time | unknowable | per-agent golden questions, **eval-on-edit**, versioned rollback |
| Learning | none | corrections crystallize into the ambiguity ledger (override-wins, per scope) |

This is also the convergence point of three existing arcs: the Palantir AI-FDE study (Aughor has the
reasoning backend, lacks the *user-owned context* command surface), Domain Expertise Packs, and
BIRD-INTERACT (the interactive-agent direction + its measurement gap).

## B2 · Substrate inventory — what already exists (verified in-repo 2026-07-11)

| Capability | Where | State |
|---|---|---|
| Declarative domain bundle | `packs/customer-analytics/` — `pack.yaml`, `expertise.md`, `entities.yaml`, `questions.yaml`, `metrics/*.yaml`, **`evals/*.eval.yaml`** | Shipped (flag `specialist_packs`, Phase A). A pack already bundles expertise docs + semantics + its own eval set — the Gem skeleton |
| Artifact upload | `routers/volumes.py` — `put_object`/`list_objects`/`get_object_content` per catalog | Shipped (volumes.db) |
| Fleet governance | `kernel/agents.py` — `AgentCharter`, `Budget`, `Governance`, `effective_governance()`, `set_governance()`, `is_enabled()`; `routers/agents.py` roster + spend aggregation from metered jobs | Shipped for *built-in* agent kinds — the exact model user agents need |
| Document retrieval | `semantic/kb_loader.py`, `kb_retriever.py`, `connection_kb.py` (Qdrant-backed) | Shipped; **global/per-connection today, not per-agent** |
| Declarative behavior | `agent/modes/manifests/` — `direct/explore/investigate/final_text.yaml` | Shipped |
| Scoping value object | `canvas/scope.py::ExecutionScope` (NOM-11; used by `routers/investigations.py`) | Shipped — the natural carrier for agent scope |
| RBAC + row policies | `aughor/rbac/` + `sql/rls.py` (fail-closed, AST-compiled WHERE) | Shipped |
| Autonomous runs | `briefs/scheduler.py` + `monitors/scheduler.py` (APScheduler cron) | Shipped |
| Replayable plans | `agent/program_planner.py` + `semantic/trusted_programs.py` (flag `plan.program`) | Shipped |
| Cost metering | `kernel/metering.py::RunMetrics` (contextvar; `record_llm`/`record_query`) | Shipped |
| External exposure | `aughor/mcp/server.py` + `client.py` | Shipped |
| Durable learning | `semantic/ambiguity_ledger.py` (override-wins crystallization) + `verify/priors.py` read-back | Shipped, live-proven |

**The gap:** no product entity binds these. Nothing named "Agent" carries
{instructions + documents + packs + connection/schema scope + governance} through intake. The
capability exists; the wiring is the feature — the recurring Aughor pattern (cf. the report-quality
arc: quality was wiring between subsystems, not missing subsystems).

## B3 · Division of labor — Aughor runtime, MLflow lifecycle

**Aughor owns the runtime and context assembly** (LangGraph spine, guards, retrieval, scope — none of
it changes per agent). **MLflow owns the lifecycle** — exactly the part that would otherwise be a
from-scratch build:

1. **Instructions = Prompt Registry entries.** Immutable versions + commit messages; mutable aliases
   (`@production`, `@draft`). Edit → new version; publish = alias move; rollback = alias move back;
   diffs in the UI. The whole edit/publish/rollback UX for free.
2. **Agent version = `LoggedModel`.** `mlflow.set_active_model(name=f"agent:{agent_id}@{version}")`
   at run start → every trace + eval run links to that version. "Did v4 of the Finance agent get
   worse after the new policy PDF?" = a UI comparison.
3. **Per-agent observability + chargeback.** Traces tagged `agent_id`/`user`/`session` + 3.10 cost
   tracking = per-agent spend with trace drill-down; deepens the spend aggregation
   `routers/agents.py` already computes from `RunMetrics` (tokens → dollars-per-answer).
4. **The quality loop (the differentiator).** Pack `evals/*.eval.yaml` + creator-supplied golden
   questions → `mlflow.genai.datasets` per agent; deterministic guards as `@scorer`s;
   **eval-on-edit**: instruction edits or document uploads trigger `evaluate` before the
   `@production` alias moves — "your agent still passes 11/12 golden questions; here's the
   regression."
5. **Human feedback → substrate.** Review Queues route low-confidence agent answers to domain
   experts; accepted corrections crystallize into the ambiguity ledger scoped to the agent's
   connections (source=user, override-wins) — durable learning in the existing mechanism, not a
   fine-tune black box.
6. **Budgets.** AI Gateway per-endpoint budget limits (3.11) or charter budgets via
   `kernel/agents.py` — mandatory before self-serve agent creation.

**Direction of dependency (hard rule):** the Agent entity lives in Aughor's store with RBAC on it;
MLflow is the system of record for versions/traces/evals only. If MLflow is down, agents still run
(tracing degrades gracefully; aliases resolve from cache). One-directional.

## B4 · Build plan

**Phase 1 — Agent entity + Gem-parity MVP** (~2–3 weeks; the biggest single step):
- Store: `agents.db` — `{id, name, instructions, connection_scope, schema_scope, pack_ids,
  volume_refs, mode_policy, owner, governance}`. Back it with `kernel/agents.py` charters (extend,
  don't duplicate — the charter/governance/budget model is already right). Naming caution:
  `routers/agents.py` exists for the built-in fleet; the user-agent surface should extend it, not
  collide.
- **Context assembly at intake:** `/ask?agent_id=…` threads the agent through `ExecutionScope`; ADA
  intake + quick path receive pinned instructions, pack semantic blocks (loader exists), and
  retrieved chunks from the agent's documents — Volumes upload → embed into a **per-agent Qdrant
  namespace**.
- **Hard dependency, do inside this phase:** the queued per-connection/per-scope document+glossary
  store migration (`task_170ac04a` — these stores are global today). Per-agent context *forces* it.
- **Builder UI:** create agent → pick connections/schemas (**RBAC-limited to creator's own scope or
  narrower — never broader, fail-closed**) → upload documents → write instructions → side-by-side
  test chat.
- Exit criterion: a "Churn Analyst" agent with two uploaded PDFs + one bound connection answers
  through `/ask` with its context visibly applied and a Trust Receipt.

**Phase 2 — MLflow lifecycle underneath** (~1 week; requires A1 Phase 1 `obs.mlflow`):
prompt-registry-backed instructions, LoggedModel per agent version, `agent_id`-tagged traces,
per-agent cost.

**Phase 3 — Quality plane** (~1–2 weeks): golden questions in the builder; eval-on-edit gate; Review
Queues → ambiguity-ledger crystallization. This is where Aughor pulls decisively ahead of every
custom-GPT product.

**Phase 4 — Operational agents** (incremental):
- Agents own scheduled briefs/monitors ("my churn agent briefs me Mondays") — `briefs/` +
  `monitors/` schedulers exist.
- Agent composition via investigations-as-data-sources (the QRDS pattern, A4.2 #1).
- **Each published agent exposed as an MCP tool** via `aughor/mcp/server.py` → a user's domain agent
  becomes callable from Claude, Cursor, any MCP host. Aughor quietly becomes an agent platform other
  AI surfaces consume.
- Distribution: pack/agent sharing; watch OpenSharing's agents/skills scope (A3.1) as the eventual
  cross-org channel.

## B5 · Design principles / risks

1. **Agents are context + scope + governance — never new machinery.** Instructions steer
   tone/domain/priorities; guards, SQL safety, and the graph stay invariant. If each agent can
   redefine investigation behavior, the deterministic spine forks into N untested variants.
2. **Spend control ships before self-serve.** Charter budgets + metering gate Phase 1 launch, not
   after.
3. **Fail-closed scope inheritance.** An agent's data scope ⊆ its creator's RBAC scope, checked at
   the execution gate (`sql/rls.py` path), not at the UI.
4. **Two trust planes, bridged not merged.** Evidence ledger/Trust Receipt = user-facing product;
   MLflow traces/evals = engineer/creator-facing. A receipt may *link* to a trace; it is not
   replaced by one.
5. **Per-agent memory via existing mechanisms.** Ambiguity-ledger crystallization scoped per
   agent/connection — no new memory subsystem.

---

# Part C — Unified sequencing

**Now (highest leverage per unit effort):**
1. MLflow tracing behind `obs.mlflow` (A1 Phase 1) — near-zero risk given the contextvars match;
   makes every investigation inspectable.
2. MLflow eval harness → **run the P7 model bake-off through it** (A1 Phase 2). P7 is already the #1
   queued item; this makes its answer defensible.

**Next (reach + the platform pivot):**
3. Agent entity + Gem MVP (B4 Phase 1), including the doc-store scoping migration.
4. Lakehouse connector family: Iceberg-REST first (includes UC attach), then Delta paths, then Delta
   Sharing (A3.2). Capability-contract entries for every sharp edge.
5. UC metadata harvest → ontology/glossary seeding with provenance (A2.3 #2).

**Later (compounding):**
6. Agent lifecycle + quality plane (B4 Phases 2–3): prompt registry, LoggedModel, eval-on-edit,
   Review Queues bridge.
7. Redash patterns: investigations-as-data-sources; alert-destinations catalog; safe-parameterized
   publishing + per-query API keys; `annotate_query` attribution.
8. Operational agents + MCP exposure (B4 Phase 4); `unitycatalog-ai` functions → packs; XGBoost
   WHY-lens experiment; Terraform module; OpenSharing watch.

**Deliberately not doing:** embedding OSS UC (JVM sidecar, weaker governance than ours); embedding
Redash (legacy stack, unsigned embeds); adopting Spark (wrong scale profile); letting MLflow become
the product store of record (one-directional dependency); letting agents redefine the deterministic
spine.

**Dependency edges:** A1-P1 (`obs.mlflow`) → A1-P2 (bake-off) and → B4-P2 (lifecycle). B4-P1 forces
`task_170ac04a` (doc/glossary scoping). B4-P3 consumes A1-P2's scorer/dataset work. A2 connector and
A3 connectors are independent of everything else. P7 (frontier model pin) remains the single biggest
answer-quality lever and is *accelerated*, not blocked, by A1-P2.

---

# Part D — Residual uncertainties (flagged by research; check at build time)

- delta-rs deletion-vector **writes**: issue #4079 closed "Done," no release note found — irrelevant
  for read-mostly, verify if writes ever matter.
- DuckDB-delta **column-mapping** completeness: historically partial; test against a real Databricks
  column-mapped table before connector GA.
- Exact MLflow 3.x version where `mlflow.genai.evaluate` landed in OSS (fully OSS today — which is
  what matters); "LF AI & Data" vs generic "Linux Foundation" umbrella for MLflow unconfirmed.
- OSS UC server production-RDBMS backing (H2 default confirmed; Postgres/MySQL support unconfirmed);
  depth of its Hive-metastore-compat claim.
- MLflow OSS online-scoring maturity vs Databricks managed monitoring: inferred from docs + issue
  tracker (a 3.9.0 Postgres+S3 consistency bug existed, fixed), not load-tested by us.
- `ContextThreadPoolExecutor` → MLflow span nesting: structurally expected to work (both
  contextvars-based); **must be verified empirically in A1 Phase 1**.

# Part E — Platform critique & second assessment (2026-07-11, post-merge of PR #138)

*Trigger: a six-point user critique after the first build wave landed — (1) agent assessment
should look like the MLflow demo (demo.mlflow.org), (2) what to learn from
langchain-ai/open-swe, (3) feature flags should be intelligently self-activating, (4) Fleet
belongs inside an Agents workspace built on MLflow's ready platform, (5) agent learning has no
visible proof, (6) audit whether built features are wired & surfaced at all. Method: three
parallel research passes — the MLflow 3.12 GenAI UI verified LIVE against demo.mlflow.org
(REST endpoints probed), the open-swe repo/blogs, and a full BUILT→WIRED→SURFACED audit of this
repo. Everything below is verified, not recalled.*

## E1 · Agent assessment the demo way — MLflow server underneath (answers critique #1 + #4)

**The demo is stock OSS MLflow 3.12** — every view it shows is available self-hosted; nothing
Databricks-managed. Its UI inventory: **Overview** (Usage: trace count · latency p50/90/99 ·
error rate · token usage · cost-over-time by model/provider; Quality: per-scorer charts; Tool
calls: per-tool performance), **Traces**, **Sessions**, **Judges** (incl. an *online
auto-evaluation* toggle — OSS), **Datasets**, **Evaluation runs** (with Issues workflow),
**Prompts**, **Agent versions**. Requirements: SQL-backed tracking store (dashboards/datasets),
`mlflow[genai]` on the server for cost computation (LiteLLM pricing), MLflow ≥3.10.

**What we get for free by tagging correctly** (the load-bearing finding): the Sessions view,
user filters, and all token/cost dashboards hang off two metadata keys + autolog —
`mlflow.trace.session`, `mlflow.trace.user` (set via `mlflow.update_current_trace(session_id=…,
user=…)`), with `tokenUsage`/`cost` auto-written by autolog. Aughor's `/ask` already carries
`session_id` and org identity; traces already tag `investigation_id`. One wiring change in the
telemetry seam populates Sessions/user/cost views.

**The design unlock — one MLflow EXPERIMENT per user-agent** (`agent:{id}`): MLflow filter
state is NOT URL-addressable, but experiments are. Per-agent experiments make the entire demo
surface deep-linkable per agent: `/#/experiments/{id}/overview/usage?startTime=…`,
`…/traces/{trace_id}`, `…/chat-sessions/{session_id}`, `…/evaluation-runs`. **Iframe embedding
is officially supported**: `mlflow server --x-frame-options NONE --cors-allowed-origins <origin>`
(documented flags; the demo itself serves no X-Frame-Options).

**Programmatic access for native cards** (verified live): `POST /api/3.0/mlflow/traces/search`
(filters: `tag.<k>`, ``metadata.`mlflow.trace.user` ``, `feedback.<name>`, span fields; returns
assessments inline) and `POST /api/3.0/mlflow/traces/metrics` — the aggregation endpoint that
serves the demo's usage/cost charts (metrics: trace_count/latency/tokens on TRACES,
input/output/total_cost by span_model_name/provider on SPANS; time-bucketed). ⚠ the metrics
endpoint is undocumented/internal-ish — fall back to traces/search + client aggregation if it
shifts. Also: datasets REST (`/api/3.0/mlflow/datasets/*`), scorers/judges REST, assessments
CRUD; prompts ride the model-registry REST in OSS.

**The Agent Workspace** (reuse the existing `Workspace` layers shell, as
IntelligenceWorkspace/OperationsWorkspace do):

| Layer | Source | Cost |
|---|---|---|
| Overview | native roster (exists) + summary cards via traces/search + traces/metrics | small |
| Traces / Sessions | embedded/deep-linked MLflow views per agent-experiment | tiny |
| Evaluations | goldens pushed as MLflow eval datasets; each evaluate → an eval run (compare view) | small |
| Prompts | A1-P3: instructions → prompt registry (versions + linked traces) | the planned slice |
| Memory | the learning surfaces from E4 | small |
| Fleet | folds in as an operations layer (charters + metered jobs — audit confirms that's all it is) | small |

**Schema fix required**: `agent_id` is NOT persisted on investigation rows (`db/history.py` has
no such column — it lives only in LangGraph state, re-read from checkpoints). One additive
column via the existing `add_column_if_missing` migration makes per-agent run history joinable.

**Caveats**: OSS MLflow has no per-user auth (fine self-hosted/LAN; gate before exposing);
deep-link routes aren't a stable API (changed across 3.x minors); only time-range + selected
trace/session/run are URL-addressable — custom-tag filters are not (hence per-agent experiments).

## E2 · open-swe learnings (answers critique #2)

**Meta-lesson first**: LangChain ABANDONED their hosted product (swe.langchain.com is
DNS-dead) and their bespoke four-graph orchestration (manager/planner/programmer/reviewer),
relaunching ~2026-03 as a thin Python framework composed on their maintained `deepagents`
harness. *Compose on the platform, don't own the loop* — independent validation of Part E1's
borrow-MLflow strategy. Transferable ideas, ranked by Aughor fit:

1. **Double-texting** — a message queue drained before each model call lets users steer a
   RUNNING investigation without cancel/restart (their `check_message_queue_before_model`
   middleware). Aughor's deep runs are fire-and-forget between gates; this is the gap.
2. **Reviewer with a feedback LOOP** — their reviewer sends work back to the executor with
   objections until resolved. Aughor's adversarial refuter is one-shot (caps confidence,
   records objection); a bounded fix-loop is the natural evolution.
3. **Deterministic thread per artifact** — follow-ups rejoin the same running agent + state.
   Maps to: a follow-up on an investigation rejoins its thread/checkpoint instead of starting
   fresh.
4. **Graduated autonomy tiers** (labels `open-swe`/`-auto`/`-max` bundling autonomy + model
   tier) → per-agent autonomy setting (always-ask / auto-accept-plan / auto+strong-model) on
   top of the existing plan gate + charter governance.
5. **Tracking-issue-as-live-state + checkpoint resume** → a canvas/briefing as the living
   findings doc a long investigation continuously updates; partial work survives failure.
6. Validations of existing Aughor theses: deterministic middleware safety-nets (= guards),
   curated small toolset over accumulation (Stripe's insight), `AGENTS.md` context contract
   (= editable ontology), aggressive prompt caching + published per-run costs.

**Cautionary tales**: mandatory plan+review made small tasks miserable (validates Aughor's
auto-router downgrading); they never published end-to-end benchmarks (their only real eval is
reviewer-scoped, 50 PRs/136 golden findings, frozen dataset, LLM pairwise judge) — Aughor's
deterministic bake-off/goldens are the credibility antidote.

## E3 · Adaptive capabilities — the flag system should decide, with receipts (answers critique #3)

The audit classified all 35 registered flags: **~14 are already SELF-GATING** — flag AND a
deterministic runtime trigger must both hold (clarify gate: material metric divergence;
adversarial high-stakes: HIGH-confidence decision-changing verdicts only; key-reconciliation:
only after a value-domain mismatch; capability contract: only on a native-SQL failure; premise
check: only "why high/low" questions; guarded extract: only on typed-field failures). The
"intelligence" half-exists — missing are the policy layer, the feedback loop, and receipts:

- **Phase 1 — tri-state Auto/On/Off + activation receipts.** Reclassify flags into
  capabilities; self-gating ones default to **Auto** (platform decides per run via existing
  deterministic triggers); every activation emits a receipt edge ("activated premise-check
  because the question asserts a comparison"). Cost-dangerous ones (`ai_sql`, federation,
  champion-validate) stay manual. Operator override always wins; budget caps apply.
- **Phase 2 — runtime feedback closes the loop.** Deterministic per-connection priors from
  already-captured verdicts/outcomes: "refuter changed the outcome 3/4 times here → keep
  Auto-on"; "premise-check never fired usefully → deprioritize". Counters, never an LLM vote.
- **Phase 3 — Settings→System becomes a Capabilities page** with evidence per capability
  ("fired 12× this week, changed the answer 3×") instead of a raw toggle wall.

Housekeeping: `explorer.manifest_driven` is consulted (`explorer/agent.py:1858`) but never
registered in FLAG_ENV — permanently-off dead code; register or delete.

## E4 · Learning is real but INVISIBLE (answers critique #5)

Audit verdict: the closed loop is captured and read back into prompts, but its accumulation is
invisible. Specifics: the ambiguity-ledger burn-down (`ledger_stats`: `served_total`,
by-source) has **no API endpoint at all**; `/verify/verdicts/stats` (acceptance rate) exists
but is **consumed by zero components**; trusted queries and trusted programs are injected into
prompts but never displayed; verdict capture is wired only on ExplorationReport. The ONLY
visible learning signal is the per-answer `◆ resolved reading` badge on the Trust Receipt.

**The fix (thin, data already exists):**
- **Per-run Learning Receipt** — an SSE event + Trust-Receipt section: "reused 2 resolved
  readings (0 clarifying questions asked) · applied 1 correction · crystallized 1 NEW
  resolution · trusted plan replayed · playbook outcome logged."
- **Memory layer in the Agent Workspace** — ledger burn-down chart (new endpoint over the
  existing `ledger_stats`), acceptance-rate card (endpoint already exists), trusted
  queries/programs lists, and per-agent eval **history** (extend the single `last_eval` stamp
  to a trend line).

## E5 · BUILT→WIRED→SURFACED audit results (answers critique #6)

All 35 registered flags have live call sites — none dead (one unregistered: E3 above). The
deficit is presentation, not plumbing:

| Built & wired, NOT surfaced | Where it lives | Recommendation |
|---|---|---|
| Plan-as-program answers | `POST /query/plan-run`, `/plan-answer` (auto-routed in /ask only) | surface the program + artifacts as an inspectable answer view |
| Federated answers + cross-source join | `/query/federated-answer`, `/cross-source-join` | show the federation plan receipt when auto-routed |
| Capability-pipeline answers | `/query/capability-answer` | fold into the same receipt pattern |
| Ambiguity-ledger burn-down | `ledger_stats` (no endpoint) | E4 Memory layer |
| Verdict trust-economy stats | `/verify/verdicts/stats` (no consumer) | E4 Memory layer |
| Trusted queries / programs | prompt-injected only | E4 Memory layer lists |
| Per-agent run history | `agent_id` absent from investigations rows | additive column migration (E1) |

## E6 · Revised next-wave sequencing (supersedes Part C's "later" ordering)

Each its own PR off main: **(1) MLflow-underneath Agent Workspace** — session/user tagging +
per-agent experiments + embedded views + Fleet fold-in + `agent_id` column (biggest visible
win, mostly borrowed UI); **(2) Learning Receipt + Memory layer** (E4 — thin); **(3)
Capabilities Auto-mode Phase 1** with activation receipts (E3); **(4) double-texting +
reviewer-loop** (E2 — deeper agent work). The Part-A lakehouse connector family remains queued
in parallel (unchanged verdict); P7 remains one quiet-machine bake-off run away.

# Key sources

MLflow releases/docs: mlflow.org/releases (3.9–3.14), mlflow.org/docs/latest/genai/ (tracing ·
eval-monitor · prompt-registry · version-tracking · self-hosting), docs.databricks.com OSS-vs-managed
diff. Unity Catalog: github.com/unitycatalog/unitycatalog (+releases, roadmap.md, OpenAPI spec),
docs.unitycatalog.io, docs.databricks.com external-access, duckdb.org/2026/05/07/delta-uc-updates,
Onehouse/Polaris comparisons. Lakehouse: pypi deltalake/pyiceberg/delta-sharing,
duckdb.org core_extensions delta/iceberg + 2026-05-29 & 2025-11-28 posts,
github.com/delta-io/delta-sharing PROTOCOL.md, databricks.com OpenSharing announcement (2026-06-10).
Redash: github.com/getredash/redash (+releases, discussions/5962, query_runner sources), redash.io
docs (API, parameters, permissions), getredash/setup compose.
