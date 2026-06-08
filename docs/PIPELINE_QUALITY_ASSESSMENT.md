# Aughor Intelligence — Full-Pipeline Quality Assessment

*2026-06-08. Reading the actual outputs, light → heavy, across all connections. The question
this answers: does the system produce intelligence a user can trust and act on?*

## Method
- **13 light Insight (/chat) cases** across all 5 connections (beautycommerce, tpch, tpcds,
  clickbench, bakehouse) — read SQL, data, headline, narrative, chart, columns.
- **3 heavy Deep-Analysis cases** on beautycommerce (fastest backend), one per routing shape:
  - cross-sectional diagnostic — "Where are we losing money?" (ADA, 3 phases)
  - temporal-causal — "Why did revenue change recently?" (ADA, baseline→synthesis)
  - decision/decomposition — "Which channels drive value & where to invest?" (explore, 7 sub-Qs)

## Headline verdict
**The reasoning is more advanced than the delivery.** Decomposition and intellectual honesty
are genuinely SOTA. What undermines trust is the *last mile*: ungrounded headline numbers,
brittle SQL in the deep path, no charts on the strongest analysis path, two inconsistent report
shapes, and 8–15-minute latency. **None of the core gaps are about model intelligence — they're
grounding, delivery, and self-repair.**

---

## Stage-by-stage

### 1. Intent detection & routing — GOOD
Three questions routed to three correct strategies: diagnostic→cross-section scan,
temporal→baseline/anomaly, open decision→multi-step decomposition. Intent labels are sensible
(`metric`, `observation_period`, `comparison_basis`). No misroutes observed.

### 2. Decomposition — EXCELLENT (the standout)
"Which channels drive value & where to invest" decomposed into **7 dependency-aware,
purpose-labeled sub-questions**: `landscape → relationship → confounder → threshold →
confounder → drill_down → synthesis`, with explicit `depends_on`.
- **Self-correcting:** when the ROAS join returned 0 rows (Q2), it didn't quit — it spawned Q3
  to diagnose *why*, discovered **0 of 5,000 campaigns overlap PnL date ranges**, and adapted.
  That is hypothesis-driven investigation, not template-filling.
- Every sub-question carries its own answer + insight + SQL (traceable).
This is the best part of the system and a real differentiator.

### 3. Analysis & SQL grounding — MIXED (deep path is brittle)
- **Insight path is well-grounded:** "revenue by month" correctly joined `invoices→orders`
  for `o.order_ts`. Revenue = `SUM(price*qty)`, AOV = `SUM/COUNT(DISTINCT)`. No fan-out.
