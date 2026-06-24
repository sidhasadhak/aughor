# Explorer Grounded Generation — eliminating column hallucination at the root

**Status:** design — branch `2026-06-23-explorer-synthesis`
**Date:** 2026-06-24

## The weakest link

Phase 8 generates SQL **free-form** from a text prompt. The schema is in the prompt,
but the LLM's prior overrides it and writes canonical ecommerce column names that
don't exist in the connection — measured on `missimi`: `line_total` invented 150+
times, plus `quantity`, `customer_id`, `product_cost`, and the wrong schema
`ecommerce.*`. The only defense is a **post-hoc** feasibility gate
(`unresolved_identifiers`) that discards the entire generation and retries — burning
**~40% of the token budget** on dead generations, every run. Prompt tweaks (dead-refs
avoid-list, recipe-binding) reduce but cannot eliminate it: a generator free to emit
any identifier will hallucinate against its prior. This is the non-SOTA core.

## Principle

**Never let the model free-write an identifier into SQL.** Ground generation in the
schema by construction (the schema-linking → structured-intent → deterministic-
compilation pattern). The model contributes *intelligence* (which cut to explore,
guided by frontier/playbook/drill); the *expression* in SQL is mechanical and
schema-bound.

## Design

Replace the free-form `_NextQuestion {question, sql, angle, why}` with a structured
spec the LLM fills by CHOOSING from enumerated real columns:

```
class _Probe:
    question: str               # plain English (free)
    angle: str
    why: str
    measures: list[str]         # chosen from the domain's REAL measure columns
    dimensions: list[str]       # chosen from the REAL dimension columns (0-2)
    filters: list[{column, op, value}]      # column ∈ real cols
    having: Optional[{measure, op, value}]  # composite threshold (the SKU margin-leak class)
    sort_desc: bool
```

Pipeline per probe:
1. **Schema-link** — build the domain's allowed `{measures, dimensions, filterables}`
   from column profiles (same source the frontier/manifest already use).
2. **Generate** — LLM fills `_Probe`, picking only from the enumerated lists.
3. **Validate** — set-membership of every column field against the real columns
   (≈0 cost). On a stray pick, ONE structured repair ("X not allowed; choose from
   [...]"), else drop the probe. No SQL ever reaches execution with an invented column.
4. **Compile** — `probe_to_sql(probe, profiles, joins)` deterministically:
   per-measure aggregate from profile metadata (SUM vs AVG via `_is_rate`), GROUP BY
   dims, WHERE filters, HAVING for composites, ratio = `SUM(num)/NULLIF(SUM(den),0)`,
   and grain-safe **pre-aggregate-per-table-CTE then JOIN** across the *verified* join
   graph (`state["join_verifications"]`) when fields span tables.
5. Hand the compiled SQL to the existing pipeline (dry_run, fan-out/grain guards,
   execute, interpret, ground, dedup) unchanged.

The existing free-form generator remains as a **bounded fallback** for probes the
compiler can't express (logged + capped), so expressiveness never regresses.

## Reuse

- `aughor/explorer/manifest_query.py::cell_to_sql` — extend into `probe_to_sql`
  (it already does headline/dimension/trend aggregation + rate-aware agg).
- `aughor/explorer/coverage_manifest.py` — measure/dimension selection logic
  (`_measures`, `_material_dimensions`) → the enumerated allowed lists.
- `aughor/sql/identifiers.py::unresolved_identifiers` — backstop validation.
- `state["join_verifications"]` — the verified join graph for cross-table compiles.
- Profile metadata (`semantic_type`, `value_range`, `unit`) — aggregate selection.

## Scope

The compiler is the bulk of the work. Two scopes:

- **A — grounded single/co-table compiler (recommended first):** measures + dims +
  filters + having within a table (and co-table pairs the profile already maps).
  Covers the large majority of domain-intel questions and ELIMINATES the
  hallucination class. Free-form stays as a bounded fallback for cross-table
  composites. Build → verify zero-invention on missimi → measure ROI.
- **B — full compiler:** + arbitrary cross-table joins via the verified join graph
  (pre-agg CTEs). Maximal expressiveness, more engineering + risk. Extend to B if the
  fallback rate proves material.

## Success criteria (measured on missimi)

- Invented-identifier drops per run: ~25–40 → **~0**.
- Phase-8 token spend per kept finding: down sharply (the ~40% waste recovered).
- Kept domain findings per run: up → more synthesis pairs + forward-chain drills.
- No regression in finding quality (grain-correct; guards still green).
