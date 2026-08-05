# Running Aughor on Vercel at full capacity — design note

**Status:** proposal; §1's trim is IMPLEMENTED · **Date:** 2026-08-05

This note answers one question: *can the whole platform — not a demo — run on Vercel, and
if so, how?* It is written against measurements taken on `main` @ `1ea6ca3`, not against
assumptions. Every number below is reproducible with the commands in
[Appendix A](#appendix-a--how-the-numbers-were-taken).

---

## 1. The headline: the bundle is a solvable packaging problem, not a wall

The 250 MB serverless limit was assumed fatal because the development virtualenv is
**1.1 GB**. Most of that never reaches the serving path — but the deployable figure is the
**declared dependency set**, not the boot closure. Measured honestly and then acted on, it
went from **622 MB to 225 MB**, which fits.

> **Correction (2026-08-05, after implementing the trim).** The first version of this
> section reported the **boot closure** (~110 MB) as the bundle size. That was the wrong
> measure: a deployment installs the **declared dependency set**, not merely what the
> process imports at startup. That correction cost the claim its comfort — the honest
> starting figure was 622 MB, not 110 MB — and the trims below are what actually closed it.

| Measurement | Result |
|---|---|
| Development venv (all extras) | **1,100 MB** |
| API boot import closure (44 packages — what actually *loads*) | **121 MB** |
| **Runtime dependency install — BEFORE the trim** | **622 MB** |
| Runtime install — after step 1 (statsmodels/polars/export) | 268 MB |
| **Runtime install — after step 2 (semantic)** | **225 MB** |
| Application code (`aughor/**.py`) | **7 MB** |
| **Against the Vercel limit** | **~232 MB — UNDER 250 MB** ✅ |

The two trims removed **397 MB (64%)**. What remains, and why:

| Package | Size | On boot path? | Status |
|---|---|---|---|
| `scipy` | 71 MB | no — but on the **analysis** path | **kept** (`tools/stats.py` → `agent/explore.py`, `nodes.py`, `investigate.py`) |
| `duckdb` | 44 MB | yes | core |
| `grpc` | 39 MB | no — pulled by `qdrant-client` | **moved to `[semantic]`** |
| `numpy` | 22 MB | no | required by scipy |
| `cryptography` | 13 MB | yes | core (secretvault) |
| `openai` | 11 MB | yes | core |
| `psycopg2` | 10 MB | no | Postgres connector |

`qdrant-client` + `grpc` (42 MB) was the last lever and has now been pulled — carefully,
because it was the one with teeth. An AST pass over all **19 import sites found 7 that were
bare**, so simply moving the package would have raised `ImportError` from inside a purge
hook or a suggestion lookup. `semantic/vector_store.py` is now the single seam.

**What was done** (see `[project.optional-dependencies]`):

* **`statsmodels` deleted** — 36 MB, imported by zero modules. A test now fails if it returns.
* **`polars` → `[fastread]`** — 192 MB (+120 MB `pyarrow`) for one call site in
  `db/connection.py` that already falls back to DuckDB on `ImportError`.
* **`reportlab`, `python-pptx`, `matplotlib` → `[export]`** — the PDF/PPTX renderers, reached
  only via `from aughor.export import export_report` inside a router handler. `aughor/export`
  now degrades to `ExportUnavailable` naming the install command, and the route answers
  **501** rather than 500, because a missing extra is a configuration state, not a fault.
* **`scipy` kept**, with a comment recording why — it is absent from the boot closure but
  present on the analysis path, which the first measurement missed.
* **`qdrant-client` → `[semantic]`** — 42 MB with grpc. `vector_store.available()` gates
  every entry point; reads return empty and writes no-op, because a deployment without
  semantic search *has* no index. A **connection** failure still raises: an absent package
  is a deployment choice, a configured index that is down is an outage worth surfacing.

**The guard rails matter more than the megabytes.** `tests/unit/test_serving_footprint.py`
imports the API in a subprocess and fails if any heavy package returns to the boot closure,
and simulates `qdrant-client`'s absence — with a vacuous-pass guard, since the development
environment has it installed and would otherwise exercise only the happy path.

The boot closure was captured by importing `aughor.api` and diffing `sys.modules` — so it
is what the process actually loads, not what `pyproject.toml` declares. Absent from it:

> `polars`, `pyarrow`, `pandas`, `numpy`, `scipy`, `statsmodels`, `matplotlib`,
> `langgraph`, `mlflow`, `connectorx`, `reportlab`, `python-pptx`, `qdrant-client`

Those are ~700 MB of the venv and **the API does not import any of them at boot.**

One finding remains open after the trim:

* **`botocore` (21 MB) is in the boot closure** of a *development* environment, though
  nothing in `aughor/` imports it — it arrives transitively via `boto3` /
  `snowflake-connector-python` / `mlflow-skinny`, all of which live in extras. A
  runtime-only install never pulls it, so it needs no action; it is recorded here because
  it will reappear in any measurement taken against a dev venv.

**Conclusion:** bundle size was a dependency-hygiene problem and it is **solved** —
**622 MB → 225 MB (−64%)**, roughly 232 MB deployed, inside the 250 MB limit with ~18 MB to
spare. Thin, so the ratchet is the durable part: one convenience import at module scope
would put it back and nothing else would notice.

The headroom is real but not generous. If it needs to grow, `scipy` (71 MB) is the next
candidate — it is on the analysis path today, so moving it means making `tools/stats.py`
lazily imported by its three callers, which is a larger change than any made here.

---

## 2. The real blocker

> **The platform assumes one process with a local disk.**

That single assumption produces every genuine obstacle:

| Assumption | Evidence | Why serverless breaks it |
|---|---|---|
| Local disk is durable | **~35 SQLite DBs** (`system.db` 96 MB, `checkpoints.db` 128 MB, `audit.db` 36 MB), **52 JSON/JSONL stores**, **13 directory stores**, 7 `.duckdb` files | Functions have no persistent disk; `/tmp` is ephemeral and per-invocation |
| Work runs to completion in-process | an exploration ran **102 queries over ~8 minutes**; investigations take 2–5 min | Exceeds function duration; no long-lived process |
| One process owns all state | Job Kernel docstring: *"single-process runtime"*; boot recovery fails every non-terminal job because it assumes the only process died | Concurrent workers make that reasoning wrong, silently |
| A scheduler lives in-process | APScheduler heartbeat | No always-on process to host it |

**The encouraging half — but measured properly this time.** An AST pass over all of
`aughor/` (not a grep) finds **40 mutated module-level containers across 32 modules**, not
the 5 first reported. The count is the less important half of the correction: what matters
is that they fall into three groups, and only the third is a migration blocker.

| Group | Count | Serverless behaviour |
|---|---|---|
| Import-time registries (`_EVALUATORS`, `_PIPELINES`, purge/execution hooks, `SCENARIOS`) | ~15 | **Harmless** — every process rebuilds them identically at import |
| Memo caches (`_schema_cache`, `_GRAIN_CACHE`, `_EMBED_CACHE`, `_COLTYPE_CACHE`, `_SEEN`, …) | ~15 | **Lose hit-rate, not correctness.** Cost, though, is not zero: `_SEEN` in `explorer/revalidate_live.py` suppresses re-running a finding's SQL, so per-invocation instances would re-validate up to 12 findings' queries on **every** refresh |
| **Coordination state** (`llm/provider.py`: `_LAST_CALL_AT`, `_quota_cooldown`, `_SEMAPHORES`; `kernel/metering.py`: `_by_job`; `telemetry.py`: `_traces`) | **5** | **Breaks** — see below |

So "the refactor is bounded" survives, but its *content* changes: the work is not 40
conversions, it is **5 pieces of coordination state**, and two of them are load-bearing for
this very plan.

**`kernel/metering.py:_by_job` is the one to schedule next.** Its own comment states why it
exists: *"the kernel heartbeat (a separate task, which can't see the job task's contextvar)
can enforce budgets."* Budget enforcement is therefore a handoff between a job and its
supervisor through a module-level dict — and the entire durable-execution refactor (§3.1) is
predicated on those two no longer sharing a process. Split them and `metrics_for_job()`
returns `None`, so **budgets stop being enforced and nothing reports an error**: precisely
the §5.2 class of defect that hides behind healthy status codes. It must move with the
kernel state into Postgres, not after it.

`telemetry.py:_traces` (investigation_id → Langfuse trace) costs observability rather than
correctness — spans orphan across invocations.

> **The LLM gates were process-local.** `_LAST_CALL_AT` paces calls `60/RPM` apart,
> `_quota_cooldown` records an exhausted backend, and `_SEMAPHORES` caps in-flight calls
> with a `threading.Semaphore` — which caps nothing whatsoever across processes. §3.5
> measured Vercel spreading five slices over **three cold plus two warm instances by
> itself**, so N instances each independently honour a declared 15 RPM and the endpoint
> sees 15×N; a backend one instance has learned is exhausted keeps being probed by the
> rest. Measured caps this runs against are small enough for that to bite:
> gemini-3.1-flash-lite at **15 RPM / 500 per day**, OpenRouter free at **20 RPM / 1,000
> per day**.
>
> **Made closable — not yet closed** — by `aughor/llm/coordination.py`. The three gates now
> sit behind a `Coordinator` Protocol, and the default `InProcessCoordinator` is today's
> exact behaviour, still one instance per process. **The multi-instance defect is therefore
> still present**; what changed is that closing it is now a backend implementation plus one
> env var (`AUGHOR_LLM_COORDINATOR`) rather than a provider rewrite. No shared backend ships
> here, deliberately: there is no Redis to verify one against, and an unexercised
> distributed implementation is a liability, not progress.
>
> Proof the seam bears weight is by simulation, which needs no infrastructure: two
> `InProcessCoordinator` objects stand in for two instances and **fail** to hold the limit
> (asserted, so the problem is demonstrated rather than described), while one shared object
> holds it. See `tests/unit/test_llm_coordination.py`.
>
> Note this is **not** Vercel-specific: the same seam is what would make a multi-worker
> `uvicorn --workers N` honour its own rate limit, which it does not today.
>
> 🔑 **The clock is part of the contract.** `time.monotonic()` has a *per-process* epoch,
> so a shared backend that stored those numbers would compare unrelated timelines and
> produce no pacing at all while appearing to work. The Protocol therefore exchanges
> **durations, never timestamps**, and a test asserts it.

**The other encouraging half.** Two pieces of existing architecture do most of the heavy
lifting:

1. **The Job Kernel (K1)** already has a persisted state machine
   (`PENDING → RUNNING → SUCCEEDED | FAILED | CANCELLED`), heartbeats, an orphan
   supervisor, idempotency keys, and scope cancellation. It needs its *coordination
   model* replaced, not its *design*.
2. **`sqlglot` runs through 40 modules.** Dialect transpilation is already a first-class
   concern, which makes "push the query down to the customer's warehouse" a configuration
   of something built, not new work.

---

## 3. Target architecture

| Layer | Today | Target |
|---|---|---|
| Frontend | Next.js on Vercel | unchanged |
| API | FastAPI, one process | stateless Python functions; SSE streaming already supported |
| Relational state | ~35 SQLite files | one Postgres (Neon/Supabase) |
| Documents & artifacts | 52 JSON/JSONL + 13 dir stores | Blob storage |
| Caches | local JSON (`briefing_cache.json`) | Redis (Upstash) |
| Analytics | local `.duckdb` files | **MotherDuck** (hosted) + **warehouse pushdown** (enterprise) |
| Long work | in-process asyncio | **durable workflow** — queue-driven slices |
| Scheduler | APScheduler | Vercel Cron |

### 3.1 Durable execution — the central refactor

Today an exploration is one 8-minute asyncio task. It must become a sequence of short,
independently-invocable steps over durable state.

The explorer is already close: `_save_state()` is called at **11 sites**, persisting
phase, counters, findings and negative knowledge as it goes. The unit of slicing is
natural — Phases 2→9 are explicit, and Phase 8 (the long one, ~100 queries) already
emits and de-duplicates one finding at a time, so it slices at the *angle* level.

Two changes make it serverless-safe:

* **Leases replace process-ownership.** A worker claims a slice with a time-bounded lease
  and heartbeats it; if the lease lapses, another worker reclaims it. This directly
  replaces the current boot-recovery rule, which is only sound when a restart implies
  every non-terminal job is dead.
* **Idempotent steps.** Already partly present via the kernel's idempotency keys; each
  slice must be safe to execute twice, because at-least-once delivery is what queues
  guarantee.

Queue candidate: **Inngest** (designed for durable step functions on serverless, good
Python support) or **Upstash QStash** (lighter, less structure).

### 3.2 Analytics

Three tiers, all already supported by the dialect layer:

* **MotherDuck** — hosted DuckDB, preserves the semantics the codebase assumes.
* **Warehouse pushdown** — Snowflake/BigQuery/Postgres via `sqlglot`; the enterprise story.
* **DuckDB-in-function over Parquet in Blob** — for small datasets and the demo path.

---

## 3.3 The falsification spike — RUN, and it passed

Deployed 2026-08-05 to a throwaway Vercel project (`aughor-duckdb-spike`), separate from
the demo. Source in `scratchpad/spike`; not added to this repo.

| Step | Result | Cold | Warm |
|---|---|---|---|
| A. `import duckdb` (Linux wheel loads) | ✅ v1.5.5 | 391 ms | 0 ms |
| B. query Parquet bundled in the function | ✅ 112,439 rows, €45,437,544 | 16 ms | 2 ms |
| C. `INSTALL httpfs` + `LOAD` into `/tmp` | ✅ | 618 ms | 120 ms |
| D. read remote data over HTTPS | ✅ | 269 ms | 72 ms |
| E. real analytical query (GROUP BY over 112k rows) | ✅ | — | 24 ms |
| F. `sqlglot` transpile to Snowflake/BigQuery | ✅ | 173 ms | 2 ms |

**≈1.5 s cold, ≈220 ms warm.** The build ran on **Python 3.12**, and Vercel's Python
runtime takes an **ASGI entrypoint** (`[tool.vercel] entrypoint = "app:app"` in
`pyproject.toml`) — so FastAPI is a first-class citizen and the existing app shape carries
over.

Three results matter more than the pass/fail:

1. **`httpfs` installs at runtime on a read-only filesystem** — this was the predicted
   most-likely failure. It works provided `extension_directory` and `home_directory` point
   at `/tmp`. Cost: **618 ms cold, 120 ms warm, per invocation.** That is a real per-slice
   tax and an argument for coarser slices; pre-bundling the extension would remove it.
2. **Correctness held.** Step E returned logistics ratios by platform — THE OUTNET
   `0.0997`, YOOX `0.0768`, MR PORTER `0.0480`, NET-A-PORTER `0.0444`, Mytheresa `0.0403`
   — **identical to the same query run locally against DuckDB.** Same engine, same answers,
   different runtime.
3. **A false negative worth recording.** The first attempt failed steps D/E with
   *"No magic bytes found at end of file"*. The cause was **Deployment Protection**: DuckDB
   fetched an HTML login page and correctly refused it. Nothing to do with httpfs. Any
   future test that reads from a protected deployment will hit this — use a public origin
   or a bypass token.

**Verdict: the runtime assumption is confirmed, not refuted.** Python + DuckDB + sqlglot
run in a Vercel function, query bundled and remote data, and produce answers identical to
local. The programme's remaining risk is entirely in state and durable execution (§2), not
in the runtime.

---

## 3.4 The durable-execution spike — RUN, and it passed

The plan's second load-bearing assumption: an 8-minute in-process exploration can be
decomposed into short, resumable, queue-driven slices. Tested by deploying a `/api/slice`
endpoint doing **claim (lease) → load state → real DuckDB query → merge → return state**,
then driving five slices as five *separate* invocations with the caller acting as the queue.

**State is small — the feared blocker is absent.** Measured on real artifacts:

| | |
|---|---|
| Largest exploration state on disk | **68 KB** (`914df862` = 49 KB) |
| Dominated by | `insights` — 29 KB for 21 findings (~1.4 KB each) |
| JSON round-trip (deserialize + serialize) | **0.4 ms** |

**Per-slice cost, five separate invocations:**

| Payload | Wall (median) | In-function | Work (real query) | **Slicing overhead** |
|---|---|---|---|---|
| 1 KB state | 222 ms | 3.4–7.0 ms | 3.3–6.9 ms | **0.10–0.13 ms** |
| **49 KB real state** | 459 ms | 4.8–6.6 ms | 3.7–5.5 ms | **~1.1 ms** |

The chain resumed correctly across invocations — final state `phase=complete`,
`queries=5`, `findings=5`, each slice building on the last.

**Leases work.** A second worker was refused with **HTTP 409** while the first held the
lease, and **reclaimed** it once the lease lapsed. That is the mechanism that replaces the
kernel's *"single-process runtime"* assumption.

### What the numbers mean

Slicing overhead *inside* the function is ~1 ms — effectively free. The per-slice cost is
**network round-trip**, ~220 ms at 1 KB and ~460 ms carrying 49 KB of state.

Applied to a real Phase-8 angle, which is dominated by an LLM call measured at **8.8 s**:

```
slice = ~0.3 s transport + ~8.8 s LLM + ~0.01 s query  ≈  9.1 s
overhead ≈ 3% of the slice
102 slices × ~0.3 s ≈ 31 s added to an ~8-minute run  ≈ +6% wall-clock
```

**Slicing is viable.** The tax is single-digit percent, and it buys resumability,
horizontal scale, and survival of worker death.

Two consequences for design:

* **Pass a state *reference*, not the state.** 49 KB doubled the round-trip (222 → 459 ms).
  Slices should exchange a key and read/write the store directly, keeping queue messages
  small.
* **The httpfs tax argues for warm reuse.** 618 ms cold / 120 ms warm per invocation (§3.3)
  is comparable to the entire transport cost. Reusing the connection across slices — as the
  spike does via a module-level handle — or pre-bundling the extension removes it.

---

## 3.5 The cost test — RUN, and it moderates §5.1

Serverless bills for time the function is held open, so what a slice *costs* depends only
on its duration — not on whether that time is inference or any other wait. The test used a
wait calibrated to **measured free-tier latency** (nemotron-120b **8.8 s**), so no
inference was purchased and no credential left the machine.

**One LLM-shaped slice** (1024 MB, real DuckDB query + real egress + 8.8 s wait):

| | |
|---|---|
| Real analytical query | 64 ms |
| **Egress to `openrouter.ai` from inside the function** | **47 ms, HTTP 200** |
| Inference wait | 8,800 ms |
| Total | 8,911 ms |
| **Billed duration that is pure idle-waiting** | **98.8%** |

**Five concurrent slices:**

| | |
|---|---|
| Wall-clock for all five | **18.1 s** (serial would be 44 s) |
| Instances | 3 cold + 2 warm — Vercel scaled out automatically |
| **Aggregate function-seconds billed** | **~44.4 s** |

Two facts follow, and they matter more than any price:

1. **Concurrency is real and automatic** — five slices ran in parallel across instances with
   no queue of our own. But **billing is the sum of durations, not the wall-clock**: 44.4
   function-seconds for 18.1 s of elapsed time.
2. **98.8% of each slice is idle.** Whether that idle is cheap depends entirely on whether
   the platform charges it as active CPU. Vercel's Fluid model bills *active CPU* separately
   from *provisioned memory*, so genuinely-idle time should cost the (much cheaper) memory
   rate — **but only if the wait is truly non-blocking.**

### Arithmetic for one exploration (102 LLM-bound slices)

```
102 slices × 8.9 s      = 908 function-seconds = 0.252 GB-hours @ 1 GB
  memory-time only      ≈ $0.003     per exploration
  if idle bills as CPU  ≈ $0.032     per exploration      (~10× worse)
  invocations           ≈ negligible
```

> ⚠️ Rates are from general knowledge and **must be verified against current Vercel
> pricing** before any decision rests on them. The *function-seconds* above are measured
> and are the durable input to whatever the rates turn out to be.

At 1,000 explorations/month that is roughly **$3–$35**, against a small always-on container
at a **flat ~$3–7/month** — which is cheaper per unit at high volume but costs the same when
nothing is running and does not scale out by itself.

### What this changes

**§5.1 was too pessimistic.** The concern was "paying premium rates to idle." The measurement
says idle-waiting is affordable *provided two things hold*:

* **The LLM call must be `async`/non-blocking.** The spike used a blocking `sleep`; a real
  slice must `await`, or the runtime cannot treat the wait as idle and the 10× penalty
  applies. **This is now an architectural requirement, not a preference.**
* **Warm reuse matters.** 3 of 5 concurrent slices were cold; at ~1.5 s cold-start each
  (§3.3), 102 mostly-cold slices would add ~2.5 minutes of billed time for nothing.

**Revised recommendation:** serverless is viable for the LLM path, and the deployment-choice
hedge in §5.1 stands — not because serverless is too expensive, but because the decision now
turns on verified pricing and on async discipline, both cheap to establish.

---

## 4. Sequence

**Week 1 — ~~falsify before funding~~ BOTH SPIKES DONE (§3.3, §3.4).** Runtime and durable
execution are proven. Remaining risk is concentrated in **state externalization** (§2) —
the ~35 SQLite stores — which is engineering effort, not technical uncertainty.

~~The next test worth buying is **cost, not capability**~~ **THE COST TEST RAN 2026-08-05,
with live LLM calls — and it settles §5.1.**

One real exploration (LuxExperience, fresh state, full profiling + ontology + Phase 8)
instrumented at the process level with `getrusage` — so the CPU number covers every
thread, LLM retries and throttle-waits included:

| Measured | Value |
|---|---|
| Queries executed / findings | 100 / 10 (stopped by hand at the reference workload size) |
| **Active CPU, whole exploration** | **27.7 s** |
| Wall time (free tier, heavily throttled evening) | 3,924 s |
| **Idle share** | **99.3%** (Spike 3 predicted 98.8%) |

Pricing was **verified against the live Vercel docs** (dated 2026-06-16), which also
resolve §3.5's 10× question *officially*: "Active CPU is billed only while your code
executes; CPU billing pauses when waiting for external services." iad1 rates:
$0.128/CPU-hr, $0.0106/GB-hr memory, $0.60/M invocations.

```
Active CPU:  27.7 s → $0.0010 per exploration
Memory @1GB: 908 fn-s (daytime 8.8 s/call latency)  → $0.0027
             3,924 fn-s (throttled evening)          → $0.0116
TOTAL:       ~$0.004 per exploration (daytime) · ~$0.013 (worst-case throttling)
Break-even vs a ~$5/mo always-on container: ~1,300 explorations/month
```

**Verdict: serverless is cheap for this workload — compute is not the cost driver at
any realistic volume.** Below ~1,000 explorations/month serverless wins outright and
scales to zero; the container becomes cheaper per unit only past ~1,300/month, at which
point ~$5/month is noise anyway. Provider latency, not platform pricing, dominates the
bill — a paid inference tier changes the economics more than any deployment choice.

Caveats recorded honestly: the run was stopped at 100 queries/3 domains (the throttled
tail added no new information); the metering contextvar missed executor-thread LLM
counts in the bare-script harness (the process-level CPU number is unaffected); and the
throttled wall time is a worst case that a paid tier or daytime free tier roughly
quarters.

**Phase 1 — externalize state. THE RELATIONAL BULK SHIPPED 2026-08-05 — proven on a live
Postgres, not asserted.** Every platform SQLite store (~33 modules, the kernel Ledger
included) now opens through `aughor/db/backend.py`: default is byte-for-byte today's
tuned sqlite; `AUGHOR_DB_URL=postgres://…` moves the store — schema-per-store in one
database — behind a wrapper that speaks the sqlite3 surface the stores already use.
Store SQL stays sqlite-dialect; the seam transpiles per statement (sqlglot, cached) and
patches what a 420-statement corpus measurement showed survives verbatim (OR
IGNORE/REPLACE, rowid, reserved words, ON CONFLICT SET ambiguity, literal `%`), maps
declared types to keep string-first storage semantics, and answers `user_version` /
`table_info` truthfully because the migration framework runs on them. **The 1,479-test
store sweep passes against a real dockerized Postgres 16** (and 1,414 unchanged on
sqlite). The live run surfaced one latent bug sqlite absorbed (bare column under GROUP
BY returning an arbitrary row) and two file-existence guards that read as "no data" on
a fileless backend — the §5.2 lesson again: none of this was visible without a real
server.

**Still open in Phase 1, deliberately:** the per-connection JSON document family
(`exploration_*` / `business_profile_*` + episodes JSONL). Its migration crosses the
purge cascade's file-glob contract — where this repo's real data-loss bugs have lived —
and Phase 2's durable execution reworks explorer persistence anyway (state references,
slice-level saves), so it moves *with* that work, not ahead of it. Directory stores
(`uploads/`, `context_graph/`, `kb/`) are genuine file artifacts → Blob in Phase 3.
Connection pooling is a knob, not a blocker: stores connect per operation, fine locally,
worth a pool in front of a managed Postgres.

