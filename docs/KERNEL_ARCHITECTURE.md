# The Aughor Kernel — North-Star Architecture & Reliability Base

**Directive (user, 2026-06-10):** we lack world-class architectural design, componentization, and the
thing that makes Databricks/Palantir-class platforms *really* good — reliability as a platform
property. Think 50 years ahead; build the base for it today. Proof required, no assertions.

---

## 0. The proof — measured on `correctness-next` @ `07f49fb` (2026-06-10)

These are executed measurements, not opinions (commands preserved below each):

| # | Fact | Value |
|---|---|---|
| P1 | except blocks that silently swallow (`pass`/`continue` as the body) | **207 of 644 (32%)** |
| P2 | Separate JSON files used as state stores in `data/` | **24** (plus 36 `json.dump`/`KeyedJsonStore` write sites in code) |
| P3 | Atomic write patterns (`os.replace`/tempfile-rename) in the state-writing modules (`util/`, `explorer/`, `ontology/`) | **0** |
| P4 | Locks (`threading.Lock`/`asyncio.Lock`/`RLock`) in the entire backend | **4** |
| P5 | Raw `asyncio.create_task` spawn sites (long-running work, unsupervised) | **17** (7 `add_done_callback` total) |
| P6 | `class Job` / `heartbeat` / event-journal concepts in the codebase | **0 / 0 / ~1 mention** |
| P7 | Ad-hoc status string literals (`"running"`, `"failed"`, …) acting as state machines | **50 literals across 18 files** |
| P8 | Frontend `fetch()` calls bypassing `web/lib/api.ts` | **36**, plus **7 independent `setInterval` polling loops** |
| P9 | God modules | `agent/investigate.py` 2,316 LOC · `explorer/agent.py` 2,305 · `app/page.tsx` 1,948 · `routers/investigations.py` 1,645 · `BriefingPanel.tsx` 1,576 |
| P10 | Modules importing `aughor.db` internals directly | **39**; private `_underscore` cross-imports: **37** |

<details><summary>Measurement commands (re-run to verify)</summary>

```bash
# P1: grep -rEn --include="*.py" -A1 "except( Exception)?( as \w+)?:" aughor/ | grep -cE "(pass|continue)\s*$"
# P2: ls data/*.json | wc -l ; grep -rEl --include="*.py" "json\.dump|KeyedJsonStore" aughor/ | wc -l
# P3: grep -rEn --include="*.py" "os\.replace|NamedTemporaryFile" aughor/util/ aughor/explorer/ aughor/ontology/ | wc -l
# P4: grep -rEn --include="*.py" "threading\.Lock|asyncio\.Lock|RLock" aughor/ | wc -l
# P5: grep -rEn --include="*.py" "create_task|ensure_future" aughor/ | wc -l
# P6: grep -rE --include="*.py" "class Job|heartbeat|journal" aughor/ | wc -l
# P7: grep -rEn --include="*.py" '"(running|failed|completed|pending|complete|paused)"' aughor/ | wc -l
# P8: grep -rEn --include="*.tsx" "fetch\(" web/components web/app | grep -v "api\." | wc -l
```
</details>

**The diagnosis these numbers prove:** every "intermittent" bug we chased (ontology not building,
samples vanishing, stuck explorations, blank canvases) is a *symptom of the same three missing
substrates*: no transactional state, no supervised work, no event spine. The platform doesn't have a
reliability bug — it has a reliability *architecture gap*. Patching WCH-3…8 individually would add
finally-blocks and locks to a foundation that keeps minting new instances.

---

## 1. What actually makes Databricks & Palantir great (the borrowable core)

Strip away the marketing and each rests on ONE substrate decision:

- **Databricks / Delta Lake:** an **append-only transaction log** over dumb storage. ACID, time
  travel, audit, concurrent-writer safety — all derived from the log, not implemented per-feature.
  Unity Catalog = ONE metadata/governance plane, not 24.
- **Palantir Foundry:** **everything is a versioned resource with provenance.** Transforms are
  deterministic builds with lineage; the ontology is the kernel; Actions are typed, validated
  mutations. AIP (their LLM layer) is *only* allowed to act through governed primitives — that's why
  enterprises trust it.
- **Both:** long-running work is a **job with a formal state machine** (submitted → running →
  succeeded/failed, heartbeats, retries, resume). Nothing important runs as a fire-and-forget task.

