# Databricks wire study (2 HAR captures) + sqlx/autodoc → Aughor uplift program

**Date:** 2026-07-15 · **Inputs:** two HAR network captures of Databricks (CSV upload → table
birth; Genie **Deep Research** investigation), `jmoiron/sqlx`, `context-labs/autodoc`.
**Method:** HARs reconstructed from xlsx (single-column line dumps → HAR 1.2 JSON), every
API payload extracted, statement-signature JWTs decoded, poll-growth curves timed; repos read
in full; every claim about Aughor verified against current `main` (`24e4a34`) with file:line.
**Bonus:** the uploaded dataset is our own airline `tickets.csv` — apples-to-apples with the
Aughor demo schema.

---

## 1 · How Databricks grips data at the moment of upload (capture 1 decoded)

Wire flow (2026-07-14, workspace `dbc-43dded7e-2ac7`, 318 entries):

```
t+7s   POST /ajax-api/2.0/ingestion/staging/personal/files     multipart → idbfs:/ staging URI
t+13s  POST /ajax-api/2.0/sql/statements                        PREVIEW+INFERENCE, ONE query:
       select * from read_files('<staging>', format=>'CSV', header=>'true',
              inferColumnTypes=>'true', mergeSchema=>'true', …) limit 50
t+13→44s   (human reviews/edits the inferred preview in the UI)
t+44s  POST /ajax-api/2.0/sql/statements                        CTAS — the key payload:
       create table workspace.airlines.tickets_2
         COMMENT 'Created by the file upload UI'
       as select `ticket_id` as `ticket_id`, …
       from read_files(<same>, schemaHints => '`ticket_id` string, …,
              `fare_chf` double, `days_to_departure` bigint, `refundable` boolean, …')
t+60s  TABLE-BIRTH BURST (~20 parallel calls the second the table exists):
       GetUcTableJoinTagsQuery (15.7KB for a seconds-old table ⇒ schema-wide joinability),
       getTableInsightsQuery, getPopularTablesQuery/getPopularColumnsQuery(all 15 cols),
       batchGetHealthIndicator, GetAnomalyDetectionConfig(schema), tag-policies,
       effective-permissions, entity-tags
t+61s  POST /ajax-api/2.0/conversation/flow/autodoc              AI DOC AT BIRTH, fire-and-forget:
       {entity_info:{catalog,schema,entity_name}, entity_type:"table",
        common_params:{request_purpose:"STANDARD_USAGE"}}   ← FQN only; context assembled server-side
```

**The five design moves:**

1. **Inference belongs to the engine, and it's one round trip.** `read_files(inferColumnTypes)`
   returns sample rows *and* typed schema together. No client-side sniffing, no second pass.
2. **The inferred schema is PINNED at creation.** The CTAS carries every column as an explicit
   `schemaHints` entry — inference output (possibly human-edited during the 30s preview dwell)
   becomes a deterministic, re-runnable contract. Inference proposes; the contract disposes.
3. **A defined "birth rite" fires the instant a table exists** — joinability, popularity,
   insights, health, anomaly config, AI description. Understanding is an *event*, not a
   side-effect of the first question.
4. **The AI-doc request is minimal and purpose-tagged** — client sends the 3-part name only;
   the server owns context assembly. (`request_purpose` tags every AI call.)
5. **Provenance is baked into DDL** (`COMMENT 'Created by the file upload UI'`).

## 2 · How Genie Deep Research investigates (capture 2 decoded)

Wire flow (2026-07-15, "data-rooms" = Genie spaces API, 396 entries). Question:
*"Showcase the different visualization options with interesting aspects of the dataset."*
`GET /instructions` returned **empty** — the whole run used schema + value index + planner,
zero curated instructions.

```
t−4s   POST /data-rooms/{space}/value-index/preload-cache {}    ← fired at composer-OPEN,
                                                                   before the question is typed
t=0    POST /conversations {"title":<question>, "model":"SMART_AI",
                            "conversation_type":"DEEP_RESEARCH"}
t+0.3s POST /conversations/{id}/messages {"content":<question>,
        "client_context":{"genie_app_context":{"force_deep_research_planning":true}}}
```

