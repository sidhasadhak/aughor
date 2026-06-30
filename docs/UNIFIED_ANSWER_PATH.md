# One door: merging Insight and Deep into a single conversational analyst

*Design document — 2026-06-30. Status: **Phases 0–4 (core) shipped** — the unified `/ask` door + router;
the auto + transparency frontend (incl. answer declutter + on-demand "Explain the data"); the interactive
eval harness; ask-vs-guess clarification; and conversational session state (follow-up detection +
result-digest context, live-verified). Phase 5 + the 4b/3b deepenings proposed. Companion to
[`MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md`](MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md)
(what the modes share today), [`NL2SQL_WINNING_FORMULA_2026.md`](NL2SQL_WINNING_FORMULA_2026.md)
(the ASSESS→ROUTE formula this productizes), and
[`INTERACTIVE_DATA_AGENT_VISION_2030.md`](INTERACTIVE_DATA_AGENT_VISION_2030.md) (the
BIRD-INTERACT direction this is the first concrete step toward).*

---

## TL;DR

Today the user must pick **Insight** (quick) or **Deep Analysis** (investigation) *before*
the agent reads the question — two endpoints, a frontend toggle, two code paths. This document
proposes collapsing them into **one conversational entry (`POST /ask`)** where the agent decides
depth, decomposition, and output structure itself, asks a clarifying question when ambiguity is
material, and carries context across turns.

The key realization: **the depth-deciding intelligence already exists** — `assess_complexity`
(deterministic) + `classify_question` (`direct|investigate|explore|final_text`) + the ADA phase
gates. It just runs one layer too late, *inside* the deep path. The merge is mostly **promoting
that router to the front door**, plus two genuinely new capabilities: **budget-aware clarification**
(ask vs guess) and **conversational session state** (state-dependent follow-ups).

Grounded in BIRD-INTERACT (arXiv 2510.05318): its **a-Interact** agentic setting — where the
model autonomously decides when to *retrieve / probe / ask / submit* — **is** this merged mode.
The paper's headline finding is that interaction *shape* is worth ~2× the answer quality
(GPT-5: 14.5% protocol-forced → 29.2% agentic). Forcing the user to choose a mode is exactly the
friction the paper measures.

**Chosen direction (this doc commits to these):**
- **Control model = auto + transparency.** The agent decides depth every turn, but every answer
  shows *why* (“answered directly” / “investigating — the change needs decomposition”) with a
  one-click re-run at a different depth. No silent mode-guessing; no up-front toggle.
