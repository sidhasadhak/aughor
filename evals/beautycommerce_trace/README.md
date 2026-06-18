# BeautyCommerce Intelligence Trace

A controlled experiment: run Aughor's onboarding/intelligence pipeline on a fresh, realistic
warehouse, **trace how an intelligent agent approaches the same schema cold**, and diff the two to
find what Aughor can learn. Branch: `2026-06-18-beautycommerce-intelligence-trace`.

## What's here

| File | What it is |
|---|---|
| [build_warehouse.py](build_warehouse.py) | Deterministic builder for a richer `analytics` BeautyCommerce warehouse (13 tables) with 6 baked-in patterns + 6 deliberate schema-reasoning traps. |
| [verify_patterns.py](verify_patterns.py) | Asserts the patterns/traps actually materialised. |
| [raw_profile.py](raw_profile.py) | The raw schema profile (no LLM/glossary) — what an analyst pulls on first contact. |
| [explore.py](explore.py) | The cold-trace exploratory battery: each metric run **correct vs trap** side-by-side. |
| [run_pipeline.py](run_pipeline.py) | Runs Aughor's REAL pipeline live (autoseed glossary → `infer_business_profile`). |
| [diagnose_blanks.py](diagnose_blanks.py) | Root-cause: feeds correct SQL through Aughor's own audit to localise why metrics/questions came back empty. |
| **[01_cold_trace.md](01_cold_trace.md)** | **The trace** — my sequential, grain-first approach, with the "moves an automated pipeline should replicate." |
| **[02_diff_learnings.md](02_diff_learnings.md)** | **The payoff** — scorecard + 7 root-caused findings mapped to modules, prioritized. |
| `evidence/` | All captured artifacts (raw profile, explore results, pipeline profile/glossary, stale-glossary proof, run log). |

## Reproduce

```bash
.venv/bin/python -m evals.beautycommerce_trace.build_warehouse   # build the warehouse
.venv/bin/python -m evals.beautycommerce_trace.verify_patterns   # confirm patterns/traps
.venv/bin/python -m evals.beautycommerce_trace.raw_profile       # raw schema profile
.venv/bin/python -m evals.beautycommerce_trace.explore           # cold-trace queries
.venv/bin/python -m evals.beautycommerce_trace.run_pipeline      # Aughor's live pipeline (~7 min, LLM)
.venv/bin/python -m evals.beautycommerce_trace.diagnose_blanks   # root-cause the blanks
```
The connection `BeautyCommerce-Analytics` (`8090c60f`) is registered against
`data/beautycommerce_analytics.duckdb`, schema `analytics`.

## The one-line takeaway

Aughor gets the **framing** right (industry, metric names, and a glossary that independently nailed
payment-retry grain and attribution-weight normalization) but the **execution** layer drops 12 of 16
build-time SQLs — all of which are trivially answerable (they pass Aughor's *own* audit when written
correctly). The knowledge is captured; it just isn't propagated to where the SQL is generated.
**Biggest wins:** a deterministic recipe-driven SQL fallback (F1) and a join-key cardinality probe that
stops the fan-out guard from blanking correct weighted-attribution metrics (F2). See
[02_diff_learnings.md](02_diff_learnings.md).
