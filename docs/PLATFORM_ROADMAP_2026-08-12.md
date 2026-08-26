# Platform Roadmap — Combined Plan of Record (2026-08-12)

**What this combines:** `SESSION_HANDOFF_2026-08-12.md` (production state + open
substrate work) · the SQL editor program (`SQL_EDITOR_PARADIGM_PLAN_2026-08-12.md`,
`SQL_EDITOR_IMPLEMENTATION_ROADMAP_2026-08-12.md`,
`SQL_EDITOR_DATABRICKS_PARITY_2026-08-12.md` — **all three still uncommitted in
worktree `skill-usage-question-31d2b6`**) · every pending arc (Waves 6/7,
Tracks B/C, temporal synthesis, Ontos/ODCS, open chips and branches) · and a
**new user directive** recorded below as Arc CI.

> ⏱️ **CURRENCY NOTE (added 2026-08-24).** This document is the plan of record as it stood
> on 2026-08-12 and is not maintained as a live status board. `origin/main` is now
> `1354306`, twelve days and several arcs later. Read it for the THESIS and the programs it
> defines; read these for what is actually done:
>
> * `ROADMAP_ARC_VA_2026-08-22.md` — the agent platform. **8 of 10 waves shipped**; VA-9
>   (integrations) and VA-10 (multi-user/admin) are the remainder and both sit outside the
>   standing "data engines only" directive.
> * `KNOWLEDGE_BASE_WAVE_2026-08-24.md` — the document/RAG plane, KB-0…KB-4.
>
> A plan that reports finished work as pending points its reader at the wrong next move,
> which is exactly what the Arc VA status table was doing before 2026-08-24. This note
> exists so the same thing is not true of the plan of record.

**Baseline:** `origin/main` = `4d6de49` (+ #327). Production works end-to-end.
Layers 0–4 of the unified adoption plan are done; Wave 5 (converse) is merged
and `ask.converse` is ON locally, serving real traffic through the guarded
chokepoint.

---

## 0 · The thesis — one platform, three planes

Aughor's shape is now validated externally: Databricks is assembling exactly
this stack (Unity Catalog + Ontos business semantics + Lakebase Postgres +
Electric sync + a first-class SQL editor). Aughor has all five in miniature —
**plus the piece they lack: an agent that answers with the semantics, not just
governs them.** The moat is the ontology→agent loop. Every arc below serves one
of three planes:

1. **The human plane** — a pro-grade surface where a person does data work
   directly: the Query workbench (SQL editor program). Human SQL and agent SQL
   become peers in one provenance system — same `/query/run`, same guards, same
   receipts, same audit.
2. **The agent plane** — a conversation that feels like talking to a frontier
   model, because it is one: general, multi-turn, platform-wide — with the
   guard battery underneath it, not in front of it. This is Arc CI (new, §2).
3. **The substrate** — serverless-correct, honest-signaled, measured-not-
   inferred. The handoff's open items plus the temporal/contract arcs.

---

## 1 · Program A — the SQL editor / Query workbench (LOCKED, build-ready)

All decisions locked 2026-08-12. **Build from
`SQL_EDITOR_IMPLEMENTATION_ROADMAP_2026-08-12.md`** — PR-by-PR with acceptance
criteria. Summary only here:

- **DP-1** engine = CodeMirror 6 + dt-sql-parser (worker) + sql-formatter.
- **DP-2** grid = antd `SqlResultTable` behind a `ResultsGrid` seam → TanStack
  Table + Virtual at SE-3 bulk.
- **DP-3** TanStack Query = yes, scoped to the workbench; supersession notes in
  the two July docs ride the same PR.
- **Builder merge** = ONE Query workbench, `Visual | SQL` modes; SQL canonical,
  spec a projection; `linked`/`sql-ahead` states; decompile never destroys SQL.
- **Descoped**: real-time co-editing (user call), TanStack Router, PGlite.

```
SE-0  backend contract + SECURITY (org-scope on body-conn_id routes,
      typed results opt-in, dialect exposure, caveats forwarded, source label)
SE-1  workbench shell + CM6 editor (PRs A, B)
SE-2  two-tier diagnostics, sidebar, tabs/history/saved, extraction (C, D, E)
SE-3  cancel/timeout via kernel jobs, metadata stmts, bulk grid (F, G)
SE-4  params, viz tab, versions, full specSync (H, I, J)
SE-5a Quick Fix (explicit diff, never auto-applied)
DX-1  TanStack Query beachhead (parallel to SE-2)
DX-2  resumable chat/investigate streams, Durable-Streams-shaped (independent)
DX-3  spikes: TanStack DB QueryCollection, DuckDB-WASM playground
```

**🔴 SE-0's security item is a shared prerequisite for BOTH programs.** The
cross-tenant gap (`/query/run` resolves body `conn_id` with no org predicate,
`db/registry.py:319`; no `/query/*` RBAC entry) sits under the editor *and*
under every conversational tool that runs SQL. Nothing widens its reach before
this closes.

---

## 2 · Program B — Arc CI: general conversational intelligence (NEW)

### 2.1 The directive (user, 2026-08-12)

Quick chat and Analysis Mode feel **restricted and mechanical** — not like the
intelligence a strong or frontier LLM actually has. Chat should function like
any other conversation with Claude/ChatGPT/Gemini: general, natural,
multi-turn. Keep the current guards, logic and mechanisms — *and also* pave the
way for general interaction about anything on the platform: the data warehouse,
the playbooks/packs, the ontology, the catalog, briefings, monitors —
practically anything. **That is the power of an agentic data intelligence
platform.**

**Addendum (same day):** a major source of token burn is the prompt itself —
the agent should have "complete intelligence of the LLM and the approach of an
expert data professional" rather than pages of scripted behavior. See §2.6 for
the measured specimen.

This is the third statement of the same directive, escalating in scope:
2026-08-01 "we restrict intelligence instead of directing it" (→ Track A killed
the weak-model-era caps) · Wave 5 built the conversational body · now:
**generality**. The Track A decision rule still governs: if a smarter model
makes a mechanism unnecessary, it is a RESTRICTION — scale it with the model;
if no model strength fixes the failure, it is VERIFICATION — keep it. The guard
battery is verification. Most of what makes chat feel mechanical is restriction.

### 2.2 Why it feels mechanical — verified in code 2026-08-12, not inferred

1. **The persona is scoped to one warehouse.** `converse_system_prompt`
   (`aughor/agent/converse_tools.py:302`) opens: *"You are answering questions
   about the data warehouse '{connection_id}'."* No identity, no latitude for
   general reasoning, no knowledge of the platform it lives in.
2. **Four tools, all SQL-shaped.** `run_sql`, `list_tables`, `describe_table`,
   `answer_question`. The conversation cannot see the ontology, glossary,
   insights, briefings, monitors, packs, org settings, freshness — or explain
   the platform itself.
3. **No cross-turn memory.** Turn history is empty *on purpose* (asserted in
   the 10-turn graduation receipt — correct for proving budget isolation,
   wrong for a chat product). Every turn re-derives the world.
4. **The carve-out excludes exactly the turns that feel worst.**
   `_converse_eligible` (`routers/investigations.py:4202`) excludes `deep`
   routes, `escalate`, `insight_id`, `seed_sql` — so Analysis Mode and every
   drill-in still get the pre-conversational machinery. Wave 7's C2–C4 (adopt
   the converse body) was already the plan; this directive raises its priority.
