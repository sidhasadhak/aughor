# Parallel & Multi-Agent Groundwork — making the most of LangGraph

**Status:** **P-A SHIPPED (2026-07-02, flag `explore.parallel_subq`, default off)** — explore
sub-questions now run as dependency-respecting parallel *waves*. P-B/P-C/P-D still open.
**Trigger:** the womenswear-returns investigation took **~8.4 min**. This doc pins *why*,
what we already have, what we're missing from LangGraph's parallel/multi-agent toolkit,
and a prioritized plan that stays true to Aughor's deterministic-first thesis.

---

## 0. P-A shipped — what landed and how it was decided

Grounding the plan against LangGraph 1.2.0 surfaced two facts the groundwork didn't have, and they
drove the engine choice (the "SOTA call"):

1. A LangGraph `Send` branch sees **only its payload**, not channel state — a Send worker would have to
   be handed a fully self-contained payload.
2. **LangGraph does NOT propagate contextvars into its branch threads** (verified empirically). Aughor's
   metering accumulator, the P6 token budget, and `current_job_id` all ride on contextvars — so a naive
   `Send` fan-out would **silently drop cost attribution and defeat budget enforcement** (guardrail #1).

The codebase already solved exactly that with **`ContextThreadPoolExecutor`** (`copy_context()` per
submit — the reason `_parallel_execute_safe` uses it), and `RunMetrics` is already `threading.Lock`-guarded
for concurrent recording. So P-A fans out **in-process over `ContextThreadPoolExecutor`, not `Send`**:
metering/budget/job-id propagate for free, every guardrail holds by reusing proven infra, and the graph
structure / checkpointer / HITL are untouched. LangGraph *does* run parallel sync branches concurrently in
threads (also verified), so `Send` remains a clean future migration if per-branch streaming/partial-resume
ever becomes the driver — the per-sub-question work is already factored into a reusable core for that.

**Implementation** (`aughor/agent/explore.py`, `graph.py`, `kernel/flags.py`):
- Reusable cores extracted behavior-preservingly from the sequential nodes: `_scan_one_subq`,
  `_execute_one_subq`, `_reason_one_subq` (each pure w.r.t. graph state).
- `plan_and_execute_wave` computes the **ready set** (`_ready_subqs`: not done + every `depends_on`
  done), fans it out (each branch: own `make_reader()` → scan → plan+execute → reason → one answer),
  merges through the existing `operator.add` channels, and `route_after_wave` loops it until the chain
  is exhausted. `_apply_wave_results` marks done + injects each refinement into its **dependents** (the
  dependency-correct generalization of the sequential "inject into the next") + appends promotions.
- **Guardrails held:** budget-abort (a branch `BudgetExceeded` re-raises out of the wave), determinism
  (answers sorted by planned index post-merge, never completion order), failure isolation (one branch's
  error → an inconclusive answer, never fails the wave; serial fallback on executor failure), width cap
  (`AUGHOR_EXPLORE_PARALLEL_WIDTH`, default 4) under the P6 token budget. 15 unit tests; full suite green.

**Measured on the real path** (luxexperience, 33 tables, glm-5.2 cloud): a question decomposed into a
**width-3 parallel wave** (region ∥ product-line ∥ channel). Serial **172.6s** → wave **116.9s** =
**1.48× / −55.7s on one wave**, identical answer set, zero errors. The realized win per investigation is
gated by how much independence the (still sequential-biased) planner emits — the natural P-A+ follow-up is
to teach the decompose prompt to emit **accurate `depends_on`** (only real data dependencies) so more cuts
land in the same wave.

### 0b. ADA parallel multi-lens cross-section (2026-07-02, flag `ada.parallel_lenses`, default off)

The explore wave (§0) doesn't help a **cross-sectional Deep-Analysis** ("why is X high?") — grounding the
womenswear-returns run showed it's a 3-stage *serial dependency pipeline* (`ada_intake` → `ada_cross_section`
→ `ada_synthesize`, ~146s), where the per-dimension SQL is already parallel (`_parallel_execute_safe`) and
there's only one analysis phase. So instead of raw speedup, the parallelism win is **depth-per-second**: the
single bundled scan is split into independent themed **lenses that run concurrently** — `_partition_dimensions`
groups the intake dimensions into **segment/WHERE** (brand, tier, platform) ∥ **mechanism/WHY** (reason,
condition, carrier, refund method), and `ada_cross_section_multilens` runs one `ada_cross_section` per group
over the same `ContextThreadPoolExecutor` (own `make_reader()` clone each), reusing all the scan's guards.
`ada_synthesize` already reasons over every phase in `investigation_phases`, so the extra lens is picked up
free. Degrades to the single scan when the dimensions don't split; budget-abort + failure-isolation + a
serial fallback mirror the explore wave. Flag-gated (byte-identical when off); +10 tests.

