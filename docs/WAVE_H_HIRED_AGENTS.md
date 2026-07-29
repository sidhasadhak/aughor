# Wave H — Hired agents (agents-as-product) · scoped 2026-07-29

The product statement: **"hire an analyst — create an agent in the UI, point it at your
data, give it golden questions and a schedule, and watch its measured runs."** Disposition
#1 of `MASTRA_STUDY_2026-07-29.md`. The letter H (hire) is unused by prior waves
(A C E G K L N O Q R S V taken).

The strategic frame: Mastra licenses UI-based agent creation as Enterprise ("Agent
Builder"); our agents are **data rows, not code**, so this ships in the open product.
Their OSS Editor tier (instruction overrides, versioned) is the ceiling we clear at H6.

## 0. The pre-check (what already exists — verified in code, 2026-07-29)

The wave is **composition, not construction**. Measured premises:

- **UserAgent is already a product object**: `aughor/user_agents/models.py` — id, name,
  instructions, `connection_id`, `schema_scope`, `doc_ids`, `pack_ids`, owner, enabled,
  **`last_eval`** (the pass chip). Flag `agents.user_defined`.
- **Quality is already measured, not vibes**: `user_agents/quality.py::evaluate_agent` —
  goldens `{question, reference_sql}` authored by the creator, generated vs reference SQL
  compared **deterministically** (no LLM judge), ≤20 goldens/run, chip stamped on the
  agent. CRUD + goldens + evaluate routes live in `routers/agents.py`; the UI builder
  exists (`web/components/AgentsAdminPanel.tsx`, 414 L, incl. goldens editor).
- **The ask door already takes an agent**: `AskRequest.agent_id`
  (`routers/investigations.py:723`); `_resolve_ask_agent` (`:3819`) and
  `_apply_agent_bindings` (`:3836`) enforce connection/schema binding **fail-closed**
  (explicit conflict = 409, never a silent override); deep runs persist the persona and
  resume re-reads it (`_persona_for_investigation`).
- **Scheduled investigations already run on the real answer path**:
  `automations/engine.py::_dispatch_investigate` drains `build_ask_stream` at
  `depth="deep"` in-process, submitted via `submit_background_tick` as a supervised,
  metered kernel job with an idempotency key. `automations.engine` is default-ON
  (graduated, receipt `65364174a172`).
- **The one missing joint is one field**: `_dispatch_investigate` builds
  `AskRequest(question, connection_id, depth, schema_name)` — **no `agent_id`**.
  `EFFECT_REQUIRED["investigate"] == ("question",)` (`automations/models.py:95`).
- **The structural debt is named in place**: kinetic's `trigger_investigation` branch
  still raises (`kinetic/executor.py:200–202`); pointing it at the automations runner
  would invert the wave dependency (A depends on K) — the docstring at
  `automations/engine.py:318` records that closing it means lifting the runner into a
  module neither package owns. Standing item (chip `task_401e3882`); NOT small.

## 1. The items

| # | What | Composes |
|---|---|---|
| **H1** | **The schedule joint**: `Effect{kind: investigate}` accepts optional `agent_id`; `_dispatch_investigate` passes it through `AskRequest` so the drained ask activates the persona (instructions, doc/pack scope, bindings). A binding conflict between `automation.conn_id` and the agent's `connection_id` surfaces as the authored 409 message in the run history — verbatim, the K2 pattern. Idempotency key gains the agent id. | A (engine), user_agents |
| **H2** | **Attribution** *(shipped as PR #235 — re-scoped by its pre-check)*: the answer receipt carries `agent: {id,name} \| null` inside the signature, and `GET /usage` gains an `agent_id` axis. The axis was a *reporting* gap, not plumbing — the persona contextvar already stamped every session event; the measured 0% meant "never exercised", not "never written". **Deliberately NOT the kernel job row**: its `agent_id` is the fleet *charter* (what kind of platform work ran), not the persona (whose agent asked) — overloading one field with both would misattribute the Fleet view and budget resolution. Runs count against the Analyst charter's budget until per-agent caps earn their keep. `unattributed` bucket stays honest. | G3, trust/receipt |
| **H3** | **The per-agent run view**: grow `AgentOverviewPanel.tsx` (145 L) into the operating slice — run list from **existing stores only** (receipts filtered by the H2 stamp, `automation_runs` targeting this agent, job rows), the pass-chip trend, spend. No new store (J10/J12). | H2, S-wave rendering rules |
| **H4** | **Create-from-template — the customer analyst** *(shipped — the original scope was FALSIFIED by its pre-check)*: "seeded as goldens, born measured" is impossible and must not be faked — `reference_sql` is NOT NULL and graded by execution; a pack's evals are behavioural expectations with no SQL; its formulas carry `{{role.*}}` placeholders only resolvable per connection; the only fill would be the model writing the suite that grades itself. Shipped instead: `GET /agents/templates` + `POST /agents/custom/from-template` — the pack's stance becomes the instructions, the pack stays **bound by id, never absorbed**, and its questions return as `suggested_goldens` that each state what they still need (reference SQL). A hire is born with a stance and **no pass chip**; the UI carries the suggestions into the golden editor. `skills/*.md` seeding (§5.2) rides whenever a pack first ships skill docs. | packs, user_agents/templates |
| **H5** | **The neutral runner** (structural): lift the in-process ask-drain out of `automations/engine.py` into a module neither A nor K owns (kernel-adjacent, e.g. `aughor/runners/`); both `_dispatch_investigate` and kinetic's `trigger_investigation` branch call it. Requires the three deferred decisions: risk tier (read-path analysis but spends LLM budget → LOW + metered), async submission (via `submit_background_tick`, same as today), and receipt (the investigation's own receipt id returned in the `EffectOutcome` / kinetic result). Closes chip `task_401e3882`. | K4, A, kernel |
| **H6** | *(optional)* **Instruction versioning**: revisions table **inside `agents.db`** (not a second store) — `{agent_id, rev, instructions, at, author}`; patch = new revision; restore endpoint. The Mastra-Editor lesson: non-technical iteration with every change versioned. | user_agents/store |

## 2. Pre-registered gates

- **H1**: an automation with an agent-bound investigate effect fires on schedule; the
  resulting deep run answers **as** the agent (its instructions and doc scope visibly in
  the receipt); flag off ⇒ byte-identical engine behaviour.
- **H2**: `GET /usage` returns a per-user-agent slice with explicit
  `unattributed`/`coverage`; the receipt for an H1 run carries the agent id.
- **H3**: the per-agent view renders runs and spend **without any new store or endpoint
  that duplicates an existing store's answer**.
- **H4**: creating from the customer-analytics template yields an agent whose seeded
  goldens evaluate and stamp a pass chip with zero hand-authoring.
- **H5**: kinetic `trigger_investigation` executes end-to-end through the neutral runner;
  A and K both call it; neither imports the other (boundary test alongside Invariant #8);
  the kinetic result carries the investigation's receipt id.
- Live-path proof before "done" on every item (leverage-gate law): one real scheduled
  fire shown, not just green tests.

## 3. Joints and laws in force

- **J9** — any default flip (e.g. if H1's flag graduates) cites a `GraduationDecision`.
- **J10/J12** — no second queue, no second results store; H3 is a *view*.
- **J14** — measured-over-declared: templates are born with goldens; the pass chip is
  the number, popularity is not evidence.
- **Effect law** (`automations/models.py:103`) — H1 adds a *parameter* to an existing
  effect kind, never a new action type.
- **G5 trim** — agent doc/pack retrieval already flows the ask path; H1 introduces no
  new retrieval surface, H3/H4 must not either.
- New routes ⇒ regenerate `web/lib/api.gen.ts` (`cd web && npm run gen:api`), or the
  codegen-drift gate fails.
- One new flag for the joint (default-OFF, off = byte-identical), riding
  `agents.user_defined` ∧ `automations.engine` at dispatch time.

## 4. Sequencing & effort

**H1 → H2 → H3** is the product loop (schedule → attribute → see) — ~2–3 PRs, each
independently shippable. **H4** rides once H1 lands (~1 PR). **H5** is parallel,
design-first (~1–2 PRs; the decisions above are the design). **H6** last, optional (~1 PR).

Relation to Wave S: **H is the organizing concept for the S1–S3 design pass** — S1's
listing pages get "your agents" as a first-class object, S2's answer anatomy renders the
receipts H3 lists, S3's accuracy-per-connection number generalizes the pass chip. H does
not block on the design pass; it feeds it.

## 5. Dispositions from the 2026-07-29 Q&A (recorded so they aren't re-litigated)

### 5.1 Context documents for agent RAG — already built; zero H work

The whole pipeline exists and is live on the answer path: upload accepts
**`.pdf` / `.docx` / `.md` / `.txt` / `.markdown`** (`routers/knowledge.py:24`; PDF/Word
via the `.[docs]` extra) → parse + chunk with provenance incl. connector `source_url`
(`knowledge/documents.py`) → Qdrant `aughor_documents` + the `data/documents.json`
registry (`knowledge/indexer.py`) → **fail-closed per-agent scoping at retrieval time**
(`indexer.py:267` via `agent_doc_ids()`: an active agent sees only its bound docs; an
agent with none bound sees none). H1's scheduled runs inherit this automatically because
persona activation sets the doc scope.

Tracked, deliberately **not** built until a measured need: doc ownership/ACL (today the
registry is workspace-global and agent binding is a scope filter — private docs = an
owner field + the G5 trim) and retrieval reranking (fixed chunking + vector search is
the current truth; adopt a reranker only when answer-quality measurement demands it).

### 5.2 Markdown skills — a document with a role, not a new system

A prose skill is a registry document with `kind="skill"` (the chunk model's existing
discriminator: `""` uploaded · `"schema_doc"` generated). Same upload endpoint, same
index, same `doc_ids` binding. **The design point is injection, not storage**: a bound
skill rides the prompt deterministically (size-capped, alongside instructions) rather
than being similarity-retrieved — an agent's methodology must not have to win an
embedding lottery against each question; oversized skills degrade to scoped retrieval.
Packs may ship `skills/*.md` so H4's template agents are born with methodology, not
just goldens.

The boundary that stays sharp — three skill-shaped things, deliberately distinct:
**learned skills** (`memory/skills.py`) are executable parameterized SQL, EXPLAIN-gated,
propose→confirm→save; **playbooks** (`playbook/models.py`) are typed
trigger→intervention entries with measured success rates and version receipts;
**markdown skills** are guidance that steers and never executes. Prose never crosses
into execution except through the existing gates.

### 5.3 Outbound connectors — extend the Action Hub, never per-agent credentials

Slack / generic webhook / Jira triggers already exist workspace-globally
(`actions/models.py`: secrets encrypted at rest with auth-header auto-detection,
masked in responses, SSRF-guarded URLs); briefs already deliver through them, and
agents reach them via the `notify` effect by `trigger_id`. Email/SMTP = a new trigger
*type* in the same registry when asked for. Before widening outbound reach, verify
`govern/disclosure` applies to outbound payloads — a Slack message is an exfiltration
surface like any query result.

### 5.4 No watcher agent — checking is a deterministic plane, a judge is a scorer

Budget enforcement (kernel heartbeat), logging (`llm_call` written on entry),
attribution (metering → receipt), and periodic reporting (the S4 digest — assembled,
never generated) already cover the "background agent" jobs deterministically. Any
future LLM review of agent output enters as a **scorer in the eval plane** — sampled,
measured, receipted — never a free-floating watcher.

### 5.5 Agent-as-code — a J15 view, never a parallel store

If agents ever need git review, the shape is an O7-style bundle: the same rows
(instructions, goldens, bindings) exported and re-imported as YAML — a view over
`agents.db` and the documents registry, never a markdown-folder source of truth.