5. **The model tier.** Prod runs a free-tier model chosen because it can do
   structured output at all. Role model env vars (`AUGHOR_CODER_MODEL`,
   `AUGHOR_NARRATOR_MODEL`, `AUGHOR_FAST_NARRATOR_MODEL`) don't exist yet, and
   the runtime config cannot persist on serverless — a UI model choice reverts
   on every cold start. Frontier feel requires a frontier-class model actually
   serving the turn.
6. **The UI renders none of the conversation's texture.** `converse_step` is in
   `UNRENDERED_FRAMES` (no tool-trail renderer); the web reducer is a closed
   switch, so new conversational frames are silently dropped.

### 2.3 What does NOT change

The guard battery, receipts, audit, org scoping, clarify governance, the
P2 values-not-exceptions loop contract, connection-binding by closure. Guards
stay in the tool bodies — the model picks tools, it never picks whether guards
run. Guards narrating in the answer's own voice already shipped (`_guard_note`).
**The guards are the product; the conversation is the interface.**

### 2.4 The CI waves

- **CI-0 — measure the premise first** (house rule; every pre-check this year
  moved its own scope). Collect ~20 real sessions across quick chat and
  Analysis Mode and **read the prose** — name the top five mechanical moments
  concretely. The Wave 6 route receipt (`GET /obs/route-mix`, windowed) is
  already live for the coverage half; #282's faux receipt + #286's parity net
  are the quality half. Cheap, do immediately.
