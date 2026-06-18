# Cold Trace — approaching BeautyCommerce as the intelligence

**Connection:** `BeautyCommerce-Analytics` (`8090c60f`) → `data/beautycommerce_analytics.duckdb`, schema `analytics`, 13 tables.
**Rule for this trace:** I work from the **raw** schema only — table/column names, types, row counts, value
distributions (`evidence/raw_profile.txt`). No LLM glossary, no curated KB. The point is to record the *sequence
of moves* a careful analyst makes on first contact, so we can ask which of them Aughor's pipeline makes too.

Each move is labelled **[M#]** and carries a one-line *why*. The moves are the unit the diff measures.

---

## Step 0 — First contact: inventory the surface

**[M0] Count tables and rows before reading any column.** The shape tells me the domain before any single
column does.

```
attribution 6,930 | campaigns 16 | carts 9,000 | customers 800 | inventory_movements 8,000
inventory_snapshots 5,400 | invoices 4,620 | marketing_ledger 1,460 | order_items 16,000
orders 4,620 | payments 4,991 | products 150 | refunds 463
```

*Reading:* `orders`/`order_items`/`products`/`customers` = a transactional retail core. `carts` (2× orders) =
a funnel with abandonment. `refunds`, `payments`, `invoices` = a money/fulfilment spine. `marketing_ledger`,
`campaigns`, `attribution` = paid acquisition. `inventory_*` = supply. That's already a **DTC e-commerce**
shape — and the presence of `carts` + `attribution` + `refunds` says this is a *funnel-and-margin* business,
not a pure catalog. I have a hypothesis before reading a single value.

## Step 1 — Grain & the join graph (the load-bearing step)

**[M1] State the grain of every table in one sentence.** Everything downstream (which SUM is safe, which rate
needs which denominator) depends on this.

| table | grain (one row = …) | key signal |
|---|---|---|
| products | one SKU | `product_id` unique, 150 |
| customers | one customer | `customer_id` unique, 800 |
| carts | one shopping cart | `cart_id` unique, 9,000 |
| orders | one placed order | `order_id` unique; `cart_id` also unique → **1:1 cart↔order** |
| order_items | **one line item** (order × SKU) | `order_id` repeats; 16,000 rows / 4,620 orders |
| invoices | one order | `order_id` unique → **1:1 with orders** |
| payments | one payment **attempt** | `order_id` repeats (4,991 / 4,620) → retries exist |
| refunds | one refunded order | `order_id` unique, 463 |
| attribution | one order × touchpoint | `order_id` repeats (6,930 / 4,620) → multi-touch |
| marketing_ledger | one channel × day | `channel`+`spend_date` |
| inventory_snapshots | one SKU × warehouse × month | 150×3×12 |
| inventory_movements | one stock movement | `movement_id` unique |

**[M2] The grain immediately flags three over-counting hazards** before I write a metric:
- `order_items` is **1→N** under `orders` (avg 3.46 lines/order). *Any* order-level money summed across an
  items join inflates. → **fan-out hazard.**
- `payments` is **1→N** under `orders` (retries). "Success rate" depends on whether I count attempts or orders.
- `attribution` is **1→N** under `orders` (weights). Channel revenue depends on the attribution model.

**[M3] Verify the join graph with orphan checks rather than trusting names.** (`evidence/explore_results.txt` A1–A3)
```
order_items → orders : 0 orphans     order_items → products : 0 orphans
carts(9,000) → not_abandoned(4,620) = orders(4,620) = distinct cart_id on orders(4,620)   [clean 1:1]
rows-per-order: order_items 3.46 | payments 1.08 | invoices 1.0 | refunds 1.0 | attribution 1.5
```
Referential integrity is clean, and the 1→N fan-outs are now *quantified*, not assumed.

**[M4] Distrust the cheap PK heuristic.** "distinct == rowcount" alone flagged `campaigns.start_date`,
`campaigns.budget_usd`, `marketing_ledger.impressions`, and `products.launch_date` as PK candidates — all
false positives from small tables or coincidentally-unique numerics. A real key needs **name + type +
uniqueness + non-null**, not uniqueness alone. (Noted because automated profilers lean on this heuristic.)

## Step 2 — Value distributions & NULL semantics

**[M5] Read the categorical domains — they name the business levers.**
- `orders.channel` / `carts.traffic_source` / `customers.acquisition_channel` ∈ {TikTok, Meta, Google, Email,
  Organic, Direct/Referral} → paid + organic acquisition.
- `customers.loyalty_tier` ∈ {Bronze, Silver, Gold, Platinum} → loyalty program.
- `products.category` ∈ {Skincare, Makeup, Haircare, Fragrance, Tools} → **beauty/cosmetics**, confirmed.
- `refunds.refund_reason` ∈ {Allergic reaction, Scent too strong, Shade mismatch, Damaged in transit, Late
  delivery, Wrong item, Changed mind} + `logistics_related` bool → returns split **product-fit vs logistics**.
- `payments.payment_method` ∈ {card, apple_pay, paypal, klarna}; `success`, `attempt_no`, `fraud_flag`.

**[M6] Distinguish *structural* NULL from *noise* NULL — they are not the same and must not be treated alike.**
- `products.shade` is 80% NULL — but the NULL is **structural**: shade is populated for Makeup and NULL for
  every other category (verified: Makeup 0% null, all others 100%). NULL here *encodes* "not a shade product."
  It is signal.
- `products.gift_message` is 95% NULL and `customers.middle_name` is 100% NULL (and accidentally typed INTEGER) —
  these are **noise**: no information, should never be surfaced as a finding or a dimension.

  *This distinction is a move an automated pipeline frequently misses — it either suppresses both (losing the
  shade segmentation) or surfaces both (a "95% of gift_message is null!" non-insight).*

**[M7] Spot the redundant denormalization.** `order_items.traffic_source` duplicates `orders.channel`. Harmless,
but I note it so I don't treat it as an independent dimension.

**[M8] Spot the silent cohort.** `orders.customer_id` has 504 distinct of 800 customers → **~37% of customers
never placed an order.** That's a non-buyer cohort worth a retention question, surfaced purely from a
distinct-count gap.

## Step 3 — Business-model inference

**[M9] Name the vertical specifically, and cite the columns that prove it.**
> **DTC Beauty E-commerce**, transactional retail with a paid-acquisition funnel and a returns/logistics tail.
> Evidence: `products.category`∈beauty taxonomy + `shade`/`skin_type`/`is_organic`; `carts.abandoned` +
> `attribution.weight` (funnel + multi-touch paid acquisition); `refunds.refund_reason` split between
> product-fit (allergic/shade) and logistics (damaged/late); `order_items.unit_cogs_usd` present → **margin is
> computable**, which is the whole game for DTC beauty.

The COGS column is the tell. A catalog that ships COGS at line grain is telling me *gross margin* is the
intended north star — so I should lead with margin, not vanity revenue.

## Step 4 — Metric proposal (grounded + grain-correct *by construction*)

Each metric names real columns and the grain that keeps it honest. The **trap** column is the naive SQL I
explicitly refuse to write.

| metric | grain-correct definition | trap I avoid |
|---|---|---|
| **Gross margin %** | `SUM(line_revenue−line_cogs)/SUM(line_revenue)` at **item grain** | summing order-level revenue across an items join (T1 fan-out → 3.5× overcount) |
| **Cart→order conversion** | `orders / ALL carts`, by `traffic_source` | denominator = non-abandoned carts → **100%** (T2) |
| **AOV** | `revenue / COUNT(DISTINCT order_id)` at order grain | dividing by item rows |
| **Refund rate** | refunded orders / all orders (order grain) | counting refund *rows* against item rows |
| **Payment success** | orders with ≥1 successful attempt / orders | success **attempts** / attempts (T5) |
| **ROAS by channel** | `SUM(rev × attribution.weight) / spend` | last-touch only credits one channel (T4) |
| **Inventory turnover / stockouts** | movements `outbound` vs snapshot `stock_level=0` | averaging snapshots as a flow |

## Step 5 — Exploratory queries → the domain intelligence

I run each metric *and its trap* so the difference is visible (full output in `evidence/explore_results.txt`).
The findings:

1. **Conversion is a TikTok problem (T2).** Email 68% → Direct 62 → Organic 58 → Google 52 → Meta 46 →
   **TikTok 22%**. The trap version reports 100% for every source — a number that should never survive a sniff
   test, because *a bounded rate that pins to its boundary is almost always a denominator bug.*

2. **Fragrance is a margin leak (T3 — the cross-domain catch).** Fragrance has the **highest** gross margin
   (92.2%) **and** the **highest** refund rate (20.2% vs 5–10% elsewhere). Either number alone is a "good news"
   or "bad news" headline; only the **AND across margin and returns** reveals that the most profitable category
   is also the one bleeding the most returns. This is the question the data is built to reward.

3. **Acquisition efficiency inverts the spend (P6/T4).** Spend: TikTok \$381k ≫ Email \$82k. Return: **Email
   ROAS 7.1× (9.95× weighted), TikTok 0.45× (0.36× weighted).** The biggest budget is the worst performer; the
   cheapest channel is the best. And the attribution model *moves the verdict* — Email looks even better, Google
   worse, under weighted vs last-touch.

4. **Refund root-cause splits by warehouse (P3).** Logistics-related share: **Riverside 56% → Hillcrest 50 →
   Bayview 33 → Lakeside 0%.** Returns aren't one problem — Riverside has a fulfilment problem; Fragrance has a
   product-fit problem. Different owners, different fixes.

5. **Payment success is a klarna/grain story (T5).** Per-attempt: klarna 79%, card 95%. Per-order (any
   successful attempt): klarna 95%, paypal/apple_pay 100%. The retry mechanism *recovers* most klarna failures —
   so the per-attempt number overstates the customer-facing problem.

6. **Loyalty earns its keep (P1).** AOV: Platinum \$693 / Gold \$683 ≫ Silver \$504 / Bronze \$510. The top two
   tiers (≈16% of orders) carry a ~35% higher basket.

7. **Inventory is mis-balanced.** Tools sit at avg stock 494 (slow-mover overstock) while Haircare hero SKUs
   hit **180 stockout snapshots** at level 0. Capital is parked in the wrong category.

## Step 6 — Synthesis (the one-paragraph brief)

> BeautyCommerce is a DTC beauty retailer whose economics are dominated by **Fragrance margin** and undermined
> by **Fragrance returns** — the single most important finding is that its best-margin category is its worst-
> returns category (92% margin, 20% refunds), so margin-protection means a returns fix, not a pricing change.
> Acquisition spend is **inverted**: TikTok absorbs the largest budget at 0.4× ROAS while Email returns ~7–10×;
> reallocation is the obvious lever. Returns have **two distinct root causes** — product-fit (Fragrance) and
> logistics (Riverside warehouse, 56% logistics-related) — that need different owners. Conversion is healthy
> except TikTok (22%), payment friction is mostly klarna-and-recoverable, loyalty tiers pay off, and working
> capital is stranded in Tools inventory while Haircare hero SKUs stock out.

---

## The "moves" an automated pipeline should replicate

These are the transferable behaviours — the checklist the diff scores Aughor against:

- **[M1/M2] Grain-first.** Declare every table's grain and *derive the fan-out hazards from it* before writing
  any metric. The fan-out/retry/multi-touch traps are all predicted by grain alone.
- **[M3] Verify joins by probing (orphans, rows-per-key), not by name-matching.**
- **[M4] Don't trust uniqueness alone for keys.** Use name+type+uniqueness+non-null.
- **[M6] Classify every high-NULL column as structural vs noise.** Keep `shade`, drop `gift_message`.
- **[M8] Mine distinct-count gaps for cohorts** (the 37% non-buyers fell out of one `COUNT(DISTINCT)`).
- **[Step 4] Carry the trap with the metric.** A metric definition that doesn't name the wrong-grain version it
  avoids is under-specified — bounded rates need their denominator pinned, money needs its grain pinned.
- **[Step 5, finding 2] Cross-domain AND.** The highest-value finding required combining *margin* (items) with
  *returns* (orders) — a single-table angle never finds it. The pipeline must be willing to join two domains for
  one insight.
- **[Step 5, finding 3] Attribution model is a first-class choice**, not a detail — it changes the channel
  verdict, so it must be stated, not defaulted silently.
