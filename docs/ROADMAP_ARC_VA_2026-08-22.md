# Arc VA — the agent platform (2026-08-22)

> **Status: APPROVED and IN FLIGHT (2026-08-22).** Supersedes §4 and §8 of
> `VOLTAGENT_ADOPTION_STUDY_2026-08-22.md` as the build document.
>
> | wave | state |
> |---|---|
> | VA-0 Agent Ops control room | ✅ **shipped** — #371 |
> | VA-5 trace waterfall | ✅ **shipped** — #372 |
> | VA-6 agent-plane alerting | ✅ **shipped** (rule engine) — #373 |
> | VA-2 delegation | ✅ **shipped** — #376 |
> | VA-1 skills plane | ✅ **shipped** — #377 (deliverables 4–5 outstanding) |
> | VA-5 node view | ✅ **shipped** — #380 (payload inspector · trace logs · feedback · trace API · replay outstanding) |
> | VA-3 · VA-7 · VA-8 · VA-9 · VA-10 | planned below |
> | VA-4 automations dataflow | parked (see §2) |
>
> Three §4 decisions are LOCKED by the user; the rest remain open.
> **Thesis:** Aughor's warehouse/AI-BI half is a moat VoltOps does not have. VoltOps's
> platform half is operability Aughor does not have. Arc VA builds the second without
> diluting the first — same Python brain, same one app.

---

## 0 · What this arc is for

Today Aughor is a data intelligence product with agents inside it. Arc VA makes it a
**platform people log into to build agents**: users define agents, connect them to their
apps, and admins see everything those agents do. Three sentences that bind every wave:

1. **A user builds the agent** — instructions they version, tools they grant, apps they
   connect, guardrails they set.
2. **The platform runs it honestly** — every hop traced, every cost attributed, every
   guard decision a span.
3. **An admin can answer "what happened"** for any run, any user, any day — without
   reading logs.

**Not in scope, permanently:** a second runtime in Node (guards are the product and live
in Python; Aug-12 one-app decision); dependence on VoltOps cloud; a workflow canvas
(ReactFlow verdict stands — VA-4 is engine semantics, not UI); re-litigating NL2SQL
machinery (concluded 4×).

---

## 1 · What is true today (measured 2026-08-22 — do not re-derive)

| Substrate | State | Consequence for the plan |
|---|---|---|
| `session_events` | 8,184 rows; columns include **`span_id`, `parent_span_id`**, `duration_ms`, `at`, `trace_id`, `payload`, token counts, `role`, `fallback`, `job_id`, `charter_id`, `org_id`, `user_id` | **The waterfall tree already exists in data.** VA-5 is a rendering + API problem, not a schema problem |
| `telemetry.py` | Imports OTel SDK + OTLP HTTP exporter (~line 126); Langfuse *attribute conventions* on spans; Langfuse **SDK backend silently dead** (v2 API vs 4.7.1) | VA-3 is finishing a half-soldered wire + a deletion, not new plumbing |
| `custom_agents/revisions.py` | **Complete**: `record_revision` (fires on every `update_agent`), `list_revisions`, `revision_config(agent_id, version)` | **VA-7's versioning substrate is live.** What's missing is labels, approval, diff UI, eval-on-change |
| `platform_tools.py` | 14 tools, closure-bound, `platform_tools(connection_id, *, session_id)` → `list[ToolSpec]` | VA-2 adds tool #15 at one seam |
| `UserAgent` | id, name, instructions, connection_id, schema_scope, doc_ids, pack_ids, owner, enabled, last_eval | VA-2 needs one field (`purpose`); VA-8 needs one (`guardrails`) |
| `automations/engine.py` | `OUTWARD_EFFECT_KINDS = {"notify","brief"}`, delivery claim/dedupe, retry, fallback; **effects run as an independent list comprehension (`:581`) — no effect consumes another's output** | VA-6 reuses the delivery path as-is. VA-4 (parked) is the dataflow fix |
| `govern/` | `usage_caps` (`UsageCap`, `CapDecision`, `effective_limit`), `cap_store`, `disclosure`, `lineage`, `tags`, `actions` | VA-8 built-ins ride these, not new code |
| `secretvault.py` | Fernet `encrypt_secret`/`decrypt_secret`/`mask_secret`/`is_masked` | VA-9 credential store is a schema on top, not new crypto |
| `org/context.py` | `current_org_id()` **and** `current_user_id()` contextvars | VA-10 has its tenancy spine already |
| `mcp/` | Server (30 tools) + `client.py` = **an HTTP client for Aughor's own API**, not a generic MCP client | ⚠️ **VA-9 must BUILD a generic MCP client** (stdio/SSE) to consume Gmail/Slack servers |
| Approvals | `routers/kinetic.py` proposals plane, `list_proposals`, review inbox | VA-7 approval + VA-9 tool grants reuse it |
| Agent Ops | Built, 11 commits, **unpushed**: Overview·Roster·Attention·Activity·Runs, shared range, provenance drawers | VA-0 |