- **CI-1 — conversation memory.** A thread model with bounded rolling history
  per session (summarize-then-window; `LoopResult.injected_chars` /
  `reinjection_ratio` is the already-built meter for what history costs — keep
  `_MAX_PREVIEW_ROWS` capped or re-injection explodes, measured 3.5× at 8
  steps). Folds in the pending "scheduled-task threads design pass".
  **Data model (DECIDED 2026-08-12): adopt the AI SDK v7 UIMessage/parts
  model, thread schema, and durable-transport resume inside `web/`** — the
  standard substrate instead of a bespoke message tree. Migrate incrementally
  behind the proven C1 adapter seam (Aughor frames → typed parts; Aughor
  deltas are REPLACE, the SDK is APPEND — diff and emit the suffix). This
  retires the 105-case closed-switch reducer (`investigationStream.ts` —
  shared with the briefing surface, so the migration covers both or keeps the
  seam) in favor of an open part model where an unknown part renders a
  fallback instead of vanishing. vercel/chatbot's schema is the reference —
  patterns, never vendored code (the Ontos rule).
- **CI-2 — the platform tool roster.** Read tools over every surface the user
  named: ontology/glossary entities and docs, catalog tree + schema, stored
  insights and briefings (search + cite), monitors and their status, packs/
  playbooks, org context (already reaches `/ask`), freshness, and a
  platform-help/meta tool ("what can you do", "how do I connect Snowflake").
  **Reuse `aughor/mcp/server.py`'s ~15 docstrings as the routing policy** —
  in-process bodies, connection bound by closure, same as Wave 5.
  **Write scope (DECIDED 2026-08-12: tiered).** Personal, reversible
  artifacts the user just asked for write directly (save a query, pin a
  chart, keep a draft); shared/org semantic state (ontology, glossary,
  routing rules, monitors, automations) is proposal-only via the existing
  routing-proposal / packs-flywheel pattern. Blast radius decides the tier.
