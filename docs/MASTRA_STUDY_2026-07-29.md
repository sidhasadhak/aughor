# Mastra study — the agent-framework comparison (2026-07-29)

Studied: [mastra.ai](https://mastra.ai) + [github.com/mastra-ai/mastra](https://github.com/mastra-ai/mastra),
against the repo at `main = db86afd` (Wave S4). Companion to the Cognee/Neo4j studies
(`COGNEE_STUDY_2026-07-28.md`) and the Databricks teardown — same question: what does a
well-funded adjacent stack have that we lack, and what do we have that it cannot copy?

**Verdict up front: adopt shape, not dependency** (the same verdict as Cognee — Mastra is a
TypeScript runtime; our backend is the product). Four shapes are worth taking; one product
fact changes our positioning: **Mastra charges Enterprise for UI-based agent creation, and
our agents are already data, not code** — we can ship in the open product what they license.

---

## 1. What Mastra is (verified 2026-07-29)

TypeScript agent framework from the Gatsby founders (YC W25; ~$13M seed + $22M Series A
led by Spark, 2026-04; ~26.7k stars; >1.8M monthly npm downloads; cited adopters Plaid,
Replit, Adobe). **1.0 stable 2026-01-20**; `@mastra/core` ships a minor every 2–5 days.
Anything written about Mastra before ~Nov 2025 describes a materially different framework:
Playground→Studio rename, Mastra Cloud → "Mastra Platform" (separate hosted Studio +
Server, CLI deploys), and the two-step deprecation AgentNetwork → `.network()` →
plain supervisor agents.

Primitives: `Agent` (instructions + `"provider/model"` string + tools + memory +
sub-agents + scorers), `createTool` (zod/valibot/arktype schemas, `requireApproval`),
`createWorkflow`/`createStep` (`.then/.parallel/.branch/.dountil/.foreach/.map`,
per-step `retries`, workflow `retryConfig`, cron `schedule:`), one `Mastra` registry
instance, `mastra build` → a Hono REST server. Memory = threads + working memory +
semantic recall + observational memory over pluggable stores. RAG, model router
(5k+ models, fallback arrays), MCP client/server, AI-SDK streaming compat.

The parts that matter for us:

- **Studio** (the control room): one UI — chat with agents, live workflow graph with the
  active step highlighted, run history, schedules with pause/resume + trigger history,
  traces/logs/metrics, scorer results, live model/temperature tweaking.
- **Suspend/resume everywhere**: any step can `suspend()`; state persists as a snapshot
  in a `workflow_snapshots` table surviving deploys; `run.resume()` callable from any
  endpoint or timer. Tool-level human approval pauses the stream (`tool-call-approval`
  → approve/decline). Durable agents (2026, beta): the agentic loop runs inside a
  workflow, clients disconnect/reconnect, crash recovery re-drives orphaned runs.
- **Live sampled scorers**: evaluators (faithfulness, hallucination, tool-call accuracy,
  14 LLM-judge + a dozen rule-based) attach to agents with `sampling: {type:'ratio'}`
  and score **production** traffic non-blocking; results land in `mastra_scorers` and
  render in Studio; `runEvals()` for CI thresholds.
- **The authoring tiers** — the strategic fact: OSS Studio **cannot create agents**.
  The OSS *Editor* only overrides instructions/tools of code-defined agents (with
  draft→publish→archive versioning). Full UI creation — "Agent Builder": multi-tenant,
  RBAC, model policies, chat channels — is under the source-available **Mastra
  Enterprise License**; production use requires a paid license.
- **They walked away from LLM routing**: AgentNetwork (LLM-routed multi-agent) was
  deprecated twice over, landing on supervisor agents where delegation is ordinary tool
  calls. The industry converging on the stance we took deliberately (the R4 ablation;
  `UNIFIED_ANSWER_PATH.md` §"why an LLM mega-orchestrator is explicitly out").

## 2. How the stacks line up

| Layer | Mastra | Aughor |
|---|---|---|
| Agent | One first-class class, code-defined | Three tiers: fleet charters (`kernel/agents.py`, descriptive + governed budgets), **UserAgent personas** (`user_agents/`, data rows with goldens + measured pass chip), hard-coded pipelines (`agent/graph.py`) |
| Workflow | Portable step/workflow, typed I/O, retries, snapshots | One LangGraph (answer path) + job kernel (**no retry primitive**) + automations `Condition`/`Effect` + ad-hoc loops |
| Suspend/resume | Any step, persisted, resume from anywhere | Real but only in the answer graph (`interrupt_before` on 3 nodes) |
| Scheduling | One `schedule:` field, one Studio view | **Three schedulers** (monitors, briefs, automations heartbeat); `automations/adopt.py` built, default-OFF |
| Control room | Studio: one run-centric surface | The data exists (ledger, `session_events` `llm_call`, task_history, automation runs, receipts) scattered across 4 workspaces |
| Evals | Live sampled scorers + CI | Deeper machinery (replication, flaky detection, noise floors, `GraduationDecision`) but suite-run only — nothing samples live traffic |
| Governance | `requireApproval`; auth on Studio | Far ahead: 91 flags (off = byte-identical), kinetic inbox (resolve-once + standing grants), clearance trim, one-table RBAC, usage attribution |
| Trust | Traces | **No counterpart**: HMAC receipts, one caveat assembler, graduation receipts, provenance-required graph, deterministic SQL guards |

Aughor's abstractions are **vertical planes** every feature consumes (flags, ledger,
metering, receipts, guards) with almost no horizontal composition primitive; Mastra is
the mirror image — excellent horizontal primitives, nothing in our trust/governance/
quality territory. Our moat sits *below* orchestration and survives any orchestration
change.

## 3. Dispositions

| # | Take | Home |
|---|---|---|
| 1 | **Agents-as-product**: compose UserAgents + charters + the automations `investigate` effect + receipts into "create an analyst agent, schedule it, watch its runs" | **Wave H** — `WAVE_H_HIRED_AGENTS.md` (scoped) |
| 2 | **Run-centric control room**: one Runs surface over existing stores (jobs, session_events, automation runs, receipts) | Wave S design pass (S1–S3); H3 ships the per-agent slice first |
| 3 | **One scheduler + kernel retry**: graduate `automations.adopt_legacy` (built, OFF); add a bounded retry policy to `kernel/jobs.py` (today `attempt: 1` forever) | Standalone graduation + a small kernel PR |
| 4 | **Live sampled scorers**: attach registered evaluators (`evals/builtins.py`) to a sampling ratio of live traffic → existing evals store; feeds S3's accuracy-as-product-number | Rides S3 |
| 5 | **Editor-tier versioning** for UserAgent instructions (draft→publish, restorable) | H6 (optional) |

**Do not adopt**: the dependency itself (TS runtime, wrong layer); a general
`.then/.branch` workflow engine — the automations law (*an Effect references an existing
primitive, never a new action type*, `automations/models.py:103`) is a governance feature,
not a gap; LLM-routed agent networks (even Mastra deprecated theirs).

Sources: mastra.ai/docs (agents, workflows, studio, editor, agent-builder, evals,
observability, deployment), the 1.0 announcement and Series A posts, the GitHub repo and
release feed. All claims re-checked against post-1.0 docs — the pre-1.0 blogosphere is
stale on Studio/Cloud/networks.
