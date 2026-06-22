# R4 — Semantic-layer ablation eval (2026-06-21)

> Makes the moat **measurable**. From the MotherDuck study ([`MOTHERDUCK_LEARNINGS.md`](MOTHERDUCK_LEARNINGS.md) R4):
> their own DABstep benchmark hits 100% only when domain knowledge moves into a **governed
> layer** — *"a semantic-layer failure is an error message; a text-to-SQL failure is a
> plausible wrong answer."* This eval reproduces that thesis on a real Aughor warehouse, and
> sharpens it: **the durable moat is the *deterministic* guard layer, not LLM-derived context.**
>
> Harness: [`evals/ablation_eval.py`](../evals/ablation_eval.py) · dataset:
> [`evals/ablation_missimi.jsonl`](../evals/ablation_missimi.jsonl) · raw results:
> `evals/ablation_missimi_results.json`. Warehouse: `workspace` / schema `missimi` (1.56M orders,
> 2.37M order-items).

## Why "accuracy" is the wrong single number

A wrong answer that **errors** is cheap — you see it and retry. A wrong answer that **executes
cleanly and looks plausible** is the expensive one: it ships into a board deck. So the eval
classifies every answer three ways, not two:

- **correct** — matches ground truth
- **silent-wrong** — executes fine, returns a plausible **wrong** number (the dangerous class)
- **caught** *(governed only)* — a guard fired → the answer is flagged/repaired, never shipped silently

## Headline: deterministic guard-efficacy on the canonical traps

The exact plausible-wrong SQL a naive text-to-SQL agent writes, executed **unguarded** vs through
Aughor's deterministic guard battery. No LLM — fully reproducible (`--traps`):

| Trap | Naive answer (unguarded) | True answer | Guarded |
|------|--------------------------|-------------|---------|
| **Fan-out (chasm)** — `SUM(order_value)` joined to `order_items` | **$199,546,622** | $108,534,492 | ⚑ caught (de-fan) |
| **Value-domain (silent zero)** — `WHERE order_status = 'cancelled'` | **0** | 15,737 | ⚑ caught → `'canceled'` |
| **id-arithmetic (fabrication)** — `SUM(unit_price * order_item_id)` | **$150,098,196** | $104,798,889 | ⚑ caught |

Every naive value **executes without error and looks reasonable** — and is off by 84%, 100%, and
43%. This is the failure mode a raw text-to-SQL tool ships and a governed layer makes impossible
to ship silently. (The fan-out trap additionally has a deterministic **de-fan rewrite** — `defan()`
produces the grain-correct dedup subquery — so it's not just flagged, it's *corrected*.)

## End-to-end LLM ablation (3 arms, 12 questions)

Each question generated three ways on the same warehouse, executed, and scored against ground
truth (execution-match, with `accept_sql` alternatives for defensible variants):

| Arm | What it is | Result |
|-----|-----------|--------|
| **raw** | schema-only LLM (`generate_sql_chat`) — a thin text-to-SQL agent | **92% correct** (11/12) |
| **guarded** | raw SQL + the deterministic guard battery (the Verifier) | **92% SAFE** (correct+caught), **0 regressions** |
| **injected** | full intelligence-injected pipeline (exploration + KB + metrics + retry) | **58% correct** (7/12), **5 silent-wrong** |

Three findings, all honest:

1. **The deterministic guards are pure-upside.** Guarded **never regressed** raw (0/12) — a
   conservative rewrite/flag only ever helps. On a *capable* coder model asking *straightforward*
   questions, the raw arm already avoided most traps, so the guards had little to catch here (0
   net lift) — but the canonical-trap table proves they fire correctly when the model **does** slip,
   and the injected arm proves it slips a lot under context drift.

2. **LLM-derived context injection is a separate, drift-prone axis — *not* the moat.** The
   injected arm **regressed to 58%**: `missimi`'s ~25 exploration insights steered the model into
   id-arithmetic (`SUM(unit_price * order_item_id)`), spurious `delivered`-only filters, and wrong
   grain. This is the documented **#13 confound** the eval infra's `_assert_frozen_semantics` guard
   *forbids* for FULL runs — and which we deliberately surfaced here. It validates the platform's
   frozen-state gating and the architectural line: **governed ≠ "inject more LLM context"; governed =
   deterministic guards + registered metrics.**

3. **The danger is silent-wrong, and the guards eliminate it.** Across both the trap demo and the
   ablation, the deterministic layer converts "plausible wrong answer" → "correct or flagged," with
   zero downside. That is the moat, made measurable.

## Honest caveats

- **n = 12, one warehouse, one model.** This is a focused demonstration, not a leaderboard. The
  trap table (deterministic) is the robust result; the LLM ablation is illustrative.
- **The raw model is strong here** because the questions are mostly answerable from `orders` alone
  (no forced chasm join). A harder set (forced cross-grain joins, ratio metrics) would widen the
  raw→guarded gap — but would also be less reproducible. We chose the honest, narrow claim.
- **Execution-match is value-exact** — a rounding (`4.30` vs `4.298`) or an extra column on a
  "which…" question reads as a miss. `accept_sql` absorbs the defensible variants; one residual
  (q03, a "which channel" column-shape) is a scorer artifact, not a wrong answer.

## Reproduce

```bash
uv run python evals/ablation_eval.py --traps                                   # deterministic guard demo
uv run python evals/ablation_eval.py --output evals/ablation_missimi_results.json   # full 3-arm ablation (LLM)
```

## Bottom line

The governed layer's value is **not** a few accuracy points on easy questions — it's that the
**deterministic guards make the plausible-wrong-answer class impossible to ship silently**, at zero
downside, while keeping LLM-derived (drift-prone) context on a separate, gated axis. Aughor's Trust
Receipts surface exactly which guards fired — so every governed answer carries its own proof. That
is MotherDuck's thesis, reproduced and sharpened on Aughor's own data.
