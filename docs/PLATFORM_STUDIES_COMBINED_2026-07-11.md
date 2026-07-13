# Platform Studies — Databricks OSS × Spice.ai × Aughor (Combined Edition, 2026-07-11)

*This document combines the two same-day external-platform studies into one canonical read:*

1. *Study I — `DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md` — the Databricks open-source
   stack, project by project, plus the agentic-platform direction it unlocked (including the
   post-merge Part E platform critique & second assessment).*
2. *Study II — `SPICEAI_STUDY_AND_ADOPTION_PLAN_2026-07-11.md` — a source-level deep study of
   [spiceai/spiceai](https://github.com/spiceai/spiceai) and the adoption plan derived from it.*

*Merge rules: both study bodies are preserved **verbatim** below (Study I, Study II). Exactly three
things were lifted out and unified to remove overlap: the two TL;DRs (→ **Combined TL;DR**), the
standalone sequencing (→ **Unified Adoption Program**; each study's own sequencing remains in place
for its dependency edges), and the source lists (→ **Key sources**). Two sections are NEW and exist
only here: the **Cross-Study Synthesis** and the **Unified Adoption Program**. Section references
are study-local: `A1…E6` inside Study I; `Part A–E`, `L1–L15`, `Rec 1–10` inside Study II.*

---

## Combined TL;DR

Two same-day studies looked outward from Aughor at the two most instructive neighboring platforms and
came back with **complementary halves of one program**. The Databricks-OSS study found the
**agent-facing planes** Aughor lacked — MLflow as the lifecycle/observability/eval substrate, and the
open-lakehouse connector family as data *reach* — plus the agentic-platform direction (governed,
grounded, **measured** user-created agents). The Spice study found the **data-facing plane** —
federation breadth, dataset-level acceleration, freshness — and established that Spice deliberately
does **not** build the intelligence plane (semantic layer, guards, ambiguity handling, investigation,
trust) that is Aughor's product. Neither neighbor competes with the moat; both strengthen the flanks.

| Plane | Best-in-class owner | Study | Aughor posture |
|---|---|---|---|
| Intelligence (grounding, guards, semantics, ambiguity, investigation, trust receipts) | **Aughor** | validated by both | KEEP — the moat; both neighbors' roadmaps point *toward* what Aughor already ships (`closed_loop`) |
| Agent lifecycle (traces, evals, versions, cost, review) | MLflow 3.x | I | **ADOPT** — shipped: `obs.mlflow`, bake-off harness, MLflow-underneath Agent Workspace |
| Data reach (UC, Iceberg, Delta, Delta Sharing estates) | DuckDB extensions + thin clients | I | **BUILD** the "Connect to Lakehouse" connector family; **INTEROP** with UC as a client |
| Data plane (federation breadth, acceleration, CDC freshness) | Spice.ai runtime | II | **INTEROP** as client (`spice` connector) + **BUILD** Python-scale accelerated datasets; **REJECT** Rust-scale infra |
| Workflow/design patterns | Redash, open-swe, spicepod idioms | I + II | **MINE** — patterns, never code |

### From Study I — Databricks OSS (verdicts & theses)

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

### From Study II — Spice.ai (strategic read & verdicts)

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

## Cross-Study Synthesis — how the two studies compose

*New material: neither original states these interactions; they emerge from holding both studies side
by side.*

**S1 · One telemetry seam, two observability planes — bridge, don't pick.** Study I adopts MLflow as
the engineer-facing lifecycle plane (traces, evals, versions, cost — shipped as `obs.mlflow` + the
Agent Workspace). Study II's Rec 4 (`task_history` spans-as-a-table) is not a competitor to that: it
is the **queryable spine** — one append-only table sunk from the kernel ledger's existing `node.span`
events, which the same telemetry seam already emits unconditionally. Division of labor: MLflow answers
"compare, score, version, charge back" (rich UI, eval runs, prompt registry); `task_history` answers
"SELECT over what the agent actually did" (eval recovery, regression forensics, and the "Aughor
investigates Aughor" demo). Spice proved the pattern pays: their text-to-SQL evals *recover generated
SQL by querying task_history* — the observability table **is** the eval substrate. Aughor gets both
planes from one instrumentation seam, honoring Study I's B3 rule (bridge, don't merge) twice over.

**S2 · One connector program, three estates — Iceberg REST is the shared substrate.** Study I's
lakehouse family (Iceberg-REST → Delta paths → Delta Sharing → UC) and Study II's `spice` connector
are one program, not two: Spice itself **serves an Iceberg REST catalog** (`/v1/config`,
`/v1/namespaces`), UC exposes one, and Polaris/Lakekeeper/Glue-REST/S3-Tables/Snowflake Open Catalog
all speak it. Build the Iceberg-REST `ATTACH` machinery and its capability-contract entries once and
it reaches every estate; the `spice` connector then adds only the `/v1/sql` SQL surface (DataFusion ≈
Postgres dialect) — and transitively delivers Spice's ~40 sources plus *someone else's* acceleration
and CDC. Sequence them adjacently so the `db/capabilities.py` sharp-edge entries are written once.

**S3 · A receipts family is forming — unify it.** Four independently-proposed receipts are one
product concept: Study I's **Learning Receipt** (E4 — "reused 2 resolved readings · crystallized 1
new resolution") and **activation receipts** (E3 — "activated premise-check because the question
asserts a comparison"), and Study II's **grounding-context receipt** (Rec 5 — the exact context block
the model saw) and **staleness receipts** (Rec 3 — "data as of {last_refresh}"). Together with the
existing Trust Receipt (output-side), they cover the full answer lifecycle: *input* (grounding) →
*behavior* (activations) → *freshness* (staleness) → *output* (trust) → *learning* (crystallization).
Ship them as one coherent receipt surface with one SSE/render pattern, not four disconnected widgets.

