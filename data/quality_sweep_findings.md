# Aughor Quality Sweep — Findings (2026-06-08)

Harness: `scripts/quality_sweep.py` (resumable, usage-paced, self-flagging).
Scope this wave: **13 Insight (/chat) cases across all 5 connections** + Deep Analysis
(beautycommerce cross-section captured in full; tpch/tpcds timed out — see latency finding).

## Verdict
**Insight mode is high quality. Deep Analysis is correct in structure (post-#25 fix) but
has two serious problems: a fan-out metric bug and prohibitive latency. The recurring theme
across modes is ungrounded presentation strings.**

---

## ✅ What's working (Insight / Quick mode)

Audited the generated SQL for all 13 cases. **Zero product-of-aggregates bugs.** Revenue is
always `SUM(per_row_value)`, AOV is always `SUM(...)/COUNT(DISTINCT ...)` — fan-out-safe.

| Connection | Sample | SQL quality |
|---|---|---|
| beautycommerce | Top products by revenue | `SUM(final_price_usd*quantity)` ✓ |
| beautycommerce | Average order value | `SUM(price*qty)/NULLIF(COUNT(DISTINCT order_id),0)` ✓ |
| tpch | Revenue by region | `SUM(o_totalprice)` over correct region join ✓ (data correct: EUROPE $45.8B…) |
| tpch | AOV | `SUM(o_totalprice)/COUNT(DISTINCT o_orderkey) WHERE status='F'` ✓ |
| tpcds | Top items / sales by store | `SUM(ss_ext_sales_price)` / `SUM(ss_net_paid_inc_tax)` ✓ |
| clickbench | Top pages / hits per day | `COUNT(*)` ✓ |
| bakehouse | Sales by franchise | `SUM(totalPrice)` over franchise join ✓ |

Hygiene is good: `NULLIF` guards, sensible filters (cancelled/test/fraud, organic/direct)
surfaced honestly in the headline.

---

## 🔴 Findings (ranked)

### 1. ADA intake synthesizes fan-out metrics → billions  (CRITICAL)
"Where are we losing money?" on beautycommerce produced **~-$3.1B per dimension, every
dimension at ~14.3% share** (mathematically a global-subquery/cross-join signature, not real
data). The intake built a net-profit metric = `SUM(gross_margin_usd - (global marketing-spend
subquery)/COUNT(DISTINCT order_id))` over a fan-out join. The simpler /chat path never does
this — so the bug is localized to **ADA intake metric synthesis**, and it **bypasses the
fan-out guard / self-validating semantic layer** (M24c) that was built to catch exactly this.
Confidence was correctly LOW, but the numbers are garbage.
→ Fix: route ADA intake metrics through the validator / symmetric-aggregate (PK-keyed) guard
before ranking; reject product-of-aggregates and global-subquery-in-SUM patterns.

### 2. Insight headline is ungrounded  (HIGH)
tpch "revenue by region": data and narrative are correct (EUROPE leads at $45.8B), but the
**headline says "AMERICA leading at $1.62B"** — wrong leader, and $1.62B appears nowhere.
The headline is generated in a pass that isn't grounded in the computed top row.
→ Fix: ground the headline in the actual result (top row / leader), or validate it against
the data before display. **Same root cause as #25** (see below).

### 3. No unified metric (semantic-layer gap)  (MEDIUM)
"revenue" = `order_items.final_price_usd*quantity` in one query but `invoices.revenue_net` in
another; tpcds "sales" = `ss_ext_sales_price` vs `ss_net_paid_inc_tax`. Same concept, different
source per question — answers aren't comparable across a session.
→ Fix: a canonical, approved metric the LLM augments rather than re-derives each time.

### 4. Deep Analysis latency is prohibitive  (HIGH, operational)
Runs took **512s, 896s, and timed out** (8–15+ min); tpch's 6M-row lineitem makes it worse.
At this latency Deep Analysis is effectively unusable and broad testing is impractical.
→ Investigate: phase parallelism, query caps on large facts, model/latency, streaming earlier.

### Operational note (not a product bug)
uvicorn `--reload` **hangs on the open browser's polling connections** ("Waiting for
connections to close"), which masqueraded as a usage limit and timed out every request. Run
the API **without `--reload`** during sweeps. (No quota was actually exhausted.)

---

## 🔑 The unifying root cause
Findings #1, #2, and the original #25 bugs are **one class**: a user-facing artifact
(headline / card title / chart series / metric) produced in a pass that **isn't grounded in
the actual computed rows**. The platform-wide rule:

> **Every user-facing string and number must be derived from / validated against the actual
> result rows — never emitted by a parallel ungrounded LLM pass.**

The #25 fix applied this to ADA card titles + charts. The same discipline should extend to
the Insight headline (#2) and to metric synthesis (#1, via the validator).

## Harness self-correction
`ASK_NOAVG` false-positived on AOV (SUM/COUNT *is* the correct average). Fixed to
`ASK_NOMEAN` (fires only when there's neither `AVG()` nor a ratio), and added a
`HEADLINE_CHECK` flag for finding #2's class.