---

## 2 · The waves

### VA-0 — Ship Agent Ops ✅ SHIPPED (#371)

**Goal:** the chassis every later wave bolts onto exists on `main`.
**Deliverable:** merge the 11-commit branch (control room, the 43%-undercount fix,
`JOB_READ_LIMIT`, content-only contrast).
**Receipt:** CI green; the live browser check that was interrupted — panels painting
against the real store with `AUGHOR_CORS_ORIGINS` set.
**Risk:** none new; the work is gate-verified.

---

### VA-1 — The skills plane (≈1 week)

**Goal:** turn the 1,497-skill MIT library (`awesome-agent-skills`, Anthropic SKILL.md
format) into Aughor content, and load skills only when relevant.

**Seams:** `packs/` (pack.yaml + expertise.md + entities/metrics/questions/evals — **1
pack on disk today**); `packs/intake.py` (`known_pack_ids`, `load_pack`); the converse
tool loop's system-prompt assembly.

**Deliverables**
1. `aughor/skills/ingest.py` — SKILL.md → pack: YAML frontmatter `name`/`description` →
   `pack.yaml`; body → `expertise.md`; `source: awesome-agent-skills` + upstream URL +
   licence recorded. No entities/metrics/goldens ⇒ an **honest partial pack**, flagged as
   such in the UI (never a confident-looking empty pack).
2. **Ingestion linter, blocking** — refuses a skill carrying a hardcoded model id (the
   existing ratchet's rule), a credential-shaped literal, or instruction-injection
   patterns ("ignore previous instructions", "disregard your guards"). Skills are
   untrusted third-party prose; this is the security boundary of the wave.
3. `aughor skills import <path|url>` CLI + a review screen (diff of what will be created).
4. **Progressive disclosure**: skills load into the prompt by description match at need,
   client-side. Deliberately NOT AI SDK 7's `uploadSkill` (Anthropic/OpenAI provider-
   managed only — dead on the free ladder).
5. Seed import: the ~15 data-engine skills (DuckDB first — we run it), then
   ClickHouse/Tinybird/Neon, each reviewed.

**Receipt:** import DuckDB skills; ask a question whose answer measurably improves with
the skill loaded vs not, on the same model, same seed; show the prompt-token delta.
**Risks:** prompt bloat (measure per PE discipline — a skill that adds 800 tokens and
changes nothing is a regression); licence hygiene per skill.

> **BUILT 2026-08-22** (deliverables 1–3; 4 and 5 remain). `aughor/skills/ingest.py`
> plans and writes; `aughor skills lint|import` drives it; 26 tests.
> 🔑 **The honest-partial rule turned out to be the whole design.** Writing the missing
> layers as EMPTY files produces a pack that LOADS — a specialist every surface reports
> as real that knows nothing, because an empty structure and an unpopulated one are
> indistinguishable once written. So absent layers stay absent, the manifest carries
> `partial: true`, and everything lands `status: draft` (which `active_packs()` already
> filters on — the existing gate, not a second switch).
> 🔑 **Provenance had to reach `PackManifest` itself** — `_Base` sets `extra="ignore"`,
> so `source`/`licence`/`partial` written to pack.yaml and absent from the model vanish
> silently on load: the pack keeps its prose and loses its origin.
> ⚠️ **Slug collisions are real, and measured:** a sweep of 28 live SKILL.md files gave
> `access` ×3 and `configure` ×3 from three plugins. Bulk import (decision ②) hits that
> on the third file — hence `--namespace`. Refusing to clobber stays the default.
> ⚠️ **URL import deliberately NOT built.** Fetching untrusted prose over the network is
> a different risk surface from reading a file the user already put on disk; it wants its
> own allowlist and review path. The command says so rather than faking support.
> ⏭️ Outstanding: progressive disclosure (deliverable 4) and the seed import (5).

---

### VA-2 — Delegation (≈1–2 weeks) — *the biggest single gap*

**Goal:** custom agents stop being records an ask *impersonates* and become specialists
the conversation *delegates to*.

