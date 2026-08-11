# Session handoff — 2026-08-11

`origin/main` = **`766a972`**. Thirteen PRs merged (#298–#311). Nothing of this
session's work is unpushed.

The session started with "push this branch" and became a latency investigation, because
the user reported that the Briefing's **Start** and **Trigger Intel** buttons "feel
broken" and asked for proof. They were right, and chasing why led to the single cause
under most of the platform's local slowness.

---

## 1 · The one number that matters

| | before | after |
|---|---|---|
| click **Start** → any feedback at all | **never** (17s of an unchanged screen) | **871 ms** |
| → first `exploration.phase` | ~25 s | **2.4 s** warm, ~21 s cold-per-process |
| workspace connection open | 4.7 s (58 tables) → 9.7 s with a 96 MB CSV | **0.00 s** after the first |
| `make_reader()` per parallel reader | ~10 s | **0.00 s** |
| prod `/catalog/tree` | **10.9 s** warm | **3.9 s** — verified in production 2026-08-11 |

Cold-per-process is now the honest cost: the workspace materializes once per process,
then every open is free.

---

## 2 · What shipped

**The briefing controls** — #302 (the click is acknowledged in 871 ms instead of never),
#307 (the wait names its step, using `birth.step` events the backend was *already*
emitting with no consumer), #306 (`Start` only appears when starting is the honest verb).

**The latency chain** — #304 (the two prep steps never depended on each other), #305
(single-flight `build_intelligence`, the prerequisite for the next one), #308
(exploration is handed off first; the prep was never a precondition), #310 (the
workspace materializes once per file set), #311 (platform stores stop opening a new
Postgres connection per operation).

**Correctness** — #298 (loader survives real DSNs), #299 (five empty-conn-id requests
per load, two of which Vercel's edge answers with a CORS-less 308), #300 (the connector
picker reports what can actually run), #301 (the same DSN parsing in all four callers,
not just the loader), #309 (workspaces stop holding deleted connections), #310 (uploads
read what the drop zone advertises).

---

## 3 · Where the 17 seconds actually was

Worth reading before touching any of it, because none of it was where it looked.

1. **The POST is 42 ms.** `explorerBusy` tracked the *request*, so the disabled state
   lasted 42 ms — below the threshold of being seen.
2. **The one poll fired after the POST raced the backend and lost** — the phase had not
   moved yet, so the single refresh spent on the click re-read the state the click was
   meant to change. Nothing polled again until a kernel event or the **60-second**
   fallback.
3. **The job starts in 34 ms** — it was never a queue or a concurrency slot. That was
   the first hypothesis and it was wrong.
4. **The time was the birth rite's prep**, and the first `exploration.phase` — the only
   event the Briefing reacted to — could not exist until it finished.
5. **Under all of it**: `LocalUploadConnection` rebuilt the entire workspace on every
   connection open. 99.8 % of a 4.7 s open was `_reload_existing_files`; `db.test()`
   was 0.00 s.

---

## 4 · Three pooling mechanisms now — do not confuse them