The 50-year frame: Aughor's destination is an **autonomous data organism** — fleets of agents
continuously exploring, validating, repairing, and briefing over an enterprise's data; humans set
intent and consume proven claims. Models will change; agent counts will go 1 → 10,000; features will
churn. What CANNOT churn is the substrate that makes autonomy safe:
**durable truth, supervised work, provable claims, and contracts between components.**
That substrate is what we build now. It is deliberately boring — that's the point.

---

## 2. The Aughor Kernel — three pillars + a contract layer

```
┌────────────────────────────────────────────────────────────────────┐
│  SURFACES      Next.js UI (generated client · one /events stream) │
│                CLI · API consumers                                 │
├────────────────────────────────────────────────────────────────────┤
│  DOMAINS       catalog · ontology · explorer · semantic ·          │
│  (components)  agent/ADA · delivery (monitors/briefs/actions)      │
│                — talk to each other ONLY via typed interfaces      │
├────────────────────────────────────────────────────────────────────┤
│  KERNEL        ┌───────────┐ ┌───────────┐ ┌──────────────┐        │
│                │  LEDGER   │ │ JOB KERNEL│ │ EVENT SPINE  │        │
│                │ 1 txn DB  │ │ supervised│ │ append-only  │        │
│                │ versioned │ │ state     │ │ journal →    │        │
│                │ artifacts │ │ machines  │ │ SSE/lineage  │        │
│                └───────────┘ └───────────┘ └──────────────┘        │
│                + error taxonomy (failure-is-data, no silent swallow)│
└────────────────────────────────────────────────────────────────────┘
```

### Pillar 1 — The Ledger (one transactional truth)

**`aughor/kernel/ledger.py`** — a single SQLite database (`data/system.db`, WAL mode) replacing the
24 JSON files. SQLite-WAL gives us multi-reader/single-writer ACID for free, zero new infra, and a
clean later swap to Postgres for multi-node (#12).

Schema (initial):

```sql
-- Versioned artifacts: ontologies, findings, briefs, monitors, metric defs, profiles…
CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,            -- ulid
  kind TEXT NOT NULL,             -- 'ontology' | 'finding' | 'brief' | 'profile' | …
  scope_conn TEXT, scope_canvas TEXT, scope_schema TEXT,
  version INTEGER NOT NULL,       -- monotonic per (kind, natural key)
  natural_key TEXT NOT NULL,      -- e.g. conn:schema:fingerprint
  payload JSON NOT NULL,
  created_at TEXT NOT NULL,
  created_by_job TEXT REFERENCES jobs(id),   -- provenance root
  superseded_by TEXT               -- never DELETE: supersede (preserves repros, standing rule)
);
CREATE TABLE jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL,    -- 'exploration' | 'ontology_build' | 'investigation' | …
  scope_conn TEXT, scope_canvas TEXT,
  state TEXT NOT NULL,            -- enum, ONE place: PENDING|RUNNING|PAUSED|SUCCEEDED|FAILED|CANCELLED
  checkpoint JSON,                -- resume point (phase, cursor)
  heartbeat_at TEXT, started_at TEXT, finished_at TEXT,
  attempt INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 1,
  idempotency_key TEXT UNIQUE,    -- submitting the same work twice returns the same job
  error JSON                      -- {stage, message, retryable} — never a bare string
);
CREATE TABLE events (             -- the platform's own transaction log
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, kind TEXT NOT NULL,       -- 'job.state' | 'artifact.written' | 'error' | …
  job_id TEXT, artifact_id TEXT, payload JSON
);
CREATE TABLE lineage (            -- provenance edges → Trust Receipts fall out of this
  artifact_id TEXT NOT NULL, derived_from TEXT NOT NULL,  -- artifact or job id
  relation TEXT NOT NULL          -- 'computed_by' | 'input' | 'validated_by' | 'source_sql'
);
```

Rules:
- **All writes transactional.** No state file is ever half-written again (kills P3=0 by construction).
- **`KeyedJsonStore` becomes a facade over the ledger** — its API is kept, so the 36 call sites keep
  working day one; stores migrate underneath one `kind` at a time.
- **Supersede, never delete** — encodes the preserve-bug-artifacts rule at the schema level.
- Time travel for free: `SELECT payload FROM artifacts WHERE natural_key=? AND version=?`.

### Pillar 2 — The Job Kernel (supervised autonomy)

**`aughor/kernel/jobs.py`** — every long-running operation becomes a `Job`. The 17 raw
`create_task` sites are replaced by ONE entry point:

```python
job = await jobs.submit(
    kind="exploration", scope=Scope(conn_id=...), payload={...},
    idempotency_key=f"explore:{conn_id}:{schema_fp}",
    resume_from_checkpoint=True,
)
```

Kernel guarantees (this is the whole reliability story):
1. **Typed state machine** — the only legal transitions live in one module; P7's 50 scattered
   literals are deleted.
2. **Heartbeats** — a running job touches `heartbeat_at` every N seconds from inside its work loop.
3. **The Supervisor** — a single kernel loop (replaces the one-shot `sweep_stale_running`): any
   RUNNING job with a stale heartbeat is declared dead → resumed from checkpoint (if
   `attempt < max_attempts`) or FAILED with a structured error event. Runs every 30s, forever.
4. **Crash-resume at boot** — the kernel scans the ledger at startup; interrupted explorations and
   builds resume themselves. (Today: connection explorations are dead after restart, `api.py:226`.)
5. **Cancellation is first-class** — deleting a canvas/connection cancels its jobs through the
   kernel; the task-leak class (`_canvas_explorer_tasks` growing forever) is structurally gone.
6. **Pause is owned by the kernel** — "pause explorers during investigation" becomes a kernel
   dependency rule (job A holds a pause-lease on jobs B; lease expires with A, whatever happens to
   A). The never-resumed-explorer bug cannot exist.
7. **Idempotency** — double-clicked buttons and racing auto-triggers (manual rebuild vs Phase-8
   build) collapse onto the same job instead of corrupting caches.

### Pillar 3 — The Event Spine (observe · push · prove)

Every job transition, artifact write, and structured error appends to `events`. Three consumers:

1. **The UI** — ONE `GET /events?scope=...` SSE channel replaces the 7 polling loops (P8). Panels
   subscribe; "exploration phase 5 done", "ontology enrichment failed: LLM timeout", "finding
   written" arrive as pushes. Polling survives only as a degraded fallback.
2. **Lineage / Trust Receipts** — every finding carries edges to: the job that computed it, the SQL
   artifact it ran, the profile snapshot it read, the validation that checked it. The B-1 "Trust
   Receipt" chip is a `SELECT` over `lineage`, not a feature build.
3. **Debugging & audit** — "why didn't the ontology build at 14:32?" is
   `SELECT * FROM events WHERE kind='error' AND at > …` — a query, not an archaeology dig.

### The contract layer (componentization)

- **Error taxonomy** (`aughor/kernel/errors.py`): bare `except: pass` is banned in kernel-managed
  code. The only legal swallow is `errors.tolerate(exc, reason="…", counter="…")` which logs, counts,
  and emits an event. A lint rule (CI) enforces it; the 207 silent swallows get triaged: most become
  `tolerate(...)` with a reason, the dangerous ones become real failures. **Failure becomes data.**
- **Typed domain boundaries**: domains export an explicit interface module (`aughor/ontology/api.py`
  etc.); importing another domain's internals (P10's 39 + 37) fails lint. Routers become thin
  adapters over domain interfaces.
