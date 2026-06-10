# Full-pipeline eval — what it can and can't measure (#13)

Ran `evals/run_golden.py` (53 golden NL2SQL cases, cloud `qwen3-coder-next`) in RAW
(schema-only) and FULL (intelligence-injected) modes. The full-pipeline mode already
existed; the task was to run it and record the lift. The honest answer required two
rounds of digging — and overturned the surface reading twice.

## The numbers (this run, `workspace` connection)

| Mode | Perfect | Pass (≥0.80) | Errors |
|------|---------|--------------|--------|
| RAW  | 10 (19%) | 25 (47%) | 2 |
| FULL | 9 (17%) | 19 (36%) | 0 |

FULL looks worse — but this run is **confounded**; do not read it as a capability
regression. (A prior run on the `samples` connection, 2026-06-07, had FULL *beating*
RAW at 26%/56% vs 20%/50% — see [[eval-golden-baseline]].)

## Why this run is confounded (three independent causes)

1. **Connection-specific semantic state.** I ran on `workspace` because `samples`
   isn't in the connection list. 10 of 12 regressions are one cause: FULL computes
   revenue as `SUM(order_items.line_total)` / `qty*unit_price`, excluding cancelled/
   refunded, whereas the golden references use `SUM(orders.total_amount)`. This is
   NOT from `metrics.json` (empty on both connections) — it's the injected
   exploration/ontology/Data-Catalog context steering the model toward `order_items`.
   `workspace` was explored (≈25 insights); `samples` was not, so the injected
   context — and therefore the result — differs by connection state.

2. **The sample dataset is internally inconsistent.** `orders.total_amount` = 1.29M
   but `SUM(order_items.line_total)` = 5.58M (4.3×). So the two revenue definitions
   genuinely disagree on this data; the golden references happened to pick
   `total_amount`. Neither SQL is "wrong" — the scorer just can't tell.

3. **LLM run-to-run noise ±2–4 questions** (documented in [[eval-golden-baseline]]:
   sql014 swung 1.00→0.30→1.00 on unchanged code). A single A/B is within noise for
   small deltas; the 6-case gap here is mostly cause #1, not signal.

## What IS solid

- Excluding the 10 metric-divergence cases, FULL is **net +4 on real capability**
  (+6 genuine gains — customer count, country ranking, cancelled-vs-delivered,
  status distribution, pending-order aging, slow-delivery rating; −2 genuine
  regressions — sql044, sql049). Errors went 2 → 0 (retry/fix works).
- The harness now mirrors the production de-fan (`defan()`), so the eval reflects
  this session's fan-out correctness work.

## Conclusion / next levers

The full-pipeline eval, as-is, **cannot reliably measure capability lift** — the
result is dominated by which revenue definition the injected context steers toward
(connection-state-dependent, not pinned) plus LLM noise. To make it trustworthy:

1. **Pin the eval connection + its semantic state** (restore/register `samples`;
   freeze its metrics/ontology) so runs are comparable.
2. **Metric-aware scoring** — accept a result that matches any registered canonical
   metric definition, not just the golden's one spelling of revenue.
3. **Noise control** — coder at temperature 0 (or average N runs) so small lever
   deltas are measurable.

Do (1)–(3) before drawing capability conclusions or chasing micro-levers. This is
the metric-unification problem, made measurable: the semantic layer must agree with
ground truth, and the eval must be metric-aligned and noise-controlled.