**Seams:** `platform_tools.py:478` (`platform_tools()` returns the roster);
`converse_tools.py:378`; `UserAgent`; `kernel/agents.py` (7 charters); CA-1 parts pipeline.

**Deliverables**
1. **`purpose` field** on `UserAgent` (+ charters) — short routing description.
   ⚠️ The supervisor roster block uses `purpose`, **never** full instructions (we measured
   65% prompt waste once; do not reintroduce it through delegation).
2. **`delegate_task` as platform tool #15** — args `task`, `target_agents[]`, optional
   context. **Always returns an array** of `{agent_name, response, usage, bailed}` even for
   one target (parallel fan-out later without an API break).
3. **Loop bound** `max_steps = 10 × len(targets)`, and **bail-on-handoff**: when a
   sub-agent's output is final, skip the supervisor's synthesis round.
4. **Sub-agent events as parts** — `{sub_agent_id, parent_agent_id, agent_path}` on
   providerMetadata; forward **only** `tool-call`/`tool-result` by default (forwarding
   text-deltas doubles every token through SSE).
5. Delegation respects the delegate's own scope: `connection_id`, `schema_scope`,
   `doc_ids` — a delegate cannot read wider than its own definition.
6. Guards: a delegate's answer passes the CA-0/CA-2 evidence guards before it reaches the
   narrator, exactly as a direct answer does.

**Receipt:** live, in chat — ask a question requiring two specialists; both hops appear as
parts, both scopes hold, `agent_path` is right, and the transcript shows the supervisor
did not restate the delegate's answer when it bailed.

> **BUILT 2026-08-22 — deliverable 4 completed.** 🔑 **The hop was ALREADY streaming, and
> that was the bug:** `delegate_task` handed the parent's `emit` straight down, so a
> delegate's SQL and receipts landed in the supervisor's stream looking like the
> supervisor's own work — a query nobody in the conversation appeared to have run.
> `delegated_emit` stamps every forwarded frame with
> `{sub_agent_id, sub_agent_name, parent_agent_id, agent_path, depth}`, taken from the
> SAME `agent_path` the cycle check authorises on, so the tree the UI draws and the tree
> the runtime refuses cannot disagree.
> 🔑 **`sql` is last-write-wins in the projector**, so a delegated frame had to be routed
> BEFORE the turn's own projector — there is no correcting it afterwards. Each hop gets a
> scratch `ChatTurn` projected by the SAME `PART_PROJECTORS`, so no new part name, no
> change to the closed `data-*` map, nothing for the frame-parity gate to learn.
> ⚠️ **A new frame name emitted from `delegate_tool.py` would ESCAPE the parity gate** —
> `test_sse_frame_parity` reads only `investigations.py`. Attribution rides existing
> frames precisely to avoid that.
> ⚠️ **A suppressed frame is a cancellation checkpoint not taken** — the parent `emit`
> doubles as that checkpoint and `answer_question` takes no `cancelled` callable. Bounded
> to one hop, and it is the property `_CONVERSE_SUPPRESSED` already has. The real fix is
> threading `cancelled` down the converse tool seam, which fixes `answer_question` and
> `deep_analysis` at the same time.
> 🗣️ **One product question left open, deliberately:** a delegate's guard receipts do NOT
> pool into the supervisor's evidence list — they render under the agent that produced
> them. Whether the supervisor's evidence should include them is the user's call.
**Risks:** recursion (a delegate delegating) — bound depth at 1 for this wave and say so;
cost multiplication (each hop is a full turn) — surface it in the run's cost.

---

### VA-3 — OTLP standardization (≈3–4 days)

**Goal:** one telemetry contract, any backend. **BYO-observability — the twin of BYOK.**

**Deliverables**
1. **OTel GenAI semantic conventions** on `session_log` spans (`gen_ai.system`,
   `gen_ai.request.model`, `gen_ai.usage.input_tokens`, …) alongside the keys we already
   emit.
2. **Delete the dead Langfuse SDK backend** (v2 API against 4.7.1 — silently dead;
   removing it is the honest move, and the Langfuse *attribute* conventions stay).
3. `AUGHOR_OTLP_ENDPOINT` (+ headers) as config; ship **off** by default (pure local),
   on when set. ✅ **LOCKED by decision ④.** Langfuse / VoltOps / Grafana / Jaeger all become "point it here".
4. **This closes §7.5's LF-2/LF-3 topology question** — it collapses into "where does the
   endpoint point".

