# Feature-flag strategy — 2026-07-31

**The question:** 91 registered flags is too many for a human to read, understand and decide on.
Is there a better way to offer these? Which should become default platform behaviour? Which should
be deleted? The bar: keep anything that improves **accuracy, speed, reliability, observability or
auditability**; nothing that delivers a dead-end receipt.

**The answer in one line:** the 91 flags conflate six different *kinds* of switch, only one of
which deserves a toggle. Sorting by kind dissolves most of the list: ~25 can graduate on receipts
that cost no LLM budget (decidable by construction), ~6 should be deleted, 12 belong in a measured
experiment queue, 4 collapse into one performance profile, and ~4 are legitimately manual forever.
The visible Settings surface drops from 91 toggles to ~22 decisions.

---

## 1. The landscape, measured (not read from docs)

- **91 flags**: 21 default-ON (`FLAG_DEFAULT`), 9 auto-eligible (self-gating deterministic
  triggers under the `capabilities.auto` master), **61 default-OFF**.
- **Every flag is wired.** All 91 have real call sites (8 appeared orphaned to a naive grep but
  resolve through import aliases — `_fe`, `EB.enabled`, `_loss_flag`). Zero consulted-but-
  unregistered names. `FLAG_META` covers all 91.
- **No dead-end receipts among the ON set.** Verified each emission has a live consumer:
  `learning` → TrustReceipt/MemoryPanel · `activations` → TrustReceipt · grounding context →
  ChatMessage/GroundedNumber/BriefingPanel · `insight_delta` → investigationStream/aguiTransport ·
  `phase_progress` → investigationStream · `task_history` → telemetry + evals SQL recovery ·
  `session_events` → control room + /usage attribution.
- **One dead-end FEATURE found** (§2) — the H4 hire-an-analyst flow, half-dead behind
  `specialist_packs`.
- **Growth rate:** ~1 new flag per day through July (61 of the 91 born in July). Without a policy
  this list hits 150 by September.
- **The UI today:** two sections — the 9 auto guards + master under "Capabilities", and the other
  **81 in one flat toggle list**. That is the "too much for a human" problem, quantified.
- **The disposition ratchet designed in `FLAG_GRADUATION_AUDIT_2026-07-22.md` was never built**
  (deferred "until every flag has a disposition"). This document supplies the dispositions, so the
  precondition is now met.

## 2. The load-bearing defect: `specialist_packs` dead-ends Wave H4

