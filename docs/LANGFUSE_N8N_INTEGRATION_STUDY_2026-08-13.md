# Langfuse + n8n — Deep Integration Study

*2026-08-13 · verified against langfuse.com / docs.n8n.io / github.com/langfuse / github.com/n8n-io live, and against this codebase at `650d898` + PR #343. Every code claim below carries a file reference; every product claim was fetched today, not recalled.*

---

## 0. Executive summary

**Langfuse** (MIT core, EE folders excepted) is an LLM engineering platform: OTel-based tracing, sessions/users, cost dashboards, prompt management, LLM-as-a-judge evals, datasets, annotation queues. The self-hosted FOSS tier includes essentially everything a team needs — prompt management incl. playground, LLM-as-judge, annotation queues, custom dashboards, org RBAC/SSO; Enterprise gates only retention policies, audit logs, project-level RBAC, SCIM, server-side masking.

**n8n** is a workflow automation platform with 500+ integrations, AI-agent nodes, human-in-the-loop approvals, and first-class MCP in both directions. It is **not open source** — the Sustainable Use License allows internal business use but forbids embedding it in a commercial product; that requires the paid Embed/OEM agreement (execution-volume billed, no public price, n8n branding stays visible). This single fact fixes the whole integration architecture: **arm's-length only**.

**The three findings that reshape the ask:**

1. **Aughor already integrated Langfuse — and the integration is dead.** `aughor/telemetry.py` gates a Langfuse backend on `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` and speaks the SDK v2 API (`lf.trace(id=…)` at `:58`, `tr.span(…)` at `:622`, `tr.generation(…)` at `:690`). The venv has **langfuse 4.7.1**, where none of those methods exist (probed live: `has .trace: False`). The pin `langfuse>=2.0.0` (`pyproject.toml:112`) allowed the major-version walk. Init succeeds, every subsequent call raises `AttributeError`, and every failure is swallowed at `debug` level — by design ("observability must never break the answer path"). This is the guard-goes-blind pattern from #251: a seam whose matching key stopped matching, silently.
2. **The richest telemetry never reached Langfuse even when it worked.** `telemetry.log_generation` "existed but had no call sites, so all of it was discarded" — the codebase's own words at `aughor/llm/provider.py:1172`. The real record is the in-house **session log** (`aughor/obs/session_log.py`): one event per LLM call with provider, model, role, tokens, latency, retries, fallback-swap, caller attribution and org — axes measured 90–100% populated on real data (`aughor/obs/usage.py` docstring). Aughor built a mini-Langfuse in-house; what it lacks is Langfuse's *reading* surface (UI, dashboards, judge evals, annotation) — not instrumentation.
3. **The n8n side needs almost no new plumbing.** An **Action Hub** already exists: `aughor/notifications/executor.fire_action` dispatches webhook/Slack/Jira triggers with SSRF re-checks at send time, masked credentials, and a shared audit log (`aughor/routers/actions.py`, `aughor/briefing/delivery.py` already delivers briefs through it). Monitors carry a `notification_channel` field documented as *"'in_app' | 'slack' | 'email' (only in_app wired currently)"* (`aughor/monitors/models.py:108`) — an unwired seam waiting for exactly this. And `aughor/mcp/server.py` already exposes 15 governed tools (`ask`, `deep_analysis`, `get_metric`, `get_briefing`, `search_graph`, jobs…) that n8n's MCP Client node can consume **today**.

**Verdicts, one line each:**

