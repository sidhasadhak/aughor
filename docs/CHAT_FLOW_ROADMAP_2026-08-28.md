# Chat Flow & Reach Roadmap — 2026-08-28

Derived from the Chat SDK / Agent Stack study (2026-08-28; see memory
`chat-sdk-agent-stack-study` and the published study artifact). Two tracks:
**FL (Flow)** makes the web chat feel like a frontier-LLM conversation;
**RC (Reach)** puts Aughor where users already work (Slack first). Every wave
opens with a measured pre-check and closes with a live receipt — FL-0 already
moved the scope (again): three of the study's "missing" items were built in CA-1.

---

## FL-0 — Audit (DONE 2026-08-28)

Measured against the AI SDK 7 / Chatbot-template mechanism list, on this tree
(branch `claude/aughor-chat-sdk-research-da0a81`, main `f9eb271`):

| Mechanism | Study assumed | Measured on disk |
|---|---|---|
| Edit-and-resend | missing | **BUILT** (CA-1) — `ChatPanel.tsx:1120` replaces the user message and re-sends |
| Regenerate | missing | **BUILT** (CA-1) — `ChatPanel.tsx:1173`; stops first if busy |
| Data-part reconciliation | unverified | **Handled** — adapter converts REPLACE-semantic partials to APPEND chunks; terminal report replaces the partial (`uiMessageAdapter.ts:94,296`) |
| Streaming-markdown healing | unverified | **Partial** — `safePartial` (`lib/useReveal.ts:53`) closes a dangling `**`; caret + no-remount swap (CK-0.2). Lists/tables/code fences unverified |
| Send-while-streaming | assumed gap | **Deliberate design** (P5) — input never disabled; sending interrupts the in-flight run at the next checkpoint |
| Stick-to-bottom | present | Confirmed (`lib/useStickToBottom.ts`) |
| Render throttling | check | **Absent** — no throttle in `useAughorChat` |
| Model-health notice | missing | **Absent** — no waiting/degraded logic anywhere in chat |
| Resumable streams | missing | **Absent — worse than missing**: disconnect *fails the run* (below) |

**The FL-1 pre-check (the load-bearing finding).** A client disconnect cancels
the SSE coroutine (`CancelledError`); the stream's `finally` orphan-reconcile
marks a still-`running` investigation **failed** (`routers/investigations.py:4171-4185`
— the comment names client disconnect as the dominant cause). A browser refresh
mid-deep-run destroys the run. Assets already in place for the fix: runs execute
under a **supervised kernel job** (`/investigations/{id}/cancel` cancels via
`kernel().cancel(job_id)`); LangGraph checkpoints persist per `inv_id`
(SqliteSaver) with a salvage path; `stream_with_session_log` is observability
only (flag-gated, sniffs frames — not a replayable journal); backend partials
are REPLACE-semantic, so a resume snapshot needs only latest-frame-per-channel
plus one-shot frames, not the token history.

---

## Track FL — Flow (web surface)

### FL-1 — Runs survive the connection (BUILT 2026-08-28, flag `ask.resume_stream`)
> **GRADUATED 2026-08-28**: both declared receipts delivered live the same day
> (browser-soak reattach; interrupt cancels the kernel job), so the mirror and
> `GET /ask/stream/{session_id}` are hardwired and the flag, its env var and
> its off-path are deleted. The receipt record lives on the GRADUATION_QUEUE
> tombstone in `kernel/flags.py`. FL-5's sequencing precondition is now met.
**Premise correction (found while wiring):** FL-0's "disconnect fails the run"
was true only for the ANALYST deep body (`ask.converse` on — this laptop's
default) and the quick paths. The graph deep path already ran detached under a
supervised kernel job (K1, `_investigation_job_streamed`); its finally-comment
about client disconnects predates K1. What was actually missing: (a) any way to
REATTACH, (b) K1 coverage for the analyst body, (c) stop/interrupt actually
cancelling the job — the SDK abort never did, so every "stop" on a deep run
left it burning server-side (pre-existing, now fixed).
1. **FL-1a — frame hub** (`aughor/util/frame_hub.py`, 9 tests): snapshot-then-
   tail per run; lagged consumers told to re-attach; TTL'd; in-memory, no new
   `data/` writer.
