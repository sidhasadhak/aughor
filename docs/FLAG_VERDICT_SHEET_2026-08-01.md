# Flag verdict sheet — every flag becomes permanent or disappears

Date: 2026-08-01 · Status: **APPROVED** (user, 2026-08-01) — sheet agreed as written;
the six open calls resolved: adopt legacy automations + delete both legacy schedulers ·
continuous exploration ON with caps as the governor · closed_loop AND graph.readback
hardwired on · federation auto-hook grids first, then hardwires · parallelism becomes
transport-computed in the ModelProfile · all deep-WHY lenses hardwired on.
Policy (user, 2026-08-01): **KEEP = the feature is always on and the flag is deleted.
REMOVE = the feature's code is deleted entirely.** No flag may stay in an "off" or
"optional" state. Either way, all 89 flags are eventually deleted.

Sources: `aughor/kernel/flags.py` (registry + inline graduation receipts),
`docs/FLAG_STRATEGY_2026-07-31.md`, `docs/FLAG_QUEUE_HANDOFF_2026-08-01.md`.

**Bottom line: 82 features stay (their flags die), 7 features are deleted.
All 89 switches disappear.**

Safety context: the live environment runs zero overrides — every flag resolves to
its default — so hardwiring defaults changes nothing observable today.

---

## Group 1 — the 57 already on for everyone → 56 KEEP, 1 dissolves

Every entry here graduated with a written receipt (measured A/B, byte-identical
equivalence, or a data-gated construction proof). Hardwiring them changes nothing;
it deletes the unused "off" half. Verdict for all except one: **KEEP — hardwire,
delete flag + off-branch + off-state tests.**

