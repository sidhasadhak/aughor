# Deep-Analysis quality — audit, fixes shipped, and remaining backlog (2026-07-09)

**Method.** Ran four live Deep-Analysis (`/investigate`) runs on a fresh `beautycommerce_analytics`
connection (12 tables, 2023-01 → 2025-01), with ground truth computed by hand from the DB *before*
reading each report. Four question archetypes: a cross-sectional "why is X high?", a driver "what is
driving X?" (routes to explore mode), a temporal "why did X decline?", and a false-premise "why did X
spike?". Model: `qwen3-coder-next:cloud` via Ollama.

**Headline finding.** Report quality failures were **deterministic wiring/guard gaps between
subsystems that already compute the right signals**, not grounding-maturity or LLM-capability gaps —
the repeatedly-proven "deterministic guards > LLM machinery / suspect the wiring" pattern. Two of the
four runs contained a serious defect a strong model produced *despite* clean grounding scaffolding.

---

## 1 · What shipped (Tiers 1–4, branch `2026-07-09-ada-quality-tier1-tier2`)

All built → wired → unit-tested → live-verified on the real path. +84 tests; full unit suite green;
ruff, ratchets, web `tsc`, and the design-token gate all clean.

### Tier 1 — number correctness (the catastrophic class)
- **Global-ratio plausibility guard** (`_global_ratio_plausibility_guard`, `agent/investigate.py`).
  The worst failure: a "why is the Fragrance refund **rate** so high?" scan generated per-dimension SQL
  that inner-joined the denominator (revenue) *through* the numerator's event table (refunds), so every
  segment counted only refunded orders → a **73% refund rate** (true ≈ 10%), and the report told the
  user their premise was *inverted*. No fan-out/saturation guard caught it (values inside [0,100], no
  row multiplication). Fix: recompute the metric's true global level **independently** (each aggregate
  over its own full table); when every segment sits ≥ 2.5× above it — the systematic-inflation signature
  of a conditioned denominator — suppress the corrupted numbers and **state the true global**. Resolves
  bare (unqualified) metric columns to their tables via `information_schema` (a live run showed the LLM
  writes the formula qualified on some runs, bare on others).
- **Sustained level-shift detection** (`mean_shift_significance`, `tools/stats.py`). A real −6.4% YoY
  revenue decline was dismissed as "within normal variance" because the baseline used single-point
  anomaly detection (blind to a gradual multi-period shift) and divided the two-year mean gap by a
  single-month σ (wrong by √n). Added a **Welch two-sample test** on the series' halves; the reported
  significance is the stronger of point-anomaly and level-shift.

### Tier 2 — answer completeness
- **Decompose-under-abstention** (`route_after_baseline`). A "why did X change?" question with a
  material aggregate move (≥ 5% between series halves) now runs one dimensional decomposition instead of
  a Tier-0 "it's just noise" abstention that lists the dimensions it never queried. Live: the revenue
  run went from "within normal variance" to the exact drivers (Meta −$45,105/−22.4%, Direct −$27,102,
  volume-driven −110 orders ≈ 72% of the drop). A genuinely-flat false premise still stops cleanly.
- **Structural trust caveat** (`_reframe_on_trust_caveat`) + **scoping** (T3-1). A computation-error
  caveat now leads the executive summary with an honest reframe and floors confidence to LOW — **but
  only when a flagged finding's numbers are actually headlined** (checked via numeric grounding); a
  peripheral flagged finding is surfaced in `data_gaps` instead of nuking a grounded answer.

### Tier 3 — presentation & trust UX
- **Render-boundary number hygiene** (`round_long_decimals`, `tools/executor.py`) — no raw
  17-significant-digit float in prose ("0.20829576194770064"), both paths.
- **Inspectable exploration traces** — forward **every** sub-question's SQL/rows (was: last-only, a
  clobbered `operator.add` channel), a **per-step progress event** on the parallel-wave path (was: a
  multi-minute silent gap), and — because each step now carries its own result — a **chart per step**
  via the existing per-result renderer.

### Tier 4 — intent & data grounding
- **Data-coverage probe** (`_measure_date_span` run unconditionally; `_observation_window_is_wrong`).
  The report states the real coverage window it analyzed (populated even for a cross-sectional scan,
  which used to blank it); an out-of-span sample-inferred window is replaced. Live: `observation_period`
  went from empty to `2023-01-11 → 2025-01-09`.
- **Metric-definition receipt** (`_metric_definition_receipt`; new `AnswerReport.metric_definition`,
  rendered in `InvestigationReport.tsx`). Every report states how the metric was computed in plain
  language and whether a ratio is a value-weighted `SUM/SUM` or a count-based rate — the silent choice
  behind "refund rate" 18.8% (value) vs 20.2% (count). A live run caught a wording bug (a count ratio
  mislabeled "value-weighted") that was then fixed to read the actual aggregates.
