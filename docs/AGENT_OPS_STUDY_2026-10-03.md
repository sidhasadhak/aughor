# Agent Ops, tested — what a person meets, measured against the field (2026-10-03)

> **Adopted 2026-10-03** — ROADMAP §3.52 (Arc AO), §4.8 (five refusals), §6 item 38 (ten clauses, every one
> as recommended); PENDING item 50 and its section. The user: *"adopt all as recommended and commit locally"*.
> Nothing is built; the next step is AO-0. §6 below is the proposal as adopted.
> ~~**Status: DRAFT study.** Nothing is adopted, nothing is built, no arc exists yet.~~ Written at the user's direction: *"brutally test our Agent workflow… everything that we
> have in the Agent Ops tab… I want it to be a gold standard… easy to set up, quick and
> efficient on delivery with self recursive learning."*

## Why now

Agent Ops is the one tab that claims to be a product in itself — "ONE surface for the agent
estate" (`web/components/AgenticOpsWorkspace.tsx:102-106`). It has had seven arcs land on
it (VA, DS-5, PX-5, HB-2, HB-6, SP, TJ-4) and no arc has ever tested it as a whole, as a
first-time operator would: create an agent, put it in Slack, watch it, trust its numbers,
and see it get better. This study does that, on the live deployment, and then holds the
result against what the field now ships.

## 0 · How this was tested, and what was deliberately not done

- **Live, not imagined.** The web app on `:3000` and the API on `:8000` were driven through
  the browser at 1440×900. They serve the MAIN checkout (`claude/declared-filter-and-chat-trace`
  @ `b2b7e2c5`); `git diff` shows every Agent Ops file read here is byte-identical between that
  commit and this worktree's `389ad13d`, so the screens and the code lines agree.
- **Every layer opened**, every tab of a custom agent opened, the Create flow walked end to
  end, the Slack door rendered, Integrations → Slack read.
- **A throwaway agent was created and deleted** (`ua_1fd66217a786`, `POST /agents/custom` →
  `DELETE`, both 200; the create route makes no model call — `aughor/routers/agents.py:327-340`
  is validation plus an INSERT). Nothing else was written.
- **No model call was spent.** "Draft it", "Run evaluation", "Propose" and "Run now" were not
  pressed — each is a model call (`custom_agents/propose.py:220-223`, `quality.py:31`).
- **No Slack app was created, no token pasted, no supervisor started.** The Slack door was
  read to the point of "paste three values back".
- **Four code audits** ran in parallel (agent model · Slack mechanism · every panel · learning
  loops). Every load-bearing claim they made was re-read at the cited lines before it appears
  below; the "How verified" column says which ones were only read, never run.

## 1 · What Agent Ops is today

| Surface | What it holds | Size |
|---|---|---|
| Seven layers | Overview · Roster · Attention · Activity (Usage · Stream · Traces · Phases) · Automations · Hub · Departures | 11.6k lines of TSX across 26 files |
| Agents | **6 built-in "charters"** — static Python (`aughor/kernel/agents.py:103-204`), governable only by enable/budget/model pin · **custom agents** — rows in `data/agents.db` with instructions, connection, schema scope, documents, packs, grants, goldens, guardrails, revisions (`aughor/custom_agents/models.py:33-117`) | 19 `/agents*` routes |
| Doors to an agent | Web chat · HTTP `/ask` · AG-UI · Slack (Socket Mode, one app per bot record) · an automation's `investigate` step. **Not** MCP (the `ask` tool has no agent parameter, `aughor/mcp/server.py:61-79`), **not** email, **not** Teams | 9 `/slack-bots*` routes |
| Slack runtime | A Node process in `bots/slack/` (1.5k lines TS) that reads `GET /slack-bots/runtime` every 30 s and opens one socket per bot | started by hand, by nobody else |
| Live estate (this machine) | 6 charters · 2 custom agents · 1 Slack bot (`sb_f4755b5da613` → The Look Analyst) · 6 automations (4 live, 3 on probation) · 52 departures (24 departed, 28 held) · 0 alert rules · 0 MCP servers | — |
| Tests | Python: 19 unit files touch these routers and stores. Web: `DeparturesPanel` (5 tests) and `TraceFlow` (724 lines) render a panel; `AgenticAgentsPanel.test.tsx` and `AutomationsPanel.test.tsx` test helpers only. **7 of 8 panels and both Create/Slack-door components have no rendering test.** | — |

## 2 · Findings

**How verified:** LIVE = seen on the running deployment · CODE = read at the cited lines ·
REPORTED = an audit's claim, cited but not re-read.

### A · The Slack door (where "easy to set up" is decided)