| Where | Mechanism | Why that one |
|---|---|---|
| `db/pool.py` | data connections, **exclusive checkout**, returns on `close()` | pre-existing; callers do close |
| `db/store_pool.py` (#311) | platform stores, **thread-local ownership** | checkout needs callers to close, and **5 stores close ZERO of 142 opens** — `workspace`, `canvas`, `dashboard`, `rbac`, `savedquery` |
| `local_upload` base cache (#310) | the materialized workspace, **shared via DuckDB cursors** | cursors share data but keep their own session, so `search_path` stays per-connection |

That last point is load-bearing: `search_path` is scoped per connection precisely to
stop one schema's bare `FROM orders` resolving to a sibling's same-named table. Sharing
a session would have reopened that hole. `evict_base(conn_id)` clears one connection's
materialized database without a restart.

---

## 5 · Open — highest value first

1. **Production has data but no registered connection.** `store_connections.connections`
   is **0 rows**; `superstore.orders` (9,994), `returns` (800) and `regional_managers`
   (4) are loaded in Supabase and unreachable. Add a Postgres connection through the
   Catalog UI (the registry is Postgres-backed, so it persists). **Requires the operator
   — credentials must not be handled by the agent.**
2. ~~**Verify #311 in production.**~~ **Done 2026-08-11 — it works, but the predicted
   number was wrong.** Measured warm, same process (`/dev/stats` `uptime_seconds`
   increments across invocations, so per-process caches really are alive):

   | endpoint | store ops | before | after |
   |---|---|---|---|
   | `/health` (no store) | 0 | — | **0.22 s** ← floor |
   | `/connections` | ~1 | 1.7 s | **0.80 s** |
   | `/workspaces` | ~3–4 | 6.5 s | **3.0 s** |
   | `/catalog/tree` | ~7 | 10.9 s | **3.9 s** |

   The diagnosis was right and the change should stay: every endpoint improved, and
   `/connections` at 1.7 → 0.80 s is the clean proof the pool is being hit at all.

   **But 1–2 s was optimistic, and the reason matters.** The speedup is roughly
   *uniform* (2.2–2.8×) rather than largest where the op count is highest. If pooling
   had removed the whole per-op cost, `/catalog/tree` (7 ops) would have collapsed
   toward the floor while `/connections` (1 op) barely moved. Instead a residual
   survives that still scales with op count — ~0.55 s per store operation, stable
   across eight consecutive requests, so it is not cold-start noise.

   **Pooling removed the handshake; it did not remove the per-operation cost.** The
   next lever is therefore the *number* of store operations per request, not the cost
   of holding a connection — e.g. `/catalog/tree` writes `set_catalog_schemas` once
   per connection on every single tree read.

   **Attributed, same day — it was schema DDL replayed per operation.** Every store
   opens with its `CREATE TABLE IF NOT EXISTS` block (plus indexes, plus
   `run_migrations`, plus a commit) before its first real statement. Counted by
   running each store's `_ensure_schema` against an in-memory SQLite connection:

   | store | statements per operation |
   |---|---|
   | `workspace` | **11** |
   | `metastore` | **9** |
   | `dashboard` | 6 |
   | `savedquery` | 3 |
   | `org`, `canvas` | 2 |

   On SQLite that idiom is free — the statements never leave the process. On Postgres
   each one is a round trip. The arithmetic closes: dividing each endpoint's residual
   by its statement count gives **64 / 66 / 94 ms** for `/connections`,
   `/workspaces`, `/catalog/tree` — three independent endpoints landing on one
   round-trip cost.

   Pooling removed the handshake and left this, because the DDL ran on every
   *operation* rather than every *connection*. Fixed by `store_pool.ensure_once`,
   which memoizes the DDL on the pooled connection — 69 call sites across 22 stores.
   SQLite is unchanged by construction: it is never pooled, and a raw
   `sqlite3.Connection` has no `__dict__` to memoize on, so that path still runs the
   DDL every time.

   ⚠️ **The predicted win is ~3.9 s → 0.7–0.9 s for `/catalog/tree`, and it is a
   PREDICTION.** The last one in this slot was wrong. `/dev/stats` now carries
   `store.schema_ddl.ran` / `.skipped` precisely so the check is a direct reading
   rather than arithmetic: in steady state `ran` should plateau at roughly
   stores × threads while `skipped` climbs with traffic.
3. **`refresh_popularity` has no staleness check** — re-parses up to 5,000 statements
   every run (9.3 s measured). `save_popularity` already persists `mined_at` and
   `n_queries`, and nothing reads them.
4. **Three open chips**: `/suggestions` takes **73 s**; `?tab=briefing` and `?tab=catalog`
   render blank despite being declared `NavTab` values; exploration status reports a
   healthy `phase` with `error: null` while `per_schema` shows most schemas `failed`.
5. **`test_pause_emits_paused` is flaky** — asserts an exact event list, and
   `automation.run` bleeds in. It failed once on #305 and passed on rerun.
6. **Housekeeping**: 40 local branches ahead of `main`; nine open PRs, all bots (#131
   eslint 9→10 and #132 TypeScript 5.9→7.0 are majors).

---

## 6 · Known gaps left deliberately

- **`pyexasol` is declared in no dependency group**, so the Exasol tile cannot work in
  any install. #300 makes it say so rather than failing at form-submit.
- **The three REST connectors import `requests`**, which `[crm]` does not declare; it
  resolves transitively today.
- **`build_intelligence` is ~0.0 s cached and ~16 s cold**, so the remaining cost is
  concentrated in first builds rather than spread evenly.

---

## 7 · What this session got wrong

Recorded because the pattern repeated and cost real time.

**Four of five false alarms were bad comparisons, not bad code.**

- Two API instances running, both mine — status read from one process while the job ran
  in the other.
- "Zero SSE bytes" twice: the capture was broken, not the server. `curl -o file` in
  background plus an explicit kill works; `timeout … > file &` then `wait` does not.
- "#304 is a regression": a benchmark with a 9.3 s harness lead-in compared against an
  ad-hoc run with 34 ms, at different cache states.
- `'1' == 1` — this connector returns rows as **strings**, which made a present table
  look missing.
- A reuse test counted the open right after an ingest as a failure to reuse, when that
  open **must** rebuild.

**Two bugs were introduced and then fixed inside the same PR.**

- An **uncached transcode** re-encoded a 96 MB CSV on every connection open into a fresh
  temp directory nothing deleted: **34 directories, 2.7 GB, and the API process died.**
  Caught by the process dying, not by a test.
- **latin-1 shadowing utf-16**: latin-1 maps all 256 byte values, so it never raises — an
  ordered try-list "succeeded" on a UTF-16 file and produced `ÿþi␀d␀`. Use the BOM.

Both came from not asking what the new code does on the paths it was not written for.

**One PR was destroyed by tooling.** `gh pr merge --squash --delete-branch` on a PR that
is the *base* of another **closes** the stacked PR, and it can then be neither reopened
nor retargeted. #303 was lost this way and recreated as #307. Retarget dependents to
`main` **before** merging their base.

---

## 8 · Verification habits that paid

- **Measure the premise before building the scoped thing.** Every hypothesis that was
  checked moved the work — the queue theory, the "2 of 15 connectors", the "registry
  lives in `public`", the product-image column.
- **The browser found what tests could not**, repeatedly. Green suites coexisted with a
  17-second dead button.
- **Assert the claim, not something adjacent.** "Both steps ran" would have passed on the
  sequential code; the overlap test asserts *time*, and was verified by reverting the
  change and confirming it fails.
- **A guard that always skips looks identical to one that works.** The Qdrant fixture was
  checked in both directions; the xlsx test used `importorskip("openpyxl")`, which is not
  in this environment, so the only test covering the broken format would have skipped
  forever.
