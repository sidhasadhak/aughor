# Wave CR — the Control Room · scoped 2026-07-29

The run-centric operating surface — disposition #2 of `MASTRA_STUDY_2026-07-29.md`, now with
a concrete design reference: the **Agent Control Room mockup handoff** (claude.ai/design,
Nocturne design system, 5 views), whose vocabulary its own provenance file traces to
mastra-ai/mastra's playground-ui types. "CR" is deliberately two letters: C (context graph)
and R (transport reliability) are both taken, and the composite reads as what it is.

The product statement: **one surface answers "what is running, what did it do, what did it
cost, what needs a human" — rendered from stores that already exist, saying plainly what it
cannot measure.**

## 0. The pre-check (verified in code, 2026-07-29)

The mockup simulates its data on a 340 ms tick, so it never faces an empty state or a
missing store. Measuring ours found **most of the surface is a rendering problem**:

- **The span tree already exists.** `session_events` carries `span_id`, `parent_span_id`,
  `duration_ms`, `kind`, `trace_id`, `investigation_id`, `agent_id` (H2), model, token
  counts, retries, `error_class`. `Ledger.session_events()` (`kernel/ledger.py:787`)
  already filters by trace/kind/session/investigation — **no HTTP route serves it**; the
  only reader today is the `/usage` rollup.
- **The precondition is one flag.** `obs.session_log` is default-OFF, so the substrate
  records nothing until enabled. It is metadata-only — prompt CONTENT capture is a
  *separate* flag with its own blast-radius warning that stays off — and a retention
  window exists (`AUGHOR_SESSION_LOG_KEEP_DAYS`). Store: `data/system.db`.
- **The fleet controls exist.** Pause = persona `enabled` (H1 refuses a disabled agent at
  dispatch — proven live) and charter governance `enabled`. Kill = kernel
  `cancel`/`cancel_scope`, already served by `POST /jobs/{id}/cancel`. Per-agent
  **concurrency does not exist** — kernel semaphores are per job *kind* (`_slot_for`).
- **Spend has two honest sources.** Charter spend rides job-row metering (works with the
  session log off); persona spend rides H2's `agent_id` axis (needs the log). The fleet
  table must not present the two as one measurement.
- **Needs-a-human has three real sources, no store missing:** kinetic inbox proposals
  (resolve-once accept/reject), interrupted deep runs (`interrupt_before` +
  `read_checkpoint_values` + the feedback/resume endpoint), and `approval_required`
  effect outcomes persisted on automation runs.
- **Two honest run-graphs exist.** An automation run persists conditions-evaluated →
  per-effect outcomes (status, retries, authored refusal messages) on every tick,
  including ticks that did nothing; the ADA deep run has a fixed, checkpointed topology
  with real suspend/resume. We deliberately have no user-authored DAG (the Effect law).

## 1. The items