| # | Finding | Evidence | How verified |
|---|---|---|---|
| A1 | **Twenty manual steps across four surfaces** to get one @mention answered from a fresh install: Aughor UI → api.slack.com (manifest paste, install, three separate pages for three secrets) → Aughor UI (paste three) → Aughor UI (mint a supervisor key, shown once) → terminal (`cp .env.local.example`, paste key, `npm install`, `npm run dev`) → Slack (`/invite`). Five hand-copied secrets/blobs. | Ledger in §8; `AgentSlackDoor.tsx:178-253`; `routers/slackbots.py:67-76`; `IntegrationsPanel.tsx:438-476`; `bots/slack/package.json` | LIVE + CODE |
| A2 | **Nothing starts or watches the supervisor.** `start.sh` starts API and web only; no Dockerfile, no service unit, no launch entry, no installer step. On this machine it is **not running** (`ps` shows no `bots/slack` process) while the bot card reads enabled and "Answers as The Look Analyst". There is no heartbeat, `last_seen` or "listening" field anywhere in the store, the API or the UI — a dead bot is indistinguishable from a live one. | `start.sh:4-8`; grep of `heartbeat|last_seen|running` across `aughor/slackbots`, `routers/slackbots.py`, `IntegrationsPanel.tsx`, `AgentSlackDoor.tsx` = 0 hits | LIVE + CODE |
| A3 | **The success message omits the process.** After "Create Slack bot" the UI says *invite it, then add a Post-to-Slack action* — not that a supervisor must run, nor that a key must be minted. The key control appears only once a bot exists, one screen away. | `AgentSlackDoor.tsx:221-226`; `IntegrationsPanel.tsx:438-476` | CODE |
| A4 | **Every UI-made bot is in "legacy compat" mode.** `render_manifest(agent_view=True)` exists and adds `assistant:write` + the Agents & AI Apps feature, but neither the manifest call nor the create call from the UI ever sends `agent_view`; the live bot has `agent_view: false`. Progress cards and the native stop button are therefore "silently absent" — the README's own words. Slack announced on 2026-08-20 that `assistant_view` retires in February 2027, that **new apps can no longer use it**, and that the move to `agent_view` is one-way. | `slackbots/manifest.py:45-81`; `AgentSlackDoor.tsx:96-100,136-143`; `bots/slack/README.md:17-31`; `GET /slack-bots` live | LIVE + CODE + web |
| A5 | **Manifest and README disagree on what agent mode needs.** The manifest adds one scope; the README lists four extra events (`app_home_opened`, `app_context_changed`, `agent_session_stopped`, `agent_session_title_changed`). Nobody has run the agent-mode manifest against Slack. | `manifest.py:73-80` vs `README.md:39-41` | CODE |
| A6 | **"Regenerate" the supervisor key takes every bot dark within 30 s** — the registry returns 503, the supervisor falls back to the env bot, and reconcile stops every registry socket — until a person edits `.env.local` and restarts. The panel says only "the old one stops working". | `bots/slack/src/index.ts:110-120`; `supervisor.ts:51-99`; `IntegrationsPanel.tsx:474` | CODE |
| A7 | **The fail-closed runtime door is defeated by an ungated minting route.** `GET /slack-bots/runtime` (raw tokens) requires a key, an org API key or SSO. `POST /slack-bots/supervisor-key` is **not in `POLICY`**, falls to the `resource.write` floor, and RBAC is a no-op without SSO — so on a default install anyone who reaches the port mints a key, reads every bot's plaintext tokens, and (as a side effect) rotates the live key per A6. | `rbac/policy.py:85-95,127-141` (no `supervisor-key` entry); `rbac/__init__.py:9-11`; `routers/slackbots.py:86-98,109-149` | CODE |
| A8 | **Deleting an agent does not cascade.** `bots_for_agent` is documented as "the query an agent-delete cascade needs" and has one caller (recheck). The bot's socket stays open and answers 404. `POST /slack-bots` accepts any `agent_id`, existing or not. | `slackbots/store.py:119-122`; `custom_agents/store.py:361-365`; `routers/slackbots.py:180-192` | CODE |
| A9 | **The supervisor exits if it starts before a bot exists** (`timer.unref()`, no sockets → event loop ends after "No bots to run"). Order matters and nothing says so. | `index.ts:123-145` | CODE, not run |
| A10 | **The README documents the RC-1 single-bot story**, not the RC-5 supervisor; its layout table omits `supervisor.ts` and `registry.ts`. `.env.local.example` ships non-empty placeholder tokens, which `envBot()` turns into a phantom bot on every fallback. | `README.md:55-103`; `index.ts:90-103` | CODE |
| A11 | Only Slack is conversational. Google and Microsoft OAuth are read-only `integration_call`s (no Teams operation exists although the card says "Teams"); webhook and Jira are outbound notifications; **email, Teams, Discord, WhatsApp, Telegram: zero code**. | `integrations/operations.py:163-256`; `notifications/`; grep | CODE |

### B · Creating an agent (where "quick" is decided)

