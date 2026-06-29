# Aughor → Interactive Data Agent: the 2026→2030 trajectory

*Date: 2026-06-28. A forward-looking brief triggered by **BIRD-INTERACT** (Huo et al., ICLR 2026
Oral; BIRD Team + Google Cloud + HKU; arXiv 2510.05318). Companion to the single-turn work in
`docs/SPIDER2_PROGRESS_AND_CHALLENGES_2026-06-28.md`. This is a **direction** document — disciplined
(gated, width-first, not score-chasing), not a commitment to build everything here.*

---

## TL;DR

- **The task is being redefined.** Text-to-SQL is moving from a single-turn "NL → one query" box to
  an **interactive data agent**: it detects ambiguity, asks the *right* clarifying question, recovers
  from errors, carries state across an evolving session, and spans the full CRUD cycle — not read-only
  `SELECT`.
- **The frontier is wide open.** On BIRD-INTERACT, **GPT-5 completes only 8.67%** (conversational) /
  **17.00%** (agentic) of tasks; the best model (Gemini-2.5-Pro) captures ~21–26% of reward. Nobody is
  close. This is a *capability* gap, not a saturated benchmark.
- **It is Aughor's lane.** The paper's most actionable finding: frontier models default to **trial-and-
  error** (`submit`-and-see) and *avoid* systematic schema/knowledge retrieval. Aughor's entire
  grounding substrate — schema linking, profiling, the query-log miner, the value index, the editable
  ontology, deterministic guards — **is exactly the strategic-exploration layer the raw LLM won't do.**
  BIRD-INTERACT is independent, rigorous evidence that *grounding-first is the right 2030 architecture*.
- **Aughor is already partway up the curve** (interactive modes, multi-step investigations, closed-loop
  repair, SOMA-style ambiguity *detection*). The missing pieces are specific, isolatable interaction
  *skills* — and a way to *measure* them.

---

## 1. The paradigm shift

Single-turn evaluation (Spider, BIRD, Spider 2.0) asks: *given a perfectly-formed question, can you
write the right SQL?* Real data work never looks like that. It is an **iterative, stateful dialogue
with evolving goals**: the first request is ambiguous, the first query errors, the result prompts a
follow-up that depends on what was just computed, and the cycle includes writes/DDL, not just reads.

BIRD-INTERACT argues prior multi-turn benchmarks failed for two reasons:
1. **Static transcripts** — every model is replayed against the *same* scripted dialogue, so you can
   neither reward intelligent interaction nor penalize a model that mishandles the conversation.
2. **Narrow scope** — `SELECT`-only, ignoring the `INSERT/UPDATE/DELETE/ALTER` + transactional cycle
   that is the real DBA/analyst job.

Its fix: a live **interactive environment** (executable DB + hierarchical knowledge base + metadata +
a **function-driven user simulator**), two evaluation modes, and a CRUD-spanning task suite with
**ambiguous initial sub-tasks + state-dependent follow-ups**, all guarded by executable test cases.

---

## 2. BIRD-INTERACT, grounded

- **Scale:** Full = 600 tasks (up to **11,796** dynamic interactions); Lite = 300 tasks (cleaner DBs).
  Built on LiveSQLBench (full DML/DDL, dynamic DB states, permissive license).
- **Two modes:** `c-Interact` (protocol-guided conversation) and `a-Interact` (open-ended agentic,
  ReACT — the model decides *when* to query the user / DB / docs). **9 discrete system actions** in
  a-Interact (retrieve knowledge, retrieve column meaning, get schema, execute SQL, ask, submit …),
  each with a *cost*.
- **Function-driven user simulator (two-stage):** an LLM first maps the system's clarification request
  to one of three **symbolic actions** — `AMB()` (a pre-annotated ambiguity), `LOC()` (a reasonable
  clarification located via AST retrieval over the gold SQL), `UNA()` (**rejects** inappropriate
  requests, e.g. attempts to elicit the answer) — *then* generates a response. This prevents
  ground-truth leakage and keeps the simulator controllable. **UserSim-Guard:** baseline simulators
  fail on Unanswerable questions up to **67.4%** of the time; the function-driven design cuts that to
  **2.7%**.
- **Ambiguity taxonomy (injected):** surface user ambiguity (intent-level "elderly people";
  implementation-level decimal precision), **knowledge-chain breaking** (mask an intermediate node in a
  multi-hop knowledge DAG so the model *must* ask), environmental (NULLs in critical fields).
- **Budget-constrained:** clarification turns capped by `τ = m_amb + λ_patience`; the system is told its
  remaining budget. You cannot over-ask. Stress-tested at low budget.

---

## 3. The seven ideas that matter

1. **Mode-fit is decisive.** GPT-5 is *worst* in c-Interact (14.5%) yet *best* in a-Interact (29.2%).
   The interaction *shape* matters as much as the model.
2. **Ambiguity is the core skill** — detect material ambiguity and ask the *right* question, rather than
   guessing.
3. **State-dependent follow-ups** — the novel contribution: a follow-up depends on **DB state modified
   by, or objects created by, prior queries** ("now filter *that* to last quarter"). Harder than the
   initial query for every model.
4. **Budget-aware interaction** — "how much to clarify" becomes an optimization (≈ ReFoRCE confidence-
   tiered probing, applied to *user* dialogue).
