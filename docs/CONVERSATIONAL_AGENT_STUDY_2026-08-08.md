# From Program to Conversation — the open-webui Study and the Aughor Design (2026-08-08)

> **The design sections (§3–§6) are superseded as the plan of record by `docs/UNIFIED_ADOPTION_PLAN_2026-08-08.md`**, which merges them with the Prime Agent adoption plan into one layered program. §1 (aughor diagnosis) and §2 (what open-webui does) remain the study reference.

**The complaint this answers** (user, 2026-08-08): *"Deep analysis or quick mode do not come across as agents but very hard recorded tightened programs who can think in a single manner — the user cannot ask or even brainstorm before asking a legitimate question. We need more flexibility, more dynamic responses."*

**Sources.** Deep study of [open-webui](https://github.com/open-webui/open-webui) (~110k lines Python + large Svelte frontend; three subsystem deep-dives: backend chat flow, background task-model ecosystem, frontend conversation mechanics) + a code-verified anatomy of aughor's `/ask` path. Companion docs: `docs/UNIFIED_ANSWER_PATH.md` (this is its next phase), `docs/ROADMAP_INTELLIGENCE_AND_CHAT_2026-08-01.md` (Tracks A/B/C), `docs/PRIME_AGENT_ADOPTION_2026-08-08.md` (the harness workstream this composes with).

---

## 1. The diagnosis: aughor's conversation is owned by the pipeline

Verified anatomy of one user message today:

1. **`aughor/agent/ask_router.py`** — a deterministic complexity spine (+ LLM classifier only on the borderline) routes every message to one of exactly two bodies: `quick` → `_stream_chat`, `deep` → `_stream_investigation`. Four structural modes exist (`direct`, `explore`, `final_text`, `investigate` — `aughor/agent/modes/`), and **every one is an answer-production program**.
2. **`aughor/agent/clarify.py`** — ambiguity detection is a regex qualifier list; the budget is "one ask per turn"; the user answers via pre-baked chips and the pipeline resumes. It is a *gate*, not a dialogue.
3. **`aughor/agent/followup.py`** — continuation detection is a regex lexicon (`now`, `what about`, pronouns). It handles "break that down by region"; it cannot handle "why would that be?" or "what should I even look at?"
4. **Conversation history** exists only as a context block inside the SQL prompt (`build_history_section`, last 3 turns — `aughor/routers/investigations.py:1134`).

There is no branch anywhere whose job is simply *to talk*. Every message is treated as a **query specification to be compiled**. The model is a subroutine of the pipeline. That is the user's complaint, stated architecturally.

Important nuance: this design is *deliberate and locally correct* — the deterministic spine exists for latency and because of the R4 ablation lesson ("an LLM never sits alone in the decision path"). The fix must not throw that away. The reframe in §3 is that the R4 lesson applies to **SQL correctness**, not to **conversation routing**.

## 2. What open-webui actually does (and why it feels intelligent)

The single most instructive fact: open-webui *contains aughor's architecture* — a pipeline that reads the message, decides what it means, pre-fetches context, and hands the model a pre-cooked prompt — **and it is literally called `legacy`** (`function_calling: 'legacy'`). The default mode is `native`, and the difference is one inversion:

> **Legacy: the pipeline is the router and the model is a formatter. Native: the model is the router and the pipeline is an executor.**

The nine load-bearing decisions (backend deep-dive, condensed):

- **D1 — The model decides; nothing runs before it speaks.** In native mode the web-search handler, image handler, RAG pre-fetch are *explicitly skipped*; features become tool specs the model may ignore.
- **D2 — Capabilities live in docstrings, not routers.** `search_web` is 35 lines; its 2-sentence docstring is the entire routing policy. There is no intent classifier anywhere.
- **D3 — Feature gates are about *permission to offer*, never about message content.** Five AND-ed gates (admin, model capability, user toggle, RBAC…) — zero of them ask "did this message look like a search."
- **D4 — Everything the pipeline does is narrated back to the model as `<context>`, and the model always writes the last word.** Even failures: *"Image generation failed… tell the user the following error occurred: {error}"*. The user never sees a raw system string.
- **D5 — The assistant message is a typed array** (`reasoning` / `message` / `function_call` / `function_call_output`) — progress is message structure, not a side channel; it survives reload, forking, side-by-side.
- **D6 — The tool loop budget is effectively unbounded** (256 iterations), every iteration streams identically. There is no "the pipeline is running, please wait" state.
- **D7 — Every failure is a value, not an exception.** Search fails → model answers from its own knowledge. Tool throws → exception string becomes the tool result. Bad args → "please try again" as the result. The conversation has no failure state, only *worse context*.
- **D8 — Cheap task models do the bookkeeping, always with a deterministic fallback.** Title (fired *during* the first stream), tags, follow-ups (written in the *user's* voice, one click sends), retrieval-query generation (sees the last 6 messages, not the last message; falls back to the raw user text on any failure).
- **D9 — Progressive disclosure.** Knowledge is injected as a *manifest* (`<attached_knowledge>` tags) plus browse tools (`list/search/grep/view`); the model pulls detail on demand. No default system prompt exists at all — behavior is shaped by tool descriptions, not prose.

Their RAG template even licenses the model to *leave the pipeline's rails*: "If the answer isn't in the context but you possess the knowledge, explain this and answer" / "If uncertain, ask the user for clarification."

Frontend principles (third deep-dive): **(P1) append, never overwrite** — edit/regenerate create siblings in a message tree, nothing is destroyed; **(P2) the input is never disabled** — typing while streaming queues (editable queue) or interrupts, user choice; **(P3) everything the agent does is narrated, collapsed by default, expandable on demand** — one shimmering status line per phase, a timeline behind a click, consecutive tool steps grouped into "Exploring… → Explored web_search, 3 read_file". Plus: guided regeneration ("Suggest a change" / "Add details" / "More concise" — a `regeneration_prompt` appended as a trailing user turn, with the rejected answer kept in context), and partial answers that survive stop, error, and reload ("always show message contents even if there's an error").

## 3. The design: conversation-first aughor, guards intact

The move is **not** "replace the pipelines with an agent." The pipelines — grain guard, defan, preflight, verification, EXPLAIN-bound semantics — are aughor's moat, and the NL2SQL conclusion (deterministic guards > LLM machinery) stands. The move is to change **who owns the conversation**:

> The guards stay *inside* the tools. The model decides *which tool the conversation needs* — including the tool of just answering.

The R4 lesson is preserved because no LLM ever sits alone in the *SQL decision path* — SQL generation, execution, and verification remain exactly the guarded pipelines they are today. What changes is that a brainstormy, half-formed, or meta message is no longer force-compiled into SQL.

### Phase 1 — Aliveness inside the current architecture (no architectural change)

1. **Follow-up suggestions after every answer** — a task-model call, written in the *user's voice*, and for a data product specifically: *operations on the current result* ("break this out by region", "same view, trailing 12 months", "what's driving the Q3 dip"). One click sends. Deterministic fallback: no chips, never an error. Aughor's advantage: the answer artifact (SQL, columns, filters) gives the generator far better material than open-webui's generic chat. Lands beside the existing starters library.
2. **Narrated failures.** Adopt D4/D7 at the seams that today hard-fail or go silent: empty result sets, guard rewrites (the A4 `guard_receipt` arc is exactly this), truncated briefings, connector errors — each becomes a `<context>`-style note the *answering model* explains in its own voice, with the user's next step included. The model always writes the last word.
3. **Conversational clarify.** Keep the deterministic detection; change the *surface*: chips remain, but free-text answers are accepted (they already crystallize via `_apply_clarify_choice`), and add an explicit "just answer as best you can" affordance that records the guess as a disclosed assumption instead of blocking. A clarify should feel like the agent asking, not a form validating.
4. **Status timeline discipline** (Track B alignment): aughor already emits SSE receipts/progress frames; render them open-webui-style — one shimmering line per phase, collapsed timeline behind a click, consecutive steps grouped. This is presentation only.

Effort: each item 1–2 days; all flag-gated; zero pipeline changes.

### Phase 2 — The converse body (the architectural move)

Add a third body behind `/ask`: **`_stream_converse`** — a real agent turn whose tools are the existing machinery:

| Tool | Wraps | Notes |
|---|---|---|
| `answer_question(question)` | today's quick body | the full guarded quick pipeline as one call |
| `start_investigation(question, mode)` | today's deep body | returns an admission handle + streams into the same turn (prime-agent's admission pattern) |
| `list_tables()` / `describe_table(name)` / `sample(name)` | schema/catalog stores | progressive disclosure: the schema enters as a *manifest*, detail on demand (D9) — composes with the column-config visibility work |
| `run_sql(sql)` | the guarded execute chokepoint | every existing guard fires inside; guard rewrites return as *values* the model narrates |
| `search_history(query)` | findings/briefings/trusted queries | "have we looked at this before?" |
| `save_guidance(...)` | the harness capture (PRIME_AGENT_ADOPTION §A1/A2) | "don't use fact_sales, use v_fact_sales" gets *captured in conversation*, proposed for one-click confirm |
| `ask_user(question, options?)` | clarify surface | the agent can ask back mid-turn — clarify becomes a tool the model chooses, not a gate |

Rules of the body, copied from what works:
- **Docstrings are the routing policy** (D2). No intent classifier for tool choice. Tool availability is permission-gated (connection capabilities, license, RBAC) — never content-gated (D3).
- **Minimal system prompt**: connection identity, the schema manifest, the guidance-notes index (harness A2 Band-A style), and the verified semantic layer — *state, not instructions* (D9). Aughor's Track-A thesis ("we restrict intelligence instead of directing it") applied to prose.
- **Failures are values** (D7): empty result → the model sees it and pivots; guard rejection → the model explains and adjusts; tool exception → the string is the result.
- **A real loop budget** (D6), every iteration streamed through the existing SSE surface.

**Routing change — the door inverts gradually.** Keep the deterministic spine as the *fast path*: a message the complexity assessor scores as a clear, well-formed analytical ask still goes straight to quick/deep with zero extra LLM hops (latency preserved; this is open-webui's per-model `legacy` mode kept as an optimization). Everything else — vague, meta, exploratory, brainstormy, "what data do we have?", "why would that be?" — lands in the converse body instead of being force-compiled. Measured by the route receipt, the ratio tells us when converse should become the default door.

Effort: ~1–2 weeks behind `ask.converse` (default off). The quick/deep bodies are untouched — they gain a caller.

### Phase 3 — Frontend steerability (merges into Tracks B/C)

In order of effect per unit of work, from the frontend study:
1. **The input is never disabled** — typing while an answer streams queues the message (visible, editable, deletable) or interrupts; user's choice.
2. **Partial answers survive** stop/error/reload; error renders *below* the partial content, never instead of it; reconnect asks "is this chat still generating?" and reconciles.
3. **Guided regeneration** — "Suggest a change" + canned steers; backend accepts a `regeneration_prompt` appended as a trailing user turn with the rejected answer kept in context.
4. Follow-up chips (Phase 1's backend), status timeline, Escape-as-reset, ArrowUp-to-edit-last.
5. **Defer the message tree.** Open-webui's branching (P1) is its deepest mechanic and nearly impossible to retrofit *later* — but it is also the most expensive, and Track C's shell decision (vercel/chatbot) constrains it. Decide branching as part of Track C's data model, not as a bolt-on here. Until then, non-destructive *regeneration* (keep the old answer addressable) is the 20% that matters.

## 4. What NOT to do

- **Do not delete the deterministic guards or put an LLM in the SQL decision path.** The inversion is about conversation ownership only.
- **Do not add an intent classifier for tool selection** in the converse body — that recreates the router one level up (D2 is the whole point).
- **Do not write a big behavioral system prompt** for the converse body. Open-webui ships *no* default system prompt; behavior lives in tool descriptions and injected state.
- **Do not block answers on background tasks.** Follow-ups/titles run after the stream with deterministic fallbacks; a background failure must never be visible (open-webui's uniform rule).
- **Do not build the full message tree first.** Sequence it with Track C.

## 5. Sequencing

| Wave | Items | Depends on |
|---|---|---|
| 1 | Phase 1.1 follow-ups + 1.2 narrated failures + 1.3 conversational clarify | faux provider (PRIME_AGENT_ADOPTION WS-B) makes these testable |
| 2 | Phase 2 converse body behind `ask.converse`, tools = wrap existing bodies + schema browse + `run_sql` + `ask_user` | harness A1/A2 for `save_guidance` |
| 3 | Route-receipt measurement of converse vs fast-path ratio; widen converse routing accordingly | wave 2 live |
| 4 | Phase 3 frontend (queue, partials, guided regen) | Track B/C decisions |

**Graduation receipt for the whole premise** (Wave-H discipline): a scripted 10-turn session — brainstorm → vague question → clarify-by-conversation → analytical ask → follow-up chip → "why?" → correction ("use v_fact_sales") → captured guidance → re-ask — runs end-to-end with the converse body, against the faux provider in CI and against a live model once. Today that session dies on turn 1.

## 6. Risks

1. **Latency regression on clear asks** — mitigated by keeping the deterministic fast path; measure via route receipt before widening.
2. **Token/request budget** (OpenRouter 1k/day): the converse body adds a loop where quick was one-shot. Mitigation: fast path keeps the volume path cheap; loop budget capped; follow-ups on the task model; measure with `kernel/metering.py`.
3. **Tool-choice quality on free models** — docstring-driven choice needs a competent model; this is Track A's bet already ("scale it with the model"). The fast path bounds the blast radius.
4. **Two doors drifting**: converse-wrapped quick vs direct quick must produce identical answers for identical questions — assert it in the graduation receipt.