| # | Finding | Evidence | How verified |
|---|---|---|---|
| B1 | **The flow is good where it is honest.** Six steps, one required field (name), creation is free (no model call), the agent lands on its own Overview, and "nothing is created here" is true of the Describe step. The copy is the best in the product ("An agent is a scope and a stance"). | walked live; `CreateAgentFlow.tsx:50-68,190-225` | LIVE |
| B2 | **Starting from a pack silently discards edits.** Define shows instructions "edit freely" and a document list; the template route accepts only `pack_id, name, connection_id, schema_scope`, so edited instructions and ticked documents are dropped — and the flow itself warns that an agent with no documents "sees NO documents at all". That route also skips connection validation and sets no owner. | `CreateAgentFlow.tsx:197-201,466-468`; `routers/agents.py:211-215`; `custom_agents/templates.py:137-143` | CODE |
| B3 | **Lists are not scoped to the chosen connection.** With theLook chosen, Define offers 17 schema documents from every connection and 25 packs including `alloydb-basics` and `bigquery-bigframes`; the Setup tab does the same. The pack note admits binding is "inert until" the pack is pinned — and still offers all 25. | walked live; screenshot | LIVE |
| B4 | **The promised "no evidence" chip does not appear.** Prove says an agent without goldens' "roster chip will say so until it does"; the created agent shows `custom agent · active` and nothing else. Absence is used where the rule requires a statement. | walked live | LIVE |
| B5 | **The Describe step's connection is asked again at Scope**; Back from Scope goes to Start even when the person came from Describe; there is no Back from Start. The docstring still says four steps. | `CreateAgentFlow.tsx:5,168-180,455` | CODE |
| B6 | `purpose` — the field delegation routes on — **cannot be written by any route**; the proposer drafts it and `adoptDraft` drops it. Grants and guardrails cannot be set at creation. | `routers/agents.py:188-208`; `propose.py:250`; `delegate_tool.py:40-46` | CODE |
| B7 | After creation the **only path to Slack is the Reach step or Integrations**; the agent's own page has no Doors tab (`AgentSlackDoor` is mounted in exactly two places, neither on the agent). | grep of mounts | CODE |

### C · What an agent IS at run time (where "quality" is decided)

| # | Finding | Evidence | How verified |
|---|---|---|---|
| C1 | **A custom agent's instructions never reach the default chat body.** `agent_brief_block()` is read by three callers: the inner SQL prompt (`routers/investigations.py:2086` via `agent/grounding.py:58`), the deep-analysis report (`agent/investigate.py:10052`) and the eval (`quality.py:210`). The converse system prompt — the default quick body since SP-14 (`investigations.py:3492`, `_converse_eligible` :5120) — never reads the agent (`converse_tools.py:849-1003`; its only agent reference is the refusal gate at :384). So "Three sentences a non-analyst can act on. Never estimate" shapes the SQL, not the prose. **Live corroboration:** The Look Analyst's only run, asked exactly its question ("What were the sales yesterday?"), ended *"I ran out of steps before reaching an answer (8 tool calls)"*. | cited lines re-read; `GET /agents/custom/ua_aaeb9e07870a/observability` | CODE + LIVE |
| C2 | **Delegation does not run the delegate as itself.** `_run_one` never calls `activate_agent`; the delegate's instructions, documents, packs and PII guardrail are not applied, schema scope is a prose hint, and the response reads `result["answer"]` which `answer_question` does not return (the test stub does). | `agent/delegate_tool.py:154-215`; `tests/unit/test_delegate_task.py:26` | CODE |
| C3 | **The pass chip measures a path production does not use.** The eval runs `CHAT_PROMPT` with document, metric and pack sections empty over the whole connection — so `doc_ids`, `pack_ids`, `schema_scope` and grants mark the chip stale but are never exercised. "goldens 5/5" certifies the SQL prompt, not the agent. | `custom_agents/quality.py:201-241`; `models.py:86-97` | REPORTED, lines read |
| C4 | **Charter governance is mostly display.** `enabled` is enforced only for Explorer and Curator; Responder owns no job kind (`job_kinds=()`), so its enable switch, model pin and spend tile (forever 0) are the "confident 0" the code warns about; `tools` is card text; `reserved` is "wiring soon" on no charter. | `kernel/agents.py:124-132`; `routers/_shared.py:517-549`; `AgenticAgentsPanel.tsx:1301-1302` | CODE |
| C5 | **No external-agent identity.** MCP callers share one API key; identity providers are `slack|web|api|automation|system`; no A2A, no agent card; `HostCapabilities` has no consumer; custom agents cannot call the outbound MCP registry (only automations can). Arc DE's DE-2 already owns the principal half of this. | `mcp/client.py:45-78`; `identity/models.py:41`; `control_plane/contracts/host.py` | CODE |
| C6 | **"Door" means three things** in code: a way to reach an agent, an automation deploy door (`automations/doors.py`), and a SQL gate (`db/doors.py`). | grep | CODE |

