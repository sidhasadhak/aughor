# Diff & Learnings — my cold trace vs Aughor's live pipeline

Same warehouse (`BeautyCommerce-Analytics` / `8090c60f`, schema `analytics`), two analysts:
**me** working the raw schema by hand ([01_cold_trace.md](01_cold_trace.md)), and **Aughor's real
pipeline** run live ([run_pipeline.py](run_pipeline.py) → `evidence/pipeline_*`). All claims below are
backed by captured evidence in `evidence/` and the root-cause diagnostic
([diagnose_blanks.py](diagnose_blanks.py)).

---

## ✅ Implemented on this branch (F1 + F2)

The two highest-leverage findings are now fixed and verified on the live path:

- **F2 — cardinality-aware chasm guard** (`aughor/sql/fanout.py` + `aughor/profile/validate.py`).
  `_chasm_roots` now takes an optional cardinality oracle and **excludes any "satellite" that is 1:1 on
  the join key** (a dimension, not a fan-out source). Wired into the audits via a live, cached
  `COUNT(*)=COUNT(DISTINCT key)` probe. **Result:** the correct weighted-attribution chart that was being
  blanked now passes; the genuine 3-satellite chasm is still caught. 5 new unit tests in
  `tests/unit/test_explorer_grain_lint.py::TestChasmCardinalityAware`.
- **F1 — per-question SQL retry** (`aughor/profile/infer.py`). The real failure mode (diagnosed live, see
  [diagnose_keyq.py](diagnose_keyq.py)) was the LLM **returning empty SQL** for answerable questions via the
  "return empty if impossible" escape hatch — and the old code *skipped* empties instead of retrying. Now
  every unsolved question (empty OR audit-failed) goes to a **focused per-question retry** (≤2 attempts)
  with the prior failure reason + a no-bail instruction. **Result (live):** `key_question_sql` went from
  **1/8 → 8/8** runnable, audited queries in ~32s (`evidence/f1_verify.log`). The retry's "pre-aggregate in
  its own CTE" guidance also routed Q7 *around* the F8 join-guard false-positive below.

