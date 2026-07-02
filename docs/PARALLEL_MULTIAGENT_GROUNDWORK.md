# Parallel & Multi-Agent Groundwork — making the most of LangGraph

**Status:** groundwork for the next build cycle (not yet implemented).
**Trigger:** the womenswear-returns investigation took **~8.4 min**. This doc pins *why*,
what we already have, what we're missing from LangGraph's parallel/multi-agent toolkit,
and a prioritized plan that stays true to Aughor's deterministic-first thesis.

---

## 1. The pain point, correctly diagnosed

The 8.4 min is **not** slow SQL. The dimension queries in a phase already run **in parallel**
(`_parallel_execute_safe` at [`investigate.py:715`](../aughor/agent/investigate.py) — per-thread
reader connections via `ContextThreadPoolExecutor`, contextvar-propagated). The wall-clock is
dominated by **sequential frontier-model LLM calls across serial phases**:

```
route → exploratory_scan → ada_intake → ada_cross_section(plan → interpret) → ada_synthesize
  (1)        (1+)             (1–2)            (1 + 1 + guard retries)              (1 big)
```

≈ **7–12 serial LLM round-trips** on glm-5.2 (cloud), each seconds-to-tens-of-seconds. The graph
is a **linear chain of single-agent phases** — so LangGraph runs one node at a time and never uses
its parallel machinery. That is the miss.

## 2. What we already have (do NOT rebuild)

- **SQL-execution parallelism** within a phase — `_parallel_execute_safe` + `ContextThreadPoolExecutor`.
- **LangGraph 1.2.0** with the **`Send` map-reduce API available** (`from langgraph.types import Send`),
  a persisted `SqliteSaver` checkpointer, and `interrupt_before` (HITL / P3 plan gate).
- **Reducer-safe parallel state** — `investigation_phases` and `verification_checks` are
  `Annotated[list, operator.add]`, so parallel branches can append without clobbering. This is the
  exact idiom LangGraph map-reduce needs; **fan-out is low-friction because the state is already ready.**
- **Deterministic routing** + the **P6 budget governor** (`AUGHOR_MAX_TOKEN_BUDGET`, heartbeat cancel) —
  the guardrails a parallel fan-out needs to stay bounded.

## 3. What we're missing (the gaps)

- **G1 — No map-reduce fan-out on independent axes.** `Send` is available but unused. The genuinely
  independent work is serialized:
  - **Explore sub-questions** — `plan_and_execute_subq` runs **one sub-question per superstep** in a loop
    ([`explore.py:413`](../aughor/agent/explore.py)); independent sub-questions are a textbook `Send` fan-out.
  - **Cross-section dimensions** — SQL is parallel, but each phase is one serial step vs the others.
  - **Hypothesis testing** (investigate) — hypotheses are tested serially.
- **G2 — Linear graph → no parallel supersteps.** Pre-flight retrievals (KB, playbook, prior-analyses,
  scan, causal context) run inline/serially though they're independent and mostly non-LLM.
- **G3 — Monolith, not supervisor + specialist subgraphs.** The specialist charters (Scout / Analyst /
  SQL-Engineer / Verifier in `kernel/agents.py`) are **metering labels, not real graph agents**. There is
  no supervisor delegating to parallelizable specialists, and `run_analysis_phase` is a function, not a
  reusable **subgraph** that can be composed/parallelized/independently streamed.
- **G4 — Synthesis is one monolithic serial LLM call** (inherent — it needs all phases — but the phases
  feeding it could be parallel).
- **G5 — Streaming is phase-serial**, not merged from concurrent branches.

## 4. The plan (prioritized) — deterministic fan-out first

Aughor's thesis is **deterministic control > LLM machinery** (proven repeatedly). That directly informs the
choice: prefer **deterministic map-reduce fan-out** over an **LLM supervisor/swarm**. Current cost data backs
this — subagent-with-parallel ≈ 5 calls / 9k tokens vs handoff-swarm 7+ calls / 14k tokens. Aughor's routing
is already deterministic, so an LLM supervisor would add latency + cost for a decision we don't need an LLM to make.

- **P-A (IMMEDIATE NEXT): map-reduce the explore sub-question chain via `Send`.** Independent sub-questions
  become parallel branches, reduced through the existing `operator.add` state. Clearest win, lowest risk.
  Then apply the same to hypothesis testing and (if it helps) per-dimension cross-section mini-agents.
  Target: N independent units in ~1× wall-clock instead of ~N×.
- **P-B: parallelize the pre-flight retrievals** (KB / playbook / prior-analyses / scan) as concurrent
  nodes — near-free wall-clock (little/no extra LLM cost).
- **P-C: refactor `run_analysis_phase` into a phase subgraph** so phases compose and can run concurrently.
- **P-D (bigger, later): supervisor + real specialist subgraphs** — only if A–C don't close the gap; keep
  the *router* deterministic and use LLM agents only for genuinely open sub-tasks.

## 5. Guardrails (must hold under parallelism)

1. **Budget + rate limits** — parallel LLM calls multiply token spend and concurrency. Every fan-out MUST
   run under the **P6 governor** (per-run token cap) and a **fan-out width limit** (the concurrency executor
   already caps workers). A runaway map is exactly what P6 exists to stop.
2. **Determinism / ordering** — merge via `operator.add` (order-independent); any "lead with the top finding"
   logic must **sort post-merge**, never rely on branch completion order.
3. **Failure isolation** — one branch's error must drop to a skipped/partial finding (mirror
   `_parallel_execute_safe`'s serial fallback), never fail the whole map.
4. **Checkpoint/resume + HITL** — verify `Send` branches interact correctly with the SqliteSaver checkpointer
   and the P3 plan-gate interrupt (resume of a partially-completed map).
5. **Streaming** — merge SSE events from concurrent branches without starving the client (per-branch progress).

## 6. First concrete task for next session

Convert the explore sub-question loop to a `Send` map-reduce:
- `decompose_exploration` → emits one `Send("plan_and_execute_subq", {subq})` per **independent** sub-question
  (respect `depends_on`: only fan out the ready set; keep dependent ones staged).
- `plan_and_execute_subq` becomes stateless per-branch (reads its own `subq`, appends its answer via the
  `operator.add` reducer).
- `reason_over_result`/synthesis reduces the merged answers.
- **Bounded** by a width cap + the P6 budget; **measured** by wall-clock on a multi-sub-question explore run
  (before/after) and no accuracy regression on the P0 ratchet.

---

**Sources:** LangGraph docs (Send / map-reduce, subgraphs, supervisor vs swarm); current landscape summarized in
[Multi-Agent Orchestration in LangGraph (Supervisor vs Swarm)](https://dev.to/focused_dot_io/multi-agent-orchestration-in-langgraph-supervisor-vs-swarm-tradeoffs-and-architecture-1b7e),
[Scaling LangGraph Agents: Parallelization, Subgraphs, and Map-Reduce](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization),
[LangGraph Map-Reduce with the Send API](https://machinelearningplus.com/gen-ai/langgraph-map-reduce-parallel-execution/).