### D · The numbers on the screens (where "trust" is decided)

| # | Finding | Evidence | How verified |
|---|---|---|---|
| D1 | **Two tiles, one agent, two truths.** Roster row (24 h): The Look Analyst · 1 run · 76.7K tokens · last run 2026-10-02 11:03. Its Overview tab (same range selected): 1 run · **610 model calls · 3.5M tokens** · most recent run Sep 27. `_agent_spend` reads the all-time usage rollup and the observability route ignores `range` (`?range=24h` returns the identical body). The workspace comment says this is exactly what one shared window was meant to prevent. | `routers/agents.py:539-589`; two live GETs | LIVE + CODE |
| D2 | **Cost is $0.00 on every tile** — Overview "131 calls unpriced — a floor, not a total", agent "some models unpriced", Hub "cost over 7d is a floor". The one model in use (`gemini-3.1-flash-lite`) has no price. The caption is honest; a tile that reads **$0.00** is not — it reads as free. | screenshots; `UsagePanel` | LIVE |
| D3 | **A failed request reads as "nothing here."** Overview chart (`setChart(null)` → "No agent runs in this window"), Overview "Needs you" (`.catch(()=>{})` → "Nothing needs a human"), Roster lists, Automations list ("No automations yet"), agent Runs tab. The repo's rule is "withheld is said, never implied"; these say the opposite. | `FleetOverviewPanel.tsx:114-126,478-484`; `AgenticAgentsPanel.tsx:104-105,562`; `AutomationsPanel.tsx:145` | CODE |
| D4 | **The global range applies to some layers.** Shown on all seven; ignored by Traces, Phases, Automations, Hub, Departures, Attention and the charter page (last 500 jobs, captioned "No runs in this window"). The Usage chart's "click to filter · drag to brush" are no-ops (`onBrush` never passed). | `AgenticOpsWorkspace.tsx:202-204`; `AgenticActivityPanel.tsx:106`; `AgenticAgentsPanel.tsx:1273-1286` | CODE |
| D5 | **The run timeline cannot show what its caption says.** Every entry gets `durationMs: null`, so all bars are equal under "height is duration against the slowest shown (1ms)"; `complete` has no colour so finished runs are grey. | `AgenticAgentsPanel.tsx:639-644`; `RunTimeline.tsx:30-34,85-88` | CODE |
| D6 | **0 of 6 automations name an agent** (`agent_id: ""` on every row). The Map's "The Look - Daily Briefing runs as this agent" is derived from a step's `config.agent_id`, not the automation's. The Automations layer never shows which agent a card runs as, although the field exists. | `GET /automations` live; `web/lib/agentMap.ts:196-216` | LIVE + CODE |

### E · Layers, navigation, copy

| # | Finding | Evidence | How verified |
|---|---|---|---|
| E1 | **"charter" is on screen** — the Roster chip renders the raw kind and the group is headed "Charters · Org". The glossary bans it as a user word; the vocabulary ratchet's comment claims the visible strings say "built-in" (stale, baseline 4). | `AgenticAgentsPanel.tsx:236,337`; `tests/unit/test_vocabulary_ratchet.py:333-338,454` | LIVE + CODE |
| E2 | **Automations needs a connection chosen outside Agent Ops** and offers no picker; Propose silently does nothing without one; Attention, Departures and the Map send a person to the Automations *list*, dropping the automation id. | `AutomationsPanel.tsx:206,739`; `AgenticOpsWorkspace.tsx:189,199,211` | CODE |
| E3 | **Alert rules are fleet-wide only** — the form has no agent field although the type does; channel is a raw "trigger id"; rules cannot be edited. The Map's alert and grant nodes have no Open. | `AgentAlertRulesPanel.tsx:43-47,197`; `AgenticAgentsPanel.tsx:465-468` | CODE |
| E4 | **Hub rows are not clickable** and show raw `conn_id` / `agent_id`; the Stream and trace header show raw agent ids with no link to the Roster. | `HubMapPanel.tsx:146,197`; `ActivityStreamPanel.tsx:172-186`; `TraceExplorerPanel.tsx:451` | CODE |
| E5 | **No help anywhere.** No docs link in any of the 19 files; layer blurbs are hover-only; "charter", "runner", "goldens", "probation", "grant" are never explained; Spotlight is offered in two places (empty Roster, a held departure). | grep `href` | CODE |
| E6 | **`?tab=integrations` opens Home.** The sidebar produces `?tab=operations&layer=integrations`; the natural deep link is not in `VALID_TABS`. | `web/app/page.tsx:1302-1308`; navigated live | LIVE + CODE |
| E7 | Overview's "Needs you" cards label alerts and broken automations "Open automation" and go to Attention; Accept/Reject there are bare buttons while Attention renders the full ProposalCard its own code says is required; Kill has no confirmation and swallows errors; guardrail "Tokens per run" PUTs on every keystroke; Delete agent / Remove golden ignore a failed delete. | `FleetOverviewPanel.tsx:299-312,582`; `NeedsHumanPanel.tsx:142-146`; `AgenticAgentsPanel.tsx:761-764,841-845,1121-1128` | CODE |
| E8 | **First paint on a layer switch is a blank panel** for 2–5 s in dev (Roster blank at 2 s, rendered at 5 s; Attention "Loading…" at 3 s) while every API behind it answers in < 0.4 s (`/control-room/fleet` 0.37 s, `/needs-human` 0.21 s, `/hub/map` 0.18 s). This is Turbopack's first compile of a lazy chunk, not the API — but the `SkeletonRows` loading state did not show. A production build must be measured before this is called a defect. | timed live | LIVE |
| E9 | Design-system: `AutomationsPanel.tsx` carries 11 hex literals (`#f59e0b`, `#fff`), a hand-rolled tab bar and toggle; `AgenticAgentsPanel.tsx` has 154 inline `style={{` and 24 literal font sizes; two tile components (`Tile` vs `StatTile`). The rest is token-clean. | counts per file | REPORTED |