**Step 0, seam landed 2026-08-05: the LLM coordination gates** (§2) — small, and it is what
gates the concurrent-slice fan-out every number in §3.5 rests on. The Protocol and the
in-process default ship; **the shared backend does not**, so the fan-out defect stands until
one is written and verified against real Redis.

**Step 0b, landed 2026-08-05: budgets enforceable across the process split.** The heartbeat
now flushes the run's live spend onto the job row in the same UPDATE as `heartbeat_at`, and
both budget readers (`_over_budget`, `budget_fraction_used`) fall back to that snapshot when
the process-local registry misses — at most one beat stale. A test drives the real heartbeat
loop against a run whose accumulator it cannot see and requires the cancel. Without this,
splitting job from supervisor silently stopped token-budget enforcement (`metering._by_job`
miss read as "no spend").

**Step 0c, landed 2026-08-05: the three raw-file caches are on the Ledger facade.**
`briefing_cache` / `patterns_cache` / `schema_cache` now go through `KeyedJsonStore`
(per-key transactional, legacy file imported once and left untouched;
`test_cache_store_races.py` demonstrates the lost-write race against the raw pattern and
its absence through the store). This is the "caches first" step — done against the seam
that already existed, so Redis later means one Ledger backend, not three migrations.

**Step 0d, landed 2026-08-05: Langfuse spans survive the invocation split.**
`telemetry._traces` is now a memo, not an identity: a miss rebuilds the handle by trace
id (Langfuse upserts on id) instead of silently orphaning the span. With this, **all five
§2 coordination-state items are dispositioned** — LLM gates (seam), `_by_job`
(flush + fallback), `_traces` (rebuild by id); the ~15 registries rebuild identically per
process and the ~15 memo caches lose only hit-rate. What remains of Phase 1 is the bulk:
~32 SQLite stores → Postgres, and the 49 remaining JSON/dir stores.