Then **pure polling** (conversation GET ~1.2s, message GET ~2.7s); the message JSON is an
**append-only structure whose size is the state machine**:

| t (s) | conv JSON | what happened |
|---|---|---|
| 0–11 | 1.3KB plateau | **planning** — ~11s of pure LLM planning before any SQL |
| 11 | →4.8KB | plan attached; **WAVE 1: 4 statements issued in parallel** (uuidv7 prefixes `b120-*` = same-second batch) |
| 31 | — | first small results land (1.0–2.6KB each) |
| 46 | →8.3KB | results re-fetched **big** (86KB×2, 9.9KB, 9.4KB) for analysis; **WAVE 2: 4 parallel statements** |
| 59 | →11.2KB | wave-2 results; **WAVE 3: 3 parallel statements** |
| 70–97 | 11.8KB plateau | synthesis reasoning stretch |
| 97–137 | 19.6→24.9→27.7→41.1KB | report sections appended stepwise |
| 138 | done | THUMBS feedback poll = completion |

11 distinct statements (4+4+3), 138s total. Query results travel **out-of-band** via
per-statement **signed URLs** (JWT: `{aud:[org], exp:+30–90s, STATEMENT_ID}`), so the
conversation JSON stays small and the heavy tabular data is fetched/refetched independently.

**The eight design moves:**

1. **Plan-first, then STAGED PARALLEL WAVES** — 4∥ → analyze → 4∥ → analyze → 3∥ → long
   synthesis. Decomposition is iterative *between* waves, not one-shot.
2. **The persisted message is the source of truth; transport is dumb.** Refresh/share/resume
   are free because the client only ever re-renders a stored append-only structure. (Aughor
   streams SSE-first and persists after — we've already been bitten: the overview
   ephemeral-turn gotcha.)
3. **Results are decoupled from narrative** via short-TTL signed URLs — the message holds
   query *blocks*, not row payloads.
4. **The value index is pre-warmed at composer-open** — entity binding is ready before the
   question exists.
5. **Mode is an explicit product surface** (`SMART_AI` × `DEEP_RESEARCH`), not a hidden router
   guess; the client can force planning (`force_deep_research_planning`).
6. **Auto-titling**: title = the question.
7. **Feedback (THUMBS) is part of the completion protocol**, polled with the result.
8. **All of it worked with zero curated instructions** — schema + value index + a strong
   planner. (Validates our lean-deterministic substrate thesis; Genie's edge is orchestration
   shape, not secret context.)

Also notable across captures: `authz-eval` ×36 (per-affordance permission eval),
`type-manifest` (300KB type system shipped once), campaign engine keyed on route.

## 3 · sqlx — mine the compile-layer mechanisms

Thin, 15-year-proven deterministic layer over `database/sql`. Every feature is a **compile
step with an error path** — transform text/names deterministically, cache, fail closed before
the DB is touched. Exactly our "deterministic guards > LLM machinery" posture. The eight
mechanisms (full analysis in the agent study; highest-leverage four):

1. **Canonical placeholder IR + per-driver rebind table** (`bind.go: BindType/Rebind`,
   `defaultBinds` map): all internal transforms work on ONE canonical form; dialect is a data
   table applied once at the edge. New engines are data, not code.
2. **Named-parameter compilation as a contract** (`named.go: compileNamedQuery → (query,
   names[])`): the extracted param list is machine-checked against supplied values *before*
   execution; missing name = hard error.
3. **Strict result-shape validation by default; laxity as a named, inherited escape hatch**
   (`StructScan` "missing destination name X" / `Unsafe()`).
4. **`In()` — the one audited place SQL text grows with data** (empty-slice error +
   bidirectional arity checks).

Plus: one cached override-wins name-resolution engine shared by bind-in and scan-out
(`reflectx.Mapper` ≈ the skeleton of an ontology resolver), superset-not-replacement wrapping
with policy on the handle, narrow capability interfaces (`Queryer`/`Execer`/`binder`), and
"document the unverifiable, demote the untyped path" (`MapScan` warnings).

## 4 · autodoc — understanding is a build artifact