### F · What is tested, and what the green means

- The Slack transport is hermetically tested and the tests are good (streaming, exhibits, cancel,
  reactions, supervisor diffing). **Untested:** `index.ts` (the fallback, the exit-on-zero, the
  env bot), `registry.ts`, the `agent_id` in the `/ask` body, hot reload end to end, who may
  mint the key, the agent-mode manifest against Slack, and both UI components.
- Seven of eight panels have no rendering test; the two that exist cover helpers.
- The delegate test stubs the one key the real path does not return (C2).
- `test_vocabulary_ratchet.py` holds "charter" at 4 with a comment that no longer describes
  the screen (E1).

## 3 · Where Aughor is ahead of the field

This is not a weak surface. Against LangSmith/Langfuse-class consoles and the agent builders
inside Salesforce, Databricks and Microsoft, these are ahead or unusual:

- **Ground truth, not a judge.** A golden is a question **with reference SQL**; the suite runs
  both and compares result sets (`quality.py`). Most platforms grade with a model.
- **Departures and probation.** Every outbound message passes a gate that holds and says why;
  an automation graduates on measured precision (5 marked, ≥ 0.8). No vendor console has a
  "what left the building and why" ledger.
- **Provenance on every number** — tiles open a drawer that names the store and the window;
  "unpriced is a floor, not a total"; "unknown, not zero" copy throughout.
- **Configuration revisions with restore**, guardrails saved apart from configuration, grants
  that only ever *propose*.
- **The Map**: one read-only graph of what an agent is scoped to, what reaches it, what it runs.
- **Spend by call site and by role** (`aughor.agent.tool_loop:run_tool_loop 238K`) — an
  attribution most consoles stop short of.
- **Model-agnostic by rule** (no model id in `aughor/`), free-by-default pins.

## 4 · Against the field

Benchmarks are what these products ship as of this writing; treat the vendor rows as the bar,
not as a spec to copy.

| Capability | The bar | Aughor today |
|---|---|---|
| Put an agent in a channel | Slack-native agents: one install, agent mode, suggested prompts, status while thinking; Copilot Studio publishes to Teams in a click; Dust/Glean: one workspace install serves every assistant | 20 steps, 4 surfaces, a process a person keeps alive, legacy mode (A1–A4) |
| Agent definition reaches the model | Instructions are the system prompt, everywhere the agent speaks | Reaches the SQL prompt and the deep report; not the default chat body (C1) |
| Testing before go-live | Agentforce Testing Center: hundreds of synthetic interactions in parallel, in a sandbox mirroring the data; LangSmith datasets + online evals | 5 hand-written goldens, eval on demand, eval path ≠ production path (C3); no synthetic generation, no rehearsal |
| Learning from use | Databricks Agent Bricks: SME feedback as labelled guidelines → automatic re-optimisation; LangSmith: feedback → annotation queue → dataset → re-eval | §5 |
| One truth per number | Trace consoles: one window, every tile | Range honoured on some layers; all-time vs 24 h on one agent (D1, D4) |
| Operator help | In-product docs, guided first run | None (E5) |
| Doors | MCP, A2A, HTTP, embeddable chat (OpenAI keeps ChatKit while winding down Agent Builder and Evals on 2026-11-30 — a signal that code-first agents with an embeddable surface won, the visual builder did not) | Chat, Slack, HTTP, AG-UI, automation step; no MCP agent door, no embed, no Teams, no email |
| Identity for outside agents | Per-caller principals, scoped keys | One shared API key (C5; Arc DE-2 owns the fix) |

## 5 · Does the agent learn?

A loop is **closed** only if something run N writes is read by run N+1 and changes an input
to the model, a ranking or a gate. Live counts are from the main checkout's stores, read
only, on 2026-10-03.

