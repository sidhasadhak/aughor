# Explorer Synthesis & Knowledge Frontier

**Status:** in progress — branch `2026-06-23-explorer-synthesis`
**Date:** 2026-06-23
**Author:** Scout intelligence arc

## The problem (observed)

Intel Scout re-asks the same questions and does not visibly *build on what it
knows*. Despite a large ecommerce business dictionary and a 10k-line playbook,
the activity log shows the same `[pinned]` questions re-running every exploration
(see the Security & Audit → Activity screenshot, 2026-06-23).

Root-cause diagnosis (code-grounded):

1. **Pinned questions re-execute identical SQL every run by design** — for
   reproducibility (`_phase8_pinned_questions`, `agent.py:1352`). The dedup only
   stops a duplicate *insight* from being *stored*; it does not stop the question
   from being *asked and run*. This is the visible repetition.
2. **Coverage is tracked at coarse "angle" granularity** (`DOMAIN_ANGLES`,
   `agent.py:1697`) — `volume/value/retention/...` — not at the level of specific
   `metric × dimension` cuts. Once the ~5 named angles are "covered," the loop
   asks for vague "deeper_analysis / anomalies" with no concrete frontier.
3. **The playbook is invisible to Scout** — zero references in
   `aughor/explorer/`. It is consumed only by the Analyst (ADA).
4. **No forward-chaining** — a finding never spawns a targeted follow-up. The
   explorer has *backward* awareness (don't repeat via dedup) but no *direction*
   (what is the highest-value unknown to pursue next).
5. **No synthesis** — two individually-flat findings whose *combination* is novel
   are never composed. The insight that lives in the *relationship between knowns*
   is never manufactured.

## The two axes

This work splits into two axes. Acquisition gets the right *raw* findings;
synthesis manufactures *novel views* from findings already held.

### Acquisition axis

- **L1 — Cut-level knowledge frontier.** Replace the coarse angle checklist with
  a `metric × dimension(s) × grain` coverage map derived from each finding's SQL
  signature (`aughor/sql/shape.py::query_signature` → `(tables, group_keys,
  measures)`). The *frontier* = (profile metrics × profiled dimensions) − covered.
  The per-domain generator is fed the concrete top-K uncovered cuts instead of
  "propose something deeper." New module: `aughor/explorer/frontier.py`.
- **L2 — Playbook as a hypothesis source.** Wire `playbook/retriever.py` into
  Scout. When a finding's metric + direction matches a playbook trigger, enqueue
  the play's `recommendation`/investigate as a *targeted* next question.
- **L3 — Forward-chaining from notable findings.** A high-novelty / anomaly /
  threshold-breach finding spawns 1–2 budget-bounded targeted drills (which
  segment drives it? new vs. prior period? what co-moves?).

### Synthesis axis (the centerpiece)

**Definition.** A *synthesized insight* is an **emergent claim** produced by a
typed relationship between two or more existing findings that **share a join key**
(common entity, segment, or time window), whose novelty exceeds that of either
parent. The shared join key is what makes two findings *combinable* rather than
merely co-listed → the data structure is a **findings graph** (nodes = findings,
edges = shared keys).

**Five composition operators (v1):**

| Operator | Composes | Emergent claim |
|---|---|---|
| `share` | a magnitude + a rate on the same entity | importance / contribution |
| `tension` | two findings opposing on one entity | a trade-off / problem |
| `concentration` | a total + a subset's large share | fragility / leverage |
| `confound` | an aggregate trend + a reversing split | the headline is misleading |
| `chain` | two metrics linked via a shared segment | a causal narrative |

**Verification is non-negotiable.** Synthesis is where spurious insight breeds.
Every emergent *number* is **re-derived by one confirming query** that passes the
same fan-out/grain/value-domain guards + `dry_run` + numeric grounding the main
loop uses — never narrated from the two parents. Relational claims (tension /
confound) are structurally checked, not asserted.

**Cadence.** Phase 9 runs at **end of run** (after Phase 8). A feature flag
`explorer.synthesis_incremental` lets it also fire the moment a new finding
creates a combinable pair.

## Architecture / hooks

- **Data model.** Populate the existing-but-empty `dimensions`/`measures` on the
  insight dict (`agent.py:3117`) from `query_signature`, and add a compact
  `signature` + `claim` block. Synthesized findings carry `composition_type` and
  `parents: [id, id]` and ride the normal `_emit_insight` path (ledger artifact +
  dossier + SSE), so drill-down/provenance work unchanged.
- **Phase 9.** New `ExplorationPhase.SYNTHESIS = "synthesis"`
  (`explorer/models.py:34`); inserted in `_explore_run` after Phase 8
  (`agent.py:734`). New method `_phase9_synthesis`.
- **Reuse.** SQL guards, `dry_run`, `verify_insight`, grounding, dedup
  (`is_redundant_insight`/`is_semantically_redundant`), novelty clamp, dossier,
  `_emit_insight`, watermark (for pinned freshness).
- **Pinned fix.** `_phase8_pinned_questions` becomes *reproduce-by-reading +
  refresh-if-stale*: read the prior pinned finding from the ledger; only
  re-execute when the activity watermark moved or no prior finding exists.
- **Flag.** Register `explorer.synthesis_incremental` in
  `kernel/flags.py::FLAG_ENV`/`FLAG_META` so it appears in Settings → System.

## Verification (real path)

Run on the `missimi` ecommerce connection and report before/after:
- questions asked split into **novel cuts vs. repeats**,
- count of **synthesized findings** by operator (with their confirming SQL),
- count of **playbook-triggered** follow-ups,
- pinned re-executions eliminated (read-not-rerun).

Discipline: BUILT → WIRED → TESTED → LEVERAGED on the real path; zero net ratchet
debt; gate every synthesized number on the same authorities as a normal finding.

## Build order

1. L1 frontier (prereq for clean synthesis) + signature/claim enrichment.
2. Synthesis pillar (graph + 5 operators + verification + Phase 9 + flag).
3. Pinned read+refresh-if-stale.
4. L2 playbook wiring.
5. L3 forward-chaining.