| # | What | Composes |
|---|---|---|
| **CR0** | **Turn the lights on**: graduate `obs.session_log` to default-ON through a J9 receipt. Claim shape: answers byte-identical flag-on vs flag-off (writes are entry-side, fail-open side-effects); overhead measured (write latency on the answer path, rows/day at observed volume); retention verified against `AUGHOR_SESSION_LOG_KEEP_DAYS`. Content capture stays OFF and is out of scope. | flags, E6 graduation |
| **CR1** | **The trace waterfall**: a read-only route over `Ledger.session_events(trace_id=…)` + a span-tree component; drill-in from H3's per-agent run list and from the receipt. Span detail renders the real columns (model, tokens, retries, ok, error_class, row_count). The *feedback* tab wires to `verify/verdicts.record_verdict` — the closed loop, not a new one. Payload/content appears only when the capture flag is on, labelled as such. | session_events, H3, verify |
| **CR2** | **The activity stream**: a paged tail endpoint over `session_events` with kind/agent/connection/error filters, streaming via the existing SSE idiom. Our kind vocabulary (`llm_call`, `tool_call`, `user_request`, `final_response` + ledger lifecycle events), never Mastra's — a stream that pads its vocabulary with kinds nothing emits reads as coverage that doesn't exist. | session_events, ledger events |
| **CR3** | **The fleet overview**: KPI tiles (active jobs, runs/min, p95, error rate, tokens/hr — cost only with G3's `cost_is_complete` caveat surfaced) + ONE fleet table unifying charters and personas **with the kind labelled** (charter ≠ persona — the collision already dodged twice), per-row spark/err/tok, and controls wired to what exists: pause (persona PATCH / charter governance), kill (`POST /jobs/{id}/cancel`), open (H3 view). Calm/NOC density toggle; NOC adds the spend columns. | H2, H3, jobs, obs/usage |
| **CR4** | **Needs-a-human**: one derived list (J10 — a view, never a second queue store) over the three sources in §0, each row deep-linking to its native resolve surface (inbox accept/reject, plan-gate feedback, automation run). Shows waiting-time, computed from stored timestamps. | kinetic, LangGraph interrupts, automations |
| **CR5** | **Run graphs**: (a) the automation run strip — conditions → effects with per-effect status, retries and the authored refusal verbatim, straight from `automation_runs`; (b) the deep-run phase view — the fixed ADA topology with the live phase, interrupt point, and resume via the existing feedback endpoint. No generic DAG editor; the Effect law is a feature. | automations, agent/graph checkpoints |

## 2. Deferred — and why (recorded so they aren't re-litigated)

| Mockup element | Why not now | Comes back when |
|---|---|---|
| Scorer bars (answer-relevancy 0.91…) | Live sampled scorers don't exist; rendering them from anything we have is vibes wearing a chart. The honest panel today: golden pass-chip trend, guards-fired rates from receipts, verdict acceptance. | S3 live sampling ships |
| Per-agent temperature/topP/seed knobs | Contradicts the pinned-temperature platform fact (13% run-to-run nondeterminism measured) and the role-based transport. Render the REAL knobs read-only: role, pinned model, effort, budget — with the receipt for why. | Only inside E4 experiment cells |
| Per-agent tool toggles | Capability changes are governance actions (grants, clearances, declared kinetic actions), not UI switches. V1 renders capabilities read-only from actual bindings. | A governed grant-editing surface |
| Per-agent concurrency stepper | Kernel semaphores are per job kind; a per-agent cap is a new kernel mechanism. Expose the job-kind caps honestly instead. | A kernel PR with its own tests |
| production/staging/dev switcher | No environment concept exists; our axis is workspace/connection — reuse the existing picker. | n/a |
| Per-second pulse theater | Our runs are minutes-long investigations, not 179 runs/min of sub-second chat. Minute buckets; Calm is the default; NOC is for the day someone actually runs a fleet. | Measured demand |

## 3. Laws in force

- **J9** — CR0 flips through a `GraduationDecision`, or not at all.
- **J10/J12** — CR4 and every panel are *views*; a second queue or results store is the bug.
- **Charter ≠ persona** — one table is fine, one unlabelled column is not.
- **Honest empties** — every panel's empty state uses H3's `measured: false` +
  `enable_flag` pattern. A quiet workspace shows "not recorded — enable X", never zeros.
  The mockup never faced this; we always will.
- **Cost honesty** — a dollar figure renders only beside `cost_is_complete`; unpriced
  calls are counted, never zero.
- **Design** — adopt Nocturne's discipline (accent as line never flood, density as
  disclosure, tonal ramps), not its stylesheet: everything translates into our tokens and
  passes the four frontend gates (the CSS-var kind law holds).
- New routes ⇒ regenerate `web/lib/api.gen.ts`.

## 4. Pre-registered gates

- **CR0**: same question answered flag-on and flag-off produces byte-identical answer
  output; the only diff is rows in `data/system.db`; overhead and rows/day reported in
  the receipt.
- **CR1**: the waterfall renders a real deep run's spans — including an H1 scheduled
  agent run — with zero new writes; clicking feedback records a verdict readable back
  from `verify/verdicts`.
- **CR2**: the stream shows only kinds something actually emitted; filters compose; a
  quiet period renders as quiet, not as an error.
- **CR3**: pause from the table → the next H1 dispatch refuses with the authored message
  (the proven path); kill → the job row reads cancelled; charter and persona rows are
  visually distinguished; cost tiles carry the completeness caveat.
- **CR4**: every row resolves through its existing endpoint; the list's count equals the
  sum of its three sources at read time; resolving anywhere removes it everywhere (one
  store per source, no copies).
- **CR5**: an automation run that did nothing renders as "evaluated, did not fire, why";
  a suspended deep run resumes from the graph via the existing feedback endpoint.