- **Deep-Analysis path is *less* grounded:** the ADA baseline for the *same* metric
  hallucinated `analytics.invoices.order_ts` (doesn't exist) → binder error → **0 rows → no
  answer.** The light path gets this right; the heavy path doesn't.
- **No self-repair:** the binder error literally named the right candidate (`order_id`); a
  fix-loop could have joined to `orders` and recovered. It didn't. Missing-column errors aren't
  being repaired.
- **ADA intake builds fan-out metrics:** "losing money" produced -$3.1B/dimension (global
  subquery × fan-out join), bypassing the validator. (See quality_sweep_findings.md.)
- **Missed an absolute red flag:** the channel report ranked proxy-ROAS ≈0.88–0.93 and said
  "invest more in YouTube" — without flagging that **ROAS < 1 means every channel loses money**.
  Relative ranking computed; the decisive absolute insight skipped.

### 4. Report structure & delivery — GOOD content, INCONSISTENT shape
- ADA report: `headline · executive_summary · phases[findings] · attribution_waterfall ·
  recommendations · confidence`.
- Explore report: `headline · conclusion · narrative · recommended_actions · data_quality_notes`.
- **Two different report schemas depending on routing** — a user gets a different-shaped
  deliverable for structurally similar questions. Should converge on one report contract.
- Where it answers, structure is adequate: the channel report's headline honestly states *"true
  revenue-based value cannot be determined because no campaigns overlap with PnL records,"* with
  5 recommended actions and 3 data-quality notes. That's a trustworthy deliverable.

### 5. Charts & visualization — RIGHT TYPES, WRONG LABELS, BIG GAPS
- ✅ Insight chart-type choice is mostly correct: `bar_horizontal` for rankings, `line`/`auto`
  for time series.
- 🔴 **The decomposition path emits NO charts at all.** 7 analytical tables + a rich narrative,
  zero visualizations. The system's *deepest* analysis is its *least* visual.
- ⚠ **Label/series mapping is weak:**
  - Opaque IDs as axis labels — "Top products" plots `product_id` ("PROD-00098203"); tpch/tpcds
    plot `customer_id`/`i_item_id` **even when a name column is present** (chart picks the first
    non-numeric = the ID, not the name).
  - Unformatted labels: months render `2025-05-01 00:00:00` (want "May 2025").
  - The cross-section dimension column was aliased generically `dimension_value` (fixed in #25).
- ⚠ **Wrong chart for the data shape in a few cases:**
  - 46 franchise bars in one horizontal chart (intent said "*top*" — no LIMIT).
  - Near-equal values (channels ≈$70.1–70.3M; regions ≈$45B) render as identical bars —
    visually useless; a delta-from-mean or share view is needed.
  - AOV → single number with empty narrative.
  - clickbench "hits per day" → date mis-parse collapsed all hits to **1970-01-01** (1 row);
    the line chart plots one meaningless point.

### 6. Accuracy — GENERALLY SOUND, with grounding leaks
- ✅ Insight SQL math correct across all connections (no product-of-aggregates).
- 🔴 **Headline ungrounding (2 of 13):** tpch region headline "AMERICA $1.62B" vs data EUROPE
  $45.8B; tpch AOV headline "$184,112.61" vs data $150,398.22. The headline pass isn't reading
  the result rows.
- 🔴 clickbench date parse bug (above).
- 🔴 ADA fan-out metric (above).

### 7. Honesty / reassurance — STRONG (the best trust signal)
- "Why did revenue change?" → **refused to invent an answer**, said "unknown" at LOW confidence,
  root-caused the missing column, gave a fix recommendation.
- Channel report flagged its own data-quality limitation and labeled ROAS as a *proxy*.
- Cross-section was honest about non-concentration ("all within a $13K band").
This non-hallucination under failure is exactly what reassures users — it is the platform's
strongest asset and must be protected as features are added.

### 8. Latency — SEVERE (blocks heavy use)
Deep Analysis took **512s / 896s / 900s+ (timeouts)**; the 6-phase temporal path doesn't finish
in 15 min. At this latency the deepest intelligence is effectively unusable interactively, and
broad automated testing is impractical.
*(Ops note: API must run without uvicorn `--reload` during runs — open browser poll-connections
hang the reload and masquerade as a usage limit.)*

---

## Cross-cutting themes
1. **Grounding is the recurring failure mode.** #25 card titles, Insight headlines, ADA SQL
   columns, intake metrics — all are cases of a string/number/query not validated against the
   actual schema or rows. **One rule: every user-facing artifact must be derived from / checked
   against real data, never an independent LLM pass.**
2. **Insight = fast, robust, shallow; Deep Analysis = honest, structured, brittle, slow.** The
   target system fuses them: Insight's grounding + self-repair *inside* Deep Analysis's
   decomposition + honesty.
3. **The reasoning outruns the presentation.** Best-in-class decomposition is delivered with no
   charts, inconsistent report shapes, and ID-labeled axes.

## Prioritized recommendations
1. **Ground every headline/number in the result rows** (Insight headline + ADA). Cheapest, highest
   trust-per-effort. Kills the 2 ungrounded-headline bugs and the #25 class for good.
2. **Add a SQL self-repair loop** that reads binder/column errors and retries (join-to-source,
   use named candidate). Would have turned the "no answer" temporal run into a real answer.
3. **Route ADA intake metrics through the fan-out validator** (symmetric aggregates / PK-keyed)
   before ranking. Kills the -$3.1B class.
4. **Give the decomposition path charts**, and **converge ADA + explore on one report contract**
   (headline · key findings · evidence · actions · confidence · data-quality).
5. **Label/series intelligence:** prefer human-readable name columns over IDs for axes; format
   dates/numbers; cap top-N; switch to delta/share views when values cluster.
6. **Attack latency** (phase parallelism, fact-table caps, earlier streaming) — the deepest
   analysis must finish to be trusted.
7. **Visualization upgrades (the "interesting viz" ask):** Pareto for rankings, distribution +
   sparkline for scalars (AOV), choropleth for regions, MoM% overlay + partial-period annotation
   for time series, and a "these are within noise" treatment for near-equal categories.

**Bottom line:** the intelligence *core* (routing, decomposition, honesty) is already strong
enough to build trust on. The work to "reassure users of intelligence quality" is almost entirely
in the last mile — grounding, self-repair, consistent well-charted delivery, and speed.

---

## Implemented (2026-06-08) — fixes A–D, regression-locked (68 unit tests green)

| # | Fix | Where | Tests |
|---|---|---|---|
| **A** | **Headline grounding** — validate the coder's pre-execution headline against the actual rows; replace only on a genuine contradiction (wrong leader / phantom number; legitimate column sums & means are accepted). | `routers/investigations.py` `_ground_headline` | 4 (region & AOV bugs corrected; consistent + legitimate-total headlines untouched) |
| **B** | **Stronger SQL self-repair** — extract the binder error's missing column + candidate bindings and explicitly instruct a JOIN to the table that has it (the recovery the ADA baseline missed for `invoices.order_ts`). | `agent/investigate.py` `_missing_column_hint` (wired into `_execute_safe`) | 3 |
| **C** | **Unsafe-metric guard** — ADA intake rejects subquery-in-aggregate / product-of-aggregates (the −$3.1B class), retries once for a clean aggregate, else deterministically falls back to `SUM(<measure>)` and notes the adjustment. | `agent/investigate.py` `_unsafe_metric_sql` / `_safe_metric_fallback` (wired into `ada_intake`) | 3 |
| **D** | **Chart label intelligence** — category axis prefers a human-readable name column over an opaque id (`customer_name` not `customer_id`), falling back to the id only when no name exists. | `web/components/Chart.tsx` catCol selection | logic-verified vs real column sets |

**Verified live:** A — tpch region & AOV headlines no longer cite wrong leaders/numbers. D — name-over-id
confirmed against the real captured column sets. C — see fan-out re-run.

**Deferred (larger, scoped in recs 4–7):** charts on the decompose path + one unified report contract;
remaining label polish (date/number formatting, top-N cap, delta/share for clustered values); latency.