> Verified live, not just unit-tested. Full unit suite: 956 passed. (Two pre-existing ratchet tests in
> `test_kernel_contracts.py` were already red on the base — identical counts with/without these changes —
> so they're untouched baseline drift, not regressions.)

## Headline

**Aughor gets the *framing* right and the *execution* wrong.** It nails the industry, proposes a
sensible metric vocabulary, and its autoseed glossary independently re-derived the two hardest grain
facts (payment-retry grain; attribution weights sum to 1). But the layer that turns names into runnable
SQL collapses:

> **Of 16 build-time SQLs the pipeline tries to produce (8 metric `value_sql` + 8 `key_question_sql`),
> 12 came back EMPTY.** When I fed the *obvious correct SQL* for the empty ones through Aughor's **own**
> audit, **7 of 7 passed** — i.e. the data supports them and the audit accepts them. The blanks are a
> **generation-robustness failure with no fallback**, not a data or audit limitation.

The intelligence is *named but not computed*. My cold pass computed every one of these in a single query.

## Scorecard

| Dimension | My cold trace | Aughor pipeline | Verdict |
|---|---|---|---|
| Industry classification | DTC Beauty E-commerce | DTC Beauty E-commerce (conf 0.95) | ✅ tie |
| Business model | transactional retail | "DTC **subscription** & one-time retail" | ⚠️ hallucinated subscription |
| Table grain | all 13 stated | glossary nailed grain (incl. retry + multi-touch) | ✅ tie — strong |
| NULL semantics (structural vs noise) | shade kept, gift_message dropped | both un-caveated; shade desc invented "haircare" | ❌ pipeline miss |
| Metric `value_sql` populated | n/a (I just ran them) | **3 / 8** | ❌ 5 empty |
| `key_question_sql` populated | n/a | **1 / 8** | ❌ 7 empty |
| Margin-leak (margin × returns) | **found** (Fragrance 92%/20%) | absent from metrics & questions | ❌ pipeline miss |
| ROAS / channel efficiency | found (Email 7×, TikTok 0.4×) | metric blanked; Q1 sums revenue, never ÷ spend | ❌ not computed |
| Conversion by source | found (TikTok 22%) | metric is global; by-source Q has empty SQL | ❌ insight absent |
| Glossary cross-warehouse safety | — | inherited a DELETED warehouse's annotations | ❌ contamination bug |

---

## Findings (root-caused, mapped to modules, prioritized)

### F1 — Build-time SQL generation has no deterministic fallback ⭐ (highest leverage)
**What:** 7/8 `key_question_sql` and 2/8 trivially-answerable `value_sql` are empty. The generator
([`infer._generate_key_question_sql`](../../aughor/profile/infer.py)) does *one* batched LLM call + *one*
batched repair; anything that doesn't bind/audit on those two shots is silently abandoned (`""`).
**Evidence:** [diagnose_blanks.py](diagnose_blanks.py) — my hand SQL for Q2/Q3/Q5/Q7/Q8 and for Refund-Rate
& Inventory-Turnover **all PASS Aughor's own `audit_finding_sql`/`audit_value_sql`.** The questions are
answerable; generation just didn't land them.
**Root cause:** batched all-or-nothing generation. A single structured-output call asked to emit SQL for 8
questions at once; missing/again-failing indices fall through to empty with no per-question retry and no
template fallback.
**Fixes (cheap → strong):**
1. **Per-question retry** on the failures instead of one batched repair (isolate the hard ones).
2. **Deterministic templates** for the common shapes the profiler already recognises — "rate by
   dimension", "top-N by measure", "trend of metric" — built straight from the recipe's
   formula+grain+the dimension named in the question. Most key questions are one of ~5 shapes.
3. **Log + surface the empty count** as a profile-quality signal (today the silent `""` reads as "no
   answer exists", which is false). Per the leverage principle: *prevention (template) > recovery (a
   third LLM shot)*.

### F2 — Fan-out guard false-positives on normalized weighted attribution ⭐
**What:** The pipeline left the **Channel Contribution (Attribution)** metric's `chart_sql` empty — the one
chart that tells the ROAS-inversion story (the single most actionable finding). Aughor's
`sum_over_chasm_fanout` flags `SUM(revenue × weight)` over `attribution ⋈ invoices` as a chasm over-count.
**Evidence:** [diagnose_blanks.py](diagnose_blanks.py) returns *"grain bug: SUM over a chasm join"* — but
the chasm-join result is **byte-identical** to the pre-aggregated result across all 6 channels (total
$2,480,208 = total invoice revenue), proving the query is correct.
**Root cause:** the guard treats any table sharing the order key as a many-side satellite. But
`invoices.order_id` is **unique (1:1)** — a dimension, not a fan-out source — and attribution weights
**normalize to 1 per order**, so `SUM(value×weight)` is fan-out-safe by construction. The guard checks the
*join shape* but not the *join-key cardinality*.
**Fix:** in [`aughor/sql/fanout.py`](../../aughor/sql/fanout.py), before flagging a chasm, **probe key
cardinality**: if a putative "satellite" is unique on the join key (1:1), it is a dimension — don't flag.
Bonus: recognise the `SUM(measure × weight)` idiom where `weight` carries a "sums to 1" caveat (the
glossary already wrote that caveat for `attribution.weight`!) as the canonical attribution pattern.
This is the second half of the lesson: the knowledge **was captured** (glossary) but **not propagated** to
the guard.

### F3 — NULL semantics: structural vs noise are not distinguished
**What:** `products.shade` (80% NULL, **structural** — populated only for Makeup) and `products.gift_message`
(95% NULL, **noise**) and `customers.middle_name` (100% NULL, typed INTEGER) are all treated as ordinary
attributes. The glossary even describes `gift_message` as "a predefined gift message option" — dignifying a
noise column — and invents "or haircare" for shade.
**Evidence:** `evidence/pipeline_glossary_analytics.yaml`; raw `evidence/raw_profile.txt` (shade: Makeup 0%
null / all others 100%).
**Why it matters:** the structural NULL on `shade` *is* the Makeup segmentation signal (drop it and you lose
a dimension); the noise NULL on `gift_message` should never surface as a finding or dimension. Conflating
them either loses signal or emits "95% of gift_message is null!" non-insights.
**Fix:** [`aughor/semantic/autoseed.py`](../../aughor/semantic/autoseed.py) already sees sample values — add a
**null-profile pass** per column: compute null% and, for high-null columns, test whether nullness is
*predicted by another column's value* (structural) or *unconditional* (noise). Emit a caveat:
`"structural NULL — populated only when category='Makeup'"` vs `"95% NULL — low-signal, exclude from
dimensions"`. A 100%-NULL column should be flagged dead (and the INT-typed all-NULL `middle_name` is a
schema smell worth noting).

### F4 — `unit_or_range` is guessed from world knowledge, not measured → sanity-checks misfire
**What:** AOV's declared range is `"USD (human scale: 20–150)"`; the actual AOV here is **~$537**. Gross-margin
range etc. are fine, but the AOV band is off by 3–25×.
**Evidence:** `evidence/pipeline_profile.json` (AOV metric) vs cold-trace F1 ($504–$693 by tier).
**Why it matters:** `unit_or_range` is *load-bearing* — `validate._range_kind` and the finding range-checker
use it to flag anomalies. A band guessed from "typical beauty AOV" will flag this warehouse's correct AOV as
anomalous (false positive), the mirror of the bug the band is meant to catch.
**Fix:** after `value_sql` audits green, **calibrate the numeric band from the actual computed value**
(e.g. set the sane range to a window around the measured magnitude, keep only the *kind* — ratio/pct/usd —
from world knowledge). Measure, don't assume.

### F5 — Cross-domain "AND" insights are not in the metric/question vocabulary
**What:** My highest-value finding — *the highest-margin category (Fragrance, 92%) is also the highest-
return (20%)* — requires combining **margin (item grain)** with **returns (order grain)**. Aughor's 8
metrics and 8 questions are each single-domain; nothing crosses margin × returns.
**Evidence:** cold-trace finding #2 vs `pipeline_profile.json` (no margin∧returns metric/question).
**Why it matters:** the per-metric framing structurally can't surface "good on X but bad on Y" — exactly the
class of insight that changes a decision (protect Fragrance margin ⇒ fix returns, not pricing).
**Fix:** the profiler already supports *composite* key questions (the SKU-margin-leak prompt language is in
`_generate_key_question_sql`). **Seed one composite question per metric pair that shares an entity** — e.g.
"which categories/SKUs are high-margin AND high-return?" — and lean on F1's CTE-per-metric template so it
actually generates. The capability exists; it just isn't *invoked* for this warehouse.

### F6 — Glossary is keyed by bare `schema.table` → cross-warehouse contamination
**What:** Before I cleared it, my brand-new connection's `analytics.*` tables inherited a **deleted**
warehouse's glossary: 24 `analytics.*` entries for a warehouse with only 13 tables — **11 described tables
that don't exist here** (`clicks`, `impressions`, `experiments`, `pnl_daily`, `shipments`, `stockouts`…),
and name-matches carried **stale/hallucinated enum values** (`channel: …, YouTube, Affiliate` — neither
exists in my data).
**Evidence:** `evidence/stale_glossary_analytics_BEFORE.yaml`; commit `d961612`.
**Root cause:** `glossary.yaml` `tables` dict is keyed by table name only; autoseed's "never re-seed a
table that has an entry" treats *name* as identity. Two different databases with an `analytics.orders`
collide; a dropped warehouse's annotations linger and silently apply to the next one.
**Fix:** key glossary entries by **(connection_id, schema, table)** *or* fingerprint by **column set**, and
**invalidate on schema drift** (entry's columns ⊄ live columns ⇒ re-seed). Autoseed's idempotence guard
should compare the *column fingerprint*, not the name. (Note: the *fresh* autoseed, once I cleared the
stale entries, was clean — so this is purely a keying/invalidation bug, not a generation bug.)

### F7 — Business model hallucinates beyond the evidence
**What:** model = "DTC **subscription** & one-time purchase retail". There is no subscription/plan/renewal
table or column anywhere in the schema.
**Evidence:** `pipeline_profile.json`; schema has no recurring-billing artifact.
**Fix:** constrain `business_model` to be **evidence-cited** like `north_star_metrics.maps_to` already is —
require the inference to name the column(s) that justify each model claim, and drop unsupported clauses.
(Low severity, but it's the same discipline already enforced on metrics, just not on the prose fields.)

---

### F8 — join value-domain guard false-positives on a legitimate subset join (discovered during F1) 🔎
**What:** the `join_guard` (`check_join_value_domains`) flagged a correct `orders LEFT JOIN refunds ON
order_id` as a *"JOIN VALUE-DOMAIN MISMATCH"* and blanked the refund-rate-by-warehouse question.
**Evidence:** [diagnose_keyq.py](diagnose_keyq.py) Q7 — *"fabricated join: …MISMATCH: analytics.orders.order_id"*.
**Root cause (hypothesis):** `refunds.order_id` is a small subset (463) of `orders.order_id` (4,620) — a
normal parent⋈child FK where the child covers ~10% of parents. An overlap-fraction threshold reads that low
coverage as a fabricated join, the same *over-aggressive-guard* shape as F2 (one module over, in `sql/join_guard.py`).
**Status:** F1's per-question retry **routed around** it (the model recomputed the denominator from `orders`
alone), so Q7 now answers — but the guard itself should learn that **child⊂parent on a real FK is not a
fabricated join** (direction-aware overlap: high coverage from the child side, not the parent side). Logged
as a follow-up, not yet fixed.

## What Aughor already does well (and the cold pass should copy back)

- **Grain detection in autoseed is excellent** — it independently caught the two hardest facts: payments =
  *attempt* grain ("distinguish retry attempts") and attribution weights "should sum to 1.0 across
  channels." That's better than many human analysts.
- **The audit philosophy is right** — "a grounded-but-wrong KPI is worse than no KPI," and the bounded-rate
  boundary check is exactly what kills the `abandoned=0 → 100%` and `>1 conversion` bugs. It correctly
  blanked my saturated repeat-rate (=1.0). The problem is **recovery**, not the gate.
- **Recipe resolution worked** — 5 metrics matched curated retail recipes with correct formula+grain; that
  knowledge is sitting right there to drive F1's deterministic templates.

## The through-line

Every miss is the **same shape**: Aughor *captured* the knowledge but didn't *propagate / act* on it.
- Glossary knew attribution weights sum to 1 → the fan-out guard still blanked the attribution chart (F2).
- Recipes carry the exact formula+grain → key-question generation still produced nothing (F1, F5).
- The audit knows a metric's declared range → nobody calibrated that range from the data (F4).

This matches the engineering principle in my notes: **gate on the authority, but make sure the authority's
knowledge is wired through to where the work happens — BUILT → WIRED → LEVERAGED.** Aughor has BUILT the
knowledge layer; the leverage is leaking between stages.

## Prioritized actions

| # | Action | Module | Effort | Payoff | Status |
|---|---|---|---|---|---|
| 1 | Per-question retry for blanked/failed key-question SQL; surface empty-count | `profile/infer.py` | M | ⭐⭐⭐ 1/8 → 8/8 live | ✅ **done** |
| 2 | Cardinality probe before chasm flag (skip 1:1 dimensions) | `sql/fanout.py` + `validate.py` | S | ⭐⭐⭐ unblanked attribution/ROAS | ✅ **done** |
| 3 | Null-profile pass: structural-vs-noise caveats; flag dead columns | `semantic/autoseed.py` | S | ⭐⭐ keeps shade, drops gift_message | open |
| 4 | Calibrate `unit_or_range` band from the audited value | `profile/infer.py` + `validate.py` | S | ⭐⭐ stops false anomaly flags | open |
| 5 | Seed one composite (cross-domain AND) question per shared-entity metric pair | `profile/infer.py` | S | ⭐⭐ surfaces the margin-leak class | open |
| 6 | Key glossary by (conn, schema, table)/column-fingerprint; invalidate on drift | `semantic/glossary.py` + `autoseed.py` | M | ⭐⭐ kills cross-warehouse contamination | open |
| 7 | Require evidence-cited `business_model`; drop unsupported clauses | `profile/infer.py` | S | ⭐ removes hallucinated "subscription" | open |
| 8 | Direction-aware overlap in join guard (child⊂parent FK is valid) | `sql/join_guard.py` | S | ⭐⭐ stops blanking real subset joins | open |
