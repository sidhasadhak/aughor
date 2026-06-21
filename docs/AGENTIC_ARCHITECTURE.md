# Agentic architecture — ideation

> Status: **ideation / no code change yet** (2026-06-21). A plan for evolving Aughor from
> "several autonomous processes" into a legible, supervised **agent fleet**. Grounded in the
> current code (`aughor/kernel`, `aughor/explorer`, `aughor/agent`, `aughor/monitors`,
> `aughor/knowledge`), not generic advice.

## TL;DR

We are **already ~80% agentic in plumbing, 0% formalized as a fleet.** Aughor runs several
autonomous/active processes on a real job-orchestration substrate (`JobKernel`) with an event
spine + per-run Trust Receipts. What's missing is naming the agents, giving them a supervisor,
letting them collaborate and act proactively, and a fleet view. The highest-leverage first move
is a **agent registry + fleet view** over data we already capture.

## 1. What already behaves like an agent

| Today (implicit) | Where | Agent-ness |
|---|---|---|
| Explorer | `explorer/agent.py::explore` (Phase 1–8), runs as a Job | Genuine background agent — autonomous, goal-directed |
| Deep Analysis (ADA) | `agent/investigate.py` (LangGraph: intake → plan → query → score → synthesize) | Active multi-step reasoner |
| Insight / Quick | `agent/nodes.py` | Lightweight tool-use answerer |
| Monitors | `monitors/runner.py` + `monitors/scheduler` | Background, but **rule-based**, not reasoning |
| Briefer | `knowledge/briefing.py::get_briefing` + brief scheduler | Synthesis + scheduled delivery |
| Profiler / governance | `profile/infer.py`, `revalidate_live`, ontology + metric governance | One-shot characterizers / validators |

The **substrate** is the part most platforms must build from scratch — and it already exists:

- `kernel/jobs.py` — supervised state machine (`PENDING→RUNNING→SUCCEEDED|FAILED|CANCELLED`),
  heartbeat, orphan recovery → a worker-pool supervisor.
- `kernel/ledger.py` + the append-only event journal + Trust Receipts → shared state + audit/trace.
- `kernel/errors.tolerate` → per-agent fail-open resilience.
- `monitors/scheduler`, `briefs/scheduler` — time-based triggers.

## 2. The gap (why it doesn't *feel* agentic yet)

1. Agents are functions/jobs, not first-class **roles** with a charter (role · goal · tools · budget · memory).
2. ADA is one **monolithic graph** — the SQL writer, the verifier, the narrator are *nodes*, not collaborating agents.
3. No **supervisor/router** that decomposes a goal across specialists and manages a task queue
   (today `classify_question` only picks a single mode).
4. **Reactive, not proactive** — nothing watches the event spine and self-assigns work. Monitors are
   `if value > threshold`, not "this moved, go find out why."
5. No **fleet view** — the trace data exists (event journal + receipts) but there's no dashboard of who's doing what.

## 3. The model: a supervisor + a blackboard, on the kernel we already have

- An **Orchestrator** decomposes a goal into tasks, posts them to the queue (`JobKernel`); specialists
  claim and run; results land on the shared **blackboard** (`ledger`); other agents subscribe to the
  event spine and react. That is the Hermes/fleet topology — worker pool, heartbeats, and event bus already exist.
- **Two lanes:**
  - **Background · always-on** — `Scout` (explore + discover), `Watcher` (watch KPIs · spawn work),
    `Curator` (keep ontology/metrics/profile fresh), `Briefer` (synthesize the verdict).
  - **Active · during an investigation** — `Analyst` (plan + root-cause) assembling
    `SQL Engineer` (grounded SQL + repair) ⇄ `Verifier` (stats · plausibility) ⇄ `Narrator` (grounded prose).
    ADA's nodes get **elevated into collaborating sub-agents**, each with its own context, tools, and budget —
    and the `Verifier` becomes the home for the trust gates already built (additivity, fan-out, plausibility).

## 4. Cross-cutting

- **Shared memory:** promote the ledger to a typed blackboard of hypotheses/findings/tasks agents read+write,
  plus per-agent memory (what each learned).
- **Inter-agent messaging:** agents emit/subscribe on the spine — `Scout` finds an anomaly → `Watcher` decides
  → spawns `Analyst`.
- **Observability (biggest "feels agentic" unlock):** a **Fleet view** over the event journal + Trust Receipts —
  live who/what/tokens/handoffs/outcome. Mostly a *view* over data already captured.
- **Human-in-the-loop + guardrails:** agents propose, human approves at gates (Action Hub / recommendation inbox);
  per-agent token/time budgets + the read-only SQL gate + a kill switch (`JobKernel` cancel exists).

## 5. What to borrow

- **LangGraph / LangSmith** (already using LangGraph): the *supervisor multi-agent* pattern to turn ADA's nodes
  into agents; LangSmith-style tracing → the Fleet view.
- **Hermes / fleet:** dispatcher + role-specialized worker pool + shared blackboard + heartbeats.
- **CrewAI / AutoGen:** the explicit *agent charter* (role · goal · tools) formalization.
- **Devin-style always-on:** a long-lived loop that watches state and self-assigns work → `Watcher`.

## 6. Phased roadmap (each step leans on existing infra)

- **Phase 0 — Formalize:** an agent **registry** (charter per role) + tag every job/event with its agent.
  Instant fleet semantics, near-zero new machinery.
- **Phase 1 — Fleet view:** a dashboard over the event journal + receipts. Highest perceived-agentic ROI for the least code.
- **Phase 2 — Supervisor + blackboard:** Orchestrator routes a goal across specialists; split ADA into
  `SQL Engineer` / `Verifier` / `Narrator`.
- **Phase 3 — Proactivity:** upgrade Monitors → a reasoning `Watcher` that auto-spawns investigations and drafts
  actions (human approves).
- **Phase 4 — Collaboration + memory:** agents subscribe to each other's findings; a `Critic` re-validates
  everything before it surfaces.

**Single highest-leverage first move:** Phase 0 + 1 (registry + fleet view) — it makes the autonomy we
*already run* legible as a fleet, with minimal new code.
