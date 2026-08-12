# CI-0 — Transcript reading: why the chat feels mechanical (2026-08-12)

**What this is:** Arc CI's measurement baseline (`PLATFORM_ROADMAP_2026-08-12.md`
§2.4). Before building CI-1…CI-6, read the real transcripts and name the
mechanical moments concretely — then re-read after each wave. Success is these
markers trending toward zero, judged by prose, not status codes.

**Corpus:** the local store's **780 real investigations** (2026-06-29 →
2026-08-12): **636 quick-path turns** and **122 deep reports**, across the
user's own connections and the demo warehouses. Quantities are measured over
the full corpus; specimens are quoted verbatim from August turns.

---

## The five mechanical moments

### 1 · The quick path answers with a label, not an answer — 84% of turns

**537 of 636 quick turns carry zero prose.** The headline is a noun-phrase echo
of the question, and the answer exists only as a table cell:

> Q: "How many distinct customers are there?"
> H: "Number of distinct customers in the orders table" · rows: `[['793']]`
>
> Q: "Which product category has the highest profit?"
> H: "Product category with highest profit" · rows: `[['Technology']]`

The user asked a question and received a *caption*. A frontier chat's first
sentence IS the answer ("There are 793 distinct customers."). This is the
single largest contributor to the mechanical feel by volume.
→ **CI-3** (answer-first prose is the persona's first obligation) · **CI-4**
(the conversational body already does this — the Wave-5 live receipt answered
"5,009 distinct orders … `order_id` … groups all line items belonging to the
same customer order", unprompted grain reasoning included).

### 2 · When prose exists, it is slot-filling — the remaining 16%

The narrative arrives as a fixed rubric (`{narrative, anomalies, trend,
confidence}`) and the model dutifully fills every slot whether or not it has
anything to say:

> "The most profitable route in the latest month is GVA-NRT … **No anomalies
> are present in this single-point result. With only one month of data, a
> trend cannot be determined.**"

Obligatory anomaly/trend disclaimers appended to a one-number answer are
template noise, not analysis — the written form of the over-instruction the
prompt-economy measurement (§2.6 of the roadmap) found on the input side.
→ **PE-2/PE-3** (kill the slot obligations) · **CI-3** (prose shaped by the
question, not by a schema).

### 3 · No memory: 46 questions asked three or more times

"where are we losing money?" ×52 · "how many rows are in the returns table?"
×27 · "how many items per order?" ×25. Every repeat is re-derived from
scratch; nothing says "unchanged since this morning," nothing builds on the
previous answer, and the system cannot even *know* it is a repeat. (Some
repeats are demos and retries — but a colleague would notice the repetition;
the platform structurally cannot.)
→ **CI-1** (threads + bounded memory).

### 4 · Internal machinery leaks into user-facing fields

**11 quick headlines contain injected prompt text.** Specimen (August 12):

> Q: "What is the average delivery time by service level?"
> H: "RELEVANT SQL AND DOMAIN PATTERNS (apply when writing queries): ──
> Average Transit Time (intermediate) ── Business context: The average
> elapsed time between dis…" · rows: 0

**10 deep headlines are the fan-out caveat** (the "$14" specimen — an internal
data-quality warning as the title of an executive report). Same family, one
boundary failure: internal text promoted into answer fields with nothing
checking the promotion.
→ chips `task_4d79f282` (caveats → structured metadata) + a new chip for the
prompt-block leak; **PE-2**'s post-generation check ("the report must address
the asked question") catches both shapes mechanically.

### 5 · Analysis Mode emits the report FORM regardless of whether analysis happened

Across all 122 deep reports: **28% are the deterministic fallback** ("Narrative
synthesis was unavailable — the model was slow or failed") dressed as a
finished report · **34% have zero recommendations** · **59% have no closing
summary** · confidence is **LOW on 52%**. Eight reports wrap a single-sentence
"executive summary" in full report chrome:

> Q: "Investigate the pattern: Customer — cross-domain driver"
> E: "Performance variance is most pronounced in the is_business_traveller
> dimension…" (one sentence · LOW · 0 recommendations · no closing)

The form promises an investigation; the content is one observation. Emitting
the chrome unconditionally is what makes the real analyses harder to trust.
→ chips `task_94dbfb2c` (degraded reports look degraded) · **CI-4** (depth as
a tool the conversation reaches for, sized to what it found).

---

## The honest counterweight

When synthesis actually runs, the deep prose is competent — "Ohio at
**-21.69%** and Colorado at **-20.33%** … systemic issues in specific states
and categories rather than regional weakness" is a real analyst sentence, and
the returns-by-segment report reads well. **The mechanical feel is
concentrated in the wrappers** (quick-path caption answers, slot rubrics,
unconditional report chrome, leaked internals) **and in what's absent**
(memory, follow-through), not in the model's prose when it is allowed to
write. That is Arc CI's core bet, now with a baseline behind it.

## Baseline scorecard (re-measure after each CI wave)

| marker | today |
|---|---|
| quick turns with zero prose | **84%** (537/636) |
| quick headlines that echo the question instead of answering | dominant pattern in the no-prose set |
| internal text leaked into headlines (quick + deep) | 22 |
| questions asked 3+ times, unrecognized | 46 |
| deep reports that are the deterministic fallback | 28% |
| deep reports with zero recommendations | 34% |
| deep confidence LOW | 52% |
| converse-served turns (the CI-4 target state) | 5 lifetime |

Measurement notes: quick/deep split by report shape (`_report_type` /
`executive_summary` ⇒ deep); "zero prose" = no `insight.narrative`; converse
count from the windowed route receipt (`GET /obs/route-mix`). The scorecard is
one command — `uv run python scripts/ci0_scorecard.py` — and that script is the
counting authority for future readings.

**Companion measurement (PE-1, same day):** every LLM call is now attributed to
the call site that spent it (`GET /obs/prompt-weight`). The local log's 2,683
historical calls total **6.2M prompt tokens**, all pre-attribution — the first
attributed reading lands with the next deploy's traffic and becomes PE-2's
target list.
