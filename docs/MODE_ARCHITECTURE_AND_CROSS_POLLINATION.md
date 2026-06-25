# Answer Modes: Architecture, Findings & Cross-Pollination

*Last updated: 2026-06-25. Companion to the investigation-quality arc (PR #82).*

This document maps the three answer modes — **Insight** (quick), **Deep Analysis / ADA**
(multi-phase investigation), and **Explorer** (autonomous discovery) — and records what each
does well, what each is missing, and how they should learn from one another. It is a reference
for future work, not a spec; code pointers are approximate (they drift) but name the right files.

---

## 1. Why the modes diverged

The three modes evolved **opposite strengths because they have opposite jobs**:

| Mode | Job | Optimises for | Shape |
|---|---|---|---|
| **Insight** | One fast, trustworthy answer to a direct question | Latency + per-answer correctness | 1 query, grounded, presented honestly |
| **Deep / ADA** | A board-grade investigation that cannot be wrong | Correctness under uncertainty + decomposition | N phases (intake → baseline → decompose → dimensional → synthesis) |
| **Explorer** | Autonomously surface what matters in a dataset | Coverage + not-wasting-the-LLM on dead queries | Many queries, harvested, synthesised |

Because of those jobs, each built safeguards the others never needed — and they drifted apart
exactly where they should have shared. The `order_purchase_timestamp` Insight crash (the data's
date column lived in a table Insight never probed but Deep did) is the canonical symptom: **the
same understanding existed in one mode and was simply absent in the other.**

Entry points:
- **Insight** — `aughor/routers/investigations.py` (`/investigate` with `deep=false`), the chat/insight streaming block (~850–1450).
- **Deep / ADA** — `aughor/agent/investigate.py` (intake + phase nodes) orchestrated from `investigations.py` (~1900+).
- **Explorer** — `aughor/explorer/agent.py`.
- **Shared SQL tooling** — `aughor/sql/writer.py` (`SqlWriter.fix`, `_repair_from_candidates`), `aughor/sql/identifiers.py` (`repair_identifiers`, `unresolved_identifiers`), `aughor/tools/error_classifier.py`, `aughor/agent/verifier.py` (the Verifier).

---

## 2. Capability map

### Shared core (all modes already have)
- Unified metric grounding (`aughor/semantic/canonical.py: unified_metric_grounding`).
- Fan-out detection + de-fan (`aughor/sql/fanout.py`).
- Currency / format grounding (unified across surfaces in PR #82 via `web/lib/orgSettings.ts: localizeCurrency` + the export/CLI paths).
- The shared LLM SQL-repair loop (`SqlWriter.fix`) — now with a **deterministic candidate-binding substitution** fast-path (`_repair_from_candidates`, added 2026-06-25/G7) that fires before any LLM call.

### Insight is stronger at — *grounding BEFORE generation* + *presentation honesty*
| Capability | Where | Note |
|---|---|---|
| Trusted-query retrieval | `semantic/trusted_queries.py: retrieve_trusted` (used in investigations.py chat block) | Feeds *learned good queries* into the generator |
| Semantic compiler (grounded assembly) | `semantic` compiler / `compile_query` | Deterministic SQL for canonical shapes (scalar/timeseries/breakdown/ranking) |
| Measure-grain **prevention** | `semantic/measure_grain.py: measure_grains_block` | Tells the generator each measure's grain *before* it writes SQL |
| Receipt / badge | `_rcpt = {compiled, defan, grounded, lint}` | Per-query positive provenance the user can see |
| Headline grounding + plausibility | chat block | The answer text is checked against the real numbers |

### Deep / ADA is stronger at — *validation AFTER generation* + *honesty under uncertainty*
| Capability | Where | Note |
|---|---|---|
| **The Verifier** | `aughor/agent/verifier.py` | Deterministic trust battery (chasm/fan-out detectors) → a typed per-phase verdict |
| Error-classified repair + KB patterns + metrics block in fix | `aughor/agent/nodes.py` (FIX_SQL_PROMPT enrichment) | Repairs routed by error *type*, enriched with learned patterns |
| Temporal grounding | `investigate.py: _measure_date_span`, `_clamp_intake_to_coverage` | Understands the data's true date range + re-anchors windows (G2 fix) |
| Honesty guards | `investigate.py` (F2 reframe, F3 no-baseless-waterfall, G1 no-baseless-driver) | Never fabricate from a missing baseline / unmeasured change / truncated population |
| Intake | `investigate.py: ada_intake` | Feasibility check, dimension prioritisation, contradiction report, period selection |

### Explorer is stronger at — *pre-execution discipline*
| Capability | Where | Note |
|---|---|---|
| Pre-flight `dry_run` / EXPLAIN | `explorer/agent.py` (~2965) | Validate binds *before* the user-facing execute |
| `repair_identifiers` pre-execution | `sql/identifiers.py: repair_identifiers` | Fix case/separator before it errors |
| Semantic column repair (synonyms) | `explorer/agent.py` | location_country → country, etc. |
| `unresolved_identifiers` static check + negative-knowledge harvest | `sql/identifiers.py: unresolved_identifiers` | Skip / remember hallucinated names |

---

## 3. Findings — the asymmetries that bite

1. **Insight validates *after* it executes; Explorer validates *before*.** Insight's repair only
   fires on `result.error` (post-execute). A binder error therefore reaches the result path before
   it's repaired. The G7 deterministic substitution makes the *column* case instant, but the
   general pre-flight gap remains: Insight has no `dry_run` before the user-facing execute.

2. **Deep re-derives every phase query from scratch.** ADA does *not* use the trusted-query library
   or the semantic compiler — so it can re-introduce a fan-out the trusted library already solved.
   (Memory already captured the narrow version: "reuse the drilled finding's grain-correct query";
   this is the general case.)

3. **Grain is prevented in Insight, only caught in Deep.** Insight injects `measure_grains_block`
   pre-generation; ADA relies on the Verifier post-hoc. Deep should do both.

4. **Data understanding is assembled per-mode, not once.** The date-column-in-another-table bug
   (G2) happened because Insight's context lacked the date-range understanding Deep's intake built.
   The understanding existed; it just wasn't shared.

5. **Provenance is one-sided.** ADA findings carry a `trust_caveat` (the negative) but no positive
   "this query was compiled / grounded" receipt. Insight has the receipt but not the typed Verifier
   verdict.

---

## 4. Cross-pollination — what each should adopt

### → Insight learns from Deep / Explorer
- **Pre-flight `dry_run` + the Verifier battery** (validate-then-execute, not execute-then-repair).
- **The honesty guards** as reusable checks: caveat when a metric can't be computed instead of
  returning a plausible-but-wrong number.
- **Date-range / coverage awareness** as a shared primitive (the `_measure_date_span` probe).

### → Deep learns from Insight
- **Trusted-query retrieval in the phase planner** (stop re-deriving; reuse what's known-good).
- **Semantic-compiler grounded assembly** for canonical phase shapes (LLM only for the novel parts).
- **Measure-grain prevention** injected into the phase planner, not just caught by the Verifier.
- **The receipt/badge** paired with the existing `trust_caveat`.

---

## 5. The real move: a shared platform layer

These should not be per-mode features. Two extractions end the drift permanently:

1. **A shared SQL-safety pipeline** every mode calls, in order:
   `repair_identifiers → unresolved_identifiers → dry_run → deterministic-candidate-repair →
   SqlWriter.fix → Verifier`. Today Explorer owns the front half, ADA owns the Verifier, Insight
   owns neither end fully. One module, three callers.

2. **A shared "data-understanding" context**, built **once per question** and consumed by all modes:
   `metric grounding + measure grain + date-range/coverage + value-domains + trusted queries`.
   Today each mode assembles a different subset — which is precisely how Insight ended up blind to a
   date column Deep understood.

**The honesty invariant** becomes a single shared check both modes run: *never present a figure
whose basis is absent (missing baseline, empty domain, truncated population, unmeasured change)
without a caveat.* (F2/F3/G1 are the Deep-side instances; Insight needs the same.)

---

## 6. Prioritised recommendations

| # | Move | Direction | Risk | Leverage |
|---|---|---|---|---|
| **R1** | Pre-flight `dry_run` + repair in Insight (validate-then-execute) | Deep→Insight | Low | High — kills the raw-error class at the source |
| **R2** | Extract the shared SQL-safety pipeline (R1 generalised) | Platform | Med | Highest — one chain, three callers |
| **R3** | Trusted-queries + grounded assembly into ADA phases | Insight→Deep | Med | High — correctness + less re-derivation |
| **R4** | Shared data-understanding context object (metric+grain+date-range+domains+trusted) | Platform | Med | High — prevents the G2-class blindness |
| **R5** | Measure-grain prevention in the ADA phase planner | Insight→Deep | Low | Medium |
| **R6** | Receipt/provenance on ADA findings; Verifier verdict surfaced in Insight | Both | Low | Medium |

**Starting point (this branch): R1** — pre-flight validation in Insight. It's low-risk, continues
the Insight-hardening arc, directly closes the "raw error reaches the user" class, and is the first
concrete step toward the shared pipeline (R2).

---

## 7. Reference

- Investigation-quality arc: PR #82 (merged 2026-06-25, `60cfe44`) — F1–F9, G1–G7.
- G7 deterministic candidate substitution: `sql/writer.py: _repair_from_candidates`.
- G2 date-range probe fix: `investigate.py: _measure_date_span`.
- The Verifier: `agent/verifier.py`.
- Engineering principle this follows: build → wire → test → leverage on the real path; live-path > replay.
