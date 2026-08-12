# Session handoff — 2026-08-12

`origin/main` = **`4d6de49`** (+ #327 merging). Sixteen PRs merged, **#312–#327**.
Nothing of this session's work is unpushed.

The session began with one handoff item — *verify #311's connection pooling in
production* — and became a production outage investigation, because the verification
failed and everything under it was wrong in a different way than expected.

---

## 1 · Production went from unusable to working

Five **independent** configuration problems, each hiding the next. None was a code
bug; all needed the operator.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | every call "Failed to fetch" | CORS allowlist held localhost only | add the **frontend's** origin, with `https://` |
| 2 | every route 500, incl. `/health` | Postgres credentials | **session pooler** + `postgres.<ref>` username |
| 3 | connections refused | pooler too small | `pool_size` 15 → 40 |
| 4 | empty catalog | no registered connection | register it (9,994 rows appeared) |
| 5 | empty AI output everywhere | the free model cannot do structured output | → `openai/gpt-oss-20b:free` |

🔑 **Direct Postgres (`db.<ref>.supabase.co`) is IPv6-only and UNREACHABLE from
Vercel.** The session pooler on **port 5432** is the only shape that works — 6543 is
transaction mode and discards the `SET search_path` every store depends on.

---

## 2 · What shipped

**Serverless correctness** — the store pool takes the whole deployment down and is
now off by default where it breaks (#319); four stores wrote to a read-only path,
including the one that made the model choice silently revert (#321); SSE streams
stop burning a full 300 s invocation (#322); a superseded DuckDB database is
released rather than closed (#323).

**Latency** — schema DDL replayed per store operation (#312); the uploads workspace
rebuilt on every open (#320); `/suggestions` bought the same answer every time
(#314); and the schema display path called a model (#327).

**Honesty of signals** — exploration reported failure as health (#316); a diagnostic
whose zero meant two different things (#317); a transient introspection error
deleted the catalog's schemas (#318).

---

## 3 · The 76-second schema path — how it was actually found

Worth reading before touching any latency work here.

**Three PRs moved the number by nothing.** #324 (profiling on the display path) and
#325 (the semantic index rebuilt on the display path) were *real bugs on the right
path* that changed 96 s → 76 s, i.e. noise. Both were chosen by measuring **locally**
and reasoning about which part dominates **in production** — where the embedder is
unreachable, stores are remote, and the store pool is disabled. Those proportions do
not carry: `build_schema_index` was 0.94 s of 2.45 s locally and near-zero of 76 s
remotely.

**#326 stopped guessing** and made the path report itself:
`POST /connections/{id}/schema/refresh?timings=1`. One request:

```
total                            55.9s
  enrich.seed_missing_tables     51.053s   ← 91%
  pg.information_schema           0.103s
  pg.row_counts                   0.096s
  pg.head_samples                 0.094s
```

**All Postgres introspection: 0.29 s.** The database was never the problem — the
display path was making **one LLM call per table**, and re-making it forever because
the seed writes to a read-only path so the "already seeded" fast-path could never
arm.

🔑🔑 **The instrumentation was worth more than the two fixes before it.**

---

## 4 · Open — highest value first

1. **The glossary seed cannot PERSIST on serverless.** `glossary_generated.yaml`'s
   path is *derived* from the authored `glossary.yaml`, which genuinely ships —
   redirecting moves both and loses it. Needs a separate override for the generated
   path, then add it to `WRITABLE_STORES` (`control_plane/writable_paths.py`).
2. **Set the model per role as ENV VARS** — `AUGHOR_CODER_MODEL`,
   `AUGHOR_NARRATOR_MODEL`, `AUGHOR_FAST_NARRATOR_MODEL`. The runtime config file
   cannot persist, so a UI choice reverts on every cold start and different instances
   disagree.
3. **pgvector migration is incomplete** — 12 call sites still `import qdrant_client`
   directly, and `_pg_where` accepts only a SINGLE key/value while
   `suggestions_cache` needs two. The seam cannot express what callers need; this is
   a design change, not a swap. Two modules also build `QdrantClient` against
   `localhost:6333`.
4. **An opt-in local Postgres** for dev + a second CI job. Every serious defect this
   session was invisible locally *by construction* — DDL free on SQLite and a round
   trip on Postgres; a pool that only engages under Postgres; a filesystem writable
   here and read-only there. **Local and prod are different code paths, and that
   asymmetry is the bug generator.**
5. **Chips**: Trigger Intel may run across schemas; the live-Qdrant tests fail rather
   than skip (they make every local full-suite run look red).
6. **From the previous handoff, untouched**: `?tab=briefing` / `?tab=catalog` render
   blank, `refresh_popularity` has no staleness check, 40 stale branches.

---

## 5 · Unresolved

**The production `FUNCTION_INVOCATION_FAILED` outages.** Startup memory (141 MB of
1024) and connection exhaustion (8 of 60) were both eliminated **by measurement**.
The `_shared_base` race fixed in #323 is the first mechanism that fits — a DuckDB
abort kills the interpreter, and a dead process presents as every route failing at
once, intermittently, recovering alone. **Not proven** to be what happened. If it
recurs now, look elsewhere.

---

## 6 · What this session got wrong

Recorded because the same shape recurred and cost hours.

**Three claims had to be retracted.**

- A **14.9× improvement** that measured timings without checking status codes — and
  depended on pooling that was switched off the whole time.
- **#324 called "the fix"** when it removed one of four annotators from the hot path;
  `run_annotators` runs anything registered `"all"` in **every** phase.
- **"my fix did not land"** stated from an 81 s reading on a *cold* instance against
  an 80.5 s *warm* baseline. Mismatched comparison.

**Two crashes, both from lifetimes.** A lazy-materialization attempt segfaulted CI —
seven passing tests missed it because they were all single-threaded, and the hazard
only appears under parallel ingest. The `_shared_base` close then produced a SIGSEGV
*and* a SIGABRT on unrelated PRs.

**Two of my own experiments were confounded** — four threads sharing one DuckDB
cursor crash for a reason unrelated to GC, and I nearly reversed the correct fix
because of it. **Vary one variable.**

**`git reset --hard` with uncommitted work** destroyed changes; recovered only from a
backup that happened to exist.

🔑🔑 **The thing that caught every one of these was widening the measurement, not
sharpening the reasoning.**

---

## 7 · Habits that paid

- **Measure the premise before building the scoped thing** — and measure it *in the
  environment that matters*. Local proportions are not production proportions.
- **A per-process counter cannot measure a multi-process deployment.** `/dev/stats`
  read around an 89 s refresh showed no change; a different instance answered.
  Diagnostics must ride the **response**.
- **Check what the consumer actually calls.** Two PRs optimised `schema/rich`
  believing the Briefing used it; `BriefingPanel` never fetches schema at all.
- **Test a crash in a subprocess** — an in-process reproduction takes the runner with
  it. Six readers made a race fail 5 runs of 5 where one reader caught it 2 in 3.
- **A guard whose assertion cannot fail is not a guard.** `assert … or True` shipped
  briefly; the rewrite iterates the real mapping and was verified to fail on a rename.