Then **caches — but onto the seam that already exists, not straight to Redis.**
`kernel/ledger.py` is already a transactional store with `kv(store, key, value, seq,
updated_at)`, and `KeyedJsonStore` in `util/json_store.py` is *already a facade over it*
with a file fallback. Adoption is partial: **10 modules use the facade**, while the caches
this plan wants moved first still do raw file I/O — `knowledge/briefing.py:683` is
`json.loads(read_text())` → mutate → `write_text()` on **one file shared by every
connection**, which is the exact unlocked load→mutate→save race the Ledger was built to
eliminate, and the bug class the 2026-08-04 session hit. Routing those onto the existing
`kv` facade is a smaller change than standing up Redis, fixes the race now, and collapses
the later externalization to **one backend swap instead of N**. Redis then becomes a
Ledger backend, not a per-store migration.

*Leverage, don't duplicate* — the ledger's own docstring states this as the house rule;
the first draft of this plan proposed new infrastructure without checking what was already
built.

**Phase 2 — durable execution (4–8 weeks). OPENED 2026-08-05 — its two foundations landed:**

* **The Phase 1 JSON remainder went first** (it was the prerequisite): exploration +
  business-profile state ride a `FileFamilyStore` (per-key transactional, legacy files
  import on first touch, Postgres-capable) with purge moving *with* the data — the
  cascade now runs through the agent's purge hooks rather than filename globs, and new
  tests pin that store-seeded state purges as thoroughly as file-seeded did.
