# Aughor Platform Architecture — Org Tenancy, Catalog & Storage

> **Status:** design / decision record (2026-06-22). Records the target structure for
> Aughor *as a platform* — the org/tenant model, the catalog & storage layer, and the
> control-plane / data-plane split — and the phased path from where the code is today.
>
> **One-line thesis:** build the single-org product now, but **tenant-key everything from
> day one** and separate the control plane from the data plane, so "multi-tenant SaaS"
> becomes a configuration flip rather than a rewrite. Align the catalog/storage model to
> **Unity Catalog** (the open, proven standard) without taking on its operational weight
> until scale earns it.

---

## 0. Scope

This document covers **how the platform is structured** — orgs, workspaces, catalogs,
storage, isolation, and governance boundaries. It does **not** cover the intelligence
layer's internals (explorer, ADA, ontology, metrics, agents) except where they attach to
this structure. It records *decisions and invariants*, plus a phased roadmap; it is not an
implementation spec for any single phase.

---

## 1. Framing: a platform, not a single app

Aughor is — or will be — a **platform provider**: deployed on a mega-server (or a regionally
federated cluster of them) that the platform operator owns and runs. Tenants (customer
organizations) are *provisioned within* that infrastructure. This is the lens for every
decision below — we design from the **operator's** seat, not a single customer's.

The near-term reality is **single-org / self-hosted**. The design constraint is that the
*same codebase* must scale to **multi-tenant SaaS** without a re-platforming. The way you
get that for free is the classic split:

- **Control plane** — platform-owned, regional. Identity, the org/tenant registry, the
  metastore (catalog) service, storage-credential vending, grant/policy enforcement,
  compute scheduling, metering & billing, the agent/job fleet.
- **Data plane** — per-org. The actual stored data (catalogs, schemas, tables, volumes)
  and the compute that runs queries and agents over it.

> **Invariant #1 — tenant-keyed everything.** Every persisted object and every storage path
> carries an `org_id` from day one, even with a single org. Retrofitting a tenant key into a
> running system is the migration that eats quarters; adding a column now is free.

---

## 2. The reference model: Unity Catalog / Databricks

We align to the model the lakehouse industry has already converged on (Databricks Unity
Catalog, now Apache-2.0 open source under the LF AI & Data Foundation). It is the
battle-tested shape for exactly this problem, it is open and multi-engine, and DuckDB —
Aughor's compute engine — already integrates with it.

The hierarchy:

```
Account (Org)                         ← the tenant; identity + billing
└── Metastore            (1 per region)   ← top metadata container; the 3-level namespace
    ├── Catalog                          ← primary unit of DATA ISOLATION
    │   └── Schema
    │       ├── Table / View
    │       ├── Volume                   ← unstructured: files, images, video, docs
    │       ├── Function                 ← governed callable (e.g. AI operators)
    │       └── Model
    ├── Storage Credential   ┐ sit DIRECTLY under the metastore, OUTSIDE the namespace —
    ├── External Location    │ they govern PHYSICAL storage + access, not logical objects
    └── Share / Connection   ┘

Workspace  → attaches to ONE metastore; owns NO storage; receives GRANTS (privileges on
             catalogs / schemas / tables / volumes). A metastore serves MANY workspaces.
```

Three properties matter for us:

1. **Storage is governed at the metastore**, not the workspace. A *Storage Credential* wraps
   a long-lived cloud credential; an *External Location* binds a storage path to a credential.
   The metastore then **vends short-lived, scoped credentials** to compute per query.
2. **The catalog is the unit of isolation.** You grant a workspace access to specific
   catalogs/schemas — that is how a workspace gets "storage views, rights, and access"
   without ever owning storage.
3. **It is multimodal.** *Volumes* govern unstructured objects (the "upload any object —
   including video" requirement); *Functions* govern callables (Aughor's `prompt()` /
   `embedding()` semantic operators are a natural fit). Tables, files, and AI operators all
   live under one namespace and one access model.

---