Pipeline: post-order DFS → per-file LLM summary → **folder summary composed from child
summaries only** → JSON mirror tree (each node: `{summary, questions, url, checksum}`) →
markdown → local vector store; query = condense-question + closed-world-citation QA chain;
`estimate` = the *same* pipeline with LLM stubbed, and the index command always runs it first
and asks for confirmation. Key transferables:

1. **Bottom-up rollup**: parents read child *summaries*, never raw content → context bounded
   at every level (the ReFoRCE "DB-info compression is lever #1" finding, made persistent).
2. **Checksummed incremental re-index** — with two anti-lessons: their folder checksum hashes
   child *names* not contents (stale parents), and a Windows-path bug means the skip never
   fires on POSIX. Make ours Merkle over child checksums, and **test cache-hit counts**
   (verify-features-actually-ran).
3. **Estimate-then-confirm cost gate** = dry-run of the identical code path.
4. **Per-node cheapest-fit model routing** by measured token count (make "no model fits" loud).
5. **Summarize-then-embed with provenance inside the chunk** (deep-link + FQN in the embedded
   text → citing is copying, not generating).
6. **Question-augmented indexing**: per node, "3 questions a {persona} would ask" — retrieval
   booster + suggestion-seed pool.
7. **Condense-then-retrieve** for multi-turn; closed-world citation rule ("only link what the
   context lists"; "say 'Hmm, I'm not sure'").
8. **Two-layer config**: repo-level (prompts, ignore globs `node_modules`≈`tmp_%`,`_airbyte_%`)
   vs user-level (models/budget).

## 5 · Where Aughor stands today (verified on main `24e4a34`)

**Upload path** (`aughor/routers/connections.py`): `POST /connections/{id}/files[/bulk]` →
`_stage_upload` → `db.ingest_file` (DuckDB auto-sniff; `connectors/file/local_upload.py:410`)
→ `_invalidate_schema_cache`. **That's all.** Facts:

- `kickoff_exploration` fires **only** in `create_connection` (connections.py:132) — never on
  upload. New files into an existing connection get zero intelligence until first question or
  the off-by-default `explorer.continuous` tick.
- `/files/analyze` (connections.py:720 → `analyze_file`, local_upload.py:335) does richer
  inference + mismatch detection, but its output is **ephemeral** (temp dir deleted) — the
  inferred contract is never pinned anywhere.
- Profiles / ontology / BusinessProfile / autoseed / KB / join inference are all
  explorer-async-at-create or first-question lazy (fast vs heavy annotator split,
  db/connection.py:832/843).

**Deep path** (`_stream_ask` → `decide_ask_route` → `_stream_investigation`,
routers/investigations.py:3380/2297): deterministic-first routing, 10-table context cap,
ADA spine `intake→[clarify]→baseline→decompose→dimensional→behavioral→synthesize` with
per-phase plan(coder)/execute(∥)/interpret(fast). Weak links found (verified):

1. `SemanticContext` resolved once (investigations.py:2542) but **read only on the direct
   branch** (agent/nodes.py:75) — dormant for ADA phases.
2. `build_data_understanding` (grain + trusted retrieval) re-runs **inside every phase**
   (agent/investigate.py:3312) — ~4× duplicate retrieval per run, nothing cached on state.
3. `_trim` = hard char cut mid-table (investigate.py:258; 20k schema / 6k scan limits) on top
   of 4-table keyword linking — needed tables can silently vanish before intake.
4. **Deep path streams no tokens** — CK-0.2 `headline_delta` exists only on quick
   `_stream_chat` (investigations.py:1536); deep runs are silent between `phase_complete`
   events; `ada.progress_events` off by default.
5. Under `ada.parallel_phases`, wave phases plan against **shipped fallback prior-summaries**
   ("Baseline established."/"") instead of live ones (agent/phase_waves.py) — parallel mode
   decomposes on weaker context than serial.
6. The **explore-wave subgraph** (decompose → plan_gate → `plan_and_execute_wave`,
   agent/explore.py:1154) — our closest analogue to Genie's staged parallel waves — is
   **unreachable from `/ask`**: `requested_mode` is hardcoded `"investigate"`
   (investigations.py:2563). BUILT, not LEVERAGED.

---

## 6 · Recommendations (prioritized, seam-anchored)

Ordering principle: wiring fixes first (signals already computed, just not connected), then
real first-class features. Every item deterministic-first; LLM only where it adds judgment.

### P0 — wiring fixes (each ~a day, high leverage)

**R1 · Re-arm intelligence on upload — the "table birth rite."**
*Evidence:* Databricks fires ~20 intelligence calls + AI doc at t+60s; Aughor uploads are
inert (gap §5). *Fix:* call `kickoff_exploration(conn_id, auto=True)` (routers/_shared.py:214)
from both upload handlers (connections.py:762/816 post-ingest), scoped to the touched schema;
the explorer already computes profiles→joins→lifecycle→ontology→BusinessProfile. Debounce for
bulk (one kick per bulk call, not per file). Flag: reuse scout governance; no new flag needed.

**R2 · Pin the inferred contract at ingest (schemaHints-equivalent).**
*Evidence:* Databricks converts inference into an explicit per-column contract inside the
CTAS; our `/files/analyze` inference is discarded and `ingest_file` re-sniffs blind. *Fix:*
persist the analyze result (types + mismatch notes + sample stats) into the import sidecar
local_upload.py already writes (:438), pass it to `ingest_file` as explicit column types
(`read_csv(..., columns={...})` = DuckDB's schemaHints), and record provenance
(`created_by: upload_ui`, source filename, inference version) in the sidecar → surfaced in
ontology/Hub. Inference proposes → contract disposes → re-ingest is deterministic.

**R3 · Wake the dormant semantic plane + stop 4× re-grounding.**
*Evidence:* weak links 1–2 (§5); Genie's plan phase consumes one prepared context. *Fix:*
build `data_understanding` once at `_stream_investigation` context-assembly, stash on state,
have `run_analysis_phase` read it (investigate.py:3312); thread `semantic_context`
(investigations.py:2542) into intake + phase-plan prompts. Pure wiring; no new machinery.

**R4 · Fix wave-parallel planning on stale fallbacks; default-on `ada.progress_events`.**
*Evidence:* weak link 5; Genie analyzes *between* waves — inter-wave context is the point of
staging. *Fix:* in `phase_waves.py`, pass live prior-phase summaries to the wave members that
structurally can have them (baseline is wave-1; decompose/dimensional can consume baseline's
result if we stage 1∥(2,3) instead of (1,2,3)∥ — matching Genie's 4→4→3 staging). Flip
`ada.progress_events` default-on so deep runs narrate.

### P1 — first-class features (≈1 week each)

**R5 · Value index as a persisted artifact (Genie's preload-cache).**
*Evidence:* Genie pre-warms a distinct-value index at composer-open; entity binding then never
waits. Aughor's ground-first resolver DB-probes live per question, and the profiler *already
captures top values* (tools/profile_cache.py). *Build:* materialize a per-connection value
index (categorical columns → distinct values + counts, bounded) from profiles; consult it in
`semantic/answer_resolution.py` before live probes (probe only on miss); pre-warm on canvas
open (cheap endpoint) and refresh with profiles. Deterministic, offline-first entity binding —
faster resolve-first, fewer probes.

**R6 · Deep-path liveliness: stream the synthesis + narrate the plan.**
*Evidence:* Genie's UX is a visible plan → queries appearing in waves → sections streaming;
our deep run is silent for minutes then drops a report (weak link 4). *Build:* extend the
CK-0.2 seam (`complete_streaming(text_field=...)`, investigations.py:1536 pattern) to
`ada_synthesize`'s narrator call (investigate.py:5989) → stream `report_delta` section tokens;
emit plan/wave events already available as `phase_progress`. Frontend: reuse the CK-0.2
delta-rendering path. (Transport stays SSE/AG-UI — polling is the one Genie choice NOT to copy;
but adopt its *semantics*: the persisted turn is source of truth, deltas are projections —
consistent with the overview-persistence lesson and the AG-UI seam.)

**R7 · The SQL compile layer (sqlx mechanisms, in the existing gate).**
*Build in `aughor/sql/` (the one SQL-safety pipeline):*
(a) **Named-param contract**: coder emits `:entity`/`:start`/`:end` for resolver-grounded
values; a `compileNamedQuery`-style pass extracts names, hard-fails on ungrounded-referenced
or grounded-unused (turns "hope the literal survived generation" into a checked contract —
completes ground-first).
(b) **Guarded `In()`** for entity-list expansion (empty-list decision + arity both ways) —
never let the LLM enumerate literals.
(c) **Result-shape validation**: plan declares expected columns/cardinality (scalar vs series
vs table); strict check on row 1; any laxity is a named flag surfaced in the Trust Receipt.
(d) **Unique output aliasing** post-pass (`AS` everywhere) — precondition for (c), generalizes
the qualified-names gotcha.
Dialect facts stay data in connector capabilities (#120 home), applied once at the edge.

**R8 · Ontology docs as a build artifact (autodoc architecture on existing stores).**
*Build:* column-profile → table-doc → schema-doc → connection-doc rollup, each node persisted
(deterministic core from profiles/grain/joins; LLM enrichment optional per node), with:
Merkle checksums (hash DDL + stats epoch, parents over child checksums) for incremental
rebuild; **estimate-then-confirm** dry-run before any LLM spend (same code path, stubbed
calls); per-node model routing by width; embed the DOCS (not DDL) with FQN + Hub deep-link
inside each chunk; per-table "3 analyst questions" → suggestion chips + overview seeds; table
ignore globs (`tmp_%`, `_airbyte_%`, `dbt_%`). Seams: extends `semantic/autoseed.py`,
`ontology/store.py`, `semantic/vector_store.py`, `knowledge/`; the editable-ontology direction
gets its file-per-node shape. This is also our `conversation/flow/autodoc` equivalent for R1's
birth rite (server-side context assembly, FQN-only trigger, purpose-tagged).

### P2 — staged / architectural

**R9 · Unlock the explore-wave subgraph from `/ask` for wide questions.**
*Evidence:* Genie's staged waves ARE our explore subgraph's design (decompose → parallel
plan-execute waves → synthesis), but it's unreachable from `/ask` (weak link 6). *Fix:* let
`decide_ask_route` (or intake) route WIDE questions ("show interesting aspects", multi-facet
asks that aren't overview-eligible) to `requested_mode="explore"` instead of hardcoding
`investigate` (investigations.py:2563). Gate behind a flag; measure with the missimi-style
eval before default-on. ADA stays the causal/temporal spine; explore becomes the
breadth spine. BUILT→LEVERAGED.

**R10 · Small adoptions:** purpose-tag every LLM call (`request_purpose` ≈ MLflow tags — we
have the seam); auto-title investigations from the question; make THUMBS feedback part of the
turn-completion protocol (feeds `overview/drills.py`-style priors, which R5/R8 can consume);
per-affordance authz-eval belongs to the RBAC enforcement-breadth follow-up.

### What NOT to adopt

- **Polling transport** — SSE/AG-UI is strictly better; adopt persist-first semantics only.
- **Signed short-TTL result URLs** — multi-tenant cloud concern; local-first Aughor doesn't
  need the infra (Redash per-query-key pattern already noted for later SaaS).
- **Campaign/banner machinery, 300KB type-manifest shipping** — product surface we don't have.
- **Copying Genie's 11s-silent planning** — we stream; keep that edge.

## 7 · Sequencing

Wave A (this week): R1 + R2 + R3 + R4 — four wiring fixes, each independently shippable,
each testable hermetically (R1: upload → explorer armed; R2: sidecar contract + deterministic
re-ingest; R3: single grounding build per run; R4: live summaries in waves).
Wave B: R6 (visible), R5 (fast resolve), R7 (guard depth) — order by user-visible impact.
Wave C: R8 (the big artifact), then R9 behind eval evidence.

**Thesis check:** nothing above adds LLM machinery to the decision path. Genie's run proves
the winning shape is *orchestration + prepared context + engine-native inference* — every
recommendation strengthens deterministic substrate or wires existing signals to where
they're consumed.