| Move | Verdict |
| --- | --- |
| Repair Langfuse tracing via the existing OTel exporter → Langfuse OTLP endpoint | **Do first** (LF-1) |
| Bridge `_record_llm_call` → generation spans; map chat sessions + orgs; declare PRICES to Langfuse | **Do** (LF-2) |
| Langfuse judge-on-production-traces + annotation queues + chat feedback scores | **Do after LF-2** (LF-3) |
| Move prompt authoring into Langfuse Prompt Management | **Don't** — vocabulary ratchets in CI are the review gate; patterns only |
| Self-host Langfuse inside Vercel | **Impossible** (ClickHouse+Redis+S3+worker); separate host or Langfuse Cloud |
| Wire monitors' dead `notification_channel` through the Action Hub | **Do regardless of n8n** (N8-0 — it's an in-repo gap) |
| n8n as delivery fabric: ship workflow templates (our JSON, their n8n) | **Do** (N8-1) |
| n8n workflows call aughor's MCP/REST as a governed analytical brain | **Do — mostly documentation** (N8-2) |
| Actions-from-chat: Arc CI calls n8n (MCP Server Trigger) with HITL approval | **Do later, flag-gated** (N8-3) — this closes the closed-loop gap |
| Embed n8n's engine/editor in aughor | **Never** — Sustainable Use License; Embed/OEM is a paid agreement |

---

## 1. What the codebase already has (the measured premise)

Before proposing anything, the inventory — because every prior wave that skipped this step mis-scoped:

| Capability | Where | State |
| --- | --- | --- |
| Trace ids + spans | `aughor/telemetry.py` — three backends: Langfuse (SDK), OTel (`OTEL_EXPORTER_OTLP_ENDPOINT`), MLflow (skinny) | OTel + MLflow live; **Langfuse dead** (v2 API vs installed 4.7.1) |
| Per-LLM-call record | `provider._record_llm_call` → `session_log.LLM_CALL` | Live, always-on (graduated, flag deleted 2026-08-01) |
| Prompt/content capture | `session_log.capture_prompt` — content only inside an explicit capture window, capped + truncation-marked | Live — this *is* a masking policy, client-side |
| Cost attribution | `aughor/obs/usage.py` — declared `PRICES` with as-of dates, per org/role rollups, loud `unattributed`/`unpriced` counts | Live |
| Quick-path traces | `bind_trace` at the ask door — every `/ask`, `/chat` turn has a trace id | Live |
| Eval framework | `aughor/evals/` (runner, registry, experiments, promotion, perturb, frozen) + Wave E3 consolidation door (`routers/evals.py`), golden-SQL CI corpus | Live, load-bearing |
| Outbound actions | `notifications/executor.fire_action` — webhook/Slack/Jira, SSRF guard at send time, audit log | Live |
| Monitor delivery | `monitors/models.py` `notification_channel` | **Unwired** beyond in_app |
| MCP server | `aughor/mcp/server.py` — governed tools with Trust Receipts, thin wrappers over the REST API | Live |
| Per-prompt billing | #330 "every prompt gets a bill" | Live |

The pattern across both products: **aughor's write side is done; the read/act sides are the gaps.** Langfuse is a read surface for telemetry that already exists. n8n is an act surface for actions that already dispatch. That's why both integrations are cheap — and why the platform-review finding ("features stall at TESTED, not LEVERAGED") applies: the session log is written and barely read; the Action Hub fires and almost nothing feeds it.

---

## 2. Langfuse

### 2.1 What it is (verified today)

- **Tracing**: traces with nested observations (spans, generations, events); agent-graph view; timeline/latency view; "all LLM and non-LLM calls, including retrieval, embedding, API calls."
- **Sessions & users**: first-class multi-turn session grouping and per-user cost/usage.
- **Prompt management**: versioned prompts with labels ("deploy via labels — without code changes"), composability, caching, playground.
- **Evals**: LLM-as-a-judge on production *or* dev traces, code evaluators, user-feedback scores, manual labeling via annotation queues, datasets + experiments.
- **Dashboards**: quality/cost/latency, custom dashboards.
- **SDKs**: Python + JS; v3+ SDKs are **OpenTelemetry-based**; native OTLP ingestion endpoint; 100+ framework integrations.
- **License**: repo is "MIT licensed, except for the `ee` folders." Self-hosted FOSS tier confirmed to include prompt management (incl. playground), LLM-as-judge, annotation queues, datasets, custom dashboards, org-level RBAC + SSO. Self-hosted Enterprise adds: data retention policies, audit logs, project-level RBAC, SCIM, server-side masking, UI customization.
- **Self-host footprint (v3 architecture)**: web + async worker containers, **Postgres (OLTP) + ClickHouse (OLAP) + Redis/Valkey + S3/blob**, all clocks UTC. Docker Compose for low scale; Helm/Terraform for production. Queued ingestion via S3 buffering.