- Live-path proof before "done" on every item (leverage-gate law).

## 5. Sequencing & effort

**CR0 first and standalone** (a graduation PR — the receipt is the work). Then **CR1 →
CR2** (one PR each: a read-only route + a component). **CR3** (1–2 PRs; the table and
tiles). **CR4** (1 PR). **CR5** (1–2 PRs). Total ≈ 6–8 PRs, every one shippable alone.

## 6. Receipts (filled as items land)

| Item | Receipt | Evidence |
|---|---|---|
| **CR0** | ✅ graduation receipt `45dcc137f55b` (2026-07-29), run `43bf2bc7182d` of `aughor/evals/session_log_receipt.py` — 7/7 stable, 0 flaky, 0 errors, bar 1.0, minted through the live `POST /evals/flags/obs.session_log/graduate`. | Byte-identity proven against the real door wrapper (frames compared byte-for-byte, on vs off); store failure fail-open proven; content capture proven independent and still OFF; retention proven to delete by age and cap; write cost measured p95 **0.078 ms** vs E1's 5 ms bar. Magnitude on the real store: 267 rows/active-day, row cap ~748 days out, 14-day age prune binding. Bonus: the suite caught the door wrapper closing crashed runs as `ok=True` (fixed in the same change) and the pre-check caught two `created_at`→`at` column bugs (usage caps could never trip; the served COST_SQL errored). |
| **CR1** | ✅ built + live-proven (2026-07-30) | The waterfall rendered a real crashed deep run (57 events) including `ada_cross_section` labelled "no result recorded — entry-side evidence of a hang or cancel" — the E1 claim on screen. Span detail showed model/tokens/temperature metadata with no prompt content. Feedback: a `reject` verdict recorded from the UI and READ BACK from `verify/verdicts` (`this run` chip), durable in `data/verdicts.db`. Live-proof fix: a deep run's trace IS its investigation id and its rows carry a NULL `investigation_id` column, so the route resolves the direct match (pinned by test). |
| **CR2** | ✅ built + live-proven (2026-07-30) | The stream tailed a deep run executing on another process in real time (SSE `live` chip); filter chips folded from the store's actual kinds with counts; `errors only` composed; quiet renders as quiet. Live-proof fix: EventSource auto-reconnect replays from its original `since_seq` — rows now dedupe by seq (found via duplicate-React-key console errors). |
| **CR3** | ✅ built + live-proven (2026-07-30) | Tiles: active jobs, runs/min, p95, error rate with orphaned restarts EXCLUDED and counted (453 on Scout alone), tokens/hr with metered coverage, the kernel's real concurrency (one global cap of 8, `exploration` exempt — the doc's "per-kind semaphores" claim was corrected by the pre-check). One table, kind-labelled: 6 charters with 24h sparklines + 2 personas with session-log spend. NOC added the spend columns with `unmetered` never rendered as 0. |
| **CR4** | ✅ built + live-proven (2026-07-30) | A REAL paused run (explore branch, `mode: "explore"` + `AUGHOR_PLAN_GATE=1`) appeared as "1 waiting on a human = 1 paused deep run" — count equals the sum of sources; waiting time from the `investigation.paused` ledger event with the basis labelled; `Open & resume` deep-links to the native surface. Gap fixed en route: no `paused_at` column exists — the ledger event is the honest source. |
| **CR5** | ✅ built + live-proven (2026-07-30) | (a) The engine's own heartbeat rendered "evaluated — did not fire" every tick with the cron reason, plus a `fired` run whose effect reported `dispatch_error: unknown Action Hub trigger: cr-proof-trigger` VERBATIM. (b) The paused run's phase view: `branch explore · checkpoint step 3`, the fixed topology chain with `plan_gate ⏸` marked amber, "No phases recorded yet" stated rather than invented. Note: `source_change` conditions refuse to evaluate while `automations.source_probes` is OFF — its receipt stands; the proof used a `schedule` condition. |

Relation to the program: CR is **Wave S's control-room slice** with the H substrate
underneath — H2/H3 built the attribution these views read, and H3's per-agent page becomes
CR1's drill-in origin. CR does not block H5/H6 and shares no files with them; it can run
as the next arc after H or interleave. The S1–S3 design pass consumes Nocturne's
discipline through our tokens; this doc's deferred table is the list S3 revisits.