| Loop | Writes | Reads back into | Status | Live |
|---|---|---|---|---|
| Few-shot memory (`tools/prior_analyses.py`) | `index_answer` on a clean answer and on deep runs | the SQL-writer prompt (`agent/nodes.py:233`); a verdict evicts (`feedback/verdicts.py:118`) | **CLOSED, autonomous** — the one real self-learning loop today | 9 SQL examples · 64 analyses |
| Ambiguity ledger | a probe, a clarify choice, a verdict, a departure owner's answer | priors and the receipt | **CLOSED** and has turned | user resolutions reused 39×, verdict resolutions 7× |
| Exploration → glossary caveats · causal edges · thumbs-up → drill priors | explore / investigate / chat | schema text · plan node · ranking | **CLOSED, autonomous** | — |
| Verdicts → "PAST CORRECTIONS" block (`feedback/priors.py:81`) | `/verify/verdict`, chat fix-it, Slack ✅/❌, departure marks | plan node, quick path, grounding receipt — **connection-scoped**, token-overlap ≥ 0.18 | **CLOSED, human-gated** | **6 verdicts ever** (3 accept · 1 correct · 2 reject, last 2026-08-15); 0 carry `sql_source`; one reject has a blank connection and can never match |
| Departure probation | marks | `set_probation(False)` at ≥ 5 marked, ≥ 0.8 precision | CLOSED in code, **never turned** | 1 mark ever; 3 automations on probation |
| Learned skills (`memory/skills.py`), org intelligence, pack flywheel | a person proposes/promotes | ontology overlay → planner prompt; synthesize prompt | CLOSED, human-gated | 0 skills saved |
| Decision records (`learning/decisions.py`) | every tool pick (tool loop, framing, route) | exports only — no prompt, router or tool choice reads it | OPEN | 702 rows; outcomes `ok`/`unlabeled` only, 0 relabelled |
| Learning exports (sft / dpo / golden) | manual `POST /learning/export` | MI-4's gates (1,000 / 150 / 150) | OPEN by design | sft 0 · dpo 0 · golden 5 · choice 211 |
| Treatment shadow (`judgment/treatment.py`), explorer episodes, finding dismissals, inbox rejections | runs | nothing (flag off / no reader) | OPEN | shadow flag OFF; dismissals 1 line |
| **Autonomy ladder** (`memory/__init__.py` → `memory/trust.py` → `auto_crystallize`) | `record_run` on deep/explore runs | the planner's actions section | **DEAD** — `record_run` reads `grounded`/`all_grounded`/`confidence` from the merged state and nothing writes them (`memory/__init__.py:34`); the module docstring says the ladder "is NOT built yet" while `trust.py` carries its rungs | 1 row, `grounded=None`, 2026-08-13 |
| **Per-agent memory** | — | — | **DECLARED ONLY** (`docs/AGENTIC_ARCHITECTURE.md:37,60`) | — |

Three conclusions:

1. **The platform learns per connection; an agent learns nothing as itself.** No learning store
   carries `agent_id` (grep over `prior_analyses`, `verdicts`, `priors`, `ambiguity_ledger`,
   `memory/`, `learning/` = 0). A custom agent's `last_eval` and goldens are display; its
   verdicts land in the connection's pool, indistinguishable from any other asker's.
2. **The human half is starved, not broken.** The corrections loop works but has seen six
   verdicts in two months; the Slack reaction path posts a verdict with no `sql_source` and a
   connection of `""` while the ask path uses `"workspace"` (`bots/slack/src/aughor.ts:103,351`),
   so a Slack ❌ evicts a memory but never teaches a correction; the message→turn map is in
   memory and lost on restart.
3. **"Self-recursive" has a definition the repo already fixed:** no weights, no online learning
   on live traffic, no `llm_inferred` facts, a label must take both values on real traffic
   before anything reads it. Inside that, the closable loop is: a person's verdict on an
   agent's answer → a lesson the agent reads next time → a golden the agent is measured on →
   a pass rate that moves. Every hop exists; none is joined by `agent_id`.

## 6 · Proposal — Arc AO, "Agent Ops as a product": one sitting to Slack, one truth per number, one closed loop

The arc code is **AO** (nobody types `help ao`). Waves are ordered so that each one is
provable live without the next, and so that the first three cost no model calls.

### AO-0 · Pre-checks (measure the premise)

1. **Prove C1 live** with one quick question to The Look Analyst and the converse prompt
   captured (`obs.prompt_capture`) — one model call, ask first. Falsifier: if the captured
   system prompt carries the instructions, C1 is wrong and AO-1a is cancelled.
2. Build the web app once (`next build`) and time first paint per layer — decides whether E8
   is a defect or a dev artefact.
3. Read the usage store for `gemini-3.1-flash-lite`'s price row — decides whether D2 is a
   missing price or a missing join.