### 2.2 The deployment reality for aughor

Aughor's production is Vercel serverless + Supabase (`vercel-native-platform`, store-pool memory). A ClickHouse + Redis + worker stack cannot ride along. Three viable shapes:

1. **Langfuse Cloud** (free tier exists) — zero ops, data leaves the perimeter. Fine for the operator's own observability; questionable for tenant-data-bearing traces (see §2.6).
2. **Self-host on a separate VM/K8s** — docker compose is adequate at aughor's current volume (hundreds of LLM calls/day measured in usage.py's corpus). ~$20–40/mo VM.
3. **Local docker compose for development** — matches the local-first posture; each developer gets a disposable instance.

Recommendation: **(3) now, (2) when a real operator dashboard is wanted, (1) never for tenant traces.** The env-var gating already in `telemetry.py` means all three are the same code.

### 2.3 LF-1 — repair the dead integration (the actual "add Langfuse" PR)

Two repair paths:

**(a) Rewrite the SDK backend on the v4 API** — `start_observation`, `score_current_trace`, etc. (probed present on 4.7.1). Keeps SDK-only conveniences. Cost: a second tracing vocabulary in `telemetry.py` forever, and the same rot risk on the next SDK major.

**(b) Delete the SDK span path; standardize on the OTel exporter aughor already has**, pointed at Langfuse's OTLP endpoint (`/api/public/otel`), with Langfuse-recognized attributes (`langfuse.session.id`, `langfuse.user.id`, GenAI semconv for generations: model, usage tokens, cost). Langfuse's own positioning — "based on OpenTelemetry to reduce vendor lock-in" — argues for this; one exporter then serves Langfuse *and* any OTel backend (Jaeger, Datadog…) with zero aughor-side branching.

**Recommendation: (b)**, keeping a *thin* v4 SDK client only for the two things OTLP cannot express: **scores** (user feedback, judge results → `score_current_trace`) and **dataset writes** (LF-3). The `langfuse>=2.0.0` pin becomes `langfuse>=4,<5` — a floor *and* a ceiling, because an unbounded major pin is exactly how this integration died. Add a rot-guard test: instantiate the client, assert the methods we call exist (the same class of test that would have caught `lf.trace` vanishing).

Also in LF-1: **serverless flush**. On Vercel, spans buffered in a worker thread die with the invocation. The OTel exporter needs `force_flush()` on response end (the sliced-invocation problem is already documented at `telemetry.py:41` for trace handles — same physics).

Size: one PR. Deletes more than it adds (the v2 Langfuse branch in telemetry.py is ~150 lines of dead code).

### 2.4 LF-2 — put the good data in

