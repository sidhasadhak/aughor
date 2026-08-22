# VoltAgent adoption study — what "super agentic" actually imports (2026-08-22)

**The ask (user, 2026-08-22):** adopt github.com/VoltAgent/voltagent "as much as possible"
— naming the VoltOps Console, the core TypeScript framework, and
github.com/VoltAgent/awesome-agent-skills — to make Aughor a fully agentic data
intelligence platform.

**The verdict in one line:** adopt the *grammar* (supervisor→sub-agent delegation, workflow
dataflow, skills format, OTLP traces) into the Python brain and adopt the *content*
(1,497 MIT skills), but do not run the runtime — a second brain in Node is the same
fragmentation the Aug-12 chat-shell decision killed, and everything VoltAgent's runtime
provides already has a live Aughor organ.

---

## 1 · What VoltAgent is (measured, not assumed)

- **@voltagent/core** — MIT, TypeScript, ~10.4k stars, 1,748 commits, active. An `Agent`
  class (name/instructions/model/tools/memory), Zod-typed tools with lifecycle hooks and
  cancellation, durable memory adapters, MCP client *and* server, multi-provider via the
  Vercel AI SDK provider spec.
- **Supervisor/sub-agents** — a supervisor agent gets an auto-injected `delegate_task`
  tool (`task`, `targetAgents[]`, optional context; always returns an array of
  `{agentName, response, usage, bailed}`). Routing is prompt-driven from each sub-agent's
  short **`purpose`** field ("avoid leaking long instructions into the supervisor's
  prompt"). Sub-agent stream events forward to the parent with
  `{subAgentId, parentAgentId, agentPath}` metadata, default-limited to
  `tool-call`/`tool-result`. Loop bound: `maxSteps = 10 × sub-agent count`.
  `bail()` on handoff skips the supervisor's synthesis round when a sub-agent's output is
  final.
- **Workflow engine** — `createWorkflowChain()`: `andThen` / `andAgent` / `andWhen` /
  `andAll` / `andRace` / `andGuardrail` / `andForEach` / `andBranch`. **"The output of one
  step becomes the input for the next; the data object is automatically merged."**
  Zod `input`/`result` schemas plus **`suspendSchema`/`resumeSchema`** — workflows suspend
  mid-run, persist state, and resume with typed payloads. Per-step retry, `bail()`,
  full execution history per run.
- **Observability** — **OpenTelemetry, OTLP over HTTP.** The developer console
  (console.voltagent.dev) is a browser app that talks **directly to the local agent
  process** (port 3141): "No data is sent to or stored on any external servers for this
  local debugging mode." Cloud export activates only when `VOLTAGENT_PUBLIC_KEY`/
  `SECRET_KEY` exist. Console shows trace timeline/graph, tool I/O, a Memory Explorer,
  agent list/detail. **VoltOps the platform** (evals, triggers, deployment, guardrails
  management) is the commercial side, not part of the MIT core.
- **awesome-agent-skills** — MIT, **1,497+ curated skills** in the Anthropic SKILL.md
  ecosystem (Claude Code / Codex / Cursor / Gemini CLI compatible), explicitly
  hand-picked from real engineering teams. Data-relevant today: ClickHouse (6),
  Tinybird (4), Neon Postgres (3), DuckDB, MongoDB, BigQuery-adjacent. The AI SDK 7 added
  first-class skill support (`uploadSkill` → provider-managed execution on
  Anthropic/OpenAI).

## 2 · What Aughor already has (the premise, measured 2026-08-22)

| VoltAgent organ | Aughor's organ | state |
|---|---|---|
| `Agent` record | `UserAgent` (instructions, connection_id, schema_scope, doc_ids, pack_ids, enabled, last_eval) + 7 charters | live |
| Tool registry | 14 platform tools, closure-bound, proposal-only writes | live |
| Agentic loop | converse tool loop + CA-3 analyst loop (deep analysis as the analyst) | live |
| Memory | thread history + context graph + glossary + ontology overrides | live |
| MCP | `aughor/mcp/` — server **and** client | live |
| Observability store | `session_events` spans w/ Migration-10 attribution (job/charter/role/fallback) | live |
| OTel | `telemetry.py` **already imports the OTel SDK + OTLP HTTP exporter** (line 126-131); Langfuse attribute conventions ride on spans; the Langfuse SDK backend is silently dead (v2 vs 4.7.1) | half-wired |
| Console | **Agent Ops control room** — Overview·Roster·Attention·Activity·Runs, shared time axis, provenance drawers, run timeline | built, unpushed (11 commits) |
| Workflows | automations engine — but `engine.py:581` runs effects as an independent list comprehension: **no effect can consume another's output** (the documented blocker that parked the builder) | live, dataflow-less |
| Skills | none. Packs (pack.yaml + expertise.md + entities + metrics + questions + evals) are a richer sibling — and there is exactly **1 pack on disk** | gap |
| Delegation | none. An ask can *run as* one agent (persona substitution); chat can never *delegate to* agents mid-conversation | **the gap** |

## 3 · Per-layer verdicts

- **Core TS runtime — REFERENCE.** Running it stands up a second brain: agent state,
  memory, tool registry and — decisive — the guards would split across Python and Node.
  Guards are the product. Same verdict as vercel/chatbot ("template ≠ framework"), same
  reason as one-app. What we take: the `purpose` field (prompt economy for rosters), the
  delegate-result shape, `maxSteps = k × targets`, bail-on-handoff, tool cancellation
  semantics.
- **Supervisor/sub-agents — ADOPT THE PATTERN (VA-2).** The single highest-leverage
  import. Custom agents today are configuration that an ask can impersonate; delegation
  makes them *usable specialists inside the conversation* — `delegate_task` as platform
  tool #15, targets = enabled custom agents + eligible charters, each listed by
  `purpose`, results streamed as parts (CA-1's renderer already handles unknown parts as
  labelled extras; sub-agent metadata rides providerMetadata exactly like
  channel-tagging). This directly attacks the platform-review finding: *features stall at
  TESTED, not LEVERAGED.*
- **Workflow chain grammar — ADOPT THE SEMANTICS, LATER (VA-4, stays parked).** `andThen`
  merged-data flow is precisely the missing dataflow named at `engine.py:581`, and
  `suspendSchema`/`resumeSchema` is our approval gate formalized (a gate IS a typed
  suspension; CA-1 already made gate approvals chat-native turns). Record the shape;
  build nothing until the user unparks automations v2. **A canvas remains refused** — the
  blocker was never the canvas.
- **VoltOps Console — ALREADY BUILT; VALIDATE + finish OTLP (VA-0 + VA-3).** Agent Ops
  *is* our VoltOps: agent list/detail, trace timeline, attention inbox, usage — grounded
  in the OpenRouter grammar and in-app (better than a separate console under the one-app
  rule). Their local-first posture (nothing leaves the machine without keys) matches
  ours. The one real import: **standardize trace export on OTLP + OTel GenAI semantic
  conventions.** The exporter import already sits in telemetry.py; the dead Langfuse SDK
  backend gets deleted, Langfuse/VoltOps/Grafana/Jaeger all become pluggable OTLP
  backends, and §7.5's LF-2/LF-3 topology question collapses into "where do you point
  the OTLP endpoint" — BYO-observability, the observability twin of BYOK.
- **awesome-agent-skills — ADOPT FORMAT + CONTENT (VA-1).** Two moves. ① SKILL.md
  ingestion: `import skill → pack` (frontmatter name/description → pack.yaml; body →
  expertise.md; no entities/metrics/goldens — an honest partial pack). The 1,497-skill
  MIT library becomes Aughor content: DuckDB skills improve the engine we already run;
  ClickHouse/Tinybird/Postgres skills seed connector expertise. One pack on disk today
  means the content multiplier is ~immediate. ② Progressive disclosure in the tool loop:
  skills load by description match at need, **client-side, provider-agnostic** — works on
  the free ladder, unlike AI SDK 7's `uploadSkill`, which only exists on Anthropic/OpenAI
  provider-managed environments. Optional later: publish an "aughor" skill (MCP
  connection recipe) back to the repo — the marketing direction of Aughor-as-MCP.
- **VoltOps cloud / evals / guardrails / triggers — SKIP.** Commercial, not core; and
  Aughor already owns each organ (evals + golden questions; guards as the product thesis
  — `andGuardrail`'s step-boundary placement independently agrees with CA-2's
  guards-at-the-evidence-layer; automations as triggers).

## 4 · Arc VA sequencing

```
VA-0  ship Agent Ops                 (built; awaiting push permission — you cannot
                                      run a fleet you cannot see)
VA-1  skills plane                   (SKILL.md ingestion → packs · curated data-skill
                                      import, DuckDB first · description-gated loading
                                      in the tool loop)
VA-2  delegation                     (delegate_task tool · purpose field on
                                      UserAgent/charters · sub-agent events as parts ·
                                      maxSteps bound + bail-on-handoff)
VA-3  OTLP standardization           (GenAI semantic conventions on session_log spans ·
                                      delete the dead Langfuse SDK backend · OTLP
                                      endpoint = config; resolves §7.5)
VA-4  automations v2 chain grammar   (PARKED until the user says otherwise; the
                                      blocker's fix now has a named, proven shape)
```

## 5 · What NOT to do, and why it is already settled

No Node runtime beside the Python brain (Aug-12, one app). No VoltOps cloud dependency
(BYOK/local-first; the platform side is not open source). No canvas revival (ReactFlow
verdict stands; VA-4 is engine semantics, not UI). No NL2SQL machinery rebuilt under a
VoltAgent banner (concluded 4×: deterministic guards > LLM machinery on strong models).
No model ids in imported skills — the ingestion linter must enforce the no-hardcoded-model
rule on day one.

## 6 · Open decisions (user)

1. **VA-1 scope:** import curated skills wholesale (tagged `source: awesome-agent-skills`)
   or one-by-one with review? (Recommendation: start with the ~15 data-engine skills,
   review each; they are prompt content, and prompt content is product surface.)
2. **VA-2 targets:** custom agents only, or charters too? (Recommendation: custom agents
   first — they carry connection/schema scope; charters delegate implicitly via tools
   already.)
3. **VA-3 default endpoint:** ship with OTLP off (pure local) or pointed at a
   self-hosted collector when one is configured?
4. Whether Arc VA supersedes or interleaves with the remaining CA-3 decisions
   (deep step budget/tier, ask.converse posture) — VA-2 touches the same loop.

## Traps for the builder

- `uploadSkill` (AI SDK 7) is provider-managed and Anthropic/OpenAI-only — do not build
  VA-1 on it; client-side disclosure works on every backend including the free ladder.
- The supervisor's roster block must use `purpose`, never full instructions — we measured
  65% prompt waste once already (PE waves); do not reintroduce it via delegation.
- Sub-agent stream forwarding defaults narrow (tool-call/result only) for a reason; a
  delegate that forwards text-deltas doubles every token through the SSE pipe.
- `delegate_task` returning an *array* (even for one target) is load-bearing — parallel
  fan-out later without an API break.
- Skills are untrusted prose: ingestion must lint for model ids, credentials, and
  instruction-injection patterns ("ignore your guards…") before a skill becomes a pack.

---

## 8 · REVISION (2026-08-22, same day) — the platform lens, after user pushback

**The user's correction, verbatim in substance:** the §3 verdicts compared Aughor against
VoltAgent's *framework and local dev console* and called our console AHEAD while dismissing
the VoltOps *platform* as "SKIP — commercial." That conflated *can't reuse their code* with
*don't need the capability*. Closed source makes those capabilities a BUILD list, not a
skip list. The vision restated: **users (plural) log into Aughor, build agents the way
they want, connect them to apps (Gmail, Slack, …), and admins keep a full observation
mechanism** — the warehouse/AI-BI side is done well; the agent-platform side must reach
VoltOps grade. Aim for excellence, not minimal diffs.

**What VoltOps actually has, measured this time** (voltagent.dev/voltops-llm-observability
+ /observability-docs + prompts + guardrails docs):
- Tracing: **Waterfall View + Node-Based View**, per-hop payload inspection, session
  replay, trace logs, **trace feedback**, multi-agent hop attribution.
- Dashboards: real-time, flow-diagram execution visualization.
- **Alerts on agent telemetry** (latency / errors / token usage) → Slack, email, webhooks.
- User Analytics · LLM Usage & Costs.
- **Public Trace API** + a **read-only MCP server for traces** (coding agents debug runs).
- **Prompt management**: versioned, environment labels, variables,
  `prompts.getPrompt()` runtime fetch, non-technical editing, audit trails + approval
  workflows.
- **Guardrails**: `createInputGuardrail`/`createOutputGuardrail`, per-chunk
  `streamHandler` (modify / drop / `abort(reason)`), parallel input with
  `holdUntilPass` buffering, structured `data-input-guardrail-blocked` events, every
  execution traced as spans.
- Actions & Triggers · Deployment · Evals · RAG.

**Verdict flips:** Console/observability AHEAD → **BUILD to VoltOps grade** (Agent Ops is
the foundation, not the finish line). VoltOps-cloud SKIP → **BUILD natively** (prompt
mgmt, agent alerting, user guardrail plane, integrations, user analytics). What does NOT
flip: evidence-layer truthfulness guards and the provider ladder remain ours and ahead —
but they are a *different layer* (product truthfulness) from what VoltOps offers
(user-configurable policy), and having the first does not close the gap on the second.

**Arc VA, expanded (VA-0..4 unchanged):**
- **VA-5 Trace excellence** — waterfall + node views over session_events; per-hop payload
  inspection; trace logs; trace feedback (thumbs → evals; unblocks OA·LF-2's intent);
  Public Trace API; trace tools added to `aughor/mcp/server.py`.
- **VA-6 Agent-plane alerting** — alert rules on agent telemetry (latency, error rate,
  token burn, cost) delivered via the N8-0 outward path (Slack/email/webhook). Monitors
  machinery pointed at the agent plane instead of only at data KPIs.
- **VA-7 Instruction/prompt management** — versioned agent instructions (the
  `v{version}` history in AgenticAgentsPanel is the seed), draft/live labels, diff view,
  approval workflow (kinetic-inbox pattern), auto-rerun of the agent's goldens on change.
- **VA-8 User guardrail plane** — per-agent input/output guardrails, streaming-aware
  (parts pipeline already carries structured events), each execution a span; built-ins
  from existing bones: PII, schema-scope enforcement, `govern/usage_caps` cost caps.
- **VA-9 Integrations plane** — per-user app connections via MCP client (Gmail/Slack MCP
  servers), credentials in `secretvault.py` per user, per-agent tool permissions through
  the existing approvals plane, inbound webhook triggers into automations. (This is what
  the n8n arc was circling; native MCP is the mechanism, so the no-more-n8n directive
  stands.)
- **VA-10 Multi-user + admin observation** — user analytics over session_events
  (org_id/user_id exist), per-user quotas on `usage_caps`, admin dashboards, RBAC
  hardening.

Sequencing note: VA-2 (delegation) precedes VA-5's multi-agent hop views — you cannot
draw hops that cannot happen. VA-9 likely *unparks* VA-4 (an app trigger wants a dataflow
chain behind it) — the user decides.
