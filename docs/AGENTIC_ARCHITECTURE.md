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

- **Phase 0 — Formalize:** ✅ **SHIPPED (2026-06-21).** Charter **registry** (`kernel/agents.py`: role · goal ·
  lane · job_kinds · tools · budget; Scout + Analyst live, Watcher/Briefer/Curator reserved) + per-Org
  **governance** (enable/pause + budget, override-wins, ledger-kv) + `/agents` roster with spend + the **Scout
  enable-gate** on background exploration + a Fleet "Agents" management tab; every job is agent-tagged via
  `charter_for_kind`. — an agent **registry** (charter per role) + tag every job/event with its agent.
  Instant fleet semantics, near-zero new machinery. *Add **cost/compute metering** here (LLM tokens +
  warehouse rows/bytes + wall-time → `kernel/ledger.py` receipt + job row) — a charter's **budget** is
  unenforceable until you measure spend (MotherDuck makes this structural via per-Duckling CU-seconds; we
  make it provenance). See [`MOTHERDUCK_LEARNINGS.md`](MOTHERDUCK_LEARNINGS.md) R1.*
- **Phase 1 — Fleet view:** a dashboard over the event journal + receipts. Highest perceived-agentic ROI for the least code.
  *Build the backend as a thin **`/jobs` REST + tool surface over the existing ledger API**
  (`jobs_where`/`job_get`/`cancel`/`events`/`receipt` already exist; only the HTTP/tool layer is missing —
  today just `/events/stream` SSE). Name it `list`/`get`/`logs`/`cancel` after MotherDuck's **Flights**
  tools — that same layer becomes the MCP job tools. See [`MOTHERDUCK_LEARNINGS.md`](MOTHERDUCK_LEARNINGS.md) R2.*
- **Phase 2 — Supervisor + blackboard:** Orchestrator routes a goal across specialists; split ADA into
  `SQL Engineer` / `Verifier` / `Narrator`. *The `Verifier` is the home for a **typed SQL-error taxonomy**
  (`parser | binder | semantic | runtime`, à la MotherDuck's `try_bind`) that **routes repair by type**
  instead of by regex string — promote the existing `_make_diagnosis`/`tools/error_classifier.py`. See
  [`MOTHERDUCK_LEARNINGS.md`](MOTHERDUCK_LEARNINGS.md) R3.*
  - **◑ Started (2026-06-21) — the safe, careful first move:** each ADA phase already runs a
    SQL-Engineer → Verifier → Narrator micro-cycle inside `run_analysis_phase` (plan+execute → trust-guards →
    interpret); those hand-offs were implicit local variables. We made them **explicit, typed contracts**
    (`agent/handoff.py`: `SqlEngineerHandoff`/`VerifierHandoff`/`NarratorHandoff`) and journal each as an
    **`agent.handoff` event** so the collaboration is legible in the Fleet view / receipt — **additive and
    fail-open, no pipeline logic changed** (one insertion at the phase's clean seam). The specialists are
    registered (`kernel/agents.SPECIALISTS`) for hand-off identity. *Deliberate follow-ups (the riskier
    structural work): a standalone Verifier node owning the guards + the R3 error taxonomy; immutable premise
    correction (today it mutates `_ada_intake` mid-run); the Orchestrator decomposing across phases.*
- **Phase 3 — Proactivity:** upgrade Monitors → a reasoning `Watcher` that auto-spawns investigations and drafts
  actions (human approves).
- **Phase 4 — Collaboration + memory:** agents subscribe to each other's findings; a `Critic` re-validates
  everything before it surfaces.

**Single highest-leverage first move:** Phase 0 + 1 (registry + fleet view) — it makes the autonomy we
*already run* legible as a fleet, with minimal new code.

## 7. MotherDuck cross-check (2026-06-21)

A deep study of MotherDuck — the closest "AI + SQL + analytics" platform — both **validates this plan** and
hands us two ready-made surfaces. Full record: [`MOTHERDUCK_LEARNINGS.md`](MOTHERDUCK_LEARNINGS.md); backlog
in [`../ROADMAP.md`](../ROADMAP.md) §3.

- **It validates the moat.** MotherDuck's own benchmark (DABstep) reaches 100% only when domain knowledge
  moves into a **governed semantic layer** over raw tables, and their stated trust differentiator ("every AI
  answer shows its SQL") *is* Aughor's Trust Receipts. An engine vendor published the evidence that you need
  the governed-layer-plus-trust stack this fleet is built around — and Aughor already has the layer + guards
  + provenance their thin agents lack. **The `Verifier` and the governed-metric grounding are the point, not
  an add-on.** (Prove it with a semantic-layer *ablation* eval — `MOTHERDUCK_LEARNINGS.md` R4.)

- **Two surfaces to borrow, both thin layers over infra we already have:**
  1. **The Flights job-API contract** (`run`/`list_runs`/`get_run_logs`/`cancel`) → the shape for Phase 1's
     fleet-view backend over our ledger (R2).
  2. **The MCP tool contract** → how the fleet becomes **externally addressable**. The differentiator: expose
     *governed intelligence* tools (`ask`+receipt, `deep_analysis`, `get_metric`, `list_findings`,
     `get_briefing`, `explore`, `jobs`), **not** raw `query`. MotherDuck makes the client smart; we make the
     tool smart (R5; enriches the deferred MCP item in ROADMAP §3).

- **What it confirms we should NOT do:** become a warehouse, or move the intelligence into a columnar
  `prompt()`. Aughor's edge is warehouse-agnostic intelligence + trust; MotherDuck-as-backend is an optional
  serving tier (R6), and AI-as-a-SQL-operator a governed +1 (R8), never the foundation.

**Revised first move (unchanged in spirit, sharpened):** Phase 0 + 1 — registry + fleet view — but fold in
**cost metering** (R1, so charters carry real budgets) and build the fleet view as the **`/jobs` ledger
surface** (R2) that doubles as the MCP job tools.