1. **Generations**: emit a generation-shaped OTel span from `_record_llm_call` (`provider.py:1159`) — the single chokepoint every `complete`/`complete_with_tools`/`complete_streaming` call already passes through, already carrying model, provider, role, tokens, latency, retries, fallback, caller, org. The session log stays the system of record; this is a *mirror*, best-effort, never-raise — the discipline `session_log.emit` already enforces.
2. **Sessions**: Arc CI chat turns carry a session id (conversation memory is per-session, per-tenant — #334). Map it to `langfuse.session.id`; a multi-turn conversation then reads as one thread in Langfuse's session view — the exact surface the "chat must feel like a frontier-LLM conversation" directive needs for judging *feel* (latency between turns, cost per conversation, where the mechanical-feel baseline #330 regresses).
3. **Users/orgs**: `org_id` → `langfuse.user.id` (operator view of per-tenant cost), `role` (coder/fast/narrator) → tags. `user_id` is measured-0% (never populated in local mode) — don't map it until it exists; a dimension that's always blank teaches nothing (usage.py's own lesson).
4. **Cost**: declare `PRICES` (usage.py) as Langfuse model definitions so its cost dashboards agree with `obs/usage` to the cent. Two disagreeing cost surfaces are worse than one.
5. **Prompt content**: only inside the existing `capture_prompt` window. Default traces carry **metadata, not content** — that single decision defuses most of the tenant-privacy question (§2.6).

### 2.5 LF-3 — the pillars aughor doesn't have

These are the genuinely *new* capabilities, all in the FOSS tier:

- **LLM-as-a-judge on production traces.** Aughor's eval framework is pre-ship and execution-grounded (golden SQL, promotion gates) — keep untouched, it's load-bearing CI. What it structurally cannot do is score *live traffic*. Langfuse judges sampled production traces continuously — "is the narrator drifting," "are briefing headlines still grounded" — without a deploy. Complementary, not duplicative: aughor evals gate *changes*; Langfuse evals watch *drift*.
- **Annotation queues.** Human labeling UI over traces. Aughor has nothing here; building one is exactly the wheel not to reinvent.
- **User-feedback scores.** A 👍/👎 on chat answers → `score_current_trace` → the same dashboards. Cheap, and it finally attaches the user's verdict to the exact trace that produced the answer.
- **Datasets** (optional, later): sync aughor eval cases → Langfuse datasets so experiments run against both harnesses. Do only if the annotation queue output starts feeding eval cases — otherwise it's two stores for one corpus.

### 2.6 What NOT to do, and the tenancy caveat

- **Don't move prompt authoring to Langfuse.** Prompts here are code-resident, guarded by CI **vocabulary ratchets** (#299's lesson: `investigation_in_web` has zero headroom) and the prompt-diet discipline (#332). Langfuse's "deploy prompts without code changes" is precisely the property the ratchet exists to prevent — an unreviewed prompt change is a vocabulary change that never met its gate. Patterns only. (The playground needs no integration to be useful.)
- **Don't self-host inside the app perimeter**, and don't put Langfuse in the request path — it's an observer, `enabled == observed`, never load-bearing.
- **Tenancy**: Langfuse projects are the isolation unit; FOSS RBAC is org-level. One shared project = every trace visible to whoever holds the operator keys. That's acceptable **only** as an operator-internal tool with content capture off by default. Per-tenant projects (or the Enterprise tier's project RBAC + masking) is the line to cross before any tenant ever sees a Langfuse surface. Server-side masking is EE — but aughor's client-side `capture_prompt` window already implements the stronger policy: don't send what you'd have to mask.

---

## 3. n8n

### 3.1 What it is (verified today)

Visual + code workflow automation: 500+ integrations, JS/Python steps, Git-versioned workflows, execution history/replay, RBAC/SSO/secret stores, real-time monitoring. AI side: agent nodes, RAG support, guardrails/evaluations, human-in-the-loop approvals, and MCP both ways — **MCP Server Trigger** (exposes a workflow's tools to external MCP clients over SSE/streamable-HTTP with bearer/header auth, test + production URLs) and **MCP Client Tool** (n8n agents call external MCP servers). Webhook trigger: 6 methods, basic/header/JWT auth, 16MB default payload cap, four response modes including streaming.

### 3.2 The license, precisely

Sustainable Use License: *"You may use or modify the software only for your own internal business purposes or for non-commercial or personal use."* `.ee.` files need the Enterprise license. **Not OSI open source.** Embedding n8n in a commercial product = the **Embed/OEM** agreement: annual committed execution volume, no public pricing (third parties report ~$50k/yr entry), n8n branding remains visible in the embedded editor.

Aughor has a licensing/capability module of its own (`aughor/licensing`, `Capability`, `gate`) — it is a commercial platform. Therefore, hard rules:

1. **Never** ship, bundle, embed, or white-label n8n's engine or editor.
2. **Do** integrate over HTTP/MCP with an n8n instance the *user* runs (their internal business use — squarely licensed) or n8n Cloud (their subscription).
3. **Do** ship our own artifacts: workflow-template JSON, docs, and (optionally) a community node — all our IP, MIT, license-clean.

This constraint costs nothing: the arm's-length architecture is also the *better* architecture (their upgrades, their credentials store, their 500 connectors — none of it becomes aughor's maintenance surface).

### 3.3 N8-0 — wire the channel that already exists (no n8n required)

`notification_channel` on monitors accepts `'slack' | 'email'` and delivers neither; only `in_app` works. Meanwhile `fire_action` sits SSRF-guarded and audited, already delivering briefs. The PR: on alert fire (`monitors/runner.py`), when the monitor's channel names an Action Hub trigger, dispatch the alert payload through `fire_action`. Alert payload = monitor name, severity, value vs threshold, connection, deep link. This closes a documented in-repo gap and is the substrate every n8n scenario below rides on. One small PR.

### 3.4 N8-1 — n8n as the delivery fabric (aughor → n8n)

With N8-0 done, "n8n integration" on the outbound side is: **an Action Hub webhook trigger pointed at an n8n Webhook node** (header-auth secret in `trigger.headers`, already masked by `to_safe_dict`). One n8n workflow then fans out to anything: Slack blocks, Jira tickets, PagerDuty, email digests, Sheets logs, Teams…

Ship `integrations/n8n/` in-repo:
- `alert-to-slack.json`, `alert-to-jira.json`, `briefing-digest-to-email.json`, `alert-escalation-pagerduty.json` — importable workflow templates (our JSON).
- A doc: paste aughor's webhook trigger URL, set the shared header secret, import, publish.

Effort: templates + docs, near-zero code. Payoff: aughor stops needing native Slack/Jira/email integrations *forever* — that entire roadmap category collapses into "here's the n8n template."

### 3.5 N8-2 — aughor as the governed brain inside n8n workflows (n8n → aughor)

The differentiated story. n8n's AI ecosystem is full of raw text-to-SQL nodes that hand a model a connection string and hope. Aughor's MCP server exposes the opposite (`server.py` docstring, MotherDuck R5: *"expose governed intelligence tools, not a raw query tool"*): `ask` returns a verified answer **with a Trust Receipt**; `get_metric` returns the governed value of a registered metric; `deep_analysis` runs the full autonomous path.

- **Today, zero code**: n8n's MCP Client Tool → aughor's MCP server. A schedule-triggered workflow asks `ask("revenue vs last week, by region")` and posts the receipted answer to Slack. An n8n AI agent gets `get_metric` as a tool and stops inventing metric formulas mid-workflow.
- **Also today**: plain HTTP Request nodes against the REST API (the MCP server is a thin wrapper over it anyway).
- **Deliverable**: a "governed analytics in n8n" doc + 2–3 templates (weekly metric report; anomaly-triggered deep analysis: monitor alert → webhook → n8n → `deep_analysis` → post report link). Verify the MCP transport pairing in practice (n8n speaks SSE/streamable-HTTP; `aughor/mcp` runs FastMCP — confirm its HTTP transport config in a live test; it it's stdio-only today, exposing streamable-HTTP is a small change).
- **Later, optional**: `n8n-nodes-aughor` community node (npm, our repo, MIT) — first-class credentials + typed operations instead of hand-built HTTP nodes. Submission to n8n's verified-community-node program is an open question worth one email.

### 3.6 N8-3 — actions from chat (the closed-loop wave)

The `context-graph-closed-loop-gap` memory names the platform's oldest structural gap: insights terminate at being read. n8n is the missing actuator, and the license permits it because the *user's* n8n executes the action:

- A tenant/operator registers an n8n **MCP Server Trigger** URL (bearer token) as an "action pack" in aughor.
- Arc CI's agent gains those tools (aughor already has MCP plumbing in `agent/platform_tools.py` to build on) — chat can then do: *"Margin collapsed on Copiers — draft the Jira ticket."*
- Safety composes from parts that already exist: n8n-side **human-in-the-loop approval** nodes (their feature, verified) + aughor-side capability gating + the Action Hub's audit-log pattern + `escalate` staying a bypass (locked decision 2026-08-13).

Flag-gated, after CI-1d (the AI-SDK thread model rewrite will change tool wiring — don't build tools twice). This is the largest lift and the largest prize: it turns aughor from a system that *knows* into a system that *does*, without aughor ever shipping a connector.

### 3.7 What NOT to do

- No embedded n8n canvas in aughor's UI; no "powered by n8n" runtime in the wheel; no reselling n8n Cloud.
- Don't rebuild n8n inside the Action Hub — it stays a thin, audited dispatcher; orchestration lives on the n8n side.
- Don't take a runtime dependency for core paths: aughor must degrade gracefully when no n8n exists (in_app remains the default channel).
- Ops note for the demo/eval instance: n8n's MCP endpoints need a single dedicated webhook replica in queue mode (verified constraint) — irrelevant single-instance, relevant if a shared demo n8n ever scales.

---

## 4. Program

Independent tracks; each PR ships alone. Sequenced against the SE program (SE-3 F,G · SE-4 H,I,J · SE-5a still queued):

| Wave | Content | Size |
| --- | --- | --- |
| **LF-1** | Repair: OTLP → Langfuse; delete v2 SDK span path; pin `langfuse>=4,<5`; SDK-surface rot-guard test; serverless `force_flush`; local docker-compose doc | 1 PR |
| **N8-0** | Wire `notification_channel` → `fire_action` on alert fire | 1 small PR |
| **LF-2** | Generations from `_record_llm_call`; session + org mapping; PRICES → model definitions; capture-window content policy | 1 PR |
| **N8-1** | `integrations/n8n/` templates + delivery doc | 1 PR, mostly JSON/docs |
| **N8-2** | Governed-brain doc + templates; verify FastMCP HTTP transport with n8n's MCP Client live | 1 small PR + live test |
| **LF-3** | Judge-on-traces config, annotation queue adoption, chat 👍/👎 → scores | 1–2 PRs |
| **N8-3** | Action packs: n8n MCP tools in Arc CI, HITL, capability-gated | after CI-1d |

Success measures (instrument, don't infer): LF — mechanical-feel regressions caught by a judge score moving before a user notices; cost dashboard agreeing with `obs/usage` to the cent; time-to-diagnose a bad answer (trace link vs log-grepping). N8 — an alert reaching Slack with zero aughor-side Slack code; one workflow calling `ask` in anger; first chat-initiated, human-approved action.

## 5. Open questions

1. **Langfuse host**: local-compose now + a small VM later, or straight to a VM? (Cloud free tier acceptable for operator-only, content-off traces?)
2. **Project topology**: single operator project (content capture off) vs per-org projects — decides whether tenants can ever see traces.
3. **Community node ambition**: is `n8n-nodes-aughor` + verified-node submission worth owning an npm package, or do HTTP/MCP templates suffice indefinitely?
4. **Demo n8n**: run one (docker, internal use — license-fine) for demos/templates CI, or keep n8n purely on the user's side?
5. **Chat feedback UI**: is a 👍/👎 on Arc CI answers wanted now (LF-3 prerequisite), or does judge-scoring alone suffice initially?