### AO-1 · The stance reaches every body (quality)

- a. `converse_system_prompt` prepends `agent_brief_block()` when an agent is active; the
  analyst tool loop likewise. Receipt: the same question before/after, diffed.
- b. `_run_one` activates the delegate (`activate_agent`), reads `headline`, and the test
  stub returns what the real path returns.
- c. The eval runs the production path — documents, packs, schema scope, grants — so the
  chip certifies the agent, not the SQL prompt. Stale chips re-stamp.
- d. `purpose` writable (create, patch, Setup); the pack path accepts the same body as the
  scratch path (closes B2) and validates the connection.
- e. Agent delete cascades with a receipt: bots disabled and said so, automations' `agent_id`
  cleared and said so, revisions kept (supersede, never delete).
- No flag: these are defects against stated behaviour.

### AO-2 · Slack in one sitting (setup)

- a. **Liveness.** The supervisor POSTs a heartbeat (`/slack-bots/{id}/heartbeat`, every
  reconcile); the bot card and the agent's Map say *listening since …* or *not listening —
  start the supervisor* with the one command. Withheld is said.
- b. **The API owns the process.** Flag `slack.managed_supervisor`: the API spawns and
  restarts `bots/slack` (or runs Socket Mode in-process via `slack_bolt`'s async client —
  decide by a one-day spike), and the installer provisions it. Off by default, byte-identical
  off.
- c. **Agent mode by default for new apps** — Slack no longer lets new apps use the legacy
  view; the manifest adds the events the README lists; the UI exposes the toggle for existing
  bots and warns it is one-way. README rewritten for RC-5.
- d. **One token, not three.** A Slack *configuration token* lets Aughor call
  `apps.manifest.create` and `apps.manifest.update` itself; the person pastes one token and
  clicks Install. (On HTTPS deployments the OAuth "Connect" card can do the install.)
  Falsifier: if Slack's config-token flow still requires the app-level token to be generated
  by hand, the win is three → two, and the plan says so.
- e. **Key regeneration with a grace window** (old key valid for N minutes, both served);
  `POST /slack-bots/supervisor-key` enters `POLICY` as `ADMIN_MANAGE_ORG`; a test asserts who
  may mint.
- f. Optional channel binding on the record so a bot can be told where it may answer.
- Measure: **time from "Create agent" to a Slack answer on a fresh install, one person,
  no terminal** — target under five minutes and one hand-off; today 20 steps and four.

### AO-3 · One truth per number (trust)

- Every tile reads the shared range or says "all time" on its face; the observability route
  takes `range`; the charter page reads the window it captions.
- A failed fetch renders *could not read X — retry*, never an empty state (D3's five sites).
- An unpriced model renders **unpriced**, not `$0.00`; the price table gains the model in use
  or the tile links to Settings → Models.
- Run timeline bars carry duration; `complete` has a colour.
- "charter" → "built-in" on screen; the ratchet comment made true, the baseline falls.
- A test per rule: a fetch that rejects must not produce the empty-state string.

### AO-4 · The agent's own page is the whole agent (layout)

- Tabs: Overview · Runs · **Doors** (chat, Slack with liveness, automations that run as it,
  HTTP, MCP — each with its state and a button) · **Alerts** (rules scoped to this agent;
  the form gains `agent_id`) · Quality · Spend · Setup.
- A connection picker inside Agent Ops; every "Open automation" carries its id; Hub rows and
  every raw id are links.
- `?tab=integrations` and every layer/tab become addressable deep links.
- A "?" on each layer that opens Spotlight on the arc's help topic; the six words explained
  once (glossary on screen).

### AO-5 · Doors ×10 (reach)

In order of evidence that someone asked: **MCP** — each custom agent exposed as a tool and a
caller a principal (with DE-2) · **HTTP + embed** — a per-agent key and an embeddable chat
widget · **Teams** — the Microsoft grant already exists; a Bot Framework channel is the first
non-Slack conversational door · **inbound webhook as conversation** · **A2A** last.
Email stays refused unless HB's "no email in either direction" is reopened by the user.

### AO-6 · A testing centre (prove)

- Synthetic questions drafted from the catalogue and the agent's purpose (one model call per
  batch), certified by a person with SQL before they count — the goldens rule holds.
- A nightly eval per agent with a diff against the last stamp; a config change re-runs it.
- "Rehearse": a bot answers in a private thread first; promotion to a channel is a click.

### AO-7 · One closed learning loop per agent (self-recursive, inside the invariants)

No new store — the verdict store IS the lesson store (one store per concept).

- a. **Verdicts carry `agent_id`.** The chat, Slack and departure paths stamp it from the
  turn's history record; `build_corrections_section` reads (connection, agent) first, then
  connection. The agent's brief gains a bounded "what people corrected" block. Provenance is
  the person's verdict; a later verdict supersedes with history.