## 3. The Aughor object model

We adopt the UC object model as Aughor-native objects. Mapping current → target:

| Unity Catalog | Aughor today | Aughor target |
|---|---|---|
| **Account** | — (flat; no tenant) | **Org** — new top level, the tenant boundary |
| **Metastore** (per region) | — | **Org metastore** — catalogs + storage creds + external locations, regional |
| **Storage Credential / External Location** | encrypted DSN *per connection* (`registry.py`) | **org-level** credentials + locations, **vended** to workspaces |
| **Catalog** (isolation unit) | a *connection* (`connections` table) | **Catalog** — a data domain within an org |
| **Schema** | `meta.schema_name` | Schema |
| **Table / View** | table (introspected) | Table / View |
| **Volume** | — (docs handled out-of-band) | **Volume** — governed unstructured objects |
| **Function** | — | **Function** — governed callables (AI operators, UDFs) |
| **Workspace** (grants, no storage) | `workspaces` table = list of connection IDs, **no storage** | **Workspace** — grant-scoped views into org catalogs + a compute lane |

Aughor is **closer to this model than it looks**: a workspace is already "a named list of
connection IDs that owns no storage" (`aughor/workspace/store.py`). The work is to insert an
**Org/metastore above** the workspace and turn *connections* into *catalogs reachable via
grants* — not to invent a new structure.