- **First capability beyond plumbing = ask-vs-guess clarification** (BIRD-INTERACT’s #1 skill),
  built **harness-first** (measure before trust).

---

## 1. The current architecture (code-grounded)

Two user-facing doors, chosen by the frontend before the question is understood:

| | Insight | Deep Analysis / ADA |
|---|---|---|
| Endpoint | `POST /chat` | `POST /investigate` |
| Streamer | `_stream_chat()` ([investigations.py:812](../aughor/routers/investigations.py)) | `_stream_investigation()` ([investigations.py:1747](../aughor/routers/investigations.py)) |
| Shape | single NL→SQL→answer, one chart | LangGraph multi-phase investigation (intake→baseline→decompose→dimensional→synthesis) |
| Control | `mode: "ask"` in [`ChatPanel.tsx`](../web/components/ChatPanel.tsx) | `mode: "investigate"` + `deep: bool` escalation flag |

The router that *should* live at the door instead lives inside the agent:

- **`assess_complexity(question)`** ([complexity.py:84](../aughor/agent/complexity.py)) — deterministic
  difficulty (`simple|moderate|complex`), a 0–1 score, and an **`ambiguous`** flag. Pure, unit-tested.
- **`classify_question(question)`** ([nodes.py:80](../aughor/agent/nodes.py)) — returns
  `RouteDecision{mode ∈ direct|investigate|explore|final_text, confidence, reasoning}`
  ([state.py:25](../aughor/agent/state.py)). Prompt ([prompts.py:1](../aughor/agent/prompts.py)) is
  explicit: *“complexity does not determine the mode, intent does.”*
- **`assess_complexity` already cost-tiers the routing decision** (simple→`fast` model) while keeping
  the answer on the frontier `coder` model — but it does **not** yet choose execution depth.
- **The ADA phase gates** (`route_after_baseline/decompose/dimensional`, declared by
  [`orchestrator.py`](../aughor/agent/orchestrator.py)) already escalate/skip phases at runtime —
  the in-investigation analogue of what we want across the whole path.

Both paths already share the safety + grounding spine (the 2026-06-25 cross-pollination work):
`preflight_repair` ([sql/safety.py:31](../aughor/sql/safety.py)) and `build_data_understanding`
([semantic/data_understanding.py:34](../aughor/semantic/data_understanding.py)). **This is what makes
the merge safe** — the two bodies can be dispatched behind one router without diverging on metric
definition, grain, or SQL safety.

> The honest summary: we have a router and a shared spine; what we lack is (a) the router at the
> *front*, (b) conversation, and (c) the ability to *ask*.

---

## 2. The target — your own formula, at the front door

From [`NL2SQL_WINNING_FORMULA_2026.md`](NL2SQL_WINNING_FORMULA_2026.md) §4:

> **ASSESS → ROUTE → (CLARIFY | GENERATE) → VERIFY**, where ASSESS is deterministic.

The merge *is* the act of lifting this loop out of the deep path and making it the contract of a
single `POST /ask`:

1. **ASSESS (deterministic, at the door).** `assess_complexity` + `classify_question` run first,
   over the **full session context** (this turn + carried state), not after a mode is chosen.
2. **ROUTE to depth, not just to a classifier model.** Promote the verdict to pick *execution depth*:
   `direct/final_text` → the quick `_stream_chat` body; `investigate/explore` → the ADA graph.
   The toggle's job, done by the router. Confidence-gated, exactly as `classify_question` already is
   (`< 0.65 → investigate`, because false-shallow is worse than false-thorough).
3. **CLARIFY when ambiguity is material** — gate one budget-bounded question on the `ambiguous` flag
   (capability #1; §4).
4. **Dynamic output structure** = f(question shape × *actual* result shape), not mode. Every renderer
   already exists (`ResultChartCard`, the Brief, the KPI scorecard, the multi-finding ADA report);
   the merge wires *which* one fires to the verdict + the result (§5).
5. **Conversational session state** — carry prior SQL/CTEs, resolved entities, filters, and findings
   across turns (capability #2; §6). `ChatRequest` already carries `session_id` + `history`; today
   they are thin.
6. **VERIFY — unchanged.** `preflight_repair` + the Verifier battery still gate every answer.

### Why an LLM mega-orchestrator is explicitly *out*

Aughor's durable conclusion — *deterministic guards beat added LLM machinery on a strong model* —
and the R4 ablation ([`R4_ABLATION_EVAL_2026-06-21.md`](R4_ABLATION_EVAL_2026-06-21.md)) say
**injecting an LLM into the decision path regresses**. So:

- The **deterministic** `assess_complexity` is the routing spine. The LLM `RouteDecision` stays a
  *secondary intent signal* (as today), never the sole arbiter.
- The cost tier routes the *routing decision*, **never** the user-facing SQL — that stays on the
  frontier `coder` model + guards. The merge must not become a pretext to cheapen answers.
- This is the same legibility-without-drift stance `orchestrator.py` already takes for phases.

---

## 3. The control model — auto + transparency (the “route receipt”)

The agent decides, but it is never a black box. Every turn emits a new **`route` SSE event** before
the answer, carrying what the router already computes into run state today
(`route_complexity_tier`, `route_confidence`, `route_ambiguous`, `RouteDecision.reasoning` —
[nodes.py:141](../aughor/agent/nodes.py)):

```
event: route
data: { "depth": "investigate", "tier": "complex", "confidence": 0.82,
        "why": "‘why did margin fall’ asks for a cause — decomposing the change",
        "ambiguous": false, "alternatives": ["direct", "explore"] }
```

The frontend renders this as a one-line **depth banner** above the answer, with a re-run control:

- *“Answered directly — a single metric lookup.”* → **[Investigate instead →]**
- *“Investigating — the change needs decomposition.”* → **[Just answer quickly →]**

This is the chosen *auto + transparency* model: the user never picks a mode up front, but is always
told the call that was made and can override it in one click. The override re-runs the **same `/ask`**
with an explicit `depth=` hint — which is also how the existing **“Investigate deeper”** drill and the
**Tier-0 dossier** short-circuit survive: they become *explicit overrides on top of the auto-router*,
not the primary control. The banner doubles as the user-facing surface of the Trust Receipt the
router already writes.

---

## 4. Capability #1 (priority) — budget-aware clarification, harness-first

BIRD-INTERACT's central result: **ambiguity is the #1 unsolved skill**, and frontier models default
to **trial-and-error** (`submit`-and-see) rather than asking. Aughor *detects* candidate-disagreement
ambiguity (SOMA-SQL) but **does not ask the user today** — confirmed gap (`tools/ambiguity.py` is
SQL-column-level only). The `ambiguous` flag on `ComplexityVerdict` is the documented seam
([ROADMAP.md:246](../ROADMAP.md)).

**Design:**

- Detection is **two-source** (the Phase-2 harness proved one source is not enough — see §8 Phase 2):
  the deterministic `ambiguous` flag catches *under-specification* (vague pronoun, missing metric/time),
  but *value/term* ambiguity ("urgent" → which status?) needs **SOMA candidate-disagreement**. Ask when
  *either* fires **and** the disagreement would *materially change the answer* (the FP-aware critique gate
  keeps us from asking noise) — emit a **`clarify` SSE event** with one targeted question + 2–4 grounded
  options, instead of guessing.
- **Budgeted** — at most one clarification per turn by default (BIRD-INTERACT's `τ = m_amb + λ_patience`;
  over-asking is a failure mode the paper stress-tests). If the user ignores it, fall back to the
  best-guess answer *with the assumption stated* (the honesty invariant).
- The clarification answer feeds session state (§6), so the next turn is grounded, not re-litigated.

**Harness-first discipline (non-negotiable).** Per the arc's deepest lesson — *let evidence pick the
lever* — and the judgment call already recorded in
[`INTERACTIVE_DATA_AGENT_VISION_2030.md`](INTERACTIVE_DATA_AGENT_VISION_2030.md) §6, the **interactive
eval harness is rebuilt before this feature is trusted**. It was prototyped (`evals/interactive.py`:
function-driven `AMB`/`LOC`/**`UNA`** user simulator + episode runner scoring *submitted* SQL under a
clarification budget — rewarding good clarification, penalizing blind guessing) then removed in the
2026-06-29 consolidation. The *design* is the durable artifact; we rebuild it against the real `/ask`
pipeline so every clarification change is measurable from day one. No clarification feature ships on
anecdote at small n.

---

## 5. Dynamic output structure

The answer shape is chosen from `RouteDecision` × the **actual** result, not the entry mode:

| Signal | Output |
|---|---|
| `final_text` / definitional + strong KB | headline-only prose, no SQL (path already exists, [nodes.py:194](../aughor/agent/nodes.py)) |
| `direct`, scalar result | KPI scorecard / single-number card |
| `direct`, ranked/grouped result | `ResultChartCard` (auto chart + table + pivot) |
| `investigate` / `explore` | multi-finding investigation report (verdict, key findings, what-is-not-the-cause, risks) |

Implementation is a **render-selector decoupled from the endpoint** — today the renderer is implied
by *which endpoint answered*; after the merge it is keyed on the verdict and the result shape. The
SOMA "answer-shape / projection-minimality" rules ([prompts.py:57](../aughor/agent/prompts.py)) already
push the SQL toward the implied output columns; this extends that discipline from columns to layout.

---

## 6. Capability #2 — conversational session state (the BIRD-INTERACT lift)

The hardest, deepest-moat axis: **state-dependent follow-ups** — *“now break that down by region”*,
*“filter that to last quarter”*, *“why is that one different?”* — reasoning over what the **prior turn
computed**, not just prior text. Today each `/chat` turn is largely stateless; `session_id` + `history`
exist but carry little structured state.

**Design (carry a typed session context across turns, keyed on `session_id`):**

- **Resolved bindings** — entities, filters, the metric, and the time window the last turn settled on
  (so “that” / “those” resolve without re-asking).
- **Prior SQL / CTEs** — the last grounded query, so a follow-up can compose on it (BIRD-INTERACT's
  *objects created by prior queries*). Read-first: we carry CTE *text*, not materialized tables.
- **Prior findings** — so “why is that one different?” anchors on a specific result row, reusing the
  existing `origin_finding` anchoring the dossier/ pull-thread flows already built
  ([nodes/investigate](../aughor/agent/investigate.py)).
- **Clarification answers** — folded in (§4), so the session gets *less* ambiguous over time — the
  ITS-Law framing: interaction is a *scaling axis*, every grounded turn invests toward the ideal answer.

This is the largest lift and the hardest to verify; it is sequenced last and also gated on the eval
harness (multi-turn episodes).

---

## 7. Seam-by-seam change map

| Move | Where | Lift |
|---|---|---|
| `POST /ask` entry; `/chat` + `/investigate` become thin back-compat shims | [investigations.py:2296,2381](../aughor/routers/investigations.py) | small |
| Run `assess_complexity` + `classify_question` at `/ask` before dispatch | new dispatcher wrapping the two `_stream_*` bodies | small–med |
| Verdict → depth dispatch (reuse existing bodies verbatim at first) | the dispatcher | medium |
| `route` SSE event + depth banner + one-click re-run (`depth=` hint) | SSE layer + [`ChatPanel.tsx`](../web/components/ChatPanel.tsx) | small–med |
| Render-selector decoupled from endpoint (output structure = f(verdict × result)) | SSE render layer + turn renderer | medium |
| `clarify` SSE event gated on `ambiguous` + SOMA materiality + FP-gate; budget=1 | new node; reuses SOMA + critique gate | medium |
| Typed session context (bindings · CTEs · findings · clarifications) per `session_id` | `ChatRequest.session_id`/`history` is the hook | **large** |
| Frontend: drop the toggle, default auto, keep override chips | [ChatPanel.tsx:133](../web/components/ChatPanel.tsx), [useChat.ts:41](../web/lib/useChat.ts) | small–med |
| Rebuild interactive eval harness (AMB/LOC/UNA sim + episode runner) | `evals/` (design preserved) | medium |

**Why this is tractable:** Phases 0–1 reuse `_stream_chat` and the ADA graph **unchanged** behind a
router. The merged front door works *before* any of the hard parts (memory, clarification) are touched.

---

## 8. Gated sequence (build → wire → test → **leverage**, measure-first)

- **Phase 0 — unify the door. ✅ SHIPPED (2026-06-30).** `POST /ask` + a **deterministic-first**
  router (`aughor/agent/ask_router.py::decide_ask_route`) that dispatches to the existing `_stream_chat`
  (quick) or `_investigation_job_streamed` (deep) bodies **unchanged**, emitting a `route` SSE receipt
  first. The obvious cases (clear lookup → quick; causal/complex → deep) never call a model; only
  borderline questions consult `classify_question`. **License-safe** — a deep route degrades to quick
  (with a transparent reason) when the connection lacks `DEEP_ANALYSIS`, never bypassing the gate. The
  legacy `deep`/`insight_id` flags still drive the escalation + dossier drill through the one door.
  Behind `AUGHOR_UNIFIED_ASK` (default on); `/chat` + `/investigate` untouched for back-compat. 23 unit
  tests (decision matrix + endpoint dispatch + degrade); full unit suite green (1976). *The frontend
  still uses the toggle — switching it to `/ask` is Phase 1.*
- **Phase 1 — auto + transparency UI. ✅ SHIPPED (2026-06-30).** The composer defaults to a new **Auto**
  mode that posts to `/ask` (`web/lib/useChat.ts`); the `route` SSE receipt is parsed
  (`web/lib/investigationStream.ts`: a `route` field on the turn + a `ROUTE` action that also sets the
  turn's effective mode — deep→investigate, else ask — so the existing renderers work unchanged) and
  rendered as a **depth banner** with a **one-click re-run** at the other depth
  (`web/components/ChatPanel.tsx`: `DepthBanner` + a 3-segment Auto·Insight·Deep toggle, Auto default).
  Live-verified against the running API: a quick lookup, a causal→deep route, and a `depth=quick`
  override each stream the correct `route` receipt first; tsc + eslint clean. *Remaining within this
  arc: the render-selector keyed on the actual result shape (§5) — today output structure still follows
  the route→mode mapping, i.e. the two existing renderers.*
- **Phase 2 — eval harness (rebuild). ✅ SHIPPED (2026-06-30).** `evals/interactive.py` rebuilt: a
  function-driven user simulator (`AMB`/`LOC`/**`UNA`** anti-leak + gold-SQL scrub) + an episode runner
  that scores *submitted* SQL against executable gold under a clarification budget — rewarding good
  clarification, penalizing blind guessing. Adds the Phase-3 seam: `clarifying_system(generate_fn,
  should_ask_fn)` + `complexity_should_ask` (backed by Aughor's real `assess_complexity(...).ambiguous`)
  alongside the `single_shot_system` baseline. 14 tests; ruff clean. **Baseline measured (offline,
  sqlite): never-asks 0% vs always-asks 100% on a value-ambiguity task — and the key finding: the
  deterministic `ambiguous` flag catches *under-specification* (vague pronoun, missing metric/time) but
  NOT *value/term* ambiguity ("urgent" → which status?), so it does NOT fire there (`complexity_should_ask`
  → 0% ask).** → Phase 3 must gate on SOMA candidate-disagreement materiality, not the `ambiguous` flag
  alone. (This is exactly why the harness is built first: it names the biggest gap before we build.)
- **Phase 3 — ask-vs-guess clarification (§4). ✅ SHIPPED (2026-06-30).** `aughor/agent/clarify.py`:
  `assess_clarification(question)` — deterministic **two-source** detection (under-specification via the
  complexity `ambiguous` flag + value/term ambiguity via a subjective-qualifier detector with an FP gate
  that stays quiet on grounded questions). Wired into `_stream_ask` (behind `AUGHOR_ASK_CLARIFY`): a
  fresh auto turn that is materially ambiguous emits a **`clarify` SSE event** (one targeted question +
  reason + best-effort options) instead of guessing; budget is one ask/turn; explicit overrides /
  drills / `skip_clarify` bypass it. Frontend: a **clarify card** (`web/components/ChatPanel.tsx`:
  `ClarifyCard`) — option chips, a typed-detail input, and **“Answer anyway”** (the honesty fallback);
  the reply re-asks with `skip_clarify` so it never loops. **Live-verified** (running API): under-spec
  and value/term (“urgent”) questions both emit `clarify`; `skip_clarify` and concrete questions don’t.
  **Harness-measured** (the loop Phase 2 opened, closed): on the value-ambiguity task, never-asks **0%**
  → one-source(complexity) **0%** → **two-source(clarify) 100%**. *Remaining (3b): the execution-grounded
  SOMA candidate-disagreement + value-index/glossary binding to replace the deterministic term proxy and
  to populate grounded options.*
- **Phase 4 — conversational session state (§6). ✅ CORE SHIPPED (2026-06-30).** The chat path already
  injected the last 3 quick turns' SQL; Phase 4 makes follow-ups *reliable*: `aughor/agent/followup.py`
  `is_followup(question)` deterministically detects a continuation ("now break that down", "filter that
  to Q4", "the top one") and stays quiet on fresh questions; `build_history_section(history, followup=)`
  (extracted + testable) now also carries a **result digest** (`ChatHistoryTurn.key_rows`, the prior
  turn's top rows — frontend sends them) so "that"/"the top one"/"those" resolve against real values,
  and switches to a **"compose on the most recent query as the base"** directive when a follow-up is
  detected. **Live-verified:** "now break that down by status" after a revenue lookup →
  `SELECT status, SUM(amount) … GROUP BY status` (kept the metric + table, added the grain, dropped the
  now-wrong `WHERE status='success'`). 10 tests.
  **✅ 4b deep-turn context (2026-06-30):** `web/lib/useChat.ts: deepHistoryEntry` carries a deep/explore
  answer into the conversation — its headline (continuity) + the first finding-with-SQL as a composable
  base + a result digest — so follow-ups after an *investigation* keep context (was quick-turns-only).
  Live-verified: "now just the failed ones" after a by-status investigation → `SELECT SUM(amount) … WHERE
  status='failed'` (kept metric+table, resolved "the failed ones" via the digest). *Remaining: explicit
  resolved-binding state (metric/window/filters); server-persisted per-`session_id` context; CTE carry-over.*
- **Phase 5 — progressive escalation / ITS.** Start cheap, escalate depth mid-stream when findings are
  inconclusive (the ADA gates already do this internally; expose across the unified path).

---

## 9. Non-goals / invariants

- **No LLM in the routing decision path** (R4). Deterministic spine; LLM intent signal only.
- **Frontier model + guards for every answer.** Cost tier never downgrades the user-facing SQL.
- **Read-first.** No CRUD/DDL agency rides in on this merge.
- **Measure before trust.** No clarification/multi-turn feature ships without the harness; at small n,
  anecdote isn't evidence.
- **Don't break what works.** The `deep=true` drill and the Tier-0 dossier short-circuit survive as
  explicit overrides, not the primary control.
- **Back-compat.** `/chat` and `/investigate` keep working as shims through the transition.

---

## 10. Open questions

1. **Override granularity** — is a binary “quick ⇄ investigate” re-run enough, or do users want to land
   directly in `explore`? (Lean: binary first; `explore` is rare and the router handles it.)
2. **Session-state scope** — does the conversation thread bind to a connection/canvas, and how does it
   reset? (Lean: per `session_id`, soft-reset on connection switch.)
3. **Clarification surface** — inline chips in the chat stream vs a distinct prompt card. (Lean: inline
   chips; it keeps the conversation linear.)
4. **Materiality threshold** — when is ambiguity “material enough” to spend the one-question budget?
   This is a tuning dial the eval harness (Phase 2) exists to set, not a guess.

---

## References

- BIRD-INTERACT — arXiv [2510.05318](https://arxiv.org/abs/2510.05318) (Huo et al., ICLR 2026 Oral).
- [`MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md`](MODE_ARCHITECTURE_AND_CROSS_POLLINATION.md) — the shared spine.
- [`NL2SQL_WINNING_FORMULA_2026.md`](NL2SQL_WINNING_FORMULA_2026.md) — the ASSESS→ROUTE formula.
- [`INTERACTIVE_DATA_AGENT_VISION_2030.md`](INTERACTIVE_DATA_AGENT_VISION_2030.md) — the long-horizon direction + harness design.
- [`R4_ABLATION_EVAL_2026-06-21.md`](R4_ABLATION_EVAL_2026-06-21.md) — why the router stays deterministic.
- Code spine: `agent/complexity.py`, `agent/nodes.py` (`classify_question`), `agent/orchestrator.py`,
  `sql/safety.py` (`preflight_repair`), `semantic/data_understanding.py`,
  `routers/investigations.py` (`_stream_chat` / `_stream_investigation`).