* **Job ownership is a lease** (`AUGHOR_JOB_LEASE_S`, default the existing 120 s
  staleness window; no schema change). Boot recovery fails only lapsed leases and
  records live-lease skips as `job.foreign` — proven with two kernel instances on one
  live Postgres, where the old blanket rule demonstrably killed a healthy peer's job.
* **Slice claims are a kernel primitive** (`Ledger.try_claim/renew_claim/release_claim`,
  atomic expiry-steal in the upsert's WHERE): the spike's HTTP-409 semantics, ready for
  the explorer decomposition to build on. Contention, expiry-steal, owner-checked
  renew/release proven on both backends.

**Phase 2 completed 2026-08-05:**

* **The domain is the slice.** Phase 8's per-domain pass now claims
  `explore:{store_key}:{domain}` (`AUGHOR_DOMAIN_LEASE_S`, default 900 s) before
  working: two workers sharing the database split the domain list instead of
  double-running it, a dead worker's domain frees itself by expiry, and completion
  is recorded in `domain_coverage` state — so claims need no hand release. Claim
  failure is a skip, not an error; a ledger hiccup degrades to single-process
  behaviour. The explorer's existing cross-run resumability (phases that skip when
  their state says done) is what makes the slice boundary this cheap.
* **Dispatch is a seam** (`aughor/kernel/queue.py`): `WorkQueue` Protocol, in-process
  default submitting supervised kernel jobs by KIND through a runner registry —
  payloads are references, at-least-once via the kernel's idempotency keys. An
  external queue is `AUGHOR_WORK_QUEUE=…` plus a backend class; none ships until
  there is a real queue to verify against (the coordinator discipline).
