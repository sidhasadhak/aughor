# SOMA-SQL, leveraged — and the Ambiguity Ledger: Aughor's compounding answer

*2026-07-06. A deep re-read of arXiv 2606.11424 ("Soma-SQL: Resolving Multi-Source Ambiguity
in NL-to-SQL via Synthetic Log and Execution Probing", Oracle AI) against Aughor's assets,
plus this session's own controlled measurements. This document is the design spec for the
next accuracy phase: what to adopt from the paper, and — the larger half — seven
improvisations where Aughor's architecture goes structurally beyond it.*

*Companions: [`SPIDER2_PHASE0_FAIL_ANALYSIS_2026-07-06.md`](SPIDER2_PHASE0_FAIL_ANALYSIS_2026-07-06.md)
(the measured evidence this builds on) · [`10X_AND_SPIDER2_PROGRAM_2026-07-06.md`](10X_AND_SPIDER2_PROGRAM_2026-07-06.md)
(the umbrella program) · memory `soma-sql-ambiguity` (the June read of the same paper).*

---

## 1 · The paper, verified mechanically (2026-07-06 full read)

**Online pipeline, per question:** agentic schema linking → **K=10 candidates**, each via
plan → generate → critique (≤5 critique rounds; critique uses schema validation, AST
parsing, planner diagnostics, light execution) → an **LLM extracts implementation-level
diffs** across all K (e.g. `city='NYC'` vs `city='New York'`) → diffs + a predefined
taxonomy become *ambiguity dimensions* as triples (dimension, options, SQL evidence) →
**8–9 probe SQLs** (3 grounded in observed diffs; 5–6 instantiated from the taxonomy
against schema + live values) execute against the DB → LLM judge picks a **seed**
candidate → a resolver forms an intent estimate from (question, schema, retrieved MCQ
records, dimensions, probe report) → **minimal repair** of the seed ("apply changes only
when supported by probe evidence; keep edits minimal and localized") → execute; **fallback
to seed** on failure/empty.

**Taxonomy:** `AmbiSchema` (table/column/grain mapping) · `AmbiValue` (filter literals) ·
`AmbiIntent` (semantic operation: metric definition, aggregation, ordering, boundary).

**Offline synthetic query log:** real SQL-only logs → LLM writes a fully-specified NL
description per query → deliberately **underspecified variants** along ambiguity
dimensions → multi-candidate generation on each variant → disagreements distilled into
**MCQ records** *(underspecified question, schema, dimension, option set, anchor-supported
correct option, SQL evidence)* → at inference, retrieve ~10 similar records
(all-MiniLM-L6-v2), rerank to 3, inject as in-context examples into plan/generate/critique.

**The numbers that matter (their ablations):**

| Evidence | Value |
|---|---|
| Probing over majority voting | **+9.0 avg** (Spider2-Lite 41.1 → 61.0 with seed+probing) |
| Probing over judge-selection-only | **+7.0 avg** (46.1 → 61.0 on Lite — the back half is where the money is) |
| Recovery on instances where NO candidate was correct | **+30.6 EX** (probing repairs *beyond* the candidate set) |
| Synthetic log | **+7.3 to +10.1** (model/benchmark dependent) |
| Unambiguous-question regression | **none reported** (AMBROSIA unambig 94.7%; gap vs ambig only 2.7%) |
| Probe audit | groundedness 0.94 · resolution correctness 0.90 · repair faithfulness 0.96 — **LLM-judged, n=50, no human annotation** |

**Weaknesses (admitted or unquantified):**
1. **Cost is never reported.** K=10 × ≤5 critique rounds + extraction + probes + judge +
   resolver + repair ≈ **50–60 LLM calls per question, forever, for every question** —
   including unambiguous ones (mitigated only by candidate agreement making probes moot).
2. **Convergent-wrong blindness:** "when all candidate SQLs converge to the same incorrect
   interpretation, unresolved intent may remain undetected." Disagreement is their only
   ambiguity sensor.
3. The quality audits are LLM-as-judge, not human.
4. Headline numbers ride **GPT-5.3-Codex**; the mechanics transfer to weaker models but the
   ceiling drops (their own Gemma-4-31B rows show it).

**Why this matters to us precisely now:** our candidates lever
([`evals/spider2_candidates.py`](../evals/spider2_candidates.py)) is SOMA's *front half*
(engineered diversity + deterministic signature selection) with the *back half* (probing +
evidence-gated repair) unbuilt — and their ablation localizes most of the gain in the back
half. Our measured +3/0 on the miss subset came from selection alone; their +30.6-on-
never-correct says repair-beyond-the-candidate-set is a different, larger prize. Our
residual misses are literally their showcase inputs: `local021` (per-match vs per-career
totals) is a textbook AmbiIntent grain disagreement; `local007` (boundary logic) is
AmbiIntent; the label/value cases are AmbiValue.

---

## 2 · Direct leverage — complete SOMA-lite in the harness (B1–B3)

### B1 · The probe-and-repair stage (the missing back half)

**Trigger:** only when the candidates stage reports `n_signatures > 1` (disagreement is
free evidence we already compute). Agreement ⇒ ship the plurality answer, zero extra cost.

**Stage design** (extends `evals/spider2_candidates.py`; new module
`evals/spider2_probes.py` so it stays independently testable):

1. **Disagreement extraction — deterministic, NOT the paper's LLM step** (see I2):
   sqlglot-normalize each live candidate; pairwise AST diff; classify each delta:
   - WHERE/HAVING literal delta → `AmbiValue(column, {literals})`
   - GROUP BY / aggregate-function / DISTINCT delta → `AmbiIntent(grain|aggregation)`
   - same-role column swap (different column, same clause position) → `AmbiSchema(column)`
   - date/window expression delta → `AmbiIntent(window)`
   Output: the paper's (dimension, options, evidence) triples, derived without a model call.
2. **Probe battery — deterministic-first** (see I3): for each dimension, prefer the owned
   deterministic probe; fall back to ONE LLM-planned probe per unresolved AmbiIntent
   dimension (cap: 3 LLM probes/question — the paper uses 8–9 all-LLM).
3. **Resolution + minimal repair:** one LLM call conditioned on (question, dimensions,
   probe results, seed = current plurality winner) with the instruction contract from the
   paper — *edit only what the evidence covers* — enforced by OUR acceptance gates
   (§I7-style): the repaired SQL must (a) execute, (b) clear the probed dimension
   (re-run the deterministic probe against it), (c) not regress any untouched dimension,
   (d) AST-diff against the seed must touch ONLY clauses named in the evidence — a
   deterministic faithfulness check, stronger than their 0.96 LLM-judged one. Any gate
   fails ⇒ keep the seed (their fallback, our never-go-backwards discipline).

**Cost:** ~0 extra on agreed questions; ~2–4 extra calls on disagreed ones (vs their flat
~50–60). **Measurement:** the standing protocol — controlled same-instance run on the miss
subset + sentinels, recovered/regressed per instance; extend to full-135 only if monotonic.

### B2 · MCQ retrieval from our own verified runs (self-ICL, contamination-clean)

Skip their synthetic-log pipeline initially — we hold something better: per benchmark run,
70+ **execution-verified correct (question, SQL) pairs** of our own generation, and (in the
product) `verify/verdicts.py` human corrections + `semantic/trusted_queries.py`. Build MCQ-
shaped records from *those*: for each solved instance, (question, resolved dimension if the
candidates stage logged disagreement, the winning reading, its SQL evidence). Retrieve top-3
similar records into the plan/generate prompts (the paper's exact injection points; embedding
retrieval already exists in `semantic/lexical.py` + `kb_retriever`). Their +7–10 ablation is
the value estimate for this asset class. Integrity: our own outputs — never released gold.
The synthetic pipeline (§1) becomes the **cold-start fallback** for fresh connections later.

### B3 · The signature-tiered escalation ladder (their cost problem, solved)

Our traces show easy questions converge: all 4 strategies → 1 signature (e.g. `local002`).
So make K adaptive, keyed on the free agreement signal:

```
K=2 (direct + adversarial, the most-diverse pair)
  └─ 1 signature → SHIP                        (~1.15× avg cost)
  └─ 2 signatures → +2 strategies (K=4)
       └─ plurality ≥ 3/4 → SHIP plurality
       └─ else → B1 probes → evidence repair
            └─ still unresolved → product: ASK (I4) · benchmark: ship best + flag low-confidence
```

The deterministic guard battery keeps running on every rung — it is the partial answer to
their convergent-wrong blindness: fan-out/grain/join/value errors shared by ALL candidates
still get caught by machinery that doesn't depend on disagreement.

---

## 3 · The improvisations — where Aughor goes beyond the paper

### I1 · The Ambiguity Ledger — resolution that COMPOUNDS (the headline bet)

**The structural difference:** SOMA re-pays its full pipeline every time any user asks an
ambiguous question; the resolution evaporates after the answer. Aughor has what a paper
harness cannot: a **persistent per-connection substrate** — `SemanticContract`
(`aughor/semantic/contracts.py`), ontology overrides, `trusted_queries`, the verdicts
store, the evidence ledger.

**Design:** when a disagreement is resolved — by probe (B1), by user (I4), or by human
verdict — **crystallize the resolution as a first-class record**:

```
AmbiguityResolution {
  connection_id, schema_scope,
  dimension: {kind: AmbiValue|AmbiSchema|AmbiIntent, subject: "total runs by strikers"},
  readings: [{label, sql_evidence}],
  resolved_reading, resolution_source: probe|user|verdict,
  probe_evidence | user_utterance | verdict_id,
  question_fingerprint(s), created, use_count
}
```

Storage: a new org-scoped store following the house pattern (`AUGHOR_*_DB` override,
migrations framework), OR folded into `SemanticContract` where the resolution *is* a metric
definition (a resolved "revenue means…" IS a contract — reuse before invent; decide at
build time by whichever the first ten real resolutions actually look like).

**Read path:** the retrieval half of B2 consults the ledger FIRST — a question matching a
resolved dimension (embedding + lexical overlap, the `trusted_queries` matching pattern)
injects the resolution as an authoritative prior and **skips candidates + probes
entirely**.

**The consequence:** SOMA's cost curve is flat per question; Aughor's **burns down
monotonically per connection** — the ambiguity space of a deployed schema shrinks with use.
This is the honest, mechanical version of the "living context graph that compounds"
(memory: `context-graph-closed-loop-gap`) — built from SOMA mechanics on stores we already
ship. **Metric:** per connection per week — resolutions served from ledger vs probed vs
asked; the first should grow, the other two shrink. That chart IS the moat demo.

### I2 · Deterministic AST-diff disagreement extraction

The paper spends an LLM call to diff candidates and trusts its output. We own sqlglot and a
house of AST guards: normalized-AST pairwise diff is deterministic, complete for the diff
classes that matter (literal / grouping / aggregation / column-role / window), and maps to
the taxonomy by construction (§B1.1). Cheaper, reproducible, auditable — and the diff
itself is receipt-ready evidence. *Novel vs the paper; publishable as an ablation
(deterministic vs LLM extraction) if we ever write this up.*

### I3 · The deterministic-first probe battery

Per taxonomy class, Aughor already OWNS the probe the paper plans with an LLM:

| Dimension | The paper | Aughor, already shipped |
|---|---|---|
| AmbiValue (filter literal) | LLM-planned probe | `join_guard.bind_filter_literals` + CHESS `value_index` (probe-confirmed, dry-run-gated) |
| AmbiSchema / grain | LLM-planned probe | `grain_intent.check_result_grain` (COUNT DISTINCT probe) + `grain_guard` uniqueness probes |
| AmbiIntent (date axis/window) | LLM-planned probe | the temporal-axis recovery (intake, DB-probed) + window guards (span/density/trailing) |
| Join validity | — | `_probe_overlap` containment probes |
| AmbiIntent (metric/boundary semantics) | LLM-planned probe | **the residue — the only class that keeps an LLM-planned probe** (cap 3) |

Cost per disagreement collapses from their 8–9 LLM-planned probes to mostly-free
deterministic probes + ≤3 planned ones, and every probe result is journal-ready.

### I4 · Ask-once-remember-forever (the fusion the paper formalizes but cannot do)

Their Proposition 1 formalizes human clarification as the **ceiling** probing
approximates. Aughor already shipped the surface the ceiling needs: the clarify gate
(`agent/clarify.py`), the SOMA candidate-disagreement seam (`agent/soma.py`,
`AUGHOR_SOMA_CLARIFY`, currently dark), and grounded option chips in `/ask` (PR #89).

**One detection engine, two policies:**
- **Autonomous mode** (benchmark, monitors, background agents): resolve via B1 probes.
- **Interactive mode** (product `/ask`): when disagreement maps to AmbiIntent — a business
  definition, precisely where probes are weakest and humans are instant — surface ONE
  clarify chip whose options ARE the candidate readings with their result previews
  ("per-match totals: avg 68 · career totals: avg 1,131 — which did you mean?").
- **Either way the outcome writes to the Ambiguity Ledger (I1)** — so that class of
  question never asks again on that connection. The paper approximates the ceiling; we hit
  it once and cache it.

This also finally gives `agent/soma.py` its wiring-in story with a measured justification
path (the June ambiguity_eval showed the deterministic detector is blind to structural
ambiguity — candidate-signature disagreement is exactly the missing sensor, now already
computed by the candidates stage for free).

### I5 · Real logs beat synthetic logs

They synthesize underspecification because they assume SQL-only logs. We hold three richer
sources, in strictly increasing quality: (1) `sql/query_log_miner.py` — real historical
queries (join paths, value domains, formulas already mined); (2) the candidates stage's own
disagreement records accumulating per run; (3) `verify/verdicts.py` — REAL human
accept/reject/corrections. MCQ records distilled from real disagreements + real human
resolutions are strictly better supervision than synthetic variants; their synthetic
pipeline is our cold-start fallback only. (Their +7–10 log ablation prices this asset.)

### I6 · Ambiguity as a first-class trust signal (nobody exposes this)

`n_signatures`, the resolved dimension, and the probe evidence go on the **Trust Receipt**:
*"This question admits 3 readings; this answer follows reading B because a live probe
showed X; readings A and C are one click away."* Internal machinery becomes the product's
stated differentiator — trustworthy by inspection — and doubles as the interaction surface
for I4. Wire: extend `_write_answer_receipt` payload + one receipt-panel block; the
candidates stage already logs the needed struct in traces.

### I7 · Evidence-typed repair gates (their faithfulness, made deterministic)

Their "repair faithfulness 0.96" is LLM-audited. Ours becomes a *gate*, not an audit: the
repair call returns SQL whose AST-diff against the seed must be covered by the cited
evidence spans (clause-level), verified deterministically before adoption; uncovered edits
⇒ reject, keep seed. This is the same never-go-backwards philosophy as
`executor.execute_guarded`'s acceptance gates, extended with typed evidence — and it should
eventually graduate INTO the shared executor as the repair contract for all paths.

---

## 4 · Build sequence, effort, and honesty

| # | Item | Where | Effort | Gate before scaling |
|---|---|---|---|---|
| B1 | Probe-and-repair stage (I2+I3+I7 inside) | `evals/spider2_probes.py` + candidates hook | 1–2 days | controlled miss-subset run: monotonic or it dies |
| B3 | Escalation ladder | `spider2_candidates.py` | ½ day | cost/instance vs fixed K=4, same accuracy |
| B2 | Self-ICL from verified runs | harness + `kb_retriever` seam | 1 day | same controlled protocol |
| I1 | Ambiguity Ledger (store + read path) | `aughor/` (contracts-or-new-store decision) | 2–3 days | ledger-hit rate on repeat question classes |
| I4 | Clarify fusion (product) | `agent/soma.py` wiring + `/ask` chips | 1–2 days | ambiguity_eval structural recall > 0 + ask-rate budget |
| I6 | Receipt surfacing | receipts + one panel | ½ day | — |

**Honest constraints, stated up front:** (1) their headline numbers ride GPT-5.3-Codex —
on glm-5.2 the mechanics transfer, the ceiling is lower; the *ledger/compounding* angle
(I1) is therefore worth MORE to us than raw inference-time machinery, because it converts
scarce model capability into durable substrate. (2) Every lever faces the standing
measurement protocol (controlled same-instance on/off, sentinels, no misses-only claims) —
two levers already died under it this week (projection, col-semantics); these get no
exemption. (3) The convergent-wrong blind spot survives everything here except the
deterministic guards and the user's eye — I6 is what keeps us honest with the user when
machinery can't be.

**The one-line thesis:** SOMA proves execution-grounded disagreement resolution lifts past
the sampling ceiling at high per-question cost; Aughor's improvisation is to make each
resolution **permanent, deterministic where possible, human-confirmed where it matters, and
visible on the receipt** — ambiguity burn-down as a compounding, inspectable asset instead
of a recurring inference tax.
