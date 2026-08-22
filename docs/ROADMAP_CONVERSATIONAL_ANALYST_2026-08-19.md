# Arc CA — the Conversational Analyst (2026-08-19)

> **One roadmap for two studies that found the same defect.** `VERCEL_CHATBOT` revisit
> (memory `vercel-chatbot-revisit-2026-08-19`; state measured on main `2987984`) and
> `REPORT_QUALITY_DEEP_DIVE_2026-08-19.md` (the Direkteingabe specimens vs Databricks Genie).
> In the chat, a 107-case closed reducer narrates a shape code chose; in the deep path, a fixed
> phase script narrates a shape code chose. Both are **structure where the intelligence should
> be**. This arc puts the model where the decisions are — *the conversation is the analyst, and
> the analyst can see* — and keeps the guards that are actually guards.
>
> Supersedes nothing that is locked (§6 of `PLATFORM_ROADMAP_2026-08-12.md` stands: one
> application, brain in Python, BYOK, tiered writes). It *finishes* what Arc CI left half-built
> (CI-1d's migration, CI-4's door, CI-6a's frame streaming) and adds what the deep dive found.
> Status: **APPROVED by the user 2026-08-19 ("all in").** CA-0 merged to main as #359
> (`c3ba392`); CA-2 merged as #360 (`689b949`); CA-1, CA-3 and CA-4 merged as #361
> (`73caa9f`); CA-5 built on `claude/ca-5-fluidity` (see their STATUS blocks). The arc's
> waves are all built.
> §5-3 (PDF renderer) is DECIDED — (a), node subprocess; the rest of §5 remains open.

---

## 0 · Thesis, in three sentences

1. **Genie won by grammar, not by IQ** — slice, *see*, slice again. Our deep path gives the
   model two decision points, both before any row exists, and no result-reactive step
   (`aughor/agent/orchestrator.py:15-24`, by design, over-generalizing an n=12 SQL-guard
   ablation). The answer to "why is Direkteingabe up?" was three SQL slices away and nobody was
   allowed to take them.
2. **Guards split two ways.** SQL-level *verification* (fan-out, value-domain, id-arithmetic —
   the Verifier) is pure upside: keep it inside every tool. Analysis-level *restriction* (fixed
   script, pre-committed windows/dimensions, "2–3 queries", "never derive a number", word-list
   checks, repair text shipped to the reader) is what the user feels as "choking" — and the
   guards that would have mattered (window degeneracy, partial periods, zero-row conjunctions,
   row-based confidence) do not exist.
3. **The chat surface that shows tool steps as they happen is the natural home for an analyst
   that slices in the open.** The AI-SDK parts model is adopted and its seam is built and proven
   (#350) — the live `/chat` just never crossed it. Cross it, then stream the analyst through it.

---

## 1 · What is true today (measured — do not re-derive)

**Chat (`web/`):** two stacks coexist. LIVE: `ChatPanel` 1,134 + `ChatMessage` 1,611 (21 organ
imports) + home-grown `lib/useChat.ts` 298 + `investigationStream.ts` 846 (107-case closed switch,
77-field `ChatTurn`; 10 importers incl. `BriefAskPanel`, `aguiTransport`). PILOT (CI-1d, #350):
`ai@7.0.55` + `@ai-sdk/react@4.0.58` (ahead of upstream's 7.0.15 / 4.0.16), `uiMessageAdapter.ts`
320 (pure SSE→UIMessage; REPLACE→APPEND diff), `app/api/chat/route.ts` 160 (proxy + 3
`consumeStream` invariants), `useAughorChat.ts` 67, `/chat/parts` proving route, `PartsMessage`
152 (renders 4 parts + generic fallback). All 44 reducer frame names have a backend emitter; 37
typed data parts cover the wire (the missing 10 are SDK-native: text deltas, start/finish/error).
**The migration is unblocked on coverage and blocked on nobody doing it.** `/chat` (CI-6b) is a
full-page `ChatPanel` + `ThreadsRail` and says in its header it is NOT on the parts model. The
deep branch of `useChat.ts:147` posts `history` but **no `session_id`**.

**Deep path (`aughor/agent/investigate.py` ~8.7k lines):** 7 LLM calls/run — intake (coder),
phase SQL ×N (coder, slot-filled template), phase interpret ×N (fast), synthesis (narrator) + 1
check-retry + followups. 3 decisions, all pre-result; 4 narration. Phase order is Python
(`route_after_*`); `phase_waves.py` runs the middle three phases concurrently and severs even the
soft prose link. The tool loop exists (`tool_loop.py:105-246`, `converse_tools.py`, roster incl.
`deep_analysis`), budget 4/8 steps by `ModelProfile`, but `_converse_eligible`
(`routers/investigations.py:4410-4434`) refuses `deep`/`escalate`, and `ask.converse` is
**default off** in deployments (`kernel/flags.py:84,268`; local runs ON).

**The 8 defects with file:line** (from the deep dive — the run records prove each):
① coverage clamp sets comparison == observation, tells nobody downstream, and the guards that
could catch equality bail on it (`investigate.py:3518-3524`, `:3547`, `:5549`;
`_MEASURE_COL_RE :2331` omits `abs_change`) ② `_orchestration_plan` / `_baseline_rel_change` not
declared on `AgentState` ⇒ LangGraph drops them ⇒ plan null on **144/144** reports
(`state.py:545-564`, `investigate.py:4941→8120`) ③ confidence floor keys on `columns` not
`row_count` and the intake-spec finding always satisfies it ⇒ dead ⇒ zero-row run shipped HIGH
(`:8395-8397`; correct predicate at `:1637`) ④ #36 grounding has no derivation credit
(`report_checks.py:139-214`; `explorer/verify.py:469-489` has it) and reports whole sentences as
fabrications ⑤ #15 is a verb regex incl. `increase` (`claim_type.py:42`) under a licence that
says "how it changed" (`:145-148`); title fuses with sentence 1; negation window 4 words
⑥ repair instruction concatenated into customer `confidence_justification` (`:8358-8361`), PDF
renders it (`export/document.py:377-379`), web hides it — 10/144 reports, all since 08-15
⑦ deep follow-up: no `session_id`, `is_followup` misses "only focus", no spec carry-over ⇒ metric
"Total Orders", cross-sectional, `CHANNEL_LVL_0='Direkteingabe'` ⇒ 0 rows (value lives only at
LVL_1); value-domain guard probes columns independently — no conjunction check ⑧
`observation_label` "February 2025" = the schema's example string, not rewritten for temporal
runs (`:4848-4856`); contradiction detector reads prose word-lists not `is_significant`
(`orchestrator.py:212-237`); partial terminal month never normalized.

**Charts:** `severityRamp` value-ramp on nominal categories (the "red & orange";
`exhibit.ts:60-63,85`); `barMaxWidth: 34` in a full-width band (bars "miles apart";
`builders.ts:476-479`); 6 tokens FAIL the lightness band (3/6 dark), overflow ramp FAILs CVD at
ΔE 4.9 on 10 categories (`theme.ts:38-49`); no emphasis form; labels on every mark; titles =
query names; 24-option `chart_type` Literal + 364-line inference; PDF = separate 676-line
matplotlib port (`export/charts.py`).

**The truth in the specimen data** (for receipts): Direkteingabe human traffic grows ~900 →
1,119 → 1,439 sessions/day Jun→Aug (iOS/Mobile Safari carries 55% of the July delta; Jul 26 is a
real event at 23.6% bounce); a bot population (Chrome UA "105", macOS desktop, German ISPs,
99.8% bounce) quadrupled in August to 21% of the channel. August has 18 days.

---

## 2 · Per-layer verdicts (chat) — carried over, now binding

| Layer | vercel/chatbot gives | Verdict | Why |
|---|---|---|---|
| Message data model (UIMessage/parts) | open part model; unknown part → fallback; persisted form == streamed form | **ADOPT** (done; migrate) | retires the closed switch and `_ReconstructedTurn` |
| Client hook + transport (`useChat`, `DefaultChatTransport`, `status/stop/regenerate`, resume) | 298 + 846 lines of home-grown lifecycle replaced | **ADOPT** | edit/regenerate/branch become free; plan/clarify approvals stay side POSTs |
| Shell components (sidebar-history, message-actions, message-editor, multimodal-input, suggested-actions, data-stream-provider, use-stick-to-bottom, greeting) | the *patterns* | **REFERENCE** | Base-UI + tokens, zero Radix/framer-motion, `lint:elements` 69/69; hand-port the shape, never the code (Ontos rule) |
| Artifacts (text/code/sheet/image editors, ProseMirror/CodeMirror) | — | **NO** | nothing to say about a governed SQL result; ours are `InvestigationReport`/`Brief`/`SqlView`/charts |
| Server (`streamText` loop in TS, Drizzle, next-auth, redis resumable) | — | **NO** | brain, guards, BYOK, conversation record and tenant boundary stay Python; `/api/chat` is a proxy |

vercel/chatbot is a copy-once **template**; the framework is the `ai` package, already adopted.

---

## 3 · Waves

Each wave has a **graduation receipt** — something driven live in a browser or measured in the
store, never a passing test alone (house rule: a test whose population is empty proves the shape
of nothing). Sizes are honest guesses for one engineer.

### CA-0 — Stop the lying (≈ 1–2 days, first, no dependencies)

The small, local bugs that are silently falsifying every report's provenance and every
zero-row report's confidence. One PR, one test each, the two specimens as golden fixtures.

- Declare `_orchestration_plan`, `_baseline_rel_change`, `_cross_section_summary` on
  `AgentState`; test asserts the plan reaches synthesis (`plan_reconciliation.planned ≠ []`).
- Confidence floor keys on `row_count > 0` (reuse `_has_usable_data`), excludes the synthetic
  intake finding; zero rows ⇒ LOW, waterfall/recommendations emptied.
- **The leak**: violations become a one-line reader *disclosure* per `#n` ("one figure in the
  summary is derived, not quoted") — the repair instruction never ships; PDF renders the
  disclosure; metric `report_check_violations_shipped` keeps counting.
- `observation_label` rewritten on temporal runs after the clamp (no more "February 2025").
- **Comparison == observation ⇒ STOP the period-over-period phases**: the report *describes the
  period* and says plainly "no prior period exists"; never a decomposition of a window against
  itself. `_flag_sparse_comparison` / premise check stop bailing on equality.
- #36: derivation credit ported from `explorer/verify.py:469-489` (Δ, %, ratio within 1%); the
  message lists *figures*, not sentences. #15: sentence splitter treats the headline as its own
  sentence; negation window covers the clause; `increase`/`decrease` allowed under
  `descriptive`; the causal check keys on a *named relationship* (X verb Y with both sides
  present), not a verb alone. Tests for `increase` under descriptive.
- Partial terminal period: baseline finding carries `n_days` per period and labels/normalizes a
  partial last period ("Aug, 18 days · per-day 1,828").
- Deep branch of `useChat.ts:147` sends `session_id`.
- Restore the missing `tests/unit/test_pitfalls_contract.py` the checks module claims exists.

**Receipt:** re-ask both specimen questions live. Run 1 must say "no prior period — describing
Jun–Aug" with no obs/comp decomposition and no guard text in the Confidence section; run 2 must
either carry `traffic` as the metric or return rows or ship LOW with "0 rows". Shadow re-run of
the 144 stored questions (read-only; throwaway `AUGHOR_SYSTEM_DB`): `orchestration_plan null` =
0, `guard text leaked` = 0, `zero rows + HIGH` = 0.

**STATUS 2026-08-19 — MERGED to main as [PR #359](https://github.com/sidhasadhak/aughor/pull/359) (`c3ba392`).** Receipt run in isolation (every store redirected to scratch,
only the `traffic` upload copied, same gemini flash-lite model the specimens ran on, serial
phases at 15 RPM) through the real `/investigate` route:
- Run 1 (`b817b074`): `orchestration_plan` present, `planned = [intake, baseline,
  decomposition, dimensional, synthesis]`; the intake re-anchored to "last 1 month vs prior 1
  month" so a REAL comparison existed — decomposition found macOS +5,189 (+100%), Desktop
  +70% (the door Genie found); the monthly baseline carries `PARTIAL FINAL PERIOD: August 2026
  holds 18 of 31 days … per day 1,828 vs 1,223` and the narrator did not call August a
  correction; confidence MEDIUM, justification clean (no guard text). The no-prior-period STOP
  was not exercised live (the re-anchor found a prior window) — it is pinned by unit tests on the
  specimen's exact intake. Still no BROWSER_VERSION/ISP/day slice: CA-3.
- Run 2 (`a0b2f04c`): metric stays `traffic` (history reached the intake), filed under the same
  `session_id`; `CHANNEL_LVL_0 = 'Direkteingabe'` still returns 0 rows and the report ships
  **LOW / "No traffic data available"** — no fabrication. The wrong-column conjunction recurs
  exactly as CA-2 predicts (its probe is CA-2 work).
- Surfaced for CA-2: a z-score computed over a 2-month baseline reads "z = 3.8 — significant"
  — a minimum-periods rule for the significance verdict belongs with the evidence guards.
- Not done: the 144-question shadow re-run (≈1,000 model calls on a 15-RPM free tier; run it
  nightly or on a paid tier). Pre-existing unrelated failures noted: `test_job_leases_shared_db`
  (fails on main), `test_eval_ratchet::test_ratchet_live_smoke` (needs a live key), telemetry
  tests (`opentelemetry` extra absent in the worktree venv).

### CA-1 — The chat path crosses the seam (≈ 1 week; CI-1d's unfinished half)

- `PartsMessage` renders **all 37 parts** through the existing organs (they already take typed
  props; the adapter does the REPLACE-accumulation the reducer did). A part-coverage test: every
  `AughorUIDataTypes` key has a renderer or an explicit fallback.
- `/chat` (full page) moves to `useAughorChat` first; the workspace panel follows. Thread
  selection = `setMessages` from a history endpoint that returns `UIMessage[]` — `restore()` and
  `_ReconstructedTurn` (`db/history.py:563`) retire. Interrupt/stop semantics preserved
  (`stop()`); plan/clarify approvals remain side POSTs keyed by investigation id.
- Retire `investigationStream.ts` + `lib/useChat.ts` + `aguiTransport.ts` for chat;
  `BriefAskPanel` migrates or keeps the seam (decide from its frame usage); `/chat/parts` deleted.
- Then the cheap affordances the SDK gives: **edit-and-resend, regenerate, stop, branch**,
  message actions (copy · "open in workbench" · thumbs → the feedback hook Langfuse LF-2 wants),
  suggested follow-ups as chips, stick-to-bottom scrolling, a greeting/empty state. Shapes
  referenced from vercel/chatbot's `message-actions`, `message-editor`, `suggested-actions`,
  `sidebar-history`, `data-stream-provider`; components ours.

**Receipt:** one live conversation driven in the browser through `/chat` with zero reducer
involvement (the reducer file is gone); transcript parity vs the old path on the same session id;
five frontend gates green; `lint:elements` still 69/69.

**STATUS 2026-08-20 — BUILT on `claude/ca-1-continuation-t0ax40`.** What shipped vs the sketch:
- **The reducer stack is gone**: `investigationStream.ts` (846), `lib/useChat.ts`,
  `useInvestigationThread.ts` and `aguiTransport.ts` deleted; `/chat/parts` deleted; the
  vocabulary ratchet's `investigation_in_web` baseline fell 659 → 617 with them. The `ChatTurn`
  SHAPE survives in `lib/chatTurn.ts` — the organs speak it — but accumulation became a pure
  projection (`projectTurn`/`projectThread`) over an AI-SDK `UIMessage`'s parts: same fields,
  same semantics, derived instead of dispatched. Streamed form == persisted form == projected
  form. Every chat surface crossed together: ChatPanel (workspace + `/chat`), `BriefAskPanel`
  (migrated, not kept on the seam) and the briefing's `InlineInvestigationThread`.
- **"All 37 parts" became 41**: the adapter was silently dropping structure the reducer read —
  settled `narrative` (anomalies/trend/confidence), `answer`, the Wave-R4 `error` tail, `done`'s
  receipt id. Those now ride as declared data parts beside the text channels; text blocks carry a
  channel stamp (`providerMetadata.aughor.channel`, incl. a separate `report` channel for deep
  synthesis prose) so the projection reconstructs `headlineStream`/`narrativeStream`/`reportStream`
  faithfully. Gate frames (`plan_pending`/`clarify_pending`) close the message cleanly instead of
  reading as a dropped connection. Part coverage is a FAILING TEST, not a habit: every declared
  key must project or be named in `FALLBACK_PARTS` (`chatTurn.test.ts`; parity tests run frames
  through the real adapter AND the SDK's own `readUIMessageStream`).
- **The transport**: `/api/chat` is now THE proxy — the reducer's three doors preserved verbatim
  (`/investigate`, forced-quick `/chat`, unified `/ask`), per-turn options in the send body,
  P3/P4 approvals as `resume` bodies mapped onto the same feedback side-POST keyed by
  investigation id (the user's decision is a visible turn; the resumed run streams as its answer).
  Compact history is DERIVED from the SDK's own messages server-side (`historyFrom`) — one memory,
  no parallel client array. WP-2 drop-recovery moved into the route (bounded poll of
  `/investigations/{id}`, recovered report re-fed through the adapter).
- **Thread restore is `setMessages`**: new `GET /chat-sessions/{id}/messages` returns `UIMessage[]`
  in exactly the streamed shape (pytest pins the mapping incl. the interrupted-turn uncertainty
  sentence); ChatPanel's 40-field manual restore literal and `restore()` are gone. Deliberate
  deviation: `_ReconstructedTurn` STAYS — it is `resolve_history`'s prompt memory for
  session-addressed non-web callers (MCP, scheduled), not UI restore; `/turns` also stays for
  API compatibility. Affordances: edit-and-resend on the question bubble (SDK truncate-and-branch),
  Regenerate on the last turn, stop/interrupt preserved; chips/stick-to-bottom/greeting carried over.
- **Receipt run**: five gates green (`lint` byte-identical finding count to main, tokens/format/
  vars clean, `lint:elements` 69/69), `tsc` clean, 73 web tests + targeted backend battery
  (ratchet/contract 93 + area suites) green, production build green with `/chat/parts` gone.
  Live: this environment has no model key, so the browser run drove the REAL client seam
  (composer → `/api/chat` → adapter → SDK → projection → organs) against a frame-replay backend
  speaking the exact wire vocabulary — quick turn (route banner, streamed headline, figure,
  narrative, follow-ups), deep turn (guard receipt, phases, `answer_report` report), and
  reload-restore via `/messages` on the same session id, screenshots captured, no console errors.
  The with-a-model transcript-parity pass rides the next keyed environment (CA-3 needs one anyway).

### CA-2 — Guards move to the evidence layer (≈ 1 week; parallel with CA-1)

Verification in the Track-A sense — no model strength prevents these:

- **Window degeneracy** is a typed stop (CA-0 ships the stop; CA-2 ships the *type*:
  `IntakeVerdict.no_prior_period` consumed by the planner and the report).
- **Zero-row conjunction probe** before a phase runs: `check_filter_value_domains` gains a
  conjunction check (`SELECT 1 … WHERE <all predicates> LIMIT 1`); zero ⇒ relax to the
  value→column binding from the value index (the resolver in `semantic/answer_resolution.py:608`
  reaches the deep path) or stop with "no rows match Direkteingabe ∧ Chrome at LVL_0; did you
  mean LVL_1?".
- `_MEASURE_COL_RE` replaced by column-role inference (`change|delta|abs_change|obs_*|comp_*`
  are measures); identical-everywhere ⇒ does not earn its place.
- Contradiction detector keys on `is_significant` / `stat_note`, not adjectives.
- Claim checks bind **claims to evidence ids** (`[claim] → [finding_id,row]`), derivation credit,
  causal check by relationship shape — the scientific-agent-skills pattern.
- Confidence is computed from evidence facts (rows, windows, significance) and the model may
  only *lower* it.

**Receipt:** each defect in §1 has a unit test with the specimen as fixture; the shadow re-run
shows zero tautological findings (`obs == comp` on every row) across 144.

**STATUS 2026-08-19 — MERGED to main as [PR #360](https://github.com/sidhasadhak/aughor/pull/360) (`689b949`), built on `claude/ca2-guards-to-evidence`.** What shipped vs the sketch above: the "zero-row conjunction
probe" became something stronger — the filter guard finds the literal in a SIBLING column
(`column_suggestion`) and `execute_guarded` MOVES the predicate deterministically before any
model call (AST surgery + dry-run + guard re-probe); a literal in NO text column is a typed
`novel` verdict that rides as a caveat ("the segment is absent, not zero") and is never fed to
the model fix loop. Also: change-column-first `_measure_col_index` + `_is_self_comparison_finding`
(tautologies never reach the narrator) · contradiction detector keys on structured verdicts
(stats.py marker, `is_significant`; all-unflagged findings = "no claim"; negation stripped before
the positive scan) · `_MIN_BASELINE_PERIODS = 6` (a model z over a shorter baseline becomes a
description; fired live: "z = 2.47 … not a significance verdict") · `_evidence_confidence_ceiling`
(HIGH capped on no-prior-period / short baseline / trust caveat; the model may only lower).
**Receipt run:** the exact 7774b792 SQL against the real CSV through `execute_guarded` → repaired
to `CHANNEL_LVL_1`, 3 rows (Desktop 531 orders), zero model calls; the novel value stays an
honest absence. Trap fixed along the way: `repair_filter_literals` keyed fixes by the QUALIFIED
table name but resolves sqlglot's BARE name — value repairs on schema-qualified tables had
silently never matched (pre-existing). **Deferred to a later PR:** claim→evidence-id binding
(rewrites report_checks.py on top of CA-0's Violation type).

### CA-3 — Deep analysis becomes the analyst (≈ 2–3 weeks; needs CA-1 for rendering, CA-2 for the guards; CI-4 finished)

- **Phases become tools** with the Verifier inside each: `baseline(metric, grain, windows)`,
  `decompose(dimension, windows)`, `z_score`, `premise_check`, `cross_section(dimension)`,
  `run_sql`, `describe_table`, `value_lookup(entity)`, `profile_column`, plus the existing
  platform tools. The library of deterministic SQL *patterns* is preserved as tool bodies; the
  *sequence* stops being a script.
- **The analyst loop**: `run_tool_loop` with a deep step budget on `ModelProfile`
  (baseline/capable — e.g. 10/24 steps; a knob, not a constant), the converse states-not-scripts
  prompt extended with the analyst's stopping rule — *stop when a cause is named with its
  size, or when you can say what the data cannot tell and what to check next* — and the
  latitude to change grain, dimension, window after seeing a result. The evidence log is the
  loop's tool results; the narrator writes the report from it; CA-2's checks bind its claims.
- **The door**: `_converse_eligible` admits `deep`/`escalate`; `deep_analysis` becomes the
  analyst loop, not the phase script; `ask.converse` posture per §5.
- **Frames stream through the turn**: each tool call emits `converse_step`/`tool-*` parts and
  each finding a data part — rendered by CA-1's parts path (this *is* CI-6a's missing half). The
  user watches the analyst slice; the report is the summary of what they watched.
- **Follow-ups carry the spec**: a deep follow-up inherits the prior turn's metric, filters and
  windows unless the question changes them; `session_id` is on every branch; `is_followup` is
  not the only door (the model sees the prior spec as context and decides).
- Cost honesty: more steps per deep turn ⇒ more requests; the evidence budget and row caps
  remain on `ModelProfile`; measure with `?timings=1` and the route receipt; BYOK (CI-5b)
  already makes this the customer's model choice.

**Receipt (live, the Direkteingabe question on the real upload):** the loop reaches a concrete
segment at a finer grain than month within budget (BROWSER_VERSION/ISP/day or equivalent) and
the report either names the Chrome-105 bot population with its size or states what it could not
test; the follow-up "only focus on Chrome" keeps `traffic` and returns rows. Plus: the 20 real
transcripts CI-0 reads, re-read — the "mechanical" moments named in CI-0 gone or replaced.

**STATUS 2026-08-20 — BUILT on `claude/ca-1-continuation-t0ax40` (with CA-1).** What shipped vs
the sketch:
- **Phases became tools** (`aughor/agent/analyst.py`): `baseline`/`decompose`/`cross_section`
  wrap the existing phase nodes verbatim over a synthetic agent state — every CA-0/CA-2 guard
  runs by construction, and the Verifier's annotations land inside each tool's evidence.
  `z_score` (guarded execute + `analyze_query_result`, refuses under `MIN_BASELINE_PERIODS`),
  `premise_check` (three scalar-subquery probe; verdicts `premise_holds` / `window_corrected` —
  re-anchors the spec — / `premise_contradicted` / `no_prior_period` / `not_assessable`),
  `value_lookup` (bounded LIMIT probes, honest absence), `profile_column`, plus `run_sql` /
  `describe_table` and the platform roster. Grain/window/metric latitude is per-call spec
  overrides applied to a COPY of the intake.
- **The analyst loop**: `run_analyst` = intake once → `run_tool_loop` under `deep_loop_steps`
  (new `ModelProfile` knob: 10 baseline / 24 capable, env `AUGHOR_DEEP_LOOP_STEPS`) with the
  stopping rule in the system prompt; the loop's own conclusion rides `_analyst_conclusion`
  into `ada_synthesize` (section absent ⇒ byte-identical phase-script runs), the narrator's
  `answer_report` closes the turn. Complete runs persist with the report; a prose-only
  conclusion persists a minimal investigate report rather than lying about phases.
- **The door**: `_analyst_eligible` = `ask.converse` ∧ deep/escalate ∧ not dossier-forced ∧ not
  explore; the phase script REMAINS the flag-off fallback (§5 posture: flag off in deployments,
  local dev ON). The converse roster's `deep_analysis` now runs the analyst inline (with the
  custom-agent refusal pre-check); the route receipt claims `body: "analyst"`.
- **Frames stream through the turn**: `_stream_analyst` on the same converse bridge —
  `converse_step` per tool choice, `phase_complete` per new slice, `guard_receipt` /
  `phase_progress` / `report_delta` relayed from inside phase bodies via a progress-sink shim,
  then `tables_used` + `answer_report` + `done {body, stop_reason, steps}`. CA-1's parts path
  renders all of it with zero web changes this wave (a new tool shows its raw id in the trail
  by design — the roster map learns nice names later).
- **Follow-ups carry the spec**: `_followup_origin` — the hard "FOLLOW-UP — compose…" directive
  when the heuristic fires, a soft "PRIOR TURN (context, not a mandate)" otherwise — attached
  on every deep turn with history, phase script included, so `is_followup` is not the only door.
- **Receipt run**: ruff clean; targeted pytest green (20 unit tests over tools/loop/door, 2
  integration tests over the full `/ask` seam, the ratchet/contract battery — with one
  exception that predates this wave: `test_ratchet_live_smoke` fails identically on the clean
  tree in this keyless environment, its live pipeline metering 0 tokens). Ratchets: the
  'ada' vocabulary baseline FELL 628 → 602 (prose de-jargoned in the touched files); swallow
  and private-import counts held via `tolerate(...)` and new public aliases. Live: this
  environment has no model key, so the browser receipt drove the REAL path end to end
  (composer → `/ask` auto-depth → deterministic deep route → `_stream_analyst` → intake → loop
  → guard battery over the seeded outage-scenario DuckDB → synthesize → parts render) with the
  faux backend scripting only the model's choices: route banner `body: analyst`, tool trail
  (baseline, decompose), streamed phases with real charts and a Verifier stat note, report +
  bottom line — screenshots captured. The honesty seam showed up live: an earlier mis-pointed
  connection turned every query into a Catalog Error and the report guard REWROTE the scripted
  headline to "Data unavailable" — exactly the CA-0 contract.
- Deliberate deviations & deferred: dossier-forced and explore turns keep their own bodies (the
  door excludes them). Deep turns still do not restore into the thread on reload — parity with
  the phase script (the run files an `investigations` row under the session; restoring reports
  through `/messages` is follow-on work, not a CA-3 regression). The live-model receipt — the
  Direkteingabe specimen at finer-than-month grain, the "only focus on Chrome" follow-up, and
  the CI-0 transcript re-read — rides the next keyed environment, same as CA-1's parity pass.

### CA-4 — Charts: the exhibit spec (≈ 1 week; parallel with CA-3)

- **Emphasis form**, default whenever a subject exists: backend stamps `exhibit.emphasis =
  [entity]` from the intake filters; renderer paints the subject in the accent hue, the rest in
  one de-emphasis gray. (Most of the "terrific" is this one change.)
- **Palette by computation**: re-step the three failing tokens to pass the lightness band;
  delete the 12-hue overflow — past 7 series fold to "Other" or facet; one series = one hue; no
  value ramp on nominal categories (ramps for ordinal scales only); diverging from tokens; the
  six-check validator runs in CI for light and dark.
- **Mark specs**: bar width from the band (`barCategoryGap` ≈ 35%, cap ≈ 48px) and a max plot
  width for ≤ 4 categories; 2px surface gaps; 4px rounded data ends; 2px lines; solid hairline
  grid; **selective** labels (endpoint, extreme, subject) — all-on retired; axis titles with
  units; grain-formatted date ticks.
- **Title = claim, subtitle = scope · period · unit**; query name to the tooltip / view SQL. A
  `claim` field on the finding; one prompt line.
- **Form by job**, replacing the 24-option Literal + `chartTypeInference.ts`: magnitude → bar
  (one hue); trend → line at the grain that shows the event; identity ≤ 7 then Other;
  period-over-period → delta bar / dumbbell, never grouped obs/comp; one row → stat tile; > 7
  classes → table; never dual-axis.
- **One renderer**: PDF charts from the same ECharts spec via ECharts SSR (SVG) — matplotlib
  port deleted (§5 decision on where Node runs).

**Receipt:** the specimen's four charts re-rendered in `/chart-lab` and screenshotted; the
validator passes light + dark; a PDF and the web card of the same finding are visually the same
chart.

**STATUS 2026-08-20 — BUILT on `claude/ca-1-continuation-t0ax40` (with CA-1/CA-3).** What
shipped vs the sketch:
- **Palette by computation**: the six-check validator is vendored
  (`web/scripts/validate_palette.mjs`) behind a new `lint:palette` CI gate that also
  drift-checks the CSS tokens against the palette's new single TS source
  (`components/charts/echarts/palette.ts`). Light mode passes with ZERO hex changes — a pure
  re-order (the old order sat orange beside green: ΔE 0.7 under protanopia, indistinguishable;
  the new worst adjacent pair is 20.7) — with orange and cyan sub-3:1 under the documented
  relief rule (finding cards ship direct labels + a table view). Dark re-stepped five tokens
  into the lightness band (worst adjacent CVD 9.9); both modes share one hue order so a series
  keeps its hue family across theme flips. The 12-hue overflow ramp is DELETED: past six series
  the builders fold the tail into "Other" in a new `--chart-deemph` gray (below the chroma
  floor by design — it can never read as a seventh series). Small multiples paint every cell
  slot-1 (identity is the cell title, not a hue); the sign pair moved onto the status threshold
  tokens; the heatmap ramps come from the exhibit grammar; theme.ts's fallbacks import the TS
  source, killing the fallback-drift class outright.
- **Mark specs**: bar width from the band (`barCategoryGap` 35%, cap 48px) plus a max plot
  width for ≤4-category vertical bars; 4px rounded data ends (horizontal bars round the END,
  square at the baseline); 2px surface seams between stacked segments; ≥8px line markers with a
  2px surface ring; hairline grid; **selective labels** (≤8 marks label all, else endpoint +
  extremes + the subject — all-on retired); value axes carry titles with units. Grain date
  ticks were already in.
- **Emphasis form**: `exhibit.emphasis` stamped from the intake's `comparison_segment_sql`
  equality literals — only when the value actually appears in the finding's rows — and
  rendered on bars, multi-line, stacked and scatter: the subject in the accent hue, everything
  else in the de-emphasis gray, the subject always labeled. Deliberate deviation: the
  lifecycle `active_filter` is NOT read — it scopes the population, it is not the subject.
- **Title = claim**: a `claim` field on the finding (the pydantic field description IS the
  one prompt line), `subtitle` = scope · period · unit assembled deterministically from the
  intake. Web figures lead with the claim; the query's descriptive name stays on the
  source-data affordance; the PDF finding heading prefers the claim too.
- **Form by job**: the model's chart vocabulary is now seven JOBS plus annotated specialised
  shapes (`chart_vocab.py` `CHART_JOBS`/`JOB_TO_FORM`; both deep Literals rewritten; jobs
  resolve to engine forms at `_phase_result` and the quick seam; the web mirror
  `JOB_TO_ENGINE_HINT` is parity-tested against the Python map). `inferChartType` is the job
  ladder — one row → stat tile, composition never auto-infers a donut, and a period pair
  renders the NEW `delta-bar` (signed change, both period values in the tooltip) instead of
  grouped obs/comp bars. `scoreDualAxis` is deleted and dual axes are banned end to end:
  combo/pareto left the gallery and the registry, the backend's concentration→pareto
  auto-upgrade is removed, and two new parity tests pin the ban and the job mirror. Deviation:
  `chartTypeInference.ts` the FILE survives as the vocabulary home (union/maps/labels/
  gallery) — the sketch's target was the inference mechanism, which is replaced; deleting the
  file would only churn seven importers and the parity parser's anchor.
- **One renderer (§5-3 decided: (a))**: Chart.tsx's dispatch cascade is extracted into a pure
  `resolveOption.ts`; a small SSR entry bundles it with ECharts (esbuild, version-pinned) into
  the committed `aughor/export/chart_ssr.bundle.mjs`, drift-checked in CI. The Python export
  runs it as a node subprocess → SVG: the PDF embeds the VECTOR (svglib), PPTX rasterizes only
  where a renderPM backend exists and otherwise degrades to the data table. The 676-line
  matplotlib port is DELETED with its hand-mirrored constants family; matplotlib left the
  export extra (svglib joined). The org money symbol threads through (symbol→code shim), and
  print resolves the light tokens via an explicit mode override. The unification immediately
  caught two real parity gaps: exhibit mode `"sign"` existed only in the matplotlib port (now
  in `barOption`), and a malformed exhibit could throw in the browser (now sanitized fail-open
  at the shared seam, with `"none"` honoured everywhere).
- **Receipt run**: web gates green (tsc; tokens/format/vars/elements; the NEW `lint:palette`;
  73 vitest; production build); ruff clean; the targeted backend battery green with the W4
  print-renderer tests rewritten onto the SSR seam (they skip honestly where node/bundle are
  absent) — the only failure remains the pre-existing keyless `test_ratchet_live_smoke`.
  Live: `/chart-lab` re-rendered light + dark on the new palette including the new Delta and
  Emphasis cards (screenshots captured), and a PDF built end to end whose chart is the
  resolver's own vector output — claim heading, the subject emphasized with peers in the
  de-emphasis gray, axis titled with its unit, CHF threaded through (specimen attached to the
  session). Deferred: PPTX charts need a renderPM backend (rlPyCairo) in the deployment;
  choropleth/point-map fall to tables in print (no geo layer shipped); saved "combo" viz
  configs downgrade through inference (dual axes are banned); and the job vocabulary's
  live-prompt quality rides the next keyed environment, like CA-3's live-model receipt.

### CA-5 — Fluidity (ongoing after CA-1/CA-3; the "frontier-chat feel")

The vendored Elements organs (`ChainOfThought`, `Shimmer`, `Task`) on tool steps; tool-trail as
the conversation's visible reasoning; threads rail with rename/delete/search; suggested
follow-ups that are *actions* (drill, save, pin); attachments — a CSV dropped into chat becomes a
workspace upload (the path the specimen used); chat-first home per org (CI-6b's deferred
switch); the BYOK model chip; message edit/regenerate already free from CA-1. Guards unchanged.

**STATUS 2026-08-20 — BUILT on `claude/ca-5-fluidity`.** Half this wave had already landed as a
by-product of CA-1/CA-3 and was verified rather than rebuilt: the Elements organs are live
(`ChainOfThought` on the tool trail and the guard-receipt chain, `Task` on phases, `Shimmer` on
the streaming scaffold), the tool trail IS the conversation's visible reasoning as of CA-3, the
BYOK model chip sits in the `/chat` header, and edit/regenerate came free with CA-1. What this
wave actually built:
- **The rail stopped being read-only.** Rename (inline, Enter to save, empty restores the
  derived title), delete (confirm in place, then a REAL delete — turns, evidence claims and
  vector entries, via a new `purge_chat_session_artifacts`; a thread the user asked to be rid of
  that still steered future analysis from the RAG index would be CA-0's lie again), and a filter
  that appears only past six threads. New store table `chat_session_meta` (migration v5): the
  title override belongs to the SESSION, and a session spans many rows, so writing it onto every
  turn would have had no owner. Both writes are tenant-scoped through the same predicate the
  reads use — session ids are random, which is not an authorization model.
- **Follow-ups gained actions.** A finished turn now offers "Run a deep analysis" and "Pin to
  dashboard" beside the question chips. The actions are DERIVED from the turn, not sent over the
  wire: the client already holds the whole projected turn (CA-1), so a backend frame restating
  what it affords would be a second copy of state that can disagree with the first. Pin goes
  through the Query Builder's guarded door — the server re-runs the SQL through the guard battery
  and refuses a card whose query errors or is blocked.
- **Attachments got the right door and an honest voice.** Every attachment used to go to
  `/documents/upload`, so a dropped CSV became prose the model could read *about* rather than a
  table it could query; and the call site caught upload failures and asked the question anyway
  ("Non-fatal"), so a question about a file that never arrived was answered from whatever else
  was in scope. Now the file's KIND picks the door (data → the connection's file ingest → a real
  table; everything else → the document store), drag-and-drop works on the whole conversation,
  and every outcome — including the backend's own refusal sentence — is rendered.
- **Chat-first home per org (§5-4).** A `chat_first_home` org setting (default OFF — an org that
  navigates by the workbench should not have its entry point moved by an upgrade), honoured only
  from a bare `/`: a deep link names its destination, and a redirect that overrode it would break
  every link the app has handed out.
- **Receipt run**: ruff clean, tsc clean, all five web gates green, 8 new backend tests (rename,
  clear, 404, delete-with-footprint, name-ghost, and a tenant-isolation case for each write) plus
  the ratchet/contract battery — with the one pre-existing keyless exception (`test_ratchet_live_
  smoke`). The vocabulary ratchet caught two new `investigat*` uses in web and both were fixed at
  the cause, not the baseline: one re-derived a wire literal the caller already knew, the other
  was a user-facing label that should have said "deep analysis". Live: rail filter → rename →
  reload (the rename PERSISTED, not just optimistic) → delete-with-confirm; the action row on a
  restored result-bearing turn, and a pin the guard battery accepted; and the CSV drop on both
  paths — `quarter_regions.csv → main.quarter_regions` on the upload connection, and
  "Connection is not a file connector" shown on screen for the read-only one.
- Deliberate deviations: "save" in the action row stays the existing `Save as skill` button (deep
  turns only, its own state machine) rather than being duplicated as a chip; the action row
  self-hides on deep turns, which have no single SQL to pin — an investigation is not one card.

---

## 4 · Sequencing

```
NOW
  CA-0  stop the lying                      (1–2 days · one PR · golden specimens)

PARALLEL
  CA-1  chat crosses the seam               (≈1 wk)   ─┐
  CA-2  guards to the evidence layer        (≈1 wk)   ─┤
                                                       ▼
  CA-3  deep analysis becomes the analyst   (≈2–3 wk · needs CA-1 rendering + CA-2 guards)
  CA-4  charts / exhibit spec               (≈1 wk · parallel with CA-3)

THEN
  CA-5  fluidity polish                     (ongoing)
```

**House rules that bind every PR:** one PR at a time, squash, never push without authorization
· ratchet battery on your own diff in a clean worktree · five frontend gates + `gen:api` on route
changes · `PYTHONPATH="$PWD"` in worktrees · one writer per `data/` (`AUGHOR_SYSTEM_DB` to a
throwaway for every script while the API is up) · prove each wave live · read the prose, not the
status codes · measure the premise in the environment that matters.

**Dependencies on other arcs:** SQL-editor tail (SE-3…SE-5a) and Arc OA are unaffected; OA·LF-2
(feedback attribution) gets its thumbs from CA-1. N8-3 remains strictly after CA-1 (tool wiring
changes shape there).

---

## 5 · Decisions needed from the user

1. **`ask.converse` posture in deployments** — default ON (the conversation is the front door,
   Analysis Mode included) or opt-in per org? Cost is request rate (more steps per deep turn),
   already the customer's under BYOK. *Recommendation: ON by default once CA-3's receipt passes;
   until then local only.*
2. **Deep step budget and tier** — what a deep turn may spend (e.g. 10 baseline / 24 capable
   steps) and whether deep requires the capable tier. *Recommendation: a `ModelProfile` knob,
   capable tier required for the analyst loop; free-tier ladder keeps the phase library as
   fallback with the CA-0/CA-2 guards.*
3. **Where the PDF chart is rendered** — ECharts SSR needs Node: (a) a Node subprocess in the
   Python export path, (b) the web app renders the PDF, or (c) keep matplotlib and accept drift.
   *Recommendation: (b) on Vercel, (a) self-hosted; never (c).*
   **DECIDED 2026-08-20 by the user: (a)** — the export path runs the committed
   `aughor/export/chart_ssr.bundle.mjs` (the web resolver + ECharts, esbuild-pinned,
   CI drift-checked) as a node subprocess; deployments need node on PATH (or
   `AUGHOR_NODE_BIN`), and a missing node degrades honestly to data tables.
4. **Chat-first home by default** — `/` lands on `/chat` per org once CA-1 lands? Deferred from
   CI-6b; now cheap.
5. **Retire `BriefAskPanel`'s reducer dependency in CA-1 or later** — migrate now (one more
   surface) or keep the seam for the briefing.

---

## 6 · Explicitly not in scope

No second application; no next-auth/Drizzle/redis (the conversation record, auth and tenant
boundary stay Python); no TypeScript brain; no artifact editors; no dual-axis charts; no n8n
(dropped 2026-08-14); no workflow canvas (parked); no NL2SQL harness rebuild (deterministic
guards > LLM machinery on SQL correctness — R4 stands for what it measured); no new flags
(every knob on `ModelProfile` or a typed intake verdict).

---

## 7 · Measurement

- CA-0/CA-2: the shadow re-run counters over the 144 stored questions (degenerate windows,
  guard leaks, zero-row HIGH, tautological findings) — all zero, and kept zero by tests.
- CA-1: reducer deleted; parity transcript; gates green.
- CA-3: the specimen receipt; CI-0's transcript reading repeated; `injected_chars` /
  `reinjection_ratio` and `?timings=1` for cost; route receipt share of deep turns that reached
  a finer grain than the question's.
- CA-4: validator in CI; `/chart-lab` screenshots; PDF/web parity.
- Overall: thumbs and follow-up adoption (`purpose:"followup"`), the same two signals the
  platform roadmap already uses.