2. **FL-1b — the bridge generalised + the reattach surface:**
   `_job_streamed_body` (extracted from K1) now carries BOTH deep bodies —
   graph and analyst — giving the analyst job supervision, cancellability, and
   terminal-consistency (the bridge sniffs the investigation id off the frames
   and reconciles a still-`running` row when the run ends without a terminal —
   a cancelled analyst run used to sit `running` until the sweep, seen live).
   Behind `ask.resume_stream` (registered: FLAG_ENV + FLAG_META +
   GRADUATION_QUEUE with its receipt shape) the bridge mirrors frames into the
   hub; `GET /ask/stream/{session_id}` replays snapshot + tails (204: flag off /
   nothing running / already finished — history owns finished turns). Web:
   `GET /api/chat/[id]/stream` translates through the SAME adapter as the POST
   route (shared `lib/chatProxy.ts`); `useAughorChat` passes `resume: true`;
   ChatPanel's stop/interrupt/clear now call `cancelInvestigation` for the
   in-flight run.
- **Seam tests:** `tests/unit/test_resume_stream_seam.py` (6) — drive the REAL
  bridge with a faked body; fail the moment the mirror is unplugged.
- **Receipts (LIVE, scratch API, converse ON — the real path):** client killed
  at 8s → run survived → new client's GET replayed from frame 1 and tailed to
  the correct answer (15.6KB, `done` terminal). Cancel: `cancelled: true` with
  the job id (would have 404'd for analyst runs before), investigation row
  `failed` (terminal), resume 204 after.
- **Graduation receipt: DELIVERED IN-BROWSER 2026-08-28** (worktree dev server
  on :3100 → scratch API on :8931, flag on, converse on). An 85-second deep run
  was reloaded at ~4s; the reloaded page reattached and rendered the SAME run —
  question bubble, live "Scanning dimensions · 3/3" phase progress, and
  completion ("Thinking complete · Completed in 1m 25s") — as ONE turn. Wire
  proof: `GET /api/chat/{id}/stream 200 in 85s` (twice — React strict-mode
  double-mounts the resume; the stable id reconciled both into one message).
  FL-2's SlowTurnHint also appeared live mid-soak during a quiet stretch.
  The soak surfaced and fixed two client gaps: (a) `projectThread` DROPPED an
  orphan assistant message, rendering a resumed run as a blank page — it now
  synthesizes the user side from the question the adapter stashes off the
  wire's `start` frame as message metadata; (b) each resume stream minted a
  fresh message id, so strict-mode's double-GET duplicated the turn — the
  resume route now passes a stable `resume-{conversation}` id.
  Flag exit is now unblocked: hardwire the mirror + endpoint, delete the flag.
- Leave-behinds: the `route` receipt frame is emitted before the bridge, so a
  resumed replay lacks it (mode falls back in the projection — polish: publish
  pre-body frames into the mirror too). Quick paths remain request-bound by
  design (seconds-long). Separate PRE-EXISTING gap the soak made visible: the
  `/investigate` door never files chat-session turns, so a reload AFTER a run
  finishes shows an empty thread (no history to restore; resume correctly 204s
  on closed runs) — the reload-after-completion story needs the session store
  to cover that door (its own wave, not FL-1).

### FL-2 — Slow/degraded-model notice (BUILT 2026-08-28 — live receipt pending)
The chain narrates its hops: `emit_chain_state` in `agent/progress.py` (4th
sink payload family, `__chain_state__`), called from all four provider
fallback sites (`llm/provider.py` — engage + link-failed, tool and complete
paths; shielded lazy import, can never break the call), translated to a
`chain_state` SSE event at all three sink-translation points in
`routers/investigations.py`. Web: `chain_state` declared part → `t.chainState`
projector → `ChainStateNotice` (amber quiet line, loading state) +
`SlowTurnHint` (12 s of NO frames → "taking longer than usual"; every frame
re-projects the turn and re-arms the timer). Scope: chain frames flow where
the sink binds (deep path + shim paths — hardwired on since the flag endgame);
the quick path gets the silence hint only.
- Tests: `tests/unit/test_chain_state_events.py` (5) · chatTurn projection test
  · tsc clean · eslint at HEAD baseline (its 4 hook errors pre-exist).
- **Receipt: DELIVERED LIVE 2026-08-28** (user-authorized spend). Scratch API
  from this worktree (throwaway system DB, synthetic fixture DuckDB, wedged
  gemini primary via env bogus key + key removed from a config COPY; chain
  pinned to openrouter). Wedged deep run: **7 `chain_state` frames**
  (`fallback gemini → openrouter`, roles coder/fast/narrator), run COMPLETED
  through the fallback with the correct grounded answer ("Electronics …
  $4,250.50"). Clean run (config restored): **0 chain_state frames**, correct
  answer. Real instance and real data files never touched.
- Leave-behinds (polish, not blockers): a bogus Gemini key classifies as
  "structured output empty", not an auth error (the client swallows the 401) —
  `detail` names the symptom; two `detail` strings carried raw repair-ladder
  `<failed_attempts>` text (truncated at 200 chars) — worth a cleaner summary
  string someday. The wedged run also produced no `report_delta` frames (the
  fallback synthesis path doesn't stream prose) — pre-existing, not FL-2.

### FL-3 — Streaming-text robustness (measure first)
Extend `safePartial` to unclosed backticks/fences/table rows *if* narratives
actually emit them (grep session logs first); adopt render throttling only if a
measured jank exists (frontier answer lengths at our 13px root — profile, don't
assume).

### FL-4 — Turn-merging (evaluate, likely park)
Interrupt-latest-wins is a deliberate P5 design. Revisit only with session-log
evidence that users send multi-fragment turns; if so, burst-merge à la Chat SDK
(`context.skipped`) *behind the same interrupt semantics*, never a lock.

### FL-5 — In-flight engagement for deep runs (projection/presentation only)
> **BUILT 2026-08-28** (post-graduation, as sequenced). `explore_plan` +
> `subq_answer` left UNRENDERED_FRAMES and project into the turn (plan =
> denominator, answers = last-wins accumulation + in-flight prose); the wait
> composes into `RunProgressCard` (spinner line · real-denominator bar · mono
> meta · FL-2 notices inside) with `InFlightFindings` beneath, replacing the
> stacked B3 task list. No new stream events, no backend change. Visual
> receipt against the mock's pending card verified live in the app shell.
A deep run's wait should read as an analyst working, not a spinner holding.
Everything needed is ALREADY ON THE WIRE — `phase_progress`
(done/total/current), `queries_executed`, `subq_answer`, `phase_complete`,
`chain_state` (FL-2), guard receipts, delegations — so this item is two
projection/presentation slices and NO new stream events:
1. **Narrative interleaving — the actual engagement payload.** `subq_answer`
   frames arrive incrementally (T3-3: per-subq evidence, "so the wave path
   isn't a multi-minute silent gap") but today only accumulate into the
   terminal report. Project them into streamed in-flight prose inside the turn
   ("So far East and South look flat…") — a `chatTurn.ts` projection change
   plus ChatMessage rendering.
2. **Composition pass.** The loading state stacks separate widgets — the B3
   dimension-scan task list (ChatMessage.tsx ~1549), DelegationTrail,
   GuardReceiptChain, shimmer. Tighten into ONE compact in-place progress card
   (spinner line, progress bar, mono meta line) that swaps into its result
   when the phase lands. Styling and composition only.
Visual reference: the pending-state card in the second assistant turn of the
mock at https://claude.ai/code/artifact/6d618590-c64f-479e-b198-29ae4bc4698d.
- **Constraint (sequencing):** AFTER FL-1 GRADUATES. Engagement raises watch
  time and therefore the disconnect/reload window. (Recorded 2026-08-28 as
  "a disconnect still fails a running investigation"; since #403 the K1 job
  survives the disconnect — but the reattach surface is still flag-dark, so
  a watcher who reloads mid-run loses the view. This polish must not make
  people watch longer until reloading can bring the run back.)
- **Non-goal (rejection of record, 2026-08-28, separate session):** NO
  generative-UI card registry, NO metric/anomaly tiles à la Chat-SDK cards.
  Rejected because polished chrome lends false authority to wrong numbers; it
  duplicates render paths that already exist (ChatMessage.tsx has SqlView,
  SqlResultTable, open-in-SQL-editor via useOpenInQuery, CSV export,
  pin-to-dashboard); and this repo's history says presentation planes go
  inert. The one slice worth keeping renders *process*, not conclusions —
  that slice is this item. Do not re-propose the catalog.

### FL-6 — A deep run belongs to its conversation (BUILT 2026-08-28)
The reload story's other half. CA-0 stamped `session_id` on deep runs, but
every THREAD READ filtered `kind = 'chat'` — so the web's default (Agent) mode
produced conversations that reloaded as blank pages and a rail of quick
questions only (measured live: five sessions, all quick-shaped). Fixed on the
READ side — the write side already worked:
- `_THREAD_TURN_KINDS` (history.py): terminal deep rows join the thread's
  turns, rail listing/count/title, rename-ownership, and reconstructed memory
  (as question + headline, never a fabricated query). A LIVE run stays out
  deliberately — the resume hub (FL-1) owns it, and restoring a running shell
  would duplicate against the resume stream's synthesized turn.
- `_turn_to_ui_messages`: a deep row restores as the live wire shape — one
  `data-answer_report` part (full report renders via `projectDeepReport`,
  zero client changes), investigate mode on the user message, and an honest
  `data-error` tail for failed/timed_out/interrupted (no report-shaped shell
  around nothing).
- Delete semantics: a thread delete UNFILES deep runs (`session_id` → NULL —
  they also serve Fleet and agent history) and must do so BEFORE
  `delete_investigation`, whose id-OR-session_id predicate would take the
  runs with it; a deep-only thread now deletes as the thread, not a 404.
- Tests: `tests/unit/test_fl6_deep_threads.py` (7) + CA-5/CI-1 suites green.
- **Receipt (zero-LLM, over HTTP):** seeded a completed deep row in a scratch
  store, drove the REAL endpoints — the rail listed the deep-only thread
  under its question; `/chat-sessions/{id}/messages` restored the
  user+assistant pair with the `data-answer_report` part, byte-compatible
  with the live wire.

## Track RC — Reach (distribution)

*RC-1+ needs user-side setup (a Slack app in their workspace, state store
choice); sequenced after FL-1 unless the user pulls it forward.*

- **RC-0 — Aughor agent skill**: `SKILL.md` + `llms.txt` + machine-readable
  connector catalog (env vars, which are secrets — `chat/adapters` pattern).
  Cheap, standalone, no runtime coupling.
- **RC-1 — Slack bot spike (Chat SDK)**: thin TS transport, `onNewMention` →
  Python `/ask` SSE → `thread.post(asyncIterable)`. Python keeps loop, guards,
  tenancy. `@chat-adapter/tests` from day one; pin versions (weekly-minor beta).
  Receipt: @mention answered, streamed, in a real workspace thread.
- **RC-2 — Investigation streaming into Slack**: stage progress as `task_update`
  cards; platform stop button → `/investigations/{id}/cancel`.
  *Scope extended 2026-08-29 (user-decided, after RC-1's live receipt): the
  visual half of the answer joins this wave.* **Charts** — render the turn's
  `chart_config` through the EXISTING Vega-Lite SSR path (the PDF/PPTX export
  renderer; one grammar, no second engine) and upload the PNG to the thread.
  **Tables** — small results inline as GFM/monospace (the Chat SDK's streaming
  healer already buffers GFM tables), larger ones as an attached CSV; Slack has
  no table widget, so past ~6 columns the CSV is the honest form. **Deep link**
  — every answer carries "Open in Aughor →" to the conversation, where the
  interactive chart, full table, SQL and Trust Receipt live: Slack is the
  doorway, the platform stays where verification happens.
- **RC-3 — Durable approval cards**: the `requestApproval` *shape* (card +
  durable wait + timeout + approver identity) ported to Python; unstalls the
  scheduled-task first-run approval trap. Do not import the Workflow runtime.
- **RC-4 — Identity-keyed transcripts**: stable identity resolver; the shape for
  the open Langfuse LF-2 attribution question; prerequisite for Slack↔web
  thread continuity.
- **RC-5 — Bot doors become records** (design fixed 2026-08-29, user-decided):
  a Slack bot is a stored {credentials} → {agent_id, connection_id} binding, not
  an `.env.local`; users create as many as they want via a rendered manifest
  (one Slack app per bot — route A of three; JSON, never the YAML tab), a
  registry-driven supervisor runs N sockets in one process, and a new
  `Effect(kind="slack_post")` lets a cron post AS the bot so the reply threads
  back onto the same conversation. Its one prerequisite — headless doors leaving
  holes in their own conversations, because `_stream_converse` never filed turns
  server-side — was **closed by RC-2** (`a274728b`, chip `task_17fc91f9`), so the
  factory is unblocked. Full spec, with steps and receipts:
  `docs/ROADMAP_SLACK_BOT_FACTORY_2026-08-29.md`. *Not yet sequenced against
  RC-2..RC-4 — the user's call.*

## Parked / other arcs
- Semantic-layer-as-greppable-YAML + terminator-tool + errors-as-tool-output →
  agent-mode arc, not this one.
- Vercel Connect → WATCH; evaluate when RC-1 exists (prod is on Vercel).
- eve · Workflow SDK as runtime · ToolLoopAgent as core loop · per-request
  sandboxes → SKIP (each replaces a working Python organ; splits tenancy).

## Sequencing (user-decided 2026-08-28)
**FL-2 → FL-1 (behind a registered flag) → RC-0 → RC-1 → RC-2 → FL-3 → RC-3 → RC-4 → FL-4.**
FL-5 (added 2026-08-28) is not yet sequenced against the RC track; its one hard
precondition is FL-1's graduation.
FL-2 first banks a low-risk additive win; FL-1 then lands BEHIND A REGISTERED
FLAG (register it properly — `flag_enabled()` is False for unregistered names,
indistinguishable from "off") so detachment can be flipped off without a revert.
FL-1b must also rewire the P5 interrupt to an explicit server-side cancel —
after detachment a client abort no longer stops the run (unattended spend
otherwise; budgets bound it, but the interrupt receipt must prove the kill).
One wave per PR; pause between waves; nothing pushes without explicit permission.