- **Generated frontend client**: derive `web/lib/api.gen.ts` from the FastAPI OpenAPI schema in CI;
  the 36 raw `fetch()` calls migrate onto it; an endpoint/shape mismatch becomes a build failure,
  not a blank panel. (This permanently kills the wiring-drift class behind WCH-10.)
- **God-file decomposition follows the boundaries** (not cosmetic splitting): `explorer/agent.py`
  2,305 → phase components on the job kernel; `agent/investigate.py` 2,316 → graph nodes as units;
  `page.tsx` 1,948 → screen modules consuming the event stream; `BriefingPanel.tsx` 1,576 →
  card/layer components. Each split lands WITH its tests, incrementally.

### Pillar 4 — The Semantic Governance Plane (the SOTA trust wedge)

This is the layer that separates a demo from a platform a Fortune-500 data team
*trusts*. It is not new machinery — it is the **Ledger + Contracts applied to
meaning**: a metric definition is a versioned, owned, approved artifact, and the
AI is contractually forbidden from acting outside the governed set. Four
mechanisms, each mapped to a substrate we already have:

1. **Definitions are governed artifacts, not config.** `revenue`, `aov`, churn,
   margin — each is a versioned Ledger artifact (Pillar 1) with an `owner`,
   `approved_by`, and an audit trail of every change. A definition flows
   `proposed → reviewed → approved → enforced`; superseding a version preserves
   the old one (the artifact model already does this). *Today:* one flat
   `data/metrics.json` I hand-edited (UNIFY). *SOTA:* the human workflow around
   it — a business user proposes in the UI, an owner approves, it governs every
   query/dashboard/AI answer org-wide, instantly.