**Measured (controlled back-to-back A/B, luxexperience/glm-5.2):** baseline single scan **69.5s / 1 phase /
6 findings** → multilens **56.4s / 2 phases / 9 findings** = **0.81× wall-clock (−13.1s) with 50% more
evidence** (each lens plans/interprets a smaller focused context and the two overlap). **Live-verified in the
platform canvas**: the womenswear Deep-Analysis rendered both "Cross-Sectional Scan — Where" (luxury platforms
40.5% vs off-price 27%) and "Mechanism / Reason Scan — Why" (reason/carrier/condition/refund all uniform → a
*systemic*, not dimension-specific, problem) as distinct phase cards, synthesized together. *Caveat: a single
throttled cloud endpoint (`AUGHOR_LLM_MAX_CONCURRENCY=4` + backoff) can erase the flat-latency benefit under
load — an uncontrolled run measured 537s when the endpoint was globally slow; the controlled A/B is the honest
number. A follow-up is reconciling the two lenses' grain (the WHY lens read item-level ~76% vs the WHERE lens's
order-level ~40%).*

### 0c. Temporal WHEN lens + forward-chain period drill (2026-07-02, same `ada.parallel_lenses` flag)

A flat cross-sectional average can hide a **period concentration** (a brand/category whose returns spiked in a
season, dragging the yearly number) — and a **brand×period interaction** is exactly the blind spot of the
WHERE/WHY lenses. Grounding the womenswear run exposed a real bug feeding this: the **intake declared the
question non-temporal** (`date_column=NONE` / `returns.return_date`) because `order_items` has no date and the
event table's date only covers returned items — so the agent *never looked* at time, even though the purchase
date is join-reachable. The fix is deterministic (not a prompt gamble): **`_resolve_temporal_axis`** probes the
live DB (`information_schema`, robust to the data-catalog schema form) for a **population/order date**, and for
an event-RATE metric **excludes the event table's own date** (`_EVENT_TABLE_RE`) — so a return rate trends on
`orders.order_date`, never `returns.return_date`. A **WHEN lens** (`_run_temporal_lens`, a `run_analysis_phase`
that returns a `period · metric_value · n` series) runs concurrently with WHERE/WHY; **`_detect_anomalous_period`**
deterministically flags a period only when it's materially above the sample-weighted baseline (>20% *and*
>1.5σ) on a material sample (guards out small-n blips). If a period is flagged, a **forward-chain drill**
(`_run_period_drill` → `ada_cross_section(period_directive=…)`) re-runs the segment/mechanism scan **scoped to
that period** to find which cut concentrated inside it — the temporal→detect→drill workflow. +8 tests.

**Live-verified (luxexperience/glm-5.2):** resolver recovered `orders.order_date` (fixing the blindness); the
WHEN lens computed the real monthly womenswear return rate (`AVG(returned)*100` over the order date) at a flat
**31–35%** across 2020–2025 and interpreted *"remarkably stable… no single month or quarter deviates"*;
`_detect_anomalous_period` returned **None** → the drill honestly did **not** fire (the drill firing on a real
spike is unit-tested). So the agent now *looks* at WHEN and would drill a genuine period concentration — this
synthetic data simply has none.

### 0d. Output-quality fixes — event-dim composition + scoped fan-out caveat (2026-07-02)

Reading the live womenswear report surfaced *"a lot of calculations could not be computed."* Diagnosis: **0
findings actually errored** — the SQL-error retry never fired because the queries ran *clean but meaningless*.
The WHY lens computed "return **rate** by reason/condition/carrier/refund_method/restocked" = **100% for every
value** — a tautology, because those columns live only on *returned* rows (the denominator is only returned
items). The guards *detected* it and only **caveated** it; they never reattempted. Fixes: **(#1)**
`_partition_dimensions` now classifies by the dimension's **TABLE** (`_is_event_dim` via `_EVENT_TABLE_RE` —
the old name regex mis-routed `restocked`), routing event-only dims to a new **`_run_composition_lens`** that
computes **share-of-returns** instead of a rate. **(#3)** the numeric fan-out backstop is now **per-SQL**
(collect `_fanned_sqls`, no early break) so a genuinely-fanned finding no longer tars its clean siblings.
**Live-verified**: the WHY lens now returns **size_fit 42.2% / not_as_expected 21.9% / changed_mind 19.9% /
quality 10.2% / late_delivery 5.9%** (the real "why" — sizing) instead of 100%/100%/100%, and the correct
platform finding renders **un-caveated**. *Follow-ups: reattempt-on-degenerate (a general safety net — its main
target, the event tautology, is now fixed at the root by #1) + surface discriminating population attributes the
intake missed (`products.retail_price_eur`: return rate climbs 31%→40% with price).*

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

- **P-A ✅ SHIPPED (2026-07-02): parallel *waves* over the explore sub-question chain.** Independent
  sub-questions run as concurrent branches reduced through the existing `operator.add` state — but via
  in-process `ContextThreadPoolExecutor`, **not** `Send` (see §0 for why: contextvar-borne budget/metering).
  Measured 1.48× on a width-3 wave. **Next within P-A:** teach the decompose planner to emit accurate
  `depends_on` (wider waves), then apply the same wave pattern to hypothesis testing / per-dimension
  cross-section mini-agents. Target: N independent units in ~1× wall-clock instead of ~N×.
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