**Receipt:** run a Jaeger (or otel-collector) container, drive one deep analysis, show the
trace tree with model calls, tool calls and token counts on the spans.
**Risk:** span volume/cost — sample by default at the collector, not in our code.

---

### VA-5 — Trace excellence (≈2 weeks) — ✅ FIRST SLICE SHIPPED (#372: waterfall + timeline API + UI)

**Goal:** the debugging surface VoltOps is genuinely ahead on. **The tree already exists in
`session_events` (`span_id`/`parent_span_id`/`duration_ms`) — this is rendering + API.**

**Seams:** `routers/obs.py:59` (`/traces`), `:91` (`/traces/{trace_id}`);
`TraceExplorerPanel.tsx` (340 lines, flat list); `agentops/RunTimeline.tsx`.

**Deliverables**
1. **Waterfall view** — spans on a time axis, nested by `parent_span_id`, coloured by kind
   (model / tool / phase / guardrail), with duration bars and the critical path marked.
2. **Node view** — the run as a graph. *Gated on VA-2*: hops only exist once delegation
   does. (A run DAG has real edges — this is not the refused creation-canvas.)
3. **Payload inspector** — full input/output per span, redaction-aware, with a
   copy-as-JSON.
4. **Trace logs** — log lines correlated by `trace_id` beside the tree.
5. **Trace feedback** — thumbs + note on a trace, keyed to `trace_id` + `user_id`; feeds
   evals. **This unblocks what OA·LF-2 was stuck on (identity attribution).**
6. **Public Trace API** + **trace tools on `aughor/mcp/server.py`** — a coding agent
   (Claude Code) can pull and inspect a run. Strong story, small surface.
7. Session replay — step the run forward from `session_events` order.

**Receipt:** take a real 5-phase deep analysis; open its waterfall; identify the slowest
span; open its payload; leave feedback; then fetch the same trace through the MCP tool.
**Risks:** 8k+ spans/trace on big runs — virtualize and page by span, never load whole;
payload redaction must reuse `govern/disclosure`, not a new redactor.

---

### VA-6 — Agent-plane alerting (≈1 week) — ✅ RULE ENGINE SHIPPED (#373); storage, trigger wiring and the Attention panel outstanding

**Goal:** alerts on **agent behaviour**, not just data KPIs. Both halves exist and point at
the wrong plane.

**Seams:** `routers/monitors.py` + `aughor/monitors/`; `automations/engine.py`
`OUTWARD_EFFECT_KINDS = {"notify","brief"}` with delivery claim/dedupe/retry (OA·N8-0).

**Deliverables:** alert rules over agent telemetry — error rate, p95 latency, token burn,
cost/hour, run failure streak, **guardrail-block rate** (from VA-8), queue depth — with
thresholds per agent or fleet-wide; delivered through the existing outward path
(Slack/email/webhook); alert state visible in Attention.
**Receipt:** force an agent to fail 3× in a window; the alert fires once (not per failure —
the dedupe claim is the point), lands in Slack, and shows in Attention.
**Risk:** alert storms — reuse `claim_delivery`, and make the *first* rule shipped a
rate-limited one so the storm case is exercised on day one.

---

### VA-7 — Instruction & prompt management (≈1–2 weeks)

**Goal:** users edit and version what their agents say, safely. **`revisions.py` already
does the hard half.**

**Seams:** `custom_agents/revisions.py` (`record_revision`/`list_revisions`/
`revision_config`); `store.py:170` `update_agent`; `AgenticAgentsPanel` renders `v{n}`
history; `routers/kinetic.py` proposals.

**Deliverables**
1. **Draft / live labels** on a revision (the dev-vs-prod idea, in our vocabulary).
2. **Diff view** between any two revisions; one-click restore (`revision_config` exists).
3. **Approval workflow** for org-scoped agents via the proposals plane — tiered writes
   already say personal/reversible is direct, org semantic state is proposal-only.
4. **Eval-on-change** — changing instructions re-runs that agent's goldens and shows the
   delta. *This is the link VoltOps documents only as adjacent, and we already own both
   halves.*
5. Platform prompt templates (`prompts_investigate.py` et al.) get versioning + the PE
   token attribution readout in the same UI.

**Receipt:** edit an agent's instructions; see the diff; goldens re-run; the score delta
appears; restore v1 and watch it return.
**Risk:** eval cost per edit — debounce, and make re-run explicit-but-suggested rather
than automatic on every keystroke.

---

### VA-8 — The user guardrail plane (≈2 weeks)