**S4 · Convergent external validation of the house theses.** Both studies independently confirm:
(a) **interop-as-client over embedding** — nobody embeds the UC server; nobody should embed Spice;
(b) **compose on platforms, don't own the loop** — open-swe abandoned its bespoke four-graph
orchestration for a maintained harness (Study I E2), and Spice never built a query engine at all,
curating six forked Apache/LF projects instead (Study II A1): the same lesson from opposite
directions; (c) **deterministic-first at industrial scale** — Spice's entire AI layer is one bounded
tool loop plus deterministic context assembly, and MLflow's `@scorer` lets Aughor's guards *be* the
eval metrics; (d) **the closed feedback loop is the endgame** — Spice's stated five-year vision and
MLflow's Review-Queues→feedback direction both describe the loop Aughor already runs behind
`closed_loop` (ledger → priors → verdicts → trusted queries). The moat is real; the neighbors are
building toward it.

**S5 · Tenancy is one thread across both studies.** Study II's verified matcache finding (results
cached by `(conn_id, sql)` *before* row-policy injection) gates more than the RBAC flag: Study I's
user-created agents (B4) and per-agent workspaces multiply the principals sharing a connection, so
the cache-key fix (fold org/principal/policy-version into the key — Spice's namespace-folded keys)
is a precondition for the agent platform, not just RLS hygiene. The same execution-gate philosophy
extends to Study II's Rec 8 (per-agent table allowlists inside `security_pre`), which hardens Study
I's B5 fail-closed scope-inheritance principle at the layer where it actually binds.

**S6 · Acceleration multiplies the connector program.** Study II's accelerated datasets (Rec 3) are
most valuable exactly where Study I's connectors point: lake tables behind Iceberg-REST/Delta are
cold and remote — a DuckDB-file mirror with `full/append` refresh, readiness, and fallback-to-source
turns them into interactive-latency substrates for briefings, monitors, and explorer re-scans. The
existing API-source mirrors (`base_sync.py`) and the lakehouse estate then unify under one
acceleration model, with staleness receipts joining the S3 receipts family.

---

# Study I — The Databricks Open-Source Stack & the Agentic Platform Direction

*Preserved verbatim from `DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md`. Its TL;DR was
lifted into the Combined TL;DR above and its Key sources into the combined Key sources below; Part
C's sequencing is merged — together with Study II's — into the Unified Adoption Program at the end
(kept here for its dependency edges).*

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

---

# Study II — Spice.ai OSS: Deep Study & Adoption Plan

*Preserved verbatim from `SPICEAI_STUDY_AND_ADOPTION_PLAN_2026-07-11.md`. Its TL;DR/verdict table was
lifted into the Combined TL;DR above and its Key sources into the combined Key sources below; Part
D's wave sequencing is merged into the Unified Adoption Program (kept here for its per-rec detail).*

**Status:** STUDY — no code changes in this document. Every recommendation is flag-gated, default-off,
byte-identical-when-off, and follows BUILT→WIRED→TESTED→LEVERAGED.

**Subject:** [spiceai/spiceai](https://github.com/spiceai/spiceai) (`trunk`, v2.1.0-unstable, Apache-2.0, ~75 Rust
crates) — "a SQL query, search, and LLM-inference engine, written in Rust, for data-driven applications and AI
agents." Verified against a full source clone (commit `cb96c9f`), official docs (spiceai.org/docs), and the
Spice 2.0 launch material (Cayenne GA, Ballista distributed query, native CDC, Cedar/RBAC).

**Method:** four parallel source-level deep dives (core runtime, acceleration/CDC, connectors, AI layer) +
one Aughor gap map + docs/blog verification. File evidence cited as `crate/path:line` (Spice) and
`aughor/path` (ours).

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

---

# Unified Adoption Program (cross-study; supersedes each study's standalone sequencing)

*Merges Study I Part C / E6 — as amended by its build status (A1-P1 tracing, A1-P2 bake-off harness,
B4-P1 agent slices 1–5, and E6 item (1) the MLflow-underneath Agent Workspace are **SHIPPED**) — with
Study II Part D's waves. Ordering = leverage ÷ (effort × risk), correctness first. Everything
flag-gated, default-off, byte-identical when off, BUILT→WIRED→TESTED→LEVERAGED.*

**Build status (2026-07-12, branch `2026-07-12-matcache-tenancy-fix`, pushed to origin — 10 commits):
Wave 0 COMPLETE; Wave 1 substantially SHIPPED (the receipts family + Capabilities Auto-mode).**

**Build status (2026-07-13, local working tree — Wave 2 #6 `task_history` SHIPPED, flag `obs.task_table`):**
the spans-as-a-table spine + both its leverages, in three slices, all flag-gated / default-off /
byte-identical when off; ruff-clean, kernel ratchets green.
- *Slice 1 — the spine:* `Migration(4)` adds `task_history` (Spice's exact shape) to the kernel ledger
  (`system.db`, already hermetic); a pure **sink** in `aughor/telemetry.py` — a contextvar span-stack
  makes the existing node spans (`span()`) and the SQL tool span (`mlflow_tool_span`) each write one
  row with real `parent_span_id`/`trace_id` linkage, riding `ContextThreadPoolExecutor`'s
  `copy_context()` so parallel waves link correctly. No new instrumentation (reuses spans telemetry
  already emits). `Ledger.task_history_insert/task_history()`.
- *Slice 2 — leverage #1 (eval recovery + forensics):* `aughor/obs/task_history.py`
  (`recover_sql(trace_id)`, `recover_run()`, `recent_runs()`, `slow_tasks()`) + the `evals/task_recover.py`
  CLI (`--trace/--recent/--slow`). Proven on the REAL path (an integration test drives the actual
  `execute_guarded` and recovers the SQL). Deliberately did NOT contort `model_bakeoff`/the ground-truth
  gate to "read from" the table — their replica pipelines emit no spans, so that would be a bench-hack;
  the honest recovery surface is the API + CLI, and the live investigation path is where it populates.
- *Slice 3 — leverage #2 ("Aughor investigates Aughor"):* an `aughor_ops` built-in connection
  (`AughorOpsConnection`) — an in-memory DuckDB that live-**ATTACH**es the ledger sqlite READ-ONLY as
  the `aughor_ops` schema (fresh, not a snapshot; materialise fallback for a cold offline extension
  cache), exposing `task_history`/`jobs`/`events` so Deep Analysis can ask "why were yesterday's
  briefings slow?" as an ordinary investigation. Listed/openable only while `obs.task_table` is on.
  En route, fixed a pre-existing false positive in the connection read-only gate (`_validate`): the
  forbidden-keyword pre-scan matched DML words inside string **literals** (so `… WHERE task =
  'sql.execute'` — the natural self-investigation query — was wrongly rejected); literals are now
  blanked before the scan, with the sqlglot AST type-check still the authority. ~15 new tests.
  **NEXT (unbuilt):** Rec 5 grounding-context receipt (last Wave-1 item) · Wave 2 #7 A1-P3 lifecycle ·
  #8 the P7 decision run (biggest answer-quality lever; harness + now task_history forensics both ready).

**Build status (2026-07-13, local working tree — Rec 5 grounding-context receipt BACKEND SHIPPED, flag
`ask.context_receipt`):** the input-side twin of the Trust Receipt. Staged (chosen over a full hot-path
rewire, which memory flags as the riskiest Wave-1 item): the map found NO central assembler — grounding is
built per-caller across three seams (quick `/ask` `_stream_chat` richest, deep ADA leaner, explorer thinnest),
and the eval mirror already drifts (`build_metrics_block` vs the real path's `unified_metric_grounding`).
- New pure `aughor/agent/grounding.py`: one producer function per grounding block (dialect rules, agent/pack
  brief, trusted templates, ambiguity-ledger corrections, governed-metric bindings, schema slice, glossary,
  KB patterns, SQL examples, exploration, causal, docs) — each wrapping the SAME retriever the answer path
  calls, so per-block data can't drift. `build_grounding_context()` composes them into a `GroundingContext`
  (schema-dependent blocks fire only when a schema is resolved); `to_dict()` + `to_markdown()`.
- `GET /ask/context?connection=&question=` (`routers/investigations.py`) → `{receipt, markdown}`; 404 when the
  flag is off (byte-identical default).
- Convergence proof (no drift): `_stream_chat`'s three pure prepend producers (dialect rules, agent brief,
  corrections) now call the shared block functions — a byte-identical swap (parity asserted in tests). The
  schema-linking + governed-metric blocks stay inline (entangled with canvas-scope resolution) — folding those
  through `build_grounding_context()` is the reviewed follow-up. Value-index literal binding is post-generation
  on the answer path (a guard, not a prompt block) → not yet surfaced. 10 tests; ruff clean.
  - **"Show grounding" answer-UI affordance SHIPPED:** `web/lib/api.ts::getGroundingContext` + a `GroundingDetails`
    component in `web/components/ChatMessage.tsx` — a lazy "Show grounding" toggle (fetches on click; the endpoint
    runs real retrievers) rendering each active block, hidden when the flag is off (404 → null). Live-verified: the
    endpoint serves 4 populated blocks (incl. schema-dependent) flag-on / 404 flag-off on the real API server, and
    the web app loads it with zero console errors; eslint/design-token/raw-element/tsc gates clean.
  **Still open (own follow-up):** the schema-linking + governed-metric block convergence into `_stream_chat`.

*Wave 0 — Correctness + trivial wins — ✅ COMPLETE:*
- Matcache tenancy fix (II·Rec 1) — `de04429`. Shared `_row_policy_principal` gate + `result_cache_tenancy()`
  fold `(org, roles, resolved filters)` into the result-cache key; `None`→legacy key (byte-identical). Closed
  the verified latent RLS cache leak. Audited `schema_cache`/`suggestions_cache` = permission-independent.
- RRF fusion (II·Rec 6, flag `search.rrf`) — `6330675`. Rank-based Reciprocal Rank Fusion (k=60) in
  `hybrid_rerank`, α-blend kept as default; scale-invariance regression-proven.
- E3 housekeeping — `59d944b`. Registered the consulted-but-unregistered `explorer.manifest_driven`; added a
  ratchet that fails on any `flag_enabled("literal")` missing from `FLAG_ENV` (root-causes the class).

*Wave 1 — Receipts + adaptive capabilities — receipts family + Auto-mode SHIPPED:*
- `/learning` Memory-layer read API (I·E4) — `4ab60e2`. `GET /learning/summary` + `/learning/trusted` over
  ledger burn-down / verdict acceptance / trusted assets.
- Per-run Learning Receipt (I·E4, flag `learning.receipt`) — `c5ca4ec`. `LearningSignals` on the `RunMetrics`
  accumulator; readings-reused/corrections (receipt-time) + crystallized/trusted-replayed (runtime); SSE
  `learning` + Trust-Receipt payload. (Clarifications-asked deferred — cross-turn.)
- Agent Workspace **Memory panel** (I·E4 frontend) — `023c29e`. Live-verified.
- Capabilities **Auto-mode** tri-state (I·E3, master flag `capabilities.auto`) — `1aadda6`. One switch elevates
  the 6 self-gating guards (premise-check, clarify gate, high-stakes adversarial, join key-reconciliation,
  capability-contract, guarded-extract) to trigger-gated; cost-dangerous flags stay manual; byte-identical off.
- **Activation Receipt** (I·E3, flag `capabilities.receipt`) — `451f180`. Records which guard fired + why
  (3 guards instrumented at same-turn points; key-reconciliation/guarded-extract deferred — deep engines).
- Settings → **Capabilities page** (I·E3 frontend) — `81a5e8a`. Auto/On/Off per guard + master; live-verified.
- Per-run receipts **rendered on the Trust Receipt** (I·E4 + E3 frontend) — `140ac7b`.

*Remaining in Wave 1:* Rec 5 grounding-context receipt (input-side; deferred — a hot-path refactor to
centralize the per-caller grounding assembly into a pure `build_grounding_context()`). Every shipped item is
flag-gated / default-off / byte-identical when off.*

**Wave 0 — Correctness + trivial wins (immediately)**
1. **Matcache tenancy fix** (II·Rec 1) — fold (org, principal/role, row-policy version) into cache
   keys when a policy resolves active; audit `schema_cache` + the exploration metric-move cache for
   the same pattern. Precondition for both `rbac.row_policy` activation *and* the multi-principal
   agent platform (S5). XS.
2. **RRF fusion** in `semantic/lexical.py` (II·Rec 6, flag `search.rrf`) — rank-based fusion
   replacing the α-blend; A/B on the KB-retrieval evals before flipping. XS.
3. Housekeeping: register-or-delete `explorer.manifest_driven` (I·E3). XS.

**Wave 1 — Receipts + adaptive capabilities (the visible-trust wave)**
4. **The receipts family as one surface** (S3): Learning Receipt + Memory layer (I·E4) +
   grounding-context receipt (II·Rec 5, `ask.context_receipt`) + activation receipts (I·E3). One
   SSE/receipt render pattern, three data sources — all thin; the data already exists.
5. **Capabilities Auto-mode Phase 1** (I·E3) — tri-state Auto/On/Off over the ~14 already-self-gating
   flags, with activation receipts; cost-dangerous flags stay manual; operator override always wins.

**Wave 2 — Observability spine + the P7 decision**
6. **`task_history` spans-as-a-table** (II·Rec 4, `obs.task_table`) — sink the kernel ledger's
   `node.span` events into one queryable table; point `evals/model_bakeoff.py` + the ADA ground-truth
   gate at it; register an `aughor_ops` queryable schema ("Aughor investigates Aughor").
7. **A1-P3 lifecycle** (I) — planner/synthesizer prompts into the MLflow Prompt Registry;
   `LoggedModel`/`set_active_model` agent versioning; cost dashboards reconciled with
   `kernel/metering.py::RunMetrics`.
8. **P7 decision run** — one quiet-machine bake-off through the shipped harness; pin the frontier
   coder model. Still the single biggest answer-quality lever; accelerated, not blocked, by the above.

**Wave 3 — Reach: the connector program (S2 ordering)**
9. **Iceberg-REST connector** (I·A3.2 #1) — the shared substrate: covers UC's Iceberg endpoint,
   Polaris, Lakekeeper, Glue REST (no credential vending there — capability-contract entry), S3
   Tables… and Spice's own Iceberg catalog.
10. **UC connector + metadata harvest** (I·A2.3) — DuckDB `uc_catalog`+`delta` ATTACH for query;
    `unitycatalog-client` for comments/metric-views → ontology/glossary seeding with provenance.
11. **`spice` connector** (II·Rec 2, `connectors.spice`) — `/v1/sql` (DataFusion ≈ Postgres dialect;
    `dry_run` = EXPLAIN); transitively reaches Spice's ~40 sources + acceleration + CDC; doubles as
    the wide-schema/freshness lab substrate for eval suites.
12. **Delta path connector → Delta Sharing connector** (I·A3.2 #2–3) — with the column-mapping and
    best-effort-pushdown sharp edges encoded as capability-contract entries.

**Wave 4 — Data-plane substance**
13. **Accelerated datasets** (II·Rec 3, `accel.datasets`, phased P1–P4) — DuckDB-file mirrors with
    `full/append` refresh (explorer-watermark reuse), readiness state, fallback-to-source, retention
    (with the NULL-timestamp eviction audit), staleness receipts joining the receipts family. Applied
    first to the coldest estates: lakehouse connectors (S6) + API mirrors. **No CDC — ever**; the
    documented answer for sub-second freshness is Spice-in-front (Wave 3 #11 makes it seamless).
14. **Connector-contract hardening rides along** (II·Rec 7) — ParameterSpec-style validation with
    "did you mean", the `is_retriable` error taxonomy (consumed by the Wave-4 refresher, API-sync,
    and monitors), readiness semantics surfaced in `/capabilities` and the connection UI.

**Wave 5 — Agentic depth**
15. **Double-texting + reviewer feedback-loop** (I·E2 #1–2) — steer a running investigation via a
    drained message queue; evolve the one-shot adversarial refuter into a bounded fix-loop.
16. **Per-agent table allowlist at execution** (II·Rec 8, `agents.table_allowlist`) — hardens B5's
    fail-closed scope inheritance at the gate that binds.
17. **Operational agents** (I·B4 Phase 4) — agent-owned scheduled briefs/monitors;
    investigations-as-data-sources (the Redash QRDS pattern, I·A4.2 #1); each published agent exposed
    as an MCP tool via `aughor/mcp/server.py`.

**Deferred / evidence-gated** (unchanged from the studies): aughorpod workspace bundle (II·Rec 9 —
waits for the editable-ontology YAML tree; converges with pack/agent distribution and the OpenSharing
watch, I·A3.1/B4-P4), MCP client tools for user agents (II·Rec 10), `unitycatalog-ai` functions →
packs (I·A2.3 #3), XGBoost WHY-lens candidate ranker (I·A5), scikit-learn monitor detectors (I·A5),
Terraform module (I·A5), and the remaining Redash patterns — alert-destinations catalog,
safe-parameterized publishing + per-query API keys, `annotate_query` attribution (I·A4.2 #2–4; fold
into monitors/briefs work when next touched).

**Cross-study dependency edges:** Wave 0 #1 precedes any `rbac.row_policy` or multi-principal-agent
activation. `obs.mlflow` (shipped) → Wave 2 #7; the bake-off harness (shipped) → Wave 2 #8. Wave 2
#6 needs only the kernel ledger (already emits `node.span` unconditionally). Wave 3 #9's
Iceberg-REST machinery + capability-contract entries are shared substrate for #10–#12. Wave 4 #13
leverages Wave 3's cold estates and consumes #14's error taxonomy. B4-P1 already forced the
doc/glossary-scoping migration (`task_170ac04a` — still partially global; finish inside the agent
arc). The two "deliberately not doing" lists (end of Study I Part C; Study II Part E) remain binding
constraints on every wave.

---

# Key sources (both studies)

## Study I — Databricks OSS

MLflow releases/docs: mlflow.org/releases (3.9–3.14), mlflow.org/docs/latest/genai/ (tracing ·
eval-monitor · prompt-registry · version-tracking · self-hosting), docs.databricks.com OSS-vs-managed
diff. Unity Catalog: github.com/unitycatalog/unitycatalog (+releases, roadmap.md, OpenAPI spec),
docs.unitycatalog.io, docs.databricks.com external-access, duckdb.org/2026/05/07/delta-uc-updates,
Onehouse/Polaris comparisons. Lakehouse: pypi deltalake/pyiceberg/delta-sharing,
duckdb.org core_extensions delta/iceberg + 2026-05-29 & 2025-11-28 posts,
github.com/delta-io/delta-sharing PROTOCOL.md, databricks.com OpenSharing announcement (2026-06-10).
Redash: github.com/getredash/redash (+releases, discussions/5962, query_runner sources), redash.io
docs (API, parameters, permissions), getredash/setup compose.

## Study II — Spice.ai

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
