# CopilotKit / AG-UI Adoption Plan — 2026-07-13

**Status:** ANALYSIS COMPLETE — implementation-ready, nothing built yet.
**Audience:** the coding agent that picks this up. Every claim below carries a `file:line` reference (verified against `main` @ `a831d97`) or a primary-source URL (verified 2026-07-13).
**Inputs:** (1) full frontend/backend streaming audit of this repo; (2) fresh research of CopilotKit `v1.62.3` + AG-UI protocol (`@ag-ui/client 0.0.57`, `ag-ui-protocol` PyPI `0.1.19`); (3) the surviving learnings of the June-30 spike (branches `2026-06-30-agui-copilotkit-spike`/`-freeform` — lost, never pushed; learnings in §11).

---

## 0. Executive summary

**Verdict: adopt AG-UI as a protocol seam, adopt CopilotKit selectively and headlessly, do NOT adopt their chat shell — and fix the real root cause first, which is ours, not theirs.**

The "declarative / untrusted" feel has one dominant root cause that no frontend library can fix: **Aughor's backend never streams a single token.** Every piece of assistant text (headline, narrative, report) arrives as one complete SSE event (`investigations.py:1793-1814`, `2495`), produced by a non-streaming `instructor` structured-output call (`aughor/llm/provider.py:412`). CopilotKit renders deltas; we have no deltas to render. The plan therefore has a **Phase 0 that needs zero new dependencies** and delivers most of the perceived improvement, followed by a graduated, flag-gated, reversible adoption of the AG-UI protocol and (optionally) headless CopilotKit v2.

Phases (each independently shippable, each gated, each with a kill switch):

| Phase | What | New deps | Risk | Payoff |
|---|---|---|---|---|
| **CK-0** | Land what we own: merge the un-merged `2026-07-08-ui-ux-uplift` feel branch + add token streaming to the backend + progressive answer emission | none | LOW | ~70% of the "alive" feel |
| **CK-1** | AG-UI protocol seam: additive `POST /agui/run` translator on the backend + `@ag-ui/client` transport adapter on the frontend (UI untouched) | `ag-ui-protocol` (pip), `@ag-ui/client` (npm) | LOW-MED | standard protocol, partial-tool-arg streaming, interrupt model, ecosystem door |
| **CK-2** | DECISION GATE: headless CopilotKit v2 (`useAgent`/`useInterrupt`/`useThreads` via `selfManagedAgents` → FastAPI directly) — only if CK-1 shows we're rebuilding their state machinery | `@copilotkit/react-core` (pinned wave) | MED | threads, time-travel, HITL plumbing for free |
| **CK-3** | `@copilotkit/react-ui` chat shell | — | **REJECTED** | not worth it (see §5.3) |

**Why it broke last time, in one line:** the June-30 attempt swapped our chat surface for `<CopilotChat>` + the GraphQL runtime + a Node middleware route — a wholesale shell replacement at the most load-bearing spot in the app. This plan never replaces the shell; it changes the *transport* under our existing components, behind flags, one seam at a time. And the two 2025-era blockers (mandatory GraphQL runtime, `--legacy-peer-deps`) are gone from CopilotKit's current architecture (§4.3).

---

## 1. Diagnosis: why our UI feels "declarative and untrusted"

Five verified causes, ranked by impact:

1. **No token streaming, anywhere.** All three chat paths emit whole-payload typed events. `headline`/`answer` is one string event (`aughor/routers/investigations.py:1793-1814`); the ADA report arrives whole in one `answer_report` (`:2495`); the narrative arrives whole in one `insight` (`:1960`). The client (`web/lib/investigationStream.ts:415-546`) has no delta case at all. Root cause is upstream: `LLMProvider.complete()` (`aughor/llm/provider.py:412`) is instructor structured-output — request/response, never streamed. The UI is honest about this: it *waits, then reveals*, which reads as "declarative" and — because nothing visibly *happens* during the wait — "untrusted."
2. **Dead air.** Quick mode: after `sql` is emitted (`:1545`), nothing flows until execution finishes and `columns→rows→headline→chart_config→…` land in one burst (`:1793-1814`). Deep mode: minutes-long runs with sparse `phase_complete` beats; the finer `phase_progress` events exist but sit behind flag `ada.progress_events`, default OFF (`:411-431`).
3. **Finished polish never shipped.** The five chat-feel pieces (stick-to-bottom follow-scroll, arrival animation, typewriter headline, shimmer scaffold + empty-flash guard, tactile press) were built and live-verified on 2026-07-08 — and are still sitting on local branch `2026-07-08-ui-ux-uplift` (5 commits, +248 lines, 29 commits behind main, never pushed). Main's scroll is a manual `scrollTo(scrollHeight)` (`web/components/ChatPanel.tsx:573-589`); `web/lib/useStickToBottom.ts`, `useReveal.ts`, `streamRender.ts` do not exist on main.
4. **Post-done pop-in.** `insight` and `followups` stream *after* `done` (`investigations.py:1894-1971`) and mutate an already-"completed" turn with no arrival treatment — content appearing after the UI said "finished" reads as glitchy.
5. **All-at-once figure mount.** `ResultFigure` mounts table+chart in a single frame at completion; no scaffold-then-fill (that guard is on the un-merged branch, cause #3).

Causes 1, 2, 4, 5 are **backend emission-shape problems**. This is the strategic insight: adopting CopilotKit without fixing emission shape would reproduce exactly today's feel inside a new shell — worst of both worlds, which is roughly what the first attempt discovered.

---

## 2. Post-mortem of the first attempt (June 30) and what changed

### What we did then
- Backend: `POST /agui/chat` translation layer over `_stream_chat` using the `ag-ui-protocol` pip SDK — **this part worked and its design is reused below.**
- Frontend: `@copilotkit/*` 1.61.2 with the **GraphQL runtime** (`CopilotRuntime` + `EmptyAdapter` in a Next route), `<CopilotKit>` provider + `<CopilotChat>` **replacing our ChatPanel** (M1 swapped the chat tab), `useCopilotAction("render_answer")` hosting our real Brief/ResultChartCard.
- It worked in isolation but the integration surface was huge: dark-theme override warfare against react-ui's light shell, `.poweredByContainer` branding hacks, `--legacy-peer-deps` installs on React 19/Next 16, `<CopilotChat>` ignoring externally-set messages (history restore had to bypass it entirely), and a Node middleware hop between two systems we own. Branches were never pushed and are gone.

### What changed in the ecosystem since (verified 2026-07-13)
1. **The GraphQL layer is gone.** CopilotKit v1.50 (late 2025): the new runtime speaks plain REST + SSE of AG-UI events; GraphQL survives only as a legacy-compat shim ([v1.50 notes](https://docs.showcase.copilotkit.ai/whats-new/v1-50)).
2. **React can skip the Node runtime entirely.** The provider accepts `selfManagedAgents` with `HttpAgent` instances pointed at *your own* endpoint — FastAPI can be the only backend ([self-managed agents](https://docs.showcase.copilotkit.ai/backend/self-managed-agents)).
3. **Headless is first-class.** v2 SDK (`@copilotkit/react-core/v2`): `useAgent()` + `useCopilotKit()` with documented bring-your-own-components usage ([headless guide](https://docs.showcase.copilotkit.ai/headless)).
4. **`@ag-ui/client` is fully standalone** — no CopilotKit dependency at all. `HttpAgent`/`AbstractAgent` + `AgentSubscriber` callbacks, maintained `agent.messages`/`agent.state`, partial-JSON tool-arg repair built in (`untruncate-json`) ([SDK docs](https://docs.ag-ui.com/sdk/js/client/overview)).
5. **React 19 is in the official peer range** — no more `--legacy-peer-deps` for React itself (npm registry, `@copilotkit/react-core@1.62.3`).
6. **The protocol grew the exact events we were missing**: `ActivitySnapshot`/`ActivityDelta` (structured "what the agent is doing" — a near-exact fit for our phase/plan/probe beats), the Reasoning family (replaces THINKING), `ToolCallResult`, `RunFinished.outcome = {type:"interrupt", interrupts:[...]}` + a formal `resume` array (a near-exact fit for our clarify/plan gates), `parentRunId` ([event docs](https://docs.ag-ui.com/concepts/events), [interrupts](https://docs.ag-ui.com/concepts/interrupts)).
7. **AG-UI became the de-facto seam**: 14.7k★, first-party integrations for LangGraph, CrewAI, Mastra, Pydantic AI, LlamaIndex, Google ADK, AG2, Agno, MS Agent Framework, AWS Strands, **Claude Agent SDK**; Bedrock AgentCore runs AG-UI natively; Google's A2UI interoperates via middleware.
8. **Our side grew the seam too**: PR #101 landed the `TURN_RENDERERS`/`registerTurnRenderer` registry (`web/components/ChatMessage.tsx:586-668`) — which the architecture-review docs explicitly designed as the future AG-UI-style integration point.

### What did NOT change (still true, still constraints)
- CopilotKit version churn / internal `@ag-ui/*` skew still bites upgrades ([#2840](https://github.com/CopilotKit/CopilotKit/issues/2840)) → pin whole release waves.
- `@copilotkit/react-core` is 6.6 MB unpacked before you add react-ui.
- react-ui theming is better in v2 (shadcn-ish tokens scoped to `[data-copilotkit]`, slots) but is the youngest layer, and v1/v2 seam bugs exist ([#2622](https://github.com/CopilotKit/CopilotKit/issues/2622)).
- Open-core drift: thread persistence beyond SQLite is steered toward their paid tier.

---

## 3. Ground truth: the current architecture (what must not break)

### 3.1 Frontend chat surfaces
- **`web/components/ChatPanel.tsx`** (869 lines) — the single chat component, rendered at `web/app/page.tsx:2072` (top-level chat tab) and `web/components/CanvasWorkspace.tsx:768` (Data Canvas chat tab). Modes **Auto (`/ask`) / Insight (`/chat`) / Deep (`/investigate`)** (`ChatPanel.tsx:52-53,126-160`). Turn loop at `:748-816`: `DepthBanner` → `AgentBadge` → ErrorBoundary-wrapped `ChatMessage` → `ClarifyCard` → `EscalateBar` → `TrustReceipt` → `FeedbackPrompt`.
- **`web/components/ChatMessage.tsx`** (1309 lines) — renders one assistant turn. **The generative-UI seam already exists here:** `interface TurnRenderer {id; match(turn); render(turn, props)}` (`:592-596`), `TURN_RENDERERS` first-match-wins array (`:598-648`) with built-ins `dossier` / `ada` / `explore` / `direct`, and `registerTurnRenderer(renderer, {last?})` (`:653-656`).
- Rich renderers to preserve untouched: `InvestigationReportView`, `ExplorationReportView`, `ThinkingTrace` (+`turnToTraceState`), `ContextRibbon`, `PlanGateCard`, `ClarifyGateCard`, `Chart`/`ResultChartCard`, `Brief*` family, `TrustReceipt`.

### 3.2 Streaming client
- **`web/lib/investigationStream.ts`** (607 lines). Transport = **`fetch` + `ReadableStream` over POST SSE** (all three endpoints are POST → `EventSource` impossible). Frame parser at `:372-561`.
- **`ChatTurn`** (`:60-177`) is the single source of truth for a turn; reducer `chatReducer` (`:261-350`).
- ~35 handled event types (switch at `:415-546`): `agent, route, clarify, escalate, sql, columns, rows, headline, answer, chart_type, chart_config, tables_used, context_assembled, plan_pending, clarify_pending, followups, analysis, mode, phase_complete, phase_progress, hypotheses, answer_report, ada_report, dossier_report, report, explore_report, queries_executed, score, inspect_warning, playbook_refs, insight, clarifying_questions, error, done`. **Unknown events are journaled to the debug log and silently ignored** — this makes additive dual-emission safe.
- **WP-2 robustness (PR #146) — must survive any transport swap:** content-type/status guard (`:378-390`); `invId` capture (`:398,413`); **`recoverAfterDrop`** polling `GET /investigations/{invId}` after a stream drop (`:566-601`); abort→DONE (`:551-553`); `done` never overwrites terminal `error` (`:339-344`); per-answer ErrorBoundary (`ChatPanel.tsx:765`).

### 3.3 Backend producers (all in `aughor/routers/investigations.py`, 3581 lines)
- SSE framing: `_sse(event_type, data)` at `:67-68`.
- **`POST /chat`** → `_stream_chat` (`:1044`). Success burst at `:1793-1814`; receipts `learning`/`activations` (`:1873-1875`); `done` (`:1892`); **then** `insight` (`:1960`) and `followups` (`:1971`) *after* done.
- **`POST /investigate`** → `_investigation_job_streamed` (`:2850`) → `_stream_investigation` (`:2111`). Interrupts: `clarify_pending` (`:2417`) / `plan_pending` (`:2428`) → `done`; resume via **POST `/investigations/{inv_id}/feedback`** → `_stream_resume` (`:2678`) which re-enters the checkpointed LangGraph graph (`thread_id = inv_id`) and streams into the same turn.
- **`POST /ask`** (`:3165`) → `_stream_ask` (`:3046`): optional `clarify`→`done` short-circuit; emits `route` (`:3144`); then delegates to deep (`_investigation_job_streamed`) or quick (`_metered_stream(_stream_chat(...))`); wrappers `_stream_with_session` (`:3278`) and `_stream_as_agent` (`:3262`, prepends `agent` event).
- **Two HITL mechanisms — do not conflate**: (a) pre-answer ask-vs-guess `clarify` (flag `ask.clarify`, default ON) answered by re-POSTing `/ask` with `skip_clarify` + choices; (b) mid-run LangGraph `interrupt_before=["clarify_gate"]` (flag `ada.clarify_gate`) → `clarify_pending` → `ClarifyGateCard` → feedback endpoint resume.

### 3.4 Restore semantics (subtle, load-bearing)
Live turns: `startedAt: Date.now()` (`investigationStream.ts:269`). Restored turns (`GET /chat-sessions/{id}/turns`, `ChatPanel.tsx:513-570`): `startedAt: 0`, `status:"done"`, `route:null` — which suppresses timers, animations, and DepthBanner. **Any new transport/renderer must preserve the `startedAt===0` ⇒ inert contract.**

### 3.5 Environment constraints
- `web/package.json`: React **19.2.4**, Next **16.2.6**, Tailwind **v4 CSS-first**, ECharts 6 (lazy-loaded), antd 6 (table only), `@base-ui/react`. `overrides` pins react/react-dom.
- **CI is strict `npm ci` — NO `--legacy-peer-deps`** (`.github/workflows/ci.yml:92-98`). Peer conflicts must be solved with pinned versions/`overrides`, never install flags.
- **Blocking design gates** (`ci.yml:105-119`): `lint:tokens` (no raw radii/px fonts), `lint:format`, `lint:elements` (raw-`<button>` ratchet, baseline 204 — **CopilotKit react-ui's injected buttons would trip this**; headless does not).
- Feature flags are backend-side: `aughor/kernel/flags.py` (`flag_enabled`, `FLAG_ENV` registry, ledger-kv override + env fallback). Frontend has essentially one env knob (`NEXT_PUBLIC_API_URL`, `web/lib/config.ts:9-11`).
- A **separate** `EventSource` on `GET /events/stream` (`web/lib/events.ts`) feeds Recents/History live refresh — independent transport, leave untouched.
- Debug seam: `⌘⇧L` opens the live SSE event-log drawer (`ChatPanel.tsx:484-494`) — use it to validate every phase below.

---

## 4. CopilotKit / AG-UI in mid-2026: the layer map

| Layer | Package | Version | Standalone? | Our use |
|---|---|---|---|---|
| Protocol spec + Python producer | `ag-ui-protocol` (PyPI) | 0.1.19 | yes (Pydantic events + SSE `EventEncoder`, py≥3.9; we're on ≥3.11) | **CK-1 backend** |
| Protocol client | `@ag-ui/client` (+`core`) | 0.0.57 | yes — zero CopilotKit deps; rxjs; `fast-json-patch`; `untruncate-json` partial-tool-args | **CK-1 frontend** |
| Headless React SDK | `@copilotkit/react-core/v2` (`useAgent`, `useRenderTool`, `useFrontendTool`, `useHumanInTheLoop`, `useInterrupt`, `useThreads`) | 1.62.3 | needs provider, but `selfManagedAgents` → talks straight to FastAPI, no Node runtime, no GraphQL | **CK-2 (gated)** |
| Node runtime | `@copilotkit/runtime` | 1.62.3 | n/a | **skip** (self-managed agents make it unnecessary) |
| Chat shell | `@copilotkit/react-ui` | 1.62.3 | v2 slots + `[data-copilotkit]` tokens | **skip** (§5.3) |

AG-UI event vocabulary (complete, per [docs.ag-ui.com/concepts/events](https://docs.ag-ui.com/concepts/events)): lifecycle `RunStarted/RunFinished(outcome)/RunError/StepStarted/StepFinished`; text `TextMessageStart/Content/End/Chunk`; tools `ToolCallStart/Args/End/Result/Chunk`; state `StateSnapshot/StateDelta(RFC-6902)/MessagesSnapshot`; activity `ActivitySnapshot/ActivityDelta`; reasoning `ReasoningStart/End`, `ReasoningMessageStart/Content/End/Chunk`, `ReasoningEncryptedValue`; special `Raw/Custom`; draft `MetaEvent`. Interrupt/resume: `RunFinished.outcome={type:"interrupt",interrupts:[{id,reason,message,toolCallId,responseSchema,expiresAt,metadata}]}`; client resumes with a new `RunAgentInput` on the same thread carrying `resume:[{interruptId,status,payload}]`.

---

## 5. Strategy

### 5.1 What we adopt
1. **AG-UI as the protocol at the seam** (CK-1) — because it's now the industry seam (LangGraph, Claude Agent SDK, Bedrock all speak it), because its new Activity/Interrupt events map 1:1 onto things we already emit ad-hoc, and because it makes Aughor *hostable* by any AG-UI client and Aughor's UI able to host other AG-UI agents later.
2. **`@ag-ui/client` as a transport adapter** under our existing `ChatTurn` reducer — not as a replacement for our state model. Our reducer + renderers are the product; the adapter is plumbing.
3. **CopilotKit ideas immediately, CopilotKit code only at the CK-2 gate**: partial-args progressive rendering (we re-implement trivially in Phase 0/1 since the translator controls framing), the interrupt UX model, and the slots/registry philosophy (we already have `TURN_RENDERERS`).

### 5.2 What we explicitly keep
The spine and every domain renderer: `ChatPanel` shell, `ChatMessage` + `TURN_RENDERERS`, `Brief*`, ECharts `Chart`/`ResultChartCard`, `ThinkingTrace`, `InvestigationReportView`, `ExplorationReportView`, `TrustReceipt`, `ClarifyCard`/`ClarifyGateCard`/`PlanGateCard`, restore semantics, WP-2 drop recovery, the kernel `EventSource`, all CI design gates.

### 5.3 What we reject, with reasons
- **`@copilotkit/react-ui` chat shell**: youngest layer; two coexisting theming systems during their v1→v2 migration; the June-30 spike burned real time on dark-theme overrides, branding removal (`.poweredByContainer`), and `<CopilotChat>` ignoring externally-set messages (breaks our history restore); its injected raw `<button>`s fight our `lint:elements` ratchet. Our shell is already good — it needs *liveliness*, not replacement.
- **`@copilotkit/runtime` (Node)**: pointless hop now that `selfManagedAgents`/direct `@ag-ui/client` exist; one more deploy unit; GraphQL legacy weight.
- **LLM-driven free-form UI (A2UI-style)** as default: contradicts the deterministic-first DNA; the June-30 experiment measured ~14s narrator latency for LLM-authored layout. Deterministic block composition won; keep it that way (revisit as opt-in later).

---

## 6. Event mapping: Aughor SSE ⇄ AG-UI

The translator (CK-1.1) consumes the *existing* generators and re-frames. It owns framing, so it can also fix emission-order warts (e.g. the post-`done` events) without touching the legacy endpoints.

| Aughor event (producer line) | AG-UI emission | Notes |
|---|---|---|
| `start` (`investigations.py:2196` etc.) | `RunStarted{threadId, runId=investigation_id}` | threadId = session/canvas thread |
| `agent` (`:3269`) | `Custom{name:"aughor.agent", value}` | AgentBadge payload |
| `route` (`:3144`) | `Custom{name:"aughor.route", value}` | DepthBanner receipt |
| `headline`/`answer` (whole string) | `TextMessageStart` + one `TextMessageContent` + `TextMessageEnd` — becomes true deltas once CK-0.2 lands | messageId per turn |
| `headline_delta` (NEW, CK-0.2) | `TextMessageContent{delta}` | the whole point |
| `insight` (`:1960`) | second `TextMessage*` block (role assistant) | emitted BEFORE RunFinished by translator (§CK-1.1 step 4) |
| `sql`, `columns`, `rows`, `chart_type`, `chart_config`, `tables_used` | `ToolCallStart{name:"render_answer"}` + incremental `ToolCallArgs` deltas + `ToolCallEnd` | stream figure args as complete-JSON blocks (spike-proven: `{"blocks":[` then one block per delta) |
| `phase_complete`/`phase_progress` (`:411-431`) | `ActivitySnapshot{activityType:"PHASE", content}` / `ActivityDelta` | drives ThinkingTrace |
| `hypotheses` (`:2477`), `queries_executed` (`:2482`), `score` (`:2486`) | `StateDelta` (RFC-6902 patches onto run state) | mirrors `turnToTraceState` inputs |
| `answer_report` (`:2495`) / `report` (`:2565`) | `ToolCall render_ada` / `render_report` | whole-payload tool args |
| `explore_plan`/`subq_answer`/`explore_report` (`:2522-2549`) | `ActivitySnapshot` beats + `ToolCall render_explore` | |
| `dossier_report` (`:2163`) | `ToolCall render_dossier` | |
| `clarify` (pre-answer, `:3087`) | `Custom{name:"aughor.clarify"}` initially (parity with ClarifyCard); optionally interrupt-shaped later | current resume = re-POST with `skip_clarify` — keep |
| `clarify_pending` (`:2417`) / `plan_pending` (`:2428`) | `RunFinished{outcome:{type:"interrupt", interrupts:[{id:inv_id, reason:"input_required"/"confirmation", responseSchema, message}]}}` | resume: new `RunAgentInput` with `resume:[{interruptId, payload}]` → translator calls `_stream_resume(inv_id, ...)` (`:2678`) |
| `followups` (`:1971`) | `Custom{name:"aughor.followups"}` | before RunFinished (translator reorders) |
| `learning`/`activations`/`trusted` (`:1873-1875`) | `Custom{name:"aughor.receipt.*"}` | today ignored by FE reducer; protocol carries them for future |
| `escalate` (`:1725`), `inspect_warning`, `analysis`, `playbook_refs`, `context_assembled`, `mode`, `clarifying_questions`, `fanout`, `compiled` | `Custom{name:"aughor.<type>"}` | lossless passthrough |
| `error` (`:1726` etc.) | `RunError{message, code}` | |
| `done` (`:1892`) | **no-op** — translator emits `RunFinished` only at generator exhaustion | this is how the post-`done` `insight`/`followups` wart is absorbed |

---

## 7. Phased implementation plan

Conventions for every work package: flag-gated default-OFF, additive-only, legacy path byte-identical when the flag is off, live-verified on the fixture DB (`/health` → `fixture_db:true`) before PR, gates green (`lint:tokens`/`lint:format`/`lint:elements`/tsc/build + pytest).

### Phase CK-0 — Land what we own (no new dependencies) — est. 2–3 days

**CK-0.1 Rebase + merge `2026-07-08-ui-ux-uplift`.**
- Branch: 5 commits `f01bd49→0a6bbf1`; touches `globals.css`, `ChatMessage.tsx`, `ChatPanel.tsx`, `brief/Brief.tsx`, adds `web/lib/useReveal.ts` + `useStickToBottom.ts`. 29 commits behind main; expect conflicts in `ChatMessage.tsx`/`ChatPanel.tsx` (rewritten by #141 reskin, #146 WP-2, #148 WP-5). Rebase commit-by-commit; the hooks themselves are conflict-free (new files).
- Known load-bearing details from the original build: the stick-to-bottom hook MUST use the **callback-ref pattern** (scroll container mounts after the empty state; an object ref silently binds to null); typewriter is gated to live turns via `animate={turn.startedAt > 0}`; shimmer scaffold gates on `turn.status==="loading"` (quick-mode data arrives at done, never mid-stream — until CK-0.3 changes that); all pieces reduced-motion-gated.
- Acceptance: all five behaviors live-verified in Data Canvas chat; restored turns show zero animation; gates green.

**CK-0.2 Token streaming for narrator text (the single highest-leverage change).**
- Backend, additive: give `LLMProvider` a streaming path for *prose* roles — either instructor's partial-object streaming (`create_partial`) or a raw text-stream method (`stream_text(system, user) -> Iterator[str]`) beside `complete()` (`aughor/llm/provider.py:412`). Scope: narrator-role call sites that produce user-visible prose — the quick-answer headline/insight (`investigations.py:1946`) first; report synthesis later.
- New SSE events, dual-emitted under flag **`ask.stream_text`** (env `AUGHOR_ASK_STREAM_TEXT`, register in `aughor/kernel/flags.py` `FLAG_ENV`): `headline_delta{text}` / `insight_delta{text}` chunks, ALWAYS followed by the existing full `headline` / `insight` terminal event. Old clients ignore unknown events (verified: unknown types are journaled, not crashed, `investigationStream.ts` default) → zero migration risk.
- Frontend: two new reducer cases appending `turn.headlineStream`/`insightStream`; render through the CK-0.1 typewriter path (`useReveal`/`safePartial` already handle dangling markdown). Terminal full event overwrites the accumulated string (self-healing if a delta was dropped).
- Acceptance: on an uncached question, first visible headline text ≤ ~1s after `sql` completes, growing smoothly; flag off ⇒ byte-identical stream (assert in a pytest that snapshots the SSE frames both ways).

**CK-0.3 Progressive answer emission (figure-first) for quick mode.**
- Today the success burst is monolithic (`:1793-1814`). Under flag **`ask.progressive_answer`** (env `AUGHOR_PROGRESSIVE_ANSWER`): emit `columns`+`rows`+`chart_type`+`chart_config` immediately after execution, then `headline`(/deltas) when the narrator finishes, then `analysis`/receipts. The spike proved the value: figure at +11.3s, prose at +17.6s — 6.3s where the user already sees data instead of a spinner.
- Frontend needs no change beyond CK-0.1's scaffold (which converts from "shimmer until done" to "fill as slots arrive" — flip its gate from `status==="loading"` to slot-presence once this flag is on).
- Acceptance: chart/table visibly renders before headline on an uncached ranking question; no empty-table flash (guard from CK-0.1: `rows.length===0 && streaming` ⇒ skeleton).

**CK-0.4 Kill deep-run dead air.**
- Verify `ada.progress_events` (`:411-431` interleave) end-to-end on a live deep run, then default the flag ON (it exists precisely for this; it's just dark). Confirm `ThinkingTrace` renders `phase_progress` beats (`web/components/ThinkingTrace.tsx` `deriveSteps`).
- Also fix cause #4's pop-in cheaply: give `insight`/`followups` arrival the same `aug-fade-in` treatment as turn arrival (they currently mutate a done turn with no transition).
- Acceptance: during a 2-min deep run the trace shows movement at least every ~10s; insight/followups fade in rather than snap.

### Phase CK-1 — AG-UI protocol seam — est. 4–6 days

**CK-1.1 Backend translator endpoint.**
- Add dep `ag-ui-protocol==0.1.19` to `pyproject.toml` (pure Pydantic, py≥3.9 — safe on our ≥3.11).
- New router `aughor/routers/agui.py`, registered in `api.py`, whole router gated by flag **`agui.endpoint`** (env `AUGHOR_AGUI_ENDPOINT`, default off ⇒ 404):
  - `POST /agui/run`: accepts AG-UI `RunAgentInput` (threadId, runId, messages, state, tools, forwardedProps, resume). Aughor specifics (`connection_id`, `canvas_id`, `agent_id`, `depth`, `insight_id`, clarify trio) travel in `forwardedProps` — exactly how the spike did it.
  - **Do not reimplement orchestration.** Extract a tiny factory in `investigations.py` — `build_ask_stream(req: AskRequest) -> AsyncGenerator` — that returns the same composed generator `/ask` uses (including `_stream_with_session`/`_stream_as_agent`/`_metered_stream` wrappers), and have both the legacy endpoint and the translator consume it. The translator maps frames per the §6 table using `ag_ui.core` events + `ag_ui.encoder.EventEncoder` (spike-proven).
  - `resume` array present ⇒ dispatch to `_stream_resume(inv_id, feedback, clarify_choice/keep_subquestions)` and translate that stream.
  - RunFinished ONLY at generator exhaustion (absorbs post-`done` events, §6 last row).
- Tests (hermetic): feed recorded Aughor event sequences (quick happy path incl. post-done insight/followups; deep with clarify_pending; explore; error; final_text short-circuit) through the mapper; assert AG-UI event order + JSON shapes. No live LLM needed — the mapper is pure.
- Acceptance: `curl -N POST /agui/run` on the fixture DB shows a well-formed AG-UI stream for all five recorded shapes; legacy endpoints byte-identical (flag off AND on — translator is additive).

**CK-1.2 Frontend transport adapter (UI untouched).**
- `npm i -E @ag-ui/client@0.0.57 @ag-ui/core@0.0.57` — exact pins; verify strict `npm ci` passes (no `--legacy-peer-deps`; if a transitive peer conflicts, solve in `overrides`).
- New `web/lib/aguiTransport.ts`: an `HttpAgent` (or thin `AbstractAgent`) against `/agui/run` + an `AgentSubscriber` that maps AG-UI events **into the existing dispatch actions** of `chatReducer` — TextMessageContent→HEADLINE_DELTA/INSIGHT_DELTA, ToolCallArgs(render_answer)→SQL/COLUMNS/ROWS/CHART, Activity→PHASE, StateDelta→HYPOTHESES/SCORE, Custom(aughor.*)→their existing actions, RunError→ERROR, RunFinished→DONE. `ChatTurn`, reducer, renderers: unchanged.
- Selection in `web/lib/useChat.ts`: `NEXT_PUBLIC_AUGHOR_AGUI=1` (new knob in `web/lib/config.ts`) picks the adapter; default remains `consumeStream`. Preserve abort semantics (AbortController → `agent.stopAgent`-equivalent) and add the WP-2 analog: on transport drop with a known `runId`, reuse `recoverAfterDrop(invId, dispatch)` verbatim (`investigationStream.ts:566-601` — export it).
- Acceptance: **side-by-side parity harness** — run the same 10 canonical questions (quick cached/uncached, deep with clarify gate, explore, dossier drill, error, agent-as, restore, followup click, abort) with the flag off and on; diff the final `ChatTurn` objects from the `⌘⇧L` debug drawer; require semantic equality (allow timing fields to differ). Zero console errors. Restored turns still inert (`startedAt===0`).

**CK-1.3 Interrupts for the mid-run gates.**
- Translator: `clarify_pending`/`plan_pending` → `RunFinished{outcome:interrupt}` with `responseSchema` built from the options/previews payloads (`:2417`, `:2428`). Adapter: interrupt outcome → existing `CLARIFY_PENDING`/`PLAN_PENDING` actions (same `ClarifyGateCard`/`PlanGateCard` UI). Resume: cards' handlers → `POST /agui/run` with `resume:[...]` when the AG-UI flag is on, else legacy feedback endpoint (branch in `useChat.resumeClarify`/`resumePlan`, `useChat.ts:181-196`).
- Acceptance: live deep run on fixture DB pauses at the clarify gate, card renders, choice resumes into the SAME turn, final report identical to legacy-path run.

**CK-1.4 Deep-run state/activity parity.**
- Map the full deep/explore vocabularies (§6 rows for phase/hypotheses/score/queries_executed/subq_answer) and verify `ThinkingTrace` output is beat-for-beat identical between transports on a recorded run.
- Exit criteria for Phase CK-1 overall: parity harness green for two weeks of dogfooding with `NEXT_PUBLIC_AUGHOR_AGUI=1` locally; then (and only then) consider flipping the default.

### Phase CK-2 — DECISION GATE: headless CopilotKit v2

Do **not** start this until CK-1 has run in dogfood. Adopt only if at least one of these is true:
1. We want **threads/time-travel/multi-agent state** UX (CopilotKit `useThreads`, `parentRunId` branching) and would otherwise hand-build >~500 lines of agent-state management on top of the adapter.
2. We adopt more AG-UI agents (e.g. hosting external AG-UI agents inside Aughor) and need their multi-agent provider.
3. The interrupt UX outgrows our two cards and we want `useInterrupt`'s schema-driven form generation.

If adopted: `@copilotkit/react-core@1.62.3` **exact-pinned as a wave together with its `@ag-ui/*` versions** (the #2840 lesson); `selfManagedAgents` pointing at `/agui/run`; **never** import `@copilotkit/react-ui`; v2 imports only (`@copilotkit/react-core/v2`). Budget check: 6.6 MB unpacked — confirm tree-shaken impact on `npm run build` before committing.

### Phase CK-3 — react-ui chat shell: REJECTED (see §5.3). Revisit only if their v2 slots mature and we ever want a floating copilot surface *outside* the canvas chat (e.g. a global assistant over Settings/Hub pages) where our shell doesn't already exist.

---

## 8. Hard guardrails (the "don't break it this time" contract)

1. **Never modify `/chat`, `/ask`, `/investigate` emission when the new flags are off.** Every backend change is dual-emit or additive-endpoint. A pytest snapshot of legacy SSE frames guards this.
2. **Never replace the chat shell.** `ChatPanel`/`ChatMessage`/renderers stay; only the transport under them is switchable.
3. **Every step behind a flag with a kill switch**: `ask.stream_text`, `ask.progressive_answer`, `agui.endpoint` (backend, in `FLAG_ENV`) + `NEXT_PUBLIC_AUGHOR_AGUI` (frontend). Default OFF until the parity harness says otherwise.
4. **Exact-pin external deps; whole waves only.** `@ag-ui/client@0.0.57`+`@ag-ui/core@0.0.57` now; if CK-2 happens, `@copilotkit/*@1.62.3` + its matching `@ag-ui/*` set in one commit. Strict `npm ci` must pass; conflicts solved via `overrides`, never `--legacy-peer-deps`.
5. **Preserve WP-2 robustness invariants** across transports: content-type guard, drop-recovery via `GET /investigations/{invId}`, abort→DONE, error-is-terminal.
6. **Preserve restore semantics**: `startedAt===0` turns are inert (no animation, no timers, no route banner).
7. **Do not touch** `web/lib/events.ts` (kernel EventSource) or any non-chat surface.
8. **CI design gates are law**: no raw `<button>` additions (ratchet 204), tokens/format gates green, `npm run build` green.
9. **Push every branch same-day.** The June-30 spike died because two working branches were never pushed. Worktree → PR early, even as draft.
10. **Live-verify on the fixture DB before every PR** (`/health` → `fixture_db:true`), with the `⌘⇧L` event drawer open, on the "Luxury Retail Operations" canvas; zero console errors is part of acceptance.

---

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `@ag-ui/*`↔`@copilotkit/*` version skew breaks types/peers on upgrade | HIGH (documented, #2840) | build failure | exact pins, whole-wave upgrades, upgrade in a worktree with `npm ci` + tsc before merging |
| Streaming provider path (CK-0.2) destabilizes structured-output calls | MED | wrong answers | new method beside `complete()`, prose roles only; guards/structured paths untouched |
| Progressive emission (CK-0.3) breaks a consumer that assumed burst order | MED | UI glitches | flag-gated; parity snapshot test; audit the three consumers of quick-mode events (ChatPanel, HistoryDetail restore, briefing drills) |
| Translator drifts from legacy generators as new events are added | MED | silent feature loss on AG-UI path | translator consumes the SAME generator (factory extraction); unknown Aughor events map to `Custom{aughor.<type>}` by default — lossless by construction |
| AG-UI protocol still 0.0.x/0.1.x — event semantics could shift | LOW-MED | rework | seam is one file each side (`agui.py`, `aguiTransport.ts`); protocol is additive-evolution with major adopters constraining breakage |
| CopilotKit open-core drift (persistence → paid tier) | MED (CK-2 only) | roadmap trap | we keep our own persistence (`chat-sessions`, investigations store); never depend on their cloud |
| Bundle bloat (react-core 6.6 MB unpacked) | LOW (CK-2 gated) | perf | measure at the CK-2 gate; protocol-only path adds only `@ag-ui/client` (rxjs already the heaviest transitive) |
| The old failure mode: half-migrated UI fragmentation | — | the thing the user fears | phases are independently complete; each leaves the product in a shippable state; CK-2/3 are explicitly optional |

---

## 10. Verification playbook (run per work package)

1. Backend: `uv run pytest` (full suite is hermetic since #125/#146 — registry/glossary env-pointed); new SSE-snapshot tests both flag states.
2. Frontend: `npm --prefix web run lint:tokens && npm --prefix web run lint:format && npm --prefix web run lint:elements && npx tsc --noEmit && npm --prefix web run build`.
3. Live: start api (:8000, fixture DB) + web (:3000) dev servers; Data Canvas → "Luxury Retail Operations" → Chat tab; `⌘⇧L` drawer open.
4. Canonical question set (cover every renderer): single-value KPI ("total gmv"), ranking ("total orders by platform"), time-series ("gmv by month"), definitional, deep run that trips the clarify gate, explore run, dossier drill from briefing, an error (bad column), a followup-chip click, a history restore, an abort mid-stream.
5. For motion/streaming claims: use instrumented `preview_eval` timelines (record first-token time, scaffold-fill time, scroll behavior) — screenshots don't prove motion.
6. Gotchas from prior sessions: ECharts inits async (~seconds) — don't judge "render failed" from early DOM polls; HMR resets chat turns; the Briefing landing page also has a textarea — confirm placeholder "Ask anything about your data…" before driving; restart the web server for guaranteed-fresh browser state.

---

## 11. Appendix A — salvaged learnings from the lost June-30 spike

Worth preserving because they were live-verified and non-obvious:
- The **thin-translator pattern works**: `_stream_chat` consumed verbatim, re-emitted as AG-UI via `ag_ui.core` + `EventEncoder`; live `/chat` untouched. (Reused as CK-1.1.)
- **Incremental ToolCallArgs streaming works in practice**: emit `{"blocks":[` then one complete-JSON block per delta, then `]}` — clients partial-render growing args; worst case renders at ToolCallEnd. Figure-before-narrator gave chart at +11.3s vs prose +17.6s.
- **Deterministic block composition beat LLM-authored layout**: kpi/chart/table/prose/callout/bullets picked by data shape, instantly; LLM layout cost ~14s narrator latency → opt-in at best.
- **v1 `<CopilotChat>` ignores externally-set messages** (`setMessages` runs, UI doesn't update) → history restore must render with our own components. (Moot if we never adopt react-ui; relevant warning if CK-3 is ever reopened.)
- Theming/branding fights: `[data-copilotkit]` var overrides for dark mode; `.poweredByContainer` is the *input container* — hiding it wholesale kills the input box.
- Follow-up chips submitting via native setter + Send click was version-stable; importing runtime-client-gql internals was not.
- `@copilotkit/*` 1.61.2 needed `--legacy-peer-deps` on React 19/Next 16 — **no longer true** at 1.62.3 (React 19 in peer range), but the strict-`npm ci` check remains mandatory.

## 12. Appendix B — primary sources

- AG-UI events: https://docs.ag-ui.com/concepts/events · interrupts: https://docs.ag-ui.com/concepts/interrupts · architecture/transports: https://docs.ag-ui.com/concepts/architecture · JS client SDK: https://docs.ag-ui.com/sdk/js/client/overview · Python events: https://docs.ag-ui.com/sdk/python/core/events
- AG-UI repo (integrations matrix, dojo source `apps/dojo`): https://github.com/ag-ui-protocol/ag-ui · live dojo: https://dojo.ag-ui.com/langgraph/feature/agentic_chat
- CopilotKit repo: https://github.com/CopilotKit/CopilotKit · v1.50 architecture change (GraphQL removal): https://docs.showcase.copilotkit.ai/whats-new/v1-50 · self-managed agents (skip the runtime): https://docs.showcase.copilotkit.ai/backend/self-managed-agents · headless: https://docs.showcase.copilotkit.ai/headless · runtime REST/SSE endpoints: https://docs.showcase.copilotkit.ai/backend/runtime-endpoints · HITL/useInterrupt: https://docs.showcase.copilotkit.ai/human-in-the-loop/useInterrupt · tool rendering: https://docs.showcase.copilotkit.ai/generative-ui/tool-rendering
- Version-skew issue: https://github.com/CopilotKit/CopilotKit/issues/2840 · render-seam bug: https://github.com/CopilotKit/CopilotKit/issues/2622
- npm: `@copilotkit/react-core@1.62.3`, `@ag-ui/client@0.0.57` (registry JSON) · PyPI: `ag-ui-protocol==0.1.19`