- **Verdict↔recommendation coherence** (`detect_verdict_recommendation_incoherence`, folded into
  `contradiction_report`). A "X is not the problem / within normal variance" verdict shipping actionable
  recommendations is now flagged instead of reading severity "none".
- **Tiered adversarial verification** (opt-in `ada.adversarial_verify`, **default-off**). A ReFoRCE-style
  skeptic pass that fires *only* on a decision-changing verdict; a surviving refutation caps confidence
  and records the objection. Live (flag on): the false-premise run's abstention triggered a real
  objection about count-vs-value metric ambiguity. Kept opt-in to preserve "deterministic guards > LLM
  machinery" on the default path.

---

## 2 · Remaining backlog (prioritized)

Everything **demonstrated** in the audit is fixed. What follows is adjacent polish, the deeper grounding
direction deliberately scoped down during Tier 4, and one meta gap. Ranked by value.

### P1 — Canonical-metric pinning at ADA intake (highest-value; a real quality bug) — ✅ SHIPPED (2026-07-09, flag `ada.pin_canonical_metric`, default-off)
**Evidence.** In one live cross-sectional run the intake picked
`COUNT(DISTINCT refund_id) / COUNT(DISTINCT order_id) * 100` and the cross-section scan returned no
usable dimensional breakdown → the report degraded to *"the cause remains unidentified."* The
count-vs-value metric ambiguity that T4-1 now *discloses* actually *hurt the answer*.
**Fix (shipped).** `ada_intake` now pins the intake's `metric_sql` to the connection's GOVERNED
definition when one matches, so the scan decomposes on a stable, canonical formula every run.
`_pin_canonical_metric` (`agent/investigate.py`) resolves `resolve_canonical_metrics`
(`semantic/canonical.py`, the same three governed stores the chat path unifies) and pins **only** when
it is safe to do so — three fail-open guards: (1) a governed metric matches the intake label on its
**distinctive tokens** (reusing `_label_tokens`, which drops "rate"/"revenue"/etc, so "Fragrance
refund rate" → `{fragrance, refund}` and governed `refund_rate` → `{refund}` ⊆ it), (2) the governed
SQL is a **bare substitutable aggregate** (no SELECT/FROM/`;` — excludes a north-star full `value_sql`
that would break the `CASE WHEN … THEN {metric_sql}` templates), and (3) a **dry-run probe** confirms
it runs over the metric table (so a governed formula referencing an absent column can never replace a
working LLM one). Runs *after* the safety fallback so a governed formula supersedes a degenerate one;
updates `metric_is_ratio`; emits a transparency note into the intake spec + metric-definition receipt.
Flag-gated default-off (byte-identical default; measurable A/B), deterministic. **+14 tests**
(`tests/unit/test_canonical_metric_pin.py`, incl. two that drive `ada_intake` end-to-end). *Remaining:
live A/B on the beautycommerce fixture to measure the lift, then consider promoting to the default path.*
**Anchors.** `agent/investigate.py:_pin_canonical_metric` / `ada_intake` (pin call after the unsafe-metric
fallback); `semantic/canonical.py:resolve_canonical_metrics`; `explorer/metric_coherence.py:drifted_registered_metric`.

### P2 — Internal ADA progress events — ✅ SHIPPED (2026-07-09, flag `ada.progress_events`, default-off)
**Evidence.** T3-3 fixed the *explore* wave's silent gap, but the ADA cross-section and decompose phases
still run ~5 minutes silently between `phase_complete` events — the 8-dimension scan emits nothing
per-query. The user sees a long spinner.
**Correction to the original plan (found while building).** The cited template `_explore_subq_event` is a
**post-node drain**, not live streaming — `agent.stream(...)` runs `stream_mode="updates"` (one event per
node *completion*), and `_aiter_sync` blocks in a worker thread until a node returns. `ada_cross_section`
runs the *entire* scan as ONE node, so copying that template would emit everything at `phase_complete` and
NOT fill the gap. There was no mid-node → SSE channel in the codebase; filling the gap required adding one.
**Fix (shipped).** A best-effort in-process progress sink (`agent/progress.py`): `_parallel_execute_safe`
emits `emit_phase_progress(phase_id, done, total, current)` as **each per-dimension query completes**;
`routers/investigations.py` binds the sink `(loop, asyncio.Queue)` inside the copied `Context` each graph
node runs in (so it propagates through `ContextThreadPoolExecutor`'s per-submit context copy into the scan's
threads — `run_in_executor` alone does NOT propagate contextvars, hence `ctx.run`), and `_aiter_sync_with_progress`
races the graph `next()` against the queue, interleaving `{"__ada_progress__": …}` markers → a `phase_progress`
SSE event. Frontend (`web/lib/investigationStream.ts`) turns it into a live status line ("Scanning brand · 3/6…")
via the existing `STATUS_TEXT`/`statusText` (rendered `ChatMessage.tsx:1155`) — one `case`, no new turn state.
Flag-gated default-off = **byte-identical stream** (plain `_aiter_sync`, no sink, no extra tasks); graph events
are never dropped; a progress emit is pure telemetry (fail-safe on a full queue / dead loop). Wired on **both**
the main and HITL-resume stream paths. **+9 tests** (`tests/unit/test_ada_progress_events.py`). *Remaining:
live-verify the status line during a real multi-minute scan (needs a live endpoint); consider a coarser phase-plan
upfront (all phases pending→running→done) as a complementary structure cue.*

### P3 — Fraction↔percent unit consistency in prose — ✅ SHIPPED (2026-07-09)
**Evidence.** T3-2 killed 17-digit floats, but a report can still show "0.208" next to "20.8%" in the
same prose (a percentage written as a fraction in one place, scaled in another).
**Fix (shipped).** `unify_percent_fractions` (`tools/executor.py`), a sibling of `round_long_decimals`,
composed after it at the synth render boundary and **gated on `_metric_is_percent`** (so a plain-total /
average report is byte-identical). It is **self-grounded**: a bare fraction is rewritten to the percent
form only when its ×100 value ALSO appears in the same prose as an explicit percent, reusing that twin's
exact number string — so it fixes the "0.208 next to 20.8%" inconsistency precisely and can NEVER rescale
an unrelated sub-1 number (a correlation `0.82`, a p-value `0.05`, a `$0.50` price, a `0.36 pp` spread,
any `v ≥ 1`). Deterministic, idempotent. **+10 tests** (`tests/unit/test_percent_prose_unify.py`).
Applied on the investigate synth path; the explore path stays on `round_long_decimals` (no single governed
percent metric there). **Anchors.** `tools/executor.py:unify_percent_fractions`; wired at the synth hygiene
block in `agent/investigate.py` (the `_hygiene` composition).

### P4 — Metric-ambiguity *resolution*, not just disclosure (the deeper SOMA loop) — **now also owns the deep-mode clarify UX**
**Evidence.** T4-1 surfaces the chosen reading; the false-premise adversarial run showed the count-vs-value
ambiguity is real and decision-relevant. **Additional (2026-07-09):** the deep-mode "CLARIFYING QUESTIONS"
banner is a **UX trap** — it is *informational-only* stream enrichment (`routers/investigations.py:2276`,
best-effort `narrator.complete`, no interrupt/`return`), yet the run continues guessing while the trace
freezes at "Designing investigative chain…" and the chips are non-interactive `<span>`s with **no click
handler and no resume path** (`web/components/ChatMessage.tsx:817`). So a slow decompose reads as a stuck
human-in-the-loop wait with no way to proceed. (P1's two example chips — "net sales / units / gross margin?"
— are exactly the count-vs-value metric ambiguity this item resolves.)
**Shipped (2026-07-09) — the two safe, self-contained halves; the interactive pause+resume deferred.**
- ✅ **Ledger crystallization (the "resolution that compounds").** When P1 pins a metric to its GOVERNED
  definition over a materially-different parsed reading, `_crystallize_metric_resolution` (`agent/investigate.py`)
  records it in the **Ambiguity Ledger** (`semantic/ambiguity_ledger.py`, **source=probe**, the two candidate
  readings + the resolved governed formula), so the definition **burns down per connection** and is read back
  as a plan-time prior on every path (chat + future ADA), not just this run. Execution-grounded (P1 dry-ran the
  governed formula); **override-wins** preserved (probe is the lowest authority → never clobbers a user clarify
  or a reviewer verdict — tested). Fail-safe (a ledger error never perturbs the pin). +5 tests.
- ✅ **De-trapped the deep-mode banner (the UX half).** `ClarifyingQuestionsBanner` (`web/components/ChatMessage.tsx`)
  read as a stuck human-in-the-loop prompt — "Clarifying questions" + clickable-looking pill chips — but the run
  never pauses on it (the graph arms no clarify interrupt; it's informational enrichment). Reframed honestly:
  "**Interpreting automatically**" + "the analysis is resolving these itself and continuing — no action needed"
  + a muted non-actionable list (no pill chips). Removes the "am I supposed to answer this?" trap.
- ⬜ **DEFERRED — the full interactive clarify (source=user).** Actually **pausing** on a material ambiguity
  (arm a clarify interrupt in `agent/graph.py` beside `plan_gate`/`ada_synthesize`, emit a paused event, make
  the chips clickable → `POST /investigations/{id}/feedback` → `_stream_resume` → `crystallize_user_choice`)
  is a large graph + streaming + frontend change (high blast radius on the shared deep-run path) — its own
  careful arc. The two shipped halves deliver the compounding + the honesty now; this adds the human loop.
  Also deferred: moving the best-effort clarify-generation LLM call off the critical path (a seconds-long freeze,
  now mitigated by the honest label + P2's live progress). Complements
  [`docs/AMBIGUITY_LEDGER_2026-07-06.md`] and [`docs/SPIDER2_B1_PROBE_REPAIR_2026-07-06.md`].

### P5 — T4-3 confidence-floor path + earning-its-keep
**Evidence.** The refuter fired live and recorded its objection, but the HIGH→MEDIUM cap only triggers
when a HIGH-confidence *decision-changing* verdict is refuted — that path wasn't hit live yet, and the
capability is opt-in default-off.
**Fix.** Add a targeted test/live case that exercises the cap; consider a deterministic materiality
trigger (per the roadmapped WHY-lens "confidence-triggered activation") so the refuter earns a place on
the default path for the genuinely high-stakes minority of runs, without imposing an LLM call on every
run.

### P6 — Ground-truth regression harness (highest-leverage *meta* move) — ✅ SHIPPED (2026-07-09)
**Evidence.** The guards are unit-tested, but end-to-end **answer quality** on these four archetype
questions was not gated — this audit was manual. Nothing prevented a future change from silently
regressing the answer while keeping the unit tests green.
**Fix (shipped).** `tests/integration/test_ada_ground_truth.py` — a **hermetic** harness (temp DuckDB
seeded with closed-form ground truth + the test-isolated registry, **no live LLM**), mirroring
`test_golden_reference.py`. The answer-quality gains being locked are all deterministic, so each is
driven directly against the fixture and asserted on ground truth (**11 tests, ~1.5s**):
- **A1 (global-ratio guard, Tier 1):** a conditioned-denominator refund rate — `_independent_global_ratio`
  recomputes the **true 10.0% global** (not the inflated ~73%), `_global_ratio_plausibility_guard` **fires**
  on inflated per-segment findings and **states the true global**, and is **silent on a plausible spread**
  (negative control).
- **A2 (Welch + decompose + drivers, Tier 1+2):** a sustained −15% decline is **significant** and directional
  (`mean_shift_significance`), `route_after_baseline` **decomposes under abstention** (material move + sub-threshold
  anomaly → `ada_decompose`), and the real decomposition SQL names the worst channel (**Meta −1800**).
- **A3 (abstention correctness):** a genuinely flat series is **not significant**, has **no anomalous period**,
  and a flat "did refunds spike?" premise **stops cleanly** at `ada_synthesize` (no false decomposition).
- **P1 (canonical pin):** the pin's **dry-run probe runs the governed formula against the real fixture** — a
  runnable single-table rate is pinned; a formula referencing a **missing column fails closed** (keeps the LLM form).

*Why deterministic-seam driving, not a full-graph replay:* synthesis text is LLM-authored (not
ground-truthable), but every gain in this arc is a deterministic guard/router/stat — so the harness
gates exactly those, which is what a regression would break. Adding a new archetype = seed rows + one
assertion. **Anchors.** `tests/integration/test_ada_ground_truth.py`; drives `_global_ratio_plausibility_guard`
/ `_independent_global_ratio` / `_parse_ratio_sources` / `route_after_baseline` / `_detect_anomalous_period`
(`agent/investigate.py`) and `mean_shift_significance` (`tools/stats.py`).

### P7 — Model budget (non-code, but the #1 real-quality lever)
**Evidence.** The local `qwen3-coder-next` produced the degenerate count-based metric (P1) and several
degraded runs; per the prior finding *"frontier-model budget = #1 dependency"* a frontier coder model
would likely pick the value-based reading and decompose cleanly. Several "quality" issues are the local
model, not the pipeline.
**Action.** An ops/config decision, not a code change — pin a stronger `coder` model for real
investigations (`data/llm_config.json` / `.env`), as WS3's live ratchet already does for evals.

---

## 3 · Cross-cutting notes for the next session
- The audit ran on **one fixture** (`beautycommerce`) with a **local, flaky** endpoint (Ollama cloud,
  intermittent 502s → ~9-min ADA runs). P6 (regression harness) + P7 (model) would make future audits
  cheaper and more representative.
- **Live-run hygiene reminder:** any `/investigate` run writes `data/glossary.yaml` (knowledge-sync is
  not registry-scoped — the open `task_213affac` non-hermeticity). Always `git checkout HEAD --
  data/glossary.yaml data/metrics.json` and confirm a clean tree before committing. Prefer synthetic
  unit tests over live runs for deterministic logic.
- The four SSE captures + full per-run scorecards for this audit live in the session scratchpad
  (`assessment_notes.md`).