- **CI-3 — persona and latitude.** Rewrite the system prompt from
  "you answer questions about warehouse X" to a platform-wide analyst identity:
  general knowledge and reasoning are allowed; data claims come from tools;
  a stated gap beats a plausible number (keep that line — it's right); clarify
  conversationally in prose rather than only via the chip gate. "States, never
  scripts" stays the rule — the tools' docstrings carry routing.
- **CI-4 — Analysis Mode adopts the conversation.** Shrink the
  `_converse_eligible` carve-outs one at a time: `insight_id` and `seed_sql`
  become *context handed to the conversation* rather than bypasses; `escalate`
  and deep routes become a `deep_analysis` **tool the conversation invokes**,
  streaming the investigation's frames through the turn. The conversation is
  the front door; depth is something it reaches for, not a different building.
- **CI-5 — the model (DECIDED 2026-08-12: bring-your-own-key).** Two
  increments. **CI-5a**: role env vars (`AUGHOR_CODER_MODEL`,
  `AUGHOR_NARRATOR_MODEL`, `AUGHOR_FAST_NARRATOR_MODEL`) as the operator
  default and the no-key demo posture — small, ships early, and hardens the
  free-tier retry ladder so a slow model never again ships a fallback report
  silently. **CI-5b**: org-scoped BYOK — each org supplies its own provider
  key and picks models per role. Keys live **encrypted in a `store_*` table**
  (the runtime `llm_config.json` cannot persist on serverless and would revert
  on every cold start), settings UI in the org panel, resolved per-request.
  ⚠️ The config-apply path must not reuse `POST /llm/config`'s
  reload-everything behavior — that cancels running explorations; apply
  per-org without touching other tenants' in-flight work.
- **CI-6 — the surface (RE-DECIDED 2026-08-12: "B's posture, C's plumbing,
  one application").** Chat-first is a *layout*, not a deployment unit — no
  second app, ever. Two steps, same components, same tokens, same auth/RBAC/
  audit/org scoping:
  - **CI-6a — the panel evolves in place**: Track B organs (vendored
    Elements: ChainOfThought, Shimmer, Task — never `npx ai-elements add`),
    a tool-trail renderer for `converse_step`, threads rail. The workspace
    chat stays alive throughout — no big-bang cutover.
  - **CI-6b — the chat-first home route**: a full-page conversation surface
    in the SAME Next.js app (`/chat`, candidate home route), composed from
    the same message components riding CI-1's parts model — thread sidebar,
    voice typography, artifact cards with "Open in workbench", regen/edit/
    share, the BYOK model chip. The workspace inverts from frame to
    destination. Whether `/` lands on chat or workspace is a config decision
    (per-org), deferrable. If the route underwhelms, we lose a route, not an
    application.
  Rationale on record: a standalone vercel/chatbot app was rejected for
  *fragmentation* (split auth, second design system, orphaned workspace,
  template drift), not for technical risk — as a new surface it was actually
  the lower-regression option. The fragmentation risk is what contradicts the
  enterprise-platform posture; the layout it demonstrated is kept.

### 2.5 Measurement and cost honesty

- Success is read from CI-0's transcript reading repeated after each wave, plus
  thumbs and follow-up adoption (`purpose:"followup"` — a SQL query, no new
  store). `converse_share` is coverage, never quality — the denominator lesson
  is in the receipt itself.
- **A general conversation costs more requests, not just tokens**: more tools ⇒
  more steps/turn; multiplied against OpenRouter free-tier limits (20 RPM,
  1,000 req/day, ~60 LLM calls per exploration already). CI-5's model choice
  and the per-turn step budget (`tool_loop_steps`: baseline 4 / capable 8) are
  the cost levers. **User decision required on spend posture before CI-2 ships
  wide.**

### 2.6 The prompt economy — trust the model, verify in code (MEASURED 2026-08-12)

A real deep-analysis report prompt (user-supplied specimen, template =
`aughor/agent/prompts_investigate.py:583`) measures **~3,833 tokens**, split:

| section | ~tokens | share |
|---|---|---|
| role + question | 39 | 1% |
| findings by phase | 458 | 12% |
| full evidence (SQL + rows) | 850 | 22% |
| playbook | 428 | 11% |
| **static instruction tail** (style/grounding/materiality/sign/waterfall/confidence/recs/gaps/links) | **1,731** | **45%** |
| conditional notes (cross-sectional + fan-out) | 324 | 9% |

**The evidence — the only part unique to this call — is 22%.** The static tail
rides every report call; in the specimen the playbook was *entirely
inapplicable* (all five entries are "When GMV up…" temporal patterns inside a
prompt whose own NOTE says "this is NOT a temporal change") ⇒ ~65% of the
tokens carried no information for this question. Two further defects visible
in the same specimen: findings bullets are **char-truncated mid-word** ("poor
ef", "This indicates low") — damaged inputs plus instructions demanding
precision — and the seed question itself is degenerate ("total revenue is
$14", primary table `rearm_single.orders` ~2 rows, dimensions from
`luxexperience.orders` — the standing cross-schema Trigger-Intel chip, burning
an entire report run on a nonsense seed).

The instruction tail is scar tissue: each block patches a past weak-model
failure (fabricated percentages → GROUNDING; sign flips → SIGN CONVENTION;
cherry-picked cells → MATERIALITY; empty recs → RECOMMENDATIONS). The repo's
own benchmark receipt says the answer: **deterministic guards beat LLM
machinery on strong models.** Apply the Track A rule per block — a behavior a
stronger model does unprompted is a RESTRICTION (delete or tier it); a
correctness contract belongs in CODE (verify post-hoc), not in prose repeated
per call.

**PE waves:**

- **PE-1 — inventory by weight.** Metering already counts prompt tokens; add
  per-template attribution so the top-10 prompt templates by monthly token
  spend are a dashboard read, not an RTF export. (Same instrument-first move
  as `?timings=1`.)
- **PE-2 — the report-prompt diet.** Per-block triage of
  `prompts_investigate.py`: grounding/traceability, sign consistency, and
  waterfall-sums-to-total become **deterministic post-generation checks**
  feeding the existing bounded-repair pass (one retry with the specific
  violation named — cheaper than 1,700 tokens of prophylaxis on every call);
  style/confidence rubrics compress to lines; the persona line stays. Tier
  what remains by ModelProfile: capable models get the short prompt, baseline
  keeps the guardrail text (the decision rule, made mechanical).
- **PE-3 — conditional assembly.** Playbook entries filtered by
  approach/relevance before injection (a "When X up" entry never enters a
  cross-sectional prompt); temporal vs cross-sectional templates fully split
  so contradictory scaffolding cannot co-occur; static text positioned as a
  stable PREFIX (system side) so provider prompt-caching can actually hit it.
- **PE-4 — stop damaging the inputs.** Truncate findings at sentence
  boundaries within budget, never mid-word; the fan-out caveat already proves
  per-finding annotation works — use the same seam.
- **PE-5 — the degenerate-seed gate.** Refuse or reroute before synthesis when
  the seed is self-evidently broken (metric total from a ~2-row table,
  cross-connection dimension mismatch). The whole report run is the burn; the
  prompt is just where it becomes visible.

**Why this precedes CI-5:** the model upgrade multiplies per-token cost.
Shipping a frontier model under today's prompts pays frontier prices for
boilerplate; the diet is what makes the upgrade affordable.

### 2.7 Anatomy of the delivered report (specimen 2 — same investigation, VERIFIED at source)

The report the user actually received for that prompt is the strongest
evidence yet — because **the model never wrote it**. Its own Confidence
section admits: "Narrative synthesis was unavailable (the model was slow or
failed); this report is assembled deterministically from the phase findings"
(`agent/investigate.py:7338`). The 3,833-token prompt was paid for and its
output discarded; a deterministic assembler shipped a five-page,
executive-styled PDF instead. Every defect in it is scaffolding, not model:

1. **The title IS an internal caveat.** The fan-out warning is built as a
   prose sentence and prepended into the finding's summary
   (`investigate.py:5238`); the fallback then promotes the *first phase
   summary* to the headline and joins summaries into the executive summary
   (`investigate.py:7322-7324`). Machine diagnostics became the report's
   first words. Two choices compound: caveat-as-prose × first-summary-as-headline.
2. **The question is never answered.** The seed claim ("total revenue is
   $14") appears nowhere in the body. An expert's first move — *"it isn't
   $14; the actual total is ~€45.4M; the $14 came from `rearm_single.orders`
   (~2 rows, a scratch table); and the question says $ while the data is
   €"* — is one query plus one paragraph. No phase performs it; intake
   template-dispatched to a cross-sectional weakness scan on a *different
   schema* instead.
3. **The "Financial impact" section is semantics-blind.** The peer-gap
   generator (`agent/opportunity.py:300`) benchmarks *shipped* orders against
   **returned** orders (€2.06M "opportunity" from aspiring to the AOV of
   orders that came back) and THE OUTNET (off-price outlet) against Mytheresa
   (full-price luxury). Mechanically hedged, semantically absurd — no
   dimension-semantics filter exists.
4. **Revenue semantics unexamined.** Returned (€18.2M) + cancelled (€1.8M)
   sit inside "GMV" un-reconciled — ~44% of the "revenue" is not realized
   revenue, and no line says so.
5. **Degraded mode dresses as the deliverable.** LOW confidence and its
   honest justification are the *last lines of page 4* of a confident,
   chart-rich PDF. A failed synthesis should look failed at the top, or
   retry — not footnote its own invalidity.

**The two specimens together are the full argument:** the prompt shows a
system that over-instructs the model when present; the report shows it
shipping templated pseudo-analysis when the model is absent. Both are the
same design stance — the intelligence is treated as a formatting step, not
as the analyst. Arc CI's CI-4 (the conversation invokes depth as a tool,
with judgment at the front) is the structural fix; the immediate correctness
items are filed as chips: caveats become structured metadata (never prose in
the summary) · fallback reports become visibly degraded artifacts with
caveat-free headlines · the opportunity generator gets a dimension-semantics
guard. The premise-check ("verify the seed claim first") joins PE-5's gate,
and "the report must address the asked question" becomes a PE-2
post-generation check.

---

## 3 · The substrate — serverless correctness + honesty (handoff §4, prioritized)

1. **Glossary seed cannot persist on serverless** — separate override for the
   generated path, then `WRITABLE_STORES` (`control_plane/writable_paths.py`).
2. **Role model env vars** — shared with CI-5; do once, early.
3. **pgvector migration incomplete** — 12 call sites still import
   `qdrant_client`; `_pg_where` can't express `suggestions_cache`'s two-key
   need. A design change, not a swap.
4. **Opt-in local Postgres + second CI job** — every serious defect this cycle
   was invisible locally *by construction*. Local and prod are different code
   paths; that asymmetry is the bug generator.
5. Chips/leftovers: Trigger Intel cross-schema scope · live-Qdrant tests fail
   rather than skip · `?tab=briefing`/`?tab=catalog` blank ·
   `refresh_popularity` staleness · `/suggestions` 73s (`task_18be0262`) ·
   API-blocks-in-sync-SDK-call (`task_8517909e`) · **views invisible to the
   agent** (`task_be7f6f91` — 9 sites filter `BASE TABLE`; also degrades
   editor completion and CI-2's schema tools) · packs-flywheel generalization
   (`task_52ede537` — build the acceptance metric first) · 40 stale branches.
6. **Unresolved:** the prod `FUNCTION_INVOCATION_FAILED` outages — #323's
   `_shared_base` fix is the first mechanism that fits but is NOT proven. If it
   recurs now, look elsewhere.

Unpushed/parked branches to disposition: `claude/contra-rate-and-alignment-fixes`
(`19fffe6`) · currency-VARCHAR fix (`c334c2d3`) · connector availability
(`8e6fae3`).

---

## 4 · Intelligence over time — the queued product arcs

These are the arcs that make the agent plane *compound* rather than answer:

- **Temporal synthesis** (user question 2026-08-09): ① a freshness→automation
  trigger for re-exploration (an automation KIND — tick/jobs/leases all exist);
  ② delta exploration via per-table watermarks; ③ **belief history +
  drift-as-finding** — validity intervals on findings (`last_confirmed`,
  `invalidated_at`, `superseded_by`; `generated_at`/`id`/`signature`/`parents`
  already exist) and run-over-run synthesis diffs. "Margin concentration
  flipped on 9/12" is worth more than either snapshot. Validity must be
  enforced at READ. Delta exploration is also the cost answer (~60 calls/run).
- **ODCS data contracts** (Ontos study): formal per-connection/table contracts
  (schema + quality rules + expectations) checked at ingest/reload, violations
  surfaced as findings — the systematized fix for the currency-VARCHAR class.
  Patterns only; never vendor Databricks-licensed code.
- **Concept↔asset linking** — Ontos's glossary-terms-to-tables/columns model is
  the formalization target for ground-first resolution (resolve business
  entity → table/column BEFORE SQL generation). Raw material exists in context
  graph + glossary + ontology_overrides.
- **Aughor as an MCP server** — the mirror image of CI-2: the same
  catalog/ontology/insights surface exposed so external assistants (Claude,
  IDEs) consume Aughor as a context provider. One tool surface, both
  directions. *(2026-08-13: absorbed into Arc OA, §7 — the server exists in
  `aughor/mcp/` and n8n's MCP Client is its first named external consumer.)*

---

## 5 · Sequencing

**DECIDED 2026-08-12: Arc CI runs to completion before any editor wave.**
SE-0 still goes first — its org-scope fix protects the chat tools as much as
the editor, and it is one thin PR.

```
NOW (order matters)
  0. Commit the 3 SQL-editor docs + this doc to main (docs-only PR).
  1. SE-0            — backend contract incl. the org-scope security fix
  2. CI-0 + PE-1     — transcript reading + prompt-weight attribution (cheap)
  3. The three report-honesty chips (caveats→metadata · degraded-report
     banner · opportunity semantics guard) — small, user-visible, immediate

ARC CI — run to completion
  4. PE-2 → PE-3 → PE-4 → PE-5   (the diet + gates; funds the model change)
  5. CI-5a role env vars → CI-1 threads/memory → CI-2 tool roster
     → CI-3 persona → CI-5b BYOK → CI-4 depth-as-a-tool
     → CI-6a panel organs → CI-6b chat-first home route
  Substrate items 1–4 ride alongside as small PRs whenever CI blocks.
  CI-0's transcript reading repeats after each wave (the success measure).

THEN — the editor program
  SE-1 → SE-2 → SE-3 → SE-4 → SE-5a   (DX-1 rides with SE-2; DX-2 any time)

QUEUED (data- or decision-gated)
  Temporal synthesis (after CI-2 — drift needs the insight substrate stable)
  ODCS contracts · concept↔asset linking · Aughor-as-MCP · DX-3 spikes
```

Wave 6's remaining obligation (route-receipt reading) is satisfied by CI-0's
cadence; Wave 7 IS CI-4 + CI-6 — the unified-adoption plan's tail folds into
this document.

### 5.1 · Addendum 2026-08-13 — where we actually are, and Arc OA slots in

Landed since this doc was written: **Arc CI is complete except CI-1d**
(#328–#342 — roster, identity, BYOK, depth-as-tool, trail+rail, `/chat`);
the editor program is through **SE-2 including PR E** (#336, #338, #340,
PR #343). The current series is therefore the editor tail. Arc OA (§7,
from `LANGFUSE_N8N_INTEGRATION_STUDY_2026-08-13.md`) queues **after it**,
with two deliberate exceptions small enough to ride alongside:

```
CURRENT SERIES (finish first)
  SE-3 F  cancel + timeout          SE-4 I  results viz
  SE-3 G  EXPLAIN + bulk grid       SE-4 J  versions + specSync
  SE-4 H  multi-statement + params  SE-5a   Quick Fix
  CI-1d   AI-SDK thread model       (the one CI wave left)

RIDE-ALONGSIDE (small, unblocked, independent — slot when a gap opens)
  OA·N8-0  wire monitors' dead notification_channel → fire_action
           (an in-repo gap with or without n8n; one small PR)
  OA·LF-1  repair the silently-dead Langfuse backend (OTLP repoint,
           delete v2 SDK path, pin >=4,<5, rot-guard test, force_flush)

THEN — ARC OA proper (§7)
  LF-2 → N8-1 → N8-2 → LF-3
  N8-3 STRICTLY after CI-1d (tool wiring changes shape there — never
       build the action tools twice)
```

Rationale for the two ride-alongs: N8-0 fixes a documented unwired field
(`monitors/models.py:108`) and LF-1 fixes a **live silent failure** — both
are repairs, not features, and neither touches the editor's files.

**House rules that bind every PR here:** SE-0's legacy `/query/run` output
byte-identical (golden test) · ratchet battery on your own diff · five frontend
gates + `gen:api` on route changes · one PR at a time, squash, never push
without authorization · measure premises in the environment that matters
(prod ≠ local proportions — `?timings=1` exists because of this) · adversarial
self-review before "done" · prove each wave live against a demo connection.

## 6 · Decisions — LOCKED by the user 2026-08-12

1. **Model spend = bring-your-own-key.** Orgs supply their own provider keys
   and pick models per role (CI-5b); the platform's own posture stays
   free-tier with a hardened ladder as the no-key default (CI-5a). The PE
   diet matters MORE under BYOK — customers pay the prompt bill, so bloat is
   now a customer-facing cost.
2. **Chat shell = "B's posture, C's plumbing, one application"** (re-decided
   after mockup review, superseding the earlier evolve-in-place call). CI-1
   adopts the AI SDK UIMessage/parts data model inside `web/`; CI-6a evolves
   the panel; CI-6b adds a chat-first home route in the same app — the
   conversation becomes the front door, the workspace a destination. No
   second application; vercel/chatbot is reference-only (the Ontos rule).
3. **Chat write-scope = tiered.** Personal reversible artifacts write
   directly; org-shared semantic state is proposal-only (CI-2).
4. **Sequencing = Arc CI complete first**, after SE-0. The editor program
   (SE-1…SE-5a) starts when CI-6 lands. (§5.)

---

## 7 · Program C — Arc OA: observe + act (Langfuse + n8n) — added 2026-08-13

**Source study:** `LANGFUSE_N8N_INTEGRATION_STUDY_2026-08-13.md` — every claim
verified live against the products and this codebase; read it before building
any wave here. Summary only below.

### 7.1 The thesis — the fourth plane

The three planes of §0 share one property: aughor **writes** exhaustively —
session log, trace ids, cost attribution, audit, receipts — and **reads/acts**
almost nowhere. The platform-review finding ("features stall at TESTED, not
LEVERAGED") is structural, not accidental: there is no operator surface over
the telemetry, and no actuator behind the insights. Arc OA adds the leverage
plane: **Langfuse is the read side of telemetry that already exists; n8n is
the act side of an Action Hub that already dispatches.** Neither is a new
capability so much as a consumer for a producer aughor already built.

### 7.2 The two findings that shaped it

1. **The Langfuse integration exists and is silently dead.**
   `aughor/telemetry.py` speaks SDK v2 (`lf.trace` :58, `tr.span` :622,
   `tr.generation` :690); the venv resolves `langfuse>=2.0.0` to **4.7.1**,
   where none of those methods exist. Init succeeds; every call raises; every
   raise is swallowed at debug. The richest record never flowed there anyway:
   `telemetry.log_generation` has had zero call sites ever
   (`provider.py:1172`) — the real per-call data lives in the session log.
2. **n8n is NOT open source.** Sustainable Use License: internal business use
   only; embedding in a commercial product = paid Embed/OEM (execution-billed,
   branding stays). Aughor ships a licensing module of its own — the embed
   trap is real. **Hard rule: arm's-length only.** Users run their own n8n;
   we ship workflow-template JSON, docs, and (optionally) an MIT community
   node. Never bundle, embed, or resell.

### 7.3 The waves

```
OA·N8-0  Wire notification_channel → fire_action on alert fire.
         Closes the documented gap (monitors/models.py:108); alert payload =
         name, severity, value vs threshold, connection, deep link. 1 small PR.
OA·LF-1  Repair: point the EXISTING OTel exporter at Langfuse's OTLP endpoint;
         delete the v2 SDK span path; pin langfuse>=4,<5; SDK-surface
         rot-guard test; serverless force_flush on response end. 1 PR,
         net-negative diff.
OA·LF-2  Data in: generation spans from _record_llm_call (the one chokepoint —
         model/role/tokens/fallback/org all already there); chat session id →
         langfuse.session.id; org → user; PRICES → Langfuse model definitions
         (two cost surfaces must agree to the cent); content only inside the
         existing capture_prompt windows. 1 PR.
OA·N8-1  Delivery fabric: integrations/n8n/ workflow templates (alert→Slack,
         alert→Jira, briefing→email, escalation→PagerDuty) + setup doc.
         Aughor's native-integration roadmap category collapses into "here is
         the template." Mostly JSON/docs.
OA·N8-2  Governed brain: doc + templates for n8n's MCP Client → aughor's MCP
         server (ask / get_metric / deep_analysis with Trust Receipts — not
         another raw text-to-SQL node). Verify FastMCP's HTTP transport against
         n8n live (n8n speaks SSE/streamable-HTTP). Small PR + live test.
OA·LF-3  The pillars we lack: LLM-as-judge on sampled production traces
         (drift watch — complements, never replaces, the pre-ship golden-SQL
         gates), annotation queues, chat 👍/👎 → score_current_trace. 1–2 PRs.
OA·N8-3  Actions from chat (the closed-loop wave): n8n MCP Server Trigger URLs
         registered as capability-gated "action packs"; Arc CI's agent gets
         them as tools; n8n-side human-in-the-loop approval + Action-Hub-style
         audit. STRICTLY after CI-1d. Flag-gated. Largest lift, largest prize:
         a system that does, not just knows — without aughor shipping a single
         connector.
```

### 7.4 Locked verdicts (from the study — do not relitigate without new facts)

1. **Prompt authoring stays in the repo.** Langfuse's "deploy prompts without
   code changes" is precisely the property the CI vocabulary ratchets exist to
   prevent. Patterns only; the playground needs no integration to be useful.
2. **Aughor's eval framework is untouched.** Pre-ship, execution-grounded,
   promotion-gated — load-bearing CI. Langfuse judges live traffic for drift;
   the split is watch-vs-gate, complementary by construction.
3. **Langfuse never enters the request path or the Vercel perimeter.** Local
   docker compose now; a small VM when an operator dashboard is wanted; Cloud
   at most for operator-only, content-off traces. Observer, never load-bearing.
4. **Tenancy line:** one shared Langfuse project = operator-internal tool with
   content capture OFF by default. Per-tenant projects (or EE project-RBAC +
   masking) before any tenant ever sees a trace surface.
5. **user_id is not mapped until it is populated** — it measures 0% today, and
   a dimension that is always blank teaches nothing (obs/usage.py's own rule).

### 7.5 Open questions (user input wanted before LF-2 / N8-2)

Langfuse host + project topology · community-node ambition (`n8n-nodes-aughor`
+ verified-node submission vs HTTP/MCP templates only) · a demo n8n instance
(docker, internal use — license-fine) vs purely user-side · chat feedback UI
now (LF-3 prerequisite) or judge-only initially.

## 8 · Briefing UX backlog — from the theLook live pilot (added 2026-08-26)

User-requested items surfaced while driving the Briefing page against the live
BigQuery connection. Recorded for prioritisation, not yet scheduled.

1. **The data table behind a finding.** Each briefing finding's evidence should
   let the user see the underlying result table the claim is based on — the
   rows, not just the SQL and the chart. (Evidence drawer already carries the
   SQL and receipt; the table view is the missing third leg.)
2. **Chart legend collides with the plot.** On brand-cardinality charts the
   legend frame overlays the bars (see the profit-margin-by-brand exhibit).
   The user cannot move or re-orient the legend. Needs either automatic
   placement (outside the plot area when the series count is high), a
   density-aware legend collapse, or user-draggable orientation.
3. **Editable evidence SQL (deliberately controversial).** Allow the user to
   edit the SQL shown in a briefing finding's evidence and re-run it —
   turning a static receipt into a starting point. Needs a clear provenance
   break: an edited query is the USER's derivation, and the finding must stop
   claiming the explorer's grounding for it (the Program AT delivered-verdict
   rule applies).
4. **Status counters mix per-run and lifetime numbers** (found the same day):
   `queries_executed` resets per run while `insights_found` reads lifetime, so
   surfaces that join them ("1q · 22 insights") misread as broken history. The
   explorer status model should carry both run-scoped and lifetime counters,
   explicitly named. (The Briefing page no longer shows counters at all.)
5. **Chart number formatting, Tableau-grade** (v1 shipped 2026-08-26: a viewer
   format picker on every chart's hover toolbar — auto / % / integer / decimal
   / currency / compact — feeding the resolver's existing d3-format parameter).
   Remaining: custom format codes, date/month axis formats, per-column formats,
   org-currency-aware symbols, and persisting the choice on the exhibit.
   Reference: Tableau's number-formatting model.
6. **`columnUnits` is dead plumbing** (found same day): Chart.tsx accepts the
   backend's authoritative per-column unit ("this column is a percent") and has
   never passed it to the Vega resolver since the engine migration — the reason
   ratio charts render 0.598729927282. Rewire it as the DEFAULT the viewer's
   picker overrides.