The namespace becomes **`org.catalog.schema.table`** internally (the org is implicit in a
session's context; the user sees the UC-standard three levels `catalog.schema.table`).

---

## 4. Control plane vs data plane

```
┌──────────────────────── CONTROL PLANE (platform-owned, regional) ─────────────────────────┐
│  Identity & authn   │  Org registry   │  Metastore / catalog service (UC-shaped API)        │
│  Grant & policy     │  Credential vending  │  Compute scheduling (lanes)  │  Metering & billing │
│  Agent / job fleet  │                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                   │  resolves: who · what catalog · scoped credential · budget
                                   ▼
┌──────────────────────────── DATA PLANE (per-org) ─────────────────────────────────────────┐
│  Storage: catalogs / schemas / tables / volumes  (tenant-pathed object store)               │
│  Compute: per-org/workspace DuckDB lanes  →  query + agent execution                        │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

**What already exists in code** (the seeds — they just need an Org above workspace and
`org_id` threaded through):

- **Compute lanes** — `aughor/db/lanes.py` (R6): per-workspace DuckDB resource envelope
  (`memory_limit` + `threads`) + a per-workspace concurrency gate inside a global ceiling.
- **Metering** — `aughor/kernel/metering.py` (R1): per-job tokens / queries / rows / time,
  registered by `job_id`, with a heartbeat that enforces budgets and cancels on breach.
- **The security/audit gate** — `aughor/db/connection.py` `security_pre` / `security_post`:
  every query is safety-checked, PII-redacted, row-budgeted, and audit-logged.
- **Workspace data-path isolation** — `aughor/workspace/store.py`
  `workspace_connection_ids` / `workspace_for_connection`: a fail-closed visibility gate.

These are control-plane functions in spirit; the refactor makes that explicit and adds the
org dimension.

---

## 5. Storage architecture

### 5.1 Tenant-keyed layout

All managed storage is pathed by tenant from day one:

```
{storage_root}/{org_id}/{catalog}/{schema}/{table-or-volume}/...
```

The platform owns `{storage_root}`; an org gets a subtree; a workspace never addresses
storage directly — it addresses *logical* objects (`catalog.schema.table`) and the metastore
resolves the physical path + a scoped credential. Local filesystem now → S3/GCS prefixes
later is the *same shape* (swap `{storage_root}` for a bucket; swap direct-FS for vended
credentials). Today's `data/uploads/{conn_id}/...` becomes `…/{org_id}/{catalog}/…`.

### 5.2 Managed vs external; credential vending

- **Managed** — the platform owns the storage lifecycle (uploads, query results, materialized
  tables). Default location set at metastore / catalog / schema (precedence: schema > catalog
  > metastore), mirroring UC.
- **External** — the org points at storage it owns; the platform governs access only.
- **Credential vending** — even today, when access is just "the platform process can read the
  disk," we **model** it as *"the control plane grants this workspace a scoped, short-lived
  capability to this org's catalog."* That modelled seam is what becomes real S3 STS / GCS
  signed-credential vending later, with no change to callers.

> **Invariant #2 — access is vended, never ambient.** Compute receives a scoped capability
> from the control plane; it never reaches storage on its own authority. Local-FS is just a
> trivial implementation of that capability.

### 5.3 Storage format strategy

There are two coherent lanes, and Aughor's snapshot seam already abstracts both:

| Lane | Format | Catalog | When |
|---|---|---|---|
| **Embedded / single-tenant** | **DuckLake** (`aughor/db/ducklake.py`) | DuckLake's own catalog | now — batteries-included, no external server |
| **Governed / multi-tenant** | **Delta** (UC-native, DuckDB-writable, time-travel) or Iceberg | Unity Catalog | at scale — interop + credential vending |

The decoupling is real and already shipped: `aughor/db/snapshot.py`
(`_native_snapshot` / `as_of_supported` / `execute_as_of`) dispatches on *capability* —
DuckLake `AT (VERSION => n)` today, **Delta `VERSION AS OF`** under UC tomorrow. **The format
bet is therefore reversible** — do not over-invest in it now.

### 5.4 Unstructured tier (the "any object" requirement)

Structured data → tables (Parquet/Delta/DuckLake). Unstructured objects (video, images, PDFs,
raw files) → **Volumes**: bytes in the object store under the tenant path, with a catalog row
of metadata (path, type, size, extracted text, embedding). SQL runs over the *catalog* ("all
videos > 1 GB uploaded last week"); the **R8 semantic operators** (`prompt()` / `embedding()`,
already built in `aughor/semops/ai_sql.py`) reason over the *extracted content*. This is the
honest version of "SQL over any object" — not "video as a table," but a governed catalog of
objects with AI operators bridging to their content.

---

## 5b. Inference plane — bring-your-own-model as a vended capability

Storage and compute are vended resources (§4, §5.2). **Inference is the third — and today it
is the one that is still ambient.** Every intelligence surface (ADA, NL2SQL, briefing
synthesis, R8 semantic operators) calls one chokepoint — `LLMProvider.complete()`
(`aughor/llm/provider.py`) — but the backend, endpoint, and API key behind it are resolved
from a single **global** `data/llm_config.json` → env → default (`_active_backend` /
`_active_base_url` / `_active_key`). The only per-agent dimension is a model-*name* string
pinned via the `_run_model` contextvar. There is no `org_id`, no workspace scope, and the
credential is process-global env. That violates **Invariant #1** (tenant-keyed everything) and
**Invariant #2** (vend, never ambient) for the inference dimension.

The platform thesis applies unchanged: **flexibility is the product, not a feature.** A tenant
may bind a local Llama, a public API (Anthropic / OpenAI / Sakana), Ollama Cloud, or a private
model-serving endpoint on Databricks — and the call sites must not know or care which.

### 5b.1 Binding resolution — Org → Workspace → Agent

LLM binding is **inherited, last-most-specific wins** — the same hybrid scope as workspace
settings:

```
Org default  →  Workspace override  →  Agent override        (per role: coder · narrator · fast)
```

The org sets a sane default; a workspace may override it; an agent may override *that* to trade
cost / accuracy / latency (a cheap local model for `fast` interpretation, a frontier API for
`narrator` synthesis). Today's global config becomes the **org default**; today's `_run_model`
contextvar generalises into the **agent override** — but carrying a *binding*, not just a model
string.

### 5b.2 The capability — `vend_llm(...) → InferenceCapability`

Mirror `vend_storage` (§5.2). The control plane resolves the inheritance chain and the
credential once, and vends a scoped handle; the call site addresses a *logical role*, never a
backend:

```
vend_llm(role, *, org_id?, workspace_id?, agent_id?) -> InferenceCapability
```

The capability carries the **resolved binding** (backend · model · endpoint · scoped
credential) *and* a declared **capability profile** — what this backend can actually do, so
nothing downstream branches on provider identity:

| Field | Values | Why it matters |
|---|---|---|
| `cache_mode` | `explicit_breakpoint` · `auto_prefix` · `auto_prefix_unverified` · `none` | how (if at all) to exploit a stable prompt prefix; `_unverified` until the probe measures it |
| `tooling` | `native_tools` · `none` | whether mid-generation retrieval is available |
| `structured_output` | `native` · `instructor_emulated` | how `response_model` is enforced |
| `token_accounting` | `exact` · `estimated` | some endpoints return no `usage` — meter must degrade honestly |
| `max_context` | int | drives the payload cap (§5b.3, Layer A) |
| `privacy_class` | `local` · `private_endpoint` · `public_api` | governs *what context may be sent* (§5b.4) |
| `cost` | per-token · flat · unknown | per-agent budget normalisation |

Anthropic → `explicit_breakpoint`; OpenAI / Together / Ollama-local → `auto_prefix`;
Ollama-cloud → `auto_prefix (unverified)`; a bare private endpoint → `none`. A new backend is a
config row + a profile, **not** a code change — the same property `vend_storage` gives storage.

### 5b.3 Two-layer optimisation — only one layer is backend-coupled

Per-provider tricks (Anthropic cache_control, Ollama prefix hashing, the Qwen3
`enable_thinking` template trap) are **not** portable and must never leak into call sites. The
seam splits the work:

- **Layer A — backend-independent, always on.** Schema linking (`tools/schema_linker`),
  evidence-log digesting (the `numeric_cells_block` / dossier move), payload caps against
  `max_context`. These reduce *tokens themselves* and pay off under every binding.
- **Layer B — canonical assembly + capability-gated exploitation.** Prompts are *always*
  assembled in one canonical shape — `[stable prefix: rules + linked schema + canonical defs]`
  then `[volatile tail: phase question + results]` — assembled once, provider-agnostic. A thin
  per-provider **adapter** then exploits it against `cache_mode`: insert a breakpoint, rely on
  free auto-prefix reuse (and pin `num_ctx` / `keep_alive`), or do nothing. The sequencing thus
  *proliferates* — it lives in one assembler, and each backend gets whatever benefit it is
  capable of without the caller knowing.

> **Status (measured, not assumed).** We refuse to *assume* a backend caches. The
> prefix-cache **probe** (`aughor/llm/cache_probe.py`, `POST /llm/config/cache-probe`) measures
> reuse over the real provider — a shared-prefix series vs a distinct control — and persists
> the verdict, which the capability seam adopts (`cache_mode_override`), so the chip stops
> saying "unverified". **Live result: `qwen3-coder-next:cloud` → `no_reuse`** (warm 891ms vs
> cold 819ms). Ollama Cloud multiplexes requests across workers and does **not** reuse the
> prefix KV across calls — so **Layer B is worthless for the shipped cloud binding**, and the
> measurement (not a guess) redirects effort to Layer A.
>
> **Layer A is also tempered by reality:** aughor's context is *already curated* (schema-linking
> picks ~4 tables, results cap at 12 rows, schema/scan have char caps), so the relevance
> selection *is* the compression and headroom-style "massive compression" has a low ceiling.
> The Layer-A win across heterogeneous BYO-model backends is therefore **adaptation, not
> compression**: intake caps are sized to the bound model's `max_context`
> (`context_budget.schema_scan_char_limits`, safe-direction-only — identical on a large window,
> tighter on a small one), and a **warn-only overflow guard** at `complete()` surfaces "bind a
> larger-context model" instead of cutting evidence (which would risk grounding). The
> *destructive* evidence-log digest is deliberately **deferred pending an eval** that proves it
> does not degrade synthesis grounding.

### 5b.4 Privacy/residency is a routing constraint, not a footnote

`privacy_class` is where data governance (§7) meets inference: a `public_api` binding and a
`private_endpoint` are **not** interchangeable for a regulated tenant. An org policy can bind
the capability — *"agents on `public_api` providers receive schema-only context, never raw
cells"* — enforced at assembly time. This is the inference face of the data plane's tenant
isolation, and it is a governance capability a wrapper cannot retrofit later.

### 5b.5 Metering normalisation

`kernel/metering.py` (R1) assumes `prompt_tokens` / `completion_tokens` come back. A
bring-your-own private endpoint may return nothing, so `token_accounting: estimated` needs a
local-tokenizer fallback and must report savings/spend as an **honest estimate with a
confidence band**, not fake-exact zeros — otherwise per-agent budgets break the moment an
exotic backend is bound.

> **Invariant #7 — inference is vended, never ambient.** A model binding (endpoint +
> credential) is a scoped capability resolved Org → Workspace → Agent, not global process env.
> Local/default is just a trivial implementation of that capability.

This lands with the **Phase 4** multi-tenant flip (per-org credentials, scoped vending), but the
seam — `vend_llm` + a canonical assembler behind `complete()` — is cheap to model now and makes
the flip a config change, exactly as `vend_storage` did for storage.

---

## 6. Multi-tenancy & isolation — the groundwork

Isolation is enforced in layers; each must be tenant-aware from the start:

| Layer | Mechanism | Status |
|---|---|---|
| **Namespace** | `org.catalog.schema.table`; catalog = isolation unit | add Org + catalog objects |
| **Storage path** | `{root}/{org_id}/{catalog}/…` | re-path uploads |
| **Access** | grants resolved by the control plane; scoped credential vending | model now, vend later |
| **Compute** | per-org/workspace DuckDB lane + concurrency gate | extend `lanes.py` with `org_id` |
| **Audit** | every query gated + logged (`security_post`) | tag with `org_id` |
| **Metering / billing** | per-job tokens/queries/rows/time | tag with `org_id` (`metering.py`) |

**The "config flip" — what changes single-org → multi-tenant** (and nothing else should):

- metastore backing store: SQLite/registry → **Postgres** (concurrent, multi-client);
- storage root: local FS → **S3/GCS** with real credential vending;
- catalog service: Aughor-native → optionally **Unity Catalog OSS server** (or expose the
  Aughor catalog *via* the UC / Iceberg-REST API for external-engine interop);
- identity: local users → **external IdP / SSO**;
- regional: a single region → **per-region metastores** (see §8).

If `org_id` is everywhere and access is vended, each of these is an adapter swap behind a
stable interface — not a migration.

---

## 7. Governance: two layers, cleanly separated

A core principle: **Aughor does not reinvent data governance.** Two distinct, complementary
layers:

- **Data governance (UC model)** — *who may read this table*, credential vending, lineage,
  the namespace, grants. Owned by the metastore/control plane (Aughor-native now,
  UC-OSS-compatible, optionally UC-OSS later).
- **Intelligence governance (Aughor's edge)** — *is this metric defined correctly, is this
  finding trustworthy, is this SQL safe, what did it cost, is the answer reproducible.* The
  ontology, metrics catalog, trust receipts, snapshot reproduction, the security/audit gate,
  metering/budgets, and the agent fleet.

They **layer**: a query first passes the data-governance check (does this workspace's grant
permit this catalog?), then Aughor's intelligence governance (safety gate → execution →
trust gate → metered receipt). Aughor's position is **"the governed-intelligence layer on an
open governed lakehouse"** — a sharper, more defensible position than owning the whole stack.

### 7.1 Trust & reproducibility become native

On this base, the snapshot-pinned-receipt work (`aughor/db/snapshot.py`, `revalidate.py`)
stops being opt-in and becomes the substrate: **every workspace is versioned, every finding
pins a data-version, every answer is reproducible-as-of, the whole org is a time-machine.**
Re-validate *proves* "correct-as-computed vs mis-derived" by reproducing a finding at its
pinned snapshot. No mainstream BI platform can say "here is exactly what the data looked like
when this decision was made, and I can re-derive the number." That is the moat, and it falls
out of this architecture for free — on DuckLake today, on Delta-under-UC tomorrow, through the
same seam.

---

## 8. Regional federation

"One metastore per region" is UC's unit and ours. An **Org has a home region**; its metastore
and storage live there. A regional cluster is a self-contained control+data plane. **Cross-
region is explicitly deferred** — but nothing assumes a single global namespace, so the later
options (per-region metastores with cross-region *sharing*, or org replication for DR /
data-residency) are additive, not a redesign. The `region` attribute exists on org/metastore
from day one even while there is one region.

---

## 9. Where the code is today → the gap

**Have (the seeds):** the connection registry (`db/registry.py`), workspace-as-reference-list
(`workspace/store.py`), the connection factory + pool (`db/connection.py` `open_connection`),
per-workspace compute lanes (R6, `db/lanes.py`), per-job metering (R1, `kernel/metering.py`),
the security/audit gate (`security_pre/post`), the snapshot seam + `DuckLakeConnection`
(`db/snapshot.py`, `db/ducklake.py`), and the intelligence layer (explorer, ontology, metrics,
ADA, agents).

**Gap to target:** no **Org** level; no **metastore service** (catalog/schema/grant as
first-class objects); storage not **tenant-pathed**; access is **ambient**, not vended; no
**UC-compatible API** surface; uploads land per-connection in-memory rather than as catalog
objects; `org_id` is absent from persisted objects, jobs, receipts, and metering.

---

## 10. Phased roadmap

Each phase ships value and is independently stoppable.

- **Phase 0 — done.** `DuckLakeConnection` + the format-agnostic snapshot/reproduction seam.
- **Phase 1 — the Org/tenant spine — ✅ done** *(2026-06-22/23, branch `2026-06-22-org-tenant-spine`).*
  `aughor/org/` (`Org` above `Workspace`, `current_org_id()` contextvar, registry + bootstrap);
  `org_id` on every persisted store (workspaces, connections, jobs, artifacts, lineage,
  audit_log) + metering; storage re-pathed to `{root}/{org_id}/{conn_id}/…` via the
  `aughor/platform/` control plane (`vend_storage()` — access is vended, never ambient,
  Invariant #2) with a crash-safe idempotent on-disk migration; the control-plane / data-plane
  split is explicit in code. Single org in practice; multi-tenant-shaped in structure.
- **Phase 2 — the metastore service — ✅ done** *(2026-06-23).* `aughor/metastore/` ships
  **Catalog + Grant** (a connection *is* a catalog within an org; a workspace holds USAGE
  grants) and now **Schema** (the middle of the `catalog.schema.table` namespace, synced from
  live introspection), all org-scoped. The **live data-path gate is flipped onto grants**: the
  five visibility gates resolve through `accessible_catalog_ids()` (reconcile-on-read, provably
  equal to the legacy `workspace_connection_ids()` gate), so the metastore is on the live path.
  A **UC-compatible read surface** (`/api/2.1/unity-catalog/{catalogs,schemas,tables}`) exposes
  the three-level namespace for external-engine interop. **Grants are fully authoritative** —
  an independent access-control layer (`/metastore/workspaces/{id}/grants` to grant/revoke), so
  the gate is `membership ∪ explicit grants` with no reconcile-on-read; an explicit grant widens
  access beyond membership and is durable across membership edits. *Remaining (later):* enforce
  schema/table-level grants; the four control-path reverse lookups (governance/compute)
  deliberately stay on the workspace store.
- **Phase 3 — storage maturity — ◑ in progress.** **Volumes** for the unstructured tier
  shipped (`aughor/volumes/`): catalog-scoped governed containers for files/images/PDFs/video,
  bytes vended to the tenant path (`{root}/{org}/{catalog}/_volumes/…`), a queryable object
  metadata catalog, and a `/metastore` API (create/list volume · put/list/download/delete
  object). *Remaining:* wire `extracted_text` to the R8 `prompt()`/`embedding()` operators;
  managed vs external locations; the credential-vending abstraction made real (S3/GCS).
- **Phase 4 — the multi-tenant flip.** Postgres-backed metastore; S3/GCS storage with scoped
  credential vending; external IdP/SSO; per-org metering → billing.
- **Phase 5 — scale & interop.** Optionally embed **Unity Catalog OSS** as the catalog service
  + a **Delta** lane (DuckDB `uc_catalog` extension); regional federation.

---

## 11. Decisions recorded

- **Align to the Unity Catalog object model** (Account/Org → Metastore → Catalog → Schema →
  Table/Volume/Function; Workspace = grants, no storage). It is the proven open standard and
  DuckDB already integrates with it.
- **Storage and catalog live at the Org/metastore level**, not the workspace. Workspaces
  receive **grants** (scoped views/rights/access).
- **Tenant-key everything now** (Invariant #1) and **vend access, never ambient** (Invariant
  #2) — these are the groundwork that makes multi-tenant a config flip.
- **Two storage lanes** behind one seam: DuckLake (embedded) now, Delta+UC (governed) later;
  the format bet is reversible via `db/snapshot.py`.
- **Aughor differentiates at the intelligence layer**, not by reinventing data governance.
- **Inference is a vended resource alongside storage and compute** (§5b): bring-your-own-model
  (local · API · private endpoint) bound Org → Workspace → Agent (inherited, last-most-specific
  wins). Per-provider caching/tooling quirks stay behind a capability profile; a canonical
  prompt assembler (stable prefix → volatile tail) is provider-agnostic and applied once.
- **Measure backend caching, don't assume it.** The prefix-cache probe found
  `qwen3-coder-next:cloud` does **not** reuse prefixes across requests (Ollama Cloud
  multiplexes workers) → Layer-B prefix alignment is dead for the shipped cloud binding.
  Layer-A is **adaptation, not compression** (context already curated); the destructive
  evidence-digest waits for a grounding eval.
- **Build the Org/tenant spine next** (Phase 1), not another feature — it is the only piece
  that cannot be added cheaply later.

## 12. Open questions

- **Sequencing:** ✅ **decided 2026-06-23 — local-first.** Keep shipping single-org value;
  multi-tenant stays the already-de-risked config flip. Phase 4/5 (Postgres metastore, S3/GCS
  vending, IdP/SSO, billing) wait for a concrete SaaS driver.
- **UC adoption depth:** ✅ **model + API now, server later.** The Phase-2 UC-compatible read
  surface implements the UC model + API shape; run UC-OSS the server only when scale earns it.
- **Format bet:** ✅ **decided 2026-06-23 — two lanes** (DuckLake embedded now / Delta-under-UC
  governed at scale, behind the `db/snapshot.py` seam — reversible, simpler local), not
  Delta-everywhere.
- **Identity:** which IdP/SSO standard for the multi-tenant flip; how org-level RBAC composes
  with Aughor's existing capability gates.
- **Billing model:** the metering spine (R1) exists; the pricing/packaging on top does not.

---

## 13. Invariants (the things that must stay true)

1. **Tenant-keyed everything** — `org_id` on every persisted object, path, job, receipt.
2. **Access is vended, never ambient** — compute gets a scoped capability from the control plane.
3. **Control plane ≠ data plane** — governance/identity/scheduling separate from storage/compute.
4. **Open formats, UC-compatible** — no proprietary lock-in; the catalog speaks an open API.
5. **Format-agnostic trust** — the snapshot/reproduction seam works on any version-aware backend.
6. **Two governance layers, cleanly separated** — UC owns data access; Aughor owns intelligence.
7. **Inference is vended, never ambient** — a model binding (endpoint + credential) is a scoped
   capability resolved Org → Workspace → Agent (§5b), not global process env.
