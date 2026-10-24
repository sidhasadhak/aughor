# Learning lessons from completed runs — a study (2026-10-24)

The user, 2026-10-23, on CopilotKit's Automatic Learning (<https://docs.copilotkit.ai/learning>): *"it talks about
automatic learning.. something we can adapt or adopt?"* The answer given then was **adapt the pattern, do not adopt
the service**, with this study first, because the ground rule here is to measure the premise before building on it.
Nothing below was built. No model was called to write it; every count was read over HTTP from the live install on
2026-10-23/24.

## 1 · What CopilotKit does

A **container** groups one kind of work (an expense review, say). Once a day (02:00 UTC by default), a container
that has gathered **15** new completed threads since its last run is read: its conversations, corrections, tool
calls and interactions. The read writes **Insights** (recurring patterns) and, when a pattern is reusable, proposes
a **Skill** — a versioned `SKILL.md` set of instructions. A person reviews the Insights and the threads behind them,
approves or rejects, and publishes; only a published revision reaches the agent, which sees a catalog of skills and
loads one when it decides to (`copilotkit_load_skill`). A revision can be pinned (`CPK_INTELLIGENCE_SKILLS_REVISION`).
The model's weights never change. It is a hosted service fed by AG-UI streams.

**Not adopted, whatever is decided below:** the hosted service (every run would leave the install — a read-only,
self-hosted platform cannot ship its traces to a third party), the AG-UI stream format, and anything that changes
weights (killed in the 2027 study, ROADMAP §6 item 39, kill 1).

## 2 · What Aughor already has — measured

Aughor learns **one answer at a time** in five places; none reads **many runs** for a pattern.

| Store | Learns from | Live count | Gate |
|---|---|---|---|
| Few-shot memory (`tools/prior_analyses.py`) | each clean answer's SQL and each investigation | 19 SQL examples, 125 investigations | automatic; a rejected query is forgotten |
| Learned skills — `QueryTemplate`s (`memory/skills.py`) | one finished investigation's SQL, parameterised | **0 on every connection** (theLook, workspace, Lux, Superstore) | propose → a person confirms, EXPLAIN-gated |
| Trusted queries (`semantic/trusted_queries.py`) | an eval suite or a person | 2 (both on `workspace`, from an eval suite) | proposed → approved |
| Resolutions (the ambiguity ledger) | probes, people, verdicts | 8 (probe 2, user 4, verdict 2), served 46 times | by source |
| Verdicts (`feedback/verdicts.py`) | 👍 / 👎 / a correction on an answer | **7 in all** — 4 accept, 1 correct, 2 reject | a person |

And one place that already holds **prose a person activates**, which is what a CopilotKit skill is: a **pack**
(`packs/models.py`). A pack has a `version`, a `scope` (`{"connections": [...]}`, so one connection is expressible), a
`status` of draft, active or deprecated, a `source` for provenance, and `expertise` prose that `packs/inject.py`
writes into the agent's persona. `skills/ingest.py` already turns a third-party `SKILL.md` into a **draft** pack
that is inert until a person activates it, and activation runs the prose linter (`packs/promote.py`). 27 packs live:
14 active, 13 draft.

## 3 · The corpus — what there is to learn from

`GET /learning/run-labels?days=365&limit=500&rows=true`: every run with a recorded trace since the trace tap opened
(TJ-1, 2026-09-25).

- **181 runs**, 2026-09-25 to 2026-10-23: 67 in September, 114 in October.
- **By connection:** theLook 156 (116 deep, 40 chat) · LuxExperience 12 · Superstore 7 · workspace (Olist) 6.
- **Who asked:** 30 are theLook's scheduled daily question; **151 were asked by a person** — but they are **54
  distinct questions**, 24 of them asked more than once, and five questions alone account for **74 runs** (asked
  21, 16, 13, 12 and 12 times — by their wording, theLook demos and evals). The corpus is the builder testing the
  product, not a business using it.
- **The run label** (`learning.reward.run_label`, deterministic): 86 positive · 29 negative · 66 unlabeled.
- **Recurring reasons:** 41 "a statement returned no rows" · 14 "no statement ran" · **12 a fan-out guard fired** ·
  5 a guard's action was not recorded (E1-date-boundary) · 3 time-order · 2 declared-filter · **15 statements
  failed**.
- **The 15 failures** are the clearest patterns in the corpus, 14 of them on theLook's BigQuery:
  - dialect slips — `400 CAST operators are not supported` ×4 (a `::` cast), `Function not found: DATEADD`,
    `Function not found: julianday`, `A valid date part name is required but found EPOCH`, `No matching signature
    for operator =` (INT64 = DATE);
  - name slips — `Unrecognized name: order_items`, `Unrecognized name: sale_price`, `Name id not found inside
    orders`, `Name id not found inside o`, `Name user_id not found inside users`, `Column name cohort_month is
    ambiguous`;
  - one on LuxExperience's Postgres — `column o.order_ts does not exist`.