**Goal:** guardrails users configure per agent. Distinct from our CA-0/CA-2 truthfulness
guards — those are product logic and stay; this is **user policy**.

**Seams:** parts pipeline (structured events already flow); `govern/usage_caps`,
`govern/disclosure`, `govern/tags`; the streaming path.

**Deliverables**
1. `guardrails: list[GuardrailRef]` on `UserAgent`; input and output kinds.
2. Streaming-aware output guardrails: per-chunk handler that can **modify / drop /
   abort(reason)**; input guardrails blocking by default with an opt-in
   parallel/hold-until-pass mode.
3. **Every guardrail execution is a span** (action, pass/fail, metadata) — so VA-5 renders
   it and VA-6 can alert on block rate.
4. Structured block event to the UI (`code`, `reason`, `guardrail_id`, `severity`) — the
   parts pipeline carries it; renderer shows a real refusal, not a blank turn.
5. **Built-ins from existing bones:** PII (`govern/disclosure`), schema-scope enforcement
   (`UserAgent.schema_scope`), cost caps (`govern/usage_caps`), output-format validation.

**Receipt:** attach a PII output guardrail; stream an answer that would leak an email;
watch the chunk get modified mid-stream; find the guardrail span in the waterfall.
**Risk:** guardrails that silently swallow content — the block event and its span are
mandatory, never a quiet drop.

---

### VA-9 — The integrations plane (≈3 weeks) — *the vision's core*

**Goal:** users connect their agents to their apps. **Native MCP is the mechanism, so the
"no more n8n" directive stands.**

**Seams:** ⚠️ **no generic MCP client exists** — `mcp/client.py` is an HTTP client for
Aughor's own API. `secretvault.py` (Fernet) and the approvals plane do exist.

**Deliverables**
1. **`aughor/mcp/consumer.py`** — a real MCP client (stdio + SSE transports), server
   registry, tool discovery, health, timeouts, and per-call audit.
2. **Per-user app connections** — connect a Gmail/Slack/GitHub MCP server; credentials
   encrypted per user in the vault; connection health visible.
3. **Per-agent tool grants** — an agent gets *named* tools from a connection, not the
   whole server. Writes route through the approvals plane (tiered writes hold).
4. **Inbound triggers** — a webhook/app event starts an automation or an agent run;
   signature verification; replay protection.
5. Every external tool call is a span (VA-5) and counts toward caps (VA-8).

**Receipt:** connect Slack as a user; grant one agent `post_message`; ask it to summarise
a finding and post; the write pauses at approval; approve; the message lands; the whole
chain shows in the waterfall with the external call attributed.
**Risks:** ⚠️ this is the **largest new attack surface in the arc** — third-party servers
running third-party code with user credentials. Non-negotiables: no implicit write grants,
every credential in the vault (never in `data/` tracked dirs — the repo is public and this
has bitten before), an allowlist of servers, and outbound calls off by default.
**Note:** VA-9 likely **unparks VA-4** — an app trigger wants a dataflow chain behind it.

---

### VA-10 — Multi-user & admin observation (≈2 weeks)

**Goal:** "users (plural) log into Aughor" — with an admin who can see everything.

**Seams:** `org/context.py` (`current_org_id`/`current_user_id` — both live);
`db/rbac.py`; `session_events.org_id`/`user_id`; `govern/usage_caps`.

**Deliverables:** user analytics (activity, spend, agents owned, top questions) over
`session_events`; per-user and per-org quotas on `usage_caps`; an admin view of *every*
user's agents, runs and connections; RBAC hardening on the agent plane (who may create,
grant tools, approve, see whose traces); audit of admin access to user traces
(watching the watchers).
**Receipt:** two users, two agent sets; user A cannot see B's traces; the admin can see
both and that access is itself audited; quotas bite.
**Risk:** privacy — an admin reading a user's prompts is a real policy question, not a
technical one. Default to visible-metadata, gated-payloads.

---

### VA-4 — Automations dataflow (PARKED)

Kept for completeness. `engine.py:581` runs effects independently; the fix's shape is now
known (merged-data chaining à la `andThen`, typed suspend/resume as our approval gates).
**Build nothing until unparked.** VA-9 is the likely trigger to unpark it.

---

## 3 · Sequencing