| Flag | What it does (plain) | Verdict |
|---|---|---|
| ask.clarify | Asks one clarifying question when your question is genuinely ambiguous, instead of guessing | KEEP |
| trust.verify_live | Hard safety check: generated SQL can only read, never modify | KEEP |
| trust.verify_facade | The same read-only gate on the validate endpoint | KEEP |
| trust.e1_live | Warns on known SQL footguns (date-vs-timestamp cutoffs, text sorted as numbers); never rewrites | KEEP |
| capabilities.auto | Master switch that enables the self-triggering guards | **dissolves** — once those guards are permanent (Group 2), a master enable has nothing left to enable |
| capabilities.receipt | Records which guard fired on each answer, and why | KEEP — feeds the new Chain-of-Thought UI |
| learning.receipt | Shows what the system reused or learned this run | KEEP |
| ask.context_receipt | "Show me exactly what the model was grounded on" | KEEP |
| obs.task_table | What the agent did, as a queryable table | KEEP |
| obs.session_log | Every agent run reconstructible from a metadata log (never prompt content) | KEEP |
| deep_analysis.progress_events | Live progress during long runs instead of a silent spinner | KEEP |
| ask.stream_text | Streams answer text as it's written | KEEP |
| intake.loss_signals | "Where are we losing money" questions get pointed at refunds/discounts/capacity, and un-computable verdicts are banned | KEEP — fixed a real wrong answer |
| report.argument_style | Reports composed the way an analyst argues (one exhibit per claim) | KEEP |
| chart.exhibit_grammar | Charts encode meaning: severity colors, reference lines, one measure per exhibit | KEEP |
| lens.decision_grade | Quantifies "closing the gap ≈ N" and names the outlier entity | KEEP |
| llm.structured_salvage | Repairs almost-valid model output deterministically before spending another request | KEEP |
| llm.bounded_repair | One bounded "fix your own output" retry | KEEP |
| preflight.parallel | Four independent lookups run at once — identical result, less waiting | KEEP |
| deep_analysis.evidence_dedup | Never renders the same result table twice in the synthesis prompt (lossless) | KEEP |
| schema.two_tier_catalog | Repair prompts get a focused schema plus every table the error message names | KEEP |
| explore.wandering_detector | Gracefully ends an exploration that has stopped learning | KEEP |
| monitors.guarded | A monitor's SQL is checked for grain bugs; findings ride as caveats on the alert | KEEP |
| consistency.divergence | Surfaces questions the platform answered two different ways, for a human to settle | KEEP |
| ops.metered_monitors | Background monitors and briefings metered and budget-supervised like answers | KEEP |
| evals.experiments | The measurement plane: same cases, several configs, one process | KEEP — it's the instrument the remaining verdicts are measured with |
| starters.library | Named one-click starter questions | KEEP |
| govern.clearances | Tags can gate who reads what; a refusal names the tag that blocked it | KEEP |
| govern.usage_caps | Org and per-user spending caps, checked before work starts | KEEP — becomes THE spend governor once kill-switch flags die |
| rbac.row_policy | Per-role row filters compiled into the SQL itself; fails closed | KEEP |
| kinetic.actions | Human-declared actions visible in the ontology, run through the governed executor | KEEP |
| kinetic.overlay | Human corrections merged onto query results at read time | KEEP |
| lifecycle.publish | Save ≠ publish: versions, changelog, revert for user artifacts | KEEP |
| lifecycle.freeze | Pin an artifact to the exact data version — honestly (refuses a pin it can't honour) | KEEP |
| automations.engine | The one condition→effect automation engine with full history | KEEP |
| automations.source_probes | Automations fire on actual data arrival, not staleness guesses | KEEP |
| automations.proposals | Durable accept/reject inbox for agent-proposed actions; standing grants | KEEP |
| ask.brief_context | "Why is that?" asked from a briefing knows which briefing you're looking at | KEEP |
| freshness.resolved_rebuild | Rebuild cached artifacts when inputs/logic changed, not on a timer | KEEP |
| agui.endpoint | The standard-protocol (AG-UI) endpoint | KEEP — Track C consumes it |
| federation.remote_join | Explicit cross-source join endpoint (calling it is consent) | KEEP |
| semantic.contract_live | One unified metric contract type | KEEP **+ delete the legacy CanonicalMetric path** (its stated obligation) |
| semantic.resolve_live | Semantic context resolved once per run, read consistently | KEEP **+ delete the legacy per-node consult path** |
| capability.pipeline_live | The unified generate→validate→execute→interpret route | KEEP |
| graph.build | Project what the platform knows into a committed knowledge graph | KEEP |
| graph.freshness | Keep that graph fresh at cost proportional to the change | KEEP |
| graph.surface | The knowledge-graph UI (three zoom levels, no hairball) | KEEP |
| graph.tour | A guided tour of a connection, ordered by topology | KEEP |
| graph.export | Export the graph as a self-contained offline pack | KEEP |
| graph.consolidate | Spend the graph's finding budget on distinct live knowledge, not the newest 100 receipts | KEEP |
| birth.job | "Understand this data" runs as one observable job when a connection is born | KEEP |
| ontology.autodoc | The ontology compiled into readable docs | KEEP |
| ontology.column_config | Per-column visible/sample/index control, human edits win | KEEP — Track A2 builds on it |
| obs.popularity | Real query history as a shared "what matters" signal | KEEP |
| agents.user_defined | Your own custom agents (instructions + documents + connection) | KEEP |
| specialist_packs | Authored domain packs steer the planner once a human deploys them | KEEP |
| snapshot_receipts | Findings pinned to the exact data version they ran against | KEEP |

## Group 2 — the 10 self-triggering guards → all KEEP; the wrapper dies

Each fires only when its deterministic trigger fires (that's what "auto" meant).
The trigger logic **stays as plain product behavior**; the flag and the whole
auto-elevation machinery are deleted.

| Flag | Trigger that stays (plain) | Verdict |
|---|---|---|
| deep_analysis.premise_check | "Why is X so high?" first checks whether X is actually high | KEEP |
| deep_analysis.clarify_gate | Two materially different readings of a metric → pause and ask which you meant | KEEP |
| deep_analysis.adversarial_high_stakes | A high-confidence, decision-changing verdict gets one skeptic challenge | KEEP |
| join.key_reconciliation | Mismatched join keys get format-normalization attempts, with the exact fix surfaced | KEEP |
| capability.contract | A query failing on a warehouse gets told the exact unsupported construct | KEEP |
| semops.guarded_extract | A failed typed extraction re-extracts with targeted feedback | KEEP |
| ask.resolve_first | Named entities and time grains resolved against real data before SQL is written; honest abstention when absent | KEEP |
| deep_analysis.pin_canonical_metric | A governed metric match pins the official formula over an LLM guess | KEEP |
| ask.overview | "Tell me about this data" gets the deterministic first-look tour | KEEP |
| ask.conversation_context | Follow-ups inherit the previous turn's grounding | KEEP |

## Group 3 — the 5 deliberately off → 2 turn ON, 3 REMOVE

| Flag | What it does (plain) | Verdict | Why |
|---|---|---|---|
| automations.adopt_legacy | Runs monitors and briefings through the one automation engine instead of two private schedulers | **KEEP — turn ON, then delete the two legacy schedulers** | Byte-for-byte equivalence already proven (9/9, alerts identical, no double-fire). The registry itself says the win is "one loop, not a flag". Completing this deletes more code than it adds. |
| explorer.continuous | The explorer re-runs when the schema changes or knowledge goes stale | **KEEP — turn ON** | Its own declared precondition (background work metered) is now on, and spend is bounded by usage caps + the per-run exploration budget. The governor is caps, not a flag. This makes "never stops learning" true. |
| ai_sql | LLM calls inside SQL itself (prompt() per row) | **REMOVE** | Off since birth, a per-row cost trap, and the guarded semantic operators cover the same need safely. |
| search.rrf | An alternative search-ranking formula | **REMOVE** | Measured **worse** than the current ranking on our real knowledge base (MRR 0.964 vs 0.977). A measured loser doesn't get to live in the codebase. |
| obs.prompt_capture | Stores full prompt/response content in the session log | **REMOVE the standing switch — reshape as an explicit, self-expiring "record the next N runs" debug action** | The capability is genuinely needed (it's how a bug becomes a reproducible case), but as a standing state it's a privacy landmine. An act with an expiry, not a state. |

## Group 4 — the 13 experiments → 10 KEEP, 3 REMOVE

Policy applied: an experiment either gets its question answered now or the feature
doesn't survive. Where cost is bounded and the behavior is exactly the
"more intelligence, well-directed" direction, the answer is yes without a grid.

**KEEP (hardwire on):**

| Flag | What it does (plain) | Why keep |
|---|---|---|
| deep_analysis.why_deepen | After finding the leading cause, two more queries: is it abnormal vs peers, and where does it concentrate | This is the depth a deep run is FOR. Two bounded queries per qualifying run. |
| deep_analysis.why_where_interaction | One query linking the cause to the place it concentrates | Turns two findings into one actionable link. One bounded query. |
| deep_analysis.causal_drill | Same idea on the serial path (matters when the transport forces serial) | Keeps serial-path depth at parity. Inert when parallel runs. |
| closed_loop | Corrections humans gave the system are read back into planning | A user who corrects the system and watches it repeat the mistake is the worst product experience we can ship. Prompt-only cost, no extra model calls. |
| graph.readback | The knowledge graph the platform builds is consulted before planning | Same principle: we finally USE what we know. Prompt-only cost. Post-validate with its already-budgeted grid. |
| explorer.manifest_driven | Baseline exploration coverage synthesized deterministically; the model spends its budget on curiosity | Fewer model calls, reproducible coverage, guards unchanged. |
| explore.route_wide | Genuinely broad "landscape" questions get the multi-cut treatment | Deterministic detector, yields to "why" questions. Sanity-check with the cheap grid, then hardwire. |
| kinetic.agent_actions | The agent may PROPOSE declared actions (never run them) | Data-gated (needs declared actions to exist), human accepts every one. |
| semops.champion_validate | The strong model spot-checks the cheap model's filter verdicts | Self-gating, one sample call per filter op. Self-checking is direction. |
| federation.planner | Cross-source questions answered across two connections | The endpoint is consent-by-invocation — keep. **Condition:** the auto-detect hook on fresh /ask turns is the one unmeasured routing change; run its already-budgeted grid before hardwiring that hook. |

**REMOVE (delete the feature):**

| Flag | What it does (plain) | Why remove |
|---|---|---|
| plan.program | A second, parallel way to answer a question (typed program executor) | One brain, one answer path — our own benchmarking showed the lean path + guards wins, and a standing "adopt-or-kill" question is exactly what the new policy forbids. Kill. |
| deep_analysis.evidence_stubs | Shows the model FEWER rows of evidence to save tokens | The exact opposite of the new direction (we're raising the evidence budget). Its own description forbade graduating it without proof it doesn't hurt quality. |
| explorer.synthesis_incremental | Mid-run synthesis for a more "alive" feel, at extra model cost | The new chat UI provides the liveliness for free; end-of-run synthesis already always runs. |

## Group 5 — the 4 parallelism knobs → code stays, flags die, decision computed

`explore.parallel_subq`, `deep_analysis.parallel_lenses`,
`deep_analysis.parallel_phases`, `deep_analysis.parallel_why_lenses`

Hardwiring ON breaks today's rate-capped free transport (20 requests/min);
hardwiring OFF throws away real wall-clock wins on capable transports. Neither is
honest. The always-on behavior is: **run as parallel as the bound transport's
measured rate budget allows** — computed from the ModelProfile (Track A1), the
same place the other capability knobs move to. Four flags deleted, one
deterministic decision, no user-facing switch.

---

## Execution plan

Per-flag safety step before deleting any off-path: run the targeted suite with the
flag forced OFF and then ON (off-state tests reach "off" several different ways —
nothing greppable), then delete flag + dead branch + off-state tests together.
Every deleted flag gets a tombstone comment (the registry's existing convention).

- **Wave 1 — removals** ✅ **DONE 2026-08-01** (ai_sql, search.rrf, evidence_stubs,
  synthesis_incremental, plan.program; prompt_capture reshaped to a bounded,
  self-expiring capture window at `POST/GET/DELETE /obs/prompt-capture`, see
  `aughor/obs/prompt_window.py`). Registry 89 → 83 flags; ~3,000 lines net deleted.
  `capabilities.auto` dissolves in Wave 3 with the auto guards it enables.
- **Wave 2 — hardwire the 56 receipted default-ONs**, split by area (trust/obs,
  graph, govern/automations/lifecycle, ask/deep, semantic/capability). Includes the
  two legacy-path deletions (CanonicalMetric, per-node consult).
- **Wave 3 — unwrap the 10 auto guards** ✅ **DONE 2026-08-04** (commit `eae66a8`).
  Triggers are unconditional code; `capabilities.auto`, the elevation branch in
  `_env_resolved`, `_auto_mode_active`, `flag_state`'s `"auto"` arm and the Capabilities
  settings section are gone. `AUTO_ELIGIBLE` stays declared and EMPTY so the disposition
  ratchet keeps proving nothing rejoins the tier; `CAPABILITY_TRIGGER` is kept because the
  Activation Receipt still reports why a capability fired, which never depended on a flag.
  **Registry 40 → 29, zero undispositioned.** Two findings the sweep surfaced: four
  `ada.*` aliases in `RENAMED` were left pointing at deleted flags (an alias outliving its
  target raises `UnknownFlagError` for an operator whose `.env` still names it), and
  `test_caps_at_max_probes` had pinned `join.key_reconciliation` OFF to isolate its probe
  budget — so the budget it reported was fiction, and the real bound (8 → 48 worst case)
  is now asserted with the multiplier rather than suppressed.
- **Wave 4 — the two turn-ONs** (adopt_legacy + delete legacy schedulers;
  explorer.continuous).
- **Wave 5 — experiment keeps**: hardwire the nine; federation auto-hook after its
  grid; route_wide after its sanity grid.
- **Wave 6 — parallelism** → transport-derived decision in ModelProfile; delete
  the four flags.
- **Wave 7 — scaffolding teardown**: `flags.py`, the flags Settings panel, the
  disposition ratchet test, the override-drift ratchet, `/system/flags` routes;
  regenerate `web/lib/api.gen.ts`.

One PR at a time, explicit sign-off before each push.