**CopilotKit's threshold, read here.** Fifteen new runs per container: only theLook has ever passed it (156). Lux has
12 in a month, Superstore 7, Olist 6. And a container is *one kind of work*; the nearest thing here is a question's
shape (`agent/question_shape.py`: describe · check · diagnose · survey), which is decided at the door and **not kept
on the run** — so today the corpus cannot be cut by kind of work at all, only by connection and by chat versus deep.

## 4 · What to adapt

1. **A lesson is a recurring pattern with its evidence**, proposed as one or two sentences of instruction: *"On
   theLook (BigQuery), cast with `CAST(x AS DATE)`; a `::` cast is refused — 4 runs, 2026-09-26 and 2026-09-27."*
   The evidence runs are its source; provenance is required and no model authors it (AGENTS.md).
2. **Code finds the pattern; a model only words it.** The run label already classifies every run by reason, and
   the failure texts above group by rule (the engine's error class, the name it could not find, the guard that
   fired). A pattern is a group of at least *k* runs in a window. A model may write the sentence for a group code
   found, citing the group; it never proposes a pattern of its own. That is cheaper than CopilotKit's model read, and
   it keeps "a model proposes, a person confirms" exact.
3. **Its home is a draft pack scoped to one connection** — no new store (AGENTS.md: one store per concept). Its
   `expertise` holds the lessons; `source: "learned"` with the run ids; `status: draft` until a person activates it
   through the existing linter gate; a new revision is a new `version` and the old one is deprecated, never deleted
   (supersede, do not delete).
4. **Delivered the way packs already are** — the active pack's expertise in the persona — while a connection has a
   handful of lessons. CopilotKit's on-demand catalog earns its place only when the always-loaded prose grows past
   what a prompt should carry; measure that before building it.
5. **Each lesson carries its own falsifier**: the rate of its own pattern (e.g. `::`-cast refusals per 100 BigQuery
   runs on theLook) before and after activation. A lesson whose pattern does not fall over the next N runs is
   deprecated, a person's call, said on the pack.
6. **Triage before a lesson: is this a code defect?** Several patterns above are the platform's to fix, not the
   model's to remember — a dialect slip on the native-SQL path is the seam the gate map named (GM-1; memory: the
   dialect bugs live at `native_sql`). A lesson must not paper over a bug the door could translate; the proposal
   says which it is, and a code-shaped pattern becomes a defect, not a lesson. The corpus shows the shape: all four
   `::`-cast refusals fall on 2026-09-26 and 2026-09-27, in the days the gate map was naming the dialect seam, and
   none in the 142 theLook runs since. What ended them was not measured; a lesson learned from those four would
   still be in the prompt, teaching a workaround for a problem that no longer occurs.

**Cost.** Finding patterns is SQL and JSON over traces already kept — no model. Wording costs one model call per
proposed lesson, priced through `AUGHOR_MODEL_PRICES` and said before it runs; nothing runs on its own until a
person sets a schedule.

## 5 · Why not yet, measured

- **The corpus is thin and self-made.** 181 runs, 54 distinct person questions, 7 verdicts. Lessons learned from it
  would encode the builder's test habits — five repeated questions are 74 of the 181 runs.
- **The human signal barely exists.** CopilotKit's corrections are the signal it values most; here 1 correction has
  ever been recorded. PENDING item 35's ✅/❌ on Slack (TJ-4) is built; as that item last recorded, it is not live
  until the Slack app has the `reactions:read` scope and a `reaction_added` subscription, which are the owner's.
- **The clearest patterns are code defects.** Of the 15 failures, the dialect half is the door's to translate —
  and the four `::`-cast refusals stopped on 2026-09-27 without one.

## 6 · The calls that are the user's

1. **Adapt it now, or after real traffic?** *Recommended: build the code half now (patterns found and listed, no
   model, no store) and propose lessons only once a connection has real use — a person-asked corpus that is not a
   rehearsal.* The listing alone is useful: it is the dialect and name slips above, by connection, with their runs.
2. **Home:** a draft pack scoped to the connection *(recommended)* · the agent's instructions · a note on trusted
   queries.
3. **Who finds patterns:** code only, a model words them *(recommended)* · a model reads runs, as CopilotKit does.
4. **When it runs:** on a person's click first *(recommended)* · a weekly schedule.
5. **Delivery:** the active pack's prose, always loaded *(recommended at this size)* · a catalog the agent loads on
   demand.
6. **Keep a run's question shape on the run** (so a "kind of work" exists to group by) — a small, separate change
   either way.

## Sources

- CopilotKit, *Automatic Learning: Overview*, <https://docs.copilotkit.ai/learning>, read 2026-10-23.
- Live install, read over HTTP 2026-10-23/24: `GET /learning/summary`, `GET /learning/run-labels?days=365&limit=500&rows=true`,
  `GET /learning/trusted`, `GET /learning/resolutions`, `GET /ontology/skills?connection_id=…`, `GET /packs`.
- Code: `aughor/learning/reward.py`, `aughor/memory/skills.py`, `aughor/skills/ingest.py`, `aughor/packs/models.py`,
  `aughor/packs/inject.py`, `aughor/packs/promote.py`, `aughor/semantic/trusted_queries.py`,
  `aughor/agent/question_shape.py`.