2. **The AI may only USE registered metrics — never invent one.** This is the
   single biggest trust differentiator, and it is a **Contract**: when a metric
   is governed, the SQL path must use that exact formula; when a requested metric
   is *not* governed, the agent says "this metric isn't defined yet — define it?"
   instead of free-handing a formula. Structural, not advisory — the generator
   is gated, the way the kernel gates a silent swallow. (Aughor already has the
   pieces: the canonical-metrics injection, the fan-out/grain guards, the
   semantic-drift guard. SOTA = compose them into a hard *use-only-registered*
   rule with a measured enforcement rate.)
3. **Every number self-justifies — receipts by default, not on click.** The K3
   lineage already records (metric definition → SQL → inputs → validation → job).
   SOTA surfaces it *inline*: hover any figure and see "net revenue, defined by
   Finance, this SQL, validated, as of 2pm." The receipt is the visible proof of
   mechanism #2 — the CFO's "can I put this in a board deck?" answered in one
   glance. (Built as a drawer in K3; the SOTA delta is *default-visible*.)
4. **Honest, deterministic measurement.** Governance claims ("the AI now never
   improvises a metric", "trusted answers rose") must be *provable*. UNIFY made
   the eval unconfounded but it is small and cloud-noise-dominated (a 2% lift is
   invisible). SOTA = a larger, harder benchmark on real warehouses with a
   deterministic decode, so an improvement is *visible* instead of drowned. The
   `runs_detail` cache already enables zero-LLM re-scoring; the gap is scale +
   determinism, a methodology choice not a code gap.

Why this is a *plane* and not a feature: meaning is the one thing autonomous
agents must agree on to be trusted at scale. Pillar 1 makes state safe to share;
Pillar 4 makes *definitions* safe to share — the same move, one level up.

---

## 3. Reliability you can demonstrate — the Proof Harness

Reliability is asserted today; under the kernel it is **executable**. `tests/kernel/` holds invariant
tests that run in CI and double as the marketing claim:

| Invariant | Test |
|---|---|
| **Crash-anywhere** | A chaos harness `kill -9`s the server at randomized points during exploration/build/investigation, reboots, and asserts: zero zombie RUNNING jobs, zero corrupted ledger state, every interrupted job resumed or FAILED-with-reason. Loops N kill-points. |
| **Zero-silent-failure** | Fault-inject every external dependency (LLM down, DB locked, disk full): every non-SUCCEEDED job must have a user-visible error event. No blank panels, no `ok: True` lies. |
| **Concurrent-everything** | 10 parallel rebuilds + explorations + polls on one connection: ledger integrity check passes, no deadlock, idempotency collapses duplicates. |
| **Restart-resume** | Restart mid-phase-5 exploration → exploration completes and the ontology builds without human action. |
| **Wiring contract** | Generated client compiles against the live OpenAPI schema; any drift fails CI. |

Scorecard (re-measured at each stage, published in this doc):
`state files 24 → 1` · `silent swallows 207 → <20 (each with a reason)` · `unsupervised tasks 17 → 0`
· `polling loops 7 → ≤1 (fallback)` · `status literals 50 → 1 enum`.

---

## 4. Migration plan — K0…K4 (incremental, NEVER a rewrite)

> **STATUS (2026-06-10):** ✅ K0 (`2631d4e`) · ✅ K1 (`82c5b4d`, live crash-drilled) ·
> ✅ K2+K3 (`9b6b97e`, live-drilled: SSE phase events + real finding receipt) ·
> ✅ K4 core (errors.tolerate + swallow/private-import ratchets pinned at 269/70 +
> OpenAPI wiring-contract test) · ✅ Proof Harness (`tests/stress/` + `scripts/chaos_drill.py`,
> §3) — chaos drill ran 3× random `kill -9`, ALL RECOVERED (4 jobs caught mid-flight,
> failed-with-reason + resumed). K4 follow-ups still open: generated typed TS client
> (response-shape coverage), domain interface modules, god-file splits. WCH-8's
> .duckdb write coordination also remains open. Scorecard re-measure due after the
> ratchets have had a few sessions to bite.

Each stage ships independently, is verified by the harness, and leaves the app working. Old paths are
deleted only after the new path passes its invariant tests.

| Stage | Scope | What lands | Proof gate | Effort |
|---|---|---|---|---|
| **K0 — Ledger** | `aughor/kernel/` new; zero behavior change | `system.db` + schema + `Ledger` API; `KeyedJsonStore` facade re-backed onto it; ontology/profile/briefing caches migrate first (the racing ones); event journal table live (writers only) | Concurrent-everything invariant on the migrated caches; state-file count starts dropping; WCH-3b/-3e become deletions | M |
| **K1 — Job Kernel** | exploration, ontology build, investigation, monitor runs, brief delivery | `Job` + supervisor + heartbeats + checkpoints + idempotency + pause-leases; the 17 `create_task` sites migrate; boot-resume | Crash-anywhere + restart-resume invariants; **WCH-4, 5, 6, 7, 8 are deleted as separate items — they're kernel properties now** | L |
| **K2 — Event Spine to UI** | one SSE `/events` channel; panels subscribe | ChatPanel/Briefing/Exploration/DomainIntel stop polling (fallback kept); live job progress everywhere (feeds the motion pass — real progress, not fake spinners) | Polling-loop count ≤1; network-trace before/after; WCH-11 absorbed | M |
| **K3 — Lineage & Trust Receipts** | artifacts + lineage edges; receipt chip UI | findings/briefs/monitors written as versioned artifacts with provenance; B-1 ships as a query over `lineage` | A finding's receipt shows job, SQL, inputs, validation — live demo; supersede-not-delete verified | M |
| **K4 — Contracts** | error taxonomy + lint; generated TS client; domain interface modules; god-file splits begin | `errors.tolerate` + CI lint (no new silent swallows); `api.gen.ts`; boundary lint | Swallow count <20; wiring-contract invariant in CI; WCH-10 absorbed | M–L |
| **K5 — Semantic Governance Plane** | metrics as governed Ledger artifacts (owner/approve/version/audit); the *use-only-registered* generation contract; receipts default-visible; deterministic benchmark | UNIFY registry ✅ → governance workflow + enforcement gate + inline receipts + harder eval | **Enforcement rate** (% of metric-bearing answers using a registered formula) measured + risen; receipt visible on every figure; a metric change is auditable | L |

**Migration status (2026-06-10):** K0–K4 ✅ shipped + drilled. **K5 is the next architectural stage** —
its first brick (the UNIFY metric registry + schema-scoped injection) is already in; the remaining
bricks are the governance workflow, the AI-use-only-registered contract, default-visible receipts, and
the deterministic benchmark (see the 5-step plan below / `WORLD_CLASS_HARDENING_PLAN.md` Phase 5).

**What we explicitly do NOT do:** no microservices, no message broker, no Postgres requirement (SQLite
WAL until #12 multi-node), no framework swap, no big-bang rewrite. The kernel is ~4 focused modules;
everything else migrates onto it incrementally.

### Reconciliation with `WORLD_CLASS_HARDENING_PLAN.md`

- **Do now, pre-kernel (user-visible, tiny):** WCH-1 (blank canvas — 15 lines), WCH-2a–2c (sample-data
  honesty: instrument seed, error field, three-state UI).
- **Absorbed by the kernel:** WCH-3 (build status = job events) · WCH-4–8 (orphan class = K1) ·
  WCH-11 (poll storm = K2) · WCH-10's contract test (= K4) · B-1 Trust Receipts (= K3).
- **Unchanged, after K1:** WCH-9 stress suite (becomes the proof harness's scenario layer),
  WCH-12 (schema cache), WCH-13/14 (LLM & phase parallelism — *safe* to do once jobs are supervised),
  WCH-15–17 (motion system — now animating real kernel events, which is what makes motion feel honest
  instead of decorative).

### Recommended sequence

```
WCH-1 + WCH-2a–c   (days; user-visible wins while kernel work starts)
K0 → K1            (the reliability base — the bulk of the arc)
K2                 (UI goes event-driven; pairs naturally with WCH-15/16 motion)
WCH-9 harness + scorecard re-measure   (publish the before/after numbers)
K3 (Trust Receipts) → K4 (contracts) → WCH-12/13 perf → UNIFY → #12
```

---

## 5. The 50-year test (why these four substrates and not others)

Imagine the 2076 version: thousands of autonomous analyst-agents per enterprise, continuously
negotiating with each other over what's true in the data, self-healing pipelines, regulators auditing
AI-made claims. Every one of those capabilities reduces to a question we can answer today:

- *Can two agents act on the same state without corrupting it?* → **Ledger** (transactions).
- *Can work survive any crash, anywhere, and prove what happened?* → **Job Kernel** (supervision).
- *Can any claim be traced to its evidence, mechanically?* → **Event Spine + Lineage** (provenance).
- *Can components — including AI-written ones — evolve without breaking each other?* → **Contracts**.

Palantir and Databricks won because they answered these before scaling features. Nothing in the four
answers depends on today's models, today's UI, or today's feature list — which is exactly what makes
them the right base to lay now.
