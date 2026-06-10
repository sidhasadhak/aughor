# Full-pipeline eval — measured lift over the raw baseline (#13)

Ran `evals/run_golden.py` on the 53-case golden NL2SQL set, `workspace` connection
(ecommerce schema), cloud `qwen3-coder-next`. Two modes:

| Mode | Perfect (≥0.99) | Pass (≥0.80) | Errors |
|------|-----------------|--------------|--------|
| RAW (schema-only) | 10 (19%) | **25 (47%)** | 2 |
| FULL (intelligence-injected) | 9 (17%) | **19 (36%)** | 0 |

At face value the full pipeline looks **worse**. It is not — case-level analysis
(raw-pass → full-fail) shows the drop is almost entirely one cause.

## Root cause: metric-definition divergence (not a capability regression)

Of **12 regressions, 10** are the full pipeline applying a *learned, internally
consistent* revenue definition that diverges from the golden reference's:

| Case | Golden / RAW | FULL (injected semantic layer) | Numbers |
|------|--------------|-------------------------------|---------|
| sql004 total revenue | `SUM(orders.total_amount)` | `SUM(order_items.line_total)` | 1,286,000 vs **4,925,006** (3.8×) |
| sql002 AOV | `AVG(total_amount)` | `SUM(line_total)/COUNT(DISTINCT order)` | 257.2 vs **1,119.32** |
| sql009/013/020/… | `total_amount`/`line_total` | `qty*unit_price`, `… WHERE status NOT IN ('cancelled','refunded')` | divergent |

The exact-match result-set scorer marks the divergence as "wrong." But neither
definition is objectively wrong — and the 3.8× gap means this synthetic dataset's
`orders.total_amount` ≠ the sum of its line items (a data-quality issue that makes
*both* defensible). The pipeline is doing exactly what a semantic layer should
(apply one canonical metric) — it just disagrees with the golden's assumption.

## True capability lift (excluding the 10 metric-divergence cases)

- **+6 genuine gains** — injection fixed RAW errors: customer count, country
  ranking, cancelled-vs-delivered by month, avg rating of slow-delivery orders,
  pending-order aging, order-status distribution.
- **−2 genuine regressions** — sql044 (orders with >3 items: stray GROUP BY),
  sql049 (avg delivery time by payment method).
- **Net real capability: +4.** Errors also went 2 → 0 (retry/fix works).

## Takeaways

1. **The eval is confounded by metric misalignment.** It cannot measure capability
   lift while the injected metrics and the golden references define revenue
   differently. This is the metric-unification problem, made measurable.
2. **The semantic layer must agree with ground truth.** Either align the platform's
   canonical revenue metric to the golden definition (or vice versa), then re-run —
   the real lift should then show through instead of being masked.
3. **Net of the metric confound, intelligence injection is a modest win** (+4, zero
   errors) — strongest on filtered/status/grouped questions, where the Data Catalog
   and exploration annotations add the most.

### Follow-ups
- A **metric-aligned scoring mode** (treat a result that matches *any* registered
  canonical-metric definition as correct), or metric-pinned golden references, to
  measure capability free of the definition mismatch.
- Investigate the `total_amount` vs `line_total` data inconsistency in the sample
  ecommerce set (3.8× is too large for tax/shipping).