- b. **Slack verdicts are whole.** `record_verdict` backfills `connection_id`, `headline` and
  `sql_source` from the turn's record when blank (as `_accept_chat_answer` already does);
  the bot's verdict connection fallback matches its ask fallback; the message→turn map is
  persisted. Live only once the owner grants `reactions:read` (TJ-4 as is).
- c. **Accepted answers become golden candidates.** A ✅ or thumbs-up on an agent's answer
  places (question, the SQL that ran) on the agent's Quality tab as *uncertified*; a person
  certifies it, and only then does it count — the reference-SQL rule holds.
- d. **Re-evaluation closes the loop.** A config change or N new verdicts re-runs the
  production-path eval (AO-1c); the agent page shows *learned 3 corrections · 2 goldens
  certified from use · pass 7/8 → 8/8*. That delta is the receipt.
- e. **The dead ladder: decide, then do one of two things.** Either `record_run` derives
  `grounded` and `confidence` from what runs carry (the verification manifest for explore,
  `learning/reward.run_label` for deep) and a crystallised skill is **staged to the inbox**,
  never auto-saved (HB: propose, never execute) — or the ladder's reader side is removed and
  the docstring made true. The user chooses; the study recommends staging.
- Falsifier: per agent, a held-out golden set's pass rate must move after corrections. Two
  weeks of real use without movement → the block is removed, not kept.

### Order and cost

AO-0 → AO-1 → AO-3 → AO-2a,e (no model calls, no new processes) → AO-4 → AO-2b,c,d →
AO-6 → AO-7 → AO-5. The first three waves are defect repair against stated behaviour and need
no flag; AO-2b, AO-6 and AO-7 ship behind flags.

### Falsifiers

- AO-0.1 fails → AO-1a cancelled.
- AO-2 measure not under ten minutes on a fresh clone with the managed supervisor → the
  in-process Socket Mode spike is wrong, and the plan reverts to "spawn and watch".
- AO-7's loop must move a golden pass rate on a held-out set; if it moves nothing in two
  weeks of real use it is removed, not kept.

## 7 · Not to take

- A visual agent builder as the primary authoring surface (OpenAI is retiring its own).
- An LLM judge as the certification of a golden — reference SQL stays the rule.
- Executing grants: an agent proposes; a person acts (VA-9c, unchanged).
- A Slack Marketplace listing before AO-2d is proven on two workspaces.
- Email as a door (HB refusal stands until reopened).

## 8 · Evidence ledger

**Live, this deployment (2026-10-03):** seven layers opened; agent tabs opened; Create flow
walked with a throwaway agent (created 201, deleted 200, 404 after); Reach step rendered with
manifest; Integrations → Slack read; `GET /agents`, `/agents/custom`, `/slack-bots` (secrets
masked), `/hub/map`, `/automations`, `/departures/summary`, `/control-room/needs-human`,
`/control-room/fleet?range=24h`, `/agents/custom/{id}/observability` with and without `range`;
endpoint timings; `ps` for the supervisor; `?tab=integrations` navigation.

**The Slack friction ledger (fresh install → one answered @mention):**
1 `./start.sh` [terminal] · 2 Create agent → Reach [UI] · 3 name + Generate JSON [UI] ·
4 Copy JSON [UI] · 5 `apps?new_app=1`, From a manifest [api.slack.com] · 6 pick workspace,
JSON tab, paste, create [api.slack.com] · 7 Install to Workspace, consent [api.slack.com] ·
8 copy xoxb [api.slack.com] · 9 paste [UI] · 10 copy signing secret [api.slack.com] ·
11 paste [UI] · 12 App-Level Tokens → generate with `connections:write`, copy xapp
[api.slack.com] · 13 paste, Create Slack bot (Slack must be reachable for `auth.test`) [UI] ·
14 Integrations → Slack → Supervisor key → Generate, copy the one-time line [UI] ·
15 `cp .env.local.example .env.local` [terminal] · 16 paste the key, delete the placeholder
`SLACK_*` lines [.env] · 17 `npm install` [terminal] · 18 `npm run dev`, keep it alive, and
only after 13–14 or it exits [terminal] · 19 `/invite @app` [Slack] · 20 @mention [Slack].
Optional and UI-less: agent mode (`curl` the manifest with `agent_view=true`, `POST` with
`agent_view: true`, add four events by hand).

**Read, not run:** A6, A7, A9, B2, B5, B6, C2, C3, C4, D3–D5, E2–E4, E7, E9, and the four
audits' claims not repeated here.

**External:** Slack's 2026-08-20 changelog on `assistant_view` → `agent_view` (retirement
February 2027, one-way, closed to new apps); OpenAI's notice winding down Agent Builder and
Evals on 2026-11-30 with ChatKit retained; Salesforce Agentforce Testing Center; Databricks
Agent Bricks. Dates as published; capability descriptions summarised, not quoted.