```
NOW
  VA-0  ship Agent Ops                     (built — the chassis)

FOUNDATION (parallel-safe)
  VA-3  OTLP conventions        (3–4 d)  ─┐  small, unblocks nothing but pays forever
  VA-1  skills plane            (1 wk)   ─┤  content multiplier, independent
  VA-2  delegation              (1–2 wk) ─┘  ← the biggest gap; gates VA-5's node view

OPERABILITY
  VA-5  trace excellence        (2 wk)   needs VA-2 for hops, VA-3 for conventions
  VA-7  instruction management  (1–2 wk) parallel with VA-5
  VA-6  agent alerting          (1 wk)   needs VA-5's metrics to alert on

PLATFORM
  VA-8  guardrail plane         (2 wk)   spans land in VA-5, block-rate feeds VA-6
  VA-9  integrations            (3 wk)   the vision's core; largest risk surface
  VA-10 multi-user + admin      (2 wk)   hardening pass over everything above

LATER   VA-4 automations dataflow (unpark when VA-9 forces it)
```

**House rules that bind every PR:** one PR at a time, squash, never push without
authorization · ratchet battery on your own diff in a clean worktree · seven frontend
gates + `gen:api` on route changes · `PYTHONPATH="$PWD"` in worktrees · one writer per
`data/` · **prove each wave live in the browser** · measure the premise before building.

---

## 4 · Decisions — THREE LOCKED BY THE USER 2026-08-22

**① VA-2 delegation: EVERYTHING, UNBOUNDED DEPTH.** Any agent may delegate to any agent
(custom agents *and* charters), and a delegate may itself delegate. This is the most
capable option and it moves the safety burden from the topology into the runtime, so the
wave now MUST ship these with it — they are not optional hardening, they are the feature:

- **Cycle detection** — `agent_path` is the authority; an agent already on the path is
  refused with a typed reason, not silently dropped. A→B→A must be a visible refusal.
- **Global step ceiling per RUN**, not per level. Depth-based bounds (`10 × targets`)
  multiply catastrophically once depth is unbounded; the run-wide counter is the real
  stop. Config on `ModelProfile`, surfaced when hit.
- **Per-run cost cap** through `govern/usage_caps` — a delegation tree is the one shape
  that can spend without bound. Hitting the cap ends the run with a stated partial result,
  never a silent truncation.
- **Wall-clock timeout per run**, with the tree cancelled cleanly (tool cancellation
  semantics from the VoltAgent reference).
- **Depth is recorded on every span** so VA-5's node view can draw the tree and VA-6 can
  alert on runaway depth.
- Charters delegate through their **job lifecycle** (async), so `delegate_task` must
  handle both an inline answer and a job handle. This is the extra work the "+ charters"
  option carried, now in scope.

**🆕 RESOLVED 2026-08-22 by measurement, not by building.** "Include charters" turns out to
be *already satisfied*, through tools rather than through `delegate_task` — the roster the
conversation routes over is 15 tools, and the charters are in it:
`analyst` → **`deep_analysis`** (`converse_tools.py:451`, the CA-3 analyst door) ·
`insight` → **`answer_question`** (the quick-answer path IS that charter) ·
`watcher`/`briefer`/`curator`/`scout` → their OUTPUT is readable via `list_monitors`,
`get_briefing`, `list_findings`, `get_table_health`. A second `delegate_task` route to the
same work would be two routing surfaces for one capability, and policies drift.
**The one genuine gap is on-demand TRIGGERING** — chat cannot say "Explorer, profile this
now". That is a cost-incurring write behind `Capability.AUTO_EXPLORATION`
(`routers/exploration.py:711`), which makes it a **trigger**, not a delegation: it belongs
with VA-9's Actions & Triggers plane and its approval path, not smuggled into this wave.

**② VA-1 skills: ALL DATA/ANALYTICS SKILLS (~40–60), SPOT-CHECKED.** Everything
data-adjacent comes in, linted automatically, with a hand-reviewed sample. Consequence:
**the ingestion linter is now the primary line of defence, not a backstop** — it must be
built first and tested adversarially (a skill that tries to disable a guard, name a model,
or carry a credential must fail the suite before any bulk import runs).

**③ VA-10 admin visibility: ADMINS SEE EVERYTHING, AUDITED.** Full payload access on all
traces for admins, with **every access logged as an auditable event** (who, whose trace,
when, why-if-given). The audit trail is the control, so it ships in the same PR as the
access — never after. Users are told, in the product, that admins can read their runs.

### Still open

⚠️ **Four entries that used to sit here were already answered by the LOCKED decisions
above, added the same day.** They are struck rather than deleted, because a stale open
question costs someone a decision they have already made:

- ~~VA-1 import scope~~ → **②** (all data/analytics skills, spot-checked).
- ~~VA-2 targets~~ and ~~VA-2 depth~~ → **①** (unbounded depth; charters resolved by
  measurement, not by building).
- ~~VA-10 privacy~~ → **③** (admins see everything, audited).

**RESOLVED 2026-08-23 by the user:**

**④ VA-3 default — OTLP OFF unless an endpoint is configured.** Local-first, matching
every other integration here: `AUGHOR_OTLP_ENDPOINT` unset means no export and zero
egress. Setting it turns Langfuse / VoltOps / Grafana / Jaeger into "point it here".

**⑤ VA-9 launch allowlist — Slack + Gmail + GitHub + Airtable + Cron.** The catalog
breadth of the reference product, including a schedule-based trigger. ⚠️ This is five
credential shapes and two mechanisms (webhook AND polling) at once, on the arc's largest
attack surface — so the consumer, the vault path and the approval flow should be proven
end to end on ONE server before the other four are enabled, even though all five are in
scope for the wave.

**⑥ VA-9 write approval — ONCE PER GRANT, with a per-call audit and a kill switch.**
Granting `post_message` to an agent authorises that tool until revoked. Per-call approval
was rejected deliberately: an automation that reacts to an external event cannot complete
unattended if every write stops for a human, which defeats what triggers are for. The
audit trail and the kill switch are therefore not optional — they are the whole control,
and they ship in the same PR as the grant.

**⑦ Sequencing — FINISH ARC VA FIRST.** CA-3's open items (deep step budget/tier,
`ask.converse` posture) wait. VA-2 already touched that loop and landed cleanly, and
CA-3 is easier to decide once the trace and guardrail planes exist to measure it with.

🔑 **Carried debt, unscheduled by that choice:** threading a real `cancelled` callable
down the converse tool seam. VA-2 documented the exposure — a suppressed frame is a
cancellation checkpoint not taken — and the fix covers `answer_question` and
`deep_analysis` at the same time. Bounded to one hop today; it should not stay open
forever just because it lost a sequencing vote.

---

## 5 · Traps carried in

- `uploadSkill` (AI SDK 7) is Anthropic/OpenAI provider-managed — **do not build VA-1 on
  it**; client-side disclosure works on the free ladder.
- The roster block uses `purpose`, never instructions (65% prompt waste, measured).
- Forward only `tool-call`/`tool-result` sub-agent events by default.
- `delegate_task` returns an **array** even for one target — do not "simplify" it.
- Imported skills are untrusted prose: lint for model ids, credentials, injection.
- Credentials never in `data/` — four artifact dirs there are **tracked and public**.
- A guardrail that drops content without an event is a silent failure; the span is
  mandatory.
- `session_events` `created_at`-style comparisons: ISO uses `T`, `datetime('now')` uses a
  space — comparing them silently widens windows.
- Any capability added to `DuckDBConnection` misses `LocalUploadConnection` (bitten 3×).

---

## 6 · The VoltOps feature inventory, from screenshots (user-supplied 2026-08-22)

Read off ten screenshots of the live product. This is the granularity bar — recorded here
because "make it like VoltOps" is not a spec and this is.

### 6.1 Trace / observability views
- **Four view modes on one trace:** `Execution` · `Structure` · **`Flow`** · **`Waterfall`**.
- Timeline rail: span count ("4 spans"), agent name, expandable nodes.
- **Node cards on the flow canvas**, each with a visibility toggle: `Trigger Event`
  (service, timestamp, status PENDING, raw input JSON) → `Input` (rendered prompt) →
  agent node (elapsed `9.63s`) → `Output` (streamed text, `stop` control).
- Inter-node **latency edges** ("0ms", "12ms", "62ms") — the gap between spans is itself
  a rendered number.
- Per-node: `Instructions`, `Model` badge, and a **Usage block: Prompt / Completion /
  Total** tokens.
- Tabs per trace: `Overview · Logs · Evals / Scorers · Memory · Usage`.
- Actions in context: `Triggers (60)` · `Add Trigger` · `Add Action` · `Test Agent`.
- Canvas controls: zoom in/out, fit-to-screen.

### 6.2 Trace list
Columns: `Started at · Entity · User ID · Input · Output · Ended at · Duration · Spans`,
sortable. Filters: **Date range · Status · Agent ID · Entity type · Token usage · Cost ·
Duration · User ID**. Free-text `Search traces`, `Clear filters`, **`Columns` picker**,
pagination with rows-per-page. Status dot per row (green ok / red error / blue running),
`In Progress` rendered where a run has not finished.

