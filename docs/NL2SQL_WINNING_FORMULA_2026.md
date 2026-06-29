# NL2SQL winning formula — 2025/2026 SOTA, synthesized for Aughor

> **Status:** research synthesis + implementation direction (2026-06-30). Distils the
> 2025/2026 text-to-SQL literature into the few moves that durably help **Aughor**,
> given Aughor's hard-won prior conclusions. The companion implementation is the
> deterministic complexity-aware router (§5).

## 1. Sources mined

- **[NL2SQL Handbook (HKUSTDial)](https://github.com/hkustdial/nl2sql_handbook)** — the
  curated survey. Taxonomy: pre-processing (schema linking, retrieval) → translation
  (prompting / fine-tuning / **agentic reasoning**) → post-processing (validation,
  self-correction, execution feedback). 2025 systems it highlights: Alpha-SQL (MCTS),
  **EllieSQL** (complexity-aware routing), CHASE-SQL (multi-path + candidate selection),
  DIVER (value linking), Sphinteract / CLEAR (ambiguity), MARS-SQL / CSC-SQL / Reward-SQL
  / Arctic-Text2SQL-R1 / SQL-o1 (RL + tree search), **SquRL / Hexgen-Flow** (learned/
  scheduled agentic workflows), Agentar-Scale-SQL (test-time scaling, BIRD top-1),
  DCG-SQL (schema-link graph), NL2SQL-BUGs / SQLMorph (semantic-error eval).
- **[SQLBot (DataEase)](https://github.com/dataease/SQLBot)** — production chat-BI:
  RAG over schema + **business terminology/glossary** + **curated SQL examples**
  (few-shot calibration) + fine-grained permissions + workspace isolation + continuous
  improvement from user-interaction data.
- **[Oracle NL2SQL-Agent (MCP)](https://blogs.oracle.com/cloud-infrastructure/nl2sql-agent-mcp-powered-data-insights)**
  — a LangGraph agent over an **MCP** tool surface (Schema Explorer, Metadata Lookup,
  Business Glossary, Data Profiling, Execute Query [governed read-only], Data Insights).
  Principle: **"bring the AI to the data"** (context close to data = quality/speed/
  security); least-privilege governed execution; **per-tool LLM optimisation** (use a
  SQL-optimised model for generation).
- **[BIRD-INTERACT](https://arxiv.org/abs/2510.05318)** (= OpenReview
  [`nHrYBGujps`](https://openreview.net/forum?id=nHrYBGujps)) — re-imagines evaluation as
  **dynamic multi-turn interaction**: a user simulator + hierarchical KBs, c-Interact
  (protocol) and a-Interact (agentic), full CRUD. GPT-4o completes only **8.67%**
  (c-Interact) / **17%** (a-Interact). Takeaway: production wins come from **interaction
  orchestration** — knowing *when* to clarify, retrieve, probe, and self-correct — not
  from better one-shot generation. (Sibling: "Improving Text-to-SQL under Ambiguity".)

## 2. What the field converges on (2025/2026)

Five themes recur across every source:

1. **Ambiguity is the #1 unsolved problem** → clarify / probe before committing
   (BIRD-INTERACT, Sphinteract, CLEAR, SOMA-SQL, the ambiguity benchmark).
2. **Test-time scaling = allocate compute by difficulty** → cheap path for easy queries,
   heavy path (candidates, search, frontier model) for hard ones (EllieSQL, SquRL,
   Agentar-Scale, Hexgen-Flow, Arctic-R1, ReForce's confidence-tiered probing).
3. **Candidate generation + execution-grounded selection** (CHASE-SQL, CSC-SQL).
4. **Schema linking at scale + DB-info compression** for wide schemas (DCG-SQL, ReForce).
5. **Grounding wins**: business glossary, metadata, curated examples, governed read-only
   execution, "bring AI to the data" (SQLBot, Oracle).

## 3. Cross-reference with Aughor (have vs gap)

**Aughor already embodies the grounding consensus** (this is its moat, and the research
validates it): ontology + metrics + glossary grounding, trust receipts, a governed
read-only security/audit gate, CHESS value-index + filter-literal binding, schema
linking, the MCP surface of *governed intelligence* tools, the inference plane
(per-Org/Workspace/Agent model binding), and deterministic correctness **guards**
(grain / fan-out / value-domain). Aughor's candidate-disagreement + execution-grounded
probing (SOMA-SQL) and confidence-tiered repair (ReForce) are already noted as wins.

**Aughor's durable prior conclusions** (do not violate): on a *strong* model,
**deterministic guards beat added LLM machinery** (proven repeatedly); the **frontier
model is the accuracy ceiling**; the offline single-shot accuracy arc is *concluded*
(100% is impossible — gold itself is ~53–66% wrong on some benches); **reject bench-only
shims**; **don't rebuild removed machinery**.

**The gap that is high-value, durable, and conclusion-respecting:** Aughor allocates the
**same** model + pipeline depth to every question. The strongest 2025 production lever —
**complexity-aware / cost-tiered routing (test-time scaling)** — is *absent*. It is:
deterministic (a difficulty assessor, not LLM machinery — respects "guards win"); a
**cost/latency** win (not accuracy that can't beat the ceiling — so it's durable, not a
bench shim); and it composes perfectly with the existing inference plane (per-agent model
binding). Routing is exactly what EllieSQL/SquRL/ReForce/Oracle's per-tool-LLM all do.

## 4. The winning formula (Aughor-specific)

> **ASSESS → ROUTE → (CLARIFY | GENERATE) → VERIFY**, where **ASSESS is deterministic.**

A deterministic **difficulty + ambiguity assessment** of (question × linked schema):
- **routes compute** — easy → a cheap/fast model + single shot; hard → the frontier
  model + the existing candidate/verify depth (the test-time-scaling lever); and
- **gates clarification** — when ambiguity is high, surface a clarification (or an
  execution-grounded probe) instead of guessing (the interaction lever, BIRD-INTERACT).

This fuses the two strongest 2025 signals, both **gated by a deterministic assessor**
(so it honours "guards > LLM machinery"), and it pays in **cost + intent-grounding**
rather than chasing accuracy past the model ceiling. The grounding substrate Aughor
already has is the antidote BIRD-INTERACT calls for; routing + clarification are the
missing orchestration around it.

## 5. Implementation (this round): the deterministic complexity router

Build the **ASSESS → ROUTE** half first (the clarification half is the larger 2030
interactive arc; this lays its foundation — the same assessment signal gates it later):

- A deterministic `assess_complexity(question, schema_context) -> ComplexityVerdict`
  scoring difficulty from cheap, explainable signals: candidate-table/column count
  (schema-link breadth), implied joins, aggregation/ranking/temporal/window/nested
  markers in the question, and ambiguity markers (vague references, missing time window,
  under-specified metric). Tiers: `simple | moderate | complex`.
- A routing policy `route_for(verdict)` → the model role/binding + pipeline depth,
  consumed through the existing inference plane (per-agent model override) so a cheap
  model serves simple questions and the frontier model serves complex ones.
- Wired at the question-routing seam; metered (the receipt records the tier + the model
  chosen) so the leverage is observable and the policy is tunable.

Acceptance: deterministic + unit-tested; the receipt shows the chosen tier/model; on the
real path a simple question demonstrably binds the cheaper tier and a complex one the
frontier tier, with no regression to the trust guards.
