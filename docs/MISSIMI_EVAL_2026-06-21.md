# Missimi quality eval — 2026-06-21

A first-wave quality eval (Option B: **15 Insight + 15 Deep Analysis**, 30 real pipeline runs
on the `missimi` canvas) to assess answer quality — text, SQL, charts, routing — and surface
sharp, prioritized improvements. Run via the real `/chat` (Insight) and `/investigate` (Deep)
SSE endpoints. Raw per-run capture: [`missimi_eval_2026-06-21_results.jsonl`](missimi_eval_2026-06-21_results.jsonl);
harness: [`missimi_eval_2026-06-21_harness.py`](missimi_eval_2026-06-21_harness.py).

Outcome: **30/30 completed (1 client-timeout).** The session's fixes all held; 30 runs surfaced
**3 critical defects + 1 false-conclusion bug** with clear root causes. Verdict: fix the
criticals, then run the full 50+50 as a regression — don't scale yet.

## Held up ✅ (regressions from this session's fixes — all clean)
- AOV-by-payment-type reads "nearly uniform… spread of 0.10" — no false concentration (Q2, Q20).
- AOV-by-status renders + correct ("$70.82 vs $69.35", Q3).
- Freight-% cross-section reproduces Germany 2.17% lowest (Q12, ratio-of-sums).
- ROAS NULL handling (Q8), review distribution (Q10), order counts (Q13), country revenue (Q11).
- Honest failure (Q28): refused to answer ("blocked by missing product–warehouse schema link")
  instead of fabricating — the right failure mode; keep it.

## 🔴 Critical — wrong numbers shipped at confidence
1. **Fabricated revenue formula** (Q5, top products). Generated SQL `SUM(unit_price * order_item_id)`
   — multiplies price by the row's PRIMARY KEY. `missimi.order_items` has no quantity column
   (cols: order_id, order_item_id, product_id, brand_id, category, unit_price, unit_cost), so
   correct revenue = `SUM(unit_price)` ≈ €104.8M; the bug produced €150M and garbage per-product
   (P000545 "€36M"). An invented id-as-quantity that passed every guard.
2. **Headline ≠ query result** (Q6, repeat rate). Result row = **28.62%**; headline asserted
   "Overall repeat purchase rate is **42.3%**." A fabricated number in the lede. The deep/ADA path
   has share-grounding; the `/chat` headline does not.
3. **Cross-schema leak in `explore`** (Q19, Q21, Q25). missimi is beauty (`makeup_lips`,
   `skincare_face` — Q4), yet these deep analyses returned *Apparel/Office/Electronics 40% margin*,
   *"Mechanical Keyboard Basic / Coffee Maker Basic"*, and *"$0.00 LTV / only 500 ecom[merce] rows"*
   — a different demo schema. 3 of 5 `explore`-routed runs leaked; `investigate`-mode runs stayed
   scoped. The leak is specific to the explore decomposition path.

## 🟠 High
4. **`'cancelled'` vs `'canceled'` → a *false* conclusion** (Q29). Deep concluded "cancellation rate
   is zero across all dimensions; no driver found" — but there are **15,737** canceled orders (Q13).
   The misspelled literal (`WHERE order_status = 'cancelled'` → 0 rows) reports "you have no
   cancellations." Same root cause in Q4/Q6 (`!= 'cancelled'` fails to exclude). Worse than a filter
   slip — it ships "nothing here" when there is.
5. **Currency ignored in chat prose.** Org currency = EUR (Missimi / Berlin), but every Insight/Deep
   lede used `$` or no symbol (`$107.42M`, `$378.49`, `42983921.35`). The override reaches tables /
   charts / briefing but not the LLM answer prose.
6. **Insight vs Deep disagree on the same metric.** Freight-%: Insight 4.34% / DE 2.17% (matches
   ground truth, Q12) vs Deep 3.0% / DE 1.48% (Q23). Deep re-derives instead of reusing the
   ratio-of-sums recipe.

## 🟡 Medium
7. **Latency.** Deep 200–450s; Q24 hit the 360s client timeout. `explore` is slowest *and* owns the
   leaks. (Memory note: `score_evidence` runs serially — a parallelization win.)
8. **Time-series narrative anchors on the oldest year** (Q15, inventory turnover leads with 2022
   despite 2025 data) — the insight-path analog of the briefing trend-window bug already fixed.
9. **Weak / degenerate deep conclusions.** Q30 "drivers undetermined"; Q25 "$0.00" LTV (leaked +
   degenerate). A grain caveat also false-fired on a ratio-of-sums margin (Q4).

## Recommendations (root-cause, prioritized)
1. **Block arithmetic on id/key columns** in the SQL grounding gate (AST: `<measure> * <*_id|PK>`,
   aggregates over id columns) → kills #1, the worst class. Tie into the Phase-8 grounding/fan-out guards.
2. **Extend the "no number not in the result" gate to the `/chat` headline** (ADA already has share-grounding) → #2.
3. **Pin the `explore`/deep search_path to the canvas schema** (Insight already is) → #3.
4. **Repair `cancelled→canceled` (value-domain guard) on `!=`/`NOT IN`, not just `=`/`IN`** → #4.
5. **Thread the effective currency symbol into the chat narrator** + a `$`→symbol post-pass (reuse the briefing's `_cur()`) → #5.
6. **Make Deep reuse the ratio-of-sums recipe** via the existing `_metric_is_ratio` gate instead of re-deriving → #6.

## Scale-to-50 verdict
**Don't run the full 50+50 yet.** 30 runs gave high signal — 3 critical + 1 false-conclusion bug,
all with clear root causes. Sequence: **fix #1–#4 → run the full 50+50 as a regression** to confirm
closure and catch the long tail. Another 50 now would mostly reconfirm the same patterns at more cost.