### 6.3 Logs
`Local` / `Remote` tabs · live `Connected` state · count (369) · level filter · search ·
per-entry: timestamp, level badge, logger name, message, **structured attribute chips**
with an expandable JSON block and a **Copy** control, plus `Instrumentation Scope`
(name + version).

### 6.4 Analytics dashboards
Tabs: `Overview · Cost & Usage · Latency · Tool Usage · Agent/Workflow Usage · Prompt
Analytics`, with a global range picker ("Last 2 days"). Charts: **Trace Latency** and
**LLM Latency** as P50/P95/P99 bands with a hover tooltip giving all three; **Run Count by
Tool**; **Median Latency by Tool**. Every panel expandable to full screen.

### 6.5 Memory Explorer
`Memory` / `Managed Memory` tabs · memory **source** selector (Local API) · **USERS** list
with conversation counts and last-seen · agent filter · user search · per-user
`Conversations · Profile · Remote Traces` · a conversation transcript with **tool call
rows** (`tool-page_navigate` ✓ Completed, expandable) · **Conversation working memory**
panel with an honest empty state.

### 6.6 Prompt management
Named prompt ("Customer Support") with **`Content & Versions`** and **`Analytics &
Performance`** tabs. Version rail v4…v12 with **author + timestamp per version** and
labels **`production` / `staging` / `latest`**; **`Promote`** action; `Import` /
**`Export Markdown`**; per-version `Content · Usage · Traces` tabs.

### 6.7 Alerts
Alert name · **metric: Errored Runs | Feedback Score (soon) | Latency** · **`Filtered On`
with a rich field list** (Status, Latency ms, Model, User ID, Input, Output, Error
Message, Agent/Workflow Name, Entity Type, Metadata) · condition as **count|percent
exceeds N in {5,15,30,60} minutes** · **`Wait at least` debounce** {5m,15m,30m,60m,120m} ·
notification channels (Slack webhook + add more) with **`Send Test Notification`** · a
live **Alert Preview** chart of the metric over the window.

### 6.8 Guardrails
Per-agent `input[]` / `output[]` arrays. Built-ins named: **content moderation**
(categories + threshold), **PII detection** (`mask: true`, `types: [email, phone, ssn]`),
**topic restriction** (`blocked: [...]`). In the trace: each guardrail is **its own span**
with `Allowed` / **`Blocked`** state, elapsed (63ms / 2.03ms), **Before / After** content
panels, `Direction: Input`, and **`Severity: Warning|Critical`**. A block produces a
user-facing error with the reason.

### 6.9 Evals
`Pass rate · Mean score · Total items (84 passed · 0 failed) · Active runs` · **Run trend**
(pass-rate over time) · **Scorer performance** cards per scorer — Answer Correctness,
Answer Relevancy, contextPrecision, contextRecall, contextRelevancy, Exact Match — each
with mean, pass %, latest, run count, a threshold badge (`GTE 0.70`), a delta vs previous
and a sparkline. Config: `triggerSource`, `environment`, **`sampling: {type: ratio,
rate: 0.1}`**.

### 6.10 Triggers / integrations
**Trigger Catalog** searchable by integration/service/category, each entry tagged by
mechanism — **`webhook` | `polling` | `schedule`** — and category: Slack, Gmail, GitHub,
Airtable, Cron, plus **`Request Integration`**. Dashboard: `Success rate`, `Executions`
with trend. **Active Triggers** table (trigger · connections · status · targets) and
**Recent Runs** across all connections.

### 6.11 RAG
Chunk settings: delimiter, **max chunk length**, **chunk overlap**; pre-processing
toggles (collapse whitespace, strip URLs/emails); **`Parent-child`** chunking mode (child
chunks retrieved, parent chunks for context); embedding model + provider selector; and a
**chunk preview** showing per-chunk character and token counts before ingest.

### 6.12 What this changes in the plan
Nothing is re-sequenced, but three waves get sharper acceptance criteria: **VA-5** owes
Waterfall *and* Flow with inter-span latency edges and a per-span usage block; **VA-6**
owes the filter grammar, the debounce, the test-notification button and the preview chart,
not merely "an alert fires"; **VA-7** owes labels + author + promote + export. Two items
arrive that the plan did not name: **a Memory Explorer** (VA-5/VA-10 boundary) and **RAG
chunk configurability** (existing knowledge registry, currently not user-tunable) — both
logged, neither scheduled.
