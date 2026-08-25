# Headlong study — persistent agency and the idle mind (2026-08-25)

Studied: [Headlong launch post](https://www.laude.org/updates/headlong-a-microharness-for-persistent-agents)
+ [github.com/laude-institute/headlong](https://github.com/laude-institute/headlong), against the
repo at `claude/headlong-persistent-agent-assessment = f74eb22`. Companion to the Mastra and
Cognee studies (`MASTRA_STUDY_2026-07-29.md`, `COGNEE_STUDY_2026-07-28.md`) — same question
(what does an adjacent stack have that we lack, and what do we have that it cannot copy?) plus a
sharper one this time: Headlong builds the one thing our own tagline promises and our code does
not yet do. `README.md:5` says *"your warehouse, always thinking."* Every background loop we run
is a wall-clock timer or a condition probe; nothing in this codebase thinks when nobody asks.
Headlong is a working existence proof of exactly that missing behavior.

**Verdict up front: adopt the loop shape and the memory shape, not the runtime.** Headlong and
Aughor are near-perfect inverses. They have idle cognition with no governance: a single-tenant
Bash harness where one agent thinks 24×7, messages are observations, and the only safety rails
are Docker and an exponential backoff. We have governance with no idle cognition: charters,
budgets enforced by cancellation, provenance-required stores, org-scoped everything — and a
background plane that only ever wakes on a clock. Their runtime would violate five of our
invariants on day one. Their *shapes* — the idle wake with backoff, the monolith router, events
as observations, progressive-resolution memory — drop onto seams we have already built
(`automations/scheduler.py`, `kernel/queue.py`, `kernel/agents.py`, `kernel/jobs.py:83`) as a
seventh charter plus one condition kind, not a parallel runtime. This is also the third
independent confirmation (after Mastra's AgentNetwork retreat and our own R4 ablation) that the
industry lands on *one routed loop* rather than emergent multi-agent choreography — Headlong
tried the fleet and consolidated it away after paying for double replies and feedback loops.

Provenance note: laude.org and the Hacker News thread are egress-blocked from this environment.
The launch post's claims were taken from the search index snippet plus the repository's own
README and `design/` docs, which are richer than the post; repository figures (444 stars, 517
commits, "$1–2/hour") are the project's own statements as of 2026-08-25, not measured here.

---

## 1. What Headlong is (verified 2026-08-25)

Open-source agent microharness from Laude Institute (Apache-2.0, © 2026; 444 stars, 36 forks,
517 commits on main; core under 10K lines of Bash 3.2+; deps: git, curl, jq; Docker recommended;
Anthropic/OpenAI/Gemini/OpenRouter via one `llm` CLI). Installed by `curl | bash`; the agent's
name becomes a command (`ada hello`, `ada dash`, `ada stop`). Slack/Telegram/web bridges,
systemd deploy units, a Python dashboard, and a `terminal_bench2_eval/` harness.

The thesis is stated as a hypothesis, in their own words: *"if we spend enough tokens on
'unconscious' thought processes before producing each next 'conscious' thought, an agent
thinking loop can run 24x7 and stay on the rails."* The agent is *"never asleep and there is no
checklist"* unless the agent writes one. And the message model, which is the philosophical core:
*"A message from a human doesn't start a session. It lands in the agent's thought stream as one
more observation, and the agent decides if and when to respond."*

Five components:

- **`shellm`** — the recursive engine: send context to an LLM, execute the Bash it returns,
  append results, repeat. Bash *is* the tool surface; there is no tool registry.
- **`traj`** — the trajectory: append-only JSONL DAG, fork/merge, full history preserved.
  The only agent-specific state (*"one append-mostly log of thoughts is the only
  agent-specific state"*).
- **`context`** — renders trajectory → LLM messages with tiered compaction: *"the entire
  trajectory stays in context at exponentially decaying resolution. Recent entries appear
  verbatim, and older entries are progressively summarized"* — raw entries retrievable on
  demand, subagents inherit the parent trajectory.
- **`thinkers`** — the wake dispatcher (see §3.2 for how this collapsed into a monolith).
- **`llm`** — multi-provider CLI abstraction.

One agent serves many humans over one shared stream ("multi-player": *no hard walls between
conversations*), can fork its own codebase, test changes, and merge them back, and costs
"$1 to $2 an hour" at typical settings — the backoff design doc claims a 10× idle-cost
reduction over their prior scheme (≈6 spontaneous wakes/hour at a 600s cap, vs ~60 before).

## 2. How the stacks line up

| Layer | Headlong | Aughor |
|---|---|---|
| Idle cognition | The product: self-guided think loop, 24×7, agent picks its topics | **Absent.** Every loop is clock/condition-driven: 60s automation heartbeat (`automations/scheduler.py:138`), hourly Scout re-arm on schema-fingerprint change or 7-day staleness (`explorer/continuous.py`), hourly ontology refresh. `AGENTIC_ARCHITECTURE.md:41` names it gap #4: *"Reactive, not proactive — nothing watches the event spine and self-assigns work"* |
| Wake pacing | Exponential backoff state machine: `delay(n)=min(BASE·FACTOR^(n-1), CAP)` (5s→300s), dwell `HOLD=3` empty wakes per level; resets on external message or real work; singleton timer process + liveness watchdog | None needed yet — nothing wakes without a clock. `kernel/jobs.py:564` `supervise_forever(30)` sweeps orphans but assigns no work |
| Event model | Everything is an observation in one stream; agent decides if/when to respond | Events exist as *records* (`events` journal + `session_events` span tree, `kernel/ledger.py:155`), consumed by dashboards and alert rules (`obs/agent_alerts.py`), never by a reasoning reader |
| Sessions | Deliberately none — one timeline, all humans | First-class and org-scoped: `session_id` on investigations (`db/history.py:142`), chat-session REST, AI-SDK-shaped restore |
| Memory | Progressive-resolution hierarchy: every entry links up to coarser summaries, down to finer detail; 10× compression per level; O(log₁₀ N) drill-down; filesystem is the graph store | Declared and deliberately inert: *"the earned L0–L3 autonomy ladder is NOT built yet"* (`memory/__init__.py`); `record_run()` persists the signals the ladder will read; cross-session recall is exact-question matching only (`db/history.py:763`) |
| Budgets | Backoff *is* the cost model; no per-run ceiling | The core discipline: per-charter token/time budgets enforced by cancellation mid-run (`kernel/jobs.py:296-338`), heartbeats flush live spend, deployment ceiling `AUGHOR_MAX_TOKEN_BUDGET` |
| Tenancy / governance | None: one host, one mind, your Unix permissions (Docker recommended) | Org-keyed everything, RBAC, clearance trim, audit, kinetic inbox, provenance-required stores |
| Tool surface | Model-authored Bash, executed | Governed tools with schemas and provenance; SQL through guards; *"a delegate cannot out-reach its own definition"* (`agent/delegate_tool.py`) |
| Trust | Trajectory transparency (watch it think) | Trust Receipts, caveat assembly, graduation receipts — no counterpart on their side |
| Self-modification | Fork own repo, test, merge | Out of scope, and should stay there |

The complementarity is stark: each column's blank is the other column's core competence.

## 3. The shapes worth taking

### 3.1 The idle wake with exponential backoff — the headline import

Headlong's real invention is not "the agent has a soul"; it is a small, persisted state machine
that makes unprompted cognition *affordable and bounded*. External events always get full
attention at level 0. Only spontaneous thought backs off: empty wakes climb the ladder
(5→10→20→…→CAP, dwelling `HOLD` wakes per rung), and any real work or human contact resets to 0.
The step that wakes the mind is an ordinary event from a singleton timer, so the loop has no
resident sleeper, and a watchdog synthesizes a wake if the mind goes silent — *"a ≤window
wake-up delay instead of a dead mind."*

Everything in that design maps onto machinery we already run. The automation heartbeat is
already *the* one loop every background family rides as virtual automations
(`automations/adopt.py`), each tick submitting metered kernel jobs via `submit_background_tick`
(`kernel/jobs.py:634`). An idle wake is **one new condition kind** (backoff state consulted at
tick time, persisted per `(org, connection)`) and its effects are, per our own rule, references
to existing primitives — investigate, brief, notify — never new action types
(`automations/models.py`). On the serverless face the same condition rides `GET /cron/tick`
with the `claims` lease table (`kernel/ledger.py:111`) providing the at-least-once discipline
the durable-execution spike already measured (49 KB state, ~1.1 ms overhead, HTTP 409 on
contention — `VERCEL_PLATFORM_DESIGN_2026-08-05.md`). This is `AGENTIC_ARCHITECTURE.md`
Phase 3 — the only phase still unbuilt — arriving with someone else's operating experience
attached.

### 3.2 One routed wake, not a thinker fleet — a lesson they paid for

Headlong first shipped six concurrent thinkers (inner_monologue, actor, goals_manager,
learning, mind_wanderer, values_manager) on a subscription dispatcher. It failed in exactly the
ways emergent multi-agent systems fail: *"double replies, mimicked conventions, loops."* Their
`THINKERS_spec.md` now marks the roster stale; `monolith_thinker.md` records the consolidation
and the reason: *"most thinker 'jobs' are alternatives, not parallel processes."* The
replacement is one wake, one agentic call that routes itself — a function menu (`think`, `act`,
`reply`, `learn`, `recall`, `goals`, `idle`) chosen by the model from *"routing hints, not
rules"*, with one soft convention (an unanswered human message almost always wins) and routing
decided in *"just the first tokens of the run — no separate classifier call, no second
process."*

We independently arrived at the same shape twice — the analyst loop keeps deterministic phase
bodies as tools and lets the model choose only the sequence (`agent/analyst.py`), and the R4
ablation rejected an LLM mega-orchestrator — and Mastra deprecated AgentNetwork into plain
supervisor agents. Headlong is the third data point, and the most instructive because they ran
the fleet in production first. The import for us is pre-emptive: when the idle agent lands, it
is **one charter with a routed menu**, not watcher+briefer+curator growing autonomous siblings.
Their double-reply guard is also worth copying wholesale into any reply-capable background path:
stamped `reply_to` metadata, position-based idempotency, and deterministic already-answered
signals fed to the router — three layers, none of them "the model will probably not do that."

### 3.3 Events as observations — the spine gets a reader

The message-as-observation stance, minus the shared-stream tenancy (rejected in §4), is the
right frame for our event spine. We already record everything a synthesist would want to read —
`session_events` with spans, models, tokens, org/user attribution; the `events` journal;
monitor runs; explorer findings — and nothing reasons over any of it. The demand signal is
measured, not hypothetical: CI-0 found **46 questions asked 3+ times, one asked 52 times**
(`CI0_TRANSCRIPT_READING_2026-08-12.md`). To a reasoning reader those are observations begging
for synthesis: repeated questions → propose a trusted query or a monitor; schema drift +
failed-run clusters → a brief with receipts; a monitor breach plus a related finding → spawn an
investigation with both cited. The user-facing translation of "it thinks when not asked" is
precisely our existing primitives arriving unprompted, with provenance.

### 3.4 Progressive-resolution memory — a concrete design for the inert ladder

`unified_progressive_resolution_memory.md` is the best design doc in their repo: one hierarchy
for episodic and semantic memory where every entry links up to coarser summaries and down to
finer detail, ~10× compression per level, retrieval by drill-down (scan ~10 coarse entries,
descend, O(log₁₀ N) — ~4 LLM calls at 10k memories), downlinks written at seal time, uplinks
back-patched when the coarser entry forms. Two of its three load-bearing patterns already exist
here: `session_events` is the append-only step log rollups would seal over, and
supersede-don't-delete artifacts are versioned summaries with history. Its semantic–episodic
bridge — a belief's children point at the trajectory steps that produced it — *is* Trust
Receipt lineage, generalized: our findings and ontology entries already must cite sources; this
extends the same discipline to what an agent remembers. It is the missing design between
`record_run()`'s persisted signals and the L0–L3 ladder `memory/__init__.py` declares unbuilt,
and it beats the flat vector-recall shape the Cognee study already argued against.

### 3.5 Reply-first, work-later

The monolith's two-tier chat path — *"reply immediately, no thinking, no tools"* from existing
context, then substantive work on a later wake — is a good latency contract for the responder
charter and consistent with how salvage already treats interrupted turns. Worth adopting as a
stated behavior: the fast answer draws on the graph, prior answers, and packs; `deep_analysis`
follows as its own metered job.

### 3.6 Backoff and budgets are two halves of one cost model

Our budgets cap the cost of *a run*; nothing yet caps the *rate of runs*, because nothing
self-initiates. Headlong's dial is exactly the missing half: idle spend is bounded by the CAP
and constant (≈6 wakes/hour at 600s; raise CAP to 30–60 min for near-zero idle spend). For us
backoff level per `(org, connection)`, budget per wake from the charter, and the existing
deployment ceiling compose into: *spend scales with activity and evidence, and its worst case
is a config number* — which is the sentence that makes an always-thinking agent sellable to a
governance buyer.

## 4. What does not transfer — the drift guards

- **Bash as the tool surface.** Model-authored shell, executed, is their whole interface and
  our anti-pattern. Provenance-required stores, SQL guards, and delegates that cannot
  out-reach their definitions are the product. The idle agent gets `platform_tools()`, nothing
  more.
- **One shared thought stream.** *"No hard walls between conversations"* is a feature for a
  hobbyist's Slack and a disqualifying data-governance defect for a warehouse platform. Our
  unit of mind is `(org, connection)`; walls are the product.
- **Self-modification.** An agent that forks and merges its own harness is a research toy we
  must not ship. Self-improvement here stays data-shaped and governed: learned query templates
  (propose→confirm, EXPLAIN-gated, `memory/skills.py`) and instruction revisions with evals
  (`custom_agents/revisions.py`).
- **Persona cognition.** Headlong agents think about themselves — goals, values, wandering.
  Our agent thinks about *the warehouse*. Topics come from the event spine and observed demand,
  not self-selected identity work. This is also the cheap defense against the "expensive
  diarist" failure mode: an idle wake with no evidence routes to `rest`, not to musing.
- **Trajectory as the only state.** Elegant at one agent on one laptop; at N orgs it is the
  "one store per concept" violation we have paid for three times.
- **The 24×7 hypothesis itself, on faith.** Their own history is the caution: the rails failed
  (loops, mimicry, double replies) until they re-architected. We do not adopt "enough
  unconscious tokens keeps it on the rails" — we adopt the loop inside rails we already
  enforce: charter, budget, metering, provenance, flags.

## 5. Attach points already in the tree

| Their mechanism | Our seam | Gap |
|---|---|---|
| Timer-driven idle wake | Automation heartbeat + virtual automations (`automations/scheduler.py:36`, `adopt.py`) | New condition kind + persisted backoff state |
| Backoff state machine | — | Small; state rides the automation store |
| Monolith routed wake | Tool loop + charters (`agent/tool_loop.py:107`, `kernel/agents.py:67`) | Seventh charter (background lane, own budget; the reserved `watcher` stays threshold-SQL) |
| Watchdog / "dead mind" | `supervise_forever` (`kernel/jobs.py:564`) | One additional sweep check |
| Durable wakes, serverless | `WorkQueue` Protocol + `claims` leases (`kernel/queue.py`, `kernel/ledger.py:111`) | Backend selection, already anticipated by the docstring |
| Suspend/resume a thought | `JobState.PAUSED` (`kernel/jobs.py:83`) + LangGraph checkpointer | Unused-by-jobs today; wiring |
| Trajectory rollups | `session_events` + versioned artifacts | Tier-1/tier-2 rollup writer + drill-down read path |

Naming: the charter needs a glossary entry before code (`docs/GLOSSARY.md` is enforced).
Proposed: **Synthesist** — role "synthesize the state of things when no one is asking" — since
`watcher` is reserved for threshold monitoring and the two must not blur.

## 6. Risks and honest unknowns

- **Proactive hallucination burns trust asymmetrically.** A wrong solicited answer is a bad
  turn; a wrong *unsolicited* claim teaches the user to ignore the product. Proactive output
  must clear the receipt bar at least as strictly as solicited output, and should surface as a
  digest/brief, not a notification stream. Verification before surfacing is non-negotiable.
- **Cost multiplies by org × connection.** $1–2/hour for one hobby agent is ~$700–1400/month
  per always-on mind. Backoff CAP per workspace, evidence-gated wakes (no new events since
  last wake → `rest` without an LLM call where the deterministic signals suffice), and charter
  budgets keep the worst case a config number — but this deserves its own measurement wave.
- **Unverified:** the launch post and HN thread were unreachable (egress-blocked); no
  independent read on community critique. Headlong's `terminal_bench2_eval/` results are
  unreviewed — we have no evidence their idle thoughts are *useful*, only affordable. Their
  stars/cost figures are self-reported. None of this changes the verdict, because we are
  adopting shapes we can evaluate against our own evals, not their outcomes.

## 7. Proposed sequence (each phase flagged, off by default, byte-identical when off)

1. **H1 — pacing without a mind.** The backoff state machine as a new automation condition
   kind riding the existing heartbeat and cron tick; persisted per `(org, connection)`; metered
   no-op effect; ratchet tests for the state transitions. No LLM calls. Proves the wiring and
   the serverless path (claims lease) cheaply.
2. **H2 — the routed wake.** `synthesist` charter (background lane, budget on the order of
   100k tokens / 300s per wake, governed like every other charter); one metered job per wake
   through `submit_background_tick`; menu of `synthesize | propose | rest` routed by hints,
   not rules; reads the event spine and question history; writes only through existing
   primitives (finding, brief, proposed trusted query, proposed monitor) with provenance and
   receipts. Double-reply/duplicate-proposal guards deterministic, per §3.2.
3. **H3 — memory with resolution.** Tier-1/tier-2 rollups sealed over `session_events`,
   drill-down retrieval, and the semantic–episodic bridge onto findings/ontology — the
   substrate both the Synthesist and the L0–L3 ladder read. This is where cross-session recall
   graduates from exact-question matching to actual memory.

Non-goals, restated so the study cannot be cited for them later: no shell tool surface, no
cross-org stream, no self-modifying harness, no persona/values cognition, no second background
runtime beside the heartbeat.

The goal does not move: Aughor is an agentic data intelligence platform whose numbers can be
checked. Headlong's contribution is the missing tempo — a governed mind that is awake between
questions, pays for its own attention, and shows its receipts when it speaks first.