`agents.user_defined` graduated ON (#241). Wave H4 (#237) shipped hire-an-analyst-from-a-pack.
But on a fresh clone the feature is **half dead**:

- The hire path (`aughor/user_agents/templates.py::create_from_template`,
  `routers/agents.py` `_validate_agent_packs`) **never consults `specialist_packs`** — hiring
  works, the pack binds, validation passes.
- The steering path (`aughor/packs/intake.py:55` `injection_for_question`) returns `None` when
  `specialist_packs` is off — so the bound pack's metric recipes, anti-patterns and stance
  **never inject into a run**.

A hired expert whose expertise never fires, with no error anywhere. The flag's own description —
"Off by default while the subsystem lands" — is stale: the subsystem is 21 modules plus a merged
hire flow. **Disposition: graduate on the data-gated receipt** (the #241 playbook): with no packs
installed, no active pack, or no human-confirmed pinned deploy binding, `injection_for_question`
is `None` by construction — and steering already requires a human to propose → confirm → pin a
deployment, so default-ON adds zero un-consented behaviour. This is the highest-value single flip
in the registry.

**✅ EXECUTED 2026-07-31** — receipt `452a6fcebba4`, run `c84f1e75a50c` of
`aughor/evals/specialist_packs_receipt.py` (8/8 stable ×3 iterations, 0 errors, 0 flaky, bar
1.0, no baseline). Verified while building it: the gate is sound because `save_binding`'s ONLY
product caller is the deploy endpoint behind `govern.guard("pack.bind")` — a binding row IS a
recorded human act — and the repo's one shipped pack is `status: draft`, so a fresh clone holds
zero active packs and the flip's whole observable effect is `GET /packs` reporting
`enabled: true`.

**Second gap found while verifying (tracked separately, NOT a flag question):** steering reaches
the **explore path only** — `injection_for_question` has exactly one caller
(`aughor/agent/explore.py`). Deep-Analysis investigations and quick answers never consult it,
so a hired analyst's pack steers only exploration runs even with the flag on. The persona stance
still reaches all paths (copied into the agent's instructions at hire time); what is
explore-only is the live injection of metric recipes and diagnostics. Wiring it into
investigate/quick-ask is its own work item.

## 3. The six kinds a flag can be (and what each deserves)

| Kind | What it is | What it deserves |
|---|---|---|
| **Graduated** | Proven, default-ON | A deletion date, not a toggle forever |
| **Self-gating guard** | Deterministic trigger decides per run | `AUTO_ELIGIBLE` — the registry's best pattern; grow it |
| **Data-gated feature** | Every behaviour needs user-created data + an explicit request | Default-ON via the #241 receipt (no A/B needed) |
| **Invocation-gated surface** | A route that 404s off, does nothing unless called | Default-ON — calling it is the consent |
| **Cost/latency knob** | Parallelism, extra LLM calls | ONE performance profile, not N toggles |
| **Migration flag** | Old path vs new path | A completion date; then delete |

Plus two legitimate residues: **integration switches** (should self-gate on config presence, e.g.
MLflow on `AUGHOR_MLFLOW_TRACKING_URI` being set) and **deliberate opt-ins** (privacy/cost:
`obs.prompt_capture`, `ai_sql`) — the only category that should stay a manual toggle forever.

## 4. Dispositions — all 61 default-OFF flags

### A. Graduate now — decidable by construction, zero grid budget (9)

**✅ EXECUTED 2026-07-31** — all nine default-ON, one suite
(`aughor/evals/flag_batch_a_receipt.py`, run `d006bec663a0`, 12/12 stable ×3, 0 errors,
0 flaky), nine per-flag graduation receipts (ids in `FLAG_DEFAULT`). The flip simulation
surfaced exactly the predicted test-debt class: two tests reaching "off" by never setting
the flag (`test_flag_overrides` re-pointed to `ai_sql`; `test_starters` now forces `=0` —
the operator escape hatch), and one subtler find — the L4 equivalence suite's *legacy
oracle* inherited the kernel bridge once `ops.metered_monitors` defaulted on, reporting
zero alerts in full-suite runs where another test had captured a kernel loop; both its
flag sets now pin `ops.metered_monitors: False`, because that comparison is between the
two loops, not the bridge.

Each is deterministic and its off-state equivalence is provable hermetically (the L4/N3/CR0
receipt kinds). Direct hits on the stated axes:

| Flag | Axis | Why it is safe |
|---|---|---|
| `preflight.parallel` | speed | 4 independent non-LLM lookups; byte-identical result |
| `ada.evidence_dedup` | cost/speed | lossless by construction; no-op < 24k chars |
| `schema.two_tier_catalog` | accuracy + cost | safe-direction-only; error-path autoload fixes binder errors that are otherwise structurally unfixable |
| `explore.wandering_detector` | cost/speed | fail-open brake; reuses results verbatim, ends waves gracefully |
| `monitors.guarded` | accuracy | caveat-and-deliver; never rewrites monitor SQL |
| `consistency.divergence` | auditability | deterministic, read-only over stored receipts; routes 404 off |
| `ops.metered_monitors` | observability | same work, now metered + heartbeat-supervised; the declared gate for `explorer.continuous` |
| `evals.experiments` | observability | inert unless a run enters it (contextvars default unset) |
| `starters.library` | UX/accuracy | deterministic templates, additive on /suggestions |

### B. Graduate on the data-gated receipt — the #241 playbook (11)

Every behaviour requires user-created data AND an explicit request; a fresh clone is
byte-identical except a route stops 404-ing. No A/B grid — the claim is structural.

`specialist_packs` (§2 — ✅ graduated 2026-07-31, receipt `452a6fcebba4`) · `govern.clearances`
(untagged ⇒ allowed) · `govern.usage_caps`
(no caps ⇒ allow) · `rbac.row_policy` (already double-gated on identity + org capability; no
policies ⇒ no-op; fails closed) · `kinetic.actions` (no declared actions ⇒ empty overlay) ·
`kinetic.overlay` (no edits ⇒ byte-identical) · `lifecycle.freeze` (nothing frozen until a user
freezes) · `automations.source_probes` (probes only tables a user-created automation watches —
creating one is the consent) · `automations.proposals` (no proposer on ⇒ nothing staged; routes
empty) · `ask.brief_context` (empty when no brief is cached) · `lifecycle.publish` — **with one
named precondition**: verify that pre-existing unversioned artifacts do NOT project to `draft`
(which would hide them from viewers — not byte-identical). If they do, ship the backfill first.

Also here in spirit: `freshness.resolved_rebuild` (off ⇒ caller's TTL decision unchanged; on it
changes only WHEN rebuilds happen, never what they produce) — graduate after measuring probe
overhead on real brief ticks; no LLM grid needed, just a cost number.

### C. Convert to self-gating; the toggle disappears (5)

- `ask.conversation_context` → `AUTO_ELIGIBLE`, trigger: "the turn is a follow-up"
  (`ask.resolve_first` is already auto).
- `obs.mlflow` → self-gate on `AUGHOR_MLFLOW_TRACKING_URI` being set; delete the flag. A
  default-ON with no server is a no-op; a set URI with the flag off is silent frustration.
- `agui.endpoint`, `federation.remote_join`, `federation.planner` → invocation-gated surfaces:
  the route 404s off and does nothing unless explicitly POSTed. Calling it is the consent
  (the planner's one LLM call is user-initiated). Graduate as always-available surfaces.

### D. The experiment queue — measure with E4, the plane built for exactly this (12)

Each adds LLM calls (or changes prompts/routing) for a claimed quality gain. `closed_loop`'s own
description — "until its delta is proven on your data" — names the exit criterion for the whole
group. Pre-check each with "does the flag change the prompt?" before buying any grid
(the check that saved ~850 requests on #241).

`closed_loop` · `graph.readback` · `explore.route_wide` · `explorer.synthesis_incremental` ·
`ada.why_where_interaction` · `ada.why_deepen` · `ada.causal_drill` (inert under parallel lenses —
delete it if the performance profile makes parallel the default) · `ada.evidence_stubs` (its own
description forbids graduation before an A/B) · `search.rrf` (cheap: the KB-retrieval evals are
the grid) · `explorer.manifest_driven` · `kinetic.agent_actions` · `semops.champion_validate`.

`snapshot_receipts` (born 2026-06-23, the oldest OFF flag) also lands here: measure the per-emit
version-probe cost, and reconcile with V4's data-version machinery (`lifecycle.freeze` composes
`db/snapshot.data_version` — two pinning mechanisms should become one).

### E. Collapse into ONE performance profile (4 → 1 control)

`explore.parallel_subq` · `ada.parallel_lenses` · `ada.parallel_phases` ·
`ada.parallel_why_lenses` — all trade concurrent LLM calls for wall-clock. With the free-tier
transport capped at 20 RPM, defaulting them on is actively wrong *today*, but that is a
deployment fact, not a per-flag fact. Offer **Conservative / Balanced / Fast** as one selector;
the profile sets the four flags. (`ada.parallel_why_lenses` is byte-identical output and joins
the default the moment the transport allows it.)

### F. Finish the migration, then DELETE the flag (5)

All stalled since ~2026-07-05 — a month of maintaining two code paths each:

- `semantic.contract_live` — its own description says "byte-identical output today". Flip, soak,
  delete. The clearest case in the registry.
- `semantic.resolve_live` (AL-05) · `capability.pipeline_live` (AL-02) — complete or abandon the
  migration; a migration flag with no completion date is a permanent fork.
- `plan.program` — a whole alternate executor path: adopt-or-kill decision, not a toggle.
- `trust.verify_facade` — already default-ON; the remaining work is deleting the legacy per-path
  guard subset and then the flag.

### G. Delete now (1)

- `ada.adversarial_verify` — superseded by `ada.adversarial_high_stakes` (auto-eligible,
  materiality-gated) per its own description. The full "challenge every verdict" tier has no
  constituency; the run-scoped `flag_overrides` plane can resurrect it for any one-off audit.

### H. Intentionally OFF — declare the reason, ratchet it (4)

- `ai_sql` — per-row LLM calls; its description already says "enable deliberately".
- `obs.prompt_capture` — captures the most sensitive content in the deployment; deliberate,
  bounded-window use only.
- `automations.adopt_legacy` — changes an outward-send path (brief delivery). Graduate
  deliberately after the engine soaks, then delete the legacy schedulers — the true win is one
  loop, not the flag.
- `explorer.continuous` — background spend; its own gate is `ops.metered_monitors` (group A).
  Revisit once metering is default.

### Bundles — many flags, one decision each

- **Knowledge Graph** (5 → 1): `graph.build` + `graph.freshness` + `graph.surface` +
  `graph.tour` + `graph.export` are one product feature (deterministic build, invocation-gated
  surfaces). `graph.readback` stays in D — it is the one that changes prompts.
  (`graph.consolidate` is already ON and a no-op without a graph.)
- **Connection birth** (4 → 1): `birth.job` + `ontology.autodoc` + `ontology.column_config` +
  `obs.popularity` are the R8/R11/R12/R14 chain — deterministic, build-time, observable.
  Graduate as one bundle after one soak.
- **Federation** (2 → 1): both routes invocation-gated (group C).

## 5. The structural fixes (what stops this recurring)

1. **Build the disposition ratchet** — the audit deferred it pending dispositions; they now
   exist. A test asserts every registered flag is in exactly one of `FLAG_DEFAULT` /
   `AUTO_ELIGIBLE` / `INTENTIONALLY_OFF{reason}` / `EXPERIMENT{measure-by}` /
   `MIGRATION{delete-by}`. A new flag that declares no exit fails CI. This converts "off" from an
   accident into a decision, permanently.
2. **A flag is a loan, not an asset.** Born with an exit plan; the five receipt kinds (sampled
   delta · L4 equivalence · N3 artifact · CR0 observationally-free · #241 data-gated) are the
   repayment schedule — and four of the five cost zero LLM budget.
3. **Graduated flags get a deletion date.** After a stable window with no observed operator
   force-off (the ledger records overrides), delete the flag and the dead branch. 21 default-ON
   toggles that nobody should touch are still 21 lines of UI noise.
4. **Restructure the Settings UI by kind**: Capabilities (auto, trigger-labelled — grows to ~12) ·
   Performance profile (one selector) · Integrations (self-gating on config) · Deliberate
   opt-ins (~4 — the only raw toggles left) · Experiments (the E4 queue, each showing its
   measure-by and a "run the grid" affordance). **~22 visible decisions instead of 91.**

## 6. Execution order (each batch = one reviewable PR, #199/#241 discipline)

1. **`specialist_packs`** — fixes the dead H4 feature (§2). Data-gated receipt.
   ✅ Done 2026-07-31 (receipt `452a6fcebba4`, this branch).
2. **Group A** (9 flags) — speed/accuracy/observability wins, all construction-decidable.
   ✅ Done 2026-07-31 (run `d006bec663a0`, nine receipts, this branch).
3. **Group B** (11 flags) — the data-gated batch; one receipt suite shape, applied 11 times.
4. **Groups C + G + graph/birth bundles** — self-gating conversions and the one deletion.
5. **Group F** — migrations: flip `semantic.contract_live` first (byte-identical today).
6. **The ratchet + UI restructure** — after dispositions are code, not prose.
7. **Group D** — the E4 queue, run as grid budget allows; each result either graduates the flag
   or moves it to INTENTIONALLY_OFF with the measured reason.

Discipline per flip (hard-won): simulate with `AUGHOR_<VAR>=1 pytest` BEFORE editing
`FLAG_DEFAULT` (off-state tests reach "off" several ways — `delenv`, never-setting — nothing to
grep); then force both states explicitly; snapshot `data/` before full runs; the graduation
ratchet already refuses on contradicting live overrides (this box is at zero overrides — clean).