* **The async-LLM requirement, disposed honestly:** every explorer LLM/SQL call runs
  via `run_in_executor` — the event loop is never blocked and a thread parked on a
  socket burns no active CPU, which is what Fluid meters. §3.5's requirement is met
  at the process level; a full `AsyncOpenAI` migration remains a *billing
  optimization* to confirm with §4's cost test on real invoices, not a correctness
  gap.

**Deliberately not in Phase 2:** an end-to-end two-worker exploration run (needs live
LLM budget — it is the §4 cost test's natural companion), and any external queue
backend. The slice/claim/queue primitives all carry live shared-Postgres proofs.

**Phase 3 — packaging and cutover (2–4 weeks).** Dependency trim (do the trivial part in
week 1), functions, Cron.

**≈4–6 months.** Phases 1 and 3 are independent of Phase 2 and can run in parallel.

---

## 5. Two recommendations against the grain

### 5.1 Do not put the LLM path on serverless without measuring cost

Serverless bills wall-clock. Measured LLM latency on the current free tier is **8.8 s per
call**, and one exploration issued **102 queries**. Paying serverless rates to sit waiting
on an inference provider is paying a premium to idle; a small always-on container may cost
an order of magnitude less for the same work.

**Recommendation:** make the worker a *deployment choice, not an architecture choice*. The
durable-workflow refactor is identical either way — only the runtime target differs. Build
it, measure real cost at real volume, then choose. This also preserves the option to leave
Vercel without losing the investment.

### 5.2 Budget for the guard layer to grow

Every defect found during the 2026-08-04/05 sessions was **semantic, not structural**: a
cached finding outliving the table it depended on; a number correctly drawn from the result
but bound to the wrong label (a 26× overstatement that every existing gate passed); a list
route and a detail route disagreeing about what an id means; an HTTP cache surviving a
redeploy. None would have been caught by types, and several were invisible behind healthy
`200`s.

Distributing state enlarges that class. The verification layer becomes *more* load-bearing
after this migration, not less — and "read the prose, check the arithmetic" should be an
explicit release gate, because status codes have repeatedly failed to detect these.

---

## 6. Open questions before committing

1. Is `polars` in `db/connection.py` on the hot query path, or a convenience that DuckDB
   can absorb? (Decides whether 312 MB leaves permanently.)
2. Does Vercel's Python runtime hold DuckDB's **Linux** wheel comfortably? All sizes here
   are macOS; Linux wheels differ.
3. What is the real per-invocation cold-start cost of re-establishing DuckDB + remote data
   access? This decides slice granularity (per-phase vs per-angle vs batched).
4. ~~Which of the ~35 SQLite stores are genuinely hot, and which are append-only ledgers
   that could go to Blob instead of Postgres?~~ **ANSWERED 2026-08-05 — and the premise was
   wrong.** Classifying all 32 platform stores by the SQL verbs they actually issue:
   **26 are mutable** (`UPDATE` and/or `DELETE`), 6 append-only. Of those 6, two are not
   migrations at all — `agent/graph.py` issues no raw SQL because `checkpoints.db`
   (**128 MB, the largest store**) is LangGraph's `SqliteSaver`, making it a library swap to
   `PostgresSaver`; and `security/audit.py` (`audit.db`, 36 MB) is the one genuinely
   append-only ledger, by design. **There is no meaningful Blob tier to peel off** — plan
   for a relational migration of essentially the whole set, plus one checkpointer swap.

---

## Appendix A — how the numbers were taken

```bash
# Boot import closure: what the process actually loads, not what pyproject declares
python - <<'PY'
import sys; before = set(sys.modules)
import aughor.api
import sysconfig, pathlib
sp = pathlib.Path(sysconfig.get_paths()["purelib"])
tops = {n.split(".")[0] for n in set(sys.modules) - before
        if str(sp) in (getattr(sys.modules.get(n), "__file__", "") or "")}
print(sorted(tops))
PY

# Clean serving-set install (measured: 102 MB)
uv venv --python 3.11 && uv pip install \
  fastapi uvicorn pydantic python-dotenv python-multipart \
  duckdb sqlglot openai instructor cryptography pyyaml pytz
du -sh .venv/lib/python3.11/site-packages

# How deeply a dependency is woven in
for lib in sqlglot duckdb polars scipy statsmodels; do
  echo "$lib: $(grep -rl "import $lib" aughor --include='*.py' | wc -l) modules"
done

# State inventory
ls data/*.db data/*.duckdb | wc -l      # ~40 stores
ls data/*.json data/*.jsonl | wc -l     # 52 document stores
```

**Caveat on portability:** all sizes are macOS/arm64. Linux wheels — particularly
`duckdb` (43 MB here) and `cryptography` (13 MB) — should be re-measured on the target
platform before the ~110 MB figure is treated as final. The margin against 250 MB is
large enough that the conclusion is unlikely to change.