5. **Interaction Test-Time Scaling — the "ITS Law":** *given enough interactive turns, performance can
   match or surpass the idealized ambiguity-free single-turn task.* **Interaction is a scaling axis** —
   like test-time compute, but the resource spent is *grounded dialogue*.
6. **Memory grafting** — giving a strong-SQL/weak-interaction model (GPT-5) the *interaction histories*
   of better-interacting models lifts its score. **Interaction skill ≠ generation skill** — separable,
   trainable capabilities.
7. **The trial-and-error bias (most actionable)** — agents overwhelmingly `submit`-and-see + `ask` and
   **avoid** systematic knowledge/schema retrieval, a pre-training bias toward guessing over strategic
   exploration. *This is the gap Aughor's grounding substrate fills.*

---

## 4. Where Aughor sits on the curve

| BIRD-INTERACT capability | Aughor today | Gap |
|---|---|---|
| Detect material ambiguity | ✅ SOMA candidate-disagreement + FP-critique gate | — |
| **Ask** the right question (budget-aware) | ⚠️ likely *commits* an answer instead of asking | **the c-Interact skill** |
| In-loop error recovery | ✅ closed-loop execute→repair + deterministic guards | — |
| **State-dependent follow-ups** | ⚠️ conversational, but not over *modified DB state / created objects* | carry CTEs/created objects across turns |
| Strategic exploration vs trial-and-error | ✅ grounding substrate (schema linker, profiler, query-log miner, value index, ontology) | wire it into an agentic *budget* loop |
| CRUD beyond `SELECT` | ❌ read-only by design | strategic (stay read-first for safety) |
| **Measure** interaction skill | ❌ we measure single-turn EX only | a **user-simulator eval harness** |

**Aughor is already partway up the curve.** It has interactive modes (Insight / Deep-ADA / Explorer),
multi-step investigations, closed-loop repair, and ambiguity *detection*. What's missing are the
isolated interaction *skills* this paper names — and the measurement substrate for them.

---

## 5. Why this is Aughor's lane

The deepest result in the paper is finding #7: frontier models *won't* ground themselves — they guess
and resubmit. Aughor's whole thesis (proven across the Spider 2.0 work: *deterministic, execution-
grounded levers beat LLM machinery on strong models*) is the structural antidote. The grounding
substrate Aughor already built **is** the "strategic exploration" the benchmark says raw LLMs avoid.
BIRD-INTERACT independently validates the architecture — and adds the *interaction* dimension on top.

The ITS Law reframes cost: every grounded clarification/probe is not overhead, it's *scaling
investment* toward the idealized answer. The product framing writes itself — **an analytics colleague
that clarifies when it matters, recovers when it errs, and remembers what it just did.**

---

## 6. The gated roadmap

Each stage is BUILT → WIRED → TESTED → **LEVERAGED** (proven on the real path), measured before trusted.

1. **Interactive eval harness** — ⊘ *prototyped then removed.* A function-driven user simulator
   (AMB/LOC/**UNA** anti-leak) + an episode runner that scored *submitted* SQL against executable gold
   under a clarification budget — rewarding good clarification, penalizing blind guessing (the property
   static-transcript benchmarks lack). It was built first per the "let evidence pick the lever"
   discipline, then **removed in the 2026-06-29 consolidation** with the rest of the offline eval
   harness (the offline benchmark arc concluded — see SPIDER2_PROGRESS §14). The *design* above is the
   durable artifact; rebuild it against Aughor's real pipeline when the interactive axis is taken up.
2. **Budget-aware ambiguity clarification** *(next feature)* — when detected candidate-disagreement
   would *materially change the answer*, ask **one** targeted question within a budget instead of
   silently guessing. Reuses SOMA detection + the FP-gate discipline; validated by harness (1).
3. **State-dependent multi-turn** — carry created objects / CTEs across follow-ups; reason over modified
   DB state. Plus **HKB-as-traversable-knowledge-graph**: extend the editable ontology with multi-hop
   chains and "broken chain → ask".
4. **ITS as an explicit product loop** — spend interaction/grounding budget where it moves the answer;
   the long-horizon framing toward an autonomous, budget-aware data colleague.

---

## 7. Integrity / non-goals

- **Not chasing the BIRD-INTERACT score.** The win is the *product capability* (clarify, recover,
  remember), with the benchmark as a stress-test — the discipline held throughout the Spider 2.0 work.
- **Read-first.** CRUD/DDL agency is a market the paper maps, but Aughor stays read-first for safety;
  any write-capability is a separate, explicit decision.
- **Measure before trust.** No interaction feature is believed without the eval harness (stage 2) — at
  small n, anecdote is not evidence (see the single-turn measurement-noise lessons).

---

## 8. Open questions for a second opinion

1. Is **budget-aware clarification** the right first step, or should the **eval harness** come first so
   every later interaction feature is measurable from day one?
2. Does the **ITS Law** hold for a *grounded product* (where much "interaction" is the agent probing the
   DB/ontology, not the user)? If so, grounding depth is a tunable quality dial — what's the right
   budget policy?
3. How much of the **state-dependent follow-up** capability already falls out of Aughor's investigation
   /conversation memory, vs. needing explicit object/CTE carry-over?
4. Is there value in **memory grafting** internally — reusing the interaction traces of successful
   sessions (the query-log miner's cousin) to bootstrap weaker ones?
